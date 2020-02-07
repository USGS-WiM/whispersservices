from celery import shared_task
from whispersservices.serializers import *
from whispersservices.models import *
from whispersservices.immediate_tasks import generate_notification


@shared_task()
def all_events(events_created_yesterday, events_updated_yesterday):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='ALL Events').first()

    standard_notification_cues_new = NotificationCueStandard.objects.filter(
        standard_type__name='All', notification_cue_preference__create_when_new=True)
    for event in events_created_yesterday:
        for cue in standard_notification_cues_new:
            send_email = cue.notification_cue_preference.send_email
            recipients = [cue.created_by.id, ]
            email_to = [cue.created_by.email, ] if send_email else []

            eventlocations = EventLocation.objects.filter(event=event.id)
            event_location = "["
            for evtloc in eventlocations:
                event_location += evtloc.administrative_level_two.name
                event_location += ", " + evtloc.administrative_level_one.abbreviation
                event_location += ", " + evtloc.country.abbreviation + "; "
            event_location += "]"
            subject = msg_tmp.subject_template.format(event_id=event.id)
            body = msg_tmp.body_template.format(
                event_id=event.id, organization=event.created_by.organization.name, event_location=event_location,
                event_date=event.created_date, new_updated="New", created_updated="created", updates="N/A")
            source = event.created_by.username
            notifications.append((recipients, source, event.id, 'event', subject, body, send_email, email_to))
            # generate_notification.delay(recipients, source, event.id, 'event', subject, body, send_email, email_to)

    standard_notification_cues_updated = NotificationCueStandard.objects.filter(
        standard_type__name='All', notification_cue_preference__create_when_modified=True)
    for event in events_updated_yesterday:
        for cue in standard_notification_cues_updated:
            send_email = cue.notification_cue_preference.send_email
            recipients = [cue.created_by.id, ]
            email_to = [cue.created_by.email, ] if send_email else []

            eventlocations = EventLocation.objects.filter(event=event.id)
            event_location = "["
            for evtloc in eventlocations:
                event_location += evtloc.administrative_level_two.name
                event_location += ", " + evtloc.administrative_level_one.abbreviation
                event_location += ", " + evtloc.country.abbreviation + "; "
            event_location += "]"
            updates = ""
            subject = msg_tmp.subject_template.format(event_id=event.id)
            body = msg_tmp.body_template.format(
                event_id=event.id, organization=event.created_by.organization.name, event_location=event_location,
                event_date=event.modified_date, new_updated="Updated", created_updated="updated", updates=updates)
            source = event.modified_by.username
            notifications.append((recipients, source, event.id, 'event', subject, body, send_email, email_to))
            # generate_notification.delay(recipients, source, event.id, 'event', subject, body, send_email, email_to)

    return notifications


@shared_task()
def own_events(events_created_yesterday, events_updated_yesterday):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Your Events').first()

    standard_notification_cues_new = NotificationCueStandard.objects.filter(
        standard_type__name='Own', notification_cue_preference__create_when_new=True)
    for event in events_created_yesterday:
        for cue in standard_notification_cues_new:
            if cue.created_by.id == event.created_by.id:
                send_email = cue.notification_cue_preference.send_email
                recipients = [cue.created_by.id, ]
                email_to = [cue.created_by.email, ] if send_email else []

                subject = msg_tmp.subject_template.format(event_id=event.id)
                body = msg_tmp.body_template.format(
                    first_name=event.created_by.first_name, last_name=event.created_by.last_name,
                    created_updated="created", event_id=event.id, event_date=event.created_date, updates="N/A",
                    new_updated="New")
                source = event.created_by.username
                notifications.append((recipients, source, event.id, 'event', subject, body, send_email, email_to))
                # generate_notification.delay(recipients, source, event.id, 'event', subject, body, send_email, email_to)

    standard_notification_cues_updated = NotificationCueStandard.objects.filter(
        standard_type__name='Own', notification_cue_preference__create_when_modified=True)
    for event in events_updated_yesterday:
        for cue in standard_notification_cues_updated:
            if cue.created_by.id == event.created_by.id:
                send_email = cue.notification_cue_preference.send_email
                recipients = [cue.created_by.id, ]
                email_to = [cue.created_by.email, ] if send_email else []

                updates = ""
                subject = msg_tmp.subject_template.format(event_id=event.id)
                body = msg_tmp.body_template.format(
                    first_name=event.created_by.first_name, last_name=event.created_by.last_name,
                    created_updated="updated", event_id=event.id, event_date=event.created_date, updates=updates,
                    new_updated="Updated")
                source = event.modified_by.username
                notifications.append((recipients, source, event.id, 'event', subject, body, send_email, email_to))
                # generate_notification.delay(recipients, source, event.id, 'event', subject, body, send_email, email_to)

    return notifications


