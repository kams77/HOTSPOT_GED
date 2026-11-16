"""Mobile Money (M-Pesa, Airtel Money, Orange Money) via un agrégateur.

MOMO_PROVIDER=demo : le paiement est confirmé automatiquement après quelques
                     secondes. Pour tester sans opérateur.
MOMO_PROVIDER=http : POST JSON vers MOMO_API_URL pour déclencher la demande
                     de paiement sur le téléphone du client. L'agrégateur
                     confirme ensuite en appelant /api/momo/webhook/.

Webhook attendu (JSON) :
    {"reference": "PAY-...", "status": "SUCCESS" | "FAILED", "transaction_id": "..."}
avec l'en-tête X-Signature = HMAC-SHA256(corps brut, MOMO_WEBHOOK_SECRET) en hexadécimal.
Adaptez HttpProvider et parse_webhook au format exact de votre agrégateur.
"""
import hashlib
import hmac
import json

import requests
from django.conf import settings

OPERATORS = ['M-Pesa', 'Airtel Money', 'Orange Money']


class DemoProvider:
    def request(self, payment):
        from .tasks import confirm_demo_payment
        confirm_demo_payment.apply_async((payment.pk,), countdown=4)


class HttpProvider:
    def request(self, payment):
        r = requests.post(
            settings.MOMO_API_URL,
            json={
                'reference': payment.ref,
                'amount': payment.amount,
                'currency': 'CDF',
                'phone': payment.phone,
                'operator': payment.operator,
                'callback_url': f'{settings.PUBLIC_URL.rstrip("/")}/api/momo/webhook/',
            },
            headers={'Authorization': f'Bearer {settings.MOMO_API_KEY}'},
            timeout=20,
        )
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            data = {}
        if data.get('transaction_id'):
            payment.provider_tx = str(data['transaction_id'])[:80]
            payment.save(update_fields=['provider_tx'])


def get_provider():
    return HttpProvider() if settings.MOMO_PROVIDER == 'http' else DemoProvider()


def verify_signature(raw_body, signature):
    secret = settings.MOMO_WEBHOOK_SECRET
    if not secret:
        return settings.DEBUG  # en développement seulement
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature or '').strip().lower())


def parse_webhook(raw_body):
    data = json.loads(raw_body or b'{}')
    status = str(data.get('status', '')).upper()
    return {
        'reference': str(data.get('reference', '')),
        'success': status in ('SUCCESS', 'SUCCESSFUL', 'COMPLETED', 'PAID'),
        'failed': status in ('FAILED', 'CANCELLED', 'REJECTED', 'EXPIRED'),
        'transaction_id': str(data.get('transaction_id', ''))[:80],
        'raw': data,
    }
