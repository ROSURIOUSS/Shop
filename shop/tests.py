"""Тесты моделей, корзины, оформления заказа, аккаунтов и резервных копий."""
import csv
import json
import os
import re
import tempfile
from datetime import timedelta
from pathlib import Path
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, transaction
from django.db.utils import OperationalError
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from activity.models import AuthEvent, VisitLog
from gamezone.db_url import normalize as normalize_database_url
from gamezone.db_url import validate as validate_database_url

from .cart import Cart
from .dashboard import LOW_STOCK_THRESHOLD as DASHBOARD_LOW_STOCK_THRESHOLD
from .models import (
    LOW_STOCK_THRESHOLD,
    Coupon,
    Category,
    ContactMessage,
    Order,
    OrderItem,
    Product,
    Profile,
    Review,
    with_rating,
)
from .recommendations import bought_together
from .templatetags.shop_extras import plural_ru


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
        self.buyer = get_user_model().objects.create_user(
            username='buyer', email='buyer@example.com', password='secret-pass-2026',
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
        self.client.force_login(self.buyer)
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
        self.client.force_login(self.buyer)
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
        self.client.force_login(self.buyer)
        response = self.client.get(reverse('shop:checkout'))
        self.assertRedirects(response, reverse('shop:cart'))

    def test_guest_checkout_is_redirected_to_login(self):
        self.client.post(reverse('shop:cart_add', args=[self.product.pk]), {'quantity': 1})
        response = self.client.get(reverse('shop:checkout'))
        self.assertRedirects(response, reverse('shop:login') + '?next=/checkout/')

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


class AccountTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.product = make_product(self.category, stock=5)
        self.User = get_user_model()

    def register(self, **overrides):
        data = {
            'username': 'gamer',
            'email': 'gamer@example.com',
            'password1': 'strong-pass-2026',
            'password2': 'strong-pass-2026',
        }
        data.update(overrides)
        return self.client.post(reverse('shop:register'), data)

    def test_register_creates_user_profile_and_logs_in(self):
        response = self.register()
        self.assertRedirects(response, reverse('shop:profile'))
        user = self.User.objects.get(username='gamer')
        self.assertEqual(user.email, 'gamer@example.com')
        self.assertTrue(user.check_password('strong-pass-2026'))
        self.assertTrue(Profile.objects.filter(user=user).exists())
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))

    def test_register_rejects_duplicate_email(self):
        self.User.objects.create_user(username='first', email='gamer@example.com', password='pass-1234567')
        response = self.register(username='second')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.User.objects.filter(username='second').exists())

    def test_register_rejects_weak_password(self):
        response = self.register(password1='123', password2='123')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.User.objects.filter(username='gamer').exists())

    def test_login_and_logout(self):
        self.User.objects.create_user(username='gamer', email='g@example.com', password='strong-pass-2026')
        response = self.client.post(reverse('shop:login'), {'username': 'gamer', 'password': 'strong-pass-2026'})
        self.assertRedirects(response, reverse('shop:profile'))

        logout_response = self.client.post(reverse('shop:logout'))
        self.assertRedirects(logout_response, reverse('shop:home'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_rejects_wrong_password(self):
        self.User.objects.create_user(username='gamer', password='strong-pass-2026')
        response = self.client.post(reverse('shop:login'), {'username': 'gamer', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logout_requires_post(self):
        response = self.client.get(reverse('shop:logout'))
        self.assertEqual(response.status_code, 405)

    def test_profile_requires_login(self):
        for name in ('shop:profile', 'shop:profile_edit', 'shop:password_change'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertTrue(response.url.startswith(reverse('shop:login')), name)

    def test_checkout_stores_order_owner_and_saves_delivery_data(self):
        user = self.User.objects.create_user(username='gamer', password='strong-pass-2026')
        Profile.objects.create(user=user)
        self.client.force_login(user)
        self.client.post(reverse('shop:cart_add', args=[self.product.pk]), {'quantity': 2})
        response = self.client.post(reverse('shop:checkout'), {
            'customer_name': 'Іван Петренко',
            'phone': '+380501112233',
            'email': 'gamer@example.com',
            'city': 'Харків',
            'address': 'вул. Тестова, 1',
            'comment': '',
        })
        self.assertRedirects(response, reverse('shop:order_success'))
        order = Order.objects.get()
        self.assertEqual(order.user, user)
        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.phone, '+380501112233')
        self.assertEqual(profile.city, 'Харків')

    def test_checkout_form_is_prefilled_from_profile(self):
        user = self.User.objects.create_user(
            username='gamer', first_name='Іван', email='gamer@example.com', password='strong-pass-2026',
        )
        Profile.objects.create(user=user, phone='+380501112233', city='Харків', address='вул. Тестова, 1')
        self.client.force_login(user)
        self.client.post(reverse('shop:cart_add', args=[self.product.pk]), {'quantity': 1})
        response = self.client.get(reverse('shop:checkout'))
        self.assertContains(response, '+380501112233')
        self.assertContains(response, 'вул. Тестова, 1')
        self.assertContains(response, 'gamer@example.com')

    def test_profile_shows_only_own_orders(self):
        first = self.User.objects.create_user(username='first', password='strong-pass-2026')
        second = self.User.objects.create_user(username='second', password='strong-pass-2026')
        Order.objects.create(
            user=first, customer_name='Перший', phone='+380500000001', email='f@example.com',
            city='Київ', address='вул. 1', total_amount=Decimal('100.00'),
        )
        self.client.force_login(second)
        response = self.client.get(reverse('shop:profile'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['orders']), [])
        self.assertContains(response, 'Заказов пока нет')

        self.client.force_login(first)
        response = self.client.get(reverse('shop:profile'))
        self.assertEqual(response.context['orders'].count(), 1)

    def test_profile_creates_missing_profile_row(self):
        user = self.User.objects.create_user(username='olduser', password='strong-pass-2026')
        self.client.force_login(user)
        response = self.client.get(reverse('shop:profile'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Profile.objects.filter(user=user).exists())

    def test_profile_edit_updates_user_and_profile(self):
        user = self.User.objects.create_user(username='gamer', password='strong-pass-2026')
        Profile.objects.create(user=user)
        self.client.force_login(user)
        response = self.client.post(reverse('shop:profile_edit'), {
            'first_name': 'Іван',
            'last_name': 'Петренко',
            'email': 'new@example.com',
            'phone': '+380501112233',
            'city': 'Харків',
            'address': 'вул. Тестова, 1',
        })
        self.assertRedirects(response, reverse('shop:profile'))
        user.refresh_from_db()
        self.assertEqual(user.get_full_name(), 'Іван Петренко')
        self.assertEqual(user.email, 'new@example.com')
        self.assertEqual(Profile.objects.get(user=user).city, 'Харків')

    def test_password_change_keeps_session(self):
        user = self.User.objects.create_user(username='gamer', password='strong-pass-2026')
        self.client.force_login(user)
        response = self.client.post(reverse('shop:password_change'), {
            'old_password': 'strong-pass-2026',
            'new_password1': 'another-pass-2026',
            'new_password2': 'another-pass-2026',
        })
        self.assertRedirects(response, reverse('shop:profile'))
        user.refresh_from_db()
        self.assertTrue(user.check_password('another-pass-2026'))
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))

    def test_register_honours_safe_next_url(self):
        response = self.register(username='gamer2', email='g2@example.com')
        self.assertRedirects(response, reverse('shop:profile'))
        response = self.client.post(reverse('shop:logout'))
        self.assertRedirects(response, reverse('shop:home'))

        self.client.get(reverse('shop:login'), {'next': '/catalog/'})
        response = self.register(
            username='gamer3', email='g3@example.com', next='/catalog/',
        )
        self.assertRedirects(response, '/catalog/')


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

class DashboardTests(TestCase):
    """Дашборд админ-панели: цифры считаются по реальным данным и с учётом прав."""

    def setUp(self):
        self.User = get_user_model()
        self.superuser = self.User.objects.create_superuser(
            username='admin', email='admin@example.com', password='strong-pass-2026',
        )
        self.category = make_category()
        self.low_stock = make_product(self.category, stock=2)
        self.enough_stock = make_product(
            self.category, name='Test Keyboard', slug='test-keyboard',
            price=Decimal('1999.00'), stock=50,
        )

    def make_order(self, product, quantity, status='new', ip_address='93.184.216.34'):
        order = Order.objects.create(
            customer_name='Іван Петренко',
            phone='+380501112233',
            email='ivan@example.com',
            city='Харків',
            address='вул. Тестова, 1',
            status=status,
            ip_address=ip_address,
            total_amount=product.price * quantity,
        )
        OrderItem.objects.create(order=order, product=product, quantity=quantity, price=product.price)
        return order

    def dashboard(self):
        self.client.force_login(self.superuser)
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 200)
        return response

    def test_dashboard_is_rendered_on_admin_index(self):
        response = self.dashboard()
        self.assertContains(response, 'Сводка магазина')
        self.assertContains(response, 'Продажи')
        self.assertContains(response, 'Топ товаров по продажам')
        self.assertContains(response, 'Склад и витрина')
        self.assertContains(response, 'Активность')
        self.assertContains(response, 'Последние заказы')

    def test_admin_is_branded(self):
        response = self.dashboard()
        self.assertContains(response, 'GameZone — управление магазином')
        self.assertContains(response, 'gzh-brand')
        self.assertContains(response, 'shop/images/logo.svg')
        self.assertContains(response, 'панель управления')

    def test_dashboard_is_not_shown_on_login_page(self):
        response = self.client.get('/admin/login/')
        self.assertNotContains(response, 'Сводка магазина')

    def test_revenue_and_order_count(self):
        self.make_order(self.low_stock, 2)
        self.make_order(self.enough_stock, 1)
        response = self.dashboard()
        sales = response.context['dashboard']['sales']
        today = sales[0]
        self.assertEqual(today['label'], 'Сегодня')
        self.assertEqual(today['revenue'], Decimal('3997.00'))
        self.assertEqual(today['orders'], 2)
        self.assertEqual(today['average'], Decimal('1998.50'))
        total = sales[-1]
        self.assertTrue(total['is_total'])
        self.assertEqual(total['revenue'], Decimal('3997.00'))

    def test_cancelled_orders_are_excluded_from_revenue(self):
        self.make_order(self.low_stock, 1)
        self.make_order(self.low_stock, 1, status='cancelled')
        response = self.dashboard()
        dashboard = response.context['dashboard']
        self.assertEqual(dashboard['sales'][0]['revenue'], Decimal('999.00'))
        self.assertEqual(dashboard['sales'][0]['orders'], 1)
        cancelled = [row for row in dashboard['statuses'] if row['status'] == 'cancelled']
        self.assertEqual(cancelled[0]['count'], 1)

    def test_top_products_are_sorted_by_sold_quantity(self):
        for _ in range(3):
            self.make_order(self.low_stock, 2)
        self.make_order(self.enough_stock, 1)
        response = self.dashboard()
        top = response.context['dashboard']['top_products']
        self.assertEqual(top[0]['name'], 'Test Mouse')
        self.assertEqual(top[0]['quantity'], 6)
        self.assertEqual(top[0]['width'], 100)
        self.assertEqual(top[1]['name'], 'Test Keyboard')
        self.assertEqual(top[1]['quantity'], 1)
        self.assertLess(top[1]['width'], 100)

    def test_low_stock_products_are_listed(self):
        response = self.dashboard()
        stock = response.context['dashboard']['stock']
        self.assertEqual(stock['threshold'], 5)
        names = [item['name'] for item in stock['items']]
        self.assertIn('Test Mouse', names)
        self.assertNotIn('Test Keyboard', names)
        self.assertEqual(stock['total'], 2)
        self.assertEqual(stock['categories'], 1)
        self.assertEqual(
            stock['items'][0]['url'],
            reverse('admin:shop_product_change', args=[self.low_stock.pk]),
        )

    def test_recent_orders_include_ip_and_link(self):
        order = self.make_order(self.low_stock, 1)
        response = self.dashboard()
        recent = response.context['dashboard']['recent_orders']
        self.assertEqual(recent[0]['number'], order.order_number)
        self.assertEqual(recent[0]['ip_address'], '93.184.216.34')
        self.assertEqual(recent[0]['url'], reverse('admin:shop_order_change', args=[order.pk]))
        self.assertContains(response, '93.184.216.34')

    def test_activity_counters(self):
        VisitLog.objects.create(ip_address='93.184.216.34', path='/catalog/', method='GET', status_code=200)
        VisitLog.objects.create(ip_address='8.8.8.8', path='/about/', method='GET', status_code=200)
        AuthEvent.objects.create(action=AuthEvent.Action.REGISTER, success=True, username='gamer')
        AuthEvent.objects.create(
            action=AuthEvent.Action.LOGIN_FAILED, success=False,
            username='hacker', ip_address='45.158.11.7',
        )
        response = self.dashboard()
        activity = response.context['dashboard']['activity']
        self.assertEqual(activity['visits']['today'], 2)
        self.assertEqual(activity['visits']['ip_today'], 2)
        self.assertEqual(activity['events']['registrations_today'], 1)
        self.assertEqual(activity['events']['failed_week'], 1)
        self.assertContains(response, 'Уникальных IP сегодня')

    def test_messages_are_listed(self):
        ContactMessage.objects.create(
            name='Пётр', email='petr@example.com', subject='Вопрос о доставке',
            message='Здравствуйте!',
        )
        response = self.dashboard()
        messages = response.context['dashboard']['messages']
        self.assertEqual(messages[0]['subject'], 'Вопрос о доставке')
        self.assertContains(response, 'Вопрос о доставке')

    def test_sections_are_hidden_without_permissions(self):
        staff = self.User.objects.create_user(
            username='storekeeper', password='strong-pass-2026', is_staff=True,
        )
        staff.user_permissions.add(
            Permission.objects.get(codename='view_product', content_type__app_label='shop'),
        )
        self.make_order(self.low_stock, 1)

        self.client.force_login(self.User.objects.get(pk=staff.pk))
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 200)
        dashboard = response.context['dashboard']
        self.assertIn('stock', dashboard)
        self.assertNotIn('sales', dashboard)
        self.assertNotIn('top_products', dashboard)
        self.assertNotIn('recent_orders', dashboard)
        self.assertNotIn('activity', dashboard)
        self.assertNotIn('messages', dashboard)
        self.assertNotContains(response, 'Последние заказы')

    def test_anonymous_cannot_see_dashboard(self):
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/admin/login/'))

class BackupRestoreTests(TestCase):
    """Резервное копирование: данные переживают перенос и потерю базы."""

    def setUp(self):
        self.User = get_user_model()
        self.category = make_category()
        self.product = make_product(self.category, stock=5)

    def make_data(self):
        user = self.User.objects.create_user(
            username='gamer', email='gamer@example.com', password='strong-pass-2026',
        )
        Profile.objects.create(
            user=user, phone='+380501112233', city='Харків', address='вул. Тестова, 1',
        )
        order = Order.objects.create(
            user=user, customer_name='Іван Петренко', phone='+380501112233',
            email='gamer@example.com', city='Харків', address='вул. Тестова, 1',
            total_amount=Decimal('1998.00'), ip_address='93.184.216.34',
        )
        OrderItem.objects.create(order=order, product=self.product, quantity=2, price=self.product.price)
        return user, order

    def read(self, path):
        with open(path, encoding='utf-8') as stream:
            return json.load(stream)

    def test_backup_saves_users_orders_and_products(self):
        self.make_data()
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, 'copy.json')
            output = StringIO()
            call_command('backup_data', output=target, stdout=output)

            self.assertTrue(os.path.exists(target))
            models = {item['model'] for item in self.read(target)}
            self.assertIn('auth.user', models)
            self.assertIn('shop.profile', models)
            self.assertIn('shop.order', models)
            self.assertIn('shop.orderitem', models)
            self.assertIn('shop.product', models)
            self.assertNotIn('activity.visitlog', models)
            self.assertIn('Резервная копия сохранена', output.getvalue())

    def test_backup_creates_missing_folders(self):
        self.make_data()
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, 'nested', 'deep', 'copy.json')
            call_command('backup_data', output=target)
            self.assertTrue(os.path.exists(target))

    def test_backup_stores_password_hash_only(self):
        self.make_data()
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, 'copy.json')
            call_command('backup_data', output=target)
            record = next(item for item in self.read(target) if item['model'] == 'auth.user')
            self.assertNotEqual(record['fields']['password'], 'strong-pass-2026')
            self.assertTrue(record['fields']['password'].startswith('pbkdf2_sha256$'))

    def test_backup_can_include_activity_logs(self):
        self.make_data()
        VisitLog.objects.create(ip_address='93.184.216.34', path='/catalog/', method='GET', status_code=200)
        AuthEvent.objects.create(action=AuthEvent.Action.LOGIN, success=True, username='gamer')
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, 'copy.json')
            call_command('backup_data', output=target, with_logs=True)
            models = {item['model'] for item in self.read(target)}
            self.assertIn('activity.visitlog', models)
            self.assertIn('activity.authevent', models)

    def test_restore_brings_back_deleted_data(self):
        user, order = self.make_data()
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, 'copy.json')
            call_command('backup_data', output=target)

            Order.objects.all().delete()
            self.User.objects.all().delete()
            self.assertEqual(self.User.objects.count(), 0)
            self.assertEqual(Order.objects.count(), 0)

            call_command('restore_data', target)

            restored_user = self.User.objects.get(username='gamer')
            self.assertTrue(restored_user.check_password('strong-pass-2026'))
            self.assertEqual(restored_user.email, 'gamer@example.com')
            self.assertEqual(Profile.objects.filter(user=restored_user).count(), 1)
            self.assertEqual(Profile.objects.get(user=restored_user).city, 'Харків')

            restored_order = Order.objects.get(order_number=order.order_number)
            self.assertEqual(restored_order.user, restored_user)
            self.assertEqual(restored_order.total_amount, Decimal('1998.00'))
            self.assertEqual(restored_order.ip_address, '93.184.216.34')
            self.assertEqual(restored_order.items.count(), 1)
            self.assertEqual(restored_order.items.get().product, self.product)

    def test_restore_show_only_does_not_touch_database(self):
        self.make_data()
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, 'copy.json')
            call_command('backup_data', output=target)
            self.User.objects.all().delete()

            output = StringIO()
            call_command('restore_data', target, show=True, stdout=output)
            self.assertEqual(self.User.objects.count(), 0)
            self.assertIn('shop.order', output.getvalue())

    def test_restore_missing_file_raises(self):
        with self.assertRaises(CommandError):
            call_command('restore_data', 'no-such-backup.json')

    def test_restore_rejects_foreign_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, 'not-a-backup.json')
            with open(target, 'w', encoding='utf-8') as stream:
                stream.write('{"это": "не копия"}')
            with self.assertRaises(CommandError):
                call_command('restore_data', target)

