"""
Employee administration helpers:
  - temporary passwords and username suggestions
  - welcome / password-reset emails with login details
  - moving open work to someone else when a person's role, manager or status changes
"""
import logging
import re
import secrets
import string

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from . import services
from .models import Profile, RequestEvent, TravelRequest

logger = logging.getLogger('desk.security')
User = get_user_model()
S = TravelRequest.Status

# No look-alike characters (0/O, 1/l/I) so a password read from an email is typed correctly.
_LETTERS = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ'
_DIGITS = '23456789'
_SYMBOLS = '!@#$%*?'


def generate_temp_password(length=12):
    """Random password that always passes the password policy."""
    while True:
        chars = [secrets.choice(_LETTERS.lower()), secrets.choice(_LETTERS.upper()),
                 secrets.choice(_DIGITS), secrets.choice(_SYMBOLS)]
        chars += [secrets.choice(_LETTERS + _DIGITS + _SYMBOLS) for _ in range(length - len(chars))]
        secrets.SystemRandom().shuffle(chars)
        password = ''.join(chars)
        try:
            validate_password(password)
            return password
        except DjangoValidationError:
            continue


def suggest_username(first_name, last_name):
    """asha.patil, then asha.patil2, asha.patil3 ... (never reuses an existing one)."""
    base = '.'.join(re.sub(r'[^a-z0-9]', '', p.lower()) for p in (first_name, last_name) if p.strip())
    base = (base.strip('.') or 'user')[:140]
    candidate, n = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f'{base}{n}'
    return candidate


# ---------------------------------------------------------------- emails
def send_login_details(user, temp_password, reason='welcome'):
    """Email username + temporary password. Returns (sent: bool, error: str)."""
    if not user.email:
        return False, 'This user has no email address.'
    first = user.first_name or user.username
    if reason == 'welcome':
        subject = 'Your Travel Desk account'
        intro = 'An account has been created for you on Travel Desk, the company travel booking portal.'
    else:
        subject = 'Your Travel Desk password was reset'
        intro = 'An administrator has reset your Travel Desk password.'
    body = (
        f'Hi {first},\n\n{intro}\n\n'
        f'Sign in here: {settings.PORTAL_URL}\n'
        f'Username: {user.username}\n'
        f'Temporary password: {temp_password}\n\n'
        'You will be asked to choose your own password the first time you sign in.\n'
        'Never share your password. Travel Desk staff will never ask for it.\n\n'
        'If you did not expect this email, contact your administrator.\n'
    )
    try:
        send_mail(subject, body, None, [user.email], fail_silently=False)
        return True, ''
    except Exception as exc:  # SMTP down, wrong credentials, ...: the admin sees it and can share manually
        logger.warning('Could not email login details to %s: %s', user.username, exc)
        return False, 'The email could not be sent. Share the temporary password with them securely.'


# ---------------------------------------------------------------- moving open work
def _event(req, actor, action, old_status, comment):
    RequestEvent.objects.create(request=req, actor=actor, action=action,
                                from_status=old_status, to_status=req.status, comment=comment)


def release_desk_work(agent, actor, why):
    """Requests this desk agent was booking go back to the Travel Managers, to be assigned again."""
    moved = 0
    for req in TravelRequest.objects.select_for_update().filter(desk_agent=agent, status=S.IN_PROGRESS):
        req.status, req.desk_agent = S.APPROVED, None
        req.save(update_fields=['status', 'desk_agent', 'updated_at'])
        _event(req, actor, 'release', S.IN_PROGRESS, why)
        services.notify(services.travel_managers(), req,
                        f'{req.request_code} needs to be assigned again: {why}', actor)
        moved += 1
    return moved


def reassign_approvals(old_approver, actor, why, new_approver=None):
    """Pending approvals waiting on `old_approver` move to `new_approver`
    (default: old approver's own manager, i.e. escalate one level up)."""
    target = new_approver or services.profile_of(old_approver).manager
    moved = 0
    for req in TravelRequest.objects.select_for_update().select_related('employee').filter(
            approver=old_approver, status=S.PENDING_APPROVAL):
        if not target or not target.is_active or target.pk == req.employee_id:
            continue  # nobody suitable: stays visible to admins as stuck
        req.approver, req.submitted_at = target, timezone.now()
        req.save(update_fields=['approver', 'submitted_at', 'updated_at'])
        _event(req, actor, 'reassign', S.PENDING_APPROVAL,
               f'Approver changed to {services.display_name(target)}: {why}')
        services.notify([target], req, f'{req.request_code} from {services.display_name(req.employee)} '
                                       f'now needs your approval ({why}).', actor)
        moved += 1
    return moved


def move_employee_pending_to(employee, new_manager, actor):
    """Employee got a new manager: their pending requests go to the new manager."""
    moved = 0
    if not new_manager or not new_manager.is_active:
        return 0
    for req in TravelRequest.objects.select_for_update().filter(employee=employee, status=S.PENDING_APPROVAL) \
            .exclude(approver=new_manager):
        req.approver, req.submitted_at = new_manager, timezone.now()
        req.save(update_fields=['approver', 'submitted_at', 'updated_at'])
        _event(req, actor, 'reassign', S.PENDING_APPROVAL,
               f'Approver changed to {services.display_name(new_manager)}: reporting manager changed')
        services.notify([new_manager], req, f'{req.request_code} from {services.display_name(employee)} '
                                            'now needs your approval (reporting manager changed).', actor)
        moved += 1
    return moved


@transaction.atomic
def apply_access_changes(user, actor, *, old_role, old_manager, deactivated):
    """Keep open requests moving after an admin edits someone. Returns a short summary."""
    notes = []
    profile = services.profile_of(user)
    if profile.manager != old_manager and profile.manager:
        n = move_employee_pending_to(user, profile.manager, actor)
        if n:
            notes.append(f'{n} pending request(s) moved to the new manager')
    if deactivated:
        n = reassign_approvals(user, actor, f'{services.display_name(user)} was deactivated')
        if n:
            notes.append(f'{n} approval(s) escalated')
        n = release_desk_work(user, actor, f'{services.display_name(user)} was deactivated')
        if n:
            notes.append(f'{n} booking(s) returned to the desk queue')
    elif old_role in services.DESK_ROLES and profile.role not in services.DESK_ROLES:
        n = release_desk_work(user, actor, f'{services.display_name(user)} is no longer on the Travel Desk')
        if n:
            notes.append(f'{n} booking(s) returned to the desk queue')
    return notes
