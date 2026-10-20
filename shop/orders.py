"""Смена статуса заказа: единственное место с правилами переходов."""
from django.db import transaction
from django.db.models import F

from .models import Coupon, Order, Product


class OrderTransitionError(Exception):
    """Переход в этот статус невозможен."""


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
def cancel_order(order):
    """Отменить заказ: вернуть остатки, освободить промокод, сменить статус."""
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if not locked.can_be_cancelled():
        raise OrderTransitionError(
            'Заказ уже передан в доставку — отменить его можно только через поддержку.'
        )
    restore_stock(locked)
    release_coupon(locked)
    locked.status = Order.Status.CANCELLED
    locked.save(update_fields=['status', 'updated_at'])
    return locked


@transaction.atomic
def change_status(order, new_status):
    """Перевести заказ в новый статус, проверив допустимость перехода.

    Отмена выполняется отдельной функцией: она возвращает товары на склад
    и освобождает промокод.
    """
    if new_status not in Order.Status.values:
        raise OrderTransitionError('Неизвестный статус заказа.')

    locked = Order.objects.select_for_update().get(pk=order.pk)
    if new_status == Order.Status.CANCELLED:
        return cancel_order(locked)

    if not locked.can_move_to(new_status):
        raise OrderTransitionError(
            f'Из статуса «{locked.get_status_display()}» нельзя перейти '
            f'в «{Order.Status(new_status).label}».'
        )
    locked.status = new_status
    locked.save(update_fields=['status', 'updated_at'])
    return locked
