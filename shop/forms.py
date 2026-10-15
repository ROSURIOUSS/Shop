"""Формы интернет-магазина GameZone."""
from django import forms

from .models import ContactMessage, Order


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
