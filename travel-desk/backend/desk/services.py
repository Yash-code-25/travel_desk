"""
All workflow rules live here, in one place:
  - which action is allowed from which status
  - who is allowed to do it
  - extra checks (reasons, dates, booking details)
  - audit trail + notifications

Views only call `submit_new()` and `perform_action()`.
"""
import os
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status as http
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from .models import Notification, Profile, RequestEvent, SecurityEvent, TravelRequest, TripLeg
from .security import file_matches_extension, log_event

User = get_user_model()
S = TravelRequest.Status
MAX_COMMENT_LENGTH = 1000


class Conflict(APIException):
    """409: the request changed in the meantime (double click, two tabs, two agents)."""
    status_code = http.HTTP_409_CONFLICT
    default_detail = 'This request was already updated by someone else. Refresh and try again.'


# ---------------------------------------------------------------- the workflow
# action -> allowed "from" statuses, resulting status, who may do it, reason required?
ACTIONS = {
    'approve':        dict(src=[S.PENDING_APPROVAL], dst=S.APPROVED, who='approver'),
    'return':         dict(src=[S.PENDING_APPROVAL], dst=S.RETURNED, who='approver', reason=True),
    'reject':         dict(src=[S.PENDING_APPROVAL], dst=S.REJECTED, who='approver', reason=True),
    'resubmit':       dict(src=[S.RETURNED], dst=S.PENDING_APPROVAL, who='owner'),
    'cancel':         dict(src=[S.PENDING_APPROVAL, S.RETURNED, S.APPROVED, S.IN_PROGRESS],
                           dst=S.CANCELLED, who='owner'),
    'request_cancel': dict(src=[S.BOOKED], dst=S.CANCELLATION_REQUESTED, who='owner', reason=True),
    'pick_up':        dict(src=[S.APPROVED], dst=S.IN_PROGRESS, who='desk'),
    'release':        dict(src=[S.IN_PROGRESS], dst=S.APPROVED, who='agent'),
    'unavailable':    dict(src=[S.IN_PROGRESS], dst=S.RETURNED, who='agent', reason=True),
    # One leg at a time (flight / train / cab / hotel). The trip becomes BOOKED when every leg is booked.
    'book_leg':       dict(src=[S.IN_PROGRESS], dst=S.BOOKED, who='agent'),
    'confirm_cancel': dict(src=[S.CANCELLATION_REQUESTED], dst=S.CANCELLED, who='desk'),
    'decline_cancel': dict(src=[S.CANCELLATION_REQUESTED], dst=S.BOOKED, who='desk', reason=True),
    'complete':       dict(src=[S.BOOKED], dst=S.COMPLETED, who='desk'),
}

# These need the trip to still be in the future.
FUTURE_ONLY_ACTIONS = {'approve', 'pick_up', 'book_leg', 'resubmit'}


# ---------------------------------------------------------------- roles
# Role lookups are remembered on the user object, so a list of 20 requests
# costs 1 query for the role instead of 20 (one per row's allowed_actions).
def profile_of(user):
    profile = getattr(user, '_desk_profile', None)
    if profile is None:
        try:
            profile = user.profile  # free if already loaded with select_related
        except Profile.DoesNotExist:
            profile = Profile.objects.create(user=user)
        user._desk_profile = profile
    return profile


def is_desk(user):
    return profile_of(user).role == Profile.Role.DESK


def is_approver(user):
    if not hasattr(user, '_desk_is_approver'):
        user._desk_is_approver = user.team_members.exists()
    return user._desk_is_approver


def display_name(user):
    if not user:
        return 'System'
    return user.get_full_name() or user.username


def get_approver(employee):
    """The employee's reporting manager. Must exist, be active and not be the employee."""
    manager = profile_of(employee).manager
    if manager is None or not manager.is_active or manager.pk == employee.pk:
        raise ValidationError({'non_field_errors': [
            'You have no active reporting manager, so this request cannot be sent for approval. '
            'Please ask HR/admin to set your manager.'
        ]})
    return manager


def can_act(user, req, who):
    # Nobody can approve or process their own travel.
    if who == 'owner':
        return req.employee_id == user.pk
    if req.employee_id == user.pk:
        return False
    if who == 'approver':
        return req.approver_id == user.pk
    if who == 'desk':
        return is_desk(user)
    if who == 'agent':
        return is_desk(user) and req.desk_agent_id == user.pk
    return False


