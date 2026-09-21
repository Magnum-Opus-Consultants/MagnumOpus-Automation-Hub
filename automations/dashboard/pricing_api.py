"""The Pricing Report API: read the report, and load a new workbook into it.

Reading is one endpoint that returns every section against one filter set, so
the quote half and the income half of the page can never end up scoped to
different periods.

Uploading is deliberately separate and deliberately slow-path: the workbook is
over 20 MB and takes the better part of a minute to read, so it is a POST that
returns a summary of what landed, not something the page does on a timer.
"""
import logging
import os
import tempfile

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from . import pricing_report
from .models import PricingImport
from .views import _require_module

logger = logging.getLogger(__name__)

# Read from the same grant as the rest of the analysis work, so existing access
# applies without a new permission to hand out.
MODULE = 'data'

# Anything larger is not a pricing export; the biggest real one so far is 22 MB.
MAX_UPLOAD = 120 * 1024 * 1024

FILTER_KEYS = ('year', 'branch', 'mode', 'direction')


@require_http_methods(["GET"])
def api_pricing_report(request):
    """Every section of the report, against one filter set."""
    err = _require_module(request, MODULE)
    if err:
        return err
    filters = {k: (request.GET.get(k) or '').strip() for k in FILTER_KEYS}
    filters['unique_only'] = request.GET.get('unique_only') in ('1', 'true')
    data = pricing_report.report(filters)
    data['imports'] = [{
        'id': i.id,
        'filename': i.filename,
        'loaded_at': i.loaded_at.isoformat(),
        'rows': i.total_rows,
        'is_active': i.is_active,
    } for i in PricingImport.objects.all()[:12]]
    return JsonResponse(data)


@require_http_methods(["POST"])
def api_pricing_upload(request):
    """Take a new workbook and make it the report's source.

    Written to a temporary file rather than held in memory: Django would spool
    a 22 MB upload to disk anyway, and openpyxl needs a path it can stream.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    f = request.FILES.get('file')
    if not f:
        return JsonResponse({'detail': 'No file was sent.'}, status=400)
    if not f.name.lower().endswith(('.xlsx', '.xlsm')):
        return JsonResponse(
            {'detail': 'The pricing report has to be an .xlsx workbook.'},
            status=400)
    if f.size > MAX_UPLOAD:
        return JsonResponse(
            {'detail': f'{f.size / 1_048_576:.0f} MB is larger than this '
                       'report should ever be; check the file.'}, status=400)

    tmp = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
    try:
        for chunk in f.chunks():
            tmp.write(chunk)
        tmp.close()
        # The real filename, not the temp one, is what gets recorded.
        imp = pricing_report.load(
            tmp.name,
            user=request.user if request.user.is_authenticated else None)
        imp.filename = f.name
        imp.save(update_fields=['filename'])
    except KeyError as exc:
        logger.warning('[pricing] upload rejected: %s', exc)
        return JsonResponse(
            {'detail': f'That workbook has no sheet called '
                       f'{pricing_report.SHEET}.'}, status=400)
    except Exception as exc:                       # noqa: BLE001 - reported up
        logger.exception('[pricing] upload failed')
        return JsonResponse({'detail': f'Could not read the workbook: {exc}'},
                            status=400)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    return JsonResponse({
        'ok': True,
        'filename': imp.filename,
        'quote_rows': imp.quote_rows,
        'turnover_rows': imp.turnover_rows,
        'skipped_rows': imp.skipped_rows,
        'notes': imp.notes,
    })


@require_http_methods(["POST"])
def api_pricing_activate(request, pk):
    """Point the report back at an earlier load."""
    err = _require_module(request, MODULE)
    if err:
        return err
    try:
        imp = PricingImport.objects.get(pk=pk)
    except PricingImport.DoesNotExist:
        return JsonResponse({'detail': 'No such import.'}, status=404)
    PricingImport.objects.filter(is_active=True).update(is_active=False)
    imp.is_active = True
    imp.save(update_fields=['is_active'])
    return JsonResponse({'ok': True, 'filename': imp.filename})
