"""Показать, какая база данных подключена и сохранятся ли данные."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = (
        'Показывает, какая база данных используется: локальный SQLite или внешняя. '
        'Сразу видно, переживут ли пользователи и заказы перезапуск.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--ping', action='store_true',
            help='Дополнительно проверить, что к базе действительно можно подключиться.',
        )

    def handle(self, *args, **options):
        database = settings.DATABASES['default']
        engine = database['ENGINE'].rsplit('.', 1)[-1]

        if engine == 'sqlite3':
            self.stdout.write(self.style.WARNING(f'База: SQLite, файл {database["NAME"]}'))
            self.stdout.write(self.style.WARNING(
                'На хостинге с эфемерной файловой системой (Render, Docker) такие данные '
                'не переживут перезапуск или новый деплой: файл базы создаётся пустым. '
                'Чтобы пользователи и заказы сохранялись, задайте переменную окружения '
                'DJANGO_DATABASE_URL со строкой подключения к PostgreSQL.'
            ))
        else:
            host = database.get('HOST') or 'локальный сервер'
            name = database.get('NAME') or '—'
            self.stdout.write(self.style.SUCCESS(
                f'База: {engine}, хост {host}, имя базы {name}'
            ))
            self.stdout.write(self.style.SUCCESS(
                'Это внешняя база — данные сохраняются между перезапусками и деплоями.'
            ))

        if not options['ping']:
            return

        try:
            connection.ensure_connection()
        except Exception as error:
            raise CommandError(
                f'Подключиться к базе не удалось: {error}. '
                'Проверьте строку DJANGO_DATABASE_URL (логин, пароль, хост, '
                '?sslmode=require) и доступ к базе со стороны хостинга.'
            )
        self.stdout.write(self.style.SUCCESS('Подключение к базе работает.'))
