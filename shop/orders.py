"""Смена статуса заказа: единственное место с правилами переходов."""
from django.db import transaction
from django.db.models import F

from .models import Coupon, Order, OrderStatusChange, Product


class OrderTransitionError(Exception):
    """Переход в этот статус невозможен."""


def _log_transition(order, from_status, to_status, user=None, comment=''):
    """Записать изменение статуса в историю заказа."""
    author = user if getattr(user, 'is_authenticated', False) else None
    return OrderStatusChange.objects.create(
        order=order,
        from_status=from_status,
        to_status=to_status,
        changed_by=author,
        comment=comment,
    )


def log_order_created(order, user=None):
    """Первая запись истории: заказ оформлен."""
    return _log_transition(
        order, '', Order.Status.NEW, user=user, comment='Заказ оформлен',
    )


def restore_stock(order):
    """Вернуть товары отменённого заказа на склад."""
    for item in order.items.all():
        product = Product.objects.select_for_update().get(pk=item.product_id)
        product.stock += item.quantity
        product.save(update_fields=['stock'])


def release_coupon(order):
    """Освободить промокод: отменённый заказ не считается применением."""
    if order.coupon_id:
        Coupon.objects.filter(pk=order.coupon_id, used_count__gt=0).update(
            used_count=F('used_count') - 1
        )


@transaction.atomic
def cancel_order(order, user=None):
    """Отменить заказ: вернуть остатки, освободить промокод, сменить статус."""
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if not locked.can_be_cancelled():
        raise OrderTransitionError(
            'Заказ уже передан в доставку — отменить его можно только через поддержку.'
        )
    previous = locked.status
    restore_stock(locked)
    release_coupon(locked)
    locked.status = Order.Status.CANCELLED
    locked.save(update_fields=['status', 'updated_at'])
    _log_transition(locked, previous, locked.status, user=user)
    return locked


@transaction.atomic
def change_status(order, new_status, user=None):
    """Перевести заказ в новый статус, проверив допустимость перехода.

    Отмена выполняется отдельной функцией: она возвращает товары на склад
    и освобождает промокод.
    """
    if new_status not in Order.Status.values:
        raise OrderTransitionError('Неизвестный статус заказа.')

    locked = Order.objects.select_for_update().get(pk=order.pk)
    if new_status == Order.Status.CANCELLED:
        return cancel_order(locked, user=user)

    if not locked.can_move_to(new_status):
        raise OrderTransitionError(
            f'Из статуса «{locked.get_status_display()}» нельзя перейти '
            f'в «{Order.Status(new_status).label}».'
        )
    previous = locked.status
    locked.status = new_status
    locked.save(update_fields=['status', 'updated_at'])
    _log_transition(locked, previous, locked.status, user=user)
    return locked
