"""Logique métier : synchronisation RADIUS, tickets, paiements, revendeurs."""
import hashlib
import ipaddress
import logging
import re
import secrets
import subprocess
from datetime import timedelta, timezone as dt_tz

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from radius.models import Nas, RadAcct, RadCheck, RadGroupCheck, RadGroupReply, RadReply, RadUserGroup

from . import sms
from .models import (AuditLog, Batch, Complaint, ComplaintNote, Distributor, OtpCode, Payment, Plan, Reseller,
                     SiteSettings, Subscriber, TopupRequest, Voucher)

log = logging.getLogger(__name__)
MB = 1024 * 1024
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # sans 0, O, 1, I
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


class ServiceError(Exception):
    """Erreur métier dont le message s'affiche tel quel à l'utilisateur."""


# ---------------------------------------------------------------- utilitaires
def audit(actor, action, kind='info'):
    AuditLog.objects.create(actor=str(actor)[:80], action=action, kind=kind)


def actor_of(user):
    return user.get_username() if user is not None and user.is_authenticated else 'système'


def gen_code(n=8):
    return ''.join(secrets.choice(ALPHABET) for _ in range(n))


def gen_password():
    return str(secrets.randbelow(900000) + 100000)


def normalize_mac(mac):
    h = re.sub(r'[^0-9A-Fa-f]', '', mac or '').upper()
    return ':'.join(h[i:i + 2] for i in range(0, 12, 2)) if len(h) == 12 else ''


def normalize_phone(phone, required=True):
    d = re.sub(r'\D', '', phone or '')
    if len(d) < 9:
        if not required and not d:
            return ''
        raise ServiceError('Numéro incomplet : saisissez les 9 chiffres après +243.')
    d = d[-9:]
    return f'+243 {d[:2]} {d[2:5]} {d[5:]}'


def phone_key(phone):
    return re.sub(r'\D', '', phone or '')[-9:]


def mac_regex(mac):
    def hx(c):
        return f'[{c}{c.lower()}]' if c.isalpha() else c
    parts = normalize_mac(mac).split(':')
    return '^' + '[-:.]?'.join(''.join(hx(c) for c in p) for p in parts) + '$'


def radius_date(dt):
    dt = dt.astimezone(dt_tz.utc)
    return f'{dt.day:02d} {MONTHS[dt.month - 1]} {dt.year} {dt:%H:%M:%S}'


def is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def to_int(value, label, minimum=None, maximum=None):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise ServiceError(f'{label} : saisissez un nombre entier.')
    if minimum is not None and n < minimum:
        raise ServiceError(f'{label} : minimum {minimum}.')
    if maximum is not None and n > maximum:
        raise ServiceError(f'{label} : maximum {maximum}.')
    return n


# ---------------------------------------------------------------- RADIUS
def sync_plan(plan):
    s = SiteSettings.get()
    g = plan.group
    RadGroupCheck.objects.filter(groupname=g).delete()
    RadGroupReply.objects.filter(groupname=g).delete()
    checks = [('Simultaneous-Use', ':=', str(plan.shared))]
    if plan.login_time:
        checks.append(('Login-Time', ':=', plan.login_time))
    replies = [
        ('Acct-Interim-Interval', ':=', str(s.interim)),
        ('Idle-Timeout', ':=', str(s.idle)),
        ('WISPr-Bandwidth-Max-Down', ':=', str(plan.down * 1000)),
        ('WISPr-Bandwidth-Max-Up', ':=', str(plan.up * 1000)),
        ('Mikrotik-Rate-Limit', ':=', f'{plan.up}k/{plan.down}k'),
    ]
    RadGroupCheck.objects.bulk_create([RadGroupCheck(groupname=g, attribute=a, op=o, value=v) for a, o, v in checks])
    RadGroupReply.objects.bulk_create([RadGroupReply(groupname=g, attribute=a, op=o, value=v) for a, o, v in replies])


def drop_plan(plan_pk):
    g = f'plan-{plan_pk}'
    RadGroupCheck.objects.filter(groupname=g).delete()
    RadGroupReply.objects.filter(groupname=g).delete()


def usage_totals(username):
    a = RadAcct.objects.filter(username=username).aggregate(
        i=Sum('acctinputoctets'), o=Sum('acctoutputoctets'), t=Sum('acctsessiontime'))
    return (a['i'] or 0) + (a['o'] or 0), a['t'] or 0


def update_quota_reply(sub):
    RadReply.objects.filter(username=sub.username, attribute__startswith='ChilliSpot-Max-Total').delete()
    if sub.plan.quota:
        remaining = max(0, sub.plan.quota * MB - int(sub.used_mb * MB))
        # Attribut 32 bits : au-delà de 4 Go par session, la tâche refresh_usage coupe au quota global.
        RadReply.objects.create(username=sub.username, attribute='ChilliSpot-Max-Total-Octets', op=':=',
                                value=str(min(remaining, 0xFFFFFFFF)))


def sync_subscriber(sub):
    u = sub.username
    drop_subscriber(u)
    checks = []
    if sub.password:
        checks.append(('Cleartext-Password', ':=', sub.password))
    checks.append(('Expiration', ':=', radius_date(sub.expires_at)))
    # Temps cumulé autorisé : vérifié par le module noresetcounter (sqlcounter).
    checks.append(('Max-All-Session', ':=', str(sub.plan.duration * 60 + sub.time_offset)))
    if sub.mac:
        checks.append(('Calling-Station-Id', '=~', mac_regex(sub.mac)))
    if sub.status != Subscriber.Status.ACTIVE:
        checks.append(('Auth-Type', ':=', 'Reject'))
    RadCheck.objects.bulk_create([RadCheck(username=u, attribute=a, op=o, value=v) for a, o, v in checks])
    RadUserGroup.objects.create(username=u, groupname=sub.plan.group, priority=1)
    update_quota_reply(sub)


def drop_subscriber(username):
    RadCheck.objects.filter(username=username).delete()
    RadReply.objects.filter(username=username).delete()
    RadUserGroup.objects.filter(username=username).delete()


def open_sessions(username=None):
    qs = RadAcct.objects.filter(acctstoptime__isnull=True)
    return qs.filter(username=username) if username else qs


def disconnect_session(acct):
    """Envoie un Disconnect-Request (RFC 5176) au routeur. Retourne True si accepté."""
    ip = str(acct.nasipaddress)
    nas = Nas.objects.filter(nasname=ip).first()
    if nas is None:
        raise ServiceError(f'Aucun routeur enregistré avec l\'adresse {ip}.')
    attrs = [f'User-Name = "{acct.username}"', f'Acct-Session-Id = "{acct.acctsessionid}"']
    if acct.framedipaddress:
        attrs.append(f'Framed-IP-Address = {acct.framedipaddress}')
    port = SiteSettings.get().coa_port
    try:
        r = subprocess.run([settings.RADCLIENT_BIN, '-r', '1', '-t', '3', f'{nas.nasname}:{port}', 'disconnect', nas.secret],
                           input='\n'.join(attrs) + '\n', text=True, capture_output=True, timeout=12)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ServiceError(f'Envoi du Disconnect-Request impossible : {e}')
    ok = r.returncode == 0 and 'NAK' not in r.stdout
    if ok:
        RadAcct.objects.filter(pk=acct.pk).update(acctstoptime=timezone.now(), acctterminatecause='Admin-Reset')
    else:
        log.warning('Disconnect refusé par %s : %s %s', ip, r.stdout, r.stderr)
    return ok


def disconnect_user(username):
    ok = 0
    for acct in open_sessions(username):
        try:
            ok += int(disconnect_session(acct))
        except ServiceError as e:
            log.warning('%s', e)
    return ok


# ---------------------------------------------------------------- utilisateurs
def unique_username(prefix=''):
    for _ in range(50):
        name = f'{prefix}{gen_code(6).lower()}'
        if not Subscriber.objects.filter(username=name).exists():
            return name
    raise ServiceError('Impossible de générer un nom unique, réessayez.')


def create_subscriber(plan, source, actor, username=None, password=None, phone='', mac='', reseller=None):
    username = (username or unique_username()).strip()
    if not re.fullmatch(r'[A-Za-z0-9._@+-]{3,64}', username):
        raise ServiceError("Nom d'utilisateur : 3 à 64 caractères, lettres, chiffres, . _ - @ +")
    if Subscriber.objects.filter(username=username).exists():
        raise ServiceError("Ce nom d'utilisateur existe déjà. Choisissez-en un autre.")
    sub = Subscriber.objects.create(
        username=username, password=password or gen_password(), plan=plan,
        phone=normalize_phone(phone, required=False), mac=normalize_mac(mac), source=source,
        expires_at=timezone.now() + timedelta(days=plan.validity), reseller=reseller)
    audit(actor, f'Utilisateur {username} créé ({plan.name})')
    return sub


