"""Тесты моделей, корзины, оформления заказа, аккаунтов и резервных копий."""
import json
import os
import re
import tempfile
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db.utils import OperationalError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from activity.models import AuthEvent, VisitLog
from gamezone.db_url import normalize as normalize_database_url
from gamezone.db_url import validate as validate_database_url

from .cart import Cart
from .models import Category, ContactMessage, Order, OrderItem, Product, Profile


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