class DatabaseUrlTests(TestCase):
    """Строка подключения к базе переживает кривое копирование и понятно ругается."""

    HOST = 'ep-test-1234.eu-central-1.aws.neon.tech'
    SECRET = 'npg_SuperSecret9182'

    def url(self, prefix='postgresql://', query='sslmode=require'):
        return f'{prefix}neondb_owner:{self.SECRET}@{self.HOST}/neondb?{query}'

    def test_clean_url_is_not_changed(self):
        url = self.url()
        self.assertEqual(validate_database_url(normalize_database_url(url)), url)

    def test_html_escaped_ampersand_is_fixed(self):
        url = self.url(query='sslmode=require&amp;channel_binding=require')
        fixed = validate_database_url(normalize_database_url(url))
        self.assertIn('sslmode=require&channel_binding=require', fixed)
        self.assertNotIn('&amp;', fixed)

    def test_missing_scheme_is_restored(self):
        url = self.url(prefix='://')
        fixed = validate_database_url(normalize_database_url(url))
        self.assertTrue(fixed.startswith('postgresql://neondb_owner:'))

    def test_variable_name_inside_value_is_stripped(self):
        url = 'DJANGO_DATABASE_URL=' + self.url()
        fixed = validate_database_url(normalize_database_url(url))
        self.assertTrue(fixed.startswith('postgresql://'))
        self.assertNotIn('DJANGO_DATABASE_URL', fixed)

    def test_quotes_spaces_and_line_breaks_are_removed(self):
        url = '  "' + self.url().replace(self.HOST, self.HOST + '\n') + '"  '
        fixed = validate_database_url(normalize_database_url(url))
        self.assertNotIn('"', fixed)
        self.assertNotIn('\n', fixed)
        self.assertNotIn(' ', fixed)
        self.assertTrue(fixed.startswith('postgresql://'))

    def test_markdown_link_is_rejected_with_clear_message(self):
        url = f'postgresql://neondb_owner:[{self.SECRET}@{self.HOST}](mailto:x)/neondb?sslmode=require'
        with self.assertRaises(ImproperlyConfigured) as caught:
            validate_database_url(normalize_database_url(url))
        self.assertIn('скопировано вместе с разметкой', str(caught.exception))

    def test_value_without_separator_is_rejected(self):
        url = f'neondb_owner:{self.SECRET}@{self.HOST}/neondb'
        with self.assertRaises(ImproperlyConfigured) as caught:
            validate_database_url(normalize_database_url(url))
        self.assertIn('нет схемы подключения', str(caught.exception))

    def test_unknown_scheme_is_rejected(self):
        url = self.url(prefix='mongodb://')
        with self.assertRaises(ImproperlyConfigured) as caught:
            validate_database_url(normalize_database_url(url))
        self.assertIn('mongodb', str(caught.exception))

    def test_error_messages_do_not_leak_password(self):
        broken = (
            f'postgresql://neondb_owner:[{self.SECRET}@{self.HOST}](mailto:x)/neondb',
            f'neondb_owner:{self.SECRET}@{self.HOST}/neondb',
            f'mongodb://neondb_owner:{self.SECRET}@{self.HOST}/neondb',
        )
        for url in broken:
            with self.assertRaises(ImproperlyConfigured) as caught:
                validate_database_url(normalize_database_url(url))
            self.assertNotIn(self.SECRET, str(caught.exception))

    def test_empty_value_is_allowed(self):
        self.assertEqual(normalize_database_url(''), '')
        self.assertEqual(validate_database_url(''), '')


class DbStatusCommandTests(TestCase):
    """Команда db_status сразу показывает, где живут данные."""

    def test_warns_about_sqlite(self):
        output = StringIO()
        call_command('db_status', stdout=output)
        text = output.getvalue()
        self.assertIn('SQLite', text)
        self.assertIn('DJANGO_DATABASE_URL', text)

    @override_settings(DATABASES={
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'neondb',
            'HOST': 'ep-test-1234.eu-central-1.aws.neon.tech',
            'USER': 'neondb_owner',
            'PASSWORD': 'secret',
            'PORT': '5432',
            'OPTIONS': {'sslmode': 'require'},
        },
    })
    def test_reports_external_database(self):
        output = StringIO()
        call_command('db_status', stdout=output)
        text = output.getvalue()
        self.assertIn('postgresql', text)
        self.assertIn('neondb', text)
        self.assertIn('сохраняются между перезапусками', text)

    def test_ping_reports_connection_error(self):
        with mock.patch('shop.management.commands.db_status.connection') as fake_connection:
            fake_connection.ensure_connection.side_effect = OperationalError('нет связи с базой')
            with self.assertRaises(CommandError) as caught:
                call_command('db_status', ping=True, stdout=StringIO())
        message = str(caught.exception)
        self.assertIn('Подключиться к базе не удалось', message)
        self.assertIn('DJANGO_DATABASE_URL', message)

    def test_ping_success_is_reported(self):
        output = StringIO()
        with mock.patch('shop.management.commands.db_status.connection') as fake_connection:
            fake_connection.ensure_connection.return_value = None
            call_command('db_status', ping=True, stdout=output)
        self.assertIn('Подключение к базе работает', output.getvalue())

