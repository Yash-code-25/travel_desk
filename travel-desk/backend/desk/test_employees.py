"""Employee administration tests. Run with:  python manage.py test desk"""
import os
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Profile, SecurityEvent, TravelRequest

User = get_user_model()
DEMO_PASSWORD = 'demo1234'
STRONG = 'Tr4vel-Desk-Strong!'
URL = '/api/security/users/'


@override_settings(MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}})
class EmployeeAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with open(os.devnull, 'w') as devnull:
            call_command('seed_demo', force=True, stdout=devnull)
        cls.admin = User.objects.create_superuser('root', 'root@example.com', STRONG)

    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def new_employee(self, **extra):
        data = dict(first_name='Kiran', last_name='Desai', email='Kiran.Desai@Example.com', phone='+91 98765 43210',
                    employee_id='emp-101', department='Sales', designation='Sales Executive', role='EMPLOYEE',
                    manager_id=User.objects.get(username='meera').pk)
        data.update(extra)
        return self.api.post(URL, data, format='json')

    def sign_in(self, username, password):
        c = APIClient()
        res = c.post('/api/auth/login/', {'username': username, 'password': password}, format='json')
        return c, res

    # ------------------------------------------------------------ create
    def test_register_employee_sends_login_details_and_forces_password_change(self):
        res = self.new_employee()
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['username'], 'kiran.desai')                # generated from the name
        self.assertEqual((res.data['email'], res.data['employee_id']), ('kiran.desai@example.com', 'EMP-101'))
        self.assertEqual(res.data['manager_name'], 'Meera Shah')
        self.assertTrue(res.data['must_change_password'])
        self.assertTrue(res.data['email_sent'])
        temp = res.data['temporary_password']

        # Email contains the username and temporary password
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('kiran.desai', mail.outbox[0].body)
        self.assertIn(temp, mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ['kiran.desai@example.com'])

        # Password is stored hashed, never in plain text
        user = User.objects.get(username='kiran.desai')
        self.assertNotEqual(user.password, temp)
        self.assertTrue(user.check_password(temp))
        self.assertTrue(SecurityEvent.objects.filter(type='USER_CREATED', username='kiran.desai', actor=self.admin).exists())

        # First sign-in: everything except /api/auth/ is blocked until the password is changed
        c, login = self.sign_in('kiran.desai', temp)
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.data['user']['must_change_password'])
        blocked = c.get('/api/requests/?scope=mine')
        self.assertEqual((blocked.status_code, blocked.json()['code']), (403, 'password_change_required'))
        changed = c.post('/api/auth/change-password/', {'current_password': temp, 'new_password': STRONG,
                                                        'confirm_password': STRONG}, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertFalse(changed.data['user']['must_change_password'])
        self.assertEqual(c.get('/api/requests/?scope=mine').status_code, 200)

    def test_temp_password_meets_policy_and_is_unique(self):
        p1 = self.new_employee().data['temporary_password']
        p2 = self.new_employee(email='other@example.com', employee_id='').data['temporary_password']
        self.assertNotEqual(p1, p2)
        self.assertGreaterEqual(len(p1), 12)
        self.assertTrue(re.search(r'[A-Z]', p1) and re.search(r'[a-z]', p1) and re.search(r'\d', p1))

    def test_duplicate_username_gets_number_suffix(self):
        self.new_employee()
        res = self.new_employee(email='kiran2@example.com', employee_id='EMP-102')
        self.assertEqual(res.data['username'], 'kiran.desai2')

    def test_custom_username_and_admin_role(self):
        res = self.new_employee(username='kdesai', role='MANAGER', is_admin=True)
        self.assertEqual((res.data['username'], res.data['role'], res.data['is_admin']), ('kdesai', 'MANAGER', True))
        self.assertTrue(User.objects.get(username='kdesai').is_staff)

    def test_validation(self):
        bad = self.new_employee(email='asha@example.com', employee_id='', phone='call me', username='x')
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(set(bad.data), {'email', 'phone', 'username'})
        self.new_employee()
        dup = self.new_employee(email='new@example.com')  # same employee ID
        self.assertIn('employee_id', dup.data)
        missing = self.api.post(URL, {'email': 'a@b.com'}, format='json')
        self.assertIn('first_name', missing.data)
        taken = self.new_employee(email='z@example.com', employee_id='', username='Asha')
        self.assertIn('username', taken.data)

    def test_send_email_off_still_returns_password(self):
        res = self.new_employee(send_email=False)
        self.assertFalse(res.data['email_sent'])
        self.assertTrue(res.data['temporary_password'])
        self.assertEqual(len(mail.outbox), 0)

    def test_only_admins_can_register(self):
        c = APIClient()
        c.force_authenticate(User.objects.get(username='meera'))
        self.assertEqual(c.post(URL, {'first_name': 'a'}, format='json').status_code, 403)

    # ------------------------------------------------------------ edit
    def test_edit_details_and_username_is_fixed(self):
        asha = User.objects.get(username='asha')
        res = self.api.patch(f'{URL}{asha.pk}/', {'designation': 'Team Lead', 'phone': '+91 90000 00000',
                                                  'department': 'Enterprise Sales'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual((res.data['designation'], res.data['department']), ('Team Lead', 'Enterprise Sales'))
        res = self.api.patch(f'{URL}{asha.pk}/', {'username': 'asha2'}, format='json')
        self.assertIn('username', res.data)

    def test_cannot_remove_own_admin_or_last_admin(self):
        res = self.api.patch(f'{URL}{self.admin.pk}/', {'is_admin': False}, format='json')
        self.assertIn('is_admin', res.data)

    def test_removing_admin_access_takes_effect(self):
        other = User.objects.create_superuser('admin2', 'a2@example.com', STRONG)
        c, _ = self.sign_in('admin2', STRONG)
        self.assertEqual(c.get('/api/security/overview/').status_code, 200)
        self.api.patch(f'{URL}{other.pk}/', {'is_admin': False}, format='json')
        self.assertEqual(c.get('/api/security/overview/').status_code, 401)  # signed out
        c, _ = self.sign_in('admin2', STRONG)
        self.assertEqual(c.get('/api/security/overview/').status_code, 403)

    def test_role_change_changes_portal_access(self):
        ravi = User.objects.get(username='ravi')
        c, _ = self.sign_in('ravi', DEMO_PASSWORD)
        self.assertEqual(c.get('/api/requests/?scope=desk').status_code, 403)
        self.assertFalse(c.get('/api/auth/me/').data['user']['is_desk'])
        self.api.patch(f'{URL}{ravi.pk}/', {'role': 'DESK'}, format='json')
        self.assertEqual(c.get('/api/requests/?scope=desk').status_code, 200)
        self.assertTrue(c.get('/api/auth/me/').data['user']['is_desk'])

    # ------------------------------------------------------------ reset password
    def test_admin_reset_password(self):
        asha = User.objects.get(username='asha')
        old_session, _ = self.sign_in('asha', DEMO_PASSWORD)
        res = self.api.post(f'{URL}{asha.pk}/reset-password/', {}, format='json')
        temp = res.data['temporary_password']
        self.assertTrue(res.data['email_sent'])
        self.assertIn(temp, mail.outbox[-1].body)
        self.assertEqual(old_session.get('/api/dashboard/').status_code, 401)       # old sessions ended
        self.assertEqual(self.sign_in('asha', DEMO_PASSWORD)[1].status_code, 400)  # old password gone
        c, login = self.sign_in('asha', temp)
        self.assertTrue(login.data['user']['must_change_password'])
        self.assertTrue(SecurityEvent.objects.filter(type='PASSWORD_RESET', username='asha').exists())

    # ------------------------------------------------------------ open work follows people changes
    def _trip(self, username, days=5):
        c = APIClient()
        c.force_authenticate(User.objects.get(username=username))
        res = c.post('/api/requests/', dict(service='FLIGHT', origin='Pune', destination=f'Delhi{days}',
                                            start_date=(timezone.localdate() + timedelta(days=days)).isoformat(),
                                            purpose='Client meeting with Acme'), format='json')
        self.assertEqual(res.status_code, 201, res.data)
        return TravelRequest.objects.get(pk=res.data['id'])

    def test_new_manager_takes_over_pending_requests(self):
        req = self._trip('asha')
        director = User.objects.get(username='director')
        asha = User.objects.get(username='asha')
        res = self.api.patch(f'{URL}{asha.pk}/', {'manager_id': director.pk}, format='json')
        self.assertIn('1 pending request(s) moved to the new manager', res.data['work_notes'])
        req.refresh_from_db()
        self.assertEqual(req.approver, director)
        self.assertTrue(req.events.filter(action='reassign').exists())

    def test_deactivating_manager_escalates_their_approvals(self):
        req = self._trip('asha')  # waiting on meera
        meera = User.objects.get(username='meera')
        res = self.api.patch(f'{URL}{meera.pk}/', {'is_active': False}, format='json')
        self.assertIn('1 approval(s) escalated', res.data['work_notes'])
        req.refresh_from_db()
        self.assertEqual(req.approver.username, 'director')  # meera's own manager

    def test_desk_agent_leaving_desk_releases_bookings(self):
        req = self._trip('asha')
        for user, action in [('meera', 'approve'), ('deepak', 'pick_up')]:
            c = APIClient()
            c.force_authenticate(User.objects.get(username=user))
            c.post(f'/api/requests/{req.pk}/act/', {'action': action})
        deepak = User.objects.get(username='deepak')
        res = self.api.patch(f'{URL}{deepak.pk}/', {'role': 'EMPLOYEE'}, format='json')
        self.assertIn('1 booking(s) returned to the desk queue', res.data['work_notes'])
        req.refresh_from_db()
        self.assertEqual((req.status, req.desk_agent), (TravelRequest.Status.APPROVED, None))

    def test_search_and_role_filter(self):
        self.new_employee()
        self.assertEqual(self.api.get(f'{URL}?q=EMP-101').data['count'], 1)
        self.assertEqual(self.api.get(f'{URL}?status=DESK').data['count'], 2)
        team = {u['username']: u['team_size'] for u in self.api.get(f'{URL}?page_size=50').data['results']}
        self.assertEqual(team['meera'], 3)  # asha, ravi, kiran
