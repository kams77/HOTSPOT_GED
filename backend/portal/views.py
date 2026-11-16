"""Portail captif : page que voient les clients en se connectant au Wi-Fi.

Le routeur redirige vers /portal/ en ajoutant ses paramètres. Indiquez-les
dans la configuration du routeur, par exemple pour MikroTik :
    /portal/?preset=mikrotik&login_url=$(link-login-only)&mac=$(mac)&dst=$(link-orig)
pfSense : /portal/?preset=pfsense&login_url=$PORTAL_ACTION$&redirurl=$PORTAL_REDIRURL$
Générique : login_url = URL où envoyer username/password en POST.
"""
from urllib.parse import urlparse

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core import services, snapshot
from django.db.models import F, Q
from django.utils import timezone

from core.models import Ad, Payment, Plan, SiteSettings
from core.momo import OPERATORS
from core.services import ServiceError

PRESETS = {
    'mikrotik': ('username', 'password', 'dst'),
    'pfsense': ('auth_user', 'auth_pass', 'redirurl'),
    'generic': ('username', 'password', 'dst'),
}


def ctx_from(request):
    return request.session.get('portal', {})


def methods():
    return {m['k']: m['on'] for m in snapshot.login_methods(SiteSettings.get())}


def pick_ad(*slots):
    ad = (Ad.objects.filter(active=True, slot__in=slots)
          .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=timezone.now())).order_by('?').first())
    if ad:
        Ad.objects.filter(pk=ad.pk).update(impressions=F('impressions') + 1)
    return ad


def base_context(request, **extra):
    s = SiteSettings.get()
    return {
        's': s,
        'plans': Plan.objects.filter(active=True, is_free=False),
        'free_plan': Plan.objects.filter(active=True, is_free=True).first(),
        'operators': OPERATORS,
        'on': methods(),
        'tab': request.GET.get('tab') or extra.pop('tab', None) or 'code',
        'ad': None,
        **extra,
    }


def login_form(request, sub):
    c = ctx_from(request)
    url = c.get('login_url', '')
    if urlparse(url).scheme not in ('http', 'https'):
        return None
    user_f, pass_f, dst_f = PRESETS.get(c.get('preset'), PRESETS['generic'])
    fields = [(user_f, sub.username), (pass_f, sub.password)]
    if c.get('dst'):
        fields.append((dst_f, c['dst']))
    if c.get('preset') == 'pfsense':
        fields.append(('accept', 'Continue'))
    return {'url': url, 'fields': fields}


def success(request, sub, message='Vous êtes connecté.'):
    return render(request, 'portal/index.html', base_context(
        request, mode='success', sub=sub, message=message, login=login_form(request, sub),
        ad=pick_ad('Après connexion')))


def error(request, message, tab):
    return render(request, 'portal/index.html', base_context(request, error=message, tab=tab), status=400)


def index(request):
    keep = ('login_url', 'preset', 'mac', 'ip', 'dst', 'redirurl')
    params = {k: request.GET.get(k, '') for k in keep if request.GET.get(k)}
    if params:
        if params.get('redirurl') and not params.get('dst'):
            params['dst'] = params['redirurl']
        request.session['portal'] = params
    ctx = base_context(request)
    if ctx['tab'] == 'free':
        ctx['ad'] = pick_ad('Accès gratuit (avant)')
    elif ctx['tab'] == 'code':
        ctx['ad'] = pick_ad('Avant connexion')
    return render(request, 'portal/index.html', ctx)


@require_POST
def voucher(request):
    if not methods().get('voucher'):
        return error(request, 'La connexion par ticket est désactivée.', 'code')
    try:
        with transaction.atomic():
            sub = services.redeem_voucher(request.POST.get('code', ''), ctx_from(request).get('mac', ''))
    except ServiceError as e:
        return error(request, str(e), 'code')
    return success(request, sub)


@require_POST
def login_user(request):
    from core.models import Subscriber
    sub = Subscriber.objects.filter(username=request.POST.get('username', '').strip(),
                                    password=request.POST.get('password', '')).first()
    if sub is None:
        return error(request, 'Identifiant ou mot de passe incorrect.', 'user')
    if sub.status != Subscriber.Status.ACTIVE:
        return error(request, f'Ce compte est {sub.get_status_display().lower()}. Renouvelez votre forfait.', 'user')
    return success(request, sub, 'Bienvenue.')


@require_POST
def momo_start(request):
    if not methods().get('momo'):
        return error(request, 'Le paiement Mobile Money est désactivé.', 'momo')
    plan = Plan.objects.filter(pk=request.POST.get('plan'), active=True, is_free=False).first()
    if plan is None:
        return error(request, 'Choisissez un forfait.', 'momo')
    try:
        with transaction.atomic():
            p = services.initiate_payment(plan, request.POST.get('op', ''), request.POST.get('phone', ''))
    except ServiceError as e:
        return error(request, str(e), 'momo')
    except Exception:
        return error(request, 'Le service de paiement ne répond pas. Réessayez dans un instant.', 'momo')
    request.session.setdefault('payments', [])
    request.session['payments'] = request.session['payments'][-9:] + [p.ref]
    return redirect('portal:momo_wait', ref=p.ref)


def momo_wait(request, ref):
    if ref not in request.session.get('payments', []):
        return redirect('portal:index')
    p = Payment.objects.filter(ref=ref).select_related('subscriber', 'plan').first()
    if p and p.status == Payment.Status.SUCCESS and p.subscriber:
        return success(request, p.subscriber, f'Paiement de {p.amount} FC reçu.')
    if p is None or p.status == Payment.Status.FAILED:
        return error(request, 'Le paiement a échoué ou a été annulé. Vous n’avez pas été débité.', 'momo')
    return render(request, 'portal/index.html', base_context(request, mode='wait', payment=p))


def momo_status(request, ref):
    if ref not in request.session.get('payments', []):
        return JsonResponse({'status': 'unknown'}, status=404)
    p = Payment.objects.filter(ref=ref).first()
    return JsonResponse({'status': p.status if p else 'unknown'})


@require_POST
def sms_send(request):
    if not methods().get('sms'):
        return error(request, 'La connexion par SMS est désactivée.', 'sms')
    try:
        with transaction.atomic():
            phone = services.create_otp(request.POST.get('phone', ''))
    except ServiceError as e:
        return error(request, str(e), 'sms')
    request.session['otp_phone'] = phone
    return render(request, 'portal/index.html', base_context(request, mode='otp', phone=phone, tab='sms'))


@require_POST
def sms_verify(request):
    phone = request.session.get('otp_phone')
    if not phone:
        return error(request, 'Demandez d’abord un code.', 'sms')
    try:
        with transaction.atomic():
            sub = services.verify_otp(phone, request.POST.get('otp', ''))
    except ServiceError as e:
        return render(request, 'portal/index.html', base_context(request, mode='otp', phone=phone, error=str(e), tab='sms'))
    if sub is None:
        return error(request, 'Numéro vérifié, mais aucun forfait actif. Achetez un forfait ou utilisez un ticket.', 'momo')
    return success(request, sub, 'Numéro vérifié. Bienvenue.')


@require_POST
def free(request):
    if not methods().get('free'):
        return error(request, "L'accès gratuit est désactivé.", 'free')
    try:
        with transaction.atomic():
            sub = services.free_access(ctx_from(request).get('mac', ''))
    except ServiceError as e:
        return error(request, str(e), 'free')
    return success(request, sub, 'Accès gratuit activé.')
