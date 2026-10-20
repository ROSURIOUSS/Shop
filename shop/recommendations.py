"""Подборки товаров по реальным покупкам: без выдуманных рекомендаций."""
from django.db.models import Count, Q

from .models import Order, OrderItem, Product, with_rating


def bought_together(product, limit=4):
    """Товары, которые покупатели чаще всего берут вместе с этим.

    Считаются только завершённые и активные заказы: отменённые не участвуют.
    Если совместных покупок ещё не было, возвращается пустой набор — на сайте
    блок просто не показывается, а не подставляются случайные товары.
    """
    active_orders = (
        OrderItem.objects
        .filter(product=product)
        .exclude(order__status=Order.Status.CANCELLED)
        .values_list('order_id', flat=True)
    )
    order_ids = list(active_orders)
    if not order_ids:
        return Product.objects.none()
    pairs = Q(order_items__order_id__in=order_ids)
    return (
        with_rating(Product.objects.filter(pairs))
        .exclude(pk=product.pk)
        .filter(is_available=True)
        .annotate(together=Count('order_items', filter=pairs))
        .filter(together__gt=0)
        .select_related('category')
        .order_by('-together', 'name')[:limit]
    )