def allowed_actions(user, req):
    """What buttons this user should see for this request (the frontend just renders them)."""
    today = timezone.localdate()
    blocked_by_date = set()
    if req.start_date < today:
        blocked_by_date |= FUTURE_ONLY_ACTIONS | {'request_cancel'}
    if req.start_date > today:
        blocked_by_date.add('complete')

    actions = [name for name, rule in ACTIONS.items()
               if req.status in rule['src'] and can_act(user, req, rule['who'])
               and name not in blocked_by_date]
    if req.status == S.RETURNED and req.employee_id == user.pk:
        actions.insert(0, 'edit')
    return actions


# Actions that are always "available" but don't mean the user is blocking anything.
PASSIVE_ACTIONS = {'cancel', 'request_cancel', 'release', 'complete', 'resubmit'}


def needs_attention(user, req):
    """True when this user is the one the request is waiting on (blue dot in lists)."""
    return any(a not in PASSIVE_ACTIONS for a in allowed_actions(user, req))


# ---------------------------------------------------------------- notifications
def notify(users, req, message, actor=None):
    recipients = {}
    for user in users:
        if user and user.is_active and not (actor and user.pk == actor.pk):
            recipients[user.pk] = user
    if not recipients:
        return
    Notification.objects.bulk_create(
        [Notification(user=u, request=req, message=message) for u in recipients.values()])
    emails = [u.email for u in recipients.values() if u.email]
    if emails:
        # Sent after the DB transaction commits, so a rolled-back action never emails anyone.
        transaction.on_commit(lambda: send_mail(
            f'[Travel Desk] {req.request_code}', message, None, emails, fail_silently=True))


def desk_team():
    return list(User.objects.filter(profile__role=Profile.Role.DESK, is_active=True))


def _notify_for(action, req, actor, comment, old_status):
    who = display_name(actor)
    code = req.request_code
    reason = f' Reason: {comment}' if comment else ''
    emp = req.employee

    traveller = '' if req.traveller_is_requester else f' for {req.traveller_name}'

    if action in ('submit', 'resubmit'):
        notify([req.approver], req,
               f'{who} submitted {code}{traveller} ({req.route_summary}) for your approval.', actor)
    elif action == 'approve':
        notify([emp], req, f'{code} was approved by {who} and sent to the Travel Desk.', actor)
        notify(desk_team(), req, f'{code} ({req.traveller_name}: {req.route_summary}) is waiting in the desk queue.', actor)
    elif action == 'return':
        notify([emp], req, f'{who} returned {code} for changes.{reason}', actor)
    elif action == 'reject':
        notify([emp], req, f'{who} rejected {code}.{reason}', actor)
    elif action == 'cancel':
        targets = [req.approver] if old_status == S.PENDING_APPROVAL else []
        targets += [req.desk_agent] if old_status == S.IN_PROGRESS else []
        targets += desk_team() if old_status == S.APPROVED else []
        notify(targets, req, f'{who} cancelled {code}.', actor)
    elif action == 'request_cancel':
        notify([req.desk_agent] if req.desk_agent else desk_team(), req,
               f'{who} asked to cancel booked trip {code}.{reason}', actor)
    elif action == 'pick_up':
        notify([emp], req, f'{who} from the Travel Desk is now booking {code}.', actor)
    elif action == 'release':
        notify(desk_team(), req, f'{code} was put back in the desk queue by {who}.', actor)
    elif action == 'unavailable':
        notify([emp, req.approver], req,
               f'{code} could not be booked as requested. Please change and resubmit.{reason}', actor)
    elif action == 'book_leg' and req.status == S.BOOKED:
        refs = ', '.join(leg.booking_reference for leg in req.legs.all())
        notify([emp], req, f'{code} is fully booked{traveller}! References: {refs}. Tickets are attached.', actor)
    elif action == 'confirm_cancel':
        notify([emp], req, f'Cancellation of {code} is confirmed.', actor)
    elif action == 'decline_cancel':
        notify([emp], req, f'Cancellation of {code} was declined; booking stays active.{reason}', actor)
    elif action == 'complete':
        notify([emp], req, f'{code} is marked as completed.', actor)
    elif action == 'expire':
        notify([emp, req.approver], req, f'{code} expired: the travel date passed before it was booked.')


