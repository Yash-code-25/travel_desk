from datetime import timedelta

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class Profile(models.Model):
    """Extra info for each user: their role and who approves their travel."""

    class Role(models.TextChoices):
        EMPLOYEE = 'EMPLOYEE', 'Employee'
        MANAGER = 'MANAGER', 'Manager'
        DESK = 'DESK', 'Travel Desk'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.EMPLOYEE)
    manager = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='team_members'
    )
    department = models.CharField(max_length=100, blank=True)

    # Employee record (filled in by an administrator)
    employee_id = models.CharField(max_length=30, blank=True)
    designation = models.CharField(max_length=100, blank=True)  # job title, e.g. "Senior Sales Executive"
    phone = models.CharField(max_length=20, blank=True)
    # New accounts and admin password resets get a temporary password that must be changed first.
    must_change_password = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['employee_id'], condition=~models.Q(employee_id=''),
                                    name='unique_employee_id'),
        ]

    def __str__(self):
        return f'{self.user} ({self.get_role_display()})'


class TravelRequest(models.Model):
    class Service(models.TextChoices):
        FLIGHT = 'FLIGHT', 'Flight'
        TRAIN = 'TRAIN', 'Train'
        HOTEL = 'HOTEL', 'Hotel'
        CAB = 'CAB', 'Cab'

    class Status(models.TextChoices):
        PENDING_APPROVAL = 'PENDING_APPROVAL', 'Pending approval'
        RETURNED = 'RETURNED', 'Returned for changes'
        REJECTED = 'REJECTED', 'Rejected'
        APPROVED = 'APPROVED', 'Approved - in desk queue'
        IN_PROGRESS = 'IN_PROGRESS', 'Booking in progress'
        BOOKED = 'BOOKED', 'Booked'
        CANCELLATION_REQUESTED = 'CANCELLATION_REQUESTED', 'Cancellation requested'
        CANCELLED = 'CANCELLED', 'Cancelled'
        COMPLETED = 'COMPLETED', 'Completed'
        EXPIRED = 'EXPIRED', 'Expired'

    # Requests in these states still "hold" the employee's dates (used for duplicate checks).
    ACTIVE_STATUSES = [
        Status.PENDING_APPROVAL, Status.RETURNED, Status.APPROVED,
        Status.IN_PROGRESS, Status.BOOKED, Status.CANCELLATION_REQUESTED,
    ]

    request_code = models.CharField(max_length=20, unique=True, blank=True)
    employee = models.ForeignKey(User, on_delete=models.PROTECT, related_name='travel_requests')
    approver = models.ForeignKey(
        User, null=True, on_delete=models.PROTECT, related_name='requests_to_approve'
    )
    desk_agent = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='desk_assignments'
    )

    service = models.CharField(max_length=10, choices=Service.choices)
    origin = models.CharField(max_length=100, blank=True)  # not used for hotels
    destination = models.CharField(max_length=100)
    start_date = models.DateField()  # departure / check-in
    end_date = models.DateField(null=True, blank=True)  # return / check-out
    purpose = models.TextField()
    preferences = models.TextField(blank=True)
    estimated_cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )

    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING_APPROVAL)

    # Filled in by the Travel Desk
    booking_reference = models.CharField(max_length=50, blank=True)
    actual_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    ticket = models.FileField(upload_to='tickets/', blank=True)

    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        # Speed up the queries every page uses.
        indexes = [
            models.Index(fields=['employee', 'status']),
            models.Index(fields=['approver', 'status']),
            models.Index(fields=['status', 'start_date']),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.request_code:  # e.g. TR-2026-00001, needs the id so set after first save
            self.request_code = f'TR-{self.created_at.year}-{self.pk:05d}'
            super().save(update_fields=['request_code'])

    @property
    def last_date(self):
        return self.end_date or self.start_date

    @property
    def is_overdue(self):
        if self.status != self.Status.PENDING_APPROVAL or not self.submitted_at:
            return False
        return timezone.now() - self.submitted_at > timedelta(hours=settings.APPROVAL_SLA_HOURS)

    def __str__(self):
        return self.request_code or f'Request {self.pk}'


class RequestEvent(models.Model):
    """Audit trail: one row for every step that happened to a request."""

    request = models.ForeignKey(TravelRequest, on_delete=models.CASCADE, related_name='events')
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)  # null = system
    action = models.CharField(max_length=30)
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']


class SecurityEvent(models.Model):
    """Security audit log: sign-ins, lockouts, password and permission changes."""

    class Type(models.TextChoices):
        LOGIN_SUCCESS = 'LOGIN_SUCCESS', 'Signed in'
        LOGIN_FAILED = 'LOGIN_FAILED', 'Failed sign-in'
        LOCKED_OUT = 'LOCKED_OUT', 'Account locked'
        LOCKED_ATTEMPT = 'LOCKED_ATTEMPT', 'Sign-in while locked'
        LOGOUT = 'LOGOUT', 'Signed out'
        PASSWORD_CHANGED = 'PASSWORD_CHANGED', 'Password changed'
        PASSWORD_CHANGE_FAILED = 'PASSWORD_CHANGE_FAILED', 'Password change failed'
        USER_CREATED = 'USER_CREATED', 'User created'
        USER_UPDATED = 'USER_UPDATED', 'User updated'
        PASSWORD_RESET = 'PASSWORD_RESET', 'Password reset by admin'
        ACCOUNT_UNLOCKED = 'ACCOUNT_UNLOCKED', 'Account unlocked'
        SESSIONS_REVOKED = 'SESSIONS_REVOKED', 'Sessions revoked'
        PERMISSION_DENIED = 'PERMISSION_DENIED', 'Permission denied'
        UPLOAD_REJECTED = 'UPLOAD_REJECTED', 'Upload rejected'

    # Types the security panel highlights as "bad".
    ALERT_TYPES = [Type.LOGIN_FAILED, Type.LOCKED_OUT, Type.LOCKED_ATTEMPT, Type.PERMISSION_DENIED,
                   Type.PASSWORD_CHANGE_FAILED, Type.UPLOAD_REJECTED]

    type = models.CharField(max_length=30, choices=Type.choices)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='security_events')
    username = models.CharField(max_length=150, blank=True)  # kept even if the user doesn't exist
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['type', 'created_at']), models.Index(fields=['user', 'created_at'])]

    def __str__(self):
        return f'{self.get_type_display()} - {self.username}'


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    request = models.ForeignKey(TravelRequest, null=True, on_delete=models.CASCADE)
    message = models.CharField(max_length=300)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['user', 'is_read'])]
