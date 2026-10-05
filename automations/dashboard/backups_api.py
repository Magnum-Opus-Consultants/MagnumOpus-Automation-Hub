"""JSON endpoint for the Backups page. The work is in backup_jobs.py."""
import logging

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .views import _require_module

log = logging.getLogger(__name__)


@require_http_methods(["GET"])
def api_backup_jobs(request):
    """Backup timers on every server Sentinel can SSH into, with recent runs."""
    err = _require_module(request, 'servers')
    if err:
        return err
    from . import backup_jobs
    try:
        # ?list=1 answers at once with who will be checked, for the loading state.
        if request.GET.get('list') == '1':
            return JsonResponse(backup_jobs.server_list())
        return JsonResponse(backup_jobs.overview(refresh=request.GET.get('refresh') == '1'))
    except Exception:
        log.exception('Reading backup jobs failed')
        return JsonResponse({'error': 'Could not read the backup jobs.'}, status=500)
