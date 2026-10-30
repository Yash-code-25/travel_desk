from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from desk import profiles, services
from desk.models import FrequentFlyer, Notification, Profile, TravelProfile, TravelRequest, Visa
from desk.serializers import save_legs, trip_dates

User = get_user_model()

DEMO_PASSWORD = 'demo1234'  # local demo accounts only

# username, first, last, role, manager username, department
DEMO_USERS = [
    ('director', 'Vikram', 'Rao', 'MANAGER', None, 'Leadership'),
    ('meera', 'Meera', 'Shah', 'MANAGER', 'director', 'Sales'),
    ('asha', 'Asha', 'Patil', 'EMPLOYEE', 'meera', 'Sales'),
    ('ravi', 'Ravi', 'Kumar', 'EMPLOYEE', 'meera', 'Sales'),
    ('newjoiner', 'Neha', 'Joshi', 'EMPLOYEE', None, 'Sales'),  # no manager, no profile yet: shows the first-sign-in form
    ('anil', 'Anil', 'Mehta', 'TRAVEL_MGR', 'director', 'Travel Desk'),
    ('deepak', 'Deepak', 'Nair', 'DESK', 'director', 'Travel Desk'),
    ('sara', 'Sara', 'Khan', 'DESK', 'director', 'Travel Desk'),
]

# Filled-in travel profiles (--with-trips). Neha has none on purpose.
#   designation, phone, date of birth, gender, PAN, Aadhaar last 4, seat, meal,
#   passport (number, place, issued, expires) or None, visas [(country, type, valid until)],
#   frequent flyer [(airline, number)], forex (bank, last 4) or None
DEMO_PROFILES = {
    'director': ('Sales Director', '+91 98220 10001', '1978-03-14', 'MALE', 'AKRPR4521K', '7712', 'AISLE', 'NON_VEG',
                 ('W4821736', 'Mumbai', '2019-06-10', '2029-06-09'), [('United States', 'B1/B2 Business', '2030-01-31')],
                 [('Air India', 'AI4471902'), ('Vistara', 'UK880214')], ('ICICI Bank', '9034')),
    'meera': ('Regional Sales Manager', '+91 98220 10002', '1985-11-02', 'FEMALE', 'BMSPS7810Q', '3391', 'WINDOW', 'VEG',
              ('V7391054', 'Pune', '2021-02-18', '2031-02-17'), [('United Kingdom', 'Standard Visitor', '2027-09-30')],
              [('IndiGo', '6E7730012')], None),
    'asha': ('Senior Sales Executive', '+91 98220 10003', '1994-05-12', 'FEMALE', 'CQAPP2214M', '1234', 'WINDOW', 'VEG',
             ('Z1234567', 'Pune', '2022-01-10', '2032-01-09'),
             [('United States', 'B1/B2 Business', '2028-06-30'), ('United Arab Emirates', 'Business (multiple entry)', '2027-12-31')],
             [('Air India', 'AI9988770')], ('HDFC Bank', '4321')),
    'ravi': ('Sales Executive', '+91 98220 10004', '1996-08-23', 'MALE', 'DRKPK5532L', '5566', 'AISLE', 'NON_VEG',
             None, [], [], None),
    'anil': ('Travel Manager', '+91 98220 10005', '1982-01-30', 'MALE', 'EAMPM9012R', '8820', 'AISLE', 'VEG',
             ('T5530912', 'Mumbai', '2020-09-01', '2030-08-31'), [], [], None),
    'deepak': ('Travel Desk Executive', '+91 98220 10006', '1990-12-05', 'MALE', 'FDNPN3345T', '4471', 'WINDOW', 'NON_VEG',
               None, [], [], None),
    'sara': ('Travel Desk Executive', '+91 98220 10007', '1993-04-17', 'FEMALE', 'GSKPK6678H', '9902', 'ANY', 'VEG',
             None, [], [], None),
}

