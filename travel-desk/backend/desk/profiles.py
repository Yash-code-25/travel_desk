"""
Travel profile: personal details, identity documents and travel preferences.
Filled in by the person after their first sign-in, then editable by them any time.

GET  /api/profile/                              my profile
PUT  /api/profile/                              save it (multipart: `data` = JSON, plus document files)
GET  /api/profiles/<user id>/                   someone's profile: themselves, Travel Desk or administrators
GET  /api/profiles/<user id>/files/<doc>/       download a document: aadhaar | pan | passport | visa-<id>

Managers never see these: they approve trips and costs, not personal documents.
"""
import json
import os
import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from . import services
from .countries import COUNTRY_SET, INDIA
from .models import FrequentFlyer, SecurityEvent, TravelProfile, TravelRequest, Visa
from .security import file_matches_extension, log_event

User = get_user_model()

PHONE_RE = re.compile(r'^\+?[0-9 ()-]{7,20}$')
PAN_RE = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]$')
PASSPORT_RE = re.compile(r'^[A-Z0-9]{6,9}$')
MEMBERSHIP_RE = re.compile(r'^[A-Z0-9-]{3,30}$')
LAST4_RE = re.compile(r'^[0-9]{4}$')
MAX_VISAS = 20
MAX_FREQUENT_FLYERS = 10
DOCUMENTS = {'aadhaar': 'aadhaar_file', 'pan': 'pan_file', 'passport': 'passport_file'}


def can_view(viewer, owner):
    """The person, administrators, Travel Managers, and an agent who is booking (or booked) a trip of theirs."""
    if viewer.pk == owner.pk or viewer.is_superuser or services.is_travel_manager(viewer):
        return True
    return services.is_desk(viewer) and TravelRequest.objects.filter(employee=owner, desk_agent=viewer).exists()


def profile_of(user):
    try:
        return user.travel_profile
    except TravelProfile.DoesNotExist:
        return TravelProfile(user=user)  # not saved: an empty form


# ---------------------------------------------------------------- reading
def profile_payload(user):
    p = profile_of(user)
    desk_profile = services.profile_of(user)
    base = f'/api/profiles/{user.pk}/files'
    visas = list(p.visas.all()) if p.pk else []
    flyers = list(p.frequent_flyers.all()) if p.pk else []
    return {
        'user_id': user.pk,
        'username': user.username,
        'email': user.email,
        'employee_id': desk_profile.employee_id,
        'role_label': 'Administrator' if user.is_superuser else desk_profile.get_role_display(),
        'manager_name': services.display_name(desk_profile.manager) if desk_profile.manager else '',
        'completed_at': desk_profile.profile_completed_at,
        'updated_at': p.updated_at if p.pk else None,
        # Basic information
        'first_name': user.first_name,
        'last_name': user.last_name,
        'phone': desk_profile.phone,
        'designation': desk_profile.designation,
        'department': desk_profile.department,
        'date_of_birth': p.date_of_birth,
        'gender': p.gender,
        'gender_label': p.get_gender_display(),
        'address': p.address,
        'emergency_contact_name': p.emergency_contact_name,
        'emergency_contact_phone': p.emergency_contact_phone,
        # Documents
        'aadhaar_last4': p.aadhaar_last4,
        'aadhaar_file': f'{base}/aadhaar/' if p.aadhaar_file else '',
        'pan_number': p.pan_number,
        'pan_file': f'{base}/pan/' if p.pan_file else '',
        'has_passport': p.has_passport,
        'passport_number': p.passport_number,
        'passport_place_of_issue': p.passport_place_of_issue,
        'passport_issue_date': p.passport_issue_date,
        'passport_expiry_date': p.passport_expiry_date,
        'passport_file': f'{base}/passport/' if p.passport_file else '',
        'visas': [{'id': v.id, 'country': v.country, 'visa_type': v.visa_type, 'expiry_date': v.expiry_date,
                   'file': f'{base}/visa-{v.id}/'} for v in visas],
        # Preferences
        'seat_preference': p.seat_preference,
        'seat_preference_label': p.get_seat_preference_display(),
        'meal_preference': p.meal_preference,
        'meal_preference_label': p.get_meal_preference_display(),
        'has_frequent_flyer': p.has_frequent_flyer,
        'frequent_flyers': [{'id': f.id, 'airline': f.airline, 'membership_number': f.membership_number}
                            for f in flyers],
        'has_forex_card': p.has_forex_card,
        'forex_bank': p.forex_bank,
        'forex_card_last4': p.forex_card_last4,
    }


# ---------------------------------------------------------------- input checks
def clean_phone(value):
    value = value.strip()
    if not PHONE_RE.match(value):
        raise serializers.ValidationError('Enter a valid phone number, e.g. +91 98765 43210.')
    return value