class AdminThemeTests(TestCase):
    """Админ-панель оформлена в стиле магазина: тёмная тема и логотип."""

    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='strong-pass-2026',
        )
        self.theme_path = Path(__file__).resolve().parent / 'static' / 'shop' / 'css' / 'admin-theme.css'

    def test_login_page_is_themed(self):
        response = self.client.get('/admin/login/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'shop/css/admin-theme.css')
        self.assertContains(response, 'gzh-brand')
        self.assertContains(response, 'shop/images/logo.svg')
        self.assertContains(response, 'Inter')

    def test_admin_pages_include_theme(self):
        self.client.force_login(self.superuser)
        for url in ('/admin/', '/admin/shop/product/', '/admin/shop/order/',
                    '/admin/activity/visitlog/', '/admin/auth/user/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertContains(response, 'shop/css/admin-theme.css', msg_prefix=url)
            self.assertContains(response, 'gzh-shop-link', msg_prefix=url)

    def test_theme_uses_site_palette(self):
        css = self.theme_path.read_text(encoding='utf-8')
        site_css = (Path(__file__).resolve().parent / 'static' / 'shop' / 'css' / 'style.css').read_text(encoding='utf-8')
        for color in ('#0B0B10', '#15151F', '#292936', '#8B5CF6', '#A78BFA', '#22D3EE'):
            self.assertIn(color, css, f'в теме админки нет цвета {color}')
            self.assertIn(color, site_css, f'в теме магазина нет цвета {color}')
        self.assertIn("'Inter'", css)

    def test_theme_overrides_admin_variables(self):
        css = self.theme_path.read_text(encoding='utf-8')
        for variable in ('--primary', '--body-bg', '--body-fg', '--link-fg',
                         '--hairline-color', '--darkened-bg', '--header-bg'):
            self.assertIn(variable + ':', css, f'не переопределена переменная {variable}')

    def test_theme_is_forced_for_every_color_scheme(self):
        css = self.theme_path.read_text(encoding='utf-8')
        head = css.split('{', 1)[0]
        for selector in (':root', 'html[data-theme="light"]', 'html[data-theme="dark"]', 'html[data-theme="auto"]'):
            self.assertIn(selector, head)


class ReviewTests(TestCase):
    """Отзывы и рейтинги: пишут только покупатели, цифры считаются по базе."""

    def setUp(self):
        self.User = get_user_model()
        self.category = make_category()
        self.product = make_product(self.category, stock=10)
        self.other = make_product(
            self.category, name='Test Keyboard', slug='test-keyboard',
            price=Decimal('1999.00'), stock=20,
        )
        self.third = make_product(
            self.category, name='Test Headset', slug='test-headset',
            price=Decimal('2999.00'), stock=20,
        )
        self.buyer = self.User.objects.create_user(
            username='buyer', email='buyer@example.com', password='secret-pass-2026',
        )
        self.stranger = self.User.objects.create_user(
            username='stranger', email='stranger@example.com', password='secret-pass-2026',
        )
        self.superuser = self.User.objects.create_superuser(
            username='admin', email='admin@example.com', password='strong-pass-2026',
        )

    def buy(self, user, product, status=Order.Status.NEW):
        order = Order.objects.create(
            user=user, customer_name='Іван Петренко', phone='+380501112233',
            email='ivan@example.com', city='Харків', address='вул. Тестова, 1',
            status=status, total_amount=product.price,
        )
        OrderItem.objects.create(
            order=order, product=product, quantity=1, price=product.price,
        )
        return order

    def post_review(self, rating='5', text='Дуже зручна миша', user=None):
        if user is not None:
            self.client.force_login(user)
        return self.client.post(
            reverse('shop:review_add', args=[self.product.pk]),
            {'rating': rating, 'text': text},
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.post_review()
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('shop:login'), response.url)
        self.assertEqual(Review.objects.count(), 0)

    def test_review_requires_purchase(self):
        response = self.post_review(user=self.stranger)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Review.objects.count(), 0)
        texts = [m.message for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('заказывали этот товар' in t for t in texts), texts)

    def test_cancelled_order_does_not_allow_review(self):
        self.buy(self.buyer, self.product, status=Order.Status.CANCELLED)
        self.post_review(user=self.buyer)
        self.assertEqual(Review.objects.count(), 0)

    def test_buyer_creates_review(self):
        self.buy(self.buyer, self.product)
        response = self.post_review(user=self.buyer)
        self.assertEqual(response.status_code, 302)
        review = Review.objects.get()
        self.assertEqual(review.product, self.product)
        self.assertEqual(review.user, self.buyer)
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.text, 'Дуже зручна миша')
        self.assertTrue(review.is_visible)

    def test_second_post_updates_own_review(self):
        self.buy(self.buyer, self.product)
        self.post_review(user=self.buyer)
        self.post_review(rating='3', text='Гірше, ніж очікував', user=self.buyer)
        self.assertEqual(Review.objects.count(), 1)
        review = Review.objects.get()
        self.assertEqual(review.rating, 3)
        self.assertEqual(review.text, 'Гірше, ніж очікував')

    def test_review_of_another_user_is_not_touched(self):
        self.buy(self.buyer, self.product)
        self.buy(self.stranger, self.product)
        self.post_review(user=self.buyer)
        self.post_review(rating='2', text='Не зайшла', user=self.stranger)
        self.assertEqual(Review.objects.count(), 2)
        self.assertEqual(Review.objects.get(user=self.buyer).rating, 5)
        self.assertEqual(Review.objects.get(user=self.stranger).rating, 2)

    def test_invalid_rating_is_rejected(self):
        self.buy(self.buyer, self.product)
        for rating in ('6', '0', '', 'abc'):
            self.post_review(rating=rating, user=self.buyer)
            self.assertEqual(Review.objects.count(), 0, f'оценка {rating!r} прошла')

    def test_whitespace_text_is_stripped(self):
        self.buy(self.buyer, self.product)
        self.post_review(text='   \n  ', user=self.buyer)
        self.assertEqual(Review.objects.get().text, '')

    def test_get_request_is_not_allowed(self):
        self.buy(self.buyer, self.product)
        self.client.force_login(self.buyer)
        response = self.client.get(reverse('shop:review_add', args=[self.product.pk]))
        self.assertEqual(response.status_code, 405)

    def test_one_review_per_product_per_user(self):
        self.buy(self.buyer, self.product)
        Review.objects.create(product=self.product, user=self.buyer, rating=5)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Review.objects.create(product=self.product, user=self.buyer, rating=4)

    def test_rating_average_counts_visible_reviews_only(self):
        Review.objects.create(product=self.product, user=self.buyer, rating=5)
        Review.objects.create(product=self.product, user=self.stranger, rating=3)
        hidden = Review.objects.create(
            product=self.product, user=self.superuser, rating=1, is_visible=False,
        )
        self.assertEqual(self.product.rating_average(), Decimal('4.0'))
        self.assertEqual(self.product.rating_count(), 2)
        hidden.is_visible = True
        hidden.save()
        self.assertEqual(self.product.rating_average(), Decimal('3.0'))
        self.assertEqual(self.product.rating_count(), 3)

    def test_product_page_shows_reviews(self):
        self.buy(self.buyer, self.product)
        Review.objects.create(
            product=self.product, user=self.buyer, rating=4, text='Тримає руку добре',
        )
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, 'Отзывы покупателей')
        self.assertContains(response, 'Тримає руку добре')
        self.assertContains(response, 'buyer')
        self.assertContains(response, 'class="stars"')
        self.assertContains(response, '4,0')

    def test_hidden_review_is_not_shown(self):
        Review.objects.create(
            product=self.product, user=self.buyer, rating=5,
            text='Секретний текст', is_visible=False,
        )
        response = self.client.get(self.product.get_absolute_url())
        self.assertNotContains(response, 'Секретний текст')
        self.assertContains(response, 'Отзывов пока нет')

    def test_product_without_reviews_shows_empty_state(self):
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, 'Отзывов пока нет')
        self.assertContains(response, 'Войдите')

    def test_buyer_sees_review_form(self):
        self.buy(self.buyer, self.product)
        self.client.force_login(self.buyer)
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, 'Оставить отзыв')
        self.assertContains(response, reverse('shop:review_add', args=[self.product.pk]))

    def test_catalog_shows_rating(self):
        Review.objects.create(product=self.product, user=self.buyer, rating=5)
        response = self.client.get(reverse('shop:catalog'))
        self.assertContains(response, 'class="stars"')
        self.assertContains(response, '5,0')
        self.assertContains(response, '1 отзыв')

    def test_sorting_by_rating(self):
        Review.objects.create(product=self.product, user=self.buyer, rating=5)
        Review.objects.create(product=self.other, user=self.stranger, rating=3)
        response = self.client.get(reverse('shop:catalog'), {'sort': 'rating'})
        names = [p.name for p in response.context['products']]
        self.assertEqual(names, ['Test Mouse', 'Test Keyboard', 'Test Headset'])

    def test_rating_is_available_in_annotated_queryset(self):
        Review.objects.create(product=self.product, user=self.buyer, rating=4)
        annotated = with_rating(Product.objects.all()).get(pk=self.product.pk)
        self.assertEqual(float(annotated.rating_avg), 4.0)
        self.assertEqual(annotated.rating_count, 1)

    def test_plural_ru_filter(self):
        cases = {
            0: 'отзывов', 1: 'отзыв', 2: 'отзыва', 4: 'отзыва', 5: 'отзывов',
            11: 'отзывов', 12: 'отзывов', 21: 'отзыв', 22: 'отзыва',
            25: 'отзывов', 100: 'отзывов', 101: 'отзыв', 111: 'отзывов',
        }
        for number, expected in cases.items():
            self.assertEqual(plural_ru(number, 'отзыв,отзыва,отзывов'), expected, number)

    def test_admin_review_list_requires_staff(self):
        response = self.client.get('/admin/shop/review/')
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.buyer)
        response = self.client.get('/admin/shop/review/')
        self.assertEqual(response.status_code, 302)

    def test_admin_can_hide_reviews(self):
        review = Review.objects.create(product=self.product, user=self.buyer, rating=5)
        self.client.force_login(self.superuser)
        response = self.client.post('/admin/shop/review/', {
            'action': 'make_hidden',
            'index': '0',
            '_selected_action': [str(review.pk)],
        })
        self.assertEqual(response.status_code, 302)
        review.refresh_from_db()
        self.assertFalse(review.is_visible)

    def test_admin_changelist_shows_rating(self):
        Review.objects.create(product=self.product, user=self.buyer, rating=5)
        self.client.force_login(self.superuser)
        response = self.client.get('/admin/shop/product/')
        self.assertContains(response, 'gzh-rating')
        self.assertContains(response, '5,0')


class CsvExportTests(TestCase):
    """Выгрузка в CSV: файл открывается в Excel, фильтры списка учитываются."""

    def setUp(self):
        self.User = get_user_model()
        self.category = make_category()
        self.product = make_product(self.category, stock=3)
        self.superuser = self.User.objects.create_superuser(
            username='admin', email='admin@example.com', password='strong-pass-2026',
        )
        self.order = Order.objects.create(
            customer_name='Іван Петренко', phone='+380501112233',
            email='ivan@example.com', city='Харків',
            address='вул. Тестова, 1; кв. 2', total_amount=Decimal('1998.00'),
        )
        OrderItem.objects.create(
            order=self.order, product=self.product, quantity=2, price=Decimal('999.00'),
        )
        self.client.force_login(self.superuser)

    def run_action(self, url, action='export_csv', objects=None, query=''):
        objects = objects or [self.product.pk]
        return self.client.post(
            url + query,
            {'action': action, 'index': '0', '_selected_action': [str(pk) for pk in objects]},
        )

    def read_csv(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])
        self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
        self.assertTrue(response.content.startswith('\ufeff'.encode('utf-8')))
        text = response.content.decode('utf-8-sig')
        return list(csv.reader(text.splitlines(), delimiter=';'))

    def test_products_export(self):
        response = self.run_action('/admin/shop/product/')
        self.assertIn('products-', response['Content-Disposition'])
        self.assertIn('.csv', response['Content-Disposition'])
        rows = self.read_csv(response)
        self.assertEqual(rows[0][0], 'Товар')
        self.assertIn('Остаток, шт.', rows[0])
        self.assertEqual(rows[1][0], 'Test Mouse')
        self.assertEqual(rows[1][2], '999.00')
        self.assertEqual(rows[1][3], '3')
        self.assertEqual(rows[1][4], 'да')
        self.assertEqual(len(rows), 2)

    def test_export_respects_changelist_filter(self):
        second = make_product(
            self.category, name='Test Keyboard', slug='test-keyboard', stock=50,
        )
        response = self.run_action(
            '/admin/shop/product/', objects=[self.product.pk, second.pk],
            query='?stock_status=low',
        )
        rows = self.read_csv(response)
        names = [row[0] for row in rows[1:]]
        self.assertEqual(names, ['Test Mouse'])

    def test_export_uses_semicolon_and_escapes_quotes(self):
        rows = self.read_csv(self.run_action('/admin/shop/order/'))
        self.assertEqual(rows[0][6], 'Город')
        self.assertIn('вул. Тестова, 1; кв. 2', rows[1])

    def test_orders_export_contains_items(self):
        rows = self.read_csv(self.run_action('/admin/shop/order/'))
        headers = rows[0]
        self.assertIn('Номер заказа', headers)
        self.assertIn('IP-адрес', headers)
        row = dict(zip(headers, rows[1]))
        self.assertEqual(row['Покупатель'], 'Іван Петренко')
        self.assertEqual(row['Статус'], 'Новый')
        self.assertEqual(row['Сумма, ₴'], '1998.00')
        self.assertEqual(row['Состав заказа'], 'Test Mouse × 2')

    def test_order_items_export(self):
        rows = self.read_csv(
            self.run_action('/admin/shop/order/', action='export_items_csv')
        )
        self.assertEqual(rows[0][0], 'Номер заказа')
        self.assertIn('Количество', rows[0])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][7], 'Test Mouse')
        self.assertEqual(rows[1][9], '2')
        self.assertEqual(rows[1][11], '1998.00')

    def test_reviews_export(self):
        Review.objects.create(
            product=self.product, user=self.superuser, rating=4, text='Зручно',
        )
        rows = self.read_csv(self.run_action('/admin/shop/review/', objects=[1]))
        self.assertEqual(rows[0][0], 'Товар')
        self.assertEqual(rows[1][0], 'Test Mouse')
        self.assertEqual(rows[1][4], '4')
        self.assertEqual(rows[1][5], 'Зручно')

    def test_activity_log_export(self):
        VisitLog.objects.create(
            ip_address='93.184.216.34', path='/catalog/', method='GET',
            status_code=200, browser='Chrome', os='Windows',
        )
        rows = self.read_csv(self.run_action('/admin/activity/visitlog/', objects=[1]))
        self.assertEqual(rows[0][1], 'IP-адрес')
        self.assertEqual(rows[1][1], '93.184.216.34')
        self.assertEqual(rows[1][3], '/catalog/')

    def test_view_only_staff_can_export(self):
        staff = self.User.objects.create_user(
            username='viewer', password='strong-pass-2026', is_staff=True,
        )
        staff.user_permissions.add(
            Permission.objects.get(codename='view_product', content_type__app_label='shop'),
        )
        self.client.force_login(staff)
        rows = self.read_csv(self.run_action('/admin/shop/product/'))
        self.assertEqual(rows[1][0], 'Test Mouse')

    def test_export_is_closed_for_regular_users(self):
        buyer = self.User.objects.create_user(
            username='buyer', password='strong-pass-2026',
        )
        self.client.force_login(buyer)
        response = self.run_action('/admin/shop/product/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response.url)

    def test_csv_filename_is_ascii(self):
        response = self.run_action('/admin/shop/product/')
        filename = response['Content-Disposition'].split('filename="')[1].rstrip('"')
        self.assertTrue(filename.isascii(), filename)

    def test_empty_selection_is_reported(self):
        response = self.client.post('/admin/shop/product/', {
            'action': 'export_csv', 'index': '0', '_selected_action': [],
        })
        self.assertEqual(response.status_code, 302)


class LowStockAdminTests(TestCase):
    """Метка низкого остатка: видна в списке товаров и фильтруется."""

    def setUp(self):
        self.User = get_user_model()
        self.superuser = self.User.objects.create_superuser(
            username='admin', email='admin@example.com', password='strong-pass-2026',
        )
        self.category = make_category()
        self.low = make_product(self.category, stock=LOW_STOCK_THRESHOLD)
        self.enough = make_product(
            self.category, name='Test Keyboard', slug='test-keyboard', stock=50,
        )
        self.empty = make_product(
            self.category, name='Test Headset', slug='test-headset', stock=0,
        )
        self.off = make_product(
            self.category, name='Test Pad', slug='test-pad', stock=7, is_available=False,
        )
        self.client.force_login(self.superuser)

    def test_threshold_is_shared_with_dashboard(self):
        self.assertEqual(LOW_STOCK_THRESHOLD, DASHBOARD_LOW_STOCK_THRESHOLD)
        self.assertTrue(self.low.is_low_stock)
        self.assertFalse(self.enough.is_low_stock)
        self.assertFalse(self.empty.is_low_stock)

    def test_changelist_marks_low_stock(self):
        response = self.client.get('/admin/shop/product/')
        self.assertContains(response, 'gzh-stock--low')
        self.assertContains(response, 'Заканчивается')
        self.assertContains(response, 'gzh-stock--ok')
        self.assertContains(response, 'gzh-stock--out')
        self.assertContains(response, 'gzh-stock--off')

    def test_filter_low_stock(self):
        response = self.client.get('/admin/shop/product/', {'stock_status': 'low'})
        names = [obj.name for obj in response.context['cl'].result_list]
        self.assertEqual(names, ['Test Mouse'])

    def test_filter_out_of_stock(self):
        response = self.client.get('/admin/shop/product/', {'stock_status': 'out'})
        names = [obj.name for obj in response.context['cl'].result_list]
        self.assertEqual(names, ['Test Headset'])

    def test_filter_disabled_products(self):
        response = self.client.get('/admin/shop/product/', {'stock_status': 'off'})
        names = [obj.name for obj in response.context['cl'].result_list]
        self.assertEqual(names, ['Test Pad'])

    def test_filter_enough_stock(self):
        response = self.client.get('/admin/shop/product/', {'stock_status': 'ok'})
        names = [obj.name for obj in response.context['cl'].result_list]
        self.assertEqual(names, ['Test Keyboard'])

    def test_product_form_warns_about_low_stock(self):
        response = self.client.get(f'/admin/shop/product/{self.low.pk}/change/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'товар заканчивается')

    def test_product_form_without_warning_for_enough_stock(self):
        response = self.client.get(f'/admin/shop/product/{self.enough.pk}/change/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'товар заканчивается')
        self.assertContains(response, f'при остатке {LOW_STOCK_THRESHOLD} шт.')


class TemplateIntegrityTests(TestCase):
    """Шаблоны не содержат незакрытых тегов и не выводят их как текст."""

    def template_files(self):
        shop_dir = Path(__file__).resolve().parent
        project_dir = shop_dir.parent
        files = sorted((shop_dir / 'templates').rglob('*.html'))
        files += sorted((project_dir / 'templates').rglob('*.html'))
        self.assertTrue(files, 'шаблоны не найдены')
        return files

    def test_tags_are_balanced(self):
        for path in self.template_files():
            text = path.read_text(encoding='utf-8')
            for open_tag, close_tag in (('{%', '%}'), ('{{', '}}'), ('{#', '#}')):
                self.assertEqual(
                    text.count(open_tag), text.count(close_tag),
                    f'{path.name}: «{open_tag}» и «{close_tag}» не совпадают',
                )
            self.assertNotIn('%>', text, f'{path.name}: «%>» вместо «%}}»')
            self.assertNotIn('}}', text.replace('{{', '').replace('}}', ''),
                             f'{path.name}: лишняя «}}}}»')

    def test_public_pages_render_without_literal_tags(self):
        pages = (
            'shop:home', 'shop:catalog', 'shop:categories', 'shop:about',
            'shop:contacts', 'shop:cart', 'shop:login', 'shop:register',
        )
        for name in pages:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            html = response.content.decode()
            self.assertNotIn('{%', html, f'{name}: тег выведен как текст')
            self.assertNotIn('{{', html, f'{name}: переменная выведена как текст')

    def test_product_page_renders_all_icons(self):
        product = make_product(make_category())
        response = self.client.get(product.get_absolute_url())
        html = response.content.decode()
        self.assertNotIn('{%', html)
        self.assertNotIn('{{', html)
        self.assertNotIn('%>', html)
        self.assertIn('Цена фиксируется на момент оформления заказа', html)
        self.assertIn('Данные заказа проверяются на сервере', html)

    def test_authenticated_pages_render_without_literal_tags(self):
        product = make_product(make_category(), stock=5)
        user = get_user_model().objects.create_user(
            username='buyer', email='buyer@example.com', password='secret-pass-2026',
        )
        self.client.force_login(user)
        self.client.post(reverse('shop:cart_add', args=[product.pk]), {'quantity': 1})
        for name in ('shop:profile', 'shop:profile_edit', 'shop:password_change', 'shop:checkout', 'shop:cart'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            html = response.content.decode()
            self.assertNotIn('{%', html, f'{name}: тег выведен как текст')
            self.assertNotIn('{{', html, f'{name}: переменная выведена как текст')


class CouponModelTests(TestCase):
    """Промокод: размер скидки, срок действия и лимит применений."""

    def make_coupon(self, **kwargs):
        defaults = {
            'code': 'GAME10',
            'kind': Coupon.Kind.PERCENT,
            'value': Decimal('10'),
        }
        defaults.update(kwargs)
        return Coupon.objects.create(**defaults)

    def test_percent_discount(self):
        coupon = self.make_coupon()
        self.assertEqual(coupon.discount_for(Decimal('2000')), Decimal('200.00'))

    def test_percent_discount_is_rounded(self):
        coupon = self.make_coupon(value=Decimal('7.5'))
        self.assertEqual(coupon.discount_for(Decimal('1999')), Decimal('149.93'))

    def test_fixed_discount(self):
        coupon = self.make_coupon(kind=Coupon.Kind.FIXED, value=Decimal('250'))
        self.assertEqual(coupon.discount_for(Decimal('1000')), Decimal('250.00'))

    def test_discount_is_never_more_than_total(self):
        coupon = self.make_coupon(kind=Coupon.Kind.FIXED, value=Decimal('500'))
        self.assertEqual(coupon.discount_for(Decimal('120')), Decimal('120.00'))

    def test_min_total_blocks_small_orders(self):
        coupon = self.make_coupon(min_total=Decimal('1500'))
        self.assertEqual(coupon.discount_for(Decimal('1000')), Decimal('0.00'))
        self.assertEqual(coupon.discount_for(Decimal('1500')), Decimal('150.00'))

    def test_code_is_normalized(self):
        coupon = Coupon.objects.create(code='  game10 ', value=Decimal('5'))
        self.assertEqual(coupon.code, 'GAME10')

    def test_disabled_coupon(self):
        coupon = self.make_coupon(is_active=False)
        self.assertFalse(coupon.is_available())
        self.assertEqual(coupon.unavailable_reason(), 'Промокод отключён.')

    def test_expired_coupon(self):
        coupon = self.make_coupon(valid_until=timezone.now() - timedelta(days=1))
        self.assertFalse(coupon.is_available())
        self.assertEqual(coupon.unavailable_reason(), 'Срок действия промокода истёк.')

    def test_not_started_coupon(self):
        coupon = self.make_coupon(valid_from=timezone.now() + timedelta(days=1))
        self.assertFalse(coupon.is_available())
        self.assertEqual(coupon.unavailable_reason(), 'Срок действия промокода ещё не начался.')

    def test_usage_limit(self):
        coupon = self.make_coupon(usage_limit=2, used_count=2)
        self.assertFalse(coupon.is_available())
        self.assertEqual(coupon.unavailable_reason(), 'Лимит применений промокода исчерпан.')

    def test_coupon_without_limits(self):
        coupon = self.make_coupon()
        self.assertTrue(coupon.is_available())
        self.assertEqual(coupon.unavailable_reason(), '')


class CartCouponTests(TestCase):
    """Применение промокода в корзине: всё проверяется на сервере."""

    def setUp(self):
        self.category = make_category()
        self.product = make_product(self.category, price=Decimal('1000'), stock=20)
        self.coupon = Coupon.objects.create(
            code='GAME10', kind=Coupon.Kind.PERCENT, value=Decimal('10'),
        )

    def add_to_cart(self, quantity=2):
        return self.client.post(
            reverse('shop:cart_add', args=[self.product.pk]), {'quantity': quantity},
        )

    def apply(self, code):
        return self.client.post(reverse('shop:coupon_apply'), {'code': code}, follow=True)

    def test_apply_valid_coupon(self):
        self.add_to_cart()
        response = self.apply('game10')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['coupon_code'], 'GAME10')
        self.assertContains(response, 'coupon-code')
        self.assertContains(response, 'GAME10')
        self.assertContains(response, '1800'.replace('1800', '1 800'))

    def test_discount_is_computed_from_cart_total(self):
        self.add_to_cart()
        self.apply('GAME10')
        cart = Cart(self.client)
        self.assertEqual(cart.get_total_price(), Decimal('2000.00'))
        self.assertEqual(cart.get_discount(), Decimal('200.00'))
        self.assertEqual(cart.get_payable_total(), Decimal('1800.00'))

    def test_unknown_coupon(self):
        self.add_to_cart()
        response = self.apply('NOPE')
        self.assertNotIn('coupon_code', self.client.session)
        self.assertContains(response, 'не найден')

    def test_expired_coupon_message(self):
        self.coupon.valid_until = timezone.now() - timedelta(hours=1)
        self.coupon.save()
        self.add_to_cart()
        response = self.apply('GAME10')
        self.assertNotIn('coupon_code', self.client.session)
        self.assertContains(response, 'истёк')

    def test_min_total_message(self):
        self.coupon.min_total = Decimal('5000')
        self.coupon.save()
        self.add_to_cart(1)
        response = self.apply('GAME10')
        self.assertNotIn('coupon_code', self.client.session)
        self.assertContains(response, 'действует от')

    def test_invalid_code_format(self):
        self.add_to_cart()
        response = self.apply('промокод!')
        self.assertNotIn('coupon_code', self.client.session)
        self.assertContains(response, 'латинских букв')

    def test_coupon_can_be_removed(self):
        self.add_to_cart()
        self.apply('GAME10')
        response = self.client.post(reverse('shop:coupon_remove'), follow=True)
        self.assertNotIn('coupon_code', self.client.session)
        self.assertContains(response, 'Промокод снят')

    def test_clearing_cart_drops_coupon(self):
        self.add_to_cart()
        self.apply('GAME10')
        self.client.post(reverse('shop:cart_clear'))
        self.assertNotIn('coupon_code', self.client.session)

    def test_stale_coupon_is_dropped(self):
        """Если промокод отключили после применения, скидка не действует."""
        self.add_to_cart()
        self.apply('GAME10')
        self.coupon.is_active = False
        self.coupon.save()
        cart = Cart(self.client)
        self.assertIsNone(cart.get_coupon())
        self.assertEqual(cart.get_discount(), Decimal('0.00'))

    def test_coupon_get_request_is_not_allowed(self):
        response = self.client.get(reverse('shop:coupon_apply'))
        self.assertEqual(response.status_code, 405)


class CheckoutCouponTests(TestCase):
    """Скидка фиксируется в заказе, а лимит применений не превышается."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='buyer', email='buyer@example.com', password='secret-pass-2026',
        )
        self.category = make_category()
        self.product = make_product(self.category, price=Decimal('1000'), stock=20)
        self.coupon = Coupon.objects.create(
            code='GAME10', kind=Coupon.Kind.PERCENT, value=Decimal('10'),
        )
        self.client.force_login(self.user)

    def prepare_cart(self, quantity=2, code='GAME10'):
        self.client.post(reverse('shop:cart_add', args=[self.product.pk]), {'quantity': quantity})
        if code:
            self.client.post(reverse('shop:coupon_apply'), {'code': code})

    def checkout(self):
        return self.client.post(reverse('shop:checkout'), {
            'customer_name': 'Олена Коваль',
            'phone': '+380671234567',
            'email': 'buyer@example.com',
            'city': 'Харків',
            'address': 'вул. Сумська, 10',
            'comment': '',
        })

    def test_discount_is_saved_in_order(self):
        self.prepare_cart()
        response = self.checkout()
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.discount_amount, Decimal('200.00'))
        self.assertEqual(order.total_amount, Decimal('1800.00'))
        self.assertEqual(order.coupon, self.coupon)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.used_count, 1)

    def test_cart_is_cleared_with_coupon_after_order(self):
        self.prepare_cart()
        self.checkout()
        self.assertNotIn('coupon_code', self.client.session)

    def test_order_without_coupon(self):
        self.prepare_cart(code=None)
        self.checkout()
        order = Order.objects.get()
        self.assertEqual(order.discount_amount, Decimal('0.00'))
        self.assertEqual(order.total_amount, Decimal('2000.00'))
        self.assertIsNone(order.coupon)

    def test_usage_limit_is_respected(self):
        self.coupon.usage_limit = 1
        self.coupon.save()
        self.prepare_cart()
        self.checkout()
        first = Order.objects.get()
        self.assertEqual(first.discount_amount, Decimal('200.00'))

        self.client.post(reverse('shop:cart_add', args=[self.product.pk]), {'quantity': 1})
        self.client.post(reverse('shop:coupon_apply'), {'code': 'GAME10'})
        self.checkout()
        second = Order.objects.exclude(pk=first.pk).get()
        self.assertEqual(second.discount_amount, Decimal('0.00'))
        self.assertEqual(second.total_amount, Decimal('1000.00'))
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.used_count, 1)

    def test_checkout_page_shows_discount(self):
        self.prepare_cart()
        response = self.client.get(reverse('shop:checkout'))
        self.assertContains(response, 'Скидка по промокоду')
        self.assertContains(response, '1 800')

    def test_disabled_coupon_is_ignored_at_checkout(self):
        self.prepare_cart()
        self.coupon.is_active = False
        self.coupon.save()
        self.checkout()
        order = Order.objects.get()
        self.assertEqual(order.discount_amount, Decimal('0.00'))
        self.assertEqual(order.total_amount, Decimal('2000.00'))


class OrderLifecycleTests(TestCase):
    """Жизнь заказа в кабинете: статусы, отмена и возврат товаров на склад."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='buyer', email='buyer@example.com', password='secret-pass-2026',
        )
        self.other = self.User.objects.create_user(
            username='other', email='other@example.com', password='secret-pass-2026',
        )
        self.staff = self.User.objects.create_superuser(
            username='admin', email='admin@example.com', password='strong-pass-2026',
        )
        self.category = make_category()
        self.product = make_product(self.category, price=Decimal('1000'), stock=10)
        self.coupon = Coupon.objects.create(
            code='GAME10', value=Decimal('10'), usage_limit=5, used_count=1,
        )
        self.order = Order.objects.create(
            user=self.user,
            customer_name='Олена Коваль',
            phone='+380671234567',
            email='buyer@example.com',
            city='Харків',
            address='вул. Сумська, 10',
            status=Order.Status.NEW,
            coupon=self.coupon,
            discount_amount=Decimal('100.00'),
            total_amount=Decimal('1900.00'),
        )
        OrderItem.objects.create(
            order=self.order, product=self.product,
            quantity=2, price=Decimal('1000.00'),
        )

    def url(self):
        return reverse('shop:order_detail', args=[self.order.order_number])

    def test_order_detail_shows_status_and_items(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, 'Test Mouse')
        self.assertContains(response, 'Заказ оформлен')
        self.assertContains(response, '1 900')
        self.assertContains(response, 'GAME10')

    def test_order_detail_requires_login(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('shop:login'), response.url)

    def test_order_detail_is_closed_for_other_users(self):
        self.client.force_login(self.other)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 404)

    def test_timeline_marks_current_step(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url())
        steps = response.context['order'].status_timeline()
        self.assertEqual([step['state'] for step in steps], ['current', 'next', 'next', 'next'])
        self.assertEqual(steps[0]['label'], 'Заказ оформлен')

    def test_timeline_after_confirmation(self):
        self.order.status = Order.Status.CONFIRMED
        self.order.save()
        steps = self.order.status_timeline()
        self.assertEqual([step['state'] for step in steps], ['done', 'current', 'next', 'next'])

    def test_cancel_restores_stock_and_status(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('shop:order_cancel', args=[self.order.order_number]))
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.coupon.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(self.product.stock, 12)
        self.assertEqual(self.coupon.used_count, 0)

    def test_cancelled_order_shows_cancelled_step(self):
        self.client.force_login(self.user)
        self.client.post(reverse('shop:order_cancel', args=[self.order.order_number]))
        response = self.client.get(self.url())
        self.assertContains(response, 'Отменён')
        self.assertNotContains(response, 'Отменить заказ')
        self.assertContains(response, 'товары возвращены на склад')

    def test_shipped_order_cannot_be_cancelled(self):
        self.order.status = Order.Status.SHIPPED
        self.order.save()
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('shop:order_cancel', args=[self.order.order_number]), follow=True,
        )
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SHIPPED)
        self.assertEqual(self.product.stock, 10)
        self.assertContains(response, 'передан в доставку')

    def test_cancel_of_other_users_order_is_not_possible(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse('shop:order_cancel', args=[self.order.order_number]))
        self.assertEqual(response.status_code, 404)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.NEW)

    def test_cancel_requires_post(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('shop:order_cancel', args=[self.order.order_number]))
        self.assertEqual(response.status_code, 405)

    def test_profile_shows_timeline_and_links(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('shop:profile'))
        self.assertContains(response, 'order-timeline')
        self.assertContains(response, self.url())
        self.assertContains(response, reverse('shop:order_receipt', args=[self.order.order_number]))


class ReceiptTests(TestCase):
    """Печатный чек доступен владельцу, персоналу и сессии после покупки."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='buyer', email='buyer@example.com', password='secret-pass-2026',
        )
        self.other = self.User.objects.create_user(
            username='other', password='secret-pass-2026',
        )
        self.staff = self.User.objects.create_superuser(
            username='admin', email='admin@example.com', password='strong-pass-2026',
        )
        self.category = make_category()
        self.product = make_product(self.category, price=Decimal('1500'))
        self.coupon = Coupon.objects.create(code='SAVE200', kind=Coupon.Kind.FIXED, value=Decimal('200'))
        self.order = Order.objects.create(
            user=self.user, customer_name='Олена Коваль', phone='+380671234567',
            email='buyer@example.com', city='Харків', address='вул. Сумська, 10',
            coupon=self.coupon, discount_amount=Decimal('200.00'),
            total_amount=Decimal('1300.00'),
        )
        OrderItem.objects.create(
            order=self.order, product=self.product, quantity=1, price=Decimal('1500.00'),
        )

    def url(self):
        return reverse('shop:order_receipt', args=[self.order.order_number])

    def test_owner_sees_receipt(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, 'Test Mouse')
        self.assertContains(response, 'SAVE200')
        self.assertContains(response, '1 300')
        self.assertContains(response, 'window.print()')

    def test_other_user_gets_404(self):
        self.client.force_login(self.other)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 404)

    def test_session_after_checkout_opens_receipt(self):
        session = self.client.session
        session['last_order_id'] = self.order.pk
        session.save()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)

    def test_guest_without_session_gets_404(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 404)

    def test_staff_sees_any_receipt(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)

    def test_unknown_order_number_is_404(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('shop:order_receipt', args=['GZ-19700101-000000-ZZZZ'])
        )
        self.assertEqual(response.status_code, 404)


class WishlistTests(TestCase):
    """Избранное: хранение в сессии, страница и счётчик в шапке."""

    def setUp(self):
        self.category = make_category()
        self.product = make_product(self.category, name='Test Mouse')
        self.other = make_product(self.category, name='Test Keyboard', slug='test-keyboard')

    def toggle(self, product=None):
        product = product or self.product
        return self.client.post(reverse('shop:favorite_toggle', args=[product.pk]), follow=True)

    def test_toggle_adds_product(self):
        response = self.toggle()
        self.assertEqual(self.client.session['favorites'], [self.product.pk])
        self.assertContains(response, 'добавлен в избранное')

    def test_toggle_removes_product(self):
        self.toggle()
        response = self.toggle()
        self.assertEqual(self.client.session['favorites'], [])
        self.assertContains(response, 'убран из избранного')

    def test_wishlist_page_lists_products(self):
        self.toggle()
        response = self.client.get(reverse('shop:wishlist'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Mouse')
        self.assertNotContains(response, 'Test Keyboard')

    def test_wishlist_empty_state(self):
        response = self.client.get(reverse('shop:wishlist'))
        self.assertContains(response, 'В избранном пока пусто')

    def test_header_shows_favorites_count(self):
        self.toggle()
        response = self.client.get(reverse('shop:home'))
        self.assertEqual(response.context['favorite_count'], 1)
        self.assertContains(response, 'Избранное, товаров: 1')

    def test_card_marks_favorite(self):
        self.toggle()
        response = self.client.get(reverse('shop:catalog'))
        self.assertContains(response, 'fav-btn--active')

    def test_toggle_requires_post(self):
        response = self.client.get(reverse('shop:favorite_toggle', args=[self.product.pk]))
        self.assertEqual(response.status_code, 405)

    def test_toggle_unknown_product(self):
        response = self.client.post(reverse('shop:favorite_toggle', args=[999999]))
        self.assertEqual(response.status_code, 404)

    def test_toggle_returns_to_previous_page(self):
        response = self.client.post(
            reverse('shop:favorite_toggle', args=[self.product.pk]),
            {'next': reverse('shop:catalog')},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('shop:catalog'))

    def test_foreign_redirect_is_ignored(self):
        response = self.client.post(
            reverse('shop:favorite_toggle', args=[self.product.pk]),
            {'next': 'https://evil.example/phish'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('evil.example', response.url)


class BoughtTogetherTests(TestCase):
    """Подборка «С этим покупают» строится только по реальным заказам."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='buyer', password='secret-pass-2026',
        )
        self.category = make_category()
        self.main = make_product(self.category, name='Main Mouse', slug='main-mouse')
        self.often = make_product(self.category, name='Often Keyboard', slug='often-keyboard')
        self.rare = make_product(self.category, name='Rare Headset', slug='rare-headset')

    def make_order(self, products, status=Order.Status.COMPLETED, user=None):
        order = Order.objects.create(
            user=user or self.user,
            customer_name='Олена', phone='+380671234567', city='Харків',
            address='вул. Сумська, 10', status=status,
        )
        for product in products:
            OrderItem.objects.create(order=order, product=product, quantity=1, price=product.price)
        return order

    def test_empty_without_orders(self):
        self.assertEqual(list(bought_together(self.main)), [])

    def test_finds_product_from_same_order(self):
        self.make_order([self.main, self.often])
        result = list(bought_together(self.main))
        self.assertEqual([product.name for product in result], ['Often Keyboard'])

    def test_excludes_the_product_itself(self):
        self.make_order([self.main, self.often])
        self.make_order([self.main])
        result = list(bought_together(self.main))
        self.assertNotIn(self.main, result)

    def test_cancelled_orders_are_ignored(self):
        self.make_order([self.main, self.rare], status=Order.Status.CANCELLED)
        self.assertEqual(list(bought_together(self.main)), [])

    def test_more_frequent_pairs_come_first(self):
        self.make_order([self.main, self.rare])
        self.make_order([self.main, self.often])
        self.make_order([self.main, self.often])
        result = list(bought_together(self.main))
        self.assertEqual([product.name for product in result], ['Often Keyboard', 'Rare Headset'])

    def test_unavailable_products_are_hidden(self):
        self.make_order([self.main, self.rare])
        self.rare.is_available = False
        self.rare.save()
        self.assertEqual(list(bought_together(self.main)), [])

    def test_block_is_rendered_on_product_page(self):
        self.make_order([self.main, self.often])
        response = self.client.get(self.main.get_absolute_url())
        self.assertContains(response, 'С этим покупают')
        self.assertContains(response, 'Often Keyboard')

    def test_block_is_hidden_without_pairs(self):
        response = self.client.get(self.main.get_absolute_url())
        self.assertNotContains(response, 'С этим покупают')

    def test_products_carry_rating_annotations(self):
        self.make_order([self.main, self.often])
        Review.objects.create(product=self.often, user=self.user, rating=5)
        result = list(bought_together(self.main))
        self.assertEqual(float(result[0].rating_avg), 5.0)
        self.assertEqual(result[0].rating_count, 1)