# Sample trips, all raised by the traveller themselves.
#   legs: (service, from, from country, to, to country, starts in N days, hotel nights, is_return)
#         countries are only used for international trips
#   steps: (username, action, comment) run through the real workflow ('assign:sara', 'book:2' = book 2 legs)
IN, AE, GB, SG = 'India', 'United Arab Emirates', 'United Kingdom', 'Singapore'
SAMPLE_TRIPS = [
    dict(by='asha', type='DOMESTIC', cost=9500, overdue=True, purpose='Product demo for the Infosys procurement team',
         legs=[('FLIGHT', 'Pune', IN, 'Bengaluru', IN, 6, 0, False), ('FLIGHT', 'Bengaluru', IN, 'Pune', IN, 8, 0, True)],
         steps=[]),
    dict(by='ravi', type='DOMESTIC', cost=24000, purpose='Quarterly review with North India distributors',
         legs=[('TRAIN', 'Pune', IN, 'Mumbai', IN, 10, 0, False), ('FLIGHT', 'Mumbai', IN, 'Delhi', IN, 10, 0, False),
               ('HOTEL', '', '', 'Delhi', IN, 10, 2, False), ('FLIGHT', 'Delhi', IN, 'Pune', IN, 12, 0, True)],
         steps=[]),
    dict(by='asha', type='INTERNATIONAL', cost=145000, purpose='Gulf distributor summit and partner meetings in Dubai',
         legs=[('FLIGHT', 'Mumbai', IN, 'Dubai', AE, 18, 0, False), ('CAB', 'Dubai Airport', AE, 'Business Bay', AE, 18, 0, False),
               ('HOTEL', '', '', 'Dubai', AE, 18, 3, False), ('FLIGHT', 'Dubai', AE, 'Mumbai', IN, 21, 0, True)],
         steps=[('meera', 'approve', '')]),  # waiting for the Travel Manager
    dict(by='ravi', type='DOMESTIC', cost=21000, purpose='Partner workshop at the Hitech City office',
         legs=[('FLIGHT', 'Pune', IN, 'Hyderabad', IN, 14, 0, False), ('HOTEL', '', '', 'Hyderabad', IN, 14, 2, False),
               ('FLIGHT', 'Hyderabad', IN, 'Pune', IN, 16, 0, True)],
         steps=[('meera', 'approve', ''), ('anil', 'assign:sara', ''), ('sara', 'book:1', '')]),  # 1 of 3 booked
    dict(by='meera', type='INTERNATIONAL', cost=210000, purpose='Annual key-account review with the UK enterprise clients',
         legs=[('FLIGHT', 'Mumbai', IN, 'London', GB, 30, 0, False), ('HOTEL', '', '', 'London', GB, 30, 4, False),
               ('FLIGHT', 'London', GB, 'Mumbai', IN, 34, 0, True)],
         steps=[('director', 'approve', ''), ('anil', 'assign:deepak', ''), ('deepak', 'book:all', '')]),
    dict(by='meera', type='INTERNATIONAL', cost=160000, forex_needed=True,
         purpose='APAC channel partner conference in Singapore',
         legs=[('FLIGHT', 'Mumbai', IN, 'Singapore', SG, 45, 0, False), ('HOTEL', '', '', 'Singapore', SG, 45, 3, False),
               ('FLIGHT', 'Singapore', SG, 'Mumbai', IN, 48, 0, True)],
         steps=[]),  # no Singapore visa in her profile: flagged "Visa needed"
    dict(by='ravi', type='DOMESTIC', cost=11000, purpose='Annual contract renewal meeting with Tata Steel',
         legs=[('FLIGHT', 'Delhi', IN, 'Kolkata', IN, 20, 0, False), ('FLIGHT', 'Kolkata', IN, 'Delhi', IN, 22, 0, True)],
         steps=[('meera', 'return', 'Please take the early morning flight so you can skip the hotel night.')]),
    dict(by='asha', type='DOMESTIC', cost=9000, purpose='Customer onboarding sessions at the Chennai branch',
         legs=[('TRAIN', 'Pune', IN, 'Chennai', IN, 24, 0, False), ('HOTEL', '', '', 'Chennai', IN, 25, 2, False)],
         steps=[('meera', 'approve', ''), ('anil', 'assign:deepak', ''), ('deepak', 'book:all', ''),
                ('asha', 'request_cancel', 'The customer moved the onboarding to next month.')]),
    dict(by='ravi', type='DOMESTIC', cost=8000, purpose='Trade fair visit to scout new channel partners',
         legs=[('FLIGHT', 'Pune', IN, 'Jaipur', IN, 12, 0, False)],
         steps=[('meera', 'reject', 'Budget freeze on trade fairs this quarter.')]),
    dict(by='asha', type='DOMESTIC', cost=900, purpose='Site visit for the Nashik warehouse rollout',
         legs=[('TRAIN', 'Pune', IN, 'Nashik', IN, 9, 0, False)],
         steps=[('asha', 'cancel', '')]),
    dict(by='deepak', type='DOMESTIC', cost=14000, purpose='Hotel partnership negotiations for the Goa offsite',
         legs=[('FLIGHT', 'Pune', IN, 'Goa', IN, 27, 0, False), ('HOTEL', '', '', 'Goa', IN, 27, 2, False),
               ('FLIGHT', 'Goa', IN, 'Pune', IN, 29, 0, True)],
         steps=[('director', 'approve', ''), ('anil', 'pick_up', '')]),  # the Travel Manager books it personally
]


