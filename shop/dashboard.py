"""Данные для дашборда админ-панели.

Всё считается по реальным записям базы: заказы, позиции заказов, товары,
обращения и журнал активности. Никаких выдуманных цифр.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, DecimalField, F, Sum
from django.urls import reverse
from django.utils import timezone

from activity.models import AuthEvent, VisitLog

from .models import LOW_STOCK_THRESHOLD, Category, ContactMessage, Order, OrderItem, Product
TOP_PRODUCTS_LIMIT = 5
RECENT_LIMIT = 5
MONEY = Decimal('0.01')


def _start_of_day():
    """Начало сегодняшнего дня в часовом поясе проекта."""
    return timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)


def _money(value):
    """Привести сумму к двум знакам (Sum и Avg возвращают None на пустой выборке)."""
    return (value or Decimal('0')).quantize(MONEY)


def _can(user, permission):
    """Раздел дашборда показывается только при наличии права на просмотр."""
    return bool(user is not None and user.is_authenticated and user.has_perm(permission))


def _sales():
    """Выручка и количество заказов по периодам; отменённые не учитываются."""
    now = timezone.now()
    start_of_day = _start_of_day()
    paid = Order.objects.exclude(status=Order.Status.CANCELLED)

    periods = (
        ('Сегодня', start_of_day, now, False),
        ('7 дней', now - timedelta(days=7), now, False),
        ('30 дней', now - timedelta(days=30), now, False),
        ('За всё время', None, None, True),
    )

    rows = []
    for label, start, end, is_total in periods:
        queryset = paid
        if start is not None:
            queryset = queryset.filter(created_at__gte=start)
        if end is not None:
            queryset = queryset.filter(created_at__lte=end)
        data = queryset.aggregate(
            revenue=Sum('total_amount'),
            orders=Count('pk'),
            average=Avg('total_amount'),
        )
        rows.append({
            'label': label,
            'revenue': _money(data['revenue']),
            'orders': data['orders'] or 0,
            'average': _money(data['average']),
            'is_total': is_total,
        })
    return rows


def _statuses():
    """Сколько заказов в каждом статусе."""
    counts = dict(Order.objects.values_list('status').annotate(total=Count('pk')))
    return [
        {'status': value, 'label': label, 'count': counts.get(value, 0)}
        for value, label in Order.Status.choices
    ]


def _top_products():
    """Топ товаров по проданным штукам (отменённые заказы исключены)."""
    rows = list(
        OrderItem.objects
        .exclude(order__status=Order.Status.CANCELLED)
        .values('product_id', 'product__name')
        .annotate(
            revenue=Sum(
                F('quantity') * F('price'),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            sold=Sum('quantity'),
        )
        .order_by('-sold', '-revenue')[:TOP_PRODUCTS_LIMIT]
    )

    best = max((row['sold'] for row in rows), default=0)
    result = []
    for row in rows:
        sold = row['sold'] or 0
        result.append({
            'name': row['product__name'] or 'Товар удалён',
            'quantity': sold,
            'revenue': _money(row['revenue']),
            'width': int(round(sold * 100 / best)) if best else 0,
        })
    return result


def _stock():
    """Состояние витрины и товары, которые заканчиваются."""
    low = (
        Product.objects
        .filter(is_available=True, stock__gt=0, stock__lte=LOW_STOCK_THRESHOLD)
        .order_by('stock', 'name')[:RECENT_LIMIT * 2]
    )
    return {
        'threshold': LOW_STOCK_THRESHOLD,
        'total': Product.objects.count(),
        'categories': Category.objects.count(),
        'empty': Product.objects.filter(stock=0).count(),
        'hidden': Product.objects.filter(is_available=False).count(),
        'items': [
            {
                'name': product.name,
                'stock': product.stock,
                'url': reverse('admin:shop_product_change', args=[product.pk]),
            }
            for product in low
        ],
    }


def _activity(user):
    """Посещения и события покупателей — из журнала приложения activity."""
    now = timezone.now()
    start_of_day = _start_of_day()
    week_ago = now - timedelta(days=7)

    visits = {}
    if _can(user, 'activity.view_visitlog'):
        today = VisitLog.objects.filter(created_at__gte=start_of_day)
        visits = {
            'today': today.count(),
            'week': VisitLog.objects.filter(created_at__gte=week_ago).count(),
            'ip_today': today.exclude(ip_address=None).values('ip_address').distinct().count(),
            'users_today': today.exclude(user=None).values('user').distinct().count(),
        }

    events = {}
    if _can(user, 'activity.view_authevent'):
        events = {
            'registrations_today': AuthEvent.objects.filter(
                action=AuthEvent.Action.REGISTER, success=True, created_at__gte=start_of_day,
            ).count(),
            'registrations_week': AuthEvent.objects.filter(
                action=AuthEvent.Action.REGISTER, success=True, created_at__gte=week_ago,
            ).count(),
            'orders_week': AuthEvent.objects.filter(
                action=AuthEvent.Action.ORDER, created_at__gte=week_ago,
            ).count(),
            'failed_week': AuthEvent.objects.filter(
                action=AuthEvent.Action.LOGIN_FAILED, created_at__gte=week_ago,
            ).count(),
        }

    return {'visits': visits, 'events': events}


def _recent_orders():
    orders = Order.objects.select_related('user').order_by('-created_at')[:RECENT_LIMIT]
    return [
        {
            'number': order.order_number,
            'customer': order.customer_name,
            'username': order.user.username if order.user else '',
            'ip_address': order.ip_address or '',
            'total': order.total_amount,
            'status': order.status,
            'status_label': order.get_status_display(),
            'created_at': order.created_at,
            'url': reverse('admin:shop_order_change', args=[order.pk]),
        }
        for order in orders
    ]


def _recent_messages():
    messages = ContactMessage.objects.order_by('-created_at')[:RECENT_LIMIT]
    return [
        {
            'subject': message.subject,
            'name': message.name,
            'created_at': message.created_at,
            'url': reverse('admin:shop_contactmessage_change', args=[message.pk]),
        }
        for message in messages
    ]


def build_dashboard(user=None):
    """Собрать сводку для админ-панели с учётом прав конкретного пользователя."""
    dashboard = {'generated_at': timezone.localtime(timezone.now())}

    if _can(user, 'shop.view_order'):
        active_orders = Order.objects.exclude(status=Order.Status.CANCELLED)
        dashboard['can_view_orders'] = True
        dashboard['sales'] = _sales()
        dashboard['statuses'] = _statuses()
        dashboard['top_products'] = _top_products()
        dashboard['recent_orders'] = _recent_orders()
        dashboard['new_orders'] = Order.objects.filter(status=Order.Status.NEW).count()
        dashboard['paid_orders'] = active_orders.count()

    if _can(user, 'shop.view_product'):
        dashboard['can_view_products'] = True
        dashboard['stock'] = _stock()

    activity = _activity(user)
    if activity['visits'] or activity['events']:
        dashboard['activity'] = activity

    if _can(user, 'shop.view_contactmessage'):
        dashboard['can_view_messages'] = True
        dashboard['messages'] = _recent_messages()

    return dashboard
