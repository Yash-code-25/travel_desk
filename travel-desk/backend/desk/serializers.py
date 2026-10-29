import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from . import services
from .models import RequestEvent, TravelRequest, TripLeg

HOTEL = TravelRequest.Service.HOTEL
PHONE_RE = re.compile(r'^\+?[0-9 ()-]{7,20}$')


class EventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = RequestEvent
        fields = ['id', 'action', 'from_status', 'to_status', 'comment', 'actor_name', 'created_at']

    def get_actor_name(self, obj):
        return services.display_name(obj.actor)


class LegSerializer(serializers.ModelSerializer):
    """One flight / train / cab / hotel stay inside a trip."""
    service_label = serializers.CharField(source='get_service_display', read_only=True)
    origin = serializers.CharField(max_length=100, required=False, allow_blank=True)
    destination = serializers.CharField(max_length=100)
    end_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True)
    is_booked = serializers.BooleanField(read_only=True)
    has_ticket = serializers.SerializerMethodField()

    class Meta:
        model = TripLeg
        fields = ['id', 'position', 'service', 'service_label', 'origin', 'destination', 'date', 'end_date',
                  'notes', 'is_return', 'booking_reference', 'actual_cost', 'has_ticket', 'is_booked', 'booked_at']
        read_only_fields = ['id', 'position', 'booking_reference', 'actual_cost', 'booked_at']

    def get_has_ticket(self, obj):
        return bool(obj.ticket)


class TravelRequestListSerializer(serializers.ModelSerializer):
    """Small payload for tables: no history, no long text."""
    employee_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    route_summary = serializers.CharField(read_only=True)
    services = serializers.ListField(read_only=True)
    legs_count = serializers.SerializerMethodField()
    legs_booked = serializers.SerializerMethodField()
    is_overdue = serializers.BooleanField(read_only=True)
    needs_action = serializers.SerializerMethodField()

    class Meta:
        model = TravelRequest
        fields = [
            'id', 'request_code', 'status', 'status_label', 'employee_name',
            'traveller_name', 'traveller_is_requester', 'route_summary', 'services',
            'legs_count', 'legs_booked', 'start_date', 'end_date',
            'is_overdue', 'needs_action', 'created_at', 'updated_at',
        ]

    def get_employee_name(self, obj):
        return services.display_name(obj.employee)

    def get_legs_count(self, obj):
        return len(obj.legs.all())

    def get_legs_booked(self, obj):
        return sum(1 for leg in obj.legs.all() if leg.is_booked)

    def get_needs_action(self, obj):
        return services.needs_attention(self.context['request'].user, obj)


class TravelRequestSerializer(serializers.ModelSerializer):
    """Full detail: traveller, itinerary (legs), history and allowed actions. Also used for create/edit."""
    employee_name = serializers.SerializerMethodField()
    approver_name = serializers.SerializerMethodField()
    desk_agent_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    route_summary = serializers.CharField(read_only=True)
    services = serializers.ListField(read_only=True)
    total_actual_cost = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    allowed_actions = serializers.SerializerMethodField()
    events = EventSerializer(many=True, read_only=True)
    legs = LegSerializer(many=True)
    # Traveller: filled in automatically when the requester is travelling themselves.
    traveller_is_requester = serializers.BooleanField(default=True)
    traveller_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    traveller_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    traveller_email = serializers.EmailField(required=False, allow_blank=True)
    # Length caps on free text (stops giant payloads being stored).
    purpose = serializers.CharField(max_length=2000)
    preferences = serializers.CharField(max_length=500, required=False, allow_blank=True)

    class Meta:
        model = TravelRequest
        fields = [
            'id', 'request_code', 'status', 'status_label',
            'employee_name', 'approver_name', 'desk_agent_name',
            'traveller_is_requester', 'traveller_name', 'traveller_phone', 'traveller_email',
            'legs', 'route_summary', 'services', 'start_date', 'end_date',
            'purpose', 'preferences', 'estimated_cost', 'total_actual_cost',
            'is_overdue', 'submitted_at', 'created_at', 'updated_at',
            'allowed_actions', 'events',
        ]
        read_only_fields = ['request_code', 'status', 'start_date', 'end_date', 'submitted_at', 'created_at', 'updated_at']

    def get_employee_name(self, obj):
        return services.display_name(obj.employee)

    def get_approver_name(self, obj):
        return services.display_name(obj.approver) if obj.approver else ''

    def get_desk_agent_name(self, obj):
        return services.display_name(obj.desk_agent) if obj.desk_agent else ''

    def get_allowed_actions(self, obj):
        return services.allowed_actions(self.context['request'].user, obj)

    def validate_purpose(self, value):
        if len(value.strip()) < 10:
            raise serializers.ValidationError('Please describe the business purpose (at least 10 characters).')
        return value.strip()

    # ------------------------------------------------ whole-request checks
    def validate(self, data):
        requester = self.instance.employee if self.instance else self.context['request'].user
        self._check_traveller(data, requester)

        legs = data.get('legs')
        if legs is None and self.instance:  # edit without touching the itinerary
            first, last = self.instance.start_date, self.instance.last_date
        else:
            first, last = check_legs(legs or [])
        self._check_duplicate(requester, data.get('traveller_name') or self.instance.traveller_name, first, last)
        return data

    def _check_traveller(self, data, requester):
        is_requester = data.get('traveller_is_requester',
                                self.instance.traveller_is_requester if self.instance else True)
        if is_requester:
            data['traveller_name'] = services.display_name(requester)
            data['traveller_email'] = requester.email
            data['traveller_phone'] = services.profile_of(requester).phone
            return
        name = (data.get('traveller_name', self.instance.traveller_name if self.instance else '') or '').strip()
        phone = (data.get('traveller_phone') or '').strip()
        errors = {}
        if len(name) < 2:
            errors['traveller_name'] = ["Enter the traveller's full name."]
        if phone and not PHONE_RE.match(phone):
            errors['traveller_phone'] = ['Enter a valid phone number, e.g. +91 98765 43210.']
        if errors:
            raise serializers.ValidationError(errors)
        data['traveller_name'], data['traveller_phone'] = name, phone

    def _check_duplicate(self, requester, traveller, first, last):
        """Same traveller, overlapping dates, another trip still open -> probably a duplicate."""
        clash = (
            TravelRequest.objects
            .filter(employee=requester, traveller_name__iexact=traveller,
                    status__in=TravelRequest.ACTIVE_STATUSES, start_date__lte=last)
            .filter(Q(end_date__gte=first) | Q(end_date__isnull=True, start_date__gte=first))
        )
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        existing = clash.first()
        if existing:
            raise serializers.ValidationError({'non_field_errors': [
                f'{traveller} already has an open trip on these dates ({existing.request_code}).'
            ]})

    # ------------------------------------------------ saving with legs
    @transaction.atomic
    def create(self, validated):
        legs = validated.pop('legs')
        validated['start_date'], validated['end_date'] = trip_dates(legs)
        request = TravelRequest.objects.create(**validated)
        save_legs(request, legs)
        return request

    @transaction.atomic
    def update(self, request, validated):
        legs = validated.pop('legs', None)
        for field, value in validated.items():
            setattr(request, field, value)
        if legs is not None:
            for old in request.legs.all():  # the itinerary is replaced, old tickets go too
                if old.ticket:
                    old.ticket.delete(save=False)
            request.legs.all().delete()
            save_legs(request, legs)
            request.start_date, request.end_date = trip_dates(legs)
        request.save()
        return request


