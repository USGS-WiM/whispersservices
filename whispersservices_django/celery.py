import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whispersservices_django.settings')

app = Celery('whispersservices_django')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'test_all_events': {
        'task': 'scheduled_tasks.all_events',
        # the following schedule is just for testing; normal schedule should be minute='0', hour='1'
        'schedule': 10.0  # crontab(minute='*', hour='*'),
    },
    # 'task-number-two': {
    #     'task': 'app2.tasks.task_number_two',
    #     'schedule': crontab(minute=0, hour='*/3,10-19'),
    #     'args': (*args)
    # }
}