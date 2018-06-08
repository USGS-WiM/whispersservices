# Generated by Django 2.0 on 2018-05-25 17:43

import datetime
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('whispersservices', '0014_administrativelevelone'),
    ]

    operations = [
        migrations.CreateModel(
            name='AdministrativeLevelLocality',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_date', models.DateField(blank=True, db_index=True, default=datetime.date.today, null=True)),
                ('modified_date', models.DateField(auto_now=True, null=True)),
                ('name', models.CharField(max_length=128, unique=True)),
                ('admin_level_one', models.CharField(blank=True, default='', max_length=128)),
                ('admin_level_two', models.CharField(blank=True, default='', max_length=128)),
                ('country', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='country', to='whispersservices.Country')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='administrativelevellocality_creator', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='administrativelevellocality_modifier', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'whispers_adminstrativelevellocality',
            },
        ),
        migrations.CreateModel(
            name='AdministrativeLevelTwo',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_date', models.DateField(blank=True, db_index=True, default=datetime.date.today, null=True)),
                ('modified_date', models.DateField(auto_now=True, null=True)),
                ('name', models.CharField(max_length=128)),
                ('points', models.TextField(blank=True, default='')),
                ('centroid_latitude', models.DecimalField(blank=True, decimal_places=10, max_digits=12, null=True)),
                ('centroid_longitude', models.DecimalField(blank=True, decimal_places=10, max_digits=13, null=True)),
                ('fips_code', models.CharField(blank=True, default='', max_length=128)),
                ('administrative_level_one', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='administrativelevelone', to='whispersservices.AdministrativeLevelOne')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='administrativeleveltwo_creator', to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='administrativeleveltwo_modifier', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'whispers_administrativeleveltwo',
            },
        ),
        migrations.AlterUniqueTogether(
            name='administrativeleveltwo',
            unique_together={('name', 'administrative_level_one')},
        ),
    ]