"""Backup jobs, read from the servers that run them.

Each server backs itself up with a systemd timer - fsa-db-backup and
fsa-media-backup on the FSA production server, moc-db-backup on Server-one -
and the jobs log every file they upload ("OK: rmaa -> Red Meat Abattoir/...
(1.2M)") or fail to. Sentinel already reaches these servers over SSH for live
metrics, using the access stored on each server record, so it asks systemd
directly: which backup timers exist, when they last ran, whether they
succeeded, and what the last fortnight of runs logged.

Everything here is read-only: `systemctl show` and `journalctl`. The jobs'
own config files hold the upload passwords and are never read. Log lines are
masked before they leave this module in case a script ever echoes a secret.
"""
import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from statistics import median
from urllib.parse import quote

from django.core.cache import cache

from .models import ServerRecord

log = logging.getLogger(__name__)

CACHE_SECONDS = 180
# The folder every backup job uploads into, on each company's Nextcloud.
BACKUP_ROOT = 'System Backups'
RUNS_KEPT = 14
LINES_PER_RUN = 80
# Without enough history to measure the schedule, a job is late after this.
DEFAULT_LATE_HOURS = 26

# Every timer with "backup" in its name, except the OS's own dpkg database
# backup and template units (name@.timer), which are not real timers.
REMOTE = r'''
echo "@@TZ $(date +%Z)"
for t in $(systemctl list-unit-files --type=timer --no-legend --no-pager 2>/dev/null | awk '{print $1}' | grep -i backup | grep -v -i -e dpkg -e '@\.'); do
  s=$(systemctl show "$t" -p Unit --value 2>/dev/null)
  [ -n "$s" ] || continue
  echo "@@JOB $t $s"
  systemctl --timestamp=unix show "$t" -p TimersCalendar 2>/dev/null
  systemctl --timestamp=unix show "$s" -p Description,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp,ActiveState 2>/dev/null
  echo "@@LOG"
  journalctl -u "$s" --since "-15 days" -o short-unix --no-hostname --no-pager 2>/dev/null | tail -n 4000
done
echo "@@END"
'''

