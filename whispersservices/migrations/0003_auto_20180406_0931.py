# Generated by Django 2.0 on 2018-04-06 16:31

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('whispersservices', '0002_auto_20180328_1518'),
    ]

    operations = [
        migrations.RenameField(
            model_name='speciesdiagnosis',
            old_name='tested_cout',
            new_name='tested_count',
        ),
    ]
