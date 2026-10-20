"""Middleware журнала посещений."""
from .utils import log_visit


class VisitLogMiddleware:
    """Пишет в журнал каждое обращение к сайту, кроме статики.

    Стоит первым в списке MIDDLEWARE, чтобы в журнал попадал итоговый код
    ответа — после редиректов CommonMiddleware и SecurityMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        log_visit(request, response)
        return response
