"""
Traveller details + multi-leg trips.

Existing requests are converted, nothing is lost:
  - traveller = the employee who raised the request
  - the single service becomes leg 1; a flight/train/cab with a return date gets a return leg 2
  - booking reference / cost / ticket move to leg 1
"""
import django.db.models.deletion
from django.db import migrations, models


def to_legs(apps, schema_editor):
    TravelRequest = apps.get_model('desk', 'TravelRequest')
    TripLeg = apps.get_model('desk', 'TripLeg')
    for req in TravelRequest.objects.select_related('employee'):
        emp = req.employee
        req.traveller_is_requester = True
        req.traveller_name = (f'{emp.first_name} {emp.last_name}'.strip() or emp.username)[:150]
        req.traveller_email = emp.email or ''
        req.save(update_fields=['traveller_is_requester', 'traveller_name', 'traveller_email'])

        booked = bool(req.booking_reference or req.ticket)
        is_hotel = req.service == 'HOTEL'
        TripLeg.objects.create(
            request=req, position=1, service=req.service, origin='' if is_hotel else req.origin,
            destination=req.destination, date=req.start_date, end_date=req.end_date if is_hotel else None,
            booking_reference=req.booking_reference, actual_cost=req.actual_cost, ticket=req.ticket.name or '',
            booked_at=req.updated_at if booked else None,
        )
        if not is_hotel and req.end_date:
            TripLeg.objects.create(
                request=req, position=2, service=req.service, origin=req.destination, destination=req.origin,
                date=req.end_date, is_return=True, booked_at=req.updated_at if booked else None,
                booking_reference=req.booking_reference,  # the old single booking covered both ways
            )


class Migration(migrations.Migration):

    dependencies = [
        ('desk', '0004_employee_details'),
    ]

    operations = [
        migrations.AddField(model_name='travelrequest', name='traveller_is_requester',
                            field=models.BooleanField(default=True)),
        migrations.AddField(model_name='travelrequest', name='traveller_name',
                            field=models.CharField(default='', max_length=150), preserve_default=False),
        migrations.AddField(model_name='travelrequest', name='traveller_phone',
                            field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name='travelrequest', name='traveller_email',
                            field=models.EmailField(blank=True, max_length=254)),
        migrations.CreateModel(
            name='TripLeg',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveSmallIntegerField()),
                ('service', models.CharField(choices=[('FLIGHT', 'Flight'), ('TRAIN', 'Train'), ('HOTEL', 'Hotel'), ('CAB', 'Cab')], max_length=10)),
                ('origin', models.CharField(blank=True, max_length=100)),
                ('destination', models.CharField(max_length=100)),
                ('date', models.DateField()),
                ('end_date', models.DateField(blank=True, null=True)),
                ('notes', models.CharField(blank=True, max_length=300)),
                ('is_return', models.BooleanField(default=False)),
                ('booking_reference', models.CharField(blank=True, max_length=50)),
                ('actual_cost', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('ticket', models.FileField(blank=True, upload_to='tickets/')),
                ('booked_at', models.DateTimeField(blank=True, null=True)),
                ('request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='legs', to='desk.travelrequest')),
            ],
            options={'ordering': ['position']},
        ),
        migrations.AddConstraint(
            model_name='tripleg',
            constraint=models.UniqueConstraint(fields=('request', 'position'), name='unique_leg_position'),
        ),
        migrations.RunPython(to_legs, migrations.RunPython.noop),
        migrations.RemoveField(model_name='travelrequest', name='service'),
        migrations.RemoveField(model_name='travelrequest', name='origin'),
        migrations.RemoveField(model_name='travelrequest', name='destination'),
        migrations.RemoveField(model_name='travelrequest', name='booking_reference'),
        migrations.RemoveField(model_name='travelrequest', name='actual_cost'),
        migrations.RemoveField(model_name='travelrequest', name='ticket'),
    ]
