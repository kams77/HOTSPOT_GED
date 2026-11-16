"""API JSON utilisée par la console (session Django + jeton CSRF).

Toutes les actions sont en POST et répondent {"ok": true, ...} ou
{"error": "message lisible"} avec un code HTTP 4xx.
"""
import json
from datetime import timedelta
from functools import wraps

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from radius.models import Nas, RadAcct

from . import momo, roles, services, sms, snapshot
from .models import (AccessPoint, Ad, Batch, Campaign, Complaint, Distributor, Payment, Plan, Policy, Reseller,
                     SiteSettings, Subscriber, TopupRequest, Voucher)
from .services import ServiceError, actor_of, audit, to_int

T_STATUS_IN = {v: k for k, v in snapshot.T_STATUS.items()}
T_PRIO_IN = {v: k for k, v in snapshot.T_PRIO.items()}


def endpoint(perm=None, methods=('POST',)):
    def deco(fn):
        @wraps(fn)
        def view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({'error': 'Session expirée : reconnectez-vous.', 'login': True}, status=401)
            if request.method not in methods:
                return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)
            if roles.role_of(request.user) is None:
                return JsonResponse({'error': "Votre compte n'a aucun rôle. Demandez un rôle à l'administrateur."}, status=403)
            if perm is not None and not roles.can(request.user, perm):
                return JsonResponse({'error': 'Votre rôle ne permet pas cette action.'}, status=403)
            try:
                data = json.loads(request.body or b'{}') if request.method == 'POST' else {}
            except ValueError:
                return JsonResponse({'error': 'Requête invalide.'}, status=400)
            try:
                with transaction.atomic():
                    result = fn(request, data, *args, **kwargs)
            except ServiceError as e:
                return JsonResponse({'error': str(e)}, status=400)
            except ObjectDoesNotExist:
                return JsonResponse({'error': "Élément introuvable : il a peut-être été supprimé."}, status=404)
            return JsonResponse({'ok': True, **(result or {})})
        return view
    return deco


def me(request):
    return actor_of(request.user)


def get_plan(data, key='plan'):
    p = Plan.objects.filter(pk=data.get(key)).first()
    if p is None:
        raise ServiceError('Choisissez un forfait.')
    return p


# ---------------------------------------------------------------- état
@endpoint(methods=('GET',))
def state(request, data):
    return snapshot.build(request.user)


# ---------------------------------------------------------------- utilisateurs
@endpoint(roles.USERS)
def subscriber_create(request, data):
    sub = services.create_subscriber(get_plan(data), Subscriber.Source.MANUAL, me(request),
                                     username=data.get('username'), password=data.get('password'),
                                     phone=data.get('phone', ''), mac=data.get('mac', ''))
    return {'id': sub.id, 'message': f'Compte {sub.username} créé'}


@endpoint(roles.USERS)
def subscriber_bulk(request, data):
    plan = get_plan(data)
    n = to_int(data.get('n'), 'Nombre de comptes', 1, 500)
    prefix = str(data.get('pre') or 'compte-')[:12]
    for _ in range(n):
        services.create_subscriber(plan, Subscriber.Source.MANUAL, me(request),
                                   username=services.unique_username(prefix))
    return {'message': f'{n} comptes créés'}


@endpoint(roles.USERS)
def subscriber_update(request, data, pk):
    sub = Subscriber.objects.select_for_update().get(pk=pk)
    if data.get('password'):
        sub.password = str(data['password'])[:64]
    if data.get('plan'):
        sub.plan = get_plan(data)
    sub.phone = services.normalize_phone(data.get('phone', sub.phone), required=False)
    sub.mac = services.normalize_mac(data.get('mac', ''))
    extend = to_int(data.get('extend') or 0, 'Prolongation', 0, 3650)
    if extend:
        sub.expires_at = max(sub.expires_at, timezone.now()) + timedelta(days=extend)
        if sub.status == Subscriber.Status.EXPIRED:
            sub.status = Subscriber.Status.ACTIVE
    if data.get('reset'):
        total_bytes, _ = services.usage_totals(sub.username)
        sub.usage_offset, sub.used_mb = total_bytes, 0
    sub.save()
    audit(me(request), f'Utilisateur {sub.username} modifié')
    return {'message': 'Modifications enregistrées'}


