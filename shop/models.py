"""Модели интернет-магазина GameZone."""
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.templatetags.static import static


LOW_STOCK_THRESHOLD = 5

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
