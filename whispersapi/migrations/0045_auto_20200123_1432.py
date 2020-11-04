# Generated by Django 2.2.9 on 2020-01-23 20:32

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('whispersapi', '0044_auto_20200122_1037'),
    ]

    operations = [
        migrations.AlterField(
            model_name='historicaluserchangerequest',
            name='request_response',
            field=models.ForeignKey(blank=True, db_constraint=False, default=4, help_text='A foreign key integer value identifying a response to this request', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='whispersapi.UserChangeRequestResponse'),
        ),
        migrations.AlterField(
            model_name='userchangerequest',
            name='request_response',
            field=models.ForeignKey(default=4, help_text='A foreign key integer value identifying a response to this request', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='userchangerequests', to='whispersapi.UserChangeRequestResponse'),
        ),
    ]