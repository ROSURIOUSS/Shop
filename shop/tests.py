"""Базовые тесты моделей, корзины и оформления заказа."""
import os
import re
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
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


class EnsureAdminCommandTests(TestCase):
    """Команда ensure_admin нужна при публикации сайта на хостинге:
    там база каждый раз пустая, а интерактивный createsuperuser запустить некому.
    """

    def run_command(self, **env):
        """Запускает команду с заданными переменными окружения."""
        environment = {
            'DJANGO_SUPERUSER_USERNAME': '',
            'DJANGO_SUPERUSER_PASSWORD': '',
            'DJANGO_SUPERUSER_EMAIL': '',
        }
        environment.update(env)
        out = StringIO()
        with mock.patch.dict(os.environ, environment):
            call_command('ensure_admin', stdout=out)
        return out.getvalue()

    def test_creates_superuser_from_env(self):
        output = self.run_command(
            DJANGO_SUPERUSER_USERNAME='deploy_admin',
            DJANGO_SUPERUSER_PASSWORD='strong-pass-2026',
        )
        user = get_user_model().objects.get(username='deploy_admin')
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password('strong-pass-2026'))
        self.assertEqual(user.email, 'deploy_admin@gamezone.local')
        self.assertIn('создан', output)

    def test_skips_when_env_variables_are_not_set(self):
        output = self.run_command()
        self.assertEqual(get_user_model().objects.count(), 0)
        self.assertIn('не заданы', output)

    def test_skips_when_superuser_already_exists(self):
        get_user_model().objects.create_superuser('first', 'first@gamezone.local', 'pass-1')
        output = self.run_command(
            DJANGO_SUPERUSER_USERNAME='second',
            DJANGO_SUPERUSER_PASSWORD='pass-2',
        )
        self.assertFalse(get_user_model().objects.filter(username='second').exists())
        self.assertIn('пропущено', output)

    def test_does_not_overwrite_existing_regular_user(self):
        get_user_model().objects.create_user('buyer', 'buyer@example.com', 'pass-1')
        self.run_command(
            DJANGO_SUPERUSER_USERNAME='buyer',
            DJANGO_SUPERUSER_PASSWORD='pass-2',
        )
        user = get_user_model().objects.get(username='buyer')
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password('pass-1'))


class ProductionSecurityTests(TestCase):
    """Так сайт работает на хостинге: DEBUG=False, свой домен и HTTPS."""

    domain = 'gamezone.example'
    origin = 'https://gamezone.example'

    def setUp(self):
        self.category = make_category()
        self.product = make_product(self.category, slug='prod-mouse')
        override = override_settings(
            DEBUG=False,
            ALLOWED_HOSTS=[self.domain],
            CSRF_TRUSTED_ORIGINS=[self.origin],
        )
        override.enable()
        self.addCleanup(override.disable)
        self.client = Client(enforce_csrf_checks=True)

    def csrf_token(self):
        """Достаёт CSRF-токен из формы на странице товара."""
        response = self.client.get(
            reverse('shop:product_detail', args=[self.product.pk]),
            HTTP_HOST=self.domain,
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        match = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"',
            response.content.decode(),
        )
        self.assertIsNotNone(match, 'в форме нет поля csrfmiddlewaretoken')
        return match.group(1)

    def post_to_cart(self, origin, referer, token='skip'):
        data = {'quantity': 1}
        if token == 'skip':
            token = self.csrf_token()
        elif token:
            data['csrfmiddlewaretoken'] = token
        else:
            self.csrf_token()
        return self.client.post(
            reverse('shop:cart_add', args=[self.product.pk]),
            data,
            HTTP_HOST=self.domain,
            HTTP_ORIGIN=origin,
            HTTP_REFERER=referer,
            secure=True,
        )

    def test_post_from_trusted_origin_is_accepted(self):
        referer = f'{self.origin}/product/{self.product.pk}/'
        response = self.post_to_cart(self.origin, referer, token=self.csrf_token())
        self.assertEqual(response.status_code, 302)
        self.assertIn(str(self.product.pk), self.client.session['cart'])

    def test_post_from_foreign_origin_is_rejected(self):
        referer = f'{self.origin}/product/{self.product.pk}/'
        response = self.post_to_cart('https://evil.example', referer,
                                     token=self.csrf_token())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.client.session.get('cart'))

    def test_post_without_token_is_rejected(self):
        referer = f'{self.origin}/product/{self.product.pk}/'
        response = self.post_to_cart(self.origin, referer, token='')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.client.session.get('cart'))

    def test_foreign_host_is_rejected(self):
        response = self.client.get(reverse('shop:home'), HTTP_HOST='evil.example')
        self.assertEqual(response.status_code, 400)