_LINE = re.compile(r'^(\d+(?:\.\d+)?)\s+([^\s\[:]+)(?:\[\d+\])?:\s?(.*)$')
# The jobs' own log vocabulary:
#   "OK: rmaa -> Red Meat Abattoir/RMAA/.../rmaa.sql.gz (1.2M)"   a database dump
#   "SEND  APS-media-docs.tar.gz.part000 (401M)"                  an archive (part)
#   "DONE  34 file(s)/part(s) uploaded to 2026-10-03"             the run's summary
_ITEM = re.compile(r'^OK:\s*(\S+)\s*->\s*(.+?)\s*\(([^)]*)\)\s*$')
_SEND = re.compile(r'^SEND\s+(\S+?)(\.part\d+)?\s+\(([^)]*)\)\s*$')
_DONE = re.compile(r'^DONE\s+(.+)$')
_ERROR = re.compile(r'^(ERROR|FAIL|FAILED|FATAL)\b', re.I)
_WARNING = re.compile(r'^(WARN|WARNING)\b', re.I)
# A line in the jobs' vocabulary starts with an all-capitals word ("OK:",
# "SEND", "PACK"); anything else straight after a warning is its second line.
_KEYWORD = re.compile(r'^[A-Z][A-Z-]+[:\s]')
# sudo and PAM log into the job's journal whenever a script runs psql as the
# postgres user; that is noise next to what the job itself reports.
_NOISE_IDENTS = {'sudo', 'su', 'CRON'}
_UNITS = {'': 1, 'B': 1, 'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3, 'T': 1024 ** 4}
_SECRETS = [
    (re.compile(r'(://[^:/\s]+:)[^@\s]+@'), r'\1***@'),
    (re.compile(r'(\s-u\s+[^:\s]+:)\S+'), r'\1***'),
    (re.compile(r'((?:password|passwd|pass|token|secret|apikey|api_key)[^=:\s]*\s*[=:]\s*)\S+', re.I), r'\1***'),
]


def _mask(line):
    for pattern, repl in _SECRETS:
        line = pattern.sub(repl, line)
    return line


def _ts(value):
    """systemd's --timestamp=unix values look like "@1790992960"; blank or
    "n/a" means never."""
    m = re.match(r'@(\d+)', (value or '').strip())
    return datetime.fromtimestamp(int(m.group(1)), timezone.utc) if m and int(m.group(1)) > 0 else None


def _iso(dt):
    return dt.isoformat() if dt else None


# How often each kind of schedule runs, for telling when a job is late.
REPEAT_HOURS = {'hourly': 1, 'daily': 24, 'weekly': 24 * 7, 'monthly': 24 * 31}


def _schedule(calendar, tz):
    """Read a timer's OnCalendar into how often it runs.

    '{ OnCalendar=*-*-* 02:00:00 ; next_elapse=@1791079200 }'
      -> {'text': 'Daily 02:00 UTC', 'repeat': 'daily', 'day': None}, next run
    '*-*-02 04:00:00 Africa/Johannesburg' -> monthly on day 2.
    The page shows the time in the reader's own zone from the next run, so
    the text here is only the server's version of it."""
    on = re.search(r'OnCalendar=([^;}]+)', calendar or '')
    nxt = re.search(r'next_elapse=(@\d+)', calendar or '')
    raw = on.group(1).strip() if on else ''
    out = {'text': raw, 'repeat': None, 'day': None}
    m = re.fullmatch(r'(?:([A-Za-z]{3}(?:[.,][A-Za-z.,]*)?)\s+)?(\*|\d{4})-(\*|\d{1,2})-(\*|\d{1,2})'
                     r'\s+(\d{1,2}):(\d{2})(?::\d{2})?(?:\s+(\S+))?', raw)
    if m:
        weekday, _, month, day, hh, mm, zone = m.groups()
        at = f'{int(hh):02d}:{mm} {zone or tz}'.strip()
        if weekday and month == '*' and day == '*':
            out.update(text=f'Weekly on {weekday} {at}', repeat='weekly', day=weekday)
        elif month == '*' and day == '*':
            out.update(text=f'Daily {at}', repeat='daily')
        elif month == '*' and day.isdigit():
            out.update(text=f'Monthly on day {int(day)} {at}', repeat='monthly', day=int(day))
    elif raw.lower() in REPEAT_HOURS:
        out.update(text=raw.capitalize(), repeat=raw.lower())
    return out, _ts(nxt.group(1)) if nxt else None


def _bytes(size):
    """'401M' -> bytes; None if it isn't a size."""
    m = re.fullmatch(r'\s*([\d.]+)\s*([KMGT]?)i?B?\s*', size or '', re.I)
    return float(m.group(1)) * _UNITS[m.group(2).upper()] if m else None


def _size_text(n):
    for unit in ('B', 'K', 'M', 'G', 'T'):
        if n < 1024 or unit == 'T':
            return f'{n:.0f}{unit}' if unit in ('B', 'K') or n >= 100 else f'{n:.1f}{unit}'
        n /= 1024
    return ''


def _archives(sent):
    """Archive parts as sent ("x.tar.gz.part000 (401M)", ...) -> one item per
    archive with its part count and total size."""
    by = {}
    for name, part, size in sent:
        a = by.setdefault(name, {'parts': 0, 'bytes': 0.0, 'sizes_known': True})
        a['parts'] += 1 if part else 0
        b = _bytes(size)
        if b is None:
            a['sizes_known'] = False
        else:
            a['bytes'] += b
    return [{'name': name,
             'dest': f"{a['parts']} parts" if a['parts'] else '',
             'size': _size_text(a['bytes']) if a['sizes_known'] else ''}
            for name, a in by.items()]


def _runs(log_lines):
    """Split a job's journal into runs. systemd logs "Starting <unit>" when a
    run begins and "Finished"/"Failed" when it ends; everything the script
    prints in between belongs to that run."""
    runs, cur = [], None
    for raw in log_lines:
        m = _LINE.match(raw)
        if not m:
            continue
        at = datetime.fromtimestamp(float(m.group(1)), timezone.utc)
        ident, msg = m.group(2), m.group(3).strip()
        if ident in _NOISE_IDENTS or msg.startswith('pam_unix('):
            continue
        if ident == 'systemd':
            if msg.startswith('Starting '):
                cur = {'started': at, 'ended': None, 'ok': None, 'items': [], 'sent': [],
                       'problems': [], 'warnings': [], 'summary': '', 'lines': [], 'last': None}
                runs.append(cur)
            elif cur is not None:
                if 'Failed with result' in msg or msg.startswith('Failed to start') or \
                        re.search(r'status=(?!0/)\d+', msg) or 'code=killed' in msg:
                    cur['ok'] = False
                    cur['ended'] = at
                elif 'Deactivated successfully' in msg or msg.startswith('Finished '):
                    if cur['ok'] is None:
                        cur['ok'] = True
                    cur['ended'] = at
            continue
        if cur is None:
            continue
        msg = _mask(msg)
        cur['lines'].append(msg)
        if item := _ITEM.match(msg):
            cur['items'].append({'name': item.group(1), 'dest': item.group(2), 'size': item.group(3)})
            cur['last'] = None
        elif sent := _SEND.match(msg):
            cur['sent'].append(sent.groups())
            cur['last'] = None
        elif done := _DONE.match(msg):
            cur['summary'] = done.group(1)
            cur['last'] = None
        elif _ERROR.match(msg):
            cur['problems'].append(msg)
            cur['last'] = 'problems'
        elif _WARNING.match(msg):
            cur['warnings'].append(msg)
            cur['last'] = 'warnings'
        elif cur['last'] and not _KEYWORD.match(msg):
            # "Add it to map_folder() so it lands in the right place." -
            # the second line of the warning above it.
            cur[cur['last']][-1] += ' ' + msg
        else:
            cur['last'] = None
    for r in runs:
        r['items'] += _archives(r['sent'])
    return runs


def _status(job, runs):
    if job['active'] in ('activating', 'reloading'):
        return 'running'
    last = runs[-1] if runs else None
    started = (last and last['started']) or job['last_start']
    if not started:
        return 'never'
    if (last and last['ok'] is False) or (not last and job['result'] not in ('', 'success')):
        return 'failed'
    # Late = no run for one and a half of the job's usual gaps (a daily job
    # is late from 36 h), measured from its own history where there is some.
    # Without enough history, the schedule says how often it should run.
    gaps = [(b['started'] - a['started']).total_seconds() / 3600
            for a, b in zip(runs, runs[1:])]
    if len(gaps) >= 2:
        late_after = median(gaps) * 1.5
    else:
        late_after = REPEAT_HOURS.get(job['repeat'], DEFAULT_LATE_HOURS / 1.5) * 1.5
    if (datetime.now(timezone.utc) - started).total_seconds() / 3600 > late_after:
        return 'late'
    if last and last['problems']:
        return 'warn'
    return 'ok'


def nextcloud_sites():
    """The Nextcloud each company's backups go to, from the server inventory:
    {'Food Safety Agency': {'name': 'FSA Nextcloud', 'url': ..., 'netbird': True}, ...}."""
    from .views import SERVER_INVENTORY
    sites = {}
    for s in SERVER_INVENTORY:
        if 'nextcloud' not in (s.get('name') or '').lower() or not s.get('host'):
            continue
        company = s.get('company') or ''
        short = ''.join(w[0] for w in company.split() if w[:1].isupper()) or company
        sites[company] = {
            'name': f'{short} Nextcloud',
            'url': f"https://{s['host']}",
            'folder': f"https://{s['host']}/apps/files/?dir={quote('/' + BACKUP_ROOT)}",
            # Only reachable with NetBird connected.
            'netbird': s['host'].endswith('.netbird.cloud'),
        }
    return sites


def _store_for(description, company, sites):
    """The job names its destination ("... to MOC Nextcloud"); failing that,
    a server backs up to its own company's Nextcloud."""
    for site in sites.values():
        if site['name'].lower() in (description or '').lower():
            return site
    return sites.get(company)


def _item_link(store, dest, company):
    """A database dump's folder in Nextcloud. The jobs write dumps under
    "System Backups/Databases/" and log the path below that. MOC's job logs
    it from the company folder down; FSA's starts at the year, without the
    system folder it chose, so its link opens the company's folder."""
    if not store or not re.search(r'\.(sql(\.gz)?|dump)$', dest or '', re.I):
        return None
    parts = dest.strip('/').split('/')[:-1]
    if parts and re.fullmatch(r'20\d\d', parts[0]):
        parts = [company] if company else []
    folder = '/'.join([BACKUP_ROOT, 'Databases'] + parts)
    return f"{store['url']}/apps/files/?dir={quote('/' + folder)}"


def _parse(stdout, company='', sites=None):
    sites = sites or {}
    tz, jobs, cur, section = '', [], None, None
    for line in stdout.splitlines():
        if line.startswith('@@TZ'):
            tz = line[4:].strip()
        elif line.startswith('@@JOB'):
            parts = line.split()
            cur = {'timer': parts[1] if len(parts) > 1 else '', 'service': parts[2] if len(parts) > 2 else '',
                   'props': {}, 'log': []}
            jobs.append(cur)
            section = 'props'
        elif line.startswith('@@LOG'):
            section = 'log'
        elif line.startswith('@@END'):
            section = None
        elif cur is not None and section == 'props' and '=' in line:
            k, v = line.split('=', 1)
            cur['props'][k] = v
        elif cur is not None and section == 'log':
            cur['log'].append(line)

    out = []
    for j in jobs:
        p = j['props']
        schedule, next_at = _schedule(p.get('TimersCalendar', ''), tz)
        job = {
            'timer': j['timer'], 'service': j['service'],
            'description': p.get('Description') or j['service'],
            'schedule': schedule['text'], 'repeat': schedule['repeat'], 'day': schedule['day'],
            'next_at': next_at,
            'last_start': _ts(p.get('ExecMainStartTimestamp')),
            'last_exit': _ts(p.get('ExecMainExitTimestamp')),
            'result': p.get('Result', ''), 'active': p.get('ActiveState', ''),
        }
        runs = _runs(j['log'])
        job['status'] = _status(job, runs)
        store = _store_for(job['description'], company, sites)
        job['store'] = store
        job['runs'] = [{
            'started': _iso(r['started']), 'ended': _iso(r['ended']), 'ok': r['ok'],
            'seconds': round((r['ended'] - r['started']).total_seconds()) if r['ended'] else None,
            'items': [{**i, 'link': _item_link(store, i['dest'], company)} for i in r['items']],
            'problems': r['problems'][:20], 'warnings': r['warnings'][:20], 'summary': r['summary'],
            'lines': r['lines'][-LINES_PER_RUN:],
        } for r in reversed(runs[-RUNS_KEPT:])]
        for k in ('next_at', 'last_start', 'last_exit'):
            job[k] = _iso(job[k])
        out.append(job)
    return out


def _targets():
    """Servers to ask: every server record with SSH access, plus the known
    servers in views.SSH_CONF that have no record yet (a fresh database has
    none until someone adds them on the Servers page)."""
    from .views import SERVER_INVENTORY, SSH_CONF
    targets, seen = [], set()
    for r in ServerRecord.objects.order_by('name'):
        if r.ssh_user and r.ssh_ip and r.ssh_key:
            targets.append({'id': r.pk, 'name': r.name, 'company': r.company or '',
                            'user': r.ssh_user, 'ip': r.ssh_ip, 'key': r.ssh_key})
            seen.add(r.ssh_ip)
    inventory = {s['hostname'].lower(): s for s in SERVER_INVENTORY if s.get('hostname')}
    for host, c in SSH_CONF.items():
        if c['ip'] in seen:
            continue
        inv = inventory.get(host.lower(), {})
        targets.append({'id': None, 'name': inv.get('name', host), 'company': inv.get('company', ''),
                        'user': c['user'], 'ip': c['ip'], 'key': c['key']})
    return targets


def _ssh(t, remote, timeout=45):
    ssh_bin = r'C:\Program Files\Git\usr\bin\ssh.exe'
    if not os.path.exists(ssh_bin):
        ssh_bin = 'ssh'
    ssh_dir = os.path.join(os.path.expanduser('~'), '.ssh')
    key = os.path.join(ssh_dir, t['key'])
    if not os.path.exists(key):
        # The server's own key isn't on this machine; try the machine's main
        # key instead, which is authorised on most of the servers.
        key = os.path.join(ssh_dir, 'id_ed25519')
        if not os.path.exists(key):
            return None, f"The SSH key {t['key']} is not on the machine running Sentinel."
    try:
        p = subprocess.run(
            [ssh_bin, '-i', key, '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
             '-o', 'ConnectTimeout=8', '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
             f"{t['user']}@{t['ip']}", remote],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, 'The server took too long to answer over SSH.'
    except OSError:
        return None, 'SSH is not available on the machine running Sentinel.'
    if '@@END' not in p.stdout:
        return None, 'Could not sign in over SSH (the server refused the key or is unreachable).'
    return p.stdout, None


def _server(t, refresh):
    key = f"backups:jobs:{t['user']}@{t['ip']}"
    if not refresh and (hit := cache.get(key)):
        return hit
    base = {'id': t['id'], 'name': t['name'], 'company': t['company'], 'address': t['ip']}
    stdout, problem = _ssh(t, REMOTE)
    if problem:
        # Not cached: an unreachable server should be retried on the next load.
        return {**base, 'reachable': False, 'detail': problem, 'jobs': []}
    out = {**base, 'reachable': True, 'detail': '', 'jobs': _parse(stdout, t['company'], nextcloud_sites())}
    cache.set(key, out, CACHE_SECONDS)
    return out


def server_list():
    """The servers that will be checked, without connecting to any - so the
    page can show who it is waiting for while the SSH checks run."""
    return {'servers': [{'name': t['name'], 'company': t['company'], 'address': t['ip']}
                        for t in _targets()]}


def overview(refresh=False):
    """Every server Sentinel can SSH into, with its backup jobs."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        servers = list(pool.map(lambda t: _server(t, refresh), _targets()))
    # Servers with jobs first, then the ones with none, then the unreachable.
    servers.sort(key=lambda s: (not s['reachable'], not s['jobs'], s['name'].lower()))
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'servers': servers,
            'nextcloud': list(nextcloud_sites().values())}
