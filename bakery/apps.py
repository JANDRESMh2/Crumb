from django.apps import AppConfig


class BakeryConfig(AppConfig):
    name = 'bakery'

    def ready(self):
        from . import signals  # noqa: F401