@override_settings(MAILERS={
    'default': {
        'BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
        'OPTIONS': {},
    },
})
class PasswordResetTests(TestCase):
    """Восстановление пароля по email: письмо, ссылка и смена пароля."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='buyer', email='buyer@example.com', password='secret-pass-2026',
        )

    def request_reset(self, email='buyer@example.com'):
        return self.client.post(reverse('shop:password_reset'), {'email': email})

    def test_reset_form_is_available(self):
        response = self.client.get(reverse('shop:password_reset'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Восстановление пароля')

    def test_login_page_links_to_reset(self):
        response = self.client.get(reverse('shop:login'))
        self.assertContains(response, reverse('shop:password_reset'))

    def test_email_is_sent_for_existing_account(self):
        response = self.request_reset()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('shop:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('GameZone', mail.outbox[0].subject)
        self.assertIn('buyer@example.com', mail.outbox[0].to)
        self.assertIn(reverse('shop:password_reset'), mail.outbox[0].body)

    def test_unknown_email_does_not_reveal_accounts(self):
        response = self.request_reset('nobody@example.com')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_full_reset_flow_changes_password(self):
        self.request_reset()
        link = re.search(r'https?://\S+', mail.outbox[0].body).group(0)
        path = link.split('testserver', 1)[1]

        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        set_password_url = response.url

        response = self.client.get(set_password_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Новый пароль')

        response = self.client.post(set_password_url, {
            'new_password1': 'New-Secret-2026',
            'new_password2': 'New-Secret-2026',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('shop:password_reset_complete'))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('New-Secret-2026'))
        self.assertTrue(self.client.login(username='buyer', password='New-Secret-2026'))

    def test_invalid_token_shows_error(self):
        url = reverse('shop:password_reset_confirm', kwargs={
            'uidb64': 'MQ', 'token': 'invalid-token-value',
        })
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ссылка недействительна')

    def test_done_page_hides_account_existence(self):
        response = self.client.get(reverse('shop:password_reset_done'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Если аккаунт с таким email существует')

    def test_complete_page(self):
        response = self.client.get(reverse('shop:password_reset_complete'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Пароль изменён')
