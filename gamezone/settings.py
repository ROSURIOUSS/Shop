"""
Настройки проекта GameZone.

Проект работает в двух режимах, которые переключаются переменной окружения
DJANGO_DEBUG:

    * локально (DJANGO_DEBUG=1 или не задана) — DEBUG=True, SQLite, встроенный
      ключ разработчика. Так магазин запускает run.bat;
    * в интернете (DJANGO_DEBUG=0) — DEBUG=False и обязательные переменные:
          DJANGO_SECRET_KEY          свой секретный ключ (не из кода);
          DJANGO_ALLOWED_HOSTS       домен сайта, например gamezone.onrender.com;
      необязательные:
          DJANGO_DATABASE_URL        строка подключения к PostgreSQL;
          DJANGO_CSRF_TRUSTED_ORIGINS дополнительные https-домены через запятую;
          DJANGO_SSL_REDIRECT=0      отключить HTTPS-редирект (нужно только
                                     для проверки боевого режима локально).

Подробная инструкция по публикации — в README.md, раздел
«Как вывести сайт в интернет».
"""
import os
from pathlib import Path

from gamezone.db_url import normalize as normalize_database_url
from gamezone.db_url import validate as validate_database_url

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-gamezone-dev-only-change-me-before-publishing',
)

DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'

if DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = [
        host.strip()
        for host in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')
        if host.strip()
    ]
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured(
            'DJANGO_DEBUG=0, но не задан DJANGO_ALLOWED_HOSTS. '
            'Укажите домен сайта (через запятую, если их несколько), '
            'например: DJANGO_ALLOWED_HOSTS=gamezone.onrender.com'
        )

INSTALLED_APPS = [
    'gamezone.admin.GameZoneAdminConfig',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'shop.apps.ShopConfig',
    'activity.apps.ActivityConfig',
]

MIDDLEWARE = [
    'activity.middleware.VisitLogMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'shop.middleware.CustomDebug404Middleware',
]

try:
    import whitenoise  # noqa: F401
except ImportError:
    HAS_WHITENOISE = False
else:
    HAS_WHITENOISE = True
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

ROOT_URLCONF = 'gamezone.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'shop.context_processors.cart_summary',
            ],
        },
    },
]

WSGI_APPLICATION = 'gamezone.wsgi.application'
ASGI_APPLICATION = 'gamezone.asgi.application'

DATABASE_URL = normalize_database_url(os.environ.get('DJANGO_DATABASE_URL', ''))

if DATABASE_URL:
    import dj_database_url

    DATABASES = {
        'default': dj_database_url.config(
            default=validate_database_url(DATABASE_URL),
            conn_max_age=600,
        ),
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Kyiv'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]
if not DEBUG:
    for host in ALLOWED_HOSTS:
        if host == '*':
            continue
        origin = f'https://{host}'
        if origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origin)

MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

LOGIN_URL = 'shop:login'
LOGIN_REDIRECT_URL = 'shop:profile'
LOGOUT_REDIRECT_URL = 'shop:home'

ACTIVITY_LOG_ENABLED = os.environ.get('DJANGO_ACTIVITY_LOG', '1') == '1'
ACTIVITY_LOG_SKIP_PREFIXES = ('/static/', '/media/', '/favicon.ico')

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SSL_REDIRECT', '1') == '1'

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    SECURE_HSTS_SECONDS = 60 * 60
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

    X_FRAME_OPTIONS = 'DENY'

if HAS_WHITENOISE:
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
        },
    }
