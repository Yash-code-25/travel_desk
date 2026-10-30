import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import security, services
from .models import RequestEvent, SecurityEvent, TravelRequest, TripLeg
from .serializers import TravelRequestListSerializer, TravelRequestSerializer

User = get_user_model()

S = TravelRequest.Status
DESK_STATUSES = [S.APPROVED, S.IN_PROGRESS, S.BOOKED, S.CANCELLATION_REQUESTED, S.COMPLETED, S.CANCELLED]
ORDERINGS = {'newest': '-created_at', 'oldest': 'created_at', 'travel': 'start_date', '-travel': '-start_date'}


def scoped_queryset(user, scope):
    """Which requests a user may see on each page. Shared by the list and the dashboard."""
    qs = TravelRequest.objects.all()
    if scope == 'mine':
        return qs.filter(employee=user)
    if scope == 'approvals':
        return qs.filter(approver=user).exclude(employee=user)
    if scope == 'desk':  # trips assigned to me (agents see nothing else)
        if not services.is_desk(user):
            raise PermissionDenied('Only the Travel Desk can see the desk queue.')
        return qs.filter(desk_agent=user, status__in=DESK_STATUSES)
    if scope == 'manage':  # every approved trip: assign, reassign, follow up
        if not services.is_travel_manager(user):
            raise PermissionDenied('Only Travel Managers can see this.')
        return qs.filter(status__in=DESK_STATUSES)
    visible = Q(employee=user) | Q(approver=user)
    if services.is_travel_manager(user):
        visible |= Q(status__in=DESK_STATUSES)
    elif services.is_desk(user):
        visible |= Q(desk_agent=user, status__in=DESK_STATUSES)
    return qs.filter(visible)


def overdue_q():
    return Q(status=S.PENDING_APPROVAL,
             submitted_at__lt=timezone.now() - timedelta(hours=settings.APPROVAL_SLA_HOURS))


# ---------------------------------------------------------------- auth
def user_payload(user, request):
    profile = services.profile_of(user)
    desk = services.is_desk(user)
    travel_manager = services.is_travel_manager(user)
    return {
        'id': user.pk,
        'username': user.username,
        'full_name': services.display_name(user),
        'role': profile.role,
        'role_label': 'Administrator' if user.is_superuser else profile.get_role_display(),
        'manager_name': services.display_name(profile.manager) if profile.manager else '',
        'is_approver': services.is_approver(user),
        'is_desk': desk,
        'is_travel_manager': travel_manager,
        'is_superuser': user.is_superuser,
        'email': user.email,
        'designation': profile.designation,
        'department': profile.department,
        'employee_id': profile.employee_id,
        # Temporary password (new account / admin reset): the app shows only the change-password screen.
        'must_change_password': profile.must_change_password,
        # Travel profile not filled in yet: the app shows only the profile form.
        'profile_complete': profile.profile_completed_at is not None,
        # Set at sign-in: the password doesn't meet the policy -> UI nags to change it.
        'password_weak': bool(request.session.get('weak_password')),
        'session_minutes': settings.SESSION_COOKIE_AGE // 60,
        'counts': {
            'pending_approvals': TravelRequest.objects.filter(
                approver=user, status=S.PENDING_APPROVAL).exclude(employee=user).count(),
            # Waiting on me: trips assigned to me (to book, or a cancellation to handle)
            'desk_queue': TravelRequest.objects.filter(
                desk_agent=user, status__in=[S.IN_PROGRESS, S.CANCELLATION_REQUESTED]).count() if desk else 0,
            'to_assign': TravelRequest.objects.filter(status=S.APPROVED).count() if travel_manager else 0,
        },
    }


def demo_accounts():
    if not settings.DEMO_MODE:
        return []
    from .management.commands.seed_demo import DEMO_USERS
    names = [u[0] for u in DEMO_USERS]
    users = {u.username: u for u in User.objects.filter(username__in=names, is_active=True)
             .select_related('profile')}
    def note(u):
        p = u.profile
        return 'No manager set' if p.role == p.Role.EMPLOYEE and not p.manager else p.get_role_display()

    return [{'username': n, 'name': services.display_name(users[n]), 'note': note(users[n])}
            for n in names if n in users]