@shared_task()
def organization_events(events_created_yesterday, events_updated_yesterday):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Organization Events').first()

    standard_notification_cues_new = NotificationCueStandard.objects.filter(
        standard_type__name='Organization', notification_cue_preference__create_when_new=True)
    for event in events_created_yesterday:
        for cue in standard_notification_cues_new:
            if cue.created_by.organization.id == event.created_by.organization.id:
                send_email = cue.notification_cue_preference.send_email
                recipients = [cue.created_by.id, ]
                email_to = [cue.created_by.email, ] if send_email else []

                subject = msg_tmp.subject_template.format(event_id=event.id)
                body = msg_tmp.body_template.format(
                    first_name=event.created_by.first_name, last_name=event.created_by.last_name,
                    created_updated="created", event_id=event.id, event_date=event.created_date, updates="N/A",
                    new_updated="New")
                source = event.created_by.username
                notifications.append((recipients, source, event.id, 'event', subject, body, send_email, email_to))
                # generate_notification.delay(recipients, source, event.id, 'event', subject, body, send_email, email_to)

    standard_notification_cues_updated = NotificationCueStandard.objects.filter(
        standard_type__name='Organization', notification_cue_preference__create_when_modified=True)
    for event in events_updated_yesterday:
        for cue in standard_notification_cues_updated:
            if cue.created_by.organization.id == event.created_by.organization.id:
                send_email = cue.notification_cue_preference.send_email
                recipients = [cue.created_by.id, ]
                email_to = [cue.created_by.email, ] if send_email else []

                updates = ""
                subject = msg_tmp.subject_template.format(event_id=event.id)
                body = msg_tmp.body_template.format(
                    first_name=event.created_by.first_name, last_name=event.created_by.last_name,
                    created_updated="updated", event_id=event.id, event_date=event.created_date, updates=updates,
                    new_updated="Updated")
                source = event.modified_by.username
                notifications.append((recipients, source, event.id, 'event', subject, body, send_email, email_to))
                # generate_notification.delay(recipients, source, event.id, 'event', subject, body, send_email, email_to)

    return notifications


@shared_task()
def collaborator_events(events_created_yesterday, events_updated_yesterday):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Collaborator Events').first()

    standard_notification_cues_new = NotificationCueStandard.objects.filter(
        standard_type__name='Collaborator', notification_cue_preference__create_when_new=True)
    for event in events_created_yesterday:
        event_collaborator_ids = set(list(User.objects.filter(
            Q(eventwriteusers__event_id=event.id) |
            Q(eventreadusers__event_id=event.id)
        ).values_list('id', flat=True)))
        for cue in standard_notification_cues_new:
            if cue.created_by.id in event_collaborator_ids:
                send_email = cue.notification_cue_preference.send_email
                recipients = [cue.created_by.id, ]
                email_to = [cue.created_by.email, ] if send_email else []

                subject = msg_tmp.subject_template.format(event_id=event.id)
                body = msg_tmp.body_template.format(
                    first_name=event.created_by.first_name, last_name=event.created_by.last_name,
                    created_updated="created", event_id=event.id, event_date=event.created_date, updates="N/A",
                    new_updated="New")
                source = event.created_by.username
                notifications.append((recipients, source, event.id, 'event', subject, body, send_email, email_to))
                # generate_notification.delay(recipients, source, event.id, 'event', subject, body, send_email, email_to)

    standard_notification_cues_updated = NotificationCueStandard.objects.filter(
        standard_type__name='Collaborator', notification_cue_preference__create_when_modified=True)
    for event in events_updated_yesterday:
        event_collaborator_ids = set(list(User.objects.filter(
            Q(eventwriteusers__event_id=event.id) |
            Q(eventreadusers__event_id=event.id)
        ).values_list('id', flat=True)))
        for cue in standard_notification_cues_updated:
            if cue.created_by.id in event_collaborator_ids:
                send_email = cue.notification_cue_preference.send_email
                recipients = [cue.created_by.id, ]
                email_to = [cue.created_by.email, ] if send_email else []

                updates = ""
                subject = msg_tmp.subject_template.format(event_id=event.id)
                body = msg_tmp.body_template.format(
                    first_name=event.created_by.first_name, last_name=event.created_by.last_name,
                    created_updated="updated", event_id=event.id, event_date=event.created_date, updates=updates,
                    new_updated="Updated")
                source = event.modified_by.username
                notifications.append((recipients, source, event.id, 'event', subject, body, send_email, email_to))
                # generate_notification.delay(recipients, source, event.id, 'event', subject, body, send_email, email_to)

    return notifications