class VisaInput(serializers.Serializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    country = serializers.CharField(max_length=100)
    visa_type = serializers.CharField(max_length=100)
    expiry_date = serializers.DateField()

    def validate_expiry_date(self, v):
        if v < timezone.localdate():
            raise serializers.ValidationError('This visa has expired. Remove it from the list.')
        return v

    def validate_country(self, v):
        if v.strip() not in COUNTRY_SET:
            raise serializers.ValidationError('Choose the country from the list.')
        return v.strip()


class FrequentFlyerInput(serializers.Serializer):
    airline = serializers.CharField(max_length=100)
    membership_number = serializers.CharField(max_length=30)

    def validate_membership_number(self, v):
        v = v.strip().upper()
        if not MEMBERSHIP_RE.match(v):
            raise serializers.ValidationError('3-30 letters, numbers or dashes.')
        return v


class ProfileInput(serializers.Serializer):
    """Everything the form sends. Conditional sections (passport, frequent flyer, forex) are checked in validate()."""
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20)
    designation = serializers.CharField(max_length=100)
    department = serializers.CharField(max_length=100)
    date_of_birth = serializers.DateField()
    gender = serializers.ChoiceField(choices=TravelProfile.Gender.choices)
    address = serializers.CharField(max_length=500)
    emergency_contact_name = serializers.CharField(max_length=150)
    emergency_contact_phone = serializers.CharField(max_length=20)

    aadhaar_last4 = serializers.CharField(max_length=4)
    pan_number = serializers.CharField(max_length=10)
    has_passport = serializers.BooleanField(default=False)
    passport_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    passport_place_of_issue = serializers.CharField(max_length=100, required=False, allow_blank=True)
    passport_issue_date = serializers.DateField(required=False, allow_null=True)
    passport_expiry_date = serializers.DateField(required=False, allow_null=True)
    visas = VisaInput(many=True, required=False)

    seat_preference = serializers.ChoiceField(choices=TravelProfile.Seat.choices)
    meal_preference = serializers.ChoiceField(choices=TravelProfile.Meal.choices)
    has_frequent_flyer = serializers.BooleanField(default=False)
    frequent_flyers = FrequentFlyerInput(many=True, required=False)
    has_forex_card = serializers.BooleanField(default=False)
    forex_bank = serializers.CharField(max_length=100, required=False, allow_blank=True)
    forex_card_last4 = serializers.CharField(max_length=4, required=False, allow_blank=True)

    validate_phone = staticmethod(clean_phone)
    validate_emergency_contact_phone = staticmethod(clean_phone)

    def validate_date_of_birth(self, v):
        today = timezone.localdate()
        age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
        if not 16 <= age <= 100:
            raise serializers.ValidationError('Enter your real date of birth.')
        return v

    def validate_address(self, v):
        if len(v.strip()) < 10:
            raise serializers.ValidationError('Enter your full address.')
        return v.strip()

    def validate_aadhaar_last4(self, v):
        if not LAST4_RE.match(v.strip()):
            raise serializers.ValidationError('Enter the last 4 digits of your Aadhaar number.')
        return v.strip()

    def validate_pan_number(self, v):
        v = v.strip().upper()
        if not PAN_RE.match(v):
            raise serializers.ValidationError('Enter a valid PAN, e.g. ABCDE1234F.')
        if TravelProfile.objects.filter(pan_number=v).exclude(user=self.context['user']).exists():
            raise serializers.ValidationError('Another account already uses this PAN.')
        return v

    def validate(self, data):
        for field in ('first_name', 'last_name', 'designation', 'department', 'emergency_contact_name'):
            data[field] = data[field].strip()
        errors = {}
        today = timezone.localdate()

        if data['has_passport']:
            number = (data.get('passport_number') or '').strip().upper()
            issued, expires = data.get('passport_issue_date'), data.get('passport_expiry_date')
            if not PASSPORT_RE.match(number):
                errors['passport_number'] = ['Enter the passport number (6-9 letters and numbers).']
            if not (data.get('passport_place_of_issue') or '').strip():
                errors['passport_place_of_issue'] = ['Enter the place of issue.']
            if not issued or issued > today:
                errors['passport_issue_date'] = ['Enter the date of issue.']
            if not expires:
                errors['passport_expiry_date'] = ['Enter the expiry date.']
            elif expires <= today:
                errors['passport_expiry_date'] = ['This passport has expired.']
            elif issued and expires <= issued:
                errors['passport_expiry_date'] = ['Expiry must be after the date of issue.']
            data['passport_number'] = number
        else:  # no passport: nothing passport-related is kept
            data.update(passport_number='', passport_place_of_issue='', passport_issue_date=None,
                        passport_expiry_date=None)
        if len(data.get('visas') or []) > MAX_VISAS:
            errors['visas'] = [f'At most {MAX_VISAS} visas.']

        if data['has_frequent_flyer']:
            flyers = data.get('frequent_flyers') or []
            if not flyers:
                errors['frequent_flyers'] = ['Add your airline and membership number.']
            elif len(flyers) > MAX_FREQUENT_FLYERS:
                errors['frequent_flyers'] = [f'At most {MAX_FREQUENT_FLYERS} memberships.']
        else:
            data['frequent_flyers'] = []

        if data['has_forex_card']:
            if not (data.get('forex_bank') or '').strip():
                errors['forex_bank'] = ['Enter the bank that issued the card.']
            if not LAST4_RE.match((data.get('forex_card_last4') or '').strip()):
                errors['forex_card_last4'] = ['Enter the last 4 digits of the card.']
        else:
            data.update(forex_bank='', forex_card_last4='')

        if errors:
            raise serializers.ValidationError(errors)
        return data


