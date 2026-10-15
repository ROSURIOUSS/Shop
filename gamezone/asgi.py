"""ASGI entry point for the GameZone project."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gamezone.settings')

application = get_asgi_application()
