from django.core.management.base import BaseCommand

from desk.services import auto_close_past_trips


class Command(BaseCommand):
    help = 'Expire unbooked requests whose travel date passed, and complete finished trips. Run daily.'

    def handle(self, *args, **options):
        auto_close_past_trips()
        self.stdout.write(self.style.SUCCESS('Done.'))
