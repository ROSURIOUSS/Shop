"""Представления интернет-магазина GameZone."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from activity.models import AuthEvent
from activity.utils import get_client_ip, log_auth_event

from .cart import Cart
from .forms import (
    ContactForm,
    LoginForm,
    OrderForm,
    PasswordChangeForm,
    ProfileForm,
    RegisterForm,
    ReviewForm,
    UserForm,
)
from .models import (
    Category,
    ContactMessage,
    Order,
    OrderItem,
    Product,
    Profile,
    Review,
    with_rating,
)

SORT_OPTIONS = {
    'popular': ('По популярности', ('-is_featured', '-created_at')),
    'price_asc': ('Сначала дешёвые', ('price',)),
    'price_desc': ('Сначала дорогие', ('-price',)),
    'rating': ('По рейтингу', (F('rating_avg').desc(nulls_last=True),)),
    'name': ('По названию А — Я', ('name',)),
    'new': ('Сначала новые', ('-created_at',)),
}
DEFAULT_SORT = 'popular'
PRODUCTS_PER_PAGE = 12


def _first_form_error(form):
    """Первое сообщение об ошибке формы — для журнала событий."""
    for errors in form.errors.values():
        if errors:
            return errors[0]
    return ''


def _get_profile(user):
    """Профиль покупателя: создаётся при регистрации, но мог отсутствовать
    у аккаунтов, созданных через createsuperuser или до появления профилей.
    """
    profile, _created = Profile.objects.get_or_create(user=user)
    return profile


def _has_purchased(user, product):
    """Покупал ли пользователь этот товар (отменённые заказы не считаются)."""
    if not user.is_authenticated:
        return False
    return OrderItem.objects.filter(
        product=product,
        order__user=user,
    ).exclude(order__status=Order.Status.CANCELLED).exists()


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

    queryset = with_rating(queryset).order_by(*SORT_OPTIONS[sort_key][1], 'id')

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
    featured_products = with_rating(
        Product.objects.filter(is_featured=True, is_available=True)
        .select_related('category')
    ).order_by('-created_at')[:4]

    featured_ids = [product.pk for product in featured_products]
    new_products = with_rating(
        Product.objects.filter(is_available=True).exclude(id__in=featured_ids)
        .select_related('category')
    ).order_by('-created_at')[:4]
    if not new_products:
        new_products = with_rating(
            Product.objects.filter(is_available=True).select_related('category')
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


def _product_detail_context(request, product, review_form=None):
    """Общий контекст карточки товара: рейтинги, отзывы, похожие товары."""
    related_products = with_rating(
        Product.objects.filter(category=product.category, is_available=True)
        .exclude(pk=product.pk).select_related('category')
    ).order_by('-created_at')[:4]

    reviews = product.reviews.filter(is_visible=True).select_related('user')
    stats = reviews.aggregate(avg=Avg('rating'), count=Count('id'))
    own_review = None
    if request.user.is_authenticated:
        own_review = product.reviews.filter(user=request.user).first()

    if review_form is None:
        review_form = ReviewForm(instance=own_review)

    return {
        'product': product,
        'related_products': related_products,
        'reviews': reviews,
        'rating_avg': None if stats['avg'] is None else round(Decimal(stats['avg']), 1),
        'rating_count': stats['count'],
        'own_review': own_review,
        'review_form': review_form,
        'can_review': _has_purchased(request.user, product),
    }


def product_detail(request, pk):
    """Карточка товара: изображение, характеристики, отзывы, похожие товары."""
    product = get_object_or_404(Product.objects.select_related('category'), pk=pk)
    return render(
        request, 'shop/product_detail.html', _product_detail_context(request, product)
    )


@login_required
@require_POST
def review_add(request, pk):
    """Оставить или обновить отзыв. Доступно только покупателям товара."""
    product = get_object_or_404(Product.objects.select_related('category'), pk=pk)
    back = product.get_absolute_url() + '#reviews'

    if not _has_purchased(request.user, product):
        messages.error(
            request,
            'Отзыв могут оставить покупатели, которые заказывали этот товар.',
        )
        return redirect(back)

    own_review = Review.objects.filter(product=product, user=request.user).first()
    form = ReviewForm(request.POST, instance=own_review)
    if not form.is_valid():
        messages.error(request, _first_form_error(form) or 'Проверьте данные отзыва.')
        return render(
            request, 'shop/product_detail.html',
            _product_detail_context(request, product, review_form=form),
        )

    review = form.save(commit=False)
    review.product = product
    review.user = request.user
    review.save()
    messages.success(
        request,
        'Отзыв обновлён — спасибо!' if own_review else 'Отзыв опубликован — спасибо!',
    )
    return redirect(back)


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


@login_required
def checkout(request):
    """Оформление заказа: форма + сводка + атомарное создание заказа.

    Заказ доступен только зарегистрированным покупателям и привязывается
    к их аккаунту, поэтому история покупок видна в личном кабинете.
    """
    cart = Cart(request)
    if cart.is_empty():
        messages.info(request, 'Корзина пуста. Добавьте товары перед оформлением заказа.')
        return redirect('shop:cart')

    profile = _get_profile(request.user)
    cart_items = list(cart)
    cart_total = cart.get_total_price()

    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    order = form.save(commit=False)
                    order.user = request.user
                    order.ip_address = get_client_ip(request)
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

                    profile.phone = order.phone
                    profile.city = order.city
                    profile.address = order.address
                    profile.save(update_fields=['phone', 'city', 'address'])
            except ValidationError as error:
                messages.error(request, '; '.join(error.messages))
                return render(request, 'shop/checkout.html', {
                    'form': form,
                    'cart_items': cart_items,
                    'cart_total': cart_total,
                })

            cart.clear()
            request.session['last_order_id'] = order.pk
            log_auth_event(
                request, AuthEvent.Action.ORDER,
                user=request.user, username=request.user.username,
                detail=f'Заказ {order.order_number} на {order.total_amount}',
            )
            return redirect('shop:order_success')
    else:
        form = OrderForm(initial={
            'customer_name': request.user.get_full_name() or request.user.username,
            'phone': profile.phone,
            'email': request.user.email,
            'city': profile.city,
            'address': profile.address,
        })

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


def register(request):
    """Регистрация покупателя с автоматическим входом."""
    if request.user.is_authenticated:
        return redirect('shop:profile')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            Profile.objects.create(user=user)
            login(request, user)
            log_auth_event(request, AuthEvent.Action.REGISTER, user=user, username=user.username)
            messages.success(request, f'Аккаунт «{user.username}» создан. Можно оформлять заказы.')
            return redirect(_safe_next_url(request, 'shop:profile'))
        log_auth_event(
            request, AuthEvent.Action.REGISTER_FAILED,
            username=request.POST.get('username', ''),
            success=False, detail=_first_form_error(form),
        )
    else:
        form = RegisterForm()
    return render(request, 'shop/register.html', {'form': form})


def user_login(request):
    """Вход в аккаунт."""
    if request.user.is_authenticated:
        return redirect('shop:profile')

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            log_auth_event(request, AuthEvent.Action.LOGIN, user=request.user, username=request.user.username)
            messages.success(request, f'С возвращением, {request.user.username}!')
            return redirect(_safe_next_url(request, 'shop:profile'))
        log_auth_event(
            request, AuthEvent.Action.LOGIN_FAILED,
            username=request.POST.get('username', ''),
            success=False, detail=_first_form_error(form),
        )
    else:
        form = LoginForm(request)
    return render(request, 'shop/login.html', {'form': form})


@require_POST
def user_logout(request):
    """Выход из аккаунта (POST — действие защищено CSRF)."""
    log_auth_event(request, AuthEvent.Action.LOGOUT, user=request.user, username=request.user.username)
    logout(request)
    messages.info(request, 'Вы вышли из аккаунта.')
    return redirect('shop:home')


@login_required
def profile(request):
    """Личный кабинет: данные покупателя и история заказов."""
    orders = (
        request.user.orders
        .prefetch_related('items__product')
        .order_by('-created_at')
    )
    return render(request, 'shop/profile.html', {
        'profile': _get_profile(request.user),
        'orders': orders,
    })


@login_required
def profile_edit(request):
    """Изменение имени, email, телефона и адреса доставки."""
    profile = _get_profile(request.user)

    if request.method == 'POST':
        user_form = UserForm(request.POST, instance=request.user)
        profile_form = ProfileForm(request.POST, instance=profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Данные сохранены.')
            return redirect('shop:profile')
    else:
        user_form = UserForm(instance=request.user)
        profile_form = ProfileForm(instance=profile)

    return render(request, 'shop/profile_edit.html', {
        'user_form': user_form,
        'profile_form': profile_form,
        'profile': profile,
    })


@login_required
def password_change(request):
    """Смена пароля. Сессия не сбрасывается, чтобы не пришлось входить снова."""
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            log_auth_event(
                request, AuthEvent.Action.PASSWORD_CHANGE,
                user=request.user, username=request.user.username,
            )
            messages.success(request, 'Пароль изменён.')
            return redirect('shop:profile')
    else:
        form = PasswordChangeForm(user=request.user)
    return render(request, 'shop/password_change.html', {'form': form})


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
