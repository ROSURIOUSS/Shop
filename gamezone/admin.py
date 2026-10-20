"""Панель управления GameZone: свой AdminSite со сводкой на главной странице."""
from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig


class GameZoneAdminSite(AdminSite):
    """Админ-панель магазина: сводка на главной и счётчик новых заказов."""

    site_header = 'GameZone — управление магазином'
    site_title = 'GameZone'
    index_title = 'Панель управления'
    index_template = 'admin/index_with_dashboard.html'

    def index(self, request, extra_context=None):
        from shop.dashboard import build_dashboard

        extra_context = dict(extra_context or {})
        extra_context.setdefault('dashboard', build_dashboard(request.user))
        return super().index(request, extra_context)

    def each_context(self, request):
        """Добавить в шапку каждой страницы счётчик заказов в статусе «Новый»."""
        context = super().each_context(request)
        context['new_orders_count'] = self.count_new_orders(request)
        context['new_orders_url'] = self.new_orders_url()
        return context

    @staticmethod
    def count_new_orders(request):
        """Сколько новых заказов видит этот сотрудник (0 без прав на заказы)."""
        from shop.models import Order

        user = request.user
        if not user.is_active or not user.is_staff:
            return 0
        if not (user.has_perm('shop.view_order') or user.has_perm('shop.change_order')):
            return 0
        return Order.objects.filter(status=Order.Status.NEW).count()

    @staticmethod
    def new_orders_url():
        """Ссылка на список заказов с готовым фильтром «Новый»."""
        from django.urls import reverse

        return f"{reverse('admin:shop_order_changelist')}?status__exact=new"


class GameZoneAdminConfig(AdminConfig):
    """Заменяет стандартный django.contrib.admin на GameZoneAdminSite.

    Наследуем AdminConfig (а не SimpleAdminConfig), чтобы автопоиск
    admin.py в приложениях продолжал работать.
    """

    default_site = 'gamezone.admin.GameZoneAdminSite'