@endpoint(roles.USERS)
def subscriber_toggle(request, data, pk):
    sub = Subscriber.objects.select_for_update().get(pk=pk)
    if sub.status == Subscriber.Status.SUSPENDED:
        new = Subscriber.Status.EXPIRED if sub.expires_at < timezone.now() else Subscriber.Status.ACTIVE
    else:
        new = Subscriber.Status.SUSPENDED
    services.set_status(sub, new, me(request))
    return {'message': f'{sub.username} : {sub.get_status_display().lower()}'}


@endpoint(roles.USERS)
def subscriber_delete(request, data, pk):
    sub = Subscriber.objects.get(pk=pk)
    services.disconnect_user(sub.username)
    name = sub.username
    sub.delete()
    audit(me(request), f'Utilisateur {name} supprimé', 'warn')
    return {'message': 'Compte supprimé'}


@endpoint(roles.USERS)
def subscriber_renew(request, data, pk):
    sub = Subscriber.objects.select_for_update().get(pk=pk)
    services.renew_subscriber(sub, get_plan(data), me(request), pay=data.get('pay') or 'Espèces')
    return {'message': f'{sub.username} renouvelé jusqu\'au {timezone.localtime(sub.expires_at):%d/%m %H:%M}'}


@endpoint(roles.USERS)
def subscriber_password(request, data, pk):
    sub = Subscriber.objects.get(pk=pk)
    sub.password = services.gen_password()
    sub.save()
    audit(me(request), f'Mot de passe de {sub.username} réinitialisé')
    return {'message': f'Nouveau mot de passe : {sub.password}'}


@endpoint(roles.USERS)
def subscriber_unbind(request, data, pk):
    sub = Subscriber.objects.get(pk=pk)
    sub.mac = ''
    sub.save()
    audit(me(request), f'MAC déliée pour {sub.username}')
    return {'message': 'Adresse MAC déliée'}


@endpoint(roles.SESSIONS)
def subscriber_disconnect(request, data, pk):
    sub = Subscriber.objects.get(pk=pk)
    n = services.disconnect_user(sub.username)
    audit(me(request), f'{n} session(s) de {sub.username} déconnectée(s)')
    return {'message': f'{n} session(s) fermée(s)' if n else 'Aucune session fermée : le routeur n\'a pas confirmé.'}


@endpoint(roles.USERS)
def subscriber_send(request, data, pk):
    sub = Subscriber.objects.get(pk=pk)
    services.send_credentials(sub)
    return {'message': f'Identifiants envoyés par SMS au {sub.phone}'}


# ---------------------------------------------------------------- sessions
@endpoint(roles.SESSIONS)
def session_disconnect(request, data, pk):
    acct = RadAcct.objects.get(pk=pk)
    ok = services.disconnect_session(acct)
    audit(me(request), f'Session {acct.username} : Disconnect-Request {"accepté" if ok else "refusé"}')
    if not ok:
        raise ServiceError('Le routeur a refusé la déconnexion. Vérifiez le port CoA et le secret partagé.')
    return {'message': f'{acct.username} déconnecté'}


@endpoint(roles.SESSIONS)
def sessions_disconnect_nas(request, data):
    nas = Nas.objects.filter(shortname=data.get('nas')).first()
    if nas is None:
        raise ServiceError('Choisissez un routeur.')
    n = 0
    for acct in RadAcct.objects.filter(acctstoptime__isnull=True, nasipaddress=nas.nasname):
        n += int(services.disconnect_session(acct))
    audit(me(request), f'{n} session(s) déconnectée(s) sur {nas.shortname}', 'warn')
    return {'message': f'{n} session(s) fermée(s) sur {nas.shortname}'}


