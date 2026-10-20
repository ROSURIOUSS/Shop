"""Письма о заказах: уведомление магазина и подтверждение покупателю.

Почта никогда не мешает оформлению заказа: ошибка отправки пишется в лог,
а заказ сохраняется. Без SMTP письма печатаются в консоль сервера — это
честный режим демонстрации, а не «письмо отправлено».
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .templatetags.shop_extras import money

logger = logging.getLogger(__name__)


def _context(order, **extra):
    context = {
        'order': order,
        'items': order.items.select_related('product'),
        'site_name': 'GameZone',
    }
    context.update(extra)
    return context


def _send(subject, text, html, recipients, description):
    """Отправить письмо и не дать почте сломать основной сценарий."""
    if not recipients:
        return False
    message = EmailMultiAlternatives(
        subject, text, settings.DEFAULT_FROM_EMAIL, recipients,
    )
    if html:
        message.attach_alternative(html, 'text/html')
    try:
        message.send(fail_silently=False)
    except Exception:
        logger.exception('Не удалось отправить письмо: %s', description)
        return False
    return True


def notify_new_order(order, admin_url=''):
    """Письмо магазину о новом заказе. Адрес задаётся в SHOP_NOTIFY_EMAIL."""
    recipient = getattr(settings, 'SHOP_NOTIFY_EMAIL', '')
    if not recipient:
        logger.info(
            'Заказ %s: SHOP_NOTIFY_EMAIL не задан, письмо магазину пропущено.',
            order.order_number,
        )
        return False
    subject = f'Новый заказ {order.order_number} на {money(order.total_amount)}'
    context = _context(order, admin_url=admin_url)
    text = render_to_string('shop/emails/new_order.txt', context)
    html = render_to_string('shop/emails/new_order.html', context)
    return _send(subject, text, html, [recipient], f'заказ {order.order_number}')


def send_order_confirmation(order):
    """Письмо покупателю: заказ принят. Отправляется, только если есть email."""
    if not order.email:
        return False
    subject = f'Заказ {order.order_number} принят — GameZone'
    context = _context(order)
    text = render_to_string('shop/emails/order_confirmation.txt', context)
    html = render_to_string('shop/emails/order_confirmation.html', context)
    return _send(
        subject, text, html, [order.email], f'подтверждение {order.order_number}',
    )
