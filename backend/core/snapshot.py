"""Construit l'état de la console (même forme que l'objet S de index.html)."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone

from radius.models import Nas, RadAcct

from . import roles
from .models import (AuditLog, Complaint, Distributor, Payment, Plan, Reseller, SiteSettings, Subscriber,
                     TopupRequest, Voucher)

MB = 1024 * 1024
SUB_STATUS = {'active': 'actif', 'suspended': 'suspendu', 'expired': 'expiré'}
V_STATUS = {'available': 'disponible', 'sold': 'vendu', 'used': 'utilisé', 'cancelled': 'annulé'}
P_STATUS = {'success': 'réussi', 'pending': 'en attente', 'failed': 'échoué'}
T_STATUS = {'open': 'ouvert', 'in_progress': 'en cours', 'resolved': 'résolu'}
T_PRIO = {'high': 'haute', 'normal': 'normale', 'low': 'basse'}
TOP_STATUS = {'pending': 'en attente', 'approved': 'validée', 'rejected': 'refusée'}
LOGIN_DEFAULTS = [
    ('voucher', 'Ticket / voucher', 'Code imprimé vendu par les revendeurs.', True),
    ('momo', 'Achat Mobile Money', 'M-Pesa, Airtel Money et Orange Money depuis le portail.', True),
    ('free', 'Accès gratuit sponsorisé', 'Temps et volume limités par jour et par appareil.', False),
    ('sms', 'Code SMS (OTP)', 'Code à 6 chiffres envoyé par SMS pour retrouver son forfait.', True),
    ('mac', 'Reconnexion automatique (MAC)', 'Géré par le routeur (MAC authentication).', False),
    ('user', 'Identifiant et mot de passe', 'Pour les abonnés mensuels et les comptes d\'entreprise.', True),
    ('social', 'Google / Facebook', 'Nécessite une application déclarée chez chaque fournisseur.', False),
]


def ms(dt):
    return int(dt.timestamp() * 1000) if dt else None


def login_methods(s):
    saved = s.login_methods if isinstance(s.login_methods, dict) else {}
    return [{'k': k, 'n': n, 'd': d, 'on': bool(saved.get(k, on))} for k, n, d, on in LOGIN_DEFAULTS]


def plan_json(p):
    return {'id': p.id, 'name': p.name, 'price': p.price, 'duration': p.duration, 'quota': p.quota, 'down': p.down,
            'up': p.up, 'shared': p.shared, 'validity': p.validity, 'free': p.is_free}


def voucher_json(v):
    return {'id': v.id, 'code': v.code, 'plan': v.plan_id, 'batch': v.batch.code, 'reseller': v.reseller_id,
            'status': V_STATUS[v.status], 'created': ms(v.created), 'usedAt': ms(v.used_at),
            'soldAt': ms(v.sold_at), 'soldPhone': v.sold_phone}


def reseller_json(r):
    return {'id': r.id, 'name': r.name, 'zone': r.zone, 'phone': r.phone, 'balance': r.balance,
            'commission': r.commission, 'sold': r.sold, 'dist': r.distributor_id}


def topup_json(t):
    return {'id': t.id, 'res': t.reseller_id, 'amount': t.amount, 'date': ms(t.created), 'status': TOP_STATUS[t.status]}


def settings_json(s):
    return {'org': s.org, 'currency': s.currency, 'tz': 'Africa/Kinshasa', 'auth': 1812, 'acct': 1813,
            'interim': s.interim, 'idle': s.idle, 'coa': s.coa_port, 'portalTitle': s.portal_title,
            'portalMsg': s.portal_msg, 'aggregator': s.aggregator, 'callback': '/api/momo/webhook/'}


def build(user):
    s = SiteSettings.get()
    role = roles.role_of(user)
    base = {
        'role': role if role is not None else 0,
        'roles': roles.ROLES,
        'perms': [[label, row] for label, row in zip(roles.PERM_LABELS, roles.matrix())],
        'plans': [plan_json(p) for p in Plan.objects.all()],
        'settings': settings_json(s),
        'login': login_methods(s),
        'free': {'min': s.free_minutes, 'mb': s.free_mb, 'adSec': 10},
        'retention': s.retention_months,
        'me': {'login': user.get_username(), 'name': user.get_full_name() or user.get_username()},
    }

    if role == roles.RESELLER:
        r = getattr(user, 'reseller', None)
        rs = [r] if r else []
        base.update({
            'resellers': [reseller_json(x) for x in rs],
            'distributors': [{'id': d.id, 'name': d.name, 'zone': d.zone, 'phone': '', 'wallet': 0, 'share': d.share}
                             for d in Distributor.objects.filter(resellers__in=rs)],
            'vouchers': [voucher_json(v) for v in Voucher.objects.filter(reseller__in=rs).select_related('batch')[:3000]],
            'topups': [topup_json(t) for t in TopupRequest.objects.filter(reseller__in=rs)[:100]],
            'admins': [], 'audit': [], 'users': [], 'payments': [], 'sessions': [], 'tickets': [],
        })
        return base

    now = timezone.now()
    nas_list = list(Nas.objects.all())
    nas_by_ip = {n.nasname: n for n in nas_list}

    sessions = []
    for a in RadAcct.objects.filter(acctstoptime__isnull=True).order_by('-acctstarttime')[:2000]:
        n = nas_by_ip.get(str(a.nasipaddress))
        sessions.append({'id': a.radacctid, 'user': a.username or '', 'ip': a.framedipaddress or '',
                         'mac': a.callingstationid or '', 'nas': n.shortname if n else str(a.nasipaddress),
                         'start': ms(a.acctstarttime or now), 'inMB': (a.acctoutputoctets or 0) / MB,
                         'outMB': (a.acctinputoctets or 0) / MB})

    users = [{'id': u.id, 'username': u.username, 'password': u.password, 'plan': u.plan_id, 'phone': u.phone,
              'mac': u.mac, 'created': ms(u.created), 'expires': ms(u.expires_at), 'status': SUB_STATUS[u.status],
              'used': round(u.used_mb, 1), 'source': u.get_source_display()}
             for u in Subscriber.objects.all()[:5000]]

    payments = [{'id': p.id, 'ref': p.ref, 'tx': p.provider_tx, 'phone': p.phone, 'op': p.operator, 'plan': p.plan_id,
                 'amount': p.amount, 'status': P_STATUS[p.status], 'date': ms(p.created)}
                for p in Payment.objects.all()[:2000]]

    # Recettes des 14 derniers jours : tickets + espèces (v) et Mobile Money (m)
    start = timezone.localdate() - timedelta(days=13)
    daily = {start + timedelta(days=i): {'v': 0, 'm': 0} for i in range(14)}
    for v in Voucher.objects.filter(status='used', used_at__date__gte=start).select_related('plan'):
        d = timezone.localdate(v.used_at)
        if d in daily:
            daily[d]['v'] += v.plan.price
    for p in Payment.objects.filter(status='success', confirmed_at__date__gte=start):
        d = timezone.localdate(p.confirmed_at)
        if d in daily:
            daily[d]['m' if p.operator in ('M-Pesa', 'Airtel Money', 'Orange Money') else 'v'] += p.amount
    tz = timezone.get_current_timezone()
    daily_list = [{'date': ms(datetime(d.year, d.month, d.day, 12, tzinfo=tz)), **x} for d, x in daily.items()]

    # Fréquentation sur 30 jours, depuis la comptabilité RADIUS
    since = now - timedelta(days=30)
    visits = defaultdict(Counter)
    hours = [0] * 24
    for ip, mac, st in RadAcct.objects.filter(acctstarttime__gte=since).values_list(
            'nasipaddress', 'callingstationid', 'acctstarttime')[:200000]:
        visits[str(ip)][mac or '?'] += 1
        hours[timezone.localtime(st).hour] += 1
    hours = [round(h / 30) for h in hours]

    cdr = [{'start': ms(a.acctstarttime), 'stop': ms(a.acctstoptime), 'user': a.username or '',
            'mac': a.callingstationid or '', 'ip': a.framedipaddress or '',
            'nas': nas_by_ip[str(a.nasipaddress)].shortname if str(a.nasipaddress) in nas_by_ip else str(a.nasipaddress),
            'inMB': round((a.acctoutputoctets or 0) / MB, 1), 'outMB': round((a.acctinputoctets or 0) / MB, 1)}
           for a in RadAcct.objects.filter(acctstoptime__isnull=False).order_by('-acctstarttime')[:500]]

    nas_json = []
    for n in nas_list:
        c = visits.get(n.nasname, Counter())
        total = len(c)
        nas_json.append({'id': n.id, 'name': n.shortname, 'ip': n.nasname, 'type': n.vendor or n.type,
                         'secret': n.secret, 'online': n.online, 'zone': n.zone, 'lastSeen': ms(n.last_seen),
                         'visits': total, 'ret': round(100 * sum(1 for x in c.values() if x > 1) / total) if total else 0})

    User = get_user_model()
    admins = []
    for u in (User.objects.filter(is_staff=True) | User.objects.filter(reseller__isnull=False)).distinct():
        r = roles.role_of(u)
        admins.append({'id': u.id, 'name': u.get_full_name() or u.get_username(), 'login': u.get_username(),
                       'role': roles.ROLES[r] if r is not None else '—', 'last': ms(u.last_login), 'on': u.is_active})

    tickets = []
    for c in Complaint.objects.select_related('assignee').prefetch_related('notes')[:500]:
        tickets.append({'id': c.id, 'ref': c.ref, 'user': c.username, 'phone': c.phone, 'cat': c.category,
                        'prio': T_PRIO[c.priority], 'msg': c.message, 'status': T_STATUS[c.status],
                        'assignee': c.assignee.get_username() if c.assignee else '', 'created': ms(c.created),
                        'resolvedAt': ms(c.resolved_at),
                        'notes': [{'t': ms(n.created), 'who': n.author, 'txt': n.text} for n in c.notes.all()]})

    base.update({
        'users': users,
        'sessions': sessions,
        'vouchers': [voucher_json(v) for v in Voucher.objects.select_related('batch')[:5000]],
        'payments': payments,
        'resellers': [reseller_json(r) for r in Reseller.objects.all()],
        'distributors': [{'id': d.id, 'name': d.name, 'zone': d.zone, 'phone': d.phone, 'wallet': d.wallet,
                          'share': d.share} for d in Distributor.objects.all()],
        'op': {'wallet': s.operator_wallet},
        'nas': nas_json,
        'admins': admins,
        'audit': [{'t': ms(a.created), 'who': a.actor, 'what': a.action, 'kind': a.kind} for a in AuditLog.objects.all()[:300]],
        'tickets': tickets,
        'topups': [topup_json(t) for t in TopupRequest.objects.all()[:200]],
        'daily': daily_list,
        'hours': hours,
        'cdr': cdr,
        'weblog': [],
        'aps': [],
        'rogue': [],
    })
    return base