# ---------------------------------------------------------------- forfaits
PLAN_FIELDS = [('price', 'Prix', 0), ('duration', 'Durée', 1), ('validity', 'Validité', 1), ('quota', 'Volume', 0),
               ('down', 'Débit descendant', 64), ('up', 'Débit montant', 64), ('shared', 'Appareils simultanés', 1)]


def fill_plan(plan, data):
    name = str(data.get('name', '')).strip()
    if not name:
        raise ServiceError('Donnez un nom au forfait.')
    plan.name = name[:80]
    for field, label, minimum in PLAN_FIELDS:
        setattr(plan, field, to_int(data.get(field), label, minimum))
    plan.save()
    return plan


@endpoint(roles.PLANS)
def plan_create(request, data):
    p = fill_plan(Plan(), data)
    audit(me(request), f'Forfait « {p.name} » créé à {p.price} FC')
    return {'message': 'Forfait créé'}


@endpoint(roles.PLANS)
def plan_update(request, data, pk):
    p = Plan.objects.get(pk=pk)
    old = p.price
    fill_plan(p, data)
    audit(me(request), f'Forfait « {p.name} » modifié' + (f' : {old} → {p.price} FC' if old != p.price else ''))
    return {'message': 'Forfait mis à jour'}


@endpoint(roles.PLANS)
def plan_delete(request, data, pk):
    p = Plan.objects.get(pk=pk)
    if p.subscribers.exists() or p.vouchers.exists() or p.payments.exists():
        p.active = False
        p.save()
        audit(me(request), f'Forfait « {p.name} » retiré de la vente (historique conservé)', 'warn')
        return {'message': 'Forfait retiré de la vente : des comptes ou tickets l\'utilisent encore.'}
    name = p.name
    p.delete()
    audit(me(request), f'Forfait « {name} » supprimé', 'warn')
    return {'message': 'Forfait supprimé'}


# ---------------------------------------------------------------- tickets
@endpoint(roles.VOUCHERS)
def batch_create(request, data):
    reseller = Reseller.objects.filter(pk=data.get('res')).first() if data.get('res') else None
    b = services.generate_batch(get_plan(data), data.get('n'), request.user, data.get('len') or 8, reseller)
    return {'batch': b.code, 'message': f'Lot {b.code} créé'}


@endpoint(roles.VOUCHERS)
def batch_cancel(request, data):
    b = Batch.objects.get(code=data.get('batch'))
    n = b.vouchers.filter(status=Voucher.Status.AVAILABLE).update(status=Voucher.Status.CANCELLED)
    audit(me(request), f'Lot {b.code} : {n} tickets annulés', 'warn')
    return {'message': f'{n} tickets annulés'}


@endpoint(roles.VOUCHERS)
def voucher_cancel(request, data, pk):
    v = Voucher.objects.get(pk=pk)
    if v.status != Voucher.Status.AVAILABLE:
        raise ServiceError('Seul un ticket disponible peut être annulé.')
    v.status = Voucher.Status.CANCELLED
    v.save()
    audit(me(request), f'Ticket {v.code} annulé', 'warn')
    return {'message': 'Ticket annulé'}


def reseller_for(request, data):
    if roles.role_of(request.user) == roles.RESELLER:
        r = getattr(request.user, 'reseller', None)
        if r is None:
            raise ServiceError("Votre compte n'est lié à aucun point de vente.")
        return r
    return Reseller.objects.get(pk=data.get('reseller'))


@endpoint(roles.POS)
def pos_sell(request, data):
    r = reseller_for(request, data)
    v = services.sell_voucher(r, get_plan(data), data.get('phone', ''), me(request))
    p = v.plan
    return {'code': v.code, 'price': p.price, 'plan': p.name, 'phone': v.sold_phone,
            'info': f'{p.duration} min · {"illimité" if not p.quota else str(p.quota) + " Mo"} · valable {p.validity} j'}


@endpoint(roles.POS)
def topup_create(request, data):
    r = reseller_for(request, data)
    t = TopupRequest.objects.create(reseller=r, amount=to_int(data.get('a'), 'Montant', 500))
    audit(me(request), f'{r.name} demande une recharge de {t.amount} FC')
    return {'message': f'Demande envoyée à {r.distributor.name if r.distributor else "l’opérateur"}'}


@endpoint(roles.FINANCE)
def topup_approve(request, data, pk):
    services.decide_topup(TopupRequest.objects.select_related('reseller').get(pk=pk), True, request.user)
    return {'message': 'Recharge validée'}


@endpoint(roles.FINANCE)
def topup_reject(request, data, pk):
    services.decide_topup(TopupRequest.objects.select_related('reseller').get(pk=pk), False, request.user)
    return {'message': 'Demande refusée'}


# ---------------------------------------------------------------- paiements
@endpoint(roles.MOMO)
def payment_approve(request, data, pk):
    p = Payment.objects.get(pk=pk)
    sub = services.confirm_payment(p, me(request))
    return {'message': f'Paiement validé, compte {sub.username} activé'}


@endpoint(roles.MOMO)
def payment_reject(request, data, pk):
    services.fail_payment(Payment.objects.get(pk=pk), me(request))
    return {'message': 'Paiement rejeté'}


@endpoint(roles.MOMO)
def payment_manual(request, data):
    plan = get_plan(data)
    op = data.get('op')
    if op not in momo.OPERATORS:
        raise ServiceError('Choisissez un opérateur.')
    tx = str(data.get('tx', '')).strip()
    if not tx:
        raise ServiceError("Saisissez l'identifiant de transaction de l'opérateur.")
    if Payment.objects.filter(provider_tx=tx, operator=op).exists():
        raise ServiceError('Cette transaction est déjà enregistrée.')
    p = Payment.objects.create(ref=services.next_payment_ref(), provider_tx=tx, phone=services.normalize_phone(data.get('phone')),
                               operator=op, plan=plan, amount=plan.price, source='console')
    sub = services.confirm_payment(p, me(request), tx=tx)
    return {'message': f'Paiement enregistré, compte {sub.username} actif'}


# ---------------------------------------------------------------- distribution
@endpoint(roles.FINANCE)
def reseller_create(request, data):
    name = str(data.get('name', '')).strip()
    if not name:
        raise ServiceError('Donnez un nom au point de vente.')
    dist = Distributor.objects.filter(pk=data.get('dist')).first()
    Reseller.objects.create(name=name, zone=data.get('zone', ''), phone=data.get('phone', ''), distributor=dist,
                            commission=to_int(data.get('com', 10), 'Commission', 0, 50))
    audit(me(request), f'Revendeur {name} ajouté')
    return {'message': 'Revendeur ajouté. Créez son compte de connexion dans l’administration.'}


@endpoint(roles.FINANCE)
def reseller_topup(request, data, pk):
    r = Reseller.objects.get(pk=pk)
    services.topup_reseller(r, data.get('a'), me(request), f'({data.get("m", "espèces")})')
    return {'message': f'{r.name} rechargé'}


@endpoint(roles.FINANCE)
def reseller_assign(request, data, pk):
    r = Reseller.objects.get(pk=pk)
    b = services.generate_batch(get_plan(data), data.get('n'), request.user, 8, r)
    return {'message': f'{b.vouchers.count()} tickets attribués à {r.name} (lot {b.code})'}


@endpoint(roles.FINANCE)
def distributor_create(request, data):
    name = str(data.get('name', '')).strip()
    if not name:
        raise ServiceError('Donnez un nom au distributeur.')
    Distributor.objects.create(name=name, zone=data.get('zone', ''), phone=data.get('phone', ''),
                               share=to_int(data.get('share', 12), 'Part', 0, 40))
    audit(me(request), f'Distributeur {name} ajouté')
    return {'message': 'Distributeur ajouté'}


