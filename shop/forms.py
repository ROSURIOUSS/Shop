"""Формы интернет-магазина GameZone."""
import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.forms import PasswordChangeForm as DjangoPasswordChangeForm

from .models import REVIEW_TEXT_LIMIT, ContactMessage, Order, Profile, Review

User = get_user_model()


class OrderForm(forms.ModelForm):
    """Форма оформления заказа."""

    class Meta:
        model = Order
        fields = ['customer_name', 'phone', 'email', 'city', 'address', 'comment']
        widgets = {
            'customer_name': forms.TextInput(attrs={
                'placeholder': 'Иван Петренко',
                'autocomplete': 'name',
            }),
            'phone': forms.TextInput(attrs={
                'placeholder': '+380 __ ___ __ __',
                'autocomplete': 'tel',
                'type': 'tel',
            }),
            'email': forms.EmailInput(attrs={
                'placeholder': 'you@example.com',
                'autocomplete': 'email',
            }),
            'city': forms.TextInput(attrs={
                'placeholder': 'Киев',
                'autocomplete': 'address-level2',
            }),
            'address': forms.TextInput(attrs={
                'placeholder': 'Улица, дом, квартира',
                'autocomplete': 'street-address',
            }),
            'comment': forms.Textarea(attrs={
                'placeholder': 'Комментарий к заказу (необязательно)',
                'rows': 3,
            }),
        }
        labels = {
            'customer_name': 'Имя и фамилия',
            'phone': 'Телефон',
            'email': 'Email',
            'city': 'Город',
            'address': 'Адрес доставки',
            'comment': 'Комментарий',
        }

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if len(digits) < 9:
            raise forms.ValidationError('Введите корректный номер телефона (минимум 9 цифр).')
        return phone


class ContactForm(forms.ModelForm):
    """Форма обратной связи. Сообщения сохраняются в базу (демо-режим)."""

    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ваше имя'}),
            'email': forms.EmailInput(attrs={'placeholder': 'you@example.com'}),
            'subject': forms.TextInput(attrs={'placeholder': 'Тема обращения'}),
            'message': forms.Textarea(attrs={'placeholder': 'Ваше сообщение', 'rows': 5}),
        }
        labels = {
            'name': 'Имя',
            'email': 'Email',
            'subject': 'Тема',
            'message': 'Сообщение',
        }

class RegisterForm(UserCreationForm):
    """Регистрация покупателя."""

    email = forms.EmailField(
        label='Email',
        required=True,
        widget=forms.EmailInput(attrs={
            'placeholder': 'you@example.com',
            'autocomplete': 'email',
        }),
        help_text='Укажите действующий email: он попадёт в ваши заказы для связи.',
    )
    password1 = forms.CharField(
        label='Пароль',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Придумайте пароль',
            'autocomplete': 'new-password',
        }),
        help_text='Минимум 8 символов, не только цифры и не совпадающий с логином.',
    )
    password2 = forms.CharField(
        label='Пароль ещё раз',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Повторите пароль',
            'autocomplete': 'new-password',
        }),
    )

    class Meta:
        model = User
        fields = ['username', 'email']
        widgets = {
            'username': forms.TextInput(attrs={
                'placeholder': 'например, gamer_pro',
                'autocomplete': 'username',
            }),
        }

    def clean_email(self):
        """Email должен быть уникальным — по нему магазин связывается с покупателем."""
        email = self.cleaned_data.get('email', '').strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Пользователь с таким email уже зарегистрирован.')
        return email


class LoginForm(AuthenticationForm):
    """Вход в аккаунт."""

    username = forms.CharField(
        label='Логин',
        widget=forms.TextInput(attrs={
            'placeholder': 'Ваш логин',
            'autocomplete': 'username',
            'autofocus': True,
        }),
    )
    password = forms.CharField(
        label='Пароль',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Ваш пароль',
            'autocomplete': 'current-password',
        }),
    )


