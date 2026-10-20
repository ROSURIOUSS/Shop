"""Команда очистки журналов активности от старых записей."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from activity.models import AuthEvent, VisitLog


class Command(BaseCommand):
    help = 'Удаляет старые записи журнала посещений и событий покупателей.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=90,
            help='Удалить записи старше этого количества дней (по умолчанию 90).',
        )
        parser.add_argument(
            '--visits-only', action='store_true',
            help='Чистить только журнал посещений.',
        )
        parser.add_argument(
            '--events-only', action='store_true',
            help='Чистить только журнал событий покупателей.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Показать, сколько записей будет удалено, и ничего не удалять.',
        )

    def handle(self, *args, **options):
        days = options['days']
        if days < 0:
            self.stderr.write('Количество дней не может быть отрицательным.')
            return

        cutoff = timezone.now() - timedelta(days=days)
        targets = []
        if not options['events_only']:
            targets.append(('посещений', VisitLog.objects.filter(created_at__lt=cutoff)))
        if not options['visits_only']:
            targets.append(('событий', AuthEvent.objects.filter(created_at__lt=cutoff)))

        for label, queryset in targets:
            count = queryset.count()
            if options['dry_run']:
                self.stdout.write(f'Будет удалено {label}: {count} (старше {days} дн.)')
                continue
            deleted, _per_model = queryset.delete()
            self.stdout.write(f'Удалено {label}: {deleted} (старше {days} дн.)')

        self.stdout.write(self.style.SUCCESS('Готово.'))
