"""Резервная копия данных магазина в один JSON-файл."""
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand

from activity.models import AuthEvent, VisitLog
from shop.models import Category, ContactMessage, Order, Product, Profile

BACKUP_DIR = Path(settings.BASE_DIR) / 'backups'
CORE_MODELS = ['auth.user', 'auth.group', 'shop']
LOG_MODELS = ['activity']


class Command(BaseCommand):
    help = (
        'Сохраняет пользователей, профили, заказы, товары и обращения в JSON-файл. '
        'Копию можно перенести на другой сервер или вернуть командой restore_data.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            help='Куда сохранить копию. По умолчанию backups/gamezone-<дата и время>.json',
        )
        parser.add_argument(
            '--with-logs', action='store_true',
            help='Сохранить также журнал посещений и событий покупателей.',
        )
        parser.add_argument(
            '--indent', type=int, default=2,
            help='Отступы в JSON: 2 — читаемый файл, 0 — в одну строку (по умолчанию 2).',
        )

    def handle(self, *args, **options):
        User = get_user_model()

        if options['output']:
            target = Path(options['output'])
        else:
            target = BACKUP_DIR / f'gamezone-{datetime.now():%Y%m%d-%H%M%S}.json'
        target.parent.mkdir(parents=True, exist_ok=True)

        models = list(CORE_MODELS)
        if options['with_logs']:
            models += LOG_MODELS

        counts = [
            ('пользователей', User.objects.count()),
            ('профилей', Profile.objects.count()),
            ('заказов', Order.objects.count()),
            ('позиций заказов', sum(order.items.count() for order in Order.objects.all())),
            ('товаров', Product.objects.count()),
            ('категорий', Category.objects.count()),
            ('обращений', ContactMessage.objects.count()),
        ]
        if options['with_logs']:
            counts.append(('посещений в журнале', VisitLog.objects.count()))
            counts.append(('событий в журнале', AuthEvent.objects.count()))

        with target.open('w', encoding='utf-8') as stream:
            call_command(
                'dumpdata', *models,
                natural_foreign=True,
                indent=options['indent'],
                stdout=stream,
            )

        size = target.stat().st_size
        self.stdout.write(self.style.SUCCESS(f'Резервная копия сохранена: {target}'))
        self.stdout.write(f'Размер файла: {size / 1024:.1f} КБ')
        for label, count in counts:
            self.stdout.write(f'  {label}: {count}')
        self.stdout.write('')
        self.stdout.write(f'Восстановить: python manage.py restore_data "{target}"')
