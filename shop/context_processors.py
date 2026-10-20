"""Контекстные процессоры проекта GameZone."""
from .cart import Cart, get_favorites


def cart_summary(request):
    """Корзина и избранное для индикаторов в шапке сайта."""
    try:
        cart = Cart(request)
        cart_count = len(cart)
    except Exception:
        cart_count = 0
    try:
        favorites = get_favorites(request)
    except Exception:
        favorites = []
    return {
        'cart_item_count': cart_count,
        'favorite_ids': favorites,
        'favorite_count': len(favorites),
    }