def pdf(name):
    return SimpleUploadedFile(name, b'%PDF-1.4 demo document', content_type='application/pdf')


class Command(BaseCommand):
    help = (f'Create demo users (password: {DEMO_PASSWORD}). --with-trips also fills their profiles and adds '
            'sample requests. --reset first removes ALL travel requests and the demo profiles. DEBUG only.')

    def add_arguments(self, parser):
        parser.add_argument('--with-trips', action='store_true', help='Also fill profiles and create sample requests.')
        parser.add_argument('--reset', action='store_true', help='Delete every travel request and demo profile first.')
        parser.add_argument('--force', action='store_true', help='Run even when DEBUG is off (tests only).')

    def handle(self, *args, **options):
        if not (settings.DEBUG or options['force']):
            raise CommandError('Refusing to create demo accounts with known passwords: DEBUG is off.')
        if options['reset']:
            self.reset()
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
            self.create_profiles()
            self.create_trips()

        self.stdout.write(self.style.SUCCESS(
            f'Demo users ready: {", ".join(u[0] for u in DEMO_USERS)} (password {DEMO_PASSWORD})'
        ))

    # ------------------------------------------------------------ reset
    def reset(self):
        """Every travel request (with tickets, history, notifications) and the demo users' profiles."""
        with transaction.atomic():
            for req in TravelRequest.objects.prefetch_related('legs'):
                for leg in req.legs.all():
                    if leg.ticket:
                        leg.ticket.delete(save=False)
            count = TravelRequest.objects.count()
            TravelRequest.objects.all().delete()
            Notification.objects.all().delete()
            demo = [u[0] for u in DEMO_USERS]
            for p in TravelProfile.objects.filter(user__username__in=demo).prefetch_related('visas'):
                for f in [p.aadhaar_file, p.pan_file, p.passport_file] + [v.file for v in p.visas.all()]:
                    if f:
                        f.delete(save=False)
                p.delete()
            Profile.objects.filter(user__username__in=demo).update(profile_completed_at=None)
        self.stdout.write(f'Removed {count} travel requests and the demo profiles.')

    # ------------------------------------------------------------ profiles
    def create_profiles(self):
        users = {u.username: u for u in User.objects.filter(username__in=DEMO_PROFILES)}
        for username, (designation, phone, dob, gender, pan, aadhaar, seat, meal,
                       passport, visas, flyers, forex) in DEMO_PROFILES.items():
            user = users[username]
            if TravelProfile.objects.filter(user=user).exists():
                continue  # keep a profile someone already filled in
            p = TravelProfile(
                user=user, date_of_birth=dob, gender=gender, address=f'{10 + len(username)} FC Road, Shivajinagar, Pune 411005',
                emergency_contact_name=f'{user.last_name} family', emergency_contact_phone='+91 90110 20000',
                aadhaar_last4=aadhaar, pan_number=pan, seat_preference=seat, meal_preference=meal,
                has_passport=bool(passport), has_frequent_flyer=bool(flyers), has_forex_card=bool(forex),
            )
            p.aadhaar_file.save('aadhaar.pdf', pdf('aadhaar.pdf'), save=False)
            p.pan_file.save('pan.pdf', pdf('pan.pdf'), save=False)
            if passport:
                p.passport_number, p.passport_place_of_issue, p.passport_issue_date, p.passport_expiry_date = passport
                p.passport_file.save('passport.pdf', pdf('passport.pdf'), save=False)
            if forex:
                p.forex_bank, p.forex_card_last4 = forex
            p.save()
            for country, visa_type, until in visas:
                visa = Visa(profile=p, country=country, visa_type=visa_type, expiry_date=until)
                visa.file.save('visa.pdf', pdf('visa.pdf'), save=False)
                visa.save()
            FrequentFlyer.objects.bulk_create([FrequentFlyer(profile=p, airline=a, membership_number=n) for a, n in flyers])
            Profile.objects.filter(user=user).update(designation=designation, phone=phone,
                                                     profile_completed_at=timezone.now())

    # ------------------------------------------------------------ trips
    def create_trips(self):
        today = timezone.localdate()
        users = {u.username: u for u in User.objects.all()}
        for trip in SAMPLE_TRIPS:
            employee = users[trip['by']]
            intl = trip['type'] == TravelRequest.TripType.INTERNATIONAL
            legs = [dict(service=s, origin=o, destination=d,
                         origin_country=oc if intl else '', destination_country=dc if intl else '',
                         date=today + timedelta(days=day),
                         end_date=today + timedelta(days=day + nights) if nights else None, is_return=back)
                    for s, o, oc, d, dc, day, nights, back in trip['legs']]
            start, end = trip_dates(legs)
            snapshot = profiles.trip_snapshot(employee, trip['type'], legs, end or start, trip.get('forex_needed', False))
            req = TravelRequest.objects.create(
                employee=employee, approver=services.get_approver(employee), trip_type=trip['type'],
                traveller_is_requester=True, traveller_name=services.display_name(employee),
                traveller_phone=services.profile_of(employee).phone, traveller_email=employee.email,
                traveller_snapshot=snapshot, start_date=start, end_date=end, purpose=trip['purpose'],
                estimated_cost=trip['cost'], submitted_at=timezone.now(),
            )
            save_legs(req, legs)
            services._log(req, employee, 'submit', '')
            services._notify_for('submit', req, employee, '', '')

            for actor, action, comment in trip['steps']:
                if action.startswith('book:'):  # the desk books legs one by one, one ticket each
                    todo = list(req.legs.all())
                    count = len(todo) if action == 'book:all' else int(action.split(':')[1])
                    for leg in todo[:count]:
                        services.perform_action(
                            users[actor], req.pk, 'book_leg', '',
                            data={'leg': leg.pk, 'booking_reference': f'PNR{req.pk:03d}{leg.position}X',
                                  'actual_cost': str(trip['cost'] // len(todo))},
                            files={'ticket': pdf('ticket.pdf')})
                elif action.startswith('assign:'):  # the Travel Manager hands it to an agent
                    services.perform_action(users[actor], req.pk, 'assign', comment,
                                            data={'agent': users[action.split(':')[1]].pk})
                else:
                    services.perform_action(users[actor], req.pk, action, comment)

            if trip.get('overdue'):  # so the "Overdue" card has something to show
                TravelRequest.objects.filter(pk=req.pk).update(submitted_at=timezone.now() - timedelta(hours=60))
        self.stdout.write(f'Created {len(SAMPLE_TRIPS)} sample trips.')
