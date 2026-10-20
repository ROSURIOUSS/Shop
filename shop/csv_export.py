"""Выгрузка данных админ-панели в CSV.

Файлы рассчитаны на открытие в Excel: разделитель «;», кодировка UTF-8 с BOM.
Выгружается ровно тот набор записей, который видит администратор, — фильтры,
поиск и сортировка списка учитываются.
"""
import csv
from datetime import date, datetime
from decimal import Decimal

from django.contrib import admin
from django.http import HttpResponse
from django.utils import timezone

CSV_DELIMITER = ';'
CSV_CHUNK_SIZE = 1000


def resolve_path(obj, path):
    """Значение поля по пути вида ``order__user__username``.

    Промежуточные объекты могут отсутствовать — тогда возвращается None,
    а вызываемые атрибуты (методы модели) вызываются.
    """
    value = obj
    for part in path.split('__'):
        if value is None:
            return None
        value = getattr(value, part, None)
        if callable(value):
            value = value()
    return value


def format_cell(value):
    """Человекочитаемое значение ячейки CSV."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'да' if value else 'нет'
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime('%d.%m.%Y %H:%M')
    if isinstance(value, date):
        return value.strftime('%d.%m.%Y')
    if isinstance(value, Decimal):
        return f'{value:.2f}'
    return str(value)


def csv_filename(basename):
    """Имя файла с датой выгрузки, например ``orders-2026-10-21.csv``."""
    return f'{basename}-{timezone.localdate():%Y-%m-%d}.csv'


def csv_response(basename):
    """Ответ-файл CSV с заголовками для скачивания и BOM для Excel."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{csv_filename(basename)}"'
    response.write('\ufeff')
    return response


def write_rows(response, headers, rows):
    """Записать заголовки и строки в CSV-ответ, вернуть число строк."""
    writer = csv.writer(response, delimiter=CSV_DELIMITER, lineterminator='\r\n')
    writer.writerow(headers)
    count = 0
    for row in rows:
        writer.writerow([format_cell(value) for value in row])
        count += 1
    return count


def export_flat_csv(basename, headers, rows):
    """Готовый CSV-ответ из произвольных строк (для выгрузок по позициям)."""
    response = csv_response(basename)
    write_rows(response, headers, rows)
    return response


class CsvExportMixin:
    """Действие «Выгрузить в CSV» для списка записей.

    В наследнике достаточно описать ``csv_fields`` — пары
    (путь к значению, заголовок столбца) — и ``csv_basename``.
    """

    csv_fields = ()
    csv_basename = 'export'

    def csv_headers(self):
        return [header for _path, header in self.csv_fields]

    def csv_rows(self, queryset):
        paths = [path for path, _header in self.csv_fields]
        for obj in queryset.iterator(chunk_size=CSV_CHUNK_SIZE):
            yield [resolve_path(obj, path) for path in paths]

    @admin.action(description='Выгрузить в CSV (Excel)')
    def export_csv(self, request, queryset):
        response = csv_response(self.csv_basename)
        write_rows(response, self.csv_headers(), self.csv_rows(queryset))
        return response