@shared_task()
def standard_notifications():
    yesterday = datetime.strftime(datetime.now() - timedelta(1), '%Y-%m-%d')
    new_events = Event.objects.filter(created_date=yesterday)
    updated_events = Event.objects.filter(modified_date=yesterday).exclude(created_date=yesterday)

    all_evts = all_events(events_created_yesterday=new_events, events_updated_yesterday=updated_events)
    own_evts = own_events(events_created_yesterday=new_events, events_updated_yesterday=updated_events)
    org_evts = organization_events(events_created_yesterday=new_events, events_updated_yesterday=updated_events)
    collab_evts = collaborator_events(events_created_yesterday=new_events, events_updated_yesterday=updated_events)

    all_notifications = all_evts + own_evts + org_evts + collab_evts
    unique_notifications = []

    for notification in all_notifications:
        if (notification[0], notification[2]) not in unique_notifications:
            unique_notifications.append((notification[0], notification[2]))
            generate_notification.delay(*notification)

    return True


@shared_task()
def stale_events():
    stale_event_periords = Configuration.objects.filter(name='stale_event_periods').first()
    if stale_event_periords and all(isinstance(x, int) for x in stale_event_periords):
        msg_tmp = NotificationMessageTemplate.objects.filter(name='Stale Events').first()
        for period in stale_event_periords:
            period_date = datetime.strftime(datetime.now() - timedelta(period), '%Y-%m-%d')
            all_stale_events = Event.objects.filter(complete=False, created_date=period_date)
            for event in all_stale_events:
                recipients = list(User.objects.filter(name='madisonepi').values_list('id', flat=True))
                recipients += [event.created_by.id, ]
                email_to = list(User.objects.filter(name='madisonepi').values_list('email', flat=True))
                email_to += [event.created_by.email, ]

                eventlocations = EventLocation.objects.filter(event=event.id)
                event_location = "["
                for evtloc in eventlocations:
                    event_location += evtloc.administrative_level_two.name
                    event_location += ", " + evtloc.administrative_level_one.abbreviation
                    event_location += ", " + evtloc.country.abbreviation + "; "
                event_location += "]"
                subject = msg_tmp.subject_template.format(event_id=event.id)
                body = msg_tmp.body_template.format(
                    event_id=event.id, event_location=event_location, event_date=event.created_date,
                    stale_period=str(period))
                source = 'system'
                generate_notification.delay(recipients, source, event.id, 'event', subject, body, True, email_to)
    return True


@shared_task()
def custom_notifications():
    # An event with a number affected greater than or equal to the provided integer is created,
    # OR an event location is added/updated that meets that criteria
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Custom Notification').first()
    yesterday = datetime.strftime(datetime.now() - timedelta(1), '%Y-%m-%d')

    custom_notification_cues_new = NotificationCueCustom.objects.filter(
        notification_cue_preference__create_when_new=True)
    for cue in custom_notification_cues_new:
        custom_criteria_events = []
        # TODO: critera
        #{"Values": [], "Operator": ""}
        # event
        if len(cue.event['values']) > 0:
            queryset = Event.objects.filter(created_date=yesterday)
            values = cue.event['values']
            if cue.event['operator'] == "OR":
                queries = [Q(id=value) for value in values]
                query = queries.pop()
                for item in queries:
                    query |= item
                queryset = queryset.filter(query)
            else:
                # default to AND
                # if there is more than one value, the query is pointless because there will never be a match
                for value in values:
                    queryset.filter(id=value)
        # event_affected_count
        # event_location_land_ownership
        # event_location_administrative_level_one
        # species
        # species_diagnosis_diagnosis

        for event in custom_criteria_events:
            send_email = cue.notification_cue_preference.send_email
            # recipients: users with this notification configured
            recipients = [cue.created_by.id, ]
            # email forwarding: Optional, set by user.
            email_to = [cue.created_by.email, ] if send_email else []

            field = ""
            criteria = ""
            subject = msg_tmp.subject_template.format(event_id=event.id)
            body = msg_tmp.body_template.format(
                new_updated="New", field=field, criteria=criteria, organization=event.created_by.organization.name,
                created_updated="created", event_id=event.id, event_date=event.created_date, updates="N/A")
            # source: any user who creates or updates an event that meets the trigger criteria
            source = event.created_by.username
            generate_notification.delay(recipients, source, event.id, 'event', subject, body, send_email, email_to)

    custom_notification_cues_updated = NotificationCueCustom.objects.filter(
        notification_cue_preference__create_when_modified=True)
    for cue in custom_notification_cues_updated:
        # TODO: critera
        custom_criteria_events = []
        for event in custom_criteria_events:
            send_email = cue.notification_cue_preference.send_email
            # recipients: users with this notification configured
            recipients = [cue.created_by.id, ]
            # email forwarding: Optional, set by user.
            email_to = [cue.created_by.email, ] if send_email else []

            field = ""
            criteria = ""
            updates = ""
            subject = msg_tmp.subject_template.format(event_id=event.id)
            body = msg_tmp.body_template.format(
                new_updated="Updated", field=field, criteria=criteria, organization=event.created_by.organization.name,
                created_updated="updated", event_id=event.id, event_date=event.created_date, updates=updates)
            # source: any user who creates or updates an event that meets the trigger criteria
            source = event.modified_by.username
            generate_notification.delay(recipients, source, event.id, 'event', subject, body, send_email, email_to)

    return True