def document_error(upload, user):
    """Same rules as tickets: PDF/PNG/JPG, size limit, contents must match the file name."""
    ext = os.path.splitext(upload.name)[1].lower()
    if ext not in settings.ALLOWED_TICKET_EXTENSIONS:
        return 'Only PDF, PNG or JPG files are allowed.'
    if upload.size > settings.MAX_TICKET_SIZE_MB * 1024 * 1024:
        return f'File is too large (max {settings.MAX_TICKET_SIZE_MB} MB).'
    if upload.size == 0:
        return 'The file is empty.'
    if not file_matches_extension(upload, ext):
        log_event(SecurityEvent.Type.UPLOAD_REJECTED, user=user,
                  detail=f'Profile document "{upload.name[:80]}" content does not match {ext}')
        return 'This file is not a real PDF/PNG/JPG (its contents do not match its name).'
    return ''


# ---------------------------------------------------------------- saving
def save_profile(user, raw, files):
    try:
        data = json.loads(raw or '{}')
    except (TypeError, ValueError):
        raise ValidationError({'detail': 'Invalid form data.'})
    form = ProfileInput(data=data, context={'user': user})
    form.is_valid(raise_exception=True)
    data = form.validated_data

    p = profile_of(user)
    errors = {}

    def take_file(field, upload, required, label):
        """A new upload replaces the stored copy; without one the stored copy stays."""
        if upload is None:
            if required:
                errors[field] = [f'Upload a copy of your {label}.']
            return None
        problem = document_error(upload, user)
        if problem:
            errors[field] = [problem]
        return upload

    aadhaar = take_file('aadhaar_file', files.get('aadhaar_file'), not p.aadhaar_file, 'masked Aadhaar')
    pan = take_file('pan_file', files.get('pan_file'), not p.pan_file, 'PAN card')
    passport = take_file('passport_file', files.get('passport_file'),
                         data['has_passport'] and not p.passport_file, 'passport') if data['has_passport'] else None

    existing_visas = {v.id: v for v in p.visas.all()} if p.pk else {}
    visa_rows, visa_errors = [], []
    for n, v in enumerate(data.get('visas') or []):
        old = existing_visas.get(v.get('id'))
        upload = files.get(f'visa_file_{n}')
        problem = document_error(upload, user) if upload else ('' if old else 'Upload a copy of this visa.')
        visa_errors.append({'file': [problem]} if problem else {})
        visa_rows.append((old, v, upload))
    if any(visa_errors):
        errors['visas'] = visa_errors
    if errors:
        raise ValidationError(errors)

    replaced = []  # old files removed only after the save has been committed

    with transaction.atomic():
        user.first_name, user.last_name = data['first_name'], data['last_name']
        user.save(update_fields=['first_name', 'last_name'])
        desk_profile = services.profile_of(user)
        desk_profile.phone, desk_profile.designation = data['phone'], data['designation']
        desk_profile.department = data['department']
        desk_profile.profile_completed_at = desk_profile.profile_completed_at or timezone.now()
        desk_profile.save(update_fields=['phone', 'designation', 'department', 'profile_completed_at'])

        for field in ('date_of_birth', 'gender', 'address', 'emergency_contact_name', 'emergency_contact_phone',
                      'aadhaar_last4', 'pan_number', 'has_passport', 'passport_number', 'passport_place_of_issue',
                      'passport_issue_date', 'passport_expiry_date', 'seat_preference', 'meal_preference',
                      'has_frequent_flyer', 'has_forex_card', 'forex_bank', 'forex_card_last4'):
            setattr(p, field, data[field])
        for field, upload in (('aadhaar_file', aadhaar), ('pan_file', pan), ('passport_file', passport)):
            if upload is not None:
                if getattr(p, field):
                    replaced.append(getattr(p, field).name)
                setattr(p, field, upload)
        if not data['has_passport'] and p.passport_file:
            replaced.append(p.passport_file.name)
            p.passport_file = ''
        p.save()

        kept = set()
        for old, v, upload in visa_rows:
            visa = old or Visa(profile=p)
            visa.country, visa.visa_type, visa.expiry_date = v['country'].strip(), v['visa_type'].strip(), v['expiry_date']
            if upload is not None:
                if visa.file:
                    replaced.append(visa.file.name)
                visa.file = upload
            visa.save()
            kept.add(visa.pk)
        for visa in existing_visas.values():
            if visa.pk not in kept:
                replaced.append(visa.file.name)
                visa.delete()

        p.frequent_flyers.all().delete()
        FrequentFlyer.objects.bulk_create([
            FrequentFlyer(profile=p, airline=f['airline'].strip(), membership_number=f['membership_number'])
            for f in data['frequent_flyers']
        ])

        storage = TravelProfile._meta.get_field('aadhaar_file').storage
        transaction.on_commit(lambda: [storage.delete(name) for name in replaced if name])

    return user


