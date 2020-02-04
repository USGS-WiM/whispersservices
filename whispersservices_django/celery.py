import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whispersservices_django.settings')

app = Celery('whispersservices_django')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'nightly_standard_notifications': {
        'task': 'whispersservices.scheduled_tasks.standard_notifications',
        'schedule': crontab(minute='0', hour='1'),
    },
}