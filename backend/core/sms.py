"""Envoi de SMS.

SMS_BACKEND=console  : les SMS sont écrits dans le journal (développement).
SMS_BACKEND=http     : POST JSON vers SMS_API_URL ({"to", "from", "message"}),
                       avec l'en-tête Authorization: Bearer SMS_API_TOKEN.
Adaptez HttpBackend au format de votre fournisseur (Africa's Talking, etc.).
"""
import logging

import requests
from django.conf import settings
from django.db import transaction

log = logging.getLogger(__name__)


def send_now(phone, message):
    backend = settings.SMS_BACKEND
    if backend == 'http':
        r = requests.post(
            settings.SMS_API_URL,
            json={'to': phone, 'from': settings.SMS_SENDER, 'message': message},
            headers={'Authorization': f'Bearer {settings.SMS_API_TOKEN}'},
            timeout=15,
        )
        r.raise_for_status()
        return True
    from .models import AuditLog
    log.info('SMS (console) vers %s : %s', phone, message)
    AuditLog.objects.create(actor='sms', action=f'SMS vers {phone} : {message}')
    return True


def queue(phone, message):
    """Envoie après la validation de la transaction, via Celery si disponible."""
    if not phone:
        return

    def _go():
        from .tasks import send_sms
        send_sms.delay(phone, message)

    transaction.on_commit(_go)