# ---------------------------------------------------------------- views
@api_view(['GET', 'PUT'])
def my_profile(request):
    user = request.user
    if request.method == 'PUT':
        user = save_profile(user, request.data.get('data'), request.FILES)
        user = User.objects.select_related('profile__manager').get(pk=user.pk)
    return Response(profile_payload(user))


def _owner(request, user_id):
    owner = get_object_or_404(User.objects.select_related('profile__manager'), pk=user_id)
    if not can_view(request.user, owner):
        raise PermissionDenied('Only the Travel Desk and administrators can see other people\'s profiles.')
    return owner


@api_view(['GET'])
def profile_detail(request, user_id):
    return Response(profile_payload(_owner(request, user_id)))


@api_view(['GET'])
def profile_file(request, user_id, doc):
    p = profile_of(_owner(request, user_id))
    if doc in DOCUMENTS:
        f = getattr(p, DOCUMENTS[doc]) if p.pk else None
    elif doc.startswith('visa-') and doc[5:].isdigit() and p.pk:
        visa = p.visas.filter(pk=int(doc[5:])).first()
        f = visa.file if visa else None
    else:
        f = None
    if not f:
        raise Http404('No document uploaded.')
    ext = os.path.splitext(f.name)[1].lower()
    name = f'{p.user.username}-{doc}{ext}'
    return FileResponse(f.open('rb'), as_attachment=True, filename=name)


# ---------------------------------------------------------------- travel requests
PASSPORT_VALID_DAYS_AFTER_TRIP = 183  # most countries want 6 months of passport validity after the trip


def trip_snapshot(user, trip_type, legs, last_day, forex_needed=False):
    """What the Travel Desk needs from the profile, copied onto the request at submit.
    International trips also need a valid passport (else 400); a missing visa is only flagged for the desk."""
    p = profile_of(user)
    flyers = list(p.frequent_flyers.all()) if p.pk else []
    snap = {
        'seat': p.get_seat_preference_display(),
        'meal': p.get_meal_preference_display(),
        'frequent_flyers': [f'{f.airline}: {f.membership_number}' for f in flyers],
    }
    if trip_type != TravelRequest.TripType.INTERNATIONAL:
        return snap

    if not (p.pk and p.has_passport and p.passport_expiry_date):
        raise ValidationError({'non_field_errors': [
            'International trips need a passport. Add your passport in My profile, then submit again.']})
    needed_until = last_day + timedelta(days=PASSPORT_VALID_DAYS_AFTER_TRIP)
    if p.passport_expiry_date < needed_until:
        raise ValidationError({'non_field_errors': [
            f'Your passport expires on {p.passport_expiry_date:%d %b %Y}. It must be valid for 6 months after the '
            f'trip (until {needed_until:%d %b %Y}). Renew it and update My profile first.']})

    abroad = []
    for leg in legs:
        for country in (leg.get('origin_country'), leg.get('destination_country')):
            if country and country != INDIA and country not in abroad:
                abroad.append(country)
    visas = {v.country: v for v in p.visas.all() if v.expiry_date >= last_day}
    snap.update(
        passport={'number': p.passport_number, 'place_of_issue': p.passport_place_of_issue,
                  'expiry_date': p.passport_expiry_date.isoformat()},
        countries=abroad,
        visas=[{'country': c, 'visa_type': visas[c].visa_type, 'expiry_date': visas[c].expiry_date.isoformat()}
               for c in abroad if c in visas],
        visa_needed=[c for c in abroad if c not in visas],
        forex={'bank': p.forex_bank, 'card_last4': p.forex_card_last4} if p.has_forex_card else None,
        forex_needed=bool(forex_needed) and not p.has_forex_card,
    )
    return snap