@ensure_csrf_cookie
@api_view(['GET'])
@permission_classes([AllowAny])
def csrf(request):
    # Demo accounts are listed only in demo mode; their password never reaches the browser.
    return Response({'ok': True, 'demo_mode': settings.DEMO_MODE, 'demo_users': demo_accounts()})


@api_view(['GET'])
@permission_classes([AllowAny])
def me(request):
    user = request.user
    return Response({'user': user_payload(user, request) if user.is_authenticated else None})


def _locked_response(seconds):
    minutes = max(1, -(-seconds // 60))
    return Response({'detail': f'Too many failed attempts. Try again in {minutes} minute{"s" if minutes > 1 else ""}.',
                     'retry_after': seconds}, status=429, headers={'Retry-After': str(seconds)})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([security.LoginThrottle])
def login_view(request):
    username = str(request.data.get('username', '')).strip()[:150]
    password = str(request.data.get('password', ''))[:256]
    if not username or not password:
        return Response({'detail': 'Enter your username and password.'}, status=400)

    ip = security.client_ip(request)
    wait = security.lock_remaining(username, ip)
    if wait:
        authenticate(request, username=username, password=password)  # records the locked attempt
        return _locked_response(wait)

    user = authenticate(request, username=username, password=password)
    if user is None:  # wrong password, unknown user or deactivated: same answer (no user enumeration)
        wait = security.lock_remaining(username, ip)
        return _locked_response(wait) if wait else Response({'detail': 'Wrong username or password.'}, status=400)

    login(request, user)  # new session id (prevents session fixation)
    request.session['weak_password'] = security.password_is_weak(password, user)
    return Response({'user': user_payload(user, request)})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([security.LoginThrottle])
def demo_login(request):
    """One-click sign-in for the demo accounts. Only exists in demo mode."""
    if not settings.DEMO_MODE:
        raise Http404
    username = str(request.data.get('username', ''))
    if username not in {u['username'] for u in demo_accounts()}:
        return Response({'detail': 'Unknown demo account.'}, status=400)
    wait = security.lock_remaining(username, security.client_ip(request))
    if wait:  # a locked account stays locked, even in demo mode
        return _locked_response(wait)
    user = User.objects.get(username=username)
    login(request, user, backend='desk.security.LockoutModelBackend')
    request.session['weak_password'] = False
    return Response({'user': user_payload(user, request)})


@api_view(['POST'])
@permission_classes([AllowAny])
def logout_view(request):
    logout(request)
    return Response(status=204)


@api_view(['POST'])
@throttle_classes([security.LoginThrottle])
def change_password(request):
    user = request.user
    current = str(request.data.get('current_password', ''))
    new = str(request.data.get('new_password', ''))
    confirm = str(request.data.get('confirm_password', ''))

    if not user.check_password(current):
        security.log_event(SecurityEvent.Type.PASSWORD_CHANGE_FAILED, request, user, detail='Wrong current password')
        return Response({'current_password': ['Current password is incorrect.']}, status=400)
    if new != confirm:
        return Response({'confirm_password': ['The two new passwords do not match.']}, status=400)
    if new == current:
        return Response({'new_password': ['Choose a password different from the current one.']}, status=400)
    try:
        validate_password(new, user)
    except DjangoValidationError as e:
        return Response({'new_password': list(e.messages)}, status=400)

    user.set_password(new)
    user.save(update_fields=['password'])
    update_session_auth_hash(request, user)       # keep THIS session signed in...
    ended = security.revoke_sessions(user, keep_session_key=request.session.session_key)  # ...end all others
    request.session['weak_password'] = False
    profile = services.profile_of(user)
    if profile.must_change_password:
        profile.must_change_password = False
        profile.save(update_fields=['must_change_password'])
    security.log_event(SecurityEvent.Type.PASSWORD_CHANGED, request, user,
                       detail=f'Signed out {ended} other session(s)' if ended else '')
    return Response({'user': user_payload(user, request)})


@api_view(['GET'])
def my_activity(request):
    """The signed-in user's own recent sign-ins and security events."""
    events = SecurityEvent.objects.filter(user=request.user)[:15]
    return Response([{'id': e.id, 'type': e.type, 'label': e.get_type_display(), 'ip': e.ip,
                      'user_agent': e.user_agent, 'detail': e.detail, 'created_at': e.created_at}
                     for e in events])


# ---------------------------------------------------------------- travel requests
class TravelRequestViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                           mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    GET  /api/requests/?scope=mine|approvals|desk&status=A,B&q=text&overdue=1&ordering=newest&page=2
    POST /api/requests/                    create + submit
    GET  /api/requests/<id>/
    PUT  /api/requests/<id>/               edit a RETURNED request (re-submits it)
    POST /api/requests/<id>/act/           {action, comment, ...}  every workflow step
                                           (desk: action=book_leg, leg=<leg id>, ticket file ...)
    GET  /api/requests/<id>/legs/<leg>/ticket/   download one leg's ticket (permission checked)
    No DELETE: requests are cancelled, never deleted (audit trail).
    """

    def get_serializer_class(self):
        return TravelRequestListSerializer if self.action == 'list' else TravelRequestSerializer

    def get_queryset(self):
        services.maybe_auto_close()
        params = self.request.query_params
        qs = scoped_queryset(self.request.user, params.get('scope')).select_related(
            'employee', 'approver', 'desk_agent').prefetch_related('legs')

        if self.action != 'list':
            return qs.prefetch_related('events__actor')

        # Filtering + search happen in the database, so only one page travels to the browser.
        if params.get('status'):
            qs = qs.filter(status__in=params['status'].split(','))
        if params.get('overdue') == '1':
            qs = qs.filter(overdue_q())
        q = params.get('q', '').strip()[:100]
        if q:
            matching_legs = TripLeg.objects.filter(Q(origin__icontains=q) | Q(destination__icontains=q))
            qs = qs.filter(
                Q(request_code__icontains=q) | Q(traveller_name__icontains=q)
                | Q(pk__in=matching_legs.values('request'))
                | Q(employee__first_name__icontains=q) | Q(employee__last_name__icontains=q)
                | Q(employee__username__icontains=q)
            )
        return qs.order_by(ORDERINGS.get(params.get('ordering'), '-created_at'), '-id')

    def perform_create(self, serializer):
        services.submit_new(self.request.user, serializer)

    def update(self, request, *args, **kwargs):
        req = self.get_object()
        if req.employee_id != request.user.pk:
            raise PermissionDenied('Only the employee who raised this request can edit it.')
        if req.status != S.RETURNED:
            raise services.Conflict('Only requests returned for changes can be edited.')
        serializer = self.get_serializer(req, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        services.perform_action(request.user, req.pk, 'resubmit',
                                request.data.get('comment') or 'Updated and resubmitted.')
        return Response(self._fresh(req.pk))

    @action(detail=True, methods=['post'])
    def act(self, request, pk=None):
        req = self.get_object()  # 404 if this user can't see it
        services.perform_action(
            request.user, req.pk, request.data.get('action', ''), request.data.get('comment', ''),
            data=request.data, files=request.FILES,
        )
        return Response(self._fresh(req.pk))

    @action(detail=True, methods=['get'], url_path=r'legs/(?P<leg_id>\d+)/ticket')
    def ticket(self, request, pk=None, leg_id=None):
        req = self.get_object()  # 404 if this user can't see the request
        leg = req.legs.filter(pk=leg_id).first()
        if not leg or not leg.ticket:
            raise Http404('No ticket uploaded.')
        return FileResponse(leg.ticket.open('rb'), as_attachment=True,
                            filename=os.path.basename(leg.ticket.name))

    def _fresh(self, pk):
        req = TravelRequest.objects.select_related('employee', 'approver', 'desk_agent') \
            .prefetch_related('legs', 'events__actor').get(pk=pk)
        return self.get_serializer(req).data


# ---------------------------------------------------------------- dashboard
@api_view(['GET'])
def dashboard(request):
    """Counts per status for the stat cards: one GROUP BY query instead of loading rows."""
    services.maybe_auto_close()
    qs = scoped_queryset(request.user, request.query_params.get('scope', 'mine'))
    by_status = dict(qs.order_by().values_list('status').annotate(n=Count('id')))
    return Response({
        'by_status': by_status,
        'total': sum(by_status.values()),
        'overdue': qs.filter(overdue_q()).count(),
    })


# ---------------------------------------------------------------- notifications
@api_view(['GET'])
def notifications(request):
    items = request.user.notifications.all()[:20]
    return Response({
        'unread': request.user.notifications.filter(is_read=False).count(),
        'items': [
            {'id': n.id, 'message': n.message, 'is_read': n.is_read,
             'created_at': n.created_at, 'request_id': n.request_id}
            for n in items
        ],
    })


@api_view(['POST'])
def notifications_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return Response(status=204)


# ---------------------------------------------------------------- Travel Manager
def _require_travel_manager(user):
    if not (services.is_travel_manager(user) or user.is_superuser):
        raise PermissionDenied('Only Travel Managers can see this.')


@api_view(['GET'])
def desk_agents(request):
    """People a trip can be assigned to, with how much they are booking right now."""
    _require_travel_manager(request.user)
    agents = services.bookers().select_related('profile').annotate(open_trips=Count(
        'desk_assignments', filter=Q(desk_assignments__status__in=[S.IN_PROGRESS, S.CANCELLATION_REQUESTED])))
    return Response([{'id': a.pk, 'name': services.display_name(a), 'role_label': a.profile.get_role_display(),
                      'open_trips': a.open_trips}
                     for a in sorted(agents, key=lambda a: (a.open_trips, services.display_name(a)))])


@api_view(['GET'])
def desk_analytics(request):
    """Numbers for the Travel Manager: queue, this month's bookings and spend, speed, and agent workload."""
    _require_travel_manager(request.user)
    now = timezone.now()
    month_start = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_30 = now - timedelta(days=30)

    by_status = dict(TravelRequest.objects.filter(status__in=DESK_STATUSES).order_by()
                     .values_list('status').annotate(n=Count('id')))
    oldest_waiting = TravelRequest.objects.filter(status=S.APPROVED).order_by('updated_at').first()

    booked_this_month = RequestEvent.objects.filter(action='book', created_at__gte=month_start)
    spend = TripLeg.objects.filter(booked_at__gte=month_start).aggregate(total=Sum('actual_cost'))['total'] or 0
    trip_types = dict(TravelRequest.objects.filter(pk__in=booked_this_month.values('request_id')).order_by()
                      .values_list('trip_type').annotate(n=Count('id')))

    # Approval -> fully booked, for trips booked in the last 30 days
    booked = dict(RequestEvent.objects.filter(action='book', created_at__gte=last_30)
                  .values_list('request_id', 'created_at'))
    approved = dict(RequestEvent.objects.filter(action='approve', request_id__in=booked)
                    .order_by('created_at').values_list('request_id', 'created_at'))
    hours = [(booked[r] - approved[r]).total_seconds() / 3600 for r in booked if r in approved]

    done_30 = dict(RequestEvent.objects.filter(action='book', created_at__gte=last_30).order_by()
                   .values_list('actor').annotate(n=Count('id')))
    agents = services.bookers().select_related('profile').annotate(
        in_progress=Count('desk_assignments', filter=Q(desk_assignments__status=S.IN_PROGRESS)),
        cancellations=Count('desk_assignments', filter=Q(desk_assignments__status=S.CANCELLATION_REQUESTED)),
    )
    return Response({
        'waiting_assignment': by_status.get(S.APPROVED, 0),
        'in_progress': by_status.get(S.IN_PROGRESS, 0),
        'cancellation_requests': by_status.get(S.CANCELLATION_REQUESTED, 0),
        'booked_upcoming': by_status.get(S.BOOKED, 0),
        'oldest_waiting_hours': round((now - oldest_waiting.updated_at).total_seconds() / 3600)
        if oldest_waiting else None,
        'month': {
            'trips_booked': booked_this_month.count(),
            'spend': spend,
            'domestic': trip_types.get(TravelRequest.TripType.DOMESTIC, 0),
            'international': trip_types.get(TravelRequest.TripType.INTERNATIONAL, 0),
        },
        'avg_hours_to_book': round(sum(hours) / len(hours), 1) if hours else None,
        'agents': sorted([{'id': a.pk, 'name': services.display_name(a), 'role_label': a.profile.get_role_display(),
                           'in_progress': a.in_progress, 'cancellations': a.cancellations,
                           'booked_30d': done_30.get(a.pk, 0)} for a in agents],
                         key=lambda a: (-a['in_progress'], a['name'])),
    })
