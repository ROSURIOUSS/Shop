"""Настройка административной панели GameZone."""
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html

from .csv_export import CsvExportMixin, export_flat_csv
from .orders import OrderTransitionError, change_status
from .models import (
    LOW_STOCK_THRESHOLD,
    Category,
    Coupon,
    ContactMessage,
    Order,
    OrderItem,
    Product,
    Profile,
    Review,
    with_rating,
)
from .templatetags.shop_extras import plural_ru


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'product_count')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


class StockStatusFilter(admin.SimpleListFilter):
    """Фильтр товаров по остатку на складе."""

    title = 'остаток на складе'
    parameter_name = 'stock_status'

    def lookups(self, request, model_admin):
        return (
            ('low', f'Заканчиваются (не больше {LOW_STOCK_THRESHOLD} шт.)'),
            ('ok', 'Достаточно на складе'),
            ('out', 'Нет в наличии'),
            ('off', 'Сняты с продажи'),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'low':
            return queryset.filter(
                is_available=True, stock__gt=0, stock__lte=LOW_STOCK_THRESHOLD
            )
        if value == 'ok':
            return queryset.filter(is_available=True, stock__gt=LOW_STOCK_THRESHOLD)
        if value == 'out':
            return queryset.filter(is_available=True, stock=0)
        if value == 'off':
            return queryset.filter(is_available=False)
        return queryset


class ReviewInline(admin.TabularInline):
    """Отзывы прямо в карточке товара."""

    model = Review
    extra = 0
    fields = ('user', 'rating', 'text', 'is_visible', 'created_at')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('user',)
    verbose_name = 'отзыв'
    verbose_name_plural = 'Отзывы покупателей'


@admin.register(Product)
class ProductAdmin(CsvExportMixin, admin.ModelAdmin):
    list_display = (
        'name', 'category', 'price', 'stock_status', 'stock', 'rating_summary',
        'is_available', 'is_featured', 'created_at',
    )
    list_filter = (StockStatusFilter, 'category', 'is_available', 'is_featured')
    search_fields = ('name', 'description')
    list_editable = ('price', 'stock', 'is_available', 'is_featured')
    ordering = ('-created_at',)
    prepopulated_fields = {'slug': ('name',)}
    autocomplete_fields = ('category',)
    inlines = [ReviewInline]
    actions = ('export_csv',)
    csv_basename = 'products'
    csv_fields = (
        ('name', 'Товар'),
        ('category__name', 'Категория'),
        ('price', 'Цена, ₴'),
        ('stock', 'Остаток, шт.'),
        ('is_available', 'В продаже'),
        ('is_featured', 'Популярный'),
        ('rating_average', 'Средняя оценка'),
        ('rating_count', 'Отзывов'),
        ('created_at', 'Добавлен'),
    )
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

    def get_queryset(self, request):
        return with_rating(super().get_queryset(request))

    @admin.display(description='Наличие', ordering='stock')
    def stock_status(self, obj):
        """Цветная метка остатка: заканчивается, нет в наличии, достаточно."""
        if not obj.is_available:
            label, style = 'Снят с продажи', 'off'
        elif obj.stock == 0:
            label, style = 'Нет в наличии', 'out'
        elif obj.is_low_stock:
            label, style = 'Заканчивается', 'low'
        else:
            label, style = 'Достаточно', 'ok'
        return format_html(
            '<span class="gzh-stock gzh-stock--{}">{}</span>', style, label
        )

    @admin.display(description='Рейтинг', ordering='rating_avg')
    def rating_summary(self, obj):
        average = getattr(obj, 'rating_avg', None)
        count = getattr(obj, 'rating_count', None)
        if not count:
            return format_html('<span class="gzh-muted">{}</span>', 'нет отзывов')
        value = f'{float(average or 0):.1f}'.replace('.', ',')
        return format_html(
            '<span class="gzh-rating">{} <small>({} {})</small></span>',
            value,
            count,
            plural_ru(count, 'отзыв,отзыва,отзывов'),
        )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        note = f'Товар считается заканчивающимся при остатке {LOW_STOCK_THRESHOLD} шт. и меньше.'
        if obj is not None and obj.is_low_stock:
            note = f'Остаток {obj.stock} шт. — товар заканчивается. ' + note
        form.base_fields['stock'].help_text = note
        return form


@admin.register(Coupon)
class CouponAdmin(CsvExportMixin, admin.ModelAdmin):
    """Промокоды: скидка, срок действия и лимит применений."""

    list_display = (
        'code', 'kind', 'value', 'min_total', 'valid_until',
        'usage_limit', 'used_count', 'is_active',
    )
    list_editable = ('is_active',)
    list_filter = ('kind', 'is_active', 'valid_until')
    search_fields = ('code',)
    readonly_fields = ('used_count', 'created_at')
    ordering = ('-created_at',)
    date_hierarchy = 'valid_until'
    csv_basename = 'coupons'
    csv_fields = (
        ('code', 'Код'),
        ('get_kind_display', 'Тип скидки'),
        ('value', 'Размер'),
        ('min_total', 'Минимальная сумма, ₴'),
        ('valid_from', 'Действует с'),
        ('valid_until', 'Действует до'),
        ('usage_limit', 'Лимит применений'),
        ('used_count', 'Применён раз'),
        ('is_active', 'Активен'),
    )
    actions = ('export_csv', 'activate', 'deactivate')
    fieldsets = (
        (None, {
            'fields': ('code', 'kind', 'value', 'min_total', 'is_active'),
        }),
        ('Срок и лимит', {
            'fields': ('valid_from', 'valid_until', 'usage_limit', 'used_count'),
            'description': 'Пустые срок и лимит означают «без ограничений».',
        }),
        ('Служебное', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )

    @admin.action(description='Включить промокоды')
    def activate(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'Включено промокодов: {updated}.')

    @admin.action(description='Отключить промокоды')
    def deactivate(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'Отключено промокодов: {updated}.')


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'quantity', 'price')
    can_delete = False


@admin.register(Order)
class OrderAdmin(CsvExportMixin, admin.ModelAdmin):
    """Заказы: смена статуса кнопками в карточке и массовыми действиями."""

    change_form_template = 'admin/shop/order/change_form.html'
    TRANSITION_LABELS = {
        'confirmed': 'Подтвердить',
        'shipped': 'Отправить',
        'completed': 'Завершить',
        'cancelled': 'Отменить',
    }

    list_display = (
        'order_number', 'user', 'customer_name', 'phone', 'ip_address',
        'status', 'total_amount', 'discount_amount', 'coupon', 'created_at',
    )
    list_filter = ('status', 'created_at', 'coupon')
    search_fields = ('order_number', 'customer_name', 'phone', 'email', 'ip_address', 'user__username')
    autocomplete_fields = ('user',)
    readonly_fields = (
        'order_number', 'total_amount', 'discount_amount', 'items_summary',
        'created_at', 'updated_at',
    )
    inlines = [OrderItemInline]
    ordering = ('-created_at',)
    csv_basename = 'orders'
    csv_fields = (
        ('order_number', 'Номер заказа'),
        ('created_at', 'Дата'),
        ('get_status_display', 'Статус'),
        ('customer_name', 'Покупатель'),
        ('phone', 'Телефон'),
        ('email', 'Email'),
        ('city', 'Город'),
        ('address', 'Адрес доставки'),
        ('user__username', 'Аккаунт'),
        ('ip_address', 'IP-адрес'),
        ('discount_amount', 'Скидка, ₴'),
        ('coupon__code', 'Промокод'),
        ('total_amount', 'Сумма, ₴'),
        ('items_summary', 'Состав заказа'),
        ('comment', 'Комментарий'),
    )
    actions = (
        'export_csv', 'export_items_csv',
        'mark_confirmed', 'mark_shipped', 'mark_completed', 'mark_cancelled',
    )
    fieldsets = (
        (None, {
            'fields': ('order_number', 'status', 'created_at', 'updated_at'),
        }),
        ('Покупатель и доставка', {
            'fields': ('user', 'customer_name', 'phone', 'email', 'city', 'address', 'ip_address'),
        }),
        ('Состав и сумма', {
            'fields': ('items_summary', 'coupon', 'discount_amount', 'total_amount', 'comment'),
        }),
    )

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        """Адрес для смены статуса кнопкой из карточки заказа."""
        custom = [
            path(
                '<path:object_id>/transition/<str:status>/',
                self.admin_site.admin_view(self.transition_view),
                name='shop_order_transition',
            ),
        ]
        return custom + super().get_urls()

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        """Кнопки только для тех статусов, куда переход разрешён."""
        extra_context = dict(extra_context or {})
        if object_id:
            order = self.get_object(request, object_id)
            if order is not None:
                extra_context['transition_buttons'] = [
                    {
                        'code': code,
                        'label': self.TRANSITION_LABELS.get(
                            code, Order.Status(code).label
                        ),
                        'url': reverse(
                            'admin:shop_order_transition', args=[order.pk, code]
                        ),
                    }
                    for code in order.allowed_transitions()
                ]
        return super().changeform_view(request, object_id, form_url, extra_context)

    def transition_view(self, request, object_id, status):
        """Сменить статус заказа по POST-запросу из карточки."""
        order = get_object_or_404(Order, pk=object_id)
        if not self.has_change_permission(request, order):
            raise PermissionDenied
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
        if status not in Order.Status.values:
            raise Http404('Неизвестный статус заказа')

        try:
            change_status(order, status)
        except OrderTransitionError as error:
            self.message_user(request, str(error), messages.ERROR)
        else:
            self.message_user(
                request,
                f'Заказ {order.order_number}: «{Order.Status(status).label}».',
                messages.SUCCESS,
            )
        return HttpResponseRedirect(
            reverse('admin:shop_order_change', args=[order.pk])
        )

    def _bulk_transition(self, request, queryset, status):
        """Сменить статус у выбранных заказов, пропуская недопустимые переходы."""
        changed = 0
        skipped = 0
        for order in queryset:
            try:
                change_status(order, status)
            except OrderTransitionError:
                skipped += 1
            else:
                changed += 1

        label = Order.Status(status).label
        if changed:
            self.message_user(
                request, f'Статус «{label}» установлен: {changed}.', messages.SUCCESS
            )
        if skipped:
            self.message_user(
                request,
                f'Пропущено заказов, где переход невозможен: {skipped}.',
                messages.WARNING,
            )

    @admin.action(permissions=['change'], description='Подтвердить выбранные заказы')
    def mark_confirmed(self, request, queryset):
        self._bulk_transition(request, queryset, Order.Status.CONFIRMED)

    @admin.action(permissions=['change'], description='Отправить выбранные заказы')
    def mark_shipped(self, request, queryset):
        self._bulk_transition(request, queryset, Order.Status.SHIPPED)

    @admin.action(permissions=['change'], description='Завершить выбранные заказы')
    def mark_completed(self, request, queryset):
        self._bulk_transition(request, queryset, Order.Status.COMPLETED)

    @admin.action(permissions=['change'], description='Отменить выбранные заказы')
    def mark_cancelled(self, request, queryset):
        self._bulk_transition(request, queryset, Order.Status.CANCELLED)

    @admin.action(description='Выгрузить позиции заказов в CSV')
    def export_items_csv(self, request, queryset):
        """Плоская выгрузка: одна строка — одна позиция заказа."""
        headers = [
            'Номер заказа', 'Дата', 'Статус', 'Покупатель', 'Телефон', 'Email',
            'Город', 'Товар', 'Категория', 'Количество', 'Цена, ₴', 'Сумма, ₴',
        ]

        def rows():
            orders = queryset.select_related('user').prefetch_related(
                'items__product__category'
            )
            for order in orders:
                for item in order.items.all():
                    yield [
                        order.order_number,
                        order.created_at,
                        order.get_status_display(),
                        order.customer_name,
                        order.phone,
                        order.email,
                        order.city,
                        item.product.name,
                        item.product.category.name,
                        item.quantity,
                        item.price,
                        item.get_cost(),
                    ]

        return export_flat_csv('order-items', headers, rows())


@admin.register(Review)
class ReviewAdmin(CsvExportMixin, admin.ModelAdmin):
    list_display = ('product', 'author', 'rating', 'is_visible', 'created_at')
    list_display_links = ('product',)
    list_filter = ('rating', 'is_visible', 'created_at')
    search_fields = ('product__name', 'user__username', 'user__email', 'text')
    list_editable = ('is_visible',)
    autocomplete_fields = ('product', 'user')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    csv_basename = 'reviews'
    csv_fields = (
        ('product__name', 'Товар'),
        ('author_name', 'Автор'),
        ('user__username', 'Аккаунт'),
        ('user__email', 'Email'),
        ('rating', 'Оценка'),
        ('text', 'Текст отзыва'),
        ('is_visible', 'Показан на сайте'),
        ('created_at', 'Дата'),
    )
    actions = ('export_csv', 'make_visible', 'make_hidden')
    fieldsets = (
        (None, {
            'fields': ('product', 'user', 'rating', 'text', 'is_visible'),
        }),
        ('Служебное', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Автор', ordering='user__username')
    def author(self, obj):
        return obj.author_name

    @admin.action(description='Показать на сайте')
    def make_visible(self, request, queryset):
        updated = queryset.update(is_visible=True)
        self.message_user(request, f'Отзывы, показанные на сайте: {updated}.')

    @admin.action(description='Скрыть с сайта')
    def make_hidden(self, request, queryset):
        updated = queryset.update(is_visible=False)
        self.message_user(request, f'Скрытые отзывы: {updated}.')


@admin.register(ContactMessage)
class ContactMessageAdmin(CsvExportMixin, admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'created_at')
    search_fields = ('name', 'email', 'subject')
    readonly_fields = ('name', 'email', 'subject', 'message', 'created_at')
    actions = ('export_csv',)
    csv_basename = 'messages'
    csv_fields = (
        ('name', 'Имя'),
        ('email', 'Email'),
        ('subject', 'Тема'),
        ('message', 'Сообщение'),
        ('created_at', 'Дата отправки'),
    )

    def has_add_permission(self, request):
        return False


@admin.register(Profile)
class ProfileAdmin(CsvExportMixin, admin.ModelAdmin):
    list_display = ('user', 'phone', 'city')
    search_fields = ('user__username', 'user__email', 'phone', 'city')
    autocomplete_fields = ('user',)
    actions = ('export_csv',)
    csv_basename = 'profiles'
    csv_fields = (
        ('user__username', 'Аккаунт'),
        ('user__email', 'Email'),
        ('user__first_name', 'Имя'),
        ('user__last_name', 'Фамилия'),
        ('user__date_joined', 'Дата регистрации'),
        ('phone', 'Телефон'),
        ('city', 'Город'),
        ('address', 'Адрес доставки'),
    )