def renew_subscriber(sub, plan, actor, pay=None):
    total_bytes, total_time = usage_totals(sub.username)
    now = timezone.now()
    remaining = 0
    if sub.status == Subscriber.Status.ACTIVE and sub.expires_at > now:
        remaining = max(0, sub.plan.duration * 60 + sub.time_offset - total_time)
        base = sub.expires_at
    else:
        base = now
    sub.plan = plan
    sub.expires_at = base + timedelta(days=plan.validity)
    sub.usage_offset = total_bytes
    sub.time_offset = total_time + remaining
    sub.used_mb = 0
    sub.status = Subscriber.Status.ACTIVE
    sub.save()
    if pay and pay != 'Offert':
        Payment.objects.create(
            ref=next_payment_ref(), phone=sub.phone or '—', operator=pay, plan=plan, amount=plan.price,
            status=Payment.Status.SUCCESS, source='renewal', confirmed_at=now, subscriber=sub)
    audit(actor, f'{sub.username} renouvelé : {plan.name} ({pay or "sans encaissement"})')
    return sub


def set_status(sub, status, actor):
    sub.status = status
    sub.save()
    if status != Subscriber.Status.ACTIVE:
        disconnect_user(sub.username)
    audit(actor, f'Utilisateur {sub.username} : {sub.get_status_display().lower()}',
          'warn' if status != Subscriber.Status.ACTIVE else 'info')


def send_credentials(sub):
    if not sub.phone:
        raise ServiceError("Ce compte n'a pas de numéro de téléphone.")
    s = SiteSettings.get()
    sms.queue(sub.phone, f'{s.portal_title} : identifiant {sub.username}, mot de passe {sub.password}, '
                         f'forfait {sub.plan.name}, valable jusqu\'au {timezone.localtime(sub.expires_at):%d/%m %H:%M}.')


# ---------------------------------------------------------------- tickets
def generate_batch(plan, qty, actor_user, length=8, reseller=None):
    qty = to_int(qty, 'Quantité', 1, 1000)
    length = to_int(length, 'Longueur du code', 6, 12)
    if reseller is not None:
        reseller = Reseller.objects.select_for_update().get(pk=reseller.pk)
        cost = round(qty * plan.price * (1 - reseller.commission / 100))
        if cost > reseller.balance:
            raise ServiceError(f'Solde insuffisant : il faut {cost:,} FC, le revendeur a {reseller.balance:,} FC.'.replace(',', ' '))
        reseller.balance -= cost
        reseller.save(update_fields=['balance'])
    today = timezone.localdate()
    n = Batch.objects.filter(created__date=today).count() + 1
    code = f'B-{today:%y%m%d}-{n:02d}'
    while Batch.objects.filter(code=code).exists():
        n += 1
        code = f'B-{today:%y%m%d}-{n:02d}'
    batch = Batch.objects.create(code=code, plan=plan, reseller=reseller, created_by=actor_user)
    codes = set()
    while len(codes) < qty:
        wanted = {gen_code(length) for _ in range(qty - len(codes))}
        taken = set(Voucher.objects.filter(code__in=wanted).values_list('code', flat=True))
        codes |= wanted - taken
    Voucher.objects.bulk_create([Voucher(code=c, plan=plan, batch=batch, reseller=reseller) for c in codes])
    audit(actor_of(actor_user), f'Lot {code} généré : {qty} tickets « {plan.name} »'
          + (f' pour {reseller.name}' if reseller else ''))
    return batch