class UserForm(forms.ModelForm):
    """Изменение имени, фамилии и email покупателя."""

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        labels = {
            'first_name': 'Имя',
            'last_name': 'Фамилия',
            'email': 'Email',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={'placeholder': 'Иван', 'autocomplete': 'given-name'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Петренко', 'autocomplete': 'family-name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'you@example.com', 'autocomplete': 'email'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True

    def clean_email(self):
        """Email остаётся уникальным среди всех покупателей."""
        email = self.cleaned_data.get('email', '').strip()
        taken = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists()
        if taken:
            raise forms.ValidationError('Этот email уже занят другим покупателем.')
        return email


class ProfileForm(forms.ModelForm):
    """Контакты и адрес доставки из профиля покупателя."""

    class Meta:
        model = Profile
        fields = ['phone', 'city', 'address']
        labels = {
            'phone': 'Телефон',
            'city': 'Город',
            'address': 'Адрес доставки',
        }
        widgets = {
            'phone': forms.TextInput(attrs={'placeholder': '+380 __ ___ __ __', 'autocomplete': 'tel'}),
            'city': forms.TextInput(attrs={'placeholder': 'Харьков', 'autocomplete': 'address-level2'}),
            'address': forms.TextInput(attrs={
                'placeholder': 'Отделение или улица, дом, квартира',
                'autocomplete': 'street-address',
            }),
        }

    def clean_phone(self):
        """Телефон необязателен, но если указан — в нём должны быть цифры."""
        phone = self.cleaned_data.get('phone', '').strip()
        if phone and len(re.sub(r'\D', '', phone)) < 9:
            raise forms.ValidationError('Укажите телефон полностью, например +380501112233.')
        return phone


class PasswordChangeForm(DjangoPasswordChangeForm):
    """Смена пароля с русскими подписями полей."""

    old_password = forms.CharField(
        label='Текущий пароль',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Введите текущий пароль',
            'autocomplete': 'current-password',
        }),
    )
    new_password1 = forms.CharField(
        label='Новый пароль',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Придумайте новый пароль',
            'autocomplete': 'new-password',
        }),
        help_text='Минимум 8 символов, не только цифры и не совпадающий с логином.',
    )
    new_password2 = forms.CharField(
        label='Новый пароль ещё раз',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Повторите новый пароль',
            'autocomplete': 'new-password',
        }),
    )


RATING_FORM_CHOICES = (
    ('', 'Выберите оценку'),
    ('5', '5 — отлично'),
    ('4', '4 — хорошо'),
    ('3', '3 — нормально'),
    ('2', '2 — плохо'),
    ('1', '1 — очень плохо'),
)


class ReviewForm(forms.ModelForm):
    """Отзыв покупателя: оценка от 1 до 5 и необязательный текст."""

    rating = forms.ChoiceField(
        label='Оценка',
        choices=RATING_FORM_CHOICES,
        widget=forms.Select(attrs={'class': 'review-rating'}),
    )

    def clean_rating(self):
        """Оценка обязательна и лежит в диапазоне от 1 до 5."""
        value = self.cleaned_data.get('rating')
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise forms.ValidationError('Выберите оценку от 1 до 5.')
        if not 1 <= number <= 5:
            raise forms.ValidationError('Оценка должна быть от 1 до 5.')
        return number

    class Meta:
        model = Review
        fields = ['rating', 'text']
        labels = {
            'rating': 'Оценка',
            'text': 'Впечатления',
        }
        widgets = {
            'text': forms.Textarea(attrs={
                'placeholder': 'Что понравилось, что нет — только по делу',
                'rows': 4,
                'maxlength': REVIEW_TEXT_LIMIT,
            }),
        }
        help_texts = {
            'rating': '1 — очень плохо, 5 — отлично.',
            'text': f'Текст необязателен, но он помогает другим покупателям (до {REVIEW_TEXT_LIMIT} символов).',
        }

    def clean_text(self):
        """Отзыв без текста допустим, но пробелы и переносы не считаются содержимым."""
        return self.cleaned_data['text'].strip()


class CouponForm(forms.Form):
    """Ввод промокода. Проверка и пересчёт скидки — на сервере."""

    code = forms.CharField(
        label='Промокод',
        max_length=32,
        widget=forms.TextInput(attrs={
            'placeholder': 'Например, GAMEZONE10',
            'autocomplete': 'off',
            'class': 'input',
        }),
    )

    def clean_code(self):
        """Код приводится к верхнему регистру и без пробелов по краям."""
        code = self.cleaned_data['code'].strip().upper()
        if not code:
            raise forms.ValidationError('Введите промокод.')
        if not re.fullmatch(r'[A-Z0-9_-]{2,32}', code):
            raise forms.ValidationError(
                'Код состоит из латинских букв, цифр, дефиса и подчёркивания.'
            )
        return code
