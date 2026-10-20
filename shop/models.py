"""Модели интернет-магазина GameZone."""
import re
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.templatetags.static import static


LOW_STOCK_THRESHOLD = 5

COUPON_CODE_RE = re.compile(r'[A-ZА-ЯЁІЇЄҐ0-9_-]{2,32}')

COUPON_CODE_ERROR = (
    'Код состоит из букв, цифр, дефиса и подчёркивания — от 2 до 32 символов.'
)

REVIEW_TEXT_LIMIT = 2000


def with_rating(queryset):
    """Добавить к набору товаров средний рейтинг и число отзывов.

    Агрегаты считаются одним запросом, чтобы списки товаров не делали
    по два обращения к базе на каждую карточку.
    """
    visible = models.Q(reviews__is_visible=True)
    return queryset.annotate(
        rating_avg=models.Avg('reviews__rating', filter=visible),
        rating_count=models.Count('reviews__id', filter=visible),
    )


class Category(models.Model):
    """Категория товара (мышки, клавиатуры, наушники и т.д.)."""

    name = models.CharField('название', max_length=100, unique=True)
    slug = models.SlugField('slug', max_length=100, unique=True)
    description = models.TextField('описание', blank=True)
    image = models.ImageField('изображение', upload_to='categories/', blank=True, null=True)
    created_at = models.DateTimeField('дата создания', auto_now_add=True)

    class Meta:
        verbose_name = 'категория'
        verbose_name_plural = 'Категории'
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('shop:category_detail', kwargs={'slug': self.slug})

    def get_image_url(self):
        """URL изображения категории: загруженное или локальная иллюстрация."""
        if self.image:
            return self.image.url
        return static(f'shop/images/categories/{self.slug}.svg')

    def product_count(self):
        return self.products.filter(is_available=True).count()


