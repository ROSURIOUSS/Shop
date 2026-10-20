"""Представления интернет-магазина GameZone."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .cart import Cart
from .forms import ContactForm, OrderForm
from .models import Category, ContactMessage, Order, OrderItem, Product

SORT_OPTIONS = {
    'popular': ('По популярности', ('-is_featured', '-created_at')),
    'price_asc': ('Сначала дешёвые', ('price',)),
    'price_desc': ('Сначала дорогие', ('-price',)),
    'name': ('По названию А — Я', ('name',)),
    'new': ('Сначала новые', ('-created_at',)),
}
DEFAULT_SORT = 'popular'
PRODUCTS_PER_PAGE = 12


def _parse_price(value):
    """Безопасно разобрать цену из GET-параметра (None при ошибке)."""
    value = (value or '').strip().replace(',', '.')
    if not value:
        return None
    try:
        price = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return price if price >= 0 else None


def _filter_products(request, queryset):
    """Применить поиск и фильтры из GET-параметров к набору товаров.

    Возвращает (queryset, словарь_параметров_фильтров).
    Все фильтрации выполняются через Django ORM — SQL-инъекции исключены.
    """
    query = request.GET.get('q', '').strip()
    category_slug = request.GET.get('category', '').strip()
    min_price = _parse_price(request.GET.get('min_price'))
    max_price = _parse_price(request.GET.get('max_price'))
    sort_key = request.GET.get('sort', DEFAULT_SORT)
    if sort_key not in SORT_OPTIONS:
        sort_key = DEFAULT_SORT

    if query:
        queryset = queryset.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )
    if category_slug:
        queryset = queryset.filter(category__slug=category_slug)
    if min_price is not None:
        queryset = queryset.filter(price__gte=min_price)
    if max_price is not None:
        queryset = queryset.filter(price__lte=max_price)
    if max_price is not None and min_price is not None and max_price < min_price:
        queryset = queryset.none()

    queryset = queryset.order_by(*SORT_OPTIONS[sort_key][1], 'id')

    filters = {
        'q': query,
        'category': category_slug,
        'min_price': request.GET.get('min_price', '').strip(),
        'max_price': request.GET.get('max_price', '').strip(),
        'sort': sort_key,
    }
    return queryset, filters


def _paginated(request, queryset):
    """Пагинация: PRODUCTS_PER_PAGE товаров на страницу."""
    paginator = Paginator(queryset, PRODUCTS_PER_PAGE)
    page_number = request.GET.get('page')
    return paginator.get_page(page_number)


def _querystring_without_page(request):
    """Строка GET-параметров для ссылок пагинации (без параметра page)."""
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


def home(request):
    """Главная страница: hero, категории, популярное, новинки, преимущества."""
    categories = Category.objects.all()[:6]
    featured_products = Product.objects.filter(
        is_featured=True, is_available=True
    ).select_related('category')[:4]

    featured_ids = [product.pk for product in featured_products]
    new_products = Product.objects.filter(is_available=True).exclude(
        id__in=featured_ids
    ).select_related('category').order_by('-created_at')[:4]
    if not new_products:
        new_products = Product.objects.filter(is_available=True).select_related(
            'category'
        ).order_by('-created_at')[:4]

    return render(request, 'shop/home.html', {
        'categories': categories,
        'featured_products': featured_products,
        'new_products': new_products,
    })


def catalog(request):
    """Каталог с серверным поиском, фильтрами, сортировкой и пагинацией."""
    queryset, filters = _filter_products(
        request, Product.objects.filter(is_available=True).select_related('category')
    )
    page_obj = _paginated(request, queryset)
    categories = Category.objects.all()

    return render(request, 'shop/catalog.html', {
        'page_obj': page_obj,
        'products': page_obj.object_list,
        'categories': categories,
        'filters': filters,
        'sort_options': SORT_OPTIONS,
        'querystring': _querystring_without_page(request),
        'result_count': queryset.count(),
    })


def categories(request):
    """Список всех категорий с количеством товаров."""
    category_list = Category.objects.all()
    return render(request, 'shop/categories.html', {
        'categories': category_list,
    })


def category_detail(request, slug):
    """Страница конкретной категории с сеткой товаров."""
    category = get_object_or_404(Category, slug=slug)
    queryset, filters = _filter_products(
        request,
        Product.objects.filter(category=category, is_available=True).select_related('category'),
    )
    page_obj = _paginated(request, queryset)

    return render(request, 'shop/category_detail.html', {
        'category': category,
        'page_obj': page_obj,
        'products': page_obj.object_list,
        'filters': filters,
        'sort_options': SORT_OPTIONS,
        'querystring': _querystring_without_page(request),
        'result_count': queryset.count(),
    })


def product_detail(request, pk):
    """Карточка товара: изображение, характеристики, похожие товары."""
    product = get_object_or_404(Product.objects.select_related('category'), pk=pk)
    related_products = Product.objects.filter(
        category=product.category, is_available=True
    ).exclude(pk=product.pk).select_related('category')[:4]

    return render(request, 'shop/product_detail.html', {
        'product': product,
        'related_products': related_products,
    })


def cart_detail(request):
    """Страница корзины."""
    cart = Cart(request)
    return render(request, 'shop/cart.html', {
        'cart': cart,
        'cart_total': cart.get_total_price(),
    })


def _safe_next_url(request, default='shop:cart'):
    """Вернуть безопасный адрес возврата после действия (защита от open redirect)."""
    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return default


@require_POST
def cart_add(request, pk):
    """Добавить товар в корзину (POST, CSRF защищён)."""
    product = get_object_or_404(Product, pk=pk)
    cart = Cart(request)

    if not product.in_stock():
        messages.error(request, f'«{product.name}» сейчас нет в наличии.')
        return redirect(_safe_next_url(request, product.get_absolute_url()))

    try:
        quantity = int(request.POST.get('quantity', 1))
    except (TypeError, ValueError):
        quantity = 1
    if quantity < 1:
        quantity = 1

    cart.add(product, quantity)
    messages.success(request, f'«{product.name}» добавлен в корзину.')
    return redirect(_safe_next_url(request))


@require_POST
def cart_update(request, pk):
    """Изменить количество товара в корзине (количество 0 удаляет позицию)."""
    product = get_object_or_404(Product, pk=pk)
    cart = Cart(request)
    try:
        quantity = int(request.POST.get('quantity', 1))
    except (TypeError, ValueError):
        messages.error(request, 'Некорректное количество.')
        return redirect('shop:cart')

    if quantity <= 0:
        cart.remove(product)
        messages.success(request, f'«{product.name}» удалён из корзины.')
        return redirect('shop:cart')

    if quantity > product.stock:
        messages.error(
            request,
            f'«{product.name}»: на складе осталось {product.stock} шт.',
        )
        return redirect('shop:cart')

    cart.update(product, quantity)
    messages.success(request, f'Количество «{product.name}» обновлено.')
    return redirect('shop:cart')


@require_POST
def cart_remove(request, pk):
    """Удалить товар из корзины."""
    product = get_object_or_404(Product, pk=pk)
    Cart(request).remove(product)
    messages.success(request, f'«{product.name}» удалён из корзины.')
    return redirect('shop:cart')


@require_POST
def cart_clear(request):
    """Очистить всю корзину."""
    Cart(request).clear()
    messages.success(request, 'Корзина очищена.')
    return redirect('shop:cart')


def checkout(request):
    """Оформление заказа: форма + сводка + атомарное создание заказа."""
    cart = Cart(request)
    if cart.is_empty():
        messages.info(request, 'Корзина пуста. Добавьте товары перед оформлением заказа.')
        return redirect('shop:cart')

    cart_items = list(cart)
    cart_total = cart.get_total_price()

    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    order = form.save(commit=False)
                    order.save()

                    total = Decimal('0.00')
                    for item in cart_items:
                        product = Product.objects.select_for_update().get(
                            pk=item['product'].pk
                        )
                        quantity = item['quantity']
                        if not product.is_available or product.stock < quantity:
                            raise ValidationError(
                                f'«{product.name}»: на складе осталось {product.stock} шт. '
                                f'Уменьшите количество или уберите товар из заказа.'
                            )
                        OrderItem.objects.create(
                            order=order,
                            product=product,
                            quantity=quantity,
                            price=product.price,
                        )
                        product.stock -= quantity
                        product.save()
                        total += product.price * quantity

                    order.total_amount = total
                    order.save()
            except ValidationError as error:
                messages.error(request, '; '.join(error.messages))
                return render(request, 'shop/checkout.html', {
                    'form': form,
                    'cart_items': cart_items,
                    'cart_total': cart_total,
                })

            cart.clear()
            request.session['last_order_id'] = order.pk
            return redirect('shop:order_success')
    else:
        form = OrderForm()

    return render(request, 'shop/checkout.html', {
        'form': form,
        'cart_items': cart_items,
        'cart_total': cart_total,
    })


def order_success(request):
    """Страница успешного оформления заказа.

    Доступ возможен только из сессии, в которой был создан заказ —
    номер заказа нельзя «угадать» и получить чужие данные.
    """
    order_id = request.session.get('last_order_id')
    if not order_id:
        return redirect('shop:home')
    order = get_object_or_404(Order, pk=order_id)
    return render(request, 'shop/order_success.html', {'order': order})


def about(request):
    """Информационная страница «О магазине»."""
    return render(request, 'shop/about.html')


def contacts(request):
    """Контакты и форма обратной связи (сообщения сохраняются в базу)."""
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                'Сообщение сохранено. Рассылка email не настроена — '
                'это демонстрационный режим учебного проекта.',
            )
            return redirect('shop:contacts')
    else:
        form = ContactForm()
    return render(request, 'shop/contacts.html', {'form': form})


def custom_404(request, exception):
    """Кастомная страница 404."""
    return render(request, 'shop/404.html', status=404)