def _log(req, actor, action, old_status, comment=''):
    RequestEvent.objects.create(
        request=req, actor=actor, action=action,
        from_status=old_status or '', to_status=req.status, comment=comment,
    )


# ---------------------------------------------------------------- create
def submit_new(user, serializer):
    approver = get_approver(user)
    with transaction.atomic():
        req = serializer.save(
            employee=user, approver=approver,
            status=S.PENDING_APPROVAL, submitted_at=timezone.now(),
        )
        _log(req, user, 'submit', '')
        _notify_for('submit', req, user, '', '')
    return req


# ---------------------------------------------------------------- every other step
def perform_action(user, pk, action, comment='', data=None, files=None):
    rule = ACTIONS.get(action)
    if rule is None:
        raise ValidationError({'detail': f'Unknown action "{action}".'})
    comment = str(comment or '').strip()
    if len(comment) > MAX_COMMENT_LENGTH:
        raise ValidationError({'comment': [f'Please keep it under {MAX_COMMENT_LENGTH} characters.']})
    data = data or {}

    # Check the uploaded booking files BEFORE the transaction, so a rejected upload
    # is still recorded in the security log (a rollback would erase it).
    booking = None
    if action == 'book_leg':
        pre = TravelRequest.objects.filter(pk=pk).first()
        if pre and can_act(user, pre, rule['who']) and pre.status in rule['src']:
            booking = _validate_booking(pre, user, data, files or {})

    with transaction.atomic():
        # Lock the row so two people clicking at the same moment can't both win.
        req = TravelRequest.objects.select_for_update().select_related('employee', 'approver').get(pk=pk)

        if not can_act(user, req, rule['who']):
            raise PermissionDenied('You are not allowed to do this on this request.')
        if req.status not in rule['src']:
            raise Conflict(f'This request is now "{req.get_status_display()}", so this action is no '
                           f'longer possible. Refresh to see the latest.')
        if rule.get('reason') and not comment:
            raise ValidationError({'comment': ['Please enter a reason.']})

        today = timezone.localdate()
        if action in FUTURE_ONLY_ACTIONS and req.start_date < today:
            raise ValidationError({'detail': 'The travel date has already passed.'})
        if action == 'complete' and req.start_date > today:
            raise ValidationError({'detail': 'The trip has not started yet, so it cannot be completed.'})
        if action == 'request_cancel' and req.start_date < today:
            raise ValidationError({'detail': 'The trip has already started; contact the Travel Desk directly.'})

        old_status = req.status
        extra_note = ''

        if action == 'pick_up':
            req.desk_agent = user
        elif action in ('release', 'unavailable'):
            req.desk_agent = None
        elif action == 'resubmit':
            req.approver = get_approver(req.employee)  # manager may have changed meanwhile
            req.submitted_at = timezone.now()
        elif action == 'book_leg':
            leg = _leg_of(req, data.get('leg'))
            _save_booking(req, leg, booking or _validate_booking(req, user, data, files or {}))
            done = [l for l in req.legs.all() if l.is_booked]
            if len(done) < len(req.legs.all()):
                # Not finished yet: stay "Booking in progress", just record this leg.
                req.save(update_fields=['updated_at'])
                _log(req, user, 'book_leg', old_status,
                     comment or f'Booking {leg.position} of {len(req.legs.all())} done: {leg} · {leg.booking_reference}')
                return req
            extra_note = _cost_overrun_note(req)

        req.status = rule['dst']
        req.save()
        # When the last leg is booked, the history says "booked the trip".
        _log(req, user, 'book' if action == 'book_leg' else action, old_status, comment or extra_note)
        _notify_for(action, req, user, comment, old_status)
        if extra_note:
            notify([req.approver], req, f'{req.request_code}: {extra_note}', user)

    return req