@endpoint(roles.FINANCE)
def distributor_credit(request, data, pk):
    d = Distributor.objects.get(pk=pk)
    services.credit_distributor(d, data.get('a'), data.get('ref', ''), me(request))
    return {'message': f'{d.name} crédité'}


# ---------------------------------------------------------------- routeurs
@endpoint(roles.NAS)
def nas_create(request, data):
    ip = str(data.get('ip', '')).strip()
    if not services.is_ip(ip):
        raise ServiceError('Adresse IP invalide.')
    if Nas.objects.filter(nasname=ip).exists():
        raise ServiceError('Un routeur utilise déjà cette adresse.')
    secret = str(data.get('secret', '')).strip()
    if len(secret) < 8:
        raise ServiceError('Le secret partagé doit faire au moins 8 caractères.')
    name = str(data.get('name', '')).strip() or ip
    Nas.objects.create(nasname=ip, shortname=name, secret=secret, vendor=data.get('type', ''), zone=data.get('zone', ''))
    audit(me(request), f'Routeur {name} ({ip}) ajouté')
    return {'message': 'Routeur ajouté. Redémarrez le service radius pour qu’il soit pris en compte.'}


@endpoint(roles.NAS)
def nas_delete(request, data, pk):
    n = Nas.objects.get(pk=pk)
    n.delete()
    audit(me(request), f'Routeur {n.shortname} retiré', 'warn')
    return {'message': 'Routeur retiré. Redémarrez le service radius.'}


@endpoint(roles.NAS)
def nas_test(request, data, pk):
    n = Nas.objects.get(pk=pk)
    last = n.last_seen
    if n.online and last:
        return {'message': f'{n.shortname} envoie de la comptabilité (dernière : {timezone.localtime(last):%d/%m %H:%M})'}
    return {'message': f'{n.shortname} : aucune comptabilité récente. Vérifiez l’IP, le secret et les ports 1812/1813.'}


# ---------------------------------------------------------------- réclamations
@endpoint(roles.COMPLAINTS)
def complaint_create(request, data):
    username = str(data.get('user', '')).strip()
    msg = str(data.get('msg', '')).strip()
    if not username or not msg:
        raise ServiceError('Indiquez le client et décrivez le problème.')
    sub = Subscriber.objects.filter(username=username).first()
    c = Complaint.objects.create(ref=services.next_complaint_ref(), username=username, subscriber=sub,
                                 phone=sub.phone if sub else '', category=data.get('tcat', 'Autre'),
                                 priority=T_PRIO_IN.get(data.get('tprio'), 'normal'), message=msg)
    audit(me(request), f'Réclamation {c.ref} ouverte pour {username}')
    return {'message': f'Réclamation {c.ref} créée'}


@endpoint(roles.COMPLAINTS)
def complaint_update(request, data, pk):
    c = Complaint.objects.select_for_update().get(pk=pk)
    c.status = T_STATUS_IN.get(data.get('tstatus'), c.status)
    assignee = get_user_model().objects.filter(username=data.get('tassignee')).first()
    if assignee:
        c.assignee = assignee
    c.resolved_at = (c.resolved_at or timezone.now()) if c.status == Complaint.Status.RESOLVED else None
    c.save()
    services.add_note(c, me(request), str(data.get('note', '')))
    if data.get('comp') and c.subscriber:
        sub = c.subscriber
        sub.expires_at = max(sub.expires_at, timezone.now()) + timedelta(days=1)
        if sub.status == Subscriber.Status.EXPIRED:
            sub.status = Subscriber.Status.ACTIVE
        sub.save()
        services.add_note(c, me(request), '1 jour de compensation offert.')
    audit(me(request), f'Réclamation {c.ref} : {c.get_status_display().lower()}')
    return {'message': f'{c.ref} mise à jour'}


