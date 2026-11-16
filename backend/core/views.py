import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token

from . import roles, snapshot


@login_required
def console(request):
    """Sert index.html (la console) en mode connecté : état réel + API."""
    if roles.role_of(request.user) is None:
        return HttpResponse("Votre compte n'a aucun rôle. Demandez à l'administrateur de vous ajouter à un groupe "
                            "(Super administrateur, Opérateur réseau, Caissier ou Revendeur).", status=403,
                            content_type='text/plain; charset=utf-8')
    html = Path(settings.CONSOLE_HTML).read_text(encoding='utf-8')
    state = json.dumps(snapshot.build(request.user), ensure_ascii=False).replace('</', '<\\/')
    boot = (
        f'<script>window.HOTSPOT_API="/api";window.HOTSPOT_CSRF="{get_token(request)}";'
        f'window.HOTSPOT_STATE={state};</script>\n'
        f'<script src="{settings.STATIC_URL}console/console-api.js"></script>\n'
    )
    if '</body>' in html:
        html = html.replace('</body>', boot + '</body>', 1)
    else:
        html += boot
    return HttpResponse(html, content_type='text/html; charset=utf-8')


def healthz(request):
    with connection.cursor() as c:
        c.execute('SELECT 1')
    return JsonResponse({'ok': True})
