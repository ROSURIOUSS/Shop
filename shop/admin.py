"""Настройка административной панели GameZone."""
from django.contrib import admin

from .models import Category, ContactMessage, Order, OrderItem, Product, Profile


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'product_count')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'stock', 'is_available', 'is_featured', 'created_at')
    list_filter = ('category', 'is_available', 'is_featured')
    search_fields = ('name', 'description')
    list_editable = ('price', 'stock', 'is_available', 'is_featured')
    ordering = ('-created_at',)
    prepopulated_fields = {'slug': ('name',)}
    autocomplete_fields = ('category',)
    fieldsets = (
        (None, {
            'fields': ('category', 'name', 'slug', 'description', 'price', 'image')
        }),
        ('Остатки и доступность', {
            'fields': ('stock', 'is_available', 'is_featured')
        }),
        ('Характеристики (JSON)', {
            'fields': ('specifications',),
            'description': 'Например: {"DPI": "16000", "Интерфейс": "USB"}',
        }),
    )


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'quantity', 'price')
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'user', 'customer_name', 'phone', 'status', 'total_amount', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('order_number', 'customer_name', 'phone', 'email', 'user__username')
    autocomplete_fields = ('user',)
    readonly_fields = ('order_number', 'total_amount', 'created_at', 'updated_at')
    inlines = [OrderItemInline]
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'created_at')
    search_fields = ('name', 'email', 'subject')
    readonly_fields = ('name', 'email', 'subject', 'message', 'created_at')

    def has_add_permission(self, request):
        return False


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'city')
    search_fields = ('user__username', 'user__email', 'phone', 'city')
    autocomplete_fields = ('user',)
