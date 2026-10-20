"""Тесты журнала активности: определение IP, middleware, события, админка."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from shop.models import Order
from shop.tests import make_category, make_product

from .models import AuthEvent, VisitLog
from .utils import describe_user_agent, get_client_ip

User = get_user_model()


class ClientIpTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_first_address_from_forwarded_for(self):
        request = self.factory.get('/', HTTP_X_FORWARDED_FOR='93.184.216.34, 10.0.0.1')
        self.assertEqual(get_client_ip(request), '93.184.216.34')

    def test_invalid_addresses_are_skipped(self):
        request = self.factory.get('/', HTTP_X_FORWARDED_FOR='spoofed-value, 93.184.216.34')
        self.assertEqual(get_client_ip(request), '93.184.216.34')

    def test_ipv6_is_supported(self):
        request = self.factory.get('/', HTTP_X_FORWARDED_FOR='2001:db8::1')
        self.assertEqual(get_client_ip(request), '2001:db8::1')

    def test_falls_back_to_real_ip_and_remote_addr(self):
        request = self.factory.get('/', HTTP_X_REAL_IP='93.184.216.34', REMOTE_ADDR='127.0.0.1')
        self.assertEqual(get_client_ip(request), '93.184.216.34')

        request = self.factory.get('/', REMOTE_ADDR='127.0.0.1')
        self.assertEqual(get_client_ip(request), '127.0.0.1')

    def test_returns_none_without_valid_address(self):
        request = self.factory.get('/', REMOTE_ADDR='not-an-ip')
        self.assertIsNone(get_client_ip(request))


class UserAgentTests(TestCase):
    def test_common_browsers_and_systems(self):
        browser, system = describe_user_agent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
        )
        self.assertEqual(browser, 'Chrome')
        self.assertEqual(system, 'Windows 10/11')

        browser, system = describe_user_agent(
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
            '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
        )
        self.assertEqual(browser, 'Safari')
        self.assertEqual(system, 'iOS (iPhone)')

        browser, system = describe_user_agent('curl/8.5.0')
        self.assertEqual(browser, 'curl')
        self.assertEqual(system, '')

    def test_empty_user_agent(self):
        self.assertEqual(describe_user_agent(''), ('', ''))
        self.assertEqual(describe_user_agent(None), ('', ''))


class VisitLogTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.product = make_product(self.category, stock=5)

    def test_page_visit_is_logged(self):
        response = self.client.get(reverse('shop:catalog'))
        self.assertEqual(response.status_code, 200)
        record = VisitLog.objects.filter(path='/catalog/').first()
        self.assertIsNotNone(record)
        self.assertEqual(record.method, 'GET')
        self.assertEqual(record.status_code, 200)
        self.assertEqual(record.ip_address, '127.0.0.1')

    def test_forwarded_ip_is_logged(self):
        self.client.get(reverse('shop:home'), HTTP_X_FORWARDED_FOR='93.184.216.34')
        self.assertTrue(VisitLog.objects.filter(ip_address='93.184.216.34').exists())

    def test_static_files_are_not_logged(self):
        self.client.get('/static/shop/css/style.css')
        self.assertFalse(VisitLog.objects.filter(path__startswith='/static/').exists())

    def test_authenticated_visitor_is_linked(self):
        user = User.objects.create_user(username='buyer', password='strong-pass-2026')
        self.client.force_login(user)
        self.client.get(reverse('shop:home'))
        record = VisitLog.objects.filter(path='/').first()
        self.assertEqual(record.user, user)

    def test_missing_status_code_is_logged_as_404(self):
        self.client.get('/no-such-page/')
        self.assertTrue(VisitLog.objects.filter(path='/no-such-page/', status_code=404).exists())

    @override_settings(ACTIVITY_LOG_ENABLED=False)
    def test_logging_can_be_switched_off(self):
        before = VisitLog.objects.count()
        self.client.get(reverse('shop:catalog'))
        self.assertEqual(VisitLog.objects.count(), before)

    def test_long_values_are_truncated(self):
        long_path = '/catalog/' + 'a' * 900
        self.client.get(long_path)
        record = VisitLog.objects.order_by('-id').first()
        self.assertLessEqual(len(record.path), 400)


class AuthEventTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.product = make_product(self.category, stock=5)

    def register(self, **overrides):
        data = {
            'username': 'gamer',
            'email': 'gamer@example.com',
            'password1': 'Zebra-Lamp4077',
            'password2': 'Zebra-Lamp4077',
        }
        data.update(overrides)
        return self.client.post(reverse('shop:register'), data)

    def test_register_is_logged(self):
        self.register()
        event = AuthEvent.objects.get(action=AuthEvent.Action.REGISTER)
        self.assertTrue(event.success)
        self.assertEqual(event.username, 'gamer')
        self.assertEqual(event.ip_address, '127.0.0.1')
        self.assertEqual(event.user.username, 'gamer')

    def test_failed_register_is_logged(self):
        self.register(password1='123', password2='123')
        event = AuthEvent.objects.get(action=AuthEvent.Action.REGISTER_FAILED)
        self.assertFalse(event.success)
        self.assertTrue(event.detail)

    def test_login_and_logout_are_logged(self):
        User.objects.create_user(username='gamer', password='Zebra-Lamp4077')
        self.client.post(reverse('shop:login'), {'username': 'gamer', 'password': 'Zebra-Lamp4077'})
        self.assertTrue(AuthEvent.objects.filter(action=AuthEvent.Action.LOGIN, success=True).exists())

        self.client.post(reverse('shop:logout'))
        event = AuthEvent.objects.filter(action=AuthEvent.Action.LOGOUT).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.user.username, 'gamer')

    def test_failed_login_is_logged(self):
        User.objects.create_user(username='gamer', password='Zebra-Lamp4077')
        self.client.post(reverse('shop:login'), {'username': 'gamer', 'password': 'wrong-password'})
        event = AuthEvent.objects.get(action=AuthEvent.Action.LOGIN_FAILED)
        self.assertFalse(event.success)
        self.assertEqual(event.username, 'gamer')
        self.assertIsNone(event.user)

    def test_password_change_is_logged(self):
        user = User.objects.create_user(username='gamer', password='Zebra-Lamp4077')
        self.client.force_login(user)
        self.client.post(reverse('shop:password_change'), {
            'old_password': 'Zebra-Lamp4077',
            'new_password1': 'Tiger-Moon5188',
            'new_password2': 'Tiger-Moon5188',
        })
        self.assertTrue(AuthEvent.objects.filter(action=AuthEvent.Action.PASSWORD_CHANGE).exists())

    def test_order_stores_ip_and_event(self):
        user = User.objects.create_user(username='gamer', password='Zebra-Lamp4077')
        self.client.force_login(user)
        self.client.post(reverse('shop:cart_add', args=[self.product.pk]), {'quantity': 2})
        self.client.post(reverse('shop:checkout'), {
            'customer_name': 'Іван Петренко',
            'phone': '+380501112233',
            'email': 'gamer@example.com',
            'city': 'Харків',
            'address': 'вул. Тестова, 1',
            'comment': '',
        }, HTTP_X_FORWARDED_FOR='93.184.216.34')
        order = Order.objects.get()
        self.assertEqual(order.ip_address, '93.184.216.34')
        event = AuthEvent.objects.get(action=AuthEvent.Action.ORDER)
        self.assertEqual(event.user, user)
        self.assertIn(order.order_number, event.detail)


class ActivityAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='strong-pass-2026',
        )

    def test_admin_has_separate_section(self):
        self.client.force_login(self.superuser)
        response = self.client.get('/admin/')
        self.assertContains(response, 'Активность и IP-адреса')
        self.assertContains(response, 'Журнал посещений')
        self.assertContains(response, 'События покупателей')

    def test_logs_are_visible_in_admin(self):
        VisitLog.objects.create(ip_address='93.184.216.34', path='/catalog/', method='GET', status_code=200)
        AuthEvent.objects.create(
            action=AuthEvent.Action.LOGIN_FAILED, success=False,
            username='hacker', ip_address='93.184.216.34', detail='Неверный пароль',
        )
        self.client.force_login(self.superuser)

        visits = self.client.get('/admin/activity/visitlog/')
        self.assertEqual(visits.status_code, 200)
        self.assertContains(visits, '93.184.216.34')
        self.assertContains(visits, '/catalog/')

        events = self.client.get('/admin/activity/authevent/')
        self.assertEqual(events.status_code, 200)
        self.assertContains(events, 'hacker')
        self.assertContains(events, 'Неудачный вход')

    def test_search_by_ip(self):
        VisitLog.objects.create(ip_address='93.184.216.34', path='/catalog/', method='GET', status_code=200)
        VisitLog.objects.create(ip_address='8.8.8.8', path='/about/', method='GET', status_code=200)
        self.client.force_login(self.superuser)
        response = self.client.get('/admin/activity/visitlog/', {'q': '93.184.216.34'})
        self.assertContains(response, '/catalog/')
        self.assertNotContains(response, '/about/')

    def test_logs_cannot_be_added_or_edited_manually(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get('/admin/activity/visitlog/add/').status_code, 403)
        record = VisitLog.objects.create(ip_address='8.8.8.8', path='/', method='GET', status_code=200)
        self.assertEqual(
            self.client.get(f'/admin/activity/visitlog/{record.pk}/change/').status_code, 200,
        )

    def test_logs_require_staff(self):
        response = self.client.get('/admin/activity/visitlog/')
        self.assertRedirects(response, '/admin/login/?next=/admin/activity/visitlog/')


class ClearActivityLogTests(TestCase):
    def test_old_records_are_removed(self):
        old = VisitLog.objects.create(ip_address='8.8.8.8', path='/old/', method='GET', status_code=200)
        VisitLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))
        fresh = VisitLog.objects.create(ip_address='8.8.8.8', path='/new/', method='GET', status_code=200)

        call_command('clear_activity_log', '--days=30')
        self.assertFalse(VisitLog.objects.filter(pk=old.pk).exists())
        self.assertTrue(VisitLog.objects.filter(pk=fresh.pk).exists())

    def test_dry_run_keeps_records(self):
        record = VisitLog.objects.create(ip_address='8.8.8.8', path='/old/', method='GET', status_code=200)
        VisitLog.objects.filter(pk=record.pk).update(created_at=timezone.now() - timedelta(days=120))
        call_command('clear_activity_log', '--days=30', '--dry-run')
        self.assertTrue(VisitLog.objects.filter(pk=record.pk).exists())


class OrderIpModelTests(TestCase):
    def test_ip_field_is_optional(self):
        order = Order.objects.create(
            customer_name='Гость', phone='+380500000000', city='Київ',
            address='вул. 1', total_amount=Decimal('100.00'),
        )
        self.assertIsNone(order.ip_address)