# ---------------------------------------------------------------- paramètres
@endpoint(roles.SETTINGS)
def settings_update(request, data):
    s = SiteSettings.get()
    text = {'org': 'org', 'currency': 'currency', 'aggregator': 'aggregator', 'portalTitle': 'portal_title',
            'portalMsg': 'portal_msg'}
    for key, field in text.items():
        if key in data:
            setattr(s, field, str(data[key])[:200])
    nums = {'interim': ('interim', 60, 3600), 'idle': ('idle', 60, 86400), 'coa': ('coa_port', 1, 65535),
            'retention': ('retention_months', 1, 120)}
    resync = False
    for key, (field, lo, hi) in nums.items():
        if key in data:
            value = to_int(data[key], key, lo, hi)
            resync |= field in ('interim', 'idle') and getattr(s, field) != value
            setattr(s, field, value)
    if isinstance(data.get('login'), dict):
        methods = dict(s.login_methods or {})
        methods.update({k: bool(v) for k, v in data['login'].items()})
        s.login_methods = methods
    s.save()
    if resync:
        for p in Plan.objects.all():
            services.sync_plan(p)
    audit(me(request), 'Paramètres modifiés')
    return {'message': 'Paramètres enregistrés'}


@endpoint(roles.SETTINGS)
def perms_update(request, data):
    i = to_int(data.get('i'), 'Permission', 0, len(roles.PERM_LABELS) - 1)
    j = to_int(data.get('j'), 'Rôle', 1, len(roles.ROLES) - 1)
    s = SiteSettings.get()
    m = roles.matrix()
    m[i][j] = 1 if data.get('on') else 0
    s.perms = m
    s.save(update_fields=['perms'])
    audit(me(request), f'Permission « {roles.PERM_LABELS[i]} » {"accordée" if data.get("on") else "retirée"} : {roles.ROLES[j]}')
    return {'message': 'Permission mise à jour'}


@endpoint(roles.SETTINGS)
def admin_toggle(request, data, pk):
    u = get_object_or_404(get_user_model(), pk=pk)
    if u == request.user or u.is_superuser:
        raise ServiceError('Ce compte ne peut pas être désactivé ici.')
    u.is_active = not u.is_active
    u.save(update_fields=['is_active'])
    audit(me(request), f'Administrateur {u.get_username()} {"réactivé" if u.is_active else "désactivé"}', 'warn')
    return {'message': 'Compte mis à jour'}


# ---------------------------------------------------------------- publicité et campagnes
@endpoint(roles.MARKETING)
def ad_create(request, data):
    name = str(data.get('name', '')).strip()
    if not name:
        raise ServiceError("Donnez un titre à l'annonce.")
    days = to_int(data.get('days', 14), 'Durée', 1, 365)
    Ad.objects.create(name=name[:120], sponsor=str(data.get('sponsor', ''))[:120], kind=str(data.get('type', 'Image'))[:30],
                      slot=str(data.get('slot', 'Avant connexion'))[:60], ends_at=timezone.now() + timedelta(days=days))
    audit(me(request), f'Publicité « {name} » créée')
    return {'message': 'Publicité en ligne'}


@endpoint(roles.MARKETING)
def ad_toggle(request, data, pk):
    ad = Ad.objects.get(pk=pk)
    ad.active = bool(data.get('on'))
    ad.save(update_fields=['active'])
    audit(me(request), f'Publicité « {ad.name} » {"activée" if ad.active else "suspendue"}')
    return {'message': 'Publicité activée' if ad.active else 'Publicité suspendue'}


SEGMENTS = {
    'exp': 'Forfait expirant dans 24 h',
    'old': 'Comptes expirés',
    'momo': 'Clients Mobile Money',
    'all': 'Tous les clients avec téléphone',
}


