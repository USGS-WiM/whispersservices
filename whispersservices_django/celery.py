import os
from celery import Celery
# from celery.schedules import crontab
# from whispersservices.models import Configuration

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whispersservices_django.settings')

app = Celery('whispersservices_django')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# notifications_standard_hour = Configuration.objects.filter(name='notifications_standard_hour').first().value
# notifications_standard_minute = Configuration.objects.filter(name='notifications_standard_hour').first().value
# notifications_custom_hour = Configuration.objects.filter(name='notifications_custom_hour').first().value
# notifications_custom_minute = Configuration.objects.filter(name='notifications_custom_minute').first().value
#
# app.conf.beat_schedule = {
#     'nightly_standard_notifications': {
#         'task': 'whispersservices.scheduled_tasks.standard_notifications',
#         'schedule': crontab(minute=notifications_standard_minute, hour=notifications_standard_hour),
#     },
#     'nightly_custom_notifications': {
#         'task': 'whispersservices.scheduled_tasks.custom_notifications',
#         'schedule': crontab(minute=notifications_custom_minute, hour=notifications_custom_hour),
#     },
# }
