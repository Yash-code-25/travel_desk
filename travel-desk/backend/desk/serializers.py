from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from . import services
from .models import RequestEvent, TravelRequest


class EventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = RequestEvent
        fields = ['id', 'action', 'from_status', 'to_status', 'comment', 'actor_name', 'created_at']

    def get_actor_name(self, obj):
        return services.display_name(obj.actor)


class TravelRequestListSerializer(serializers.ModelSerializer):
    """Small payload for tables: no history, no long text."""
    employee_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    service_label = serializers.CharField(source='get_service_display', read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    needs_action = serializers.SerializerMethodField()

    class Meta:
        model = TravelRequest
        fields = [
            'id', 'request_code', 'status', 'status_label', 'employee_name',
            'service', 'service_label', 'origin', 'destination', 'start_date', 'end_date',
            'is_overdue', 'needs_action', 'created_at', 'updated_at',
        ]

    def get_employee_name(self, obj):
        return services.display_name(obj.employee)

    def get_needs_action(self, obj):
        return services.needs_attention(self.context['request'].user, obj)


class TravelRequestSerializer(serializers.ModelSerializer):
    """Full detail: everything + history + allowed actions. Also used for create/edit."""
    employee_name = serializers.SerializerMethodField()
    approver_name = serializers.SerializerMethodField()
    desk_agent_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    service_label = serializers.CharField(source='get_service_display', read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    has_ticket = serializers.SerializerMethodField()
    allowed_actions = serializers.SerializerMethodField()
    events = EventSerializer(many=True, read_only=True)
    # Length caps on free text (stops giant payloads being stored).
    purpose = serializers.CharField(max_length=2000)
    preferences = serializers.CharField(max_length=500, required=False, allow_blank=True)

    class Meta:
        model = TravelRequest
        fields = [
            'id', 'request_code', 'status', 'status_label',
            'employee_name', 'approver_name', 'desk_agent_name',
            'service', 'service_label', 'origin', 'destination', 'start_date', 'end_date',
            'purpose', 'preferences', 'estimated_cost',
            'booking_reference', 'actual_cost', 'has_ticket',
            'is_overdue', 'submitted_at', 'created_at', 'updated_at',
            'allowed_actions', 'events',
        ]
        read_only_fields = [
            'request_code', 'status', 'booking_reference', 'actual_cost',
            'submitted_at', 'created_at', 'updated_at',
        ]

    def get_employee_name(self, obj):
        return services.display_name(obj.employee)

    def get_approver_name(self, obj):
        return services.display_name(obj.approver) if obj.approver else ''

    def get_desk_agent_name(self, obj):
        return services.display_name(obj.desk_agent) if obj.desk_agent else ''

    def get_has_ticket(self, obj):
        return bool(obj.ticket)

    def get_allowed_actions(self, obj):
        return services.allowed_actions(self.context['request'].user, obj)

    def validate_purpose(self, value):
        if len(value.strip()) < 10:
            raise serializers.ValidationError('Please describe the business purpose (at least 10 characters).')
        return value.strip()

    def validate(self, data):
        # On edit, fields that weren't sent keep their current value.
        def get(field):
            return data.get(field, getattr(self.instance, field, None))

        service, origin, destination = get('service'), get('origin') or '', get('destination')
        start, end = get('start_date'), get('end_date')
        today = timezone.localdate()
        errors = {}

        if service == TravelRequest.Service.HOTEL:
            data['origin'] = ''  # hotels have no "from"
            if not end:
                errors['end_date'] = ['Check-out date is required for hotels.']
            elif end <= start:
                errors['end_date'] = ['Check-out must be after check-in.']
        else:
            if not origin:
                errors['origin'] = ['This field is required.']
            elif destination and origin.strip().lower() == destination.strip().lower():
                errors['destination'] = ['Destination must be different from origin.']
            if end and end < start:
                errors['end_date'] = ['Return date cannot be before the departure date.']

        if start < today:
            errors['start_date'] = ['Travel date cannot be in the past.']
        elif start > today + timedelta(days=settings.MAX_BOOKING_AHEAD_DAYS):
            errors['start_date'] = [f'You can only request travel up to {settings.MAX_BOOKING_AHEAD_DAYS} days ahead.']

        if end and start and (end - start).days > settings.MAX_TRIP_DAYS:
            errors.setdefault('end_date', [f'Trips longer than {settings.MAX_TRIP_DAYS} days are not allowed.'])

        if errors:
            raise serializers.ValidationError(errors)

        self._check_duplicate(service, destination, start, end)
        return data

    def _check_duplicate(self, service, destination, start, end):
        """Same employee, same service, same destination, overlapping dates, still active."""
        employee = self.instance.employee if self.instance else self.context['request'].user
        last = end or start
        clash = (
            TravelRequest.objects
            .filter(employee=employee, service=service, destination__iexact=destination,
                    status__in=TravelRequest.ACTIVE_STATUSES, start_date__lte=last)
            .filter(Q(end_date__gte=start) | Q(end_date__isnull=True, start_date__gte=start))
        )
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        existing = clash.first()
        if existing:
            raise serializers.ValidationError({'non_field_errors': [
                f'You already have an active {existing.get_service_display().lower()} request to '
                f'{existing.destination} for these dates ({existing.request_code}).'
            ]})
