# Generated by Django 2.1 on 2018-10-11 21:13

import datetime
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('whispersservices', '0015_auto_20181001_1524'),
    ]

    operations = [
        migrations.CreateModel(
            name='SpecimenSubmissionRequestResponse',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_date', models.DateField(blank=True, db_index=True, default=datetime.date.today, null=True)),
                ('modified_date', models.DateField(auto_now=True, null=True)),
                ('name', models.CharField(max_length=128, unique=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='specimensubmissionrequestresponse_creator', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='specimensubmissionrequestresponse_modifier', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'whispers_specimensubmissionrequestresponse',
            },
        ),
        migrations.CreateModel(
            name='SpecimenSubmissionRequestType',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_date', models.DateField(blank=True, db_index=True, default=datetime.date.today, null=True)),
                ('modified_date', models.DateField(auto_now=True, null=True)),
                ('name', models.CharField(max_length=128, unique=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='specimensubmissionrequesttype_creator', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='specimensubmissionrequesttype_modifier', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'whispers_specimensubmissionrequesttype',
            },
        ),
    ]