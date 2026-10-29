from django.apps import AppConfig


class DeskConfig(AppConfig):
    name = 'desk'

    def ready(self):
        from .security import connect_signals
        connect_signals()
