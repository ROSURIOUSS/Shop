"""Определение IP-адреса посетителя и запись событий в журнал активности."""
import ipaddress
import logging

from django.conf import settings

from .models import AuthEvent, VisitLog

logger = logging.getLogger(__name__)

BROWSERS = [
    ('YaBrowser', 'Яндекс.Браузер'),
    ('OPR/', 'Opera'),
    ('Opera', 'Opera'),
    ('Edg/', 'Edge'),
    ('Firefox/', 'Firefox'),
    ('Chrome/', 'Chrome'),
    ('Safari/', 'Safari'),
]

SYSTEMS = [
    ('Windows NT 10', 'Windows 10/11'),
    ('Windows NT 6.3', 'Windows 8.1'),
    ('Windows NT 6.1', 'Windows 7'),
    ('Windows', 'Windows'),
    ('iPhone', 'iOS (iPhone)'),
    ('iPad', 'iOS (iPad)'),
    ('Mac OS X', 'macOS'),
    ('Android', 'Android'),
    ('Ubuntu', 'Ubuntu'),
    ('Linux', 'Linux'),
]


def _valid_ip(value):
    """Проверить, что строка действительно похожа на IP-адрес."""
    if not value:
        return False
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return True


def get_client_ip(request):
    """IP посетителя с учётом прокси хостинга (Render, nginx, Cloudflare).

    За прокси в REMOTE_ADDR попадает адрес самого прокси, поэтому сначала
    смотрим заголовки X-Forwarded-For и X-Real-IP и берём первый корректный
    адрес из цепочки.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    for candidate in forwarded.split(','):
        candidate = candidate.strip()
        if _valid_ip(candidate):
            return candidate

    real_ip = request.META.get('HTTP_X_REAL_IP', '').strip()
    if _valid_ip(real_ip):
        return real_ip

    remote_addr = (request.META.get('REMOTE_ADDR') or '').strip()
    return remote_addr if _valid_ip(remote_addr) else None


def describe_user_agent(user_agent):
    """Определить браузер и систему по строке User-Agent, без сторонних библиотек."""
    agent = user_agent or ''
    browser = ''
    for marker, name in BROWSERS:
        if marker in agent:
            browser = name
            break
    system = ''
    for marker, name in SYSTEMS:
        if marker in agent:
            system = name
            break
    if not browser:
        if 'curl/' in agent:
            browser = 'curl'
        elif 'python-requests' in agent:
            browser = 'python-requests'
        elif 'bot' in agent.lower():
            browser = 'Бот'
    return browser, system


def _cut(value, limit):
    """Обрезать строку под максимальную длину поля — важно для PostgreSQL."""
    if value is None:
        return ''
    value = str(value)
    return value[:limit]


def logging_enabled():
    """Журнал можно отключить переменной окружения DJANGO_ACTIVITY_LOG=0."""
    return bool(getattr(settings, 'ACTIVITY_LOG_ENABLED', True))


def is_skipped_path(path):
    """Служебные адреса (статика, медиа, favicon) в журнал не пишем."""
    prefixes = getattr(settings, 'ACTIVITY_LOG_SKIP_PREFIXES', ('/static/', '/media/'))
    return any(path.startswith(prefix) for prefix in prefixes)


def log_visit(request, response):
    """Записать обращение к сайту в журнал посещений.

    Ошибка записи не должна мешать сайту отвечать, поэтому всё под try/except.
    """
    if not logging_enabled():
        return None
    path = request.path or ''
    if is_skipped_path(path):
        return None
    if request.method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
        return None

    user = getattr(request, 'user', None)
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    browser, system = describe_user_agent(user_agent)

    try:
        return VisitLog.objects.create(
            ip_address=get_client_ip(request),
            user=user if (user is not None and user.is_authenticated) else None,
            path=_cut(path, 400),
            method=_cut(request.method, 10),
            status_code=getattr(response, 'status_code', None),
            browser=browser,
            os=system,
            user_agent=_cut(user_agent, 400),
            referer=_cut(request.META.get('HTTP_REFERER', ''), 400),
        )
    except Exception as error:
        logger.warning('Не удалось записать посещение в журнал: %s', error)
        return None


def log_auth_event(request, action, user=None, username='', success=True, detail=''):
    """Записать действие покупателя (вход, регистрация, заказ) вместе с IP."""
    if not logging_enabled():
        return None

    user_agent = request.META.get('HTTP_USER_AGENT', '')
    browser, system = describe_user_agent(user_agent)

    try:
        return AuthEvent.objects.create(
            action=action,
            success=success,
            user=user if (user is not None and getattr(user, 'is_authenticated', False)) else None,
            username=_cut(username, 150),
            ip_address=get_client_ip(request),
            browser=browser,
            os=system,
            user_agent=_cut(user_agent, 400),
            detail=_cut(detail, 200),
        )
    except Exception as error:
        logger.warning('Не удалось записать событие в журнал: %s', error)
        return None