def _validate_booking(req, user, data, files):
    """Check booking details + ticket file. Returns (reference, cost, ticket, ext) or raises 400."""
    errors = {}
    reference = str(data.get('booking_reference') or '').strip()
    if not reference:
        errors['booking_reference'] = ['Booking reference / PNR is required.']
    elif len(reference) > 50:
        errors['booking_reference'] = ['Booking reference is too long (max 50 characters).']

    try:
        cost = Decimal(str(data.get('actual_cost')).strip())
        if cost < 0 or not cost.is_finite():
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        errors['actual_cost'] = ['Enter a valid cost (0 or more).']
        cost = None

    ticket = files.get('ticket')
    ext = os.path.splitext(ticket.name)[1].lower() if ticket else ''
    if not ticket:
        errors['ticket'] = ['Upload the ticket or booking confirmation.']
    elif ext not in settings.ALLOWED_TICKET_EXTENSIONS:
        errors['ticket'] = [f'Only {", ".join(settings.ALLOWED_TICKET_EXTENSIONS)} files are allowed.']
    elif ticket.size > settings.MAX_TICKET_SIZE_MB * 1024 * 1024:
        errors['ticket'] = [f'File is too large (max {settings.MAX_TICKET_SIZE_MB} MB).']
    elif ticket.size == 0:
        errors['ticket'] = ['The file is empty.']
    elif not file_matches_extension(ticket, ext):
        errors['ticket'] = ['This file is not a real PDF/PNG/JPG (its contents do not match its name).']
        log_event(SecurityEvent.Type.UPLOAD_REJECTED, user=user,
                  detail=f'{req.request_code}: "{ticket.name[:80]}" content does not match {ext}')

    if errors:
        raise ValidationError(errors)
    return reference, cost, ticket, ext


def _leg_of(req, leg_id):
    """The leg being booked; it must belong to this request."""
    try:
        return req.legs.get(pk=int(leg_id))
    except (TypeError, ValueError, TripLeg.DoesNotExist):
        raise ValidationError({'leg': ['Choose which booking (leg) this ticket is for.']})


def _save_booking(req, leg, booking):
    """Store the validated booking on one leg. Uploading again replaces that leg's ticket."""
    reference, cost, ticket, ext = booking
    leg.booking_reference, leg.actual_cost, leg.booked_at = reference, cost, timezone.now()
    if leg.ticket:
        leg.ticket.delete(save=False)
    leg.ticket.save(f'{req.request_code}-{leg.position}{ext}', ticket, save=False)
    leg.save()


def _cost_overrun_note(req):
    """Warn the approver when the whole trip costs much more than estimated."""
    total = req.total_actual_cost
    if req.estimated_cost and total and total > req.estimated_cost:
        over = (total - req.estimated_cost) / req.estimated_cost * 100
        if over >= settings.COST_OVERRUN_ALERT_PERCENT:
            return f'Actual cost {total} is {over:.0f}% above the estimate of {req.estimated_cost}.'
    return ''


# ---------------------------------------------------------------- time-based rules
def maybe_auto_close():
    """Run auto_close_past_trips at most once per AUTO_CLOSE_INTERVAL_SECONDS (cheap to call often).
    Date rules are also enforced inside perform_action, so nothing slips through in between."""
    if cache.add('desk:auto_close', True, settings.AUTO_CLOSE_INTERVAL_SECONDS):
        auto_close_past_trips()


def auto_close_past_trips():
    """
    Also run by `manage.py auto_close` (daily cron):
      - not booked yet but travel date passed  -> EXPIRED
      - booked and trip dates are over          -> COMPLETED
    Done in bulk: a few queries total, however many requests change.
    """
    today = timezone.localdate()
    with transaction.atomic():
        expired = list(
            TravelRequest.objects.select_for_update().select_related('employee', 'approver').filter(
                status__in=[S.PENDING_APPROVAL, S.RETURNED, S.APPROVED, S.IN_PROGRESS], start_date__lt=today)
        )
        finished = list(
            TravelRequest.objects.select_for_update().filter(status=S.BOOKED).filter(
                Q(end_date__lt=today) | Q(end_date__isnull=True, start_date__lt=today))
        )
        if not expired and not finished:
            return

        events = []
        for reqs, new_status, action, note in [
            (expired, S.EXPIRED, 'expire', 'Travel date passed before the booking was completed.'),
            (finished, S.COMPLETED, 'complete', 'Trip dates are over.'),
        ]:
            if not reqs:
                continue
            TravelRequest.objects.filter(pk__in=[r.pk for r in reqs]).update(
                status=new_status, updated_at=timezone.now())
            for req in reqs:
                events.append(RequestEvent(request=req, actor=None, action=action,
                                           from_status=req.status, to_status=new_status, comment=note))
                req.status = new_status
        RequestEvent.objects.bulk_create(events)

        for req in expired:
            _notify_for('expire', req, None, '', '')
