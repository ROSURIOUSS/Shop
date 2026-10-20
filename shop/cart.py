"""Серверная корзина на основе сессий Django.

В сессии хранится только словарь {id товара: количество}.
Цены и остатки всегда загружаются заново из базы данных —
данные из браузера не считаются достоверными.
"""
from decimal import Decimal

from django.shortcuts import get_object_or_404

from .models import Coupon, Product

SESSION_KEY = 'cart'
COUPON_KEY = 'coupon_code'
FAVORITES_KEY = 'favorites'
FAVORITES_LIMIT = 60


class Cart:
    """Корзина покупок текущей сессии."""

    def __init__(self, request):
        self.session = request.session
        cart = self.session.get(SESSION_KEY)
        if cart is None:
            cart = self.session[SESSION_KEY] = {}
        self.cart = cart

    def save(self):
        self.session.modified = True

    def add(self, product, quantity=1):
        """Добавить товар в корзину (количество суммируется)."""
        quantity = max(int(quantity), 1)
        product_id = str(product.pk)
        current = int(self.cart.get(product_id, 0))
        quantity = min(current + quantity, product.stock)
        self.cart[product_id] = quantity
        self.save()

    def update(self, product, quantity):
        """Установить точное количество товара (0 удаляет позицию)."""
        product_id = str(product.pk)
        quantity = int(quantity)
        if quantity <= 0:
            self.remove(product)
            return
        self.cart[product_id] = min(quantity, product.stock)
        self.save()

    def remove(self, product):
        """Удалить товар из корзины."""
        product_id = str(product.pk)
        if product_id in self.cart:
            del self.cart[product_id]
            self.save()

    def clear(self):
        """Полностью очистить корзину и снять промокод."""
        self.cart.clear()
        self.session[SESSION_KEY] = self.cart
        self.session.pop(COUPON_KEY, None)
        self.save()

    def __iter__(self):
        """Перебор позиций с актуальными данными товаров из базы.

        Количество не «подрезается» молча: если остаток уменьшился,
        страница корзины покажет предупреждение, а оформление заказа
        отклонит позицию с понятным сообщением.
        """
        product_ids = [int(pid) for pid in self.cart.keys()]
        products = Product.objects.filter(id__in=product_ids).select_related('category')
        products_by_id = {product.pk: product for product in products}
        for product_id, quantity in self.cart.items():
            product = products_by_id.get(int(product_id))
            if product is None:
                continue
            quantity = int(quantity)
            yield {
                'product': product,
                'quantity': quantity,
                'price': product.price,
                'total_price': product.price * quantity,
            }

    def __len__(self):
        """Общее количество единиц товара в корзине."""
        return sum(int(quantity) for quantity in self.cart.values())

    def get_total_price(self):
        """Общая сумма корзины — пересчитывается по ценам из базы."""
        total = Decimal('0.00')
        for item in self:
            total += item['total_price']
        return total

    def is_empty(self):
        return len(self.cart) == 0

    def get_coupon(self):
        """Действующий промокод сессии или None, если он больше не подходит."""
        code = self.session.get(COUPON_KEY)
        if not code:
            return None
        coupon = Coupon.objects.filter(code=code).first()
        if coupon is None or not coupon.is_available():
            self.session.pop(COUPON_KEY, None)
            return None
        return coupon

    def apply_coupon(self, coupon):
        """Запомнить промокод в сессии: код проверяется на сервере."""
        self.session[COUPON_KEY] = coupon.code
        self.save()

    def remove_coupon(self):
        """Снять промокод с корзины."""
        self.session.pop(COUPON_KEY, None)
        self.save()

    def get_discount(self):
        """Скидка по промокоду для текущей суммы корзины."""
        coupon = self.get_coupon()
        if coupon is None:
            return Decimal('0.00')
        return coupon.discount_for(self.get_total_price())

    def get_payable_total(self):
        """Итог к оплате: сумма товаров за вычетом скидки."""
        return self.get_total_price() - self.get_discount()


def get_favorites(request):
    """Список id товаров в избранном у текущей сессии."""
    raw = request.session.get(FAVORITES_KEY, [])
    favorites = []
    for value in raw:
        try:
            favorites.append(int(value))
        except (TypeError, ValueError):
            continue
    return favorites


def toggle_favorite(request, product):
    """Добавить товар в избранное или убрать его оттуда."""
    favorites = get_favorites(request)
    if product.pk in favorites:
        favorites.remove(product.pk)
        added = False
    else:
        if len(favorites) >= FAVORITES_LIMIT:
            favorites.pop(0)
        favorites.append(product.pk)
        added = True
    request.session[FAVORITES_KEY] = favorites
    request.session.modified = True
    return added


def get_product_or_404(product_id):
    """Безопасно получить товар по id из корзины/POST-запроса."""
    return get_object_or_404(Product, pk=product_id)
