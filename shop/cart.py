"""Серверная корзина на основе сессий Django.

В сессии хранится только словарь {id товара: количество}.
Цены и остатки всегда загружаются заново из базы данных —
данные из браузера не считаются достоверными.
"""
from decimal import Decimal

from django.shortcuts import get_object_or_404

from .models import Product

SESSION_KEY = 'cart'


class Cart:
    """Корзина покупок текущей сессии."""

    def __init__(self, request):
        self.session = request.session
        cart = self.session.get(SESSION_KEY)
        if cart is None:
            cart = self.session[SESSION_KEY] = {}
        # Ключи сессии сериализуются в JSON, поэтому id хранятся как строки.
        self.cart = cart

    def save(self):
        self.session.modified = True

    def add(self, product, quantity=1):
        """Добавить товар в корзину (количество суммируется)."""
        quantity = max(int(quantity), 1)
        product_id = str(product.pk)
        current = int(self.cart.get(product_id, 0))
        # Не даём добавить больше, чем есть на складе.
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
        """Полностью очистить корзину."""
        self.cart.clear()
        self.session[SESSION_KEY] = self.cart
        self.save()

    def __iter__(self):
        """Перебор позиций с актуальными данными товаров из базы.

        Количество не «подрезается» молча: если остаток уменьшился,
        страница корзины покажет предупреждение, а оформление заказа
        отклонит позицию с понятным сообщением.
        """
        product_ids = [int(pid) for pid in self.cart.keys()]
        products = Product.objects.filter(id__in=product_ids).select_related('category')
        # Сохраняем порядок добавления товаров в корзину.
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


def get_product_or_404(product_id):
    """Безопасно получить товар по id из корзины/POST-запроса."""
    return get_object_or_404(Product, pk=product_id)
