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

BASE_DIR = Path(__file__).resolve().parent.parent

# Секретный ключ: для разработки используется локальный ключ.
# В продакшене обязательно задайте переменную окружения DJANGO_SECRET_KEY.
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-gamezone-dev-only-change-me-before-publishing',
)

DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'

# В разработке принимаем запросы с любого адреса (сервер виден только вам).
# В продакшене — только домены из DJANGO_ALLOWED_HOSTS, иначе Django ответит
# ошибкой «Invalid HTTP_HOST header».
if DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = [
        host.strip()
        for host in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')
        if host.strip()
    ]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'shop.apps.ShopConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'shop.middleware.CustomDebug404Middleware',
]

# WhiteNoise раздаёт статику (CSS, JS, картинки) без nginx — это нужно на
# хостингах вроде Render. Подключаем только если пакет установлен:
# для локального запуска он не обязателен и в requirements.txt не входит.
try:
    import whitenoise  # noqa: F401
except ImportError:
    HAS_WHITENOISE = False
else:
    HAS_WHITENOISE = True
    # WhiteNoise должен стоять сразу после SecurityMiddleware.
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

ROOT_URLCONF = 'gamezone.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

# База данных.
# По умолчанию SQLite: этого достаточно локально и на PythonAnywhere
# (там файл базы хранится на диске и никуда не пропадает).
# На Render файловая система временная, поэтому туда лучше подключить
# PostgreSQL через DJANGO_DATABASE_URL (пакеты — в requirements-prod.txt).
DATABASE_URL = os.environ.get('DJANGO_DATABASE_URL', '')

if DATABASE_URL:
    import dj_database_url

    DATABASES = {
        # conn_max_age держит соединения открытыми — так ORM не упирается
        # в лимит подключений бесплатной базы.
        'default': dj_database_url.config(default=DATABASE_URL, conn_max_age=600),
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

# Источники, которым доверяет CSRF-защита (нужны, если сайт открыт через
# HTTPS-прокси с другим доменом — например, онлайн-предпросмотр проекта).
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]
if DEBUG:
    # Онлайн-предпросмотр учебного проекта (домен *.e2b.app).
    CSRF_TRUSTED_ORIGINS.append('https://*.e2b.app')
else:
    # Хостинг работает по HTTPS, поэтому домены из ALLOWED_HOSTS сразу
    # добавляем в доверенные — без этого формы (корзина, оформление заказа)
    # отвечали бы ошибкой 403.
    for host in ALLOWED_HOSTS:
        if host == '*':
            continue
        origin = f'https://{host}'
        if origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origin)

# Сообщения об успехе/ошибках (добавление в корзину, оформление заказа)
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

# --- Продакшен-настройки: действуют только при DEBUG=False -------------------
if not DEBUG:
    # Хостинги сами выдают HTTPS; Django стоит за прокси, поэтому доверяем
    # его заголовку и перенаправляем http-запросы на https.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SSL_REDIRECT', '1') == '1'

    # Cookies корзины и админки передаются только по HTTPS.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Браузеры будут ходить только по HTTPS (час — безопасное стартовое
    # значение; увеличивают, когда убедятся, что HTTPS работает стабильно).
    SECURE_HSTS_SECONDS = 60 * 60
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

    X_FRAME_OPTIONS = 'DENY'

if HAS_WHITENOISE:
    # Сжимаем статику при отдаче. Намеренно без Manifest-варианта: тот
    # требует, чтобы все файлы из url(...) в CSS существовали, и сборка
    # падает из-за одной недостающей картинки.
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
        },
    }
