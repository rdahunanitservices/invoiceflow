import logging

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def healthz(request):
    """Liveness and database check for uptime monitors. Never returns error
    details to the caller; they go to the log instead."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        logger.exception("Health check could not reach the database")
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})
