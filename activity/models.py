"""Модели журнала активности: посещения страниц и события аккаунтов."""
from django.conf import settings
from django.db import models


class VisitLog(models.Model):
    """Одно обращение к сайту: IP-адрес, страница, браузер и кто был в аккаунте."""

    ip_address = models.GenericIPAddressField('IP-адрес', null=True, blank=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='visits',
        verbose_name='посетитель',
        null=True,
        blank=True,
    )
    path = models.CharField('адрес страницы', max_length=400, db_index=True)
    method = models.CharField('метод запроса', max_length=10, default='GET')
    status_code = models.PositiveSmallIntegerField('код ответа', null=True, blank=True)
    browser = models.CharField('браузер', max_length=40, blank=True)
    os = models.CharField('операционная система', max_length=40, blank=True)
    user_agent = models.CharField('user agent', max_length=400, blank=True)
    referer = models.CharField('откуда пришёл', max_length=400, blank=True)
    created_at = models.DateTimeField('время', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'посещение'
        verbose_name_plural = 'Журнал посещений'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ip_address', '-created_at'], name='visit_ip_time'),
        ]

    def __str__(self):
        return f'{self.ip_address or "IP не определён"} → {self.path}'


class AuthEvent(models.Model):
    """Значимое действие покупателя: регистрация, вход, выход, заказ."""

    class Action(models.TextChoices):
        REGISTER = 'register', 'Регистрация'
        REGISTER_FAILED = 'register_failed', 'Неудачная регистрация'
        LOGIN = 'login', 'Вход'
        LOGIN_FAILED = 'login_failed', 'Неудачный вход'
        LOGOUT = 'logout', 'Выход'
        PASSWORD_CHANGE = 'password_change', 'Смена пароля'
        ORDER = 'order', 'Оформлен заказ'

    action = models.CharField('событие', max_length=20, choices=Action.choices, db_index=True)
    success = models.BooleanField('успешно', default=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='auth_events',
        verbose_name='покупатель',
        null=True,
        blank=True,
    )
    username = models.CharField('логин из формы', max_length=150, blank=True)
    ip_address = models.GenericIPAddressField('IP-адрес', null=True, blank=True, db_index=True)
    browser = models.CharField('браузер', max_length=40, blank=True)
    os = models.CharField('операционная система', max_length=40, blank=True)
    user_agent = models.CharField('user agent', max_length=400, blank=True)
    detail = models.CharField('детали', max_length=200, blank=True)
    created_at = models.DateTimeField('время', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'событие'
        verbose_name_plural = 'События покупателей'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_action_display()} — {self.username or (self.user and self.user.username) or "гость"}'
