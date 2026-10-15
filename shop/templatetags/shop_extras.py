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
