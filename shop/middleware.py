"""Middleware проекта GameZone."""
from django.shortcuts import render
from django.conf import settings


class CustomDebug404Middleware:
    """Показывать шаблон shop/404.html даже при DEBUG=True.

    В режиме разработки Django заменяет страницу 404 технической
    диагностикой. Для учебного проекта удобнее видеть настоящий
    дизайн страницы ошибки, поэтому middleware подменяет ответ.
    При DEBUG=False работает стандартный handler404 из gamezone/urls.py.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.DEBUG and response.status_code == 404:
            return render(request, 'shop/404.html', status=404)
        return response
