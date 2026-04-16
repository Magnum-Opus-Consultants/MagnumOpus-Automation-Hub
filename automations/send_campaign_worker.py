#!/usr/bin/env python3
"""
Standalone campaign worker — launched as a subprocess by the web UI
so the email campaign survives gunicorn restarts.

Usage:
    python send_campaign_worker.py --tp-num 1 --job-id tp1_1234567890
"""
import os
import sys
import argparse
import time
import json
import base64
import re
import threading
import tempfile
import concurrent.futures

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'automations.settings')
import django
django.setup()

from datetime import datetime
from django.conf import settings as django_settings
import boto3
from botocore.exceptions import ClientError

from dashboard.models import USEUContact, TouchpointTemplate
from dashboard.views import update_touchpoint_progress, _ses_send_mail


def _write_job_file(job_file, data):
    """Atomically write job progress to file."""
    dir_name = os.path.dirname(job_file)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f)
        os.replace(tmp, job_file)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def run_campaign(tp_num, job_id, job_file):
    tp_sent_field = f'tp{tp_num}_sent_on'
    tp_type = f'tp{tp_num}'

    # Find eligible contacts
    filters = {'status': 'Active', tp_sent_field: ''}
    contacts = list(
        USEUContact.objects.filter(**filters)
        .exclude(email='').exclude(email__isnull=True)
    )
    total = len(contacts)
    print(f"[WORKER] TP{tp_num}: {total} eligible contacts", flush=True)

    if not contacts:
        _write_job_file(job_file, {'total': 0, 'sent': 0, 'failed': 0, 'current': '', 'done': True, 'results': []})
        update_touchpoint_progress(tp_type, total=0, sent=0, failed=0, status='idle')
        return

    # Get template
    try:
        template = TouchpointTemplate.objects.get(touchpoint_number=tp_num)
    except TouchpointTemplate.DoesNotExist:
        print(f"[WORKER] Template TP{tp_num} not found", flush=True)
        _write_job_file(job_file, {'total': total, 'sent': 0, 'failed': 0, 'current': 'Error: template not found', 'done': True, 'results': []})
        update_touchpoint_progress(tp_type, status='idle')
        return

    # Seed progress file so the UI can poll immediately
    _write_job_file(job_file, {'total': total, 'sent': 0, 'failed': 0, 'current': '', 'done': False, 'results': []})
    update_touchpoint_progress(tp_type, total=total, sent=0, failed=0, status='sending')

    # Build template body and attachments once (shared across all sends)
    body_content = template.body_html if template.body_html else template.body
    content_type = 'HTML' if template.body_html else 'Text'

    sig_inline = None
    if content_type == 'HTML' and template.signature_image:
        try:
            sig_path = template.signature_image.path
            sig_name = os.path.basename(sig_path)
            ext = os.path.splitext(sig_name)[1].lower().lstrip('.') or 'png'
            cid = f'signature_tp{tp_num}'
            # Rewrite any existing Drive-thumbnail placeholder to our cid
            body_content = re.sub(
                r'https://drive\.google\.com/thumbnail\?id=[^"\'&]+(?:&amp;[^"\']*|&[^"\']*)*',
                f'cid:{cid}',
                body_content,
                flags=re.IGNORECASE,
            )
            with open(sig_path, 'rb') as sf:
                sig_inline = {
                    'name': sig_name,
                    'contentType': f'image/{ext if ext!="jpg" else "jpeg"}',
                    'contentBytes': base64.b64encode(sf.read()).decode('utf-8'),
                    'contentId': cid,
                    'isInline': True,
                }
        except Exception as e:
            print(f'[WORKER] signature_image load failed: {e}', flush=True)

    att_data = None
    if template.attachment:
        try:
            att_path = template.attachment.path
            with open(att_path, 'rb') as f:
                att_bytes = f.read()
            raw_name = os.path.basename(att_path)
            name_part, ext = os.path.splitext(raw_name)
            att_name = name_part.replace('_', ' ').replace('-', ' ')
            att_name = ' '.join(att_name.split()) + ext
            att_data = {
                'name': att_name,
                'contentBytes': base64.b64encode(att_bytes).decode('utf-8'),
            }
        except Exception as e:
            print(f"[WORKER] Attachment error: {e}", flush=True)

    now_str = datetime.now().strftime('%d/%m/%Y')
    _progress_lock = threading.Lock()
    state = {'sent': 0, 'failed': 0}
    DAILY_SEND_LIMIT = 50000  # SES production limit is much higher than Graph
    SES_RATE_LIMIT = 14       # SES default is 14/sec, but we'll be conservative
    _stop_file = os.path.join(project_root, f'send_stop_{job_id}.signal')
    _stopped = {'value': False}

    def _send_one(contact):
        try:
            # ── Stop signal check ──
            if _stopped['value'] or os.path.exists(_stop_file):
                _stopped['value'] = True
                return

            email_addr = contact.email.strip()
            if not email_addr:
                return

            # ── Daily limit check ──
            with _progress_lock:
                if state['sent'] >= DAILY_SEND_LIMIT:
                    print(f"[WORKER] Daily limit of {DAILY_SEND_LIMIT} reached. Stopping.", flush=True)
                    return

            # Pace sends (SES allows ~14/sec but let's be safe)
            time.sleep(0.1)

            with _progress_lock:
                _write_job_file(job_file, {
                    'total': total,
                    'sent': state['sent'],
                    'failed': state['failed'],
                    'current': email_addr,
                    'done': False,
                    'results': [],
                })
            update_touchpoint_progress(tp_type, current_email=email_addr, status='sending')

            final_body = body_content
            final_body = final_body.replace('{{org_name}}', contact.org_name or '')
            final_body = final_body.replace('{{contact_name}}', contact.contact_name or '')
            final_body = final_body.replace('{{email}}', contact.email or '')
            final_body = final_body.replace('{{phone}}', contact.phone or '')
            final_body = final_body.replace('{{touchpoint_number}}', str(tp_num))

            subject = template.subject or ''
            subject = subject.replace('{{org_name}}', contact.org_name or '')
            subject = subject.replace('{{contact_name}}', contact.contact_name or '')

            # Build attachments
            attachments = []
            if att_data:
                attachments.append(att_data)
            if sig_inline:
                attachments.append(sig_inline)

            body_html = final_body if content_type == 'HTML' else None
            body_text = final_body if content_type == 'Text' else None

            print(f"[WORKER] Sending to: {email_addr}", flush=True)
            sent_ok, result_msg = _ses_send_mail(
                to_address=email_addr,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                attachments=attachments if attachments else None,
            )

            with _progress_lock:
                if not sent_ok:
                    state['failed'] += 1
                    error_lower = result_msg.lower()
                    if any(kw in error_lower for kw in [
                        'mailboxdoesnotexist', 'mailbox does not exist',
                        'addressnotverified', 'invalidparametervalue',
                        'messagerejected', 'message rejected',
                        'bounce', 'permanent failure', 'no such user',
                        'recipient address rejected', 'user unknown',
                        'domain not found', 'suppressed', 'blacklisted',
                        'account is in the suppression list',
                    ]):
                        # Mark contact as Undeliverable only — do NOT mark as sent
                        contact.status = 'Undeliverable'
                        contact.save(update_fields=['status'])
                        print(f"[WORKER] Marked {email_addr} as Undeliverable", flush=True)
                    else:
                        print(f"[WORKER] FAILED {email_addr}: {result_msg}", flush=True)
                    update_touchpoint_progress(tp_type, failed=state['failed'], status='sending')
                else:
                    # Only mark as sent after SES confirms delivery
                    state['sent'] += 1
                    setattr(contact, tp_sent_field, now_str)
                    contact.last_touch = str(tp_num)
                    contact.save(update_fields=[tp_sent_field, 'last_touch'])
                    update_touchpoint_progress(tp_type, sent=state['sent'], status='sending')

        except Exception as e:
            print(f"[WORKER] Unhandled exception for {getattr(contact, 'email', '?')}: {e}", flush=True)
            with _progress_lock:
                state['failed'] += 1

    try:
        # Single worker thread to guarantee rate limits are respected
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.map(_send_one, contacts)
    except Exception as e:
        print(f"[WORKER] Executor error: {e}", flush=True)
    finally:
        stopped = _stopped['value']
        _write_job_file(job_file, {
            'total': total,
            'sent': state['sent'],
            'failed': state['failed'],
            'current': 'Stopped by user' if stopped else '',
            'done': True,
            'stopped': stopped,
            'results': [],
        })
        update_touchpoint_progress(tp_type, status='idle')
        # Clean up stop signal file
        try:
            os.unlink(_stop_file)
        except OSError:
            pass
        print(f"[WORKER] {'Stopped by user' if stopped else 'Complete'} — sent: {state['sent']}, failed: {state['failed']}", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tp-num', type=int, required=True)
    parser.add_argument('--job-id', type=str, required=True)
    args = parser.parse_args()

    job_file = os.path.join(project_root, f'send_job_{args.job_id}.json')
    run_campaign(args.tp_num, args.job_id, job_file)