def segment_phones(key):
    qs = Subscriber.objects.exclude(phone='')
    now = timezone.now()
    if key == 'exp':
        qs = qs.filter(status=Subscriber.Status.ACTIVE, expires_at__lt=now + timedelta(days=1))
    elif key == 'old':
        qs = qs.filter(status=Subscriber.Status.EXPIRED)
    elif key == 'momo':
        qs = qs.filter(source=Subscriber.Source.MOMO)
    return sorted(set(qs.values_list('phone', flat=True)))[:5000]


@endpoint(roles.MARKETING)
def campaign_create(request, data):
    key = data.get('seg')
    if key not in SEGMENTS:
        raise ServiceError('Choisissez une cible.')
    msg = str(data.get('msg', '')).strip()
    if not msg or len(msg) > 160:
        raise ServiceError('Le message doit faire entre 1 et 160 caractères.')
    phones = segment_phones(key)
    for phone in phones:
        sms.queue(phone, msg)
    Campaign.objects.create(name=str(data.get('name', 'Campagne'))[:120], segment=SEGMENTS[key], message=msg, sent=len(phones))
    audit(me(request), f'Campagne SMS envoyée à {len(phones)} numéro(s) : {SEGMENTS[key]}')
    return {'message': f'{len(phones)} SMS envoyés'}


# ---------------------------------------------------------------- politiques et filtrage
@endpoint(roles.NAS)
def policy_create(request, data):
    name = str(data.get('name', '')).strip()
    rule = str(data.get('rule', '')).strip()
    if not name or not rule:
        raise ServiceError('Indiquez le nom et l’effet de la règle.')
    Policy.objects.create(name=name[:120], scope=str(data.get('scope', 'Tous les forfaits'))[:120], rule=rule)
    audit(me(request), f'Règle « {name} » créée')
    return {'message': 'Règle créée'}


@endpoint(roles.NAS)
def policy_toggle(request, data, pk):
    p = Policy.objects.get(pk=pk)
    p.active = bool(data.get('on'))
    p.save(update_fields=['active'])
    audit(me(request), f'Règle « {p.name} » {"activée" if p.active else "désactivée"}')
    return {'message': 'Règle activée' if p.active else 'Règle désactivée'}


@endpoint(roles.NAS)
def filter_toggle(request, data):
    i = to_int(data.get('i'), 'Catégorie', 0, len(snapshot.WEB_FILTERS) - 1)
    name = snapshot.WEB_FILTERS[i]
    s = SiteSettings.get()
    current = dict(s.web_filters or {})
    current[name] = bool(data.get('on'))
    s.web_filters = current
    s.save(update_fields=['web_filters'])
    audit(me(request), f'Filtrage « {name} » {"activé" if current[name] else "désactivé"}')
    return {'message': 'Filtrage mis à jour'}


@endpoint(roles.NAS)
def ap_reboot(request, data, pk):
    ap = AccessPoint.objects.get(pk=pk)
    audit(me(request), f'Redémarrage demandé pour {ap.name}')
    return {'message': f'Demande notée. Redémarrez {ap.name} depuis le contrôleur du constructeur (UniFi, Omada…).'}


# ---------------------------------------------------------------- webhook Mobile Money
@csrf_exempt
@require_POST
def momo_webhook(request):
    if not momo.verify_signature(request.body, request.headers.get('X-Signature')):
        return JsonResponse({'error': 'signature invalide'}, status=403)
    try:
        event = momo.parse_webhook(request.body)
    except ValueError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    with transaction.atomic():
        p = Payment.objects.select_for_update().filter(ref=event['reference']).first()
        if p is None:
            return JsonResponse({'error': 'référence inconnue'}, status=404)
        p.raw = event['raw']
        p.save(update_fields=['raw'])
        if event['success']:
            services.confirm_payment(p, 'momo', tx=event['transaction_id'])
        elif event['failed'] and p.status == Payment.Status.PENDING:
            services.fail_payment(p, 'momo')
    return JsonResponse({'ok': True})
