"""
Security building blocks, all in one place:
  - brute-force protection (lock a username / IP after repeated failed sign-ins)
  - security audit log (SecurityEvent rows)
  - 401 for expired sessions, logging of "permission denied" attempts
  - helpers: revoke a user's sessions, weak-password check, file signature check
"""
import logging
import math
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.throttling import SimpleRateThrottle

from .models import SecurityEvent

logger = logging.getLogger('desk.security')
User = get_user_model()
E = SecurityEvent.Type


# ---------------------------------------------------------------- request info
def client_ip(request):
    # REMOTE_ADDR only. X-Forwarded-For is trivially spoofed unless a trusted proxy sets it.
    return (request.META.get('REMOTE_ADDR') or None) if request is not None else None


def user_agent(request):
    return (request.META.get('HTTP_USER_AGENT') or '')[:200] if request is not None else ''


# ---------------------------------------------------------------- audit log
def log_event(type_, request=None, user=None, username='', actor=None, detail=''):
    event = SecurityEvent.objects.create(
        type=type_, user=user if user and user.pk else None,
        username=(username or (user.username if user else ''))[:150],
        actor=actor, ip=client_ip(request), user_agent=user_agent(request), detail=detail[:500],
    )
    logger.info('%s user=%s ip=%s %s', type_, event.username, event.ip, detail)
    return event


# ---------------------------------------------------------------- brute-force protection
LOCK_SECONDS = settings.LOGIN_LOCKOUT_MINUTES * 60


def _norm(username):
    return (username or '').strip().lower()


def _keys(username, ip):
    keys = []
    if _norm(username):
        keys.append(('u', _norm(username), settings.LOGIN_MAX_FAILURES))
    if ip:
        keys.append(('ip', ip, settings.LOGIN_MAX_FAILURES_PER_IP))
    return keys


def lock_remaining(username, ip=None):
    """Seconds until this username (or IP) may try again; 0 if not locked."""
    now = time.time()
    for kind, ident, _ in _keys(username, ip):
        until = cache.get(f'sec:lock:{kind}:{ident}')
        if until and until > now:
            return math.ceil(until - now)
    return 0


def register_failure(username, ip):
    """Count a failed sign-in. Returns True if this failure triggered a lockout."""
    locked = False
    for kind, ident, limit in _keys(username, ip):
        key = f'sec:fail:{kind}:{ident}'
        count = cache.get(key, 0) + 1
        cache.set(key, count, LOCK_SECONDS)
        if count >= limit:
            cache.set(f'sec:lock:{kind}:{ident}', time.time() + LOCK_SECONDS, LOCK_SECONDS)
            cache.delete(key)
            locked = True
    return locked


def clear_failures(username):
    ident = _norm(username)
    cache.delete_many([f'sec:fail:u:{ident}', f'sec:lock:u:{ident}'])


def is_locked(username):
    return lock_remaining(username) > 0


class LockoutModelBackend(ModelBackend):
    """Normal username/password check, but refuses locked usernames/IPs.
    Used by both the React sign-in and the Django admin login."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username and lock_remaining(username, client_ip(request)):
            raise DjangoPermissionDenied('Too many failed sign-in attempts.')
        return super().authenticate(request, username=username, password=password, **kwargs)


# Signals fire for every sign-in path (API, Django admin), so nothing escapes the log.
def _on_login_failed(sender, credentials, request=None, **kwargs):
    username = str(credentials.get('username', ''))[:150]
    ip = client_ip(request)
    user = User.objects.filter(username__iexact=username).first() if username else None
    if lock_remaining(username, ip):
        log_event(E.LOCKED_ATTEMPT, request, user, username)
        return
    just_locked = register_failure(username, ip)
    log_event(E.LOGIN_FAILED, request, user, username)
    if just_locked:
        log_event(E.LOCKED_OUT, request, user, username,
                  detail=f'Locked for {settings.LOGIN_LOCKOUT_MINUTES} minutes after repeated failed sign-ins.')


def _on_logged_in(sender, request, user, **kwargs):
    clear_failures(user.username)
    log_event(E.LOGIN_SUCCESS, request, user)


def _on_logged_out(sender, request, user, **kwargs):
    if user is not None:
        log_event(E.LOGOUT, request, user)


def connect_signals():
    user_login_failed.connect(_on_login_failed, dispatch_uid='desk_login_failed')
    user_logged_in.connect(_on_logged_in, dispatch_uid='desk_logged_in')
    user_logged_out.connect(_on_logged_out, dispatch_uid='desk_logged_out')


# ---------------------------------------------------------------- DRF integration
class SessionAuth(SessionAuthentication):
    """Session auth that answers 401 (not 403) when not signed in,
    so the frontend can tell "session expired" apart from "not allowed"."""

    def authenticate_header(self, request):
        return 'Session'


class LoginThrottle(SimpleRateThrottle):
    """Per-IP limit on sign-in style endpoints (rate: REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login'])."""
    scope = 'login'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


def exception_handler(exc, context):
    # Imported here: rest_framework.views reads REST_FRAMEWORK settings, which point back at this module.
    from rest_framework.views import exception_handler as drf_exception_handler

    response = drf_exception_handler(exc, context)
    request = context.get('request')
    if response is not None and response.status_code == 403 and request is not None \
            and request.user and request.user.is_authenticated:
        log_event(E.PERMISSION_DENIED, request, request.user,
                  detail=f'{request.method} {request.path}: {response.data.get("detail", "")}'[:500])
    return response


# ---------------------------------------------------------------- helpers
def revoke_sessions(user, keep_session_key=None):
    """Sign a user out on every device. Returns how many sessions were ended."""
    ended = 0
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        if session.session_key == keep_session_key:
            continue
        if str(session.get_decoded().get('_auth_user_id')) == str(user.pk):
            session.delete()
            ended += 1
    return ended


def password_is_weak(password, user):
    try:
        validate_password(password, user)
        return False
    except DjangoValidationError:
        return True


# First bytes of real files. A renamed .exe can't pass as a .pdf.
FILE_SIGNATURES = {
    '.pdf': [b'%PDF-'],
    '.png': [b'\x89PNG\r\n\x1a\n'],
    '.jpg': [b'\xff\xd8\xff'],
    '.jpeg': [b'\xff\xd8\xff'],
}


def file_matches_extension(uploaded, ext):
    head = uploaded.read(16)
    uploaded.seek(0)
    return any(head.startswith(sig) for sig in FILE_SIGNATURES.get(ext, []))