# ---------------------------------------------------------------- itinerary rules
def check_legs(legs):
    """Validate the itinerary. Returns (first_day, last_day) or raises errors per leg."""
    if not legs:
        raise serializers.ValidationError({'legs': ['Add at least one booking: flight, train, cab or hotel.']})
    if len(legs) > TravelRequest.MAX_LEGS:
        raise serializers.ValidationError({'legs': [f'A trip can have at most {TravelRequest.MAX_LEGS} bookings.']})

    today = timezone.localdate()
    furthest = today + timedelta(days=settings.MAX_BOOKING_AHEAD_DAYS)
    errors = [{} for _ in legs]

    for i, leg in enumerate(legs):
        e = errors[i]
        leg['origin'] = (leg.get('origin') or '').strip()
        leg['destination'] = leg['destination'].strip()
        if leg['service'] == HOTEL:
            leg['origin'], leg['is_return'] = '', False
            if not leg.get('end_date'):
                e['end_date'] = ['Check-out date is required.']
            elif leg['end_date'] <= leg['date']:
                e['end_date'] = ['Check-out must be after check-in.']
        else:
            leg['end_date'] = None
            if not leg['origin']:
                e['origin'] = ['Where does this journey start?']
            elif leg['origin'].lower() == leg['destination'].lower():
                e['destination'] = ['Destination must be different from the starting point.']
            if leg.get('is_return') and not any(l['service'] != HOTEL for l in legs[:i]):
                e['is_return'] = ['A return journey needs an outward journey before it.']

        if leg['date'] < today:
            e['date'] = ['This date is in the past.']
        elif leg['date'] > furthest:
            e['date'] = [f'You can only book up to {settings.MAX_BOOKING_AHEAD_DAYS} days ahead.']
        elif i > 0 and leg['date'] < legs[i - 1]['date']:
            e['date'] = [f'Must be on or after the previous booking ({legs[i - 1]["date"]:%d %b}). '
                         'Put the bookings in travel order.']

    if any(errors):
        raise serializers.ValidationError({'legs': errors})

    first, last = trip_dates(legs)
    if (last or first) - first > timedelta(days=settings.MAX_TRIP_DAYS):
        raise serializers.ValidationError({'non_field_errors': [
            f'Trips longer than {settings.MAX_TRIP_DAYS} days are not allowed.']})
    return first, last or first


def trip_dates(legs):
    first = min(leg['date'] for leg in legs)
    last = max(leg.get('end_date') or leg['date'] for leg in legs)
    return first, (last if last != first else None)


def save_legs(request, legs):
    TripLeg.objects.bulk_create([
        TripLeg(request=request, position=n, service=leg['service'], origin=leg.get('origin', ''),
                destination=leg['destination'], date=leg['date'], end_date=leg.get('end_date'),
                notes=leg.get('notes', ''), is_return=leg.get('is_return', False))
        for n, leg in enumerate(legs, start=1)
    ])
