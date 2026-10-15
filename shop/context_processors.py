"""Контекстные процессоры проекта GameZone."""
from .cart import Cart


def cart_summary(request):
    """Количество товаров в корзине для индикатора в шапке сайта."""
    try:
        cart = Cart(request)
        return {'cart_item_count': len(cart)}
    except Exception:
        # Сессия может быть недоступна (например, в тестах без middleware).
        return {'cart_item_count': 0}
