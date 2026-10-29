"""Security tests. Run with:  python manage.py test desk"""
import os

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import SecurityEvent

User = get_user_model()
DEMO_PASSWORD = 'demo1234'
STRONG = 'Tr4vel-Desk-Strong!'


class SecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with open(os.devnull, 'w') as devnull:
            call_command('seed_demo', force=True, stdout=devnull)
        cls.admin = User.objects.create_superuser('root', 'root@example.com', STRONG)

    def setUp(self):
        cache.clear()  # lockouts and rate limits live in the cache

    def login(self, username, password, client=None):
        client = client or APIClient()
        return client, client.post('/api/auth/login/', {'username': username, 'password': password}, format='json')

    def as_admin(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        return c

    # ------------------------------------------------------------ sign-in
    def test_wrong_password_gives_generic_message(self):
        _, res = self.login('asha', 'nope')
        _, res2 = self.login('no-such-user', 'nope')
        self.assertEqual((res.status_code, res2.status_code), (400, 400))
        self.assertEqual(res.data['detail'], res2.data['detail'])  # no user enumeration

    def test_lockout_after_repeated_failures_even_with_right_password(self):
        for _ in range(5):
            self.login('asha', 'wrong-password')
        _, res = self.login('asha', DEMO_PASSWORD)
        self.assertEqual(res.status_code, 429)
        self.assertIn('Try again', res.data['detail'])
        self.assertTrue(SecurityEvent.objects.filter(type='LOCKED_OUT', username='asha').exists())
        self.assertEqual(SecurityEvent.objects.filter(type='LOGIN_FAILED', username='asha').count(), 5)

        # Admin unlocks -> sign-in works again
        asha = User.objects.get(username='asha')
        self.assertTrue(self.as_admin().get('/api/security/users/?q=asha').data['results'][0]['locked'])
        self.assertEqual(self.as_admin().post(f'/api/security/users/{asha.pk}/unlock/').status_code, 200)
        _, res = self.login('asha', DEMO_PASSWORD)
        self.assertEqual(res.status_code, 200)

    def test_lockout_case_insensitive_and_successful_login_resets_counter(self):
        for _ in range(4):
            self.login('ASHA', 'wrong')
        self.login('asha', DEMO_PASSWORD)  # success clears the counter
        for _ in range(4):
            self.login('asha', 'wrong')
        _, res = self.login('asha', DEMO_PASSWORD)
        self.assertEqual(res.status_code, 200)

    def test_login_rate_limited(self):
        codes = [self.login('nobody', 'x')[1].status_code for _ in range(12)]
        self.assertIn(429, codes)

    def test_deactivated_user_cannot_sign_in(self):
        User.objects.filter(username='ravi').update(is_active=False)
        _, res = self.login('ravi', DEMO_PASSWORD)
        self.assertEqual(res.status_code, 400)

    def test_weak_password_flagged_after_login(self):
        _, res = self.login('asha', DEMO_PASSWORD)
        self.assertTrue(res.data['user']['password_weak'])
        _, res = self.login('root', STRONG)
        self.assertFalse(res.data['user']['password_weak'])
        self.assertTrue(res.data['user']['is_superuser'])

    def test_session_cookie_is_httponly_and_rotates(self):
        client, res = self.login('asha', DEMO_PASSWORD)
        cookie = res.cookies['sessionid']
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        first = cookie.value
        client.post('/api/auth/logout/')
        _, res = self.login('asha', DEMO_PASSWORD, client)
        self.assertNotEqual(res.cookies['sessionid'].value, first)

    def test_expired_session_is_401(self):
        self.assertEqual(APIClient().get('/api/dashboard/').status_code, 401)

    # ------------------------------------------------------------ demo mode
    def test_demo_login_does_not_expose_password(self):
        res = APIClient().get('/api/auth/csrf/')
        self.assertNotIn(DEMO_PASSWORD, str(res.data))
        c = APIClient()
        self.assertEqual(c.post('/api/auth/demo-login/', {'username': 'meera'}, format='json').status_code, 200)
        self.assertEqual(c.post('/api/auth/demo-login/', {'username': 'root'}, format='json').status_code, 400)
        for _ in range(5):
            self.login('ravi', 'wrong')
        self.assertEqual(APIClient().post('/api/auth/demo-login/', {'username': 'ravi'}, format='json').status_code, 429)

    @override_settings(DEMO_MODE=False)
    def test_demo_login_disabled_outside_demo_mode(self):
        res = APIClient().get('/api/auth/csrf/')
        self.assertEqual(res.data['demo_users'], [])
        self.assertEqual(APIClient().post('/api/auth/demo-login/', {'username': 'meera'}, format='json').status_code, 404)

    # ------------------------------------------------------------ password change
    def test_change_password_rules_and_other_sessions_signed_out(self):
        main, _ = self.login('asha', DEMO_PASSWORD)
        other, _ = self.login('asha', DEMO_PASSWORD)  # second device
        url = '/api/auth/change-password/'
        bad = main.post(url, {'current_password': 'x', 'new_password': STRONG, 'confirm_password': STRONG}, format='json')
        self.assertIn('current_password', bad.data)
        weak = main.post(url, {'current_password': DEMO_PASSWORD, 'new_password': '12345678',
                               'confirm_password': '12345678'}, format='json')
        self.assertIn('new_password', weak.data)
        mismatch = main.post(url, {'current_password': DEMO_PASSWORD, 'new_password': STRONG,
                                   'confirm_password': STRONG + 'x'}, format='json')
        self.assertIn('confirm_password', mismatch.data)

        ok = main.post(url, {'current_password': DEMO_PASSWORD, 'new_password': STRONG,
                             'confirm_password': STRONG}, format='json')
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertFalse(ok.data['user']['password_weak'])
        self.assertEqual(main.get('/api/auth/me/').data['user']['username'], 'asha')  # still signed in here
        self.assertIsNone(other.get('/api/auth/me/').data['user'])                    # other device signed out
        self.assertTrue(SecurityEvent.objects.filter(type='PASSWORD_CHANGED', username='asha').exists())

    # ------------------------------------------------------------ security panel
    def test_security_panel_is_superuser_only(self):
        c = APIClient()
        c.force_authenticate(User.objects.get(username='meera'))
        for url in ['/api/security/overview/', '/api/security/events/', '/api/security/users/']:
            self.assertEqual(c.get(url).status_code, 403, url)
            self.assertEqual(APIClient().get(url).status_code, 401, url)
            self.assertEqual(self.as_admin().get(url).status_code, 200, url)
        self.assertTrue(SecurityEvent.objects.filter(type='PERMISSION_DENIED', username='meera').exists())

    def test_admin_changes_role_and_manager_and_it_is_logged(self):
        ravi = User.objects.get(username='ravi')
        director = User.objects.get(username='director')
        res = self.as_admin().patch(f'/api/security/users/{ravi.pk}/',
                                    {'role': 'DESK', 'manager_id': director.pk}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual((res.data['role'], res.data['manager_name']), ('DESK', 'Vikram Rao'))
        event = SecurityEvent.objects.get(type='USER_UPDATED', username='ravi')
        self.assertEqual(event.actor, self.admin)
        self.assertIn('role EMPLOYEE → DESK', event.detail)

    def test_manager_loops_and_self_manager_rejected(self):
        meera = User.objects.get(username='meera')
        asha = User.objects.get(username='asha')  # asha reports to meera
        c = self.as_admin()
        self.assertIn('manager_id', c.patch(f'/api/security/users/{meera.pk}/', {'manager_id': asha.pk}, format='json').data)
        self.assertIn('manager_id', c.patch(f'/api/security/users/{meera.pk}/', {'manager_id': meera.pk}, format='json').data)

    def test_cannot_deactivate_self_or_last_admin(self):
        res = self.as_admin().patch(f'/api/security/users/{self.admin.pk}/', {'is_active': False}, format='json')
        self.assertIn('is_active', res.data)

    def test_deactivating_user_signs_them_out_immediately(self):
        ravi_client, _ = self.login('ravi', DEMO_PASSWORD)
        self.assertEqual(ravi_client.get('/api/dashboard/').status_code, 200)
        ravi = User.objects.get(username='ravi')
        self.as_admin().patch(f'/api/security/users/{ravi.pk}/', {'is_active': False}, format='json')
        self.assertEqual(ravi_client.get('/api/dashboard/').status_code, 401)

    def test_revoke_sessions(self):
        c1, _ = self.login('asha', DEMO_PASSWORD)
        asha = User.objects.get(username='asha')
        res = self.as_admin().post(f'/api/security/users/{asha.pk}/revoke-sessions/')
        self.assertEqual(res.data['ended'], 1)
        self.assertEqual(c1.get('/api/dashboard/').status_code, 401)

    def test_overview_and_event_filters(self):
        self.login('asha', 'wrong')
        self.login('asha', DEMO_PASSWORD)
        c = self.as_admin()
        ov = c.get('/api/security/overview/').data
        self.assertEqual(ov['last_24h']['failed_logins'], 1)
        self.assertEqual(ov['last_24h']['logins'], 1)
        self.assertEqual(c.get('/api/security/events/?type=alerts').data['count'], 1)
        self.assertEqual(c.get('/api/security/events/?q=asha').data['count'], 2)

    # ------------------------------------------------------------ headers
    def test_security_headers(self):
        res = APIClient().get('/api/auth/me/')
        self.assertEqual(res['X-Frame-Options'], 'DENY')
        self.assertEqual(res['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(res['Cache-Control'], 'no-store')
        self.assertIn("default-src 'none'", res['Content-Security-Policy'])
        self.assertEqual(res['Referrer-Policy'], 'same-origin')

    def test_no_public_admin_or_api_root(self):
        self.assertEqual(self.client.get('/admin/').status_code, 404)
        self.assertEqual(self.client.get('/api/').status_code, 404)
