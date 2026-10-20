"""Панель управления GameZone: свой AdminSite со сводкой на главной странице."""
from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig


class GameZoneAdminSite(AdminSite):
    """Админ-панель магазина: на главной странице показывает дашборд."""

    site_header = 'GameZone — управление магазином'
    site_title = 'GameZone'
    index_title = 'Панель управления'
    index_template = 'admin/index_with_dashboard.html'

    def index(self, request, extra_context=None):
        from shop.dashboard import build_dashboard

        extra_context = dict(extra_context or {})
        extra_context.setdefault('dashboard', build_dashboard(request.user))
        return super().index(request, extra_context)


class GameZoneAdminConfig(AdminConfig):
    """Заменяет стандартный django.contrib.admin на GameZoneAdminSite.

    Наследуем AdminConfig (а не SimpleAdminConfig), чтобы автопоиск
    admin.py в приложениях продолжал работать.
    """

    default_site = 'gamezone.admin.GameZoneAdminSite'
