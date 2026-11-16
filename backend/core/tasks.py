"""Tâches périodiques (Celery beat) et asynchrones."""
import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Max, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from radius.models import Nas, RadAcct, RadPostAuth

from . import services, sms
from .models import AuditLog, OtpCode, Payment, SiteSettings, Subscriber

log = logging.getLogger(__name__)


@shared_task
def send_sms(phone, message):
    try:
        sms.send_now(phone, message)
    except Exception as e:  # le fournisseur peut être indisponible
        log.error('Échec SMS vers %s : %s', phone, e)
        AuditLog.objects.create(actor='sms', action=f'Échec de l\'envoi du SMS vers {phone} : {e}', kind='warn')


@shared_task
def confirm_demo_payment(payment_id):
    with transaction.atomic():
        p = Payment.objects.filter(pk=payment_id, status=Payment.Status.PENDING).first()
        if p:
            services.confirm_payment(p, 'momo-démo', tx=f'DEMO{payment_id:08d}')


@shared_task
def expire_subscribers():
    now = timezone.now()
    n = 0
    for sub in Subscriber.objects.filter(status=Subscriber.Status.ACTIVE, expires_at__lt=now).select_related('plan'):
        with transaction.atomic():
            sub.status = Subscriber.Status.EXPIRED
            sub.save()
        services.disconnect_user(sub.username)
        n += 1
    return n


@shared_task
def refresh_usage():
    """Met à jour la consommation et coupe les comptes dont le volume est épuisé."""
    totals = {r['username']: (r['i'] or 0) + (r['o'] or 0)
              for r in RadAcct.objects.values('username').annotate(i=Sum('acctinputoctets'), o=Sum('acctoutputoctets'))}
    for sub in Subscriber.objects.filter(status=Subscriber.Status.ACTIVE).select_related('plan'):
        used_mb = max(0, totals.get(sub.username, 0) - sub.usage_offset) / services.MB
        if abs(used_mb - sub.used_mb) < 0.01:
            continue
        Subscriber.objects.filter(pk=sub.pk).update(used_mb=used_mb)
        sub.used_mb = used_mb
        if sub.plan.quota and used_mb >= sub.plan.quota:
            with transaction.atomic():
                sub.status = Subscriber.Status.EXPIRED
                sub.save()
            services.disconnect_user(sub.username)
            services.audit('système', f'{sub.username} : volume du forfait épuisé')
        else:
            services.update_quota_reply(sub)


@shared_task
def check_nas():
    """Un routeur est « en ligne » s'il a envoyé de la comptabilité récemment."""
    s = SiteSettings.get()
    limit = timezone.now() - timedelta(seconds=max(3 * s.interim, 600))
    for nas in Nas.objects.all():
        if not services.is_ip(nas.nasname):
            continue
        last = RadAcct.objects.filter(nasipaddress=nas.nasname).aggregate(
            m=Max(Coalesce('acctupdatetime', 'acctstarttime')))['m']
        online = bool(last and last >= limit)
        if nas.online != online or nas.last_seen != last:
            if nas.online and not online:
                services.audit('système', f'Routeur {nas.shortname} : plus de comptabilité depuis {last:%d/%m %H:%M}'
                               if last else f'Routeur {nas.shortname} hors ligne', 'warn')
            Nas.objects.filter(pk=nas.pk).update(online=online, last_seen=last)


@shared_task
def close_stale_sessions():
    """Ferme les sessions dont le routeur n'envoie plus de mises à jour (coupure, redémarrage)."""
    s = SiteSettings.get()
    limit = timezone.now() - timedelta(seconds=max(3 * s.interim, 900))
    stale = RadAcct.objects.filter(acctstoptime__isnull=True).filter(
        Q(acctupdatetime__lt=limit) | Q(acctupdatetime__isnull=True, acctstarttime__lt=limit))
    return stale.update(acctstoptime=Coalesce('acctupdatetime', 'acctstarttime'), acctterminatecause='Stale-Session')


@shared_task
def purge_old_records():
    s = SiteSettings.get()
    limit = timezone.now() - timedelta(days=30 * s.retention_months)
    RadAcct.objects.filter(acctstoptime__lt=limit).delete()
    RadPostAuth.objects.filter(authdate__lt=limit).delete()
    AuditLog.objects.filter(created__lt=limit).delete()
    OtpCode.objects.filter(created__lt=timezone.now() - timedelta(days=2)).delete()