class Product(models.Model):
    """Товар магазина — игровая периферия и аксессуары."""

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products',
        verbose_name='категория',
    )
    name = models.CharField('название', max_length=200)
    slug = models.SlugField('slug', max_length=200, unique=True, blank=True)
    description = models.TextField('описание')
    price = models.DecimalField(
        'цена, ₴',
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    image = models.ImageField('изображение', upload_to='products/', blank=True, null=True)
    stock = models.PositiveIntegerField('остаток на складе', default=0)
    is_available = models.BooleanField('в наличии', default=True)
    is_featured = models.BooleanField('популярный товар', default=False)
    specifications = models.JSONField('характеристики', blank=True, null=True)
    created_at = models.DateTimeField('дата создания', auto_now_add=True)
    updated_at = models.DateTimeField('дата обновления', auto_now=True)

    class Meta:
        verbose_name = 'товар'
        verbose_name_plural = 'Товары'
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.price is not None and self.price <= 0:
            raise ValidationError({'price': 'Цена должна быть больше нуля.'})

    def get_absolute_url(self):
        return reverse('shop:product_detail', kwargs={'pk': self.pk})

    def get_image_url(self):
        """URL изображения товара: загруженное или иллюстрация категории."""
        if self.image:
            return self.image.url
        return self.category.get_image_url()

    def in_stock(self):
        """Товар можно купить, если он доступен и есть на складе."""
        return self.is_available and self.stock > 0

    def get_specifications(self):
        """Характеристики в виде списка пар (название, значение)."""
        if not self.specifications:
            return []
        return list(self.specifications.items())

    @property
    def is_low_stock(self):
        """Товар заканчивается: он доступен, но остаток не выше порога."""
        return self.is_available and 0 < self.stock <= LOW_STOCK_THRESHOLD

    def rating_average(self):
        """Средняя оценка по видимым отзывам или None, если отзывов нет."""
        average = self.reviews.filter(is_visible=True).aggregate(
            value=models.Avg('rating')
        )['value']
        if average is None:
            return None
        return round(Decimal(average), 1)

    def rating_count(self):
        """Количество видимых отзывов."""
        return self.reviews.filter(is_visible=True).count()


class Profile(models.Model):
    """Профиль покупателя: контактные данные и адрес доставки по умолчанию."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='пользователь',
    )
    phone = models.CharField('телефон', max_length=30, blank=True)
    city = models.CharField('город', max_length=100, blank=True)
    address = models.CharField('адрес доставки', max_length=255, blank=True)

    class Meta:
        verbose_name = 'профиль'
        verbose_name_plural = 'Профили'

    def __str__(self):
        return f'Профиль {self.user.username}'


class Coupon(models.Model):
    """Промокод: скидка на заказ с ограничением по сроку и числу применений."""

    class Kind(models.TextChoices):
        PERCENT = 'percent', 'Процент от суммы'
        FIXED = 'fixed', 'Фиксированная сумма'

    code = models.CharField('код', max_length=32, unique=True)
    kind = models.CharField(
        'тип скидки', max_length=10, choices=Kind.choices, default=Kind.PERCENT
    )
    value = models.DecimalField(
        'размер скидки', max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    min_total = models.DecimalField(
        'минимальная сумма заказа, ₴', max_digits=10, decimal_places=2,
        default=0, validators=[MinValueValidator(Decimal('0.00'))],
    )
    valid_from = models.DateTimeField('действует с', null=True, blank=True)
    valid_until = models.DateTimeField('действует до', null=True, blank=True)
    usage_limit = models.PositiveIntegerField(
        'сколько раз можно применить', null=True, blank=True,
        help_text='Пустое поле — без ограничений.',
    )
    used_count = models.PositiveIntegerField('применён раз', default=0)
    is_active = models.BooleanField('активен', default=True)
    created_at = models.DateTimeField('создан', auto_now_add=True)

    class Meta:
        verbose_name = 'промокод'
        verbose_name_plural = 'Промокоды'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} — {self.get_kind_display()}: {self.value}'

    @staticmethod
    def normalize_code(value):
        """Привести код к единому виду: без пробелов и в верхнем регистре."""
        return ''.join(str(value or '').split()).upper()

    def clean(self):
        """Проверить код до записи в базу, чтобы не ловить IntegrityError.

        Ввод вроде «Шкафифи» приводится к «ШКАФИФИ» заранее, поэтому проверка
        уникальности сравнивает уже нормализованное значение.
        """
        super().clean()
        self.code = self.normalize_code(self.code)
        if self.code and not COUPON_CODE_RE.fullmatch(self.code):
            raise ValidationError({'code': COUPON_CODE_ERROR})

    def save(self, *args, **kwargs):
        self.code = self.normalize_code(self.code)
        super().save(*args, **kwargs)

    def is_available(self, now=None):
        """Промокод включён, срок действия идёт, лимит не исчерпан."""
        now = now or timezone.now()
        if not self.is_active:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        if self.usage_limit is not None and self.used_count >= self.usage_limit:
            return False
        return True

    def unavailable_reason(self, now=None):
        """Понятная причина, почему промокод не действует."""
        now = now or timezone.now()
        if not self.is_active:
            return 'Промокод отключён.'
        if self.valid_from and now < self.valid_from:
            return 'Срок действия промокода ещё не начался.'
        if self.valid_until and now > self.valid_until:
            return 'Срок действия промокода истёк.'
        if self.usage_limit is not None and self.used_count >= self.usage_limit:
            return 'Лимит применений промокода исчерпан.'
        return ''

    def discount_for(self, subtotal):
        """Скидка для суммы: не больше самой суммы и не меньше минимальной."""
        subtotal = Decimal(subtotal)
        if subtotal <= 0 or subtotal < self.min_total:
            return Decimal('0.00')
        if self.kind == self.Kind.PERCENT:
            discount = subtotal * self.value / Decimal('100')
        else:
            discount = self.value
        return min(discount, subtotal).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class Order(models.Model):
    """Заказ покупателя."""

    class Status(models.TextChoices):
        NEW = 'new', 'Новый'
        CONFIRMED = 'confirmed', 'Подтверждён'
        SHIPPED = 'shipped', 'Отправлен'
        COMPLETED = 'completed', 'Завершён'
        CANCELLED = 'cancelled', 'Отменён'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='orders',
        verbose_name='покупатель',
        null=True,
        blank=True,
    )
    order_number = models.CharField('номер заказа', max_length=32, unique=True, blank=True)
    customer_name = models.CharField('имя и фамилия', max_length=150)
    phone = models.CharField('телефон', max_length=30)
    email = models.EmailField('email', blank=True)
    city = models.CharField('город', max_length=100)
    address = models.CharField('адрес доставки', max_length=255)
    comment = models.TextField('комментарий', blank=True)
    ip_address = models.GenericIPAddressField(
        'IP-адрес покупателя',
        null=True,
        blank=True,
    )
    status = models.CharField(
        'статус',
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )
    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.SET_NULL,
        related_name='orders',
        verbose_name='промокод',
        null=True,
        blank=True,
    )
    discount_amount = models.DecimalField(
        'скидка, ₴', max_digits=10, decimal_places=2, default=0
    )
    total_amount = models.DecimalField('общая сумма, ₴', max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField('дата создания', auto_now_add=True)
    updated_at = models.DateTimeField('дата изменения', auto_now=True)

    class Meta:
        verbose_name = 'заказ'
        verbose_name_plural = 'Заказы'
        ordering = ['-created_at']

    def __str__(self):
        return f'Заказ {self.order_number} — {self.customer_name}'

    def save(self, *args, **kwargs):
        if not self.order_number:
            suffix = uuid4().hex[:4].upper()
            self.order_number = f'GZ-{timezone.now():%Y%m%d-%H%M%S}-{suffix}'
        super().save(*args, **kwargs)

    STATUS_FLOW = {
        'new': ('confirmed', 'cancelled'),
        'confirmed': ('shipped', 'cancelled'),
        'shipped': ('completed',),
        'completed': (),
        'cancelled': (),
    }

    def allowed_transitions(self):
        """Коды статусов, в которые можно перевести заказ из текущего."""
        return list(self.STATUS_FLOW.get(self.status, ()))

    def can_move_to(self, code):
        """Разрешён ли переход в указанный статус."""
        return code in self.allowed_transitions()

    def can_be_cancelled(self):
        """Отменить заказ можно, пока он не отправлен на доставку."""
        return self.can_move_to(self.Status.CANCELLED)

    def status_timeline(self):
        """Шаги жизненного цикла заказа для личного кабинета."""
        steps = (
            (self.Status.NEW, 'Заказ оформлен'),
            (self.Status.CONFIRMED, 'Подтверждён'),
            (self.Status.SHIPPED, 'Отправлен'),
            (self.Status.COMPLETED, 'Завершён'),
        )
        if self.status == self.Status.CANCELLED:
            return [
                {'code': self.Status.CANCELLED, 'label': 'Отменён', 'state': 'cancelled'}
            ]
        codes = [code for code, _label in steps]
        current = codes.index(self.status) if self.status in codes else 0
        timeline = []
        for index, (code, label) in enumerate(steps):
            if index < current:
                state = 'done'
            elif index == current:
                state = 'current'
            else:
                state = 'next'
            timeline.append({'code': code, 'label': label, 'state': state})
        return timeline

    def items_summary(self):
        """Позиции заказа одной строкой — для выгрузок и списка заказов."""
        return '; '.join(
            f'{item.product.name} × {item.quantity}'
            for item in self.items.select_related('product')
        )

    def get_total_cost(self):
        """Общая стоимость заказа, вычисленная из его позиций."""
        total = self.items.aggregate(
            total=models.Sum(models.F('price') * models.F('quantity'), output_field=models.DecimalField())
        )['total']
        return total or Decimal('0.00')


class OrderItem(models.Model):
    """Позиция заказа: товар, количество и цена на момент оформления."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='заказ',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='order_items',
        verbose_name='товар',
    )
    quantity = models.PositiveIntegerField('количество', validators=[MinValueValidator(1)])
    price = models.DecimalField('цена за единицу, ₴', max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = 'позиция заказа'
        verbose_name_plural = 'Позиции заказа'

    def __str__(self):
        return f'{self.product.name} × {self.quantity}'

    def get_cost(self):
        return self.price * self.quantity


class OrderStatusChange(models.Model):
    """Запись истории заказа: кто и когда сменил статус.

    История пишется сервисом `shop/orders.py` — и для кнопок в админке,
    и для отмены покупателем, поэтому в летописи всегда есть автор.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='status_changes',
        verbose_name='заказ',
    )
    from_status = models.CharField(
        'был статус', max_length=20, choices=Order.Status.choices, blank=True,
    )
    to_status = models.CharField(
        'стал статус', max_length=20, choices=Order.Status.choices,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='order_status_changes',
        verbose_name='кто изменил',
        null=True,
        blank=True,
    )
    comment = models.CharField('комментарий', max_length=255, blank=True)
    created_at = models.DateTimeField('дата изменения', auto_now_add=True)

    class Meta:
        verbose_name = 'изменение статуса'
        verbose_name_plural = 'История статусов'
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['order', '-created_at'])]

    def __str__(self):
        return f'{self.order.order_number}: {self.from_label or "создан"} → {self.to_label}'

    @property
    def from_label(self):
        """Название прежнего статуса; пустая строка для только что созданного заказа."""
        return Order.Status(self.from_status).label if self.from_status else ''

    @property
    def to_label(self):
        return Order.Status(self.to_status).label

    @property
    def author_label(self):
        """Кто изменил статус: сотрудник, покупатель или система."""
        if self.changed_by_id:
            user = self.changed_by
            name = user.get_full_name() or user.username
            return f'{name} (сотрудник)' if user.is_staff else name
        return 'Система'


class ContactMessage(models.Model):
    """Обращение с формы обратной связи (демонстрационный режим, без email)."""

    name = models.CharField('имя', max_length=150)
    email = models.EmailField('email')
    subject = models.CharField('тема', max_length=255)
    message = models.TextField('сообщение')
    created_at = models.DateTimeField('дата отправки', auto_now_add=True)

    class Meta:
        verbose_name = 'обращение'
        verbose_name_plural = 'Обращения'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.subject}'


class Review(models.Model):
    """Отзыв покупателя о товаре.

    Отзыв оставляет только тот, кто заказывал этот товар: покупка проверяется
    по позициям незакрытых отменой заказов, поэтому на сайте нет выдуманных оценок.
    """

    RATING_CHOICES = tuple((value, str(value)) for value in range(1, 6))

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name='товар',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name='автор',
    )
    rating = models.PositiveSmallIntegerField(
        'оценка от 1 до 5',
        choices=RATING_CHOICES,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    text = models.TextField(
        'текст отзыва',
        blank=True,
        validators=[MaxLengthValidator(REVIEW_TEXT_LIMIT)],
    )
    is_visible = models.BooleanField('показывать на сайте', default=True)
    created_at = models.DateTimeField('дата публикации', auto_now_add=True)
    updated_at = models.DateTimeField('дата изменения', auto_now=True)

    class Meta:
        verbose_name = 'отзыв'
        verbose_name_plural = 'Отзывы'
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'user'],
                name='unique_review_per_product_and_user',
            ),
        ]
        indexes = [
            models.Index(fields=['product', '-created_at']),
        ]

    def __str__(self):
        return f'{self.product.name} — {self.rating}/5 от {self.author_name}'

    @property
    def author_name(self):
        """Имя автора для витрины: имя и фамилия или логин."""
        full_name = f'{self.user.first_name} {self.user.last_name}'.strip()
        return full_name or self.user.username
