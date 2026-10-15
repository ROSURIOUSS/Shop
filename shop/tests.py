"""Базовые тесты моделей, корзины и оформления заказа."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .cart import Cart
from .models import Category, ContactMessage, Order, OrderItem, Product


def make_category(**kwargs):
    defaults = {'name': 'Игровые мышки', 'slug': 'mouse', 'description': 'Описание'}
    defaults.update(kwargs)
    return Category.objects.create(**defaults)


def make_product(category, **kwargs):
    defaults = {
        'name': 'Test Mouse',
        'description': 'Тестовая игровая мышь',
        'price': Decimal('999.00'),
        'stock': 10,
        'is_available': True,
    }
    defaults.update(kwargs)
    return Product.objects.create(category=category, **defaults)


class ModelTests(TestCase):
    def test_category_str_and_url(self):
        category = make_category()
        self.assertEqual(str(category), 'Игровые мышки')
        self.assertEqual(category.get_absolute_url(), '/categories/mouse/')

    def test_product_str_and_url(self):
        category = make_category()
        product = make_product(category)
        self.assertEqual(str(product), 'Test Mouse')
        self.assertEqual(product.get_absolute_url(), f'/product/{product.pk}/')

    def test_product_in_stock(self):
        category = make_category()
        product = make_product(category, stock=0)
        self.assertFalse(product.in_stock())
        product.stock = 3
        self.assertTrue(product.in_stock())

    def test_product_negative_price_invalid(self):
        category = make_category()
        product = make_product(category, price=Decimal('-5.00'))
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_order_number_generated(self):
        category = make_category()
        product = make_product(category)
        order = Order.objects.create(
            customer_name='Иван Петренко', phone='+380501112233',
            city='Киев', address='Ул. Тестовая, 1',
        )
        OrderItem.objects.create(order=order, product=product, quantity=2, price=product.price)
        self.assertTrue(order.order_number.startswith('GZ-'))
        self.assertEqual(order.get_total_cost(), Decimal('1998.00'))

    def test_order_item_price_fixed(self):
        """Стоимость старого заказа не меняется при изменении цены товара."""
        category = make_category()
        product = make_product(category)
        order = Order.objects.create(
            customer_name='Иван', phone='+380501112233', city='Киев', address='Тестовая, 1',
        )
        OrderItem.objects.create(order=order, product=product, quantity=1, price=product.price)
        product.price = Decimal('5000.00')
        product.save()
        order.refresh_from_db()
        self.assertEqual(order.get_total_cost(), Decimal('999.00'))


class CartTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.product = make_product(self.category, stock=5)
        self.request = self.client.get('/').wsgi_request
        self.cart = Cart(self.request)

    def test_add_and_total(self):
        self.cart.add(self.product, 2)
        self.assertEqual(len(self.cart), 2)
        self.assertEqual(self.cart.get_total_price(), Decimal('1998.00'))

    def test_add_limited_by_stock(self):
        self.cart.add(self.product, 4)
        self.cart.add(self.product, 4)
        self.assertEqual(len(self.cart), 5)

    def test_update_and_remove(self):
        self.cart.add(self.product, 1)
        self.cart.update(self.product, 3)
        self.assertEqual(len(self.cart), 3)
        self.cart.remove(self.product)
        self.assertEqual(len(self.cart), 0)

    def test_clear(self):
        self.cart.add(self.product, 2)
        self.cart.clear()
        self.assertTrue(self.cart.is_empty())


class ViewTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.product = make_product(self.category, is_featured=True, stock=5)
        self.other_product = make_product(
            self.category, name='Test Keyboard', slug='test-keyboard',
            price=Decimal('1999.00'),
        )

    def test_home_page(self):
        response = self.client.get(reverse('shop:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Твоя игровая зона начинается здесь')

    def test_catalog_search(self):
        response = self.client.get(reverse('shop:catalog'), {'q': 'keyboard'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Keyboard')
        self.assertNotContains(response, 'Test Mouse')

    def test_catalog_price_filter(self):
        response = self.client.get(reverse('shop:catalog'), {'min_price': '1500'})
        self.assertContains(response, 'Test Keyboard')
        self.assertNotContains(response, 'Test Mouse')

    def test_catalog_bad_price_does_not_crash(self):
        response = self.client.get(reverse('shop:catalog'), {'min_price': 'abc', 'max_price': '-3'})
        self.assertEqual(response.status_code, 200)

    def test_category_detail_and_404(self):
        response = self.client.get(reverse('shop:category_detail', args=['mouse']))
        self.assertEqual(response.status_code, 200)
        missing = self.client.get(reverse('shop:category_detail', args=['no-such']))
        self.assertEqual(missing.status_code, 404)

    def test_product_detail(self):
        response = self.client.get(reverse('shop:product_detail', args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)

    def test_product_missing_returns_404(self):
        response = self.client.get(reverse('shop:product_detail', args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_add_to_cart_flow(self):
        response = self.client.post(
            reverse('shop:cart_add', args=[self.product.pk]),
            {'quantity': 2},
        )
        self.assertRedirects(response, reverse('shop:cart'))
        session_cart = self.client.session['cart']
        self.assertEqual(session_cart[str(self.product.pk)], 2)

    def test_add_to_cart_requires_post(self):
        response = self.client.get(reverse('shop:cart_add', args=[self.product.pk]))
        self.assertEqual(response.status_code, 405)

    def test_cart_update_and_remove(self):
        self.client.post(reverse('shop:cart_add', args=[self.product.pk]), {'quantity': 1})
        self.client.post(reverse('shop:cart_update', args=[self.product.pk]), {'quantity': 3})
        self.assertEqual(self.client.session['cart'][str(self.product.pk)], 3)
        self.client.post(reverse('shop:cart_remove', args=[self.product.pk]))
        self.assertNotIn(str(self.product.pk), self.client.session.get('cart', {}))

    def test_checkout_creates_order_and_reduces_stock(self):
        self.client.post(reverse('shop:cart_add', args=[self.product.pk]), {'quantity': 2})
        response = self.client.post(reverse('shop:checkout'), {
            'customer_name': 'Иван Петренко',
            'phone': '+380501112233',
            'email': 'ivan@example.com',
            'city': 'Киев',
            'address': 'Ул. Тестовая, 1',
            'comment': '',
        })
        self.assertRedirects(response, reverse('shop:order_success'))
        order = Order.objects.get()
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.total_amount, self.product.price * 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertFalse(self.client.session.get('cart'))

    def test_checkout_rejects_insufficient_stock(self):
        self.client.post(reverse('shop:cart_add', args=[self.product.pk]), {'quantity': 5})
        self.product.stock = 1
        self.product.save()
        response = self.client.post(reverse('shop:checkout'), {
            'customer_name': 'Иван Петренко',
            'phone': '+380501112233',
            'city': 'Киев',
            'address': 'Ул. Тестовая, 1',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_empty_cart_redirects(self):
        response = self.client.get(reverse('shop:checkout'))
        self.assertRedirects(response, reverse('shop:cart'))

    def test_order_success_requires_session(self):
        response = self.client.get(reverse('shop:order_success'))
        self.assertRedirects(response, reverse('shop:home'))

    def test_contact_form_saved(self):
        response = self.client.post(reverse('shop:contacts'), {
            'name': 'Пётр',
            'email': 'petr@example.com',
            'subject': 'Вопрос',
            'message': 'Здравствуйте!',
        })
        self.assertRedirects(response, reverse('shop:contacts'))
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_catalog_pagination(self):
        for index in range(15):
            make_product(
                self.category,
                name=f'Extra {index}',
                slug=f'extra-{index}',
                stock=1,
            )
        response = self.client.get(reverse('shop:catalog'))
        self.assertEqual(len(response.context['products']), 12)
        response_page_2 = self.client.get(reverse('shop:catalog'), {'page': 2})
        self.assertEqual(len(response_page_2.context['products']), 5)