def redeem_voucher(code, mac=''):
    code = re.sub(r'[^A-Za-z0-9]', '', code or '').upper()
    v = (Voucher.objects.select_for_update(of=('self',)).select_related('plan', 'subscriber')
         .filter(code=code).first())
    if v is None:
        raise ServiceError('Code introuvable. Vérifiez les caractères imprimés sur votre ticket.')
    if v.status == Voucher.Status.CANCELLED:
        raise ServiceError('Ce ticket a été annulé. Adressez-vous au point de vente.')
    if v.status == Voucher.Status.USED:
        if v.subscriber and v.subscriber.status == Subscriber.Status.ACTIVE:
            return v.subscriber  # reconnexion avec le même code
        raise ServiceError('Ce ticket a déjà été utilisé et son forfait est terminé.')
    sub = create_subscriber(v.plan, Subscriber.Source.VOUCHER, 'portail', username=code, password=code,
                            reseller=v.reseller)
    v.status = Voucher.Status.USED
    v.used_at = timezone.now()
    v.subscriber = sub
    v.save()
    return sub


def sell_voucher(reseller, plan, phone, actor):
    phone = normalize_phone(phone, required=False)
    v = (Voucher.objects.select_for_update()
         .filter(reseller=reseller, plan=plan, status=Voucher.Status.AVAILABLE).order_by('created').first())
    if v is None:
        raise ServiceError('Plus de stock pour ce forfait. Demandez un lot à votre distributeur.')
    v.status = Voucher.Status.SOLD
    v.sold_at = timezone.now()
    v.sold_phone = phone
    v.save()
    Reseller.objects.filter(pk=reseller.pk).update(sold=F('sold') + 1)
    if phone:
        sms.queue(phone, f'Votre code Wi-Fi : {v.code[:4]}-{v.code[4:]} ({plan.name}). Saisissez-le sur la page de connexion.')
    audit(actor, f'{reseller.name} a vendu le ticket {v.code} ({plan.name})')
    return v


# ---------------------------------------------------------------- paiements
def next_payment_ref():
    return f'PAY-{timezone.now():%y%m%d}-{secrets.token_hex(3).upper()}'


def initiate_payment(plan, operator, phone):
    from . import momo
    if operator not in momo.OPERATORS:
        raise ServiceError('Choisissez un opérateur Mobile Money.')
    p = Payment.objects.create(ref=next_payment_ref(), phone=normalize_phone(phone), operator=operator,
                               plan=plan, amount=plan.price, source='portal')
    transaction.on_commit(lambda: momo.get_provider().request(p))
    return p


def confirm_payment(p, actor, tx=''):
    p = Payment.objects.select_for_update().get(pk=p.pk)
    if p.status == Payment.Status.SUCCESS:
        return p.subscriber
    username = phone_key(p.phone)
    sub = Subscriber.objects.filter(username=username).first()
    if sub:
        renew_subscriber(sub, p.plan, actor)
    else:
        sub = create_subscriber(p.plan, Subscriber.Source.MOMO, actor, username=username, phone=p.phone)
    p.status = Payment.Status.SUCCESS
    p.confirmed_at = timezone.now()
    p.subscriber = sub
    if tx:
        p.provider_tx = tx
    p.save()
    send_credentials(sub)
    audit(actor, f'Paiement {p.ref} confirmé ({p.operator}, {p.amount} FC), compte {sub.username}')
    return sub


def fail_payment(p, actor):
    if p.status == Payment.Status.SUCCESS:
        raise ServiceError('Ce paiement est déjà confirmé.')
    p.status = Payment.Status.FAILED
    p.save(update_fields=['status'])
    audit(actor, f'Paiement {p.ref} rejeté', 'warn')


# ---------------------------------------------------------------- distribution
def credit_distributor(dist, amount, ref, actor):
    amount = to_int(amount, 'Montant', 1)
    s = SiteSettings.objects.select_for_update().get(pk=SiteSettings.get().pk)
    if amount > s.operator_wallet:
        raise ServiceError(f'Portefeuille opérateur insuffisant : {s.operator_wallet} FC disponibles.')
    s.operator_wallet -= amount
    s.save(update_fields=['operator_wallet'])
    Distributor.objects.filter(pk=dist.pk).update(wallet=F('wallet') + amount)
    audit(actor, f'{dist.name} crédité de {amount} FC (réf. {ref})')


