"""Создание администратора из переменных окружения.

Команда нужна для публикации сайта в интернете: на хостинге база каждый раз
пустая (например, на Render файловая система временная), а интерактивный
`createsuperuser` там запустить некому.

Данные берутся из переменных окружения — имена те же, что использует
`createsuperuser --noinput`:

    DJANGO_SUPERUSER_USERNAME   логин (обязательно)
    DJANGO_SUPERUSER_PASSWORD   пароль (обязательно)
    DJANGO_SUPERUSER_EMAIL      e-mail (необязательно)

Команда идемпотентна: если переменные не заданы или администратор уже есть,
она ничего не меняет и завершается без ошибки. Поэтому её безопасно включать
в start-команду хостинга — деплой не упадёт ни при первом запуске,
ни при повторном.

    python manage.py ensure_admin
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Создаёт администратора из переменных окружения, если его ещё нет.'

    def handle(self, *args, **options):
        user_model = get_user_model()

        username = os.environ.get('DJANGO_SUPERUSER_USERNAME', '').strip()
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')

        if not username or not password:
            self.stdout.write(
                'Переменные DJANGO_SUPERUSER_USERNAME и DJANGO_SUPERUSER_PASSWORD '
                'не заданы — администратор не создан.\n'
                'Локально используйте create_admin.bat или '
                'python manage.py createsuperuser.'
            )
            return

        if user_model.objects.filter(is_superuser=True).exists():
            self.stdout.write('Администратор уже есть — создание пропущено.')
            return

        if user_model.objects.filter(username=username).exists():
            # Логин занят обычным пользователем: перезаписывать его нельзя.
            self.stdout.write(self.style.WARNING(
                f'Пользователь "{username}" уже существует — пропускаю. '
                f'Права администратора можно выдать ему через /admin/.'
            ))
            return

        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '').strip()
        if not email:
            # Поле e-mail у модели пользователя обязательное, но для учебного
            # проекта достаточно технического адреса.
            email = f'{username}@gamezone.local'

        user_model.objects.create_superuser(
            username=username,
            email=email,
            password=password,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Администратор "{username}" создан. Вход в админ-панель: /admin/'
        ))
