"""Run with:  python manage.py test desk"""
import os
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Notification, SecurityEvent, TravelRequest

User = get_user_model()
S = TravelRequest.Status
TMP_MEDIA = tempfile.mkdtemp()


def day(n):
    return (timezone.localdate() + timedelta(days=n)).isoformat()


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with open(os.devnull, 'w') as devnull:
            call_command('seed_demo', force=True, stdout=devnull)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()  # auto-close is throttled through the cache

    # ------------------------------------------------------------ helpers
    def as_user(self, username):
        client = APIClient()
        client.force_authenticate(User.objects.get(username=username))
        return client

    def flight(self, **overrides):
        data = dict(service='FLIGHT', origin='Pune', destination='Delhi',
                    start_date=day(5), end_date=day(7), purpose='Client meeting with Acme')
        data.update(overrides)
        return data

    def create(self, username='asha', **overrides):
        res = self.as_user(username).post('/api/requests/', self.flight(**overrides), format='json')
        self.assertEqual(res.status_code, 201, res.data)
        return res.data['id']

    def act(self, username, pk, action, **extra):
        return self.as_user(username).post(f'/api/requests/{pk}/act/', {'action': action, **extra})

    def status_of(self, pk):
        return TravelRequest.objects.get(pk=pk).status

    def ticket(self, name='ticket.pdf', content=b'%PDF-1.4 test'):
        return SimpleUploadedFile(name, content, content_type='application/pdf')

    def booked_request(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.act('deepak', pk, 'pick_up')
        res = self.act('deepak', pk, 'book', booking_reference='PNR123', actual_cost='5000',
                       ticket=self.ticket())
        self.assertEqual(res.status_code, 200, res.data)
        return pk

    # ------------------------------------------------------------ happy path
    def test_full_happy_path(self):
        pk = self.booked_request()
        req = TravelRequest.objects.get(pk=pk)
        self.assertEqual(req.status, S.BOOKED)
        self.assertTrue(req.request_code.startswith('TR-'))
        self.assertEqual([e.action for e in req.events.all()], ['submit', 'approve', 'pick_up', 'book'])
        self.assertTrue(Notification.objects.filter(user__username='asha', message__contains='booked').exists())

        res = self.as_user('asha').get(f'/api/requests/{pk}/ticket/')
        self.assertEqual(res.status_code, 200)

    # ------------------------------------------------------------ form validation
    def test_past_date_rejected(self):
        res = self.as_user('asha').post('/api/requests/', self.flight(start_date=day(-1), end_date=None), format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('start_date', res.data)

    def test_same_origin_and_destination_rejected(self):
        res = self.as_user('asha').post('/api/requests/', self.flight(destination=' pune '), format='json')
        self.assertIn('destination', res.data)

    def test_return_before_departure_rejected(self):
        res = self.as_user('asha').post('/api/requests/', self.flight(end_date=day(3)), format='json')
        self.assertIn('end_date', res.data)

    def test_hotel_needs_checkout_after_checkin_and_ignores_origin(self):
        c = self.as_user('asha')
        res = c.post('/api/requests/', self.flight(service='HOTEL', end_date=None), format='json')
        self.assertIn('end_date', res.data)
        res = c.post('/api/requests/', self.flight(service='HOTEL', end_date=day(5)), format='json')
        self.assertIn('end_date', res.data)
        res = c.post('/api/requests/', self.flight(service='HOTEL', origin=''), format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['origin'], '')

    def test_too_far_ahead_and_too_long_rejected(self):
        c = self.as_user('asha')
        self.assertIn('start_date', c.post('/api/requests/', self.flight(start_date=day(400), end_date=None), format='json').data)
        self.assertIn('end_date', c.post('/api/requests/', self.flight(end_date=day(100)), format='json').data)

    def test_short_purpose_rejected(self):
        res = self.as_user('asha').post('/api/requests/', self.flight(purpose='trip'), format='json')
        self.assertIn('purpose', res.data)

    def test_duplicate_overlapping_request_rejected(self):
        self.create()
        res = self.as_user('asha').post('/api/requests/', self.flight(start_date=day(6), end_date=day(8)), format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('non_field_errors', res.data)
        # A different destination is fine
        self.create(destination='Mumbai')

    def test_employee_without_manager_cannot_submit(self):
        res = self.as_user('newjoiner').post('/api/requests/', self.flight(), format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('manager', str(res.data))

    def test_login_required(self):
        self.assertEqual(APIClient().get('/api/requests/').status_code, 401)

    # ------------------------------------------------------------ approvals
    def test_only_assigned_manager_can_approve(self):
        pk = self.create()
        self.assertEqual(self.act('director', pk, 'approve').status_code, 404)  # can't even see it
        self.assertEqual(self.act('ravi', pk, 'approve').status_code, 404)
        self.assertEqual(self.act('asha', pk, 'approve').status_code, 403)    # own request
        self.assertEqual(self.act('meera', pk, 'approve').status_code, 200)

    def test_manager_own_request_goes_to_their_manager(self):
        pk = self.create('meera')
        self.assertEqual(TravelRequest.objects.get(pk=pk).approver.username, 'director')
        self.assertEqual(self.act('meera', pk, 'approve').status_code, 403)
        self.assertEqual(self.act('director', pk, 'approve').status_code, 200)

    def test_double_approve_is_conflict(self):
        pk = self.create()
        self.assertEqual(self.act('meera', pk, 'approve').status_code, 200)
        self.assertEqual(self.act('meera', pk, 'approve').status_code, 409)
        self.assertEqual(self.act('meera', pk, 'reject', comment='x').status_code, 409)

    def test_reject_and_return_need_a_reason(self):
        pk = self.create()
        self.assertEqual(self.act('meera', pk, 'reject').status_code, 400)
        self.assertEqual(self.act('meera', pk, 'return', comment='  ').status_code, 400)
        self.assertEqual(self.act('meera', pk, 'reject', comment='No budget').status_code, 200)
        self.assertEqual(self.status_of(pk), S.REJECTED)
        self.assertEqual(self.act('asha', pk, 'cancel').status_code, 409)  # final state

    def test_return_edit_resubmit_cycle(self):
        pk = self.create()
        c = self.as_user('asha')
        # Can't edit while pending
        self.assertEqual(c.put(f'/api/requests/{pk}/', {'destination': 'Goa'}, format='json').status_code, 409)
        self.act('meera', pk, 'return', comment='Take the train instead')
        self.assertIn('edit', c.get(f'/api/requests/{pk}/').data['allowed_actions'])
        # Others can't edit it
        self.assertEqual(self.as_user('meera').put(f'/api/requests/{pk}/', {'service': 'TRAIN'}, format='json').status_code, 403)
        res = c.put(f'/api/requests/{pk}/', {'service': 'TRAIN'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], S.PENDING_APPROVAL)
        self.assertEqual(res.data['service'], 'TRAIN')

    def test_edit_still_validated(self):
        pk = self.create()
        self.act('meera', pk, 'return', comment='fix')
        res = self.as_user('asha').put(f'/api/requests/{pk}/', {'destination': 'Pune'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.status_of(pk), S.RETURNED)

    def test_approve_after_travel_date_passed_blocked_and_auto_expired(self):
        pk = self.create()
        TravelRequest.objects.filter(pk=pk).update(start_date=timezone.localdate() - timedelta(days=1))
        res = self.act('meera', pk, 'approve')
        self.assertIn(res.status_code, (400, 409))
        self.assertEqual(self.status_of(pk), S.EXPIRED)

    def test_overdue_flag(self):
        pk = self.create()
        TravelRequest.objects.filter(pk=pk).update(submitted_at=timezone.now() - timedelta(hours=72))
        self.assertTrue(self.as_user('meera').get(f'/api/requests/{pk}/').data['is_overdue'])

    def test_manager_changed_resubmit_goes_to_new_manager(self):
        pk = self.create()
        self.act('meera', pk, 'return', comment='fix')
        asha = User.objects.get(username='asha')
        asha.profile.manager = User.objects.get(username='director')
        asha.profile.save()
        self.assertEqual(self.act('asha', pk, 'resubmit').status_code, 200)
        self.assertEqual(TravelRequest.objects.get(pk=pk).approver.username, 'director')

    # ------------------------------------------------------------ visibility
    def test_employees_only_see_their_own(self):
        pk = self.create()
        self.assertEqual(self.as_user('ravi').get(f'/api/requests/{pk}/').status_code, 404)
        self.assertEqual(self.as_user('ravi').get('/api/requests/').data['count'], 0)
        self.assertEqual(self.as_user('ravi').get(f'/api/requests/{pk}/ticket/').status_code, 404)

    def test_desk_queue_only_for_desk(self):
        self.assertEqual(self.as_user('asha').get('/api/requests/?scope=desk').status_code, 403)
        pk = self.create()
        self.assertEqual(self.as_user('deepak').get('/api/requests/?scope=desk').data['count'], 0)  # not approved
        self.act('meera', pk, 'approve')
        self.assertEqual(self.as_user('deepak').get('/api/requests/?scope=desk').data['count'], 1)

    # ------------------------------------------------------------ travel desk
    def test_two_agents_cannot_pick_same_request(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.assertEqual(self.act('deepak', pk, 'pick_up').status_code, 200)
        self.assertEqual(self.act('sara', pk, 'pick_up').status_code, 409)
        self.assertEqual(self.act('sara', pk, 'book', booking_reference='X', actual_cost='1',
                                  ticket=self.ticket()).status_code, 403)

    def test_release_puts_back_in_queue(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.act('deepak', pk, 'pick_up')
        self.assertEqual(self.act('deepak', pk, 'release').status_code, 200)
        self.assertEqual(self.status_of(pk), S.APPROVED)
        self.assertEqual(self.act('sara', pk, 'pick_up').status_code, 200)

    def test_employee_cannot_do_desk_work(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.assertEqual(self.act('asha', pk, 'pick_up').status_code, 403)

    def test_booking_validation(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.act('deepak', pk, 'pick_up')
        res = self.act('deepak', pk, 'book')
        self.assertEqual(set(res.data), {'booking_reference', 'actual_cost', 'ticket'})
        res = self.act('deepak', pk, 'book', booking_reference='P', actual_cost='-5', ticket=self.ticket())
        self.assertIn('actual_cost', res.data)
        res = self.act('deepak', pk, 'book', booking_reference='P', actual_cost='5',
                       ticket=self.ticket('virus.exe'))
        self.assertIn('ticket', res.data)
        big = SimpleUploadedFile('big.pdf', b'0' * (5 * 1024 * 1024 + 1))
        res = self.act('deepak', pk, 'book', booking_reference='P', actual_cost='5', ticket=big)
        self.assertIn('ticket', res.data)
        self.assertEqual(self.status_of(pk), S.IN_PROGRESS)

    def test_unavailable_returns_to_employee_and_needs_reapproval(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.act('deepak', pk, 'pick_up')
        self.assertEqual(self.act('deepak', pk, 'unavailable').status_code, 400)  # reason needed
        self.assertEqual(self.act('deepak', pk, 'unavailable', comment='Flights full').status_code, 200)
        self.assertEqual(self.status_of(pk), S.RETURNED)
        self.assertIsNone(TravelRequest.objects.get(pk=pk).desk_agent)
        self.act('asha', pk, 'resubmit')
        self.assertEqual(self.status_of(pk), S.PENDING_APPROVAL)

    def test_cost_overrun_alerts_approver(self):
        pk = self.create(estimated_cost='1000')
        self.act('meera', pk, 'approve')
        self.act('deepak', pk, 'pick_up')
        self.act('deepak', pk, 'book', booking_reference='P', actual_cost='1500', ticket=self.ticket())
        self.assertTrue(Notification.objects.filter(user__username='meera', message__contains='above the estimate').exists())

    # ------------------------------------------------------------ cancellation
    def test_cancel_before_booking(self):
        pk = self.create()
        self.assertEqual(self.act('meera', pk, 'cancel').status_code, 403)  # only owner
        self.assertEqual(self.act('asha', pk, 'cancel').status_code, 200)
        self.assertEqual(self.status_of(pk), S.CANCELLED)
        # Cancelled requests free up the dates
        self.create()

    def test_cancel_after_booking_needs_desk(self):
        pk = self.booked_request()
        self.assertEqual(self.act('asha', pk, 'cancel').status_code, 409)
        self.assertEqual(self.act('asha', pk, 'request_cancel', comment='Meeting moved').status_code, 200)
        self.assertEqual(self.act('deepak', pk, 'decline_cancel', comment='Non-refundable').status_code, 200)
        self.assertEqual(self.status_of(pk), S.BOOKED)
        self.act('asha', pk, 'request_cancel', comment='Please try again')
        self.assertEqual(self.act('sara', pk, 'confirm_cancel').status_code, 200)
        self.assertEqual(self.status_of(pk), S.CANCELLED)

    # ------------------------------------------------------------ time rules
    def test_complete_rules(self):
        pk = self.booked_request()
        self.assertEqual(self.act('deepak', pk, 'complete').status_code, 400)  # trip not started
        TravelRequest.objects.filter(pk=pk).update(
            start_date=timezone.localdate() - timedelta(days=3), end_date=timezone.localdate() - timedelta(days=1))
        cache.clear()  # pretend the 60-second throttle window has passed
        self.as_user('asha').get('/api/requests/')  # triggers auto-close
        self.assertEqual(self.status_of(pk), S.COMPLETED)

    def test_unknown_action(self):
        pk = self.create()
        self.assertEqual(self.act('meera', pk, 'teleport').status_code, 400)

    def test_requests_cannot_be_deleted(self):
        pk = self.create()
        self.assertEqual(self.as_user('asha').delete(f'/api/requests/{pk}/').status_code, 405)

    # ------------------------------------------------------------ list, search, dashboard, speed
    def test_search_status_filter_and_pagination(self):
        self.create(destination='Delhi')
        self.create(destination='Mumbai')
        mumbai_id = self.create(destination='Chennai')
        self.act('meera', mumbai_id, 'approve')
        c = self.as_user('meera')
        self.assertEqual(c.get('/api/requests/?scope=approvals&q=mum').data['count'], 1)
        self.assertEqual(c.get('/api/requests/?scope=approvals&q=asha').data['count'], 3)
        self.assertEqual(c.get('/api/requests/?scope=approvals&status=PENDING_APPROVAL').data['count'], 2)
        self.assertEqual(c.get('/api/requests/?scope=approvals&status=APPROVED,REJECTED').data['count'], 1)
        page = c.get('/api/requests/?scope=approvals&page_size=2').data
        self.assertEqual((page['count'], len(page['results'])), (3, 2))
        self.assertIsNotNone(page['next'])
        self.assertNotIn('events', page['results'][0])  # list payload stays small
        flags = {r['status']: r['needs_action']
                 for r in c.get('/api/requests/?scope=approvals').data['results']}
        self.assertEqual(flags, {'PENDING_APPROVAL': True, 'APPROVED': False})

    def test_overdue_filter_and_dashboard_counts(self):
        a = self.create(destination='Delhi')
        self.create(destination='Mumbai')
        TravelRequest.objects.filter(pk=a).update(submitted_at=timezone.now() - timedelta(hours=72))
        c = self.as_user('meera')
        self.assertEqual(c.get('/api/requests/?scope=approvals&overdue=1').data['count'], 1)
        dash = c.get('/api/dashboard/?scope=approvals').data
        self.assertEqual(dash, {'by_status': {'PENDING_APPROVAL': 2}, 'total': 2, 'overdue': 1})
        self.assertEqual(self.as_user('asha').get('/api/dashboard/?scope=desk').status_code, 403)

    def test_list_query_count_does_not_grow_with_rows(self):
        def count_queries():
            cache.set('desk:auto_close', True)  # measure the list itself, not the auto-close job
            client = self.as_user('meera')
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(client.get('/api/requests/?scope=approvals').status_code, 200)
            return len(ctx)

        for city in ['Delhi', 'Goa']:
            self.create(destination=city)
        few = count_queries()
        for city in ['Agra', 'Jaipur', 'Surat', 'Indore', 'Nagpur', 'Kochi']:
            self.create(destination=city)
        self.assertEqual(count_queries(), few)  # no N+1: 8 rows cost the same as 2
        # ~8 data queries + a few fixed cache queries (rate limiting lives in the DB cache).
        self.assertLessEqual(few, 15)

    def test_fake_ticket_file_rejected_and_logged(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.act('deepak', pk, 'pick_up')
        fake = SimpleUploadedFile('ticket.pdf', b'MZ\x90\x00 this is really an exe')
        res = self.act('deepak', pk, 'book', booking_reference='P', actual_cost='5', ticket=fake)
        self.assertEqual(res.status_code, 400)
        self.assertIn('not a real', str(res.data['ticket']))
        self.assertTrue(SecurityEvent.objects.filter(type='UPLOAD_REJECTED', username='deepak').exists())

    def test_comment_length_capped(self):
        pk = self.create()
        self.assertEqual(self.act('meera', pk, 'reject', comment='x' * 1001).status_code, 400)

    def test_auto_close_is_throttled(self):
        self.as_user('asha').get('/api/requests/')  # runs once and sets the throttle
        with CaptureQueriesContext(connection) as ctx:
            self.as_user('asha').get('/api/dashboard/')
        self.assertFalse(any('FOR UPDATE' in q['sql'] or '"status" IN' in q['sql'] and 'UPDATE' in q['sql']
                             for q in ctx.captured_queries))
