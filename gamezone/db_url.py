"""Подготовка строки подключения к базе из переменной окружения.

Значение `DJANGO_DATABASE_URL` копируют из консоли хостинга, документации или
переписки, и в него регулярно попадает мусор: пробелы и переносы строк, кавычки,
HTML-экранирование (`&amp;`), имя переменной вместе со значением, а иногда
теряется схема `postgresql://`. Здесь строка приводится к рабочему виду, а если
привести её нельзя — сообщается понятно, без технических трейсбеков и без
показа пароля.
"""
from django.core.exceptions import ImproperlyConfigured

SUPPORTED_SCHEMES = (
    'postgres', 'postgresql', 'postgis', 'timescale', 'timescalegis',
    'cockroach', 'redshift', 'mysql', 'mysql2', 'mssql', 'mssqlms',
    'oracle', 'oraclegis', 'sqlite', 'spatialite',
)

INVISIBLE = ('\t', '\r', '\n', '\u00a0', '\u200b', '\u200c', '\u200d', '\ufeff')
FORBIDDEN = ('[', ']', '(', ')', '<', '>', '"', "'", ' ', '`')

EXAMPLE = 'postgresql://ПОЛЬЗОВАТЕЛЬ:ПАРОЛЬ@ХОСТ/ИМЯБАЗЫ?sslmode=require'


def normalize(value):
    """Убрать из строки подключения то, что попадает в неё при копировании."""
    url = value or ''

    for char in INVISIBLE:
        url = url.replace(char, '')

    url = url.strip()
    while len(url) > 1 and url[0] == url[-1] and url[0] in ('"', "'"):
        url = url[1:-1].strip()

    url = url.replace('&amp;', '&')

    head = url.split('://', 1)[0]
    if '=' in head:
        url = url.split('=', 1)[1].strip()

    if url.startswith('://'):
        url = 'postgresql' + url

    return url


def validate(url):
    """Проверить строку подключения и объяснить проблему человеческим языком."""
    if not url:
        return url

    if '://' not in url:
        raise ImproperlyConfigured(
            'DJANGO_DATABASE_URL: в значении нет схемы подключения (нет «://»). '
            f'Скопируйте строку из Neon целиком, она выглядит так: {EXAMPLE}. '
            f'Сейчас в переменной {len(url)} символов и ни одного «://» — '
            'похоже, значение скопировано не полностью.'
        )

    scheme = url.split('://', 1)[0].lower()
    if scheme not in SUPPORTED_SCHEMES:
        raise ImproperlyConfigured(
            f'DJANGO_DATABASE_URL: схема «{scheme}» не поддерживается. '
            f'Нужна одна из: {", ".join(SUPPORTED_SCHEMES[:6])}. '
            f'Пример правильного значения: {EXAMPLE}'
        )

    for char in FORBIDDEN:
        if char in url:
            raise ImproperlyConfigured(
                f'DJANGO_DATABASE_URL: в строке встретился символ «{char}» — '
                'в подключении к базе таких быть не должно. Похоже, значение '
                'скопировано вместе с разметкой (ссылка, скобки, кавычки или '
                f'пробелы). Правильный вид: {EXAMPLE}'
            )

    return url
