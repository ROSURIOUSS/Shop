"""Пользовательские теги шаблонов GameZone."""
from decimal import Decimal

from django import template
from django.utils.safestring import mark_safe

from shop.icons import ICONS

register = template.Library()


@register.simple_tag
def icon(name, size=20):
    """Вставить SVG-иконку из единого набора (без эмодзи)."""
    inner = ICONS.get(name, ICONS['info'])
    return mark_safe(
        f'<svg class="icon" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{inner}</svg>'
    )


@register.filter
def money(value):
    """Форматировать сумму в гривнах: 12 500 ₴."""
    try:
        amount = Decimal(value)
    except Exception:
        return value
    if amount == amount.to_integral():
        formatted = f'{int(amount):,}'.replace(',', ' ')
    else:
        formatted = f'{amount:,.2f}'.replace(',', ' ')
    return f'{formatted} ₴'


@register.filter
def multiply(value, arg):
    """Умножение двух чисел (цена × количество) для шаблонов."""
    try:
        return Decimal(value) * Decimal(arg)
    except Exception:
        return 0


@register.filter
def plural_ru(value, forms):
    """Склонение существительного по-русски: 1 отзыв, 2 отзыва, 5 отзывов.

    Формы передаются строкой через запятую: 'отзыв,отзыва,отзывов'.
    """
    try:
        number = abs(int(value))
    except (TypeError, ValueError):
        return forms
    parts = [part.strip() for part in forms.split(',')]
    if len(parts) != 3:
        return forms
    one, few, many = parts
    last_digit = number % 10
    last_two = number % 100
    if last_digit == 1 and last_two != 11:
        return one
    if 2 <= last_digit <= 4 and not 12 <= last_two <= 14:
        return few
    return many
