"""Travel profile tests. Run with:  python manage.py test desk"""
import json
import os
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Profile, TravelProfile, TravelRequest

User = get_user_model()
TMP_MEDIA = tempfile.mkdtemp()


def mark_profiles_complete():
    """Other test suites test the workflow, not the profile form: let every existing user through."""
    for user in User.objects.filter(profile__isnull=True):
        Profile.objects.create(user=user)
    Profile.objects.update(profile_completed_at=timezone.now())


def day(n):
    return (timezone.localdate() + timedelta(days=n)).isoformat()


def pdf(name='doc.pdf'):
    return SimpleUploadedFile(name, b'%PDF-1.4 test', content_type='application/pdf')


def details(**extra):
    data = dict(
        first_name='Asha', last_name='Patil', phone='+91 98765 43210', designation='Sales Executive',
        department='Sales', date_of_birth='1994-05-12', gender='FEMALE', address='12 MG Road, Pune 411001',
        emergency_contact_name='Ravi Patil', emergency_contact_phone='+91 91234 56789',
        aadhaar_last4='1234', pan_number='abcde1234f', has_passport=True, passport_number='z1234567',
        passport_place_of_issue='Pune', passport_issue_date=day(-400), passport_expiry_date=day(3000),
        visas=[{'country': 'United States', 'visa_type': 'B1/B2', 'expiry_date': day(500)}],
        seat_preference='WINDOW', meal_preference='VEG',
        has_frequent_flyer=True, frequent_flyers=[{'airline': 'Air India', 'membership_number': 'ai-998877'}],
        has_forex_card=True, forex_bank='HDFC Bank', forex_card_last4='4321',
    )
    data.update(extra)
    return data


