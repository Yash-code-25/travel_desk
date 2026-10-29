from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from desk import services
from desk.models import Profile, TravelRequest

User = get_user_model()

DEMO_PASSWORD = 'demo1234'  # local demo accounts only

# username, first, last, role, manager username, department
DEMO_USERS = [
    ('director', 'Vikram', 'Rao', 'MANAGER', None, 'Leadership'),
    ('meera', 'Meera', 'Shah', 'MANAGER', 'director', 'Sales'),
    ('asha', 'Asha', 'Patil', 'EMPLOYEE', 'meera', 'Sales'),
    ('ravi', 'Ravi', 'Kumar', 'EMPLOYEE', 'meera', 'Sales'),
    ('newjoiner', 'Neha', 'Joshi', 'EMPLOYEE', None, 'Sales'),  # no manager yet -> can't submit
    ('deepak', 'Deepak', 'Nair', 'DESK', 'director', 'Travel Desk'),
    ('sara', 'Sara', 'Khan', 'DESK', 'director', 'Travel Desk'),
]

# employee, service, origin, destination, starts in N days, length in days, cost, purpose, steps
# steps = list of (username, action, comment) run through the real workflow
SAMPLE_TRIPS = [
    ('asha', 'FLIGHT', 'Pune', 'Bengaluru', 6, 2, 9500, 'Product demo for Infosys procurement team', []),
    ('ravi', 'TRAIN', 'Mumbai', 'Ahmedabad', 10, 1, 2400, 'Quarterly review with Gujarat distributors', []),
    ('ravi', 'HOTEL', '', 'Hyderabad', 14, 2, 12000, 'Two-day partner workshop at Hitech City',
     [('meera', 'approve', '')]),
    ('asha', 'CAB', 'Pune', 'Mumbai Airport', 4, 0, 3500, 'Airport drop for international client visit',
     [('meera', 'approve', ''), ('sara', 'pick_up', '')]),
    ('ravi', 'FLIGHT', 'Delhi', 'Kolkata', 20, 2, 11000, 'Annual contract renewal meeting with Tata Steel',
     [('meera', 'return', 'Please take the early morning flight so you can skip the hotel night.')]),
    ('meera', 'FLIGHT', 'Mumbai', 'Goa', 25, 3, 15000, 'Regional sales offsite planning with the West team', []),
    ('asha', 'HOTEL', '', 'Chennai', 30, 2, 9000, 'Customer onboarding sessions at the Chennai branch',
     [('meera', 'approve', ''), ('deepak', 'pick_up', ''), ('deepak', 'book', '')]),
    ('ravi', 'FLIGHT', 'Pune', 'Jaipur', 12, 1, 8000, 'Trade fair visit to scout new channel partners',
     [('meera', 'reject', 'Budget freeze on trade fairs this quarter.')]),
    ('asha', 'TRAIN', 'Pune', 'Nashik', 9, 0, 900, 'Site visit for the Nashik warehouse rollout',
     [('asha', 'cancel', '')]),
]


class Command(BaseCommand):
    help = f'Create demo users (password: {DEMO_PASSWORD}). --with-trips adds sample requests. DEBUG only.'

    def add_arguments(self, parser):
        parser.add_argument('--with-trips', action='store_true', help='Also create sample travel requests.')
        parser.add_argument('--force', action='store_true', help='Run even when DEBUG is off (tests only).')

    def handle(self, *args, **options):
        if not (settings.DEBUG or options['force']):
            raise CommandError('Refusing to create demo accounts with known passwords: DEBUG is off.')
        for username, first, last, role, _, dept in DEMO_USERS:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={'first_name': first, 'last_name': last, 'email': f'{username}@example.com'},
            )
            user.set_password(DEMO_PASSWORD)
            user.save()
            Profile.objects.update_or_create(user=user, defaults={'role': role, 'department': dept})

        for username, *_, manager, _ in DEMO_USERS:
            Profile.objects.filter(user__username=username).update(
                manager=User.objects.filter(username=manager).first() if manager else None
            )

        # No built-in admin account: create one yourself with `python manage.py createsuperuser`.
        if options['with_trips']:
            self.create_trips()

        self.stdout.write(self.style.SUCCESS(
            f'Demo users ready: {", ".join(u[0] for u in DEMO_USERS)} (password {DEMO_PASSWORD})'
        ))

    def create_trips(self):
        today = timezone.localdate()
        users = {u.username: u for u in User.objects.all()}
        for emp, service, origin, dest, start_in, days, cost, purpose, steps in SAMPLE_TRIPS:
            employee = users[emp]
            start = today + timedelta(days=start_in)
            req = TravelRequest.objects.create(
                employee=employee, approver=services.get_approver(employee), service=service,
                origin=origin, destination=dest, start_date=start,
                end_date=start + timedelta(days=days) if days else None,
                purpose=purpose, estimated_cost=cost, submitted_at=timezone.now(),
            )
            services._log(req, employee, 'submit', '')
            services._notify_for('submit', req, employee, '', '')

            for actor, action, comment in steps:
                extra = {}
                if action == 'book':
                    extra = dict(
                        data={'booking_reference': f'PNR{req.pk:04d}X', 'actual_cost': str(cost)},
                        files={'ticket': SimpleUploadedFile('ticket.pdf', b'%PDF-1.4 demo ticket')},
                    )
                services.perform_action(users[actor], req.pk, action, comment, **extra)

        # Make the first one overdue so the "Overdue" card has something to show.
        first = TravelRequest.objects.filter(destination='Bengaluru').first()
        if first:
            TravelRequest.objects.filter(pk=first.pk).update(submitted_at=timezone.now() - timedelta(hours=60))
        self.stdout.write(f'Created {len(SAMPLE_TRIPS)} sample trips.')
