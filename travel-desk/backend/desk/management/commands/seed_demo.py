from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from desk import services
from desk.models import Profile, TravelRequest
from desk.serializers import save_legs, trip_dates

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

# Each sample trip:
#   requester, traveller (None = the requester; or (name, phone) for someone else),
#   legs = [(service, origin, destination, starts in N days, hotel nights, is_return)],
#   estimated cost, purpose, steps = [(username, action, comment)] run through the real workflow.
SAMPLE_TRIPS = [
    ('asha', None, [('FLIGHT', 'Pune', 'Bengaluru', 6, 0, False), ('FLIGHT', 'Bengaluru', 'Pune', 8, 0, True)],
     9500, 'Product demo for Infosys procurement team', []),
    ('ravi', None, [('TRAIN', 'Pune', 'Mumbai', 10, 0, False), ('FLIGHT', 'Mumbai', 'Delhi', 10, 0, False),
                    ('HOTEL', '', 'Delhi', 10, 2, False), ('FLIGHT', 'Delhi', 'Pune', 12, 0, True)],
     24000, 'Quarterly review with North India distributors', []),
    ('ravi', ('Kavita Menon (guest speaker)', '+91 98200 11223'),
     [('FLIGHT', 'Chennai', 'Hyderabad', 14, 0, False), ('HOTEL', '', 'Hyderabad', 14, 2, False),
      ('FLIGHT', 'Hyderabad', 'Chennai', 16, 0, True)],
     21000, 'Guest speaker for the partner workshop at Hitech City', [('meera', 'approve', '')]),
    ('asha', None, [('CAB', 'Pune', 'Mumbai Airport', 4, 0, False)], 3500,
     'Airport drop for international client visit', [('meera', 'approve', ''), ('sara', 'pick_up', '')]),
    ('ravi', None, [('FLIGHT', 'Delhi', 'Kolkata', 20, 0, False), ('FLIGHT', 'Kolkata', 'Delhi', 22, 0, True)],
     11000, 'Annual contract renewal meeting with Tata Steel',
     [('meera', 'return', 'Please take the early morning flight so you can skip the hotel night.')]),
    ('meera', None, [('FLIGHT', 'Mumbai', 'Goa', 25, 0, False), ('HOTEL', '', 'Goa', 25, 3, False),
                     ('FLIGHT', 'Goa', 'Mumbai', 28, 0, True)],
     15000, 'Regional sales offsite planning with the West team', []),
    ('asha', None, [('TRAIN', 'Pune', 'Chennai', 30, 0, False), ('HOTEL', '', 'Chennai', 31, 2, False)],
     9000, 'Customer onboarding sessions at the Chennai branch',
     [('meera', 'approve', ''), ('deepak', 'pick_up', ''), ('deepak', 'book_all', '')]),
    ('ravi', None, [('FLIGHT', 'Pune', 'Jaipur', 12, 0, False)], 8000,
     'Trade fair visit to scout new channel partners', [('meera', 'reject', 'Budget freeze on trade fairs this quarter.')]),
    ('asha', None, [('TRAIN', 'Pune', 'Nashik', 9, 0, False)], 900,
     'Site visit for the Nashik warehouse rollout', [('asha', 'cancel', '')]),
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
        for emp, traveller, legs, cost, purpose, steps in SAMPLE_TRIPS:
            employee = users[emp]
            legs = [dict(service=s, origin=o, destination=d, date=today + timedelta(days=day),
                         end_date=today + timedelta(days=day + nights) if nights else None, is_return=back)
                    for s, o, d, day, nights, back in legs]
            start, end = trip_dates(legs)
            name, phone = traveller or (services.display_name(employee), '')
            req = TravelRequest.objects.create(
                employee=employee, approver=services.get_approver(employee),
                traveller_is_requester=traveller is None, traveller_name=name, traveller_phone=phone,
                traveller_email=employee.email if traveller is None else '',
                start_date=start, end_date=end, purpose=purpose, estimated_cost=cost, submitted_at=timezone.now(),
            )
            save_legs(req, legs)
            services._log(req, employee, 'submit', '')
            services._notify_for('submit', req, employee, '', '')

            for actor, action, comment in steps:
                if action == 'book_all':  # the desk books every leg, one ticket each
                    for leg in req.legs.all():
                        services.perform_action(
                            users[actor], req.pk, 'book_leg', '',
                            data={'leg': leg.pk, 'booking_reference': f'PNR{req.pk:03d}{leg.position}X',
                                  'actual_cost': str(cost // len(legs))},
                            files={'ticket': SimpleUploadedFile('ticket.pdf', b'%PDF-1.4 demo ticket')})
                else:
                    services.perform_action(users[actor], req.pk, action, comment)

        # Make the first one overdue so the "Overdue" card has something to show.
        first = TravelRequest.objects.filter(purpose__startswith='Product demo').first()
        if first:
            TravelRequest.objects.filter(pk=first.pk).update(submitted_at=timezone.now() - timedelta(hours=60))
        self.stdout.write(f'Created {len(SAMPLE_TRIPS)} sample trips.')
