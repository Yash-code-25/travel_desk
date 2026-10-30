"""
Administration API — superusers only.

GET   /api/security/overview/                       numbers for the cards + latest alerts
GET   /api/security/events/?type=&q=&page=          security log
GET   /api/security/users/?q=&status=&page=         employees
POST  /api/security/users/                          register an employee (+ email login details)
PATCH /api/security/users/<id>/                     edit details / role / manager / active / admin
POST  /api/security/users/<id>/reset-password/      new temporary password (+ email)
POST  /api/security/users/<id>/unlock/              lift a sign-in lockout
POST  /api/security/users/<id>/revoke-sessions/     sign the user out everywhere
GET   /api/security/users/suggest-username/?first=&last=
"""
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from . import employees, security, services
from .models import Profile, SecurityEvent

User = get_user_model()
E = SecurityEvent.Type


class IsSuperuser(BasePermission):
    message = 'Only administrators can do this.'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and u.is_superuser)


# ---------------------------------------------------------------- overview
@api_view(['GET'])
@permission_classes([IsSuperuser])
def overview(request):
    since = timezone.now() - timedelta(hours=24)
    counts = dict(SecurityEvent.objects.filter(created_at__gte=since).order_by()
                  .values_list('type').annotate(n=Count('id')))
    active = Q(is_active=True)
    users = User.objects.aggregate(
        total=Count('id'), inactive=Count('id', filter=Q(is_active=False)),
        admins=Count('id', filter=Q(is_superuser=True) & active),
        employees=Count('id', filter=Q(profile__role=Profile.Role.EMPLOYEE) & active),
        managers=Count('id', filter=Q(profile__role=Profile.Role.MANAGER) & active),
        desk=Count('id', filter=Q(profile__role=Profile.Role.DESK) & active),
        travel_managers=Count('id', filter=Q(profile__role=Profile.Role.TRAVEL_MANAGER) & active),
        awaiting_first_login=Count('id', filter=Q(profile__must_change_password=True) & active),
    )
    locked = [u.username for u in User.objects.only('username') if security.is_locked(u.username)]
    alerts = SecurityEvent.objects.filter(type__in=SecurityEvent.ALERT_TYPES).select_related('actor')[:6]
    return Response({
        'last_24h': {
            'logins': counts.get(E.LOGIN_SUCCESS, 0),
            'failed_logins': counts.get(E.LOGIN_FAILED, 0) + counts.get(E.LOCKED_ATTEMPT, 0),
            'lockouts': counts.get(E.LOCKED_OUT, 0),
            'denied': counts.get(E.PERMISSION_DENIED, 0) + counts.get(E.UPLOAD_REJECTED, 0),
        },
        'users': {**users, 'locked': len(locked)},
        'locked_usernames': locked,
        'alerts': EventSerializer(alerts, many=True).data,
    })


# ---------------------------------------------------------------- security log
class EventSerializer(serializers.ModelSerializer):
    label = serializers.CharField(source='get_type_display')
    actor_name = serializers.SerializerMethodField()
    is_alert = serializers.SerializerMethodField()

    class Meta:
        model = SecurityEvent
        fields = ['id', 'type', 'label', 'is_alert', 'username', 'actor_name', 'ip', 'user_agent', 'detail', 'created_at']

    def get_actor_name(self, obj):
        return services.display_name(obj.actor) if obj.actor_id else ''

    def get_is_alert(self, obj):
        return obj.type in SecurityEvent.ALERT_TYPES


class EventViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsSuperuser]
    serializer_class = EventSerializer

    def get_queryset(self):
        qs = SecurityEvent.objects.select_related('actor')
        p = self.request.query_params
        if p.get('type') == 'alerts':
            qs = qs.filter(type__in=SecurityEvent.ALERT_TYPES)
        elif p.get('type'):
            qs = qs.filter(type=p['type'])
        q = p.get('q', '').strip()[:100]
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(ip__icontains=q) | Q(detail__icontains=q))
        return qs


# ---------------------------------------------------------------- employees
USERNAME_RE = re.compile(r'^[a-zA-Z0-9.@+_-]{3,150}$')
PHONE_RE = re.compile(r'^\+?[0-9 ()-]{7,20}$')


class EmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    username = serializers.CharField(max_length=150, required=False, allow_blank=True)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)
    is_admin = serializers.BooleanField(source='is_superuser', required=False)
    # Profile fields
    role = serializers.ChoiceField(choices=Profile.Role.choices, source='profile.role', required=False)
    role_label = serializers.CharField(source='profile.get_role_display', read_only=True)
    manager_id = serializers.PrimaryKeyRelatedField(
        source='profile.manager', queryset=User.objects.filter(is_active=True), allow_null=True, required=False)
    manager_name = serializers.SerializerMethodField()
    employee_id = serializers.CharField(source='profile.employee_id', max_length=30, required=False, allow_blank=True)
    department = serializers.CharField(source='profile.department', max_length=100, required=False, allow_blank=True)
    designation = serializers.CharField(source='profile.designation', max_length=100, required=False, allow_blank=True)
    phone = serializers.CharField(source='profile.phone', max_length=20, required=False, allow_blank=True)
    must_change_password = serializers.BooleanField(source='profile.must_change_password', read_only=True)
    profile_complete = serializers.SerializerMethodField()
    team_size = serializers.IntegerField(read_only=True, default=0)
    locked = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'full_name', 'email', 'phone', 'employee_id',
                  'department', 'designation', 'role', 'role_label', 'manager_id', 'manager_name', 'team_size',
                  'is_active', 'is_admin', 'must_change_password', 'profile_complete', 'last_login', 'date_joined', 'locked']
        read_only_fields = ['last_login', 'date_joined']

    def get_full_name(self, obj):
        return services.display_name(obj)

    def get_manager_name(self, obj):
        m = getattr(getattr(obj, 'profile', None), 'manager', None)
        return services.display_name(m) if m else ''

    def get_profile_complete(self, obj):
        return services.profile_of(obj).profile_completed_at is not None

    def get_locked(self, obj):
        return security.is_locked(obj.username)

    # ------------------------------------------------ field checks
    def validate_first_name(self, v):
        return v.strip()

    def validate_last_name(self, v):
        return v.strip()

    def validate_email(self, v):
        v = v.strip().lower()
        clash = User.objects.filter(email__iexact=v)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError('Another account already uses this email address.')
        return v

    def validate_username(self, v):
        v = v.strip()
        if self.instance:
            if v and v != self.instance.username:
                raise serializers.ValidationError('Usernames cannot be changed.')
            return self.instance.username
        if not v:
            return v  # generated later from the name
        if not USERNAME_RE.match(v):
            raise serializers.ValidationError('3-150 characters: letters, numbers and . @ + - _ only.')
        if User.objects.filter(username__iexact=v).exists():
            raise serializers.ValidationError('This username is taken.')
        return v

    def validate_employee_id(self, v):
        v = v.strip().upper()
        if v:
            clash = Profile.objects.filter(employee_id__iexact=v)
            if self.instance:
                clash = clash.exclude(user=self.instance)
            if clash.exists():
                raise serializers.ValidationError('Another employee already has this ID.')
        return v

    def validate_phone(self, v):
        v = v.strip()
        if v and not PHONE_RE.match(v):
            raise serializers.ValidationError('Enter a valid phone number, e.g. +91 98765 43210.')
        return v

    def validate(self, data):
        target, actor = self.instance, self.context['request'].user
        manager = data.get('profile', {}).get('manager', 'unchanged')

        if target and manager not in ('unchanged', None):
            if manager.pk == target.pk:
                raise serializers.ValidationError({'manager_id': 'A person cannot be their own manager.'})
            seen, m = set(), manager  # no loops: the new manager's chain must never reach this person
            while m is not None and m.pk not in seen:
                if m.pk == target.pk:
                    raise serializers.ValidationError(
                        {'manager_id': f'{services.display_name(manager)} already reports to this person.'})
                seen.add(m.pk)
                m = services.profile_of(m).manager

        if target and target.pk == actor.pk:
            if data.get('is_active') is False:
                raise serializers.ValidationError({'is_active': 'You cannot deactivate your own account.'})
            if data.get('is_superuser') is False:
                raise serializers.ValidationError({'is_admin': 'You cannot remove your own administrator access.'})

        removing_admin = target and target.is_superuser and (
            data.get('is_active') is False or data.get('is_superuser') is False)
        if removing_admin and not User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target.pk).exists():
            raise serializers.ValidationError({'is_admin': 'This is the last active administrator.'})
        return data

    # ------------------------------------------------ save
    @transaction.atomic
    def create(self, data):
        actor = self.context['request'].user
        p = data.pop('profile', {})
        is_admin = data.pop('is_superuser', False)
        user = User(
            username=data.get('username') or employees.suggest_username(data['first_name'], data['last_name']),
            first_name=data['first_name'], last_name=data['last_name'], email=data['email'],
            is_superuser=is_admin, is_staff=is_admin, is_active=data.get('is_active', True),
        )
        self.temp_password = employees.generate_temp_password()
        user.set_password(self.temp_password)  # only the hash is stored
        user.save()
        Profile.objects.create(
            user=user, role=p.get('role', Profile.Role.EMPLOYEE), manager=p.get('manager'),
            employee_id=p.get('employee_id', ''), department=p.get('department', ''),
            designation=p.get('designation', ''), phone=p.get('phone', ''), must_change_password=True,
        )
        security.log_event(E.USER_CREATED, self.context['request'], user, actor=actor,
                           detail=f'{p.get("role", "EMPLOYEE")}{" + admin" if is_admin else ""}')
        return user

    @transaction.atomic
    def update(self, user, data):
        actor = self.context['request'].user
        profile = services.profile_of(user)
        old_role, old_manager, was_active = profile.role, profile.manager, user.is_active
        changes = []

        for field in ['first_name', 'last_name', 'email']:
            if field in data and data[field] != getattr(user, field):
                changes.append(f'{field.replace("_", " ")} changed')
                setattr(user, field, data[field])
        if 'is_active' in data and data['is_active'] != user.is_active:
            changes.append('activated' if data['is_active'] else 'deactivated')
            user.is_active = data['is_active']
        if 'is_superuser' in data and data['is_superuser'] != user.is_superuser:
            changes.append('admin access granted' if data['is_superuser'] else 'admin access removed')
            user.is_superuser = user.is_staff = data['is_superuser']
        user.save()

        p = data.get('profile', {})
        if 'role' in p and p['role'] != profile.role:
            changes.append(f'role {profile.role} → {p["role"]}')
        if 'manager' in p and p['manager'] != profile.manager:
            changes.append(f'manager {profile.manager or "none"} → {p["manager"] or "none"}')
        for field in ['employee_id', 'department', 'designation', 'phone']:
            if field in p and p[field] != getattr(profile, field):
                changes.append(f'{field.replace("_", " ")} changed')
        for field, value in p.items():
            setattr(profile, field, value)
        profile.save()

        deactivated = was_active and not user.is_active
        if deactivated or 'admin access removed' in changes:
            security.revoke_sessions(user)  # takes effect immediately
        self.work_notes = employees.apply_access_changes(
            user, actor, old_role=old_role, old_manager=old_manager, deactivated=deactivated)
        if changes:
            security.log_event(E.USER_UPDATED, self.context['request'], user, actor=actor,
                               detail='; '.join(changes + self.work_notes))
        return user


class EmployeeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                      mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsSuperuser]
    serializer_class = EmployeeSerializer
    http_method_names = ['get', 'post', 'patch']

    def get_queryset(self):
        qs = (User.objects.select_related('profile__manager')
              .annotate(team_size=Count('team_members', filter=Q(team_members__user__is_active=True), distinct=True))
              .order_by('first_name', 'last_name', 'username'))
        p = self.request.query_params
        q = p.get('q', '').strip()[:100]
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                           | Q(email__icontains=q) | Q(profile__employee_id__icontains=q)
                           | Q(profile__department__icontains=q) | Q(profile__designation__icontains=q))
        status_filter = p.get('status')
        if status_filter == 'inactive':
            qs = qs.filter(is_active=False)
        elif status_filter == 'admins':
            qs = qs.filter(is_superuser=True)
        elif status_filter in Profile.Role.values:
            qs = qs.filter(profile__role=status_filter, is_active=True)
        return qs

    def list(self, request, *args, **kwargs):
        for u in User.objects.filter(profile__isnull=True):
            services.profile_of(u)  # every account gets a profile row
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        sent, error = (False, 'Email not requested.')
        if request.data.get('send_email', True) in (True, 'true', '1', 1):
            sent, error = employees.send_login_details(user, serializer.temp_password, 'welcome')
        data = self.get_serializer(self.get_queryset().get(pk=user.pk)).data
        # The temporary password is shown to the admin ONCE (it is never stored in plain text).
        return Response({**data, 'temporary_password': serializer.temp_password,
                         'email_sent': sent, 'email_error': '' if sent else error},
                        status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        user = self.get_object()
        serializer = self.get_serializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        data = self.get_serializer(self.get_queryset().get(pk=user.pk)).data
        return Response({**data, 'work_notes': getattr(serializer, 'work_notes', [])})

    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        user = self.get_object()
        temp = employees.generate_temp_password()
        user.set_password(temp)
        user.save(update_fields=['password'])
        profile = services.profile_of(user)
        profile.must_change_password = True
        profile.save(update_fields=['must_change_password'])
        ended = security.revoke_sessions(user)
        security.clear_failures(user.username)
        sent, error = (False, 'Email not requested.')
        if request.data.get('send_email', True) in (True, 'true', '1', 1):
            sent, error = employees.send_login_details(user, temp, 'reset')
        security.log_event(E.PASSWORD_RESET, request, user, actor=request.user,
                           detail=f'{ended} session(s) ended; email {"sent" if sent else "not sent"}')
        return Response({'temporary_password': temp, 'email_sent': sent, 'email_error': '' if sent else error})

    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        user = self.get_object()
        security.clear_failures(user.username)
        security.log_event(E.ACCOUNT_UNLOCKED, request, user, actor=request.user)
        return Response(self.get_serializer(self.get_queryset().get(pk=user.pk)).data)

    @action(detail=True, methods=['post'], url_path='revoke-sessions')
    def revoke_sessions(self, request, pk=None):
        user = self.get_object()
        keep = request.session.session_key if user.pk == request.user.pk else None
        ended = security.revoke_sessions(user, keep_session_key=keep)
        security.log_event(E.SESSIONS_REVOKED, request, user, actor=request.user, detail=f'{ended} session(s) ended')
        return Response({'ended': ended})

    @action(detail=False, methods=['get'], url_path='suggest-username')
    def suggest(self, request):
        first = request.query_params.get('first', '')[:150]
        last = request.query_params.get('last', '')[:150]
        return Response({'username': employees.suggest_username(first, last) if (first or last) else ''})