def topup_reseller(reseller, amount, actor, method=''):
    amount = to_int(amount, 'Montant', 1)
    if reseller.distributor_id:
        src = Distributor.objects.select_for_update().get(pk=reseller.distributor_id)
        label = src.name
        if amount > src.wallet:
            raise ServiceError(f'Portefeuille de {label} insuffisant : {src.wallet} FC disponibles.')
        src.wallet -= amount
        src.save(update_fields=['wallet'])
    else:
        src = SiteSettings.objects.select_for_update().get(pk=SiteSettings.get().pk)
        label = 'opérateur'
        if amount > src.operator_wallet:
            raise ServiceError(f'Portefeuille opérateur insuffisant : {src.operator_wallet} FC disponibles.')
        src.operator_wallet -= amount
        src.save(update_fields=['operator_wallet'])
    Reseller.objects.filter(pk=reseller.pk).update(balance=F('balance') + amount)
    audit(actor, f'Recharge {reseller.name} : +{amount} FC {method} depuis {label}'.strip())


def decide_topup(t, approve, user):
    if t.status != TopupRequest.Status.PENDING:
        raise ServiceError('Cette demande a déjà été traitée.')
    if approve:
        topup_reseller(t.reseller, t.amount, actor_of(user), '(demande)')
    t.status = TopupRequest.Status.APPROVED if approve else TopupRequest.Status.REJECTED
    t.decided_at = timezone.now()
    t.decided_by = user
    t.save()
    if not approve:
        audit(actor_of(user), f'Demande de recharge de {t.reseller.name} ({t.amount} FC) refusée', 'warn')


# ---------------------------------------------------------------- réclamations
def next_complaint_ref():
    last = Complaint.objects.order_by('-id').values_list('ref', flat=True).first()
    try:
        n = int(last.split('-')[1]) + 1 if last else 1001
    except (IndexError, ValueError):
        n = Complaint.objects.count() + 1001
    return f'REC-{n}'


def add_note(c, author, text):
    if text.strip():
        ComplaintNote.objects.create(complaint=c, author=author, text=text.strip())


# ---------------------------------------------------------------- portail : SMS et accès gratuit
def _otp_hash(phone, code):
    return hashlib.sha256(f'{phone_key(phone)}:{code}:{settings.SECRET_KEY}'.encode()).hexdigest()


def create_otp(phone):
    phone = normalize_phone(phone)
    since = timezone.now() - timedelta(minutes=15)
    if OtpCode.objects.filter(phone=phone, created__gte=since).count() >= 3:
        raise ServiceError('Trop de demandes de code. Réessayez dans 15 minutes.')
    code = f'{secrets.randbelow(1000000):06d}'
    OtpCode.objects.create(phone=phone, code_hash=_otp_hash(phone, code), expires_at=timezone.now() + timedelta(minutes=5))
    sms.queue(phone, f'Votre code de connexion Wi-Fi : {code}. Il expire dans 5 minutes.')
    return phone


def verify_otp(phone, code):
    phone = normalize_phone(phone)
    otp = OtpCode.objects.filter(phone=phone, used=False, expires_at__gt=timezone.now()).order_by('-created').first()
    if otp is None:
        raise ServiceError('Code expiré. Demandez un nouveau code.')
    if otp.attempts >= 5:
        raise ServiceError('Trop d\'essais. Demandez un nouveau code.')
    if otp.code_hash != _otp_hash(phone, (code or '').strip()):
        otp.attempts += 1
        otp.save(update_fields=['attempts'])
        raise ServiceError('Code incorrect. Vérifiez le SMS reçu.')
    otp.used = True
    otp.save(update_fields=['used'])
    return Subscriber.objects.filter(phone=phone, status=Subscriber.Status.ACTIVE).order_by('-expires_at').first()


def free_access(mac):
    mac = normalize_mac(mac)
    if not mac:
        raise ServiceError("L'accès gratuit nécessite l'adresse de votre appareil. Reconnectez-vous au Wi-Fi.")
    plan = Plan.objects.filter(is_free=True, active=True).first()
    if plan is None:
        raise ServiceError("L'accès gratuit n'est pas proposé pour le moment.")
    username = 'free-' + mac.replace(':', '').lower()
    sub = Subscriber.objects.filter(username=username).first()
    if sub and timezone.localdate(sub.created) == timezone.localdate():
        if sub.status != Subscriber.Status.ACTIVE:
            raise ServiceError("Vous avez déjà utilisé l'accès gratuit aujourd'hui. Revenez demain ou achetez un forfait.")
        return sub
    if sub:
        sub.delete()
    sub = create_subscriber(plan, Subscriber.Source.FREE, 'portail', username=username, mac=mac)
    sub.expires_at = timezone.now() + timedelta(days=1)
    sub.save()
    return sub