def all_files():
    return {'aadhaar_file': pdf(), 'pan_file': pdf(), 'passport_file': pdf(), 'visa_file_0': pdf()}


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class ProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with open(os.devnull, 'w') as devnull:
            call_command('seed_demo', force=True, stdout=devnull)
        cls.admin = User.objects.create_superuser('root', 'root@example.com', 'Tr4vel-Desk-Strong!')

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()

    def client_for(self, username):
        client = APIClient()
        client.force_login(User.objects.get(username=username))  # a real session, so the middleware sees it
        return client

    def save(self, username='asha', files=None, **extra):
        body = {'data': json.dumps(details(**extra)), **(all_files() if files is None else files)}
        return self.client_for(username).put('/api/profile/', body, format='multipart')

    def test_app_is_blocked_until_profile_is_filled(self):
        client = self.client_for('asha')
        self.assertFalse(client.get('/api/auth/me/').data['user']['profile_complete'])
        res = client.get('/api/requests/')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()['code'], 'profile_required')
        self.assertEqual(client.get('/api/profile/').status_code, 200)

        self.assertEqual(self.save().status_code, 200)
        self.assertTrue(client.get('/api/auth/me/').data['user']['profile_complete'])
        self.assertEqual(client.get('/api/requests/').status_code, 200)

    def test_saved_profile(self):
        res = self.save()
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['pan_number'], 'ABCDE1234F')
        self.assertEqual(res.data['passport_number'], 'Z1234567')
        self.assertEqual(res.data['frequent_flyers'][0]['membership_number'], 'AI-998877')
        self.assertEqual(len(res.data['visas']), 1)
        self.assertTrue(res.data['aadhaar_file'] and res.data['visas'][0]['file'])
        p = TravelProfile.objects.get(user__username='asha')
        self.assertFalse(p.aadhaar_file.name.endswith('doc.pdf'))  # original file name is not kept
        self.assertEqual(Profile.objects.get(user=p.user).designation, 'Sales Executive')

    def test_documents_required(self):
        res = self.save(files={})
        self.assertEqual(res.status_code, 400)
        self.assertTrue({'aadhaar_file', 'pan_file', 'passport_file', 'visas'} <= set(res.data))

    def test_field_checks(self):
        res = self.save(pan_number='12345', aadhaar_last4='12', date_of_birth=day(-365))
        self.assertEqual(res.status_code, 400)
        self.assertTrue({'pan_number', 'aadhaar_last4', 'date_of_birth'} <= set(res.data))
        # Sections switched on must be filled in
        res = self.save(passport_expiry_date=day(-1), forex_card_last4='', frequent_flyers=[])
        self.assertEqual(res.status_code, 400)
        self.assertTrue({'passport_expiry_date', 'forex_card_last4', 'frequent_flyers'} <= set(res.data))

    def test_optional_sections_can_be_left_out(self):
        res = self.save(has_passport=False, visas=[], has_frequent_flyer=False, has_forex_card=False,
                        files={'aadhaar_file': pdf(), 'pan_file': pdf()})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['passport_number'], '')
        self.assertEqual(res.data['frequent_flyers'], [])

    def test_edit_keeps_documents_and_removes_dropped_visa(self):
        self.save()
        p = TravelProfile.objects.get(user__username='asha')
        pan_name, visa_file = p.pan_file.name, p.visas.get().file.name
        with self.captureOnCommitCallbacks(execute=True):  # old files are removed after the commit
            res = self.save(files={}, visas=[], seat_preference='AISLE')
        self.assertEqual(res.status_code, 200, res.data)
        p.refresh_from_db()
        self.assertEqual(p.pan_file.name, pan_name)
        self.assertEqual(p.seat_preference, 'AISLE')
        self.assertFalse(p.visas.exists())
        self.assertFalse(os.path.exists(os.path.join(TMP_MEDIA, visa_file)))

    def test_fake_document_rejected(self):
        files = all_files()
        files['pan_file'] = SimpleUploadedFile('pan.pdf', b'MZ\x90\x00 really an exe')
        res = self.save(files=files)
        self.assertEqual(res.status_code, 400)
        self.assertIn('pan_file', res.data)

    def trip_for_asha(self):
        res = self.client_for('asha').post('/api/requests/', {
            'legs': [{'service': 'FLIGHT', 'origin': 'Pune', 'destination': 'Delhi', 'date': day(5)}],
            'purpose': 'Client meeting with Acme'}, format='json')
        return res.data['id']

    def test_who_can_see_a_profile(self):
        self.save()
        mark_profiles_complete()
        asha = User.objects.get(username='asha')
        url = f'/api/profiles/{asha.pk}/'
        self.assertEqual(self.client_for('asha').get(url).status_code, 200)    # owner
        self.assertEqual(self.client_for('anil').get(url).status_code, 200)    # Travel Manager
        self.assertEqual(self.client_for('deepak').get(url).status_code, 403)  # agent, not booking her trip...
        TravelRequest.objects.filter(pk=self.trip_for_asha()).update(desk_agent=User.objects.get(username='deepak'))
        self.assertEqual(self.client_for('deepak').get(url).status_code, 200)  # ...until assigned one
        self.assertEqual(self.client_for('root').get(url).status_code, 200)    # administrator
        self.assertEqual(self.client_for('meera').get(url).status_code, 403)   # her manager: no
        self.assertEqual(self.client_for('ravi').get(url).status_code, 403)    # colleague: no

        doc = f'/api/profiles/{asha.pk}/files/pan/'
        self.assertEqual(self.client_for('deepak').get(doc).status_code, 200)
        self.assertEqual(self.client_for('meera').get(doc).status_code, 403)
        self.assertEqual(self.client_for('deepak').get(f'/api/profiles/{asha.pk}/files/nope/').status_code, 404)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class InternationalTripTests(TestCase):
    """Domestic / international requests and what they take from the traveller's profile."""

    @classmethod
    def setUpTestData(cls):
        with open(os.devnull, 'w') as devnull:
            call_command('seed_demo', force=True, stdout=devnull)
        mark_profiles_complete()

    def setUp(self):
        cache.clear()

    def client_for(self, username):
        client = APIClient()
        client.force_login(User.objects.get(username=username))
        return client

    def give_profile(self, **extra):
        body = {'data': json.dumps(details(**extra)), **all_files()}
        res = self.client_for('asha').put('/api/profile/', body, format='multipart')
        self.assertEqual(res.status_code, 200, res.data)

    def trip(self, trip_type='INTERNATIONAL', legs=None, **extra):
        legs = legs or [
            dict(service='FLIGHT', origin='Mumbai', origin_country='India', destination='New York',
                 destination_country='United States', date=day(10)),
            dict(service='HOTEL', destination='New York', destination_country='United States', date=day(11), end_date=day(14)),
            dict(service='FLIGHT', origin='New York', origin_country='United States', destination='Mumbai',
                 destination_country='India', date=day(14), is_return=True),
        ]
        body = dict(trip_type=trip_type, legs=legs, purpose='Client meeting with Acme', **extra)
        return self.client_for('asha').post('/api/requests/', body, format='json')

    def test_international_trip_copies_passport_and_visa_from_profile(self):
        self.give_profile()
        with self.captureOnCommitCallbacks(execute=True):
            res = self.trip()
        self.assertEqual(res.status_code, 201, res.data)
        snap = res.data['traveller_snapshot']
        self.assertEqual(snap['passport']['number'], 'Z1234567')
        self.assertEqual(snap['visas'][0]['country'], 'United States')
        self.assertEqual(snap['visa_needed'], [])
        self.assertEqual(snap['forex']['card_last4'], '4321')
        self.assertEqual((snap['seat'], snap['meal']), ('Window', 'Vegetarian'))
        self.assertEqual(res.data['trip_type_label'], 'International')

    def test_missing_visa_is_flagged_not_blocked(self):
        self.give_profile(visas=[], has_forex_card=False)
        legs = [dict(service='FLIGHT', origin='Mumbai', origin_country='India', destination='Dubai',
                     destination_country='United Arab Emirates', date=day(10))]
        res = self.trip(legs=legs, forex_needed=True)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['traveller_snapshot']['visa_needed'], ['United Arab Emirates'])
        self.assertTrue(res.data['traveller_snapshot']['forex_needed'])

    def test_passport_rules(self):
        self.give_profile(has_passport=False, visas=[])
        self.assertIn('passport', str(self.trip().data['non_field_errors']).lower())
        self.give_profile(passport_expiry_date=day(60))  # expires within 6 months of the trip
        self.assertIn('6 months', str(self.trip().data['non_field_errors']))

    def test_international_leg_rules(self):
        self.give_profile()
        legs = [dict(service='TRAIN', origin='Paris', origin_country='France', destination='Lyon',
                     destination_country='Narnia', date=day(10))]
        errs = self.trip(legs=legs).data['legs'][0]
        self.assertTrue({'service', 'destination_country'} <= set(errs))
        india_only = [dict(service='FLIGHT', origin='Pune', origin_country='India', destination='Delhi',
                           destination_country='India', date=day(10))]
        self.assertIn('non_field_errors', self.trip(legs=india_only).data)

    def test_domestic_trip_needs_no_passport_and_ignores_countries(self):
        legs = [dict(service='TRAIN', origin='Pune', destination='Mumbai', destination_country='France', date=day(10))]
        res = self.trip('DOMESTIC', legs=legs)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['legs'][0]['destination_country'], '')
        self.assertNotIn('passport', res.data['traveller_snapshot'])

    def test_manager_does_not_see_personal_documents(self):
        self.give_profile()
        pk = self.trip().data['id']
        meera = self.client_for('meera')
        self.assertEqual(meera.get(f'/api/requests/{pk}/').data['traveller_snapshot'], {})
        meera.post(f'/api/requests/{pk}/act/', {'action': 'approve'})  # now with the Travel Manager
        self.assertIn('passport', self.client_for('anil').get(f'/api/requests/{pk}/').data['traveller_snapshot'])
