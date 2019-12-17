from celery import shared_task
from whispersservices.serializers import *
from whispersservices.models import *
from whispersservices.immediate_tasks import generate_notification


@shared_task()
def all_events():
    yesterday = datetime.strftime(datetime.now() - timedelta(1), '%Y-%m-%d')
    events_created_yesterday = Event.objects.filter(created_date=yesterday)
    standard_notification_cues_new = NotificationCueStandard.objects.filter(
        standard_type__name='ALL New Events', notification_cue_preference__create_when_new=True)
    for cue in standard_notification_cues_new:
        send_email = cue.notification_cue_preference.send_email
        for event in events_created_yesterday:
            recipients = [cue.created_by.id, ]
            email_to = [cue.created_by.email, ] if send_email else []
            msg_tmp = NotificationMessageTemplate.objects.filter(name='Event Created').first().message_template
            event_location = "["
            for evtloc in event.eventlocations:
                event_location += evtloc.administrative_level_two + ", " + evtloc.administrative_level_one + ", " + evtloc.country + "; "
            event_location += "]"
            message = msg_tmp.format(
                event_id=event.id, event_location=event_location, date=event.created_date,
                organization=event.created_by.organization.name)
            source = event.created_by.username
            generate_notification.delay(recipients, source, event.id, 'event', message, send_email, email_to)
    events_updated_yesterday = Event.objects.filter(modified_date=yesterday).exclude(created_date=yesterday)
    standard_notification_cues_updated = NotificationCueStandard.objects.filter(
        standard_type__name='ALL Updated Events', notification_cue_preference__create_when_modified=True)
    for cue in standard_notification_cues_updated:
        send_email = cue.notification_cue_preference.send_email
        for event in events_updated_yesterday:
            recipients = [cue.created_by.id, ]
            email_to = [cue.created_by.email, ] if send_email else []
            msg_tmp = NotificationMessageTemplate.objects.filter(name='Event Updated').first().message_template
            event_location = "["
            for evtloc in event.eventlocations:
                event_location += evtloc.administrative_level_two + ", " + evtloc.administrative_level_one + ", " + evtloc.country + "; "
            event_location += "]"
            updates = ""
            message = msg_tmp.format(
                event_id=event.id, event_location=event_location, date=event.modified_date,
                organization=event.modified_by.organization.name, updates=updates)
            source = event.modified_by.username
            generate_notification.delay(recipients, source, event.id, 'event', message, send_email, email_to)

    return True
