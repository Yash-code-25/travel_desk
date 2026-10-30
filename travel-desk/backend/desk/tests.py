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
from .test_profiles import mark_profiles_complete

User = get_user_model()
S = TravelRequest.Status
TMP_MEDIA = tempfile.mkdtemp()


def day(n):
    return (timezone.localdate() + timedelta(days=n)).isoformat()


def leg(service, origin, destination, date, end_date=None, is_return=False):
    return dict(service=service, origin=origin, destination=destination, date=date,
                end_date=end_date, is_return=is_return)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with open(os.devnull, 'w') as devnull:
            call_command('seed_demo', force=True, stdout=devnull)
        mark_profiles_complete()

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

    def trip(self, service='FLIGHT', origin='Pune', destination='Delhi', start_date=None, end_date='default',
             legs=None, **extra):
        """Shortcut payload. A flight/train/cab with an end_date gets a return leg; a hotel uses it as check-out."""
        start_date = start_date or day(5)
        end_date = day(7) if end_date == 'default' else end_date
        if legs is None:
            if service == 'HOTEL':
                legs = [leg('HOTEL', '', destination, start_date, end_date)]
            else:
                legs = [leg(service, origin, destination, start_date)]
                if end_date:
                    legs.append(leg(service, destination, origin, end_date, is_return=True))
        return {'traveller_is_requester': True, 'legs': legs, 'purpose': 'Client meeting with Acme', **extra}

    def post(self, username='asha', **trip_args):
        return self.as_user(username).post('/api/requests/', self.trip(**trip_args), format='json')

    def create(self, username='asha', **trip_args):
        res = self.post(username, **trip_args)
        self.assertEqual(res.status_code, 201, res.data)
        return res.data['id']

    def leg_errors(self, res):
        """Field names with an error in any leg, e.g. {'date', 'destination'}."""
        return {field for errs in res.data.get('legs', []) if isinstance(errs, dict) for field in errs}

    def act(self, username, pk, action, **extra):
        return self.as_user(username).post(f'/api/requests/{pk}/act/', {'action': action, **extra})

    def assign(self, pk, agent='deepak', manager='anil'):
        """The Travel Manager hands an approved trip to an agent."""
        return self.act(manager, pk, 'assign', agent=User.objects.get(username=agent).pk)

    def leg_ids(self, pk):
        return list(TravelRequest.objects.get(pk=pk).legs.values_list('pk', flat=True))

    def book(self, pk, leg_id, agent='deepak', **extra):
        data = dict(leg=leg_id, booking_reference='PNR123', actual_cost='5000', ticket=self.ticket())
        data.update(extra)
        return self.act(agent, pk, 'book_leg', **data)

    def book_all(self, pk, agent='deepak'):
        for leg_id in self.leg_ids(pk):
            self.assertEqual(self.book(pk, leg_id, agent).status_code, 200)

    def status_of(self, pk):
        return TravelRequest.objects.get(pk=pk).status

    def ticket(self, name='ticket.pdf', content=b'%PDF-1.4 test'):
        return SimpleUploadedFile(name, content, content_type='application/pdf')

    def booked_request(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.assign(pk)
        self.book_all(pk)
        return pk

    # ------------------------------------------------------------ happy path
    def test_full_happy_path(self):
        pk = self.booked_request()
        req = TravelRequest.objects.get(pk=pk)
        self.assertEqual(req.status, S.BOOKED)
        self.assertTrue(req.request_code.startswith('TR-'))
        self.assertEqual([e.action for e in req.events.all()], ['submit', 'approve', 'assign', 'book_leg', 'book'])
        self.assertTrue(Notification.objects.filter(user__username='asha', message__contains='fully booked').exists())
        for leg_id in self.leg_ids(pk):
            self.assertEqual(self.as_user('asha').get(f'/api/requests/{pk}/legs/{leg_id}/ticket/').status_code, 200)

    # ------------------------------------------------------------ traveller
    def test_requester_travelling_fills_traveller_automatically(self):
        res = self.post()
        self.assertEqual((res.data['traveller_name'], res.data['employee_name']), ('Asha Patil', 'Asha Patil'))

    def test_cannot_request_for_someone_else(self):
        # Colleagues raise their own requests (their own profile, passport and visas are used)
        res = self.post(traveller_is_requester=False, traveller_name='Rahul Guest')
        self.assertEqual(res.status_code, 400)
        self.assertIn('traveller_is_requester', res.data)

    def test_same_dates_twice_is_a_duplicate(self):
        self.create()
        dup = self.post()  # Asha again, same dates
        self.assertIn('non_field_errors', dup.data)

    # ------------------------------------------------------------ itinerary
    def test_multi_leg_trip_in_one_request(self):
        legs = [leg('TRAIN', 'Pune', 'Mumbai', day(5)), leg('FLIGHT', 'Mumbai', 'Delhi', day(5)),
                leg('HOTEL', '', 'Delhi', day(5), day(7)), leg('FLIGHT', 'Delhi', 'Pune', day(7), is_return=True)]
        res = self.post(legs=legs)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual([l['position'] for l in res.data['legs']], [1, 2, 3, 4])
        self.assertEqual(res.data['route_summary'], 'Pune → Mumbai → Delhi → Pune · Hotel in Delhi')
        self.assertEqual((res.data['start_date'], res.data['end_date']), (day(5), day(7)))

    def test_legs_must_be_in_date_order(self):
        legs = [leg('FLIGHT', 'Pune', 'Delhi', day(8)), leg('HOTEL', '', 'Delhi', day(6), day(9))]
        res = self.post(legs=legs)
        self.assertEqual(res.status_code, 400)
        self.assertIn('date', res.data['legs'][1])

    def test_return_before_outbound_rejected(self):
        res = self.post(end_date=day(3))  # return leg dated before departure
        self.assertIn('date', res.data['legs'][1])

    def test_return_needs_an_outbound_journey(self):
        legs = [leg('HOTEL', '', 'Delhi', day(5), day(6)), leg('FLIGHT', 'Delhi', 'Pune', day(6), is_return=True)]
        self.assertIn('is_return', self.leg_errors(self.post(legs=legs)))

    def test_one_way_trip_allowed(self):
        res = self.post(end_date=None)
        self.assertEqual((res.status_code, len(res.data['legs']), res.data['end_date']), (201, 1, None))

    def test_at_least_one_and_at_most_ten_legs(self):
        self.assertIn('legs', self.post(legs=[]).data)
        many = [leg('CAB', 'A', 'B', day(5)) for _ in range(11)]
        self.assertIn('legs', self.post(legs=many).data)

    # ------------------------------------------------------------ form validation
    def test_past_date_rejected(self):
        res = self.post(start_date=day(-1), end_date=None)
        self.assertEqual(res.status_code, 400)
        self.assertIn('date', self.leg_errors(res))

    def test_same_origin_and_destination_rejected(self):
        self.assertIn('destination', self.leg_errors(self.post(destination=' pune ', end_date=None)))

    def test_hotel_needs_checkout_after_checkin_and_ignores_origin(self):
        self.assertIn('end_date', self.leg_errors(self.post(service='HOTEL', end_date=None)))
        self.assertIn('end_date', self.leg_errors(self.post(service='HOTEL', end_date=day(5))))
        res = self.post(legs=[leg('HOTEL', 'Pune', 'Delhi', day(5), day(7))])
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['legs'][0]['origin'], '')

    def test_too_far_ahead_and_too_long_rejected(self):
        self.assertIn('date', self.leg_errors(self.post(start_date=day(400), end_date=None)))
        self.assertIn('non_field_errors', self.post(end_date=day(100)).data)

    def test_short_purpose_rejected(self):
        res = self.as_user('asha').post('/api/requests/', {**self.trip(), 'purpose': 'trip'}, format='json')
        self.assertIn('purpose', res.data)

    def test_employee_without_manager_cannot_submit(self):
        res = self.post('newjoiner')
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
        train = {'legs': [leg('TRAIN', 'Pune', 'Delhi', day(5))]}
        # Can't edit while pending
        self.assertEqual(c.put(f'/api/requests/{pk}/', train, format='json').status_code, 409)
        self.act('meera', pk, 'return', comment='Take the train instead')
        self.assertIn('edit', c.get(f'/api/requests/{pk}/').data['allowed_actions'])
        # Others can't edit it
        self.assertEqual(self.as_user('meera').put(f'/api/requests/{pk}/', train, format='json').status_code, 403)
        res = c.put(f'/api/requests/{pk}/', train, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], S.PENDING_APPROVAL)
        self.assertEqual([l['service'] for l in res.data['legs']], ['TRAIN'])

    def test_edit_still_validated(self):
        pk = self.create()
        self.act('meera', pk, 'return', comment='fix')
        res = self.as_user('asha').put(f'/api/requests/{pk}/', {'legs': [leg('FLIGHT', 'Pune', 'Pune', day(5))]},
                                       format='json')
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
        leg_id = self.leg_ids(pk)[0]
        self.assertEqual(self.as_user('ravi').get(f'/api/requests/{pk}/').status_code, 404)
        self.assertEqual(self.as_user('ravi').get('/api/requests/').data['count'], 0)
        self.assertEqual(self.as_user('ravi').get(f'/api/requests/{pk}/legs/{leg_id}/ticket/').status_code, 404)

    def test_approved_trip_goes_to_travel_manager_first(self):
        self.assertEqual(self.as_user('asha').get('/api/requests/?scope=desk').status_code, 403)
        self.assertEqual(self.as_user('deepak').get('/api/requests/?scope=manage').status_code, 403)
        pk = self.create()
        self.act('meera', pk, 'approve')
        # Agents see only what is assigned to them; the Travel Manager sees every approved trip
        self.assertEqual(self.as_user('deepak').get('/api/requests/?scope=desk').data['count'], 0)
        self.assertEqual(self.as_user('deepak').get(f'/api/requests/{pk}/').status_code, 404)
        self.assertEqual(self.as_user('anil').get('/api/requests/?scope=manage').data['count'], 1)
        self.assertTrue(Notification.objects.filter(user__username='anil', message__contains='waiting to be assigned').exists())
        self.assertEqual(self.assign(pk).status_code, 200)
        self.assertEqual(self.as_user('deepak').get('/api/requests/?scope=desk').data['count'], 1)
        self.assertEqual(self.as_user('sara').get('/api/requests/?scope=desk').data['count'], 0)
        # The agent and the employee are told
        self.assertTrue(Notification.objects.filter(user__username='deepak', message__contains='assigned').exists())
        self.assertTrue(Notification.objects.filter(user__username='asha', message__contains='Deepak Nair').exists())

    # ------------------------------------------------------------ travel desk
    def test_only_travel_manager_assigns(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.assertEqual(self.act('deepak', pk, 'pick_up').status_code, 404)  # agents don't even see unassigned trips
        self.assertEqual(self.assign(pk, manager='deepak').status_code, 404)
        self.assertIn('agent', self.act('anil', pk, 'assign', agent=User.objects.get(username='asha').pk).data)
        self.assertEqual(self.assign(pk).status_code, 200)
        self.assertEqual(self.book(pk, self.leg_ids(pk)[0], agent='sara').status_code, 404)  # not hers: can't see it

    def test_travel_manager_reassigns_and_unassigns(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.assign(pk)
        self.assertEqual(self.act('deepak', pk, 'release').status_code, 403)  # agents can't hand it back
        self.assertEqual(self.assign(pk, agent='sara').status_code, 200)
        self.assertEqual(TravelRequest.objects.get(pk=pk).desk_agent.username, 'sara')
        self.assertTrue(Notification.objects.filter(user__username='deepak', message__contains='reassigned').exists())
        self.assertEqual(self.act('anil', pk, 'release').status_code, 200)
        self.assertEqual((self.status_of(pk), TravelRequest.objects.get(pk=pk).desk_agent), (S.APPROVED, None))
        # ...or books it personally
        self.assertEqual(self.act('anil', pk, 'pick_up').status_code, 200)
        self.assertEqual(self.book(pk, self.leg_ids(pk)[0], agent='anil').status_code, 200)

    def test_travel_manager_analytics(self):
        self.assertEqual(self.as_user('deepak').get('/api/desk/analytics/').status_code, 403)
        self.booked_request()
        waiting = self.create(start_date=day(20), end_date=day(22))
        self.act('meera', waiting, 'approve')
        data = self.as_user('anil').get('/api/desk/analytics/').data
        self.assertEqual((data['waiting_assignment'], data['month']['trips_booked']), (1, 1))
        self.assertEqual(data['month']['spend'], 10000)  # 2 legs x 5000
        deepak = next(a for a in data['agents'] if a['name'] == 'Deepak Nair')
        self.assertEqual(deepak['booked_30d'], 1)
        agents = self.as_user('anil').get('/api/desk/agents/').data
        self.assertTrue({'Deepak Nair', 'Sara Khan', 'Anil Mehta'} <= {a['name'] for a in agents})

    def test_employee_cannot_do_desk_work(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.assertEqual(self.act('asha', pk, 'pick_up').status_code, 403)

    def test_each_leg_booked_separately(self):
        pk = self.create()  # outbound + return = 2 legs
        self.act('meera', pk, 'approve')
        self.assign(pk)
        first, second = self.leg_ids(pk)

        self.assertEqual(self.book(pk, first, booking_reference='OUT-1').status_code, 200)
        self.assertEqual(self.status_of(pk), S.IN_PROGRESS)  # one of two booked
        row = self.as_user('deepak').get('/api/requests/?scope=desk').data['results'][0]
        self.assertEqual((row['legs_booked'], row['legs_count']), (1, 2))

        # Uploading again replaces that leg's ticket (e.g. a wrong file)
        self.assertEqual(self.book(pk, first, booking_reference='OUT-2').status_code, 200)
        other_trip = self.create(start_date=day(20), end_date=None)
        self.assertIn('leg', self.book(pk, self.leg_ids(other_trip)[0]).data)  # leg of another trip
        self.assertIn('leg', self.book(pk, '').data)  # no leg chosen

        self.assertEqual(self.book(pk, second, booking_reference='BACK-1').status_code, 200)
        req = TravelRequest.objects.get(pk=pk)
        self.assertEqual(req.status, S.BOOKED)
        self.assertEqual([l.booking_reference for l in req.legs.all()], ['OUT-2', 'BACK-1'])
        self.assertEqual(req.total_actual_cost, 10000)

    def test_booking_validation(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.assign(pk)
        leg_id = self.leg_ids(pk)[0]
        res = self.act('deepak', pk, 'book_leg', leg=leg_id)
        self.assertEqual(set(res.data), {'booking_reference', 'actual_cost', 'ticket'})
        self.assertIn('actual_cost', self.book(pk, leg_id, actual_cost='-5').data)
        self.assertIn('ticket', self.book(pk, leg_id, ticket=self.ticket('virus.exe')).data)
        big = SimpleUploadedFile('big.pdf', b'0' * (5 * 1024 * 1024 + 1))
        self.assertIn('ticket', self.book(pk, leg_id, ticket=big).data)
        self.assertEqual(self.status_of(pk), S.IN_PROGRESS)

    def test_unavailable_returns_to_employee_and_needs_reapproval(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.assign(pk)
        self.assertEqual(self.act('deepak', pk, 'unavailable').status_code, 400)  # reason needed
        self.assertEqual(self.act('deepak', pk, 'unavailable', comment='Flights full').status_code, 200)
        self.assertEqual(self.status_of(pk), S.RETURNED)
        self.assertIsNone(TravelRequest.objects.get(pk=pk).desk_agent)
        self.act('asha', pk, 'resubmit')
        self.assertEqual(self.status_of(pk), S.PENDING_APPROVAL)

    def test_cost_overrun_alerts_approver(self):
        pk = self.create(estimated_cost='1000')
        self.act('meera', pk, 'approve')
        self.assign(pk)
        for leg_id in self.leg_ids(pk):
            self.book(pk, leg_id, actual_cost='750')  # 2 x 750 = 1500 vs 1000 estimate
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
        self.assertEqual(self.act('sara', pk, 'confirm_cancel').status_code, 404)  # not her booking
        self.assertEqual(self.act('anil', pk, 'confirm_cancel').status_code, 403)  # the agent who booked handles it
        self.assertEqual(self.act('deepak', pk, 'confirm_cancel').status_code, 200)
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
    def separate_trips(self, cities, username='asha'):
        """Trips on different dates (the same traveller can't have overlapping trips)."""
        return [self.create(username, destination=c, start_date=day(5 + 3 * i), end_date=None)
                for i, c in enumerate(cities)]

    def test_search_status_filter_and_pagination(self):
        _, _, chennai = self.separate_trips(['Delhi', 'Mumbai', 'Chennai'])
        self.act('meera', chennai, 'approve')
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
        a, _ = self.separate_trips(['Delhi', 'Mumbai'])
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

        self.separate_trips(['Delhi', 'Goa'])
        few = count_queries()
        self.separate_trips(['Agra', 'Jaipur', 'Surat', 'Indore', 'Nagpur', 'Kochi'], username='ravi')
        self.assertEqual(count_queries(), few)  # no N+1: 8 rows cost the same as 2
        # ~9 data queries + a few fixed cache queries (rate limiting lives in the DB cache).
        self.assertLessEqual(few, 16)

    def test_fake_ticket_file_rejected_and_logged(self):
        pk = self.create()
        self.act('meera', pk, 'approve')
        self.assign(pk)
        fake = SimpleUploadedFile('ticket.pdf', b'MZ\x90\x00 this is really an exe')
        res = self.book(pk, self.leg_ids(pk)[0], ticket=fake)
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
