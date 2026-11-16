"""Configuration Django de HotSpot Pro. Tout se règle par variables d'environnement (voir .env.example)."""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key, default=''):
    return os.environ.get(key, default)


SECRET_KEY = env('DJANGO_SECRET_KEY', 'dev-insecure-change-me')
DEBUG = env('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = [h.strip() for h in env('DJANGO_ALLOWED_HOSTS', '*').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'radius',
    'core',
    'portal',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'hotspot.urls'
WSGI_APPLICATION = 'hotspot.wsgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

if env('DB_HOST'):
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'HOST': env('DB_HOST'),
        'PORT': env('DB_PORT', '5432'),
        'NAME': env('DB_NAME', 'radius'),
        'USER': env('DB_USER', 'radius'),
        'PASSWORD': env('DB_PASSWORD', ''),
        'CONN_MAX_AGE': 60,
    }}
else:  # développement sans Docker : SQLite (les fonctions RADIUS réelles ne marchent pas)
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
]

LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = env('TZ', 'Africa/Kinshasa')
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/console/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
SESSION_COOKIE_AGE = 60 * 60 * 12

if not DEBUG:
    SESSION_COOKIE_SECURE = env('SECURE_COOKIES', '1') == '1'
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

# --- Celery ---------------------------------------------------------------
CELERY_BROKER_URL = env('REDIS_URL', '')
CELERY_TASK_ALWAYS_EAGER = not CELERY_BROKER_URL  # sans Redis, les tâches s'exécutent tout de suite
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    'expire-subscribers': {'task': 'core.tasks.expire_subscribers', 'schedule': timedelta(minutes=2)},
    'refresh-usage': {'task': 'core.tasks.refresh_usage', 'schedule': timedelta(minutes=2)},
    'check-nas': {'task': 'core.tasks.check_nas', 'schedule': timedelta(minutes=2)},
    'close-stale-sessions': {'task': 'core.tasks.close_stale_sessions', 'schedule': timedelta(minutes=10)},
    'purge-old-records': {'task': 'core.tasks.purge_old_records', 'schedule': timedelta(hours=24)},
}

# --- HotSpot Pro ------------------------------------------------------------
CONSOLE_HTML = env('CONSOLE_HTML', str(BASE_DIR.parent / 'index.html'))
PUBLIC_URL = env('PUBLIC_URL', 'http://localhost:8000')
RADCLIENT_BIN = env('RADCLIENT_BIN', 'radclient')

MOMO_PROVIDER = env('MOMO_PROVIDER', 'demo')          # demo | http
MOMO_API_URL = env('MOMO_API_URL', '')
MOMO_API_KEY = env('MOMO_API_KEY', '')
MOMO_WEBHOOK_SECRET = env('MOMO_WEBHOOK_SECRET', '')

SMS_BACKEND = env('SMS_BACKEND', 'console')            # console | http
SMS_API_URL = env('SMS_API_URL', '')
SMS_API_TOKEN = env('SMS_API_TOKEN', '')
SMS_SENDER = env('SMS_SENDER', 'HotSpot')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': env('LOG_LEVEL', 'INFO')},
}
