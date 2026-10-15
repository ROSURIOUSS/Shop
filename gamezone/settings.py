"""
Настройки проекта GameZone.

Для учебного локального проекта DEBUG=True и встроенный SECRET_KEY допустимы.
Перед публикацией в интернете обязательно измените:
    * SECRET_KEY — возьмите значение из переменной окружения DJANGO_SECRET_KEY;
    * DEBUG = False;
    * ALLOWED_ADDRESSES — укажите домен вашего сервера;
    * настройте реальный STATIC_ROOT и WhiteNoise/nginx для статики.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Секретный ключ: для разработки используется локальный ключ.
# В продакшене задайте переменную окружения DJANGO_SECRET_KEY.
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-gamezone-dev-only-change-me-before-publishing',
)

DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'

ALLOWED_HOSTS = ['*'] if DEBUG else os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')

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

# Источники, которым доверяет CSRF-защита (нужно, если сайт открыт через
# HTTPS-прокси с другим доменом — например, онлайн-предпросмотр проекта).
CSRF_TRUSTED_ORIGINS = [
    origin
    for origin in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin
]
if DEBUG:
    # Онлайн-предпросмотр учебного проекта (домен *.e2b.app).
    CSRF_TRUSTED_ORIGINS.append('https://*.e2b.app')

# Сообщения об успехе/ошибках (добавление в корзину, оформление заказа)
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'
