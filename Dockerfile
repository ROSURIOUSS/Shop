# Образ для хостинга, который собирает проект через Docker
# (Render с рантаймом Docker, Railway, свой VPS).
# Если хостинг использует обычный Python-рантайм, этот файл не задействуется:
# там работают buildCommand и startCommand из render.yaml.

FROM python:3.13-slim

# PYTHONUNBUFFERED — логи сразу видны в консоли хостинга,
# PYTHONDONTWRITEBYTECODE — не мусорим .pyc-файлами.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала только зависимости: этот слой кэшируется, поэтому повторные сборки
# идут быстро, если менялся код, а requirements — нет.
# Все пакеты ставятся из готовых wheel, компилятор в образе не нужен.
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-prod.txt

# Теперь сам проект (содержимое .dockerignore в образ не попадает).
COPY . .

# Статику раздаёт WhiteNoise из папки staticfiles.
RUN python manage.py collectstatic --noinput

# Хостинг передаёт номер порта в переменной PORT (на Render это 10000).
# Перед запуском сервера приводим базу в рабочее состояние:
# миграции, демо-товары (только в пустую базу) и администратор из
# переменных окружения — все три команды безопасны при повторном запуске.
CMD python manage.py migrate --noinput \
    && python manage.py seed_data --if-empty \
    && python manage.py ensure_admin \
    && exec gunicorn gamezone.wsgi:application \
        --bind 0.0.0.0:${PORT:-8000} \
        --workers 2 \
        --timeout 90
