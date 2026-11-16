from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from core import views as core_views

urlpatterns = [
    path('', RedirectView.as_view(url='/console/', permanent=False)),
    path('console/', core_views.console, name='console'),
    path('healthz', core_views.healthz),
    path('accounts/login/', auth_views.LoginView.as_view(
        template_name='admin/login.html',
        extra_context={'site_header': 'HotSpot Pro', 'site_title': 'HotSpot Pro', 'title': 'Connexion'}), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
    path('api/', include('core.urls')),
    path('portal/', include('portal.urls')),
]
