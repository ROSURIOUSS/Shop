"""Админ-панель журнала активности: отдельный раздел «Активность и IP-адреса»."""
from django.contrib import admin

from .models import AuthEvent, VisitLog


class ReadOnlyLogAdmin(admin.ModelAdmin):
    """Общая база для журналов: записи создаются сайтом, а не вручную."""

    view_on_site = False
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(VisitLog)
class VisitLogAdmin(ReadOnlyLogAdmin):
    list_display = (
        'created_at', 'ip_address', 'user', 'short_path', 'method',
        'status_code', 'browser', 'os',
    )
    list_display_links = ('created_at', 'ip_address')
    list_filter = ('method', 'status_code', 'browser', 'os', 'created_at')
    search_fields = ('ip_address', 'path', 'referer', 'user__username', 'user__email', 'user_agent')
    date_hierarchy = 'created_at'
    list_select_related = ('user',)
    ordering = ['-created_at']
    readonly_fields = (
        'ip_address', 'user', 'path', 'method', 'status_code',
        'browser', 'os', 'user_agent', 'referer', 'created_at',
    )
    fieldsets = (
        ('Запрос', {
            'fields': ('path', 'method', 'status_code', 'referer', 'created_at'),
        }),
        ('Посетитель', {
            'fields': ('ip_address', 'user', 'browser', 'os', 'user_agent'),
        }),
    )

    @admin.display(description='Страница', ordering='path')
    def short_path(self, obj):
        return obj.path if len(obj.path) <= 60 else obj.path[:57] + '…'


@admin.register(AuthEvent)
class AuthEventAdmin(ReadOnlyLogAdmin):
    list_display = (
        'created_at', 'action', 'success', 'username', 'user',
        'ip_address', 'browser', 'detail',
    )
    list_display_links = ('created_at', 'action')
    list_filter = ('action', 'success', 'browser', 'os', 'created_at')
    search_fields = ('ip_address', 'username', 'user__username', 'user__email', 'detail', 'user_agent')
    date_hierarchy = 'created_at'
    list_select_related = ('user',)
    ordering = ['-created_at']
    readonly_fields = (
        'action', 'success', 'user', 'username', 'ip_address',
        'browser', 'os', 'user_agent', 'detail', 'created_at',
    )
    fieldsets = (
        ('Событие', {
            'fields': ('action', 'success', 'detail', 'created_at'),
        }),
        ('Покупатель', {
            'fields': ('user', 'username', 'ip_address', 'browser', 'os', 'user_agent'),
        }),
    )
