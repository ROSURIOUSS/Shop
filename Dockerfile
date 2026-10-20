FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-prod.txt

COPY . .

RUN python manage.py collectstatic --noinput

CMD python manage.py db_status \
    && python manage.py migrate --noinput \
    && python manage.py seed_data --if-empty \
    && python manage.py ensure_admin \
    && exec gunicorn gamezone.wsgi:application \
        --bind 0.0.0.0:${PORT:-8000} \
        --workers 2 \
        --timeout 90
