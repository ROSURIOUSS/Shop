"""Восстановление данных из резервной копии, созданной командой backup_data."""
import json
from collections import Counter
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        'Возвращает в базу пользователей, заказы, товары и обращения '
        'из JSON-копии, созданной командой backup_data.'
    )

    def add_arguments(self, parser):
        parser.add_argument('file', help='Путь к файлу резервной копии.')
        parser.add_argument(
            '--show', action='store_true',
            help='Только показать, что лежит в копии, ничего не восстанавливая.',
        )

    def handle(self, *args, **options):
        path = Path(options['file'])
        if not path.exists():
            raise CommandError(f'Файл не найден: {path}')

        try:
            with path.open(encoding='utf-8') as stream:
                data = json.load(stream)
        except (OSError, ValueError) as error:
            raise CommandError(f'Не удалось прочитать копию: {error}')

        if not isinstance(data, list):
            raise CommandError('Файл не похож на резервную копию GameZone.')

        counts = Counter(item.get('model', 'неизвестно') for item in data)
        self.stdout.write(f'В копии {len(data)} объектов:')
        for model, count in sorted(counts.items()):
            self.stdout.write(f'  {model}: {count}')

        if options['show']:
            self.stdout.write('')
            self.stdout.write('Ничего не восстановлено: указан --show.')
            return

        call_command('loaddata', str(path))
        self.stdout.write(self.style.SUCCESS('Данные восстановлены.'))
        self.stdout.write(
            'Существующие записи с теми же ключами перезаписаны значениями из копии.',
        )
