from celery import shared_task
from django.db.models import Count
from whispersservices.serializers import *
from whispersservices.models import *
from whispersservices.immediate_tasks import generate_notification


def get_create_info(history_record, model_name):
    model = " ".join([part.capitalize() for part in model_name.split('_')])
    if model_name == 'event_comment':
        details = "<br />An {} was created: {}".format(model, history_record.comment)
    elif model_name == 'event_diagnosis':
        details = "<br />An {} was created: {}".format(model, history_record.diagnosis.name)
    elif model_name == 'event_group':
        details = "<br />Event was added to {} {}".format(model, history_record.eventgroup.name)
    elif model_name == 'event_group_comment':
        details = "<br />An {} was created: {}".format(model, history_record.comment)
    elif model_name == 'event_organization':
        details = "<br />An Event Organization was assigned: {}".format(history_record.organization.name)
    elif model_name == 'event_contact':
        name = history_record.contact.first_name + " " + history_record.contact.last_name
        details = "<br />An Event Location Contact was assigned: {}".format(name)
    elif model_name == 'event_location':
        details = "<br />An {} was created: {}".format(model, history_record.name)
    elif model_name == 'event_location_comment':
        details = "<br />An {} was created: {}".format(model, history_record.comment)
    elif model_name == 'event_location_contact':
        name = history_record.contact.first_name + " " + history_record.contact.last_name
        details = "<br />An Event Location Contact was assigned: {}".format(name)
    elif model_name == 'event_location_flyway':
        details = "<br />An Event Location was put in flyway {}".format(history_record.flyway.name)
    elif model_name == 'location_species':
        details = "<br />A {} was created: {}".format(model, history_record.species.name)
    elif model_name == 'species_diagnosis':
        details = "<br />A {} was created: {}".format(model, history_record.diagnosis.name)
    elif model_name == 'species_diagnosis_organization':
        details = "<br />A Species Diagnosis Organization was assigned: {}".format(history_record.organization.name)
    else:
        details = "<br />A new {} was created".format(model_name)
    return details


def get_changes(obj, source_id, yesterday, model_name, source_type, cue_user):
    yesterday_date = datetime.strptime(yesterday, '%Y-%m-%d').date()
    changes = ""

    # grab all history for this event from yesterday ...
    history = obj.history.order_by('-history_id')
    if len(history) == 0:
        # no history records for the model, so ignore
        pass
    elif len(history) == 1:
        # only one history record for the model
        h = history[0]
        # only include creates made yesterday by the source user (or org)
        #  (a single history record can only ever be a create, but better to be safe by being explicit)
        h_id = h.history_user.id if source_type == 'user' else h.history_user.organization.id
        if h.history_date.date() == yesterday_date and h_id == source_id and h.history_type == '+':
            changes += get_create_info(h, model_name)
    else:
        # more than one history record for the model
        for h in history:
            # only include changes made yesterday
            if not h.history_date.date() == yesterday_date:
                # no changes from yesterday found, so exit the loop
                break
            else:
                # only include changes made by this particular updater (source)
                h_id = h.history_user.id if source_type == 'user' else h.history_user.organization.id
                if not h_id == source_id:
                    # keep the loop going in case changes made by this updater are interspersed among other changes
                    continue
                else:
                    # process object creates differently, since there is no earlier record to diff against for changes
                    if h.history_type == '+':
                        changes += get_create_info(h, model_name)
                    else:
                        delta = h.diff_against(h.prev_record)
                        for change in delta.changes:
                            fld = change.field

                            # ignore automatically calculated fields (non-editable by user)
                            if fld in ['priority', 'created_by', 'modified_by', 'created_date', 'modified_date',
                                       'id', 'event', 'event_location', 'location_species', 'species_diagnosis']:
                                continue
                            # substitute related object names for foreign key IDs
                            elif model_name == 'event':
                                # but also ignore automatically calculated fields (non-editable by user)
                                if fld in ['start_date', 'end_date', 'affected_count']:
                                    continue
                                elif fld == 'event_type':
                                    change.new = EventType.objects.get(id=change.new) if change.new else change.new
                                    change.old = EventType.objects.get(id=change.old) if change.old else change.old
                                elif fld == 'event_reference':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == obj.created_by.id
                                            or cue_user.organization.id == obj.created_by.organization.id
                                            or cue_user.organization.id in obj.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[obj.id]) | Q(readevents__in=[obj.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                elif fld == 'staff':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == obj.created_by.id
                                            or cue_user.organization.id == obj.created_by.organization.id
                                            or cue_user.organization.id in obj.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[obj.id]) | Q(readevents__in=[obj.id])
                                            ).values_list('id', flat=True))):
                                        change.new = Staff.objects.get(id=change.new) if change.new else change.new
                                        change.old = Staff.objects.get(id=change.old) if change.old else change.old
                                    else:
                                        continue
                                elif fld == 'event_status':
                                    # check permissions (visible to NWHC only!)
                                    if cue_user.role.is_superadmin or cue_user.role.is_admin:
                                        chg = change
                                        change.new = EventStatus.objects.get(id=chg.new) if chg.new else chg.new
                                        change.old = EventStatus.objects.get(id=chg.old) if chg.old else chg.old
                                    else:
                                        continue
                                elif fld == 'quality_check':
                                    # check permissions (visible to NWHC only!)
                                    if cue_user.role.is_superadmin or cue_user.role.is_admin:
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                elif fld == 'legal_status':
                                    # check permissions (visible to NWHC only!)
                                    if cue_user.role.is_superadmin or cue_user.role.is_admin:
                                        chg = change
                                        change.new = LegalStatus.objects.get(id=chg.new) if chg.new else chg.new
                                        change.old = LegalStatus.objects.get(id=chg.old) if chg.old else chg.old
                                    else:
                                        continue
                                elif fld == 'legal_number':
                                    # check permissions (visible to NWHC only!)
                                    if cue_user.role.is_superadmin or cue_user.role.is_admin:
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                            elif model_name == 'event_location':
                                if fld == 'name':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == obj.created_by.id
                                            or cue_user.organization.id == obj.created_by.organization.id
                                            or cue_user.organization.id in obj.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[obj.event.id]) | Q(readevents__in=[obj.event.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                if fld == 'country':
                                    change.new = Country.objects.get(id=change.new) if change.new else change.new
                                    change.old = Country.objects.get(id=change.old) if change.old else change.old
                                elif fld == 'administrative_level_one':
                                    chg = change
                                    change.new = AdministrativeLevelOne.objects.get(id=chg.new) if chg.new else chg.new
                                    change.old = AdministrativeLevelOne.objects.get(id=chg.old) if chg.old else chg.old
                                    # substitute locality name if applicable
                                    locality = AdministrativeLevelLocality.objects.filter(country=obj.country).first()
                                    if locality and locality.admin_level_one_name:
                                        change.field = locality.admin_level_one_name
                                elif fld == 'administrative_level_two':
                                    chg = change
                                    change.new = AdministrativeLevelTwo.objects.get(id=chg.new) if chg.new else chg.new
                                    change.old = AdministrativeLevelTwo.objects.get(id=chg.old) if chg.old else chg.old
                                    # substitute locality name if applicable
                                    locality = AdministrativeLevelLocality.objects.filter(country=obj.country).first()
                                    if locality and locality.admin_level_two_name:
                                        change.field = locality.admin_level_two_name
                                if fld == 'latitude':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == obj.created_by.id
                                            or cue_user.organization.id == obj.created_by.organization.id
                                            or cue_user.organization.id in obj.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[obj.event.id]) | Q(readevents__in=[obj.event.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                if fld == 'longitude':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == obj.created_by.id
                                            or cue_user.organization.id == obj.created_by.organization.id
                                            or cue_user.organization.id in obj.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[obj.event.id]) | Q(readevents__in=[obj.event.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                elif fld == 'land_ownership':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == obj.created_by.id
                                            or cue_user.organization.id == obj.created_by.organization.id
                                            or cue_user.organization.id in obj.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[obj.event.id]) | Q(readevents__in=[obj.event.id])
                                            ).values_list('id', flat=True))):
                                        chg = change
                                        change.new = LandOwnership.objects.get(id=chg.new) if chg.new else chg.new
                                        change.old = LandOwnership.objects.get(id=chg.old) if chg.old else chg.old
                                    else:
                                        continue
                                if fld == 'gnis_name':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == obj.created_by.id
                                            or cue_user.organization.id == obj.created_by.organization.id
                                            or cue_user.organization.id in obj.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[obj.event.id]) | Q(readevents__in=[obj.event.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                if fld == 'gnis_id':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == obj.created_by.id
                                            or cue_user.organization.id == obj.created_by.organization.id
                                            or cue_user.organization.id in obj.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[obj.event.id]) | Q(readevents__in=[obj.event.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                            elif model_name == 'location_species':
                                if fld == 'species':
                                    change.new = Species.objects.get(id=change.new) if change.new else change.new
                                    change.old = Species.objects.get(id=change.old) if change.old else change.old
                                elif fld == 'age_bias':
                                    change.new = AgeBias.objects.get(id=change.new) if change.new else change.new
                                    change.old = AgeBias.objects.get(id=change.old) if change.old else change.old
                                elif fld == 'sex_bias':
                                    change.new = SexBias.objects.get(id=change.new) if change.new else change.new
                                    change.old = SexBias.objects.get(id=change.old) if change.old else change.old
                            elif model_name == 'species_diagnosis':
                                if fld == 'diagnosis':
                                    change.new = Diagnosis.objects.get(id=change.new) if change.new else change.new
                                    change.old = Diagnosis.objects.get(id=change.old) if change.old else change.old
                                if fld == 'cause':
                                    change.new = DiagnosisCause.objects.get(id=change.new) if change.new else change.new
                                    change.old = DiagnosisCause.objects.get(id=change.old) if change.old else change.old
                                if fld == 'basis':
                                    change.new = DiagnosisBasis.objects.get(id=change.new) if change.new else change.new
                                    change.old = DiagnosisBasis.objects.get(id=change.old) if change.old else change.old

                            # substitute a two double quotation marks for empty string to avoid confusing the recipient
                            # (an empty string in the notification or email looks like the value is missing,
                            # not like what the value actually is (a string without content),
                            # and might make them think that there is a bug in the code)
                            change.new = "\"\"" if change.new == '' else change.new
                            change.old = "\"\"" if change.old == '' else change.old

                            # format the change into an update string item
                            model = " ".join([part.capitalize() for part in model_name.split('_')])
                            field = change.field.replace('_', ' ')
                            changes += "<br />{} {} changed from {} to {}".format(model, field, change.old, change.new)

    return changes


def get_updates(event, source_id, yesterday, source_type, cue_user):
    # get changes from the event and its children (event comments, event diagnoses, event event groups,
    #  event event group comments, event locations, event location comments, event location contacts,
    #  event location flyways, location species, species diagnoses, species diagnosis organizations)
    updates = ""

    # event
    updates += get_changes(event, source_id, yesterday, 'event', source_type, cue_user)

    # event comments
    event_content_type = ContentType.objects.filter(model='event').first()
    for event_comment in Comment.objects.filter(
            object_id=event.id, content_type=event_content_type.id,
            modified_date=event.modified_date).order_by('-id'):
        updates += get_changes(event_comment, source_id, yesterday, 'event_comment', source_type, cue_user)

    # event diagnoses
    for event_diagnosis in EventDiagnosis.objects.filter(event=event.id).order_by('-id'):
        updates += get_changes(event_diagnosis, source_id, yesterday, 'event_diagnosis', source_type, cue_user)

    # event event groups
    for event_group in EventEventGroup.objects.filter(event=event.id).order_by('-id'):
        updates += get_changes(event_group, source_id, yesterday, 'event_group', source_type, cue_user)

        # event event group comments
        event_group_content_type = ContentType.objects.filter(model='eventeventgroup').first()
        for event_group_comment in Comment.objects.filter(
                object_id=event.id, content_type=event_group_content_type.id,
                modified_date=event.modified_date).order_by('-id'):
            updates += get_changes(
                event_group_comment, source_id, yesterday, 'event_group_comment', source_type, cue_user)

    # event organizations
    for event_organization in EventOrganization.objects.filter(event=event.id).order_by('-id'):
        updates += get_changes(event_organization, source_id, yesterday, 'event_organization', source_type, cue_user)

    # event contacts
    for event_contact in EventContact.objects.filter(event=event.id).order_by('-id'):
        updates += get_changes(event_contact, source_id, yesterday, 'event_contact', source_type, cue_user)

    # event locations
    for event_location in EventLocation.objects.filter(event=event.id).order_by('-id'):
        updates += get_changes(event_location, source_id, yesterday, 'event_location', source_type, cue_user)

        # event location comments
        event_location_content_type = ContentType.objects.filter(model='eventlocation').first()
        for event_location_comment in Comment.objects.filter(
                object_id=event.id, content_type=event_location_content_type.id,
                modified_date=event.modified_date).order_by('-id'):
            updates += get_changes(
                event_location_comment, source_id, yesterday, 'event_location_comment', source_type, cue_user)

        # event location contacts
        for event_location_contact in EventLocationContact.objects.filter(
                event_location=event_location.id).order_by('-id'):
            updates += get_changes(
                event_location_contact, source_id, yesterday, 'event_location_contact', source_type, cue_user)

        # event location flyways
        for event_location_flyway in EventLocationFlyway.objects.filter(
                event_location=event_location.id).order_by('-id'):
            updates += get_changes(
                event_location_flyway, source_id, yesterday, 'event_location_flyway', source_type, cue_user)

        # location species
        for location_species in LocationSpecies.objects.filter(event_location=event_location.id).order_by('-id'):
            updates += get_changes(location_species, source_id, yesterday, 'location_species', source_type, cue_user)

            # species diagnoses
            for species_diagnosis in SpeciesDiagnosis.objects.filter(
                    location_species=location_species.id).order_by('-id'):
                updates += get_changes(
                    species_diagnosis, source_id, yesterday, 'species_diagnosis', source_type, cue_user)

                # species diagnosis organizations
                for species_diagnosis_organization in SpeciesDiagnosisOrganization.objects.filter(
                        species_diagnosis=species_diagnosis.id).order_by('-id'):
                    updates += get_changes(species_diagnosis_organization, source_id, yesterday,
                                           'species_diagnosis_organization', source_type, cue_user)

    return updates


def get_notification_details(cue, event, msg_tmp, updates, source):
    send_email = cue.notification_cue_preference.send_email
    recipients = [cue.created_by.id, ]
    email_to = [cue.created_by.email, ] if send_email else []

    if updates == "N/A":
        new_updated = "New"
        created_updated = 'created'
        event_date = event.created_date
        first_name = event.created_by.first_name
        last_name = event.created_by.last_name
        org = event.created_by.organization.name
    else:
        new_updated = "Updated"
        created_updated = 'updated'
        event_date = event.modified_date
        first_name = event.modified_by.first_name
        last_name = event.modified_by.last_name
        org = event.modified_by.organization.name

    subject = msg_tmp.subject_template.format(event_id=event.id)
    body = msg_tmp.body_template.format(
        first_name=first_name, last_name=last_name, created_updated=created_updated,
        event_id=event.id, event_date=event_date, updates=updates, new_updated=new_updated)

    return [recipients, source, event.id, 'event', subject, body, send_email, email_to, org]


@shared_task()
def own_events(events_created_yesterday, events_updated_yesterday, yesterday):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Your Events').first()

    standard_notification_cues_new = NotificationCueStandard.objects.filter(
        standard_type__name='Own', notification_cue_preference__create_when_new=True)
    for event in events_created_yesterday:
        for cue in standard_notification_cues_new:
            if cue.created_by.id == event.created_by.id:
                source = event.created_by.username
                updates = "N/A"
                notifications.append(get_notification_details(cue, event, msg_tmp, updates, source))

    standard_notification_cues_updated = NotificationCueStandard.objects.filter(
        standard_type__name='Own', notification_cue_preference__create_when_modified=True)
    for event in events_updated_yesterday:
        # Create one notification per distinct updater (not including the creator)
        # django_simple_history.history_type: + for create, ~ for update, and - for delete
        event_updaters = list(set(
            Event.history.filter(id=event.id, modified_date=yesterday
                                 ).exclude(history_type='+', modified_by=event.created_by.id
                                           ).values_list('modified_by__username', 'modified_by__id')))
        # only create notifications if there were truly updates and not just creates (exclude history_type='+')
        if event_updaters:
            for cue in standard_notification_cues_updated:
                if cue.created_by.id == event.created_by.id:
                    for event_updater in event_updaters:
                        source = event_updater[0]
                        source_id = event_updater[1]
                        updates = get_updates(event, source_id, yesterday, 'user', cue.created_by)

                        # only create notifications if there are update details (non-empty string)
                        if updates:
                            notifications.append(get_notification_details(cue, event, msg_tmp, updates, source))

    return notifications


@shared_task()
def organization_events(events_created_yesterday, events_updated_yesterday, yesterday):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Organization Events').first()

    standard_notification_cues_new = NotificationCueStandard.objects.filter(
        standard_type__name='Organization', notification_cue_preference__create_when_new=True)
    for event in events_created_yesterday:
        for cue in standard_notification_cues_new:
            if (cue.created_by.organization.id == event.created_by.organization.id
                    or cue.created_by.organization.id in event.created_by.organization.parent_organizations):
                source = event.created_by.username
                updates = "N/A"
                notifications.append(get_notification_details(cue, event, msg_tmp, updates, source))

    standard_notification_cues_updated = NotificationCueStandard.objects.filter(
        standard_type__name='Organization', notification_cue_preference__create_when_modified=True)
    for event in events_updated_yesterday:
        # Create one notification per distinct updater (not including the creator)
        # django_simple_history.history_type: + for create, ~ for update, and - for delete
        event_updaters = list(set(
            Event.history.filter(id=event.id, modified_date=yesterday
                                 ).exclude(history_type='+', modified_by=event.created_by.id
                                           ).values_list('modified_by__username', 'modified_by__id')))
        # only create notifications if there were truly updates and not just creates (exclude history_type='+')
        if event_updaters:
            for cue in standard_notification_cues_updated:
                if (cue.created_by.organization.id == event.created_by.organization.id
                        or cue.created_by.organization.id in event.created_by.organization.parent_organizations):
                    for event_updater in event_updaters:
                        source = event_updater[0]
                        source_id = event_updater[1]
                        updates = get_updates(event, source_id, yesterday, 'user', cue.created_by)

                        # only create notifications if there are update details (non-empty string)
                        if updates:
                            notifications.append(get_notification_details(cue, event, msg_tmp, updates, source))

    return notifications


@shared_task()
def collaborator_events(events_created_yesterday, events_updated_yesterday, yesterday):
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
                source = event.created_by.username
                updates = "N/A"
                notifications.append(get_notification_details(cue, event, msg_tmp, updates, source))

    standard_notification_cues_updated = NotificationCueStandard.objects.filter(
        standard_type__name='Collaborator', notification_cue_preference__create_when_modified=True)
    for event in events_updated_yesterday:
        # Create one notification per distinct updater (not including the creator)
        # django_simple_history.history_type: + for create, ~ for update, and - for delete
        event_updaters = list(set(
            Event.history.filter(id=event.id, modified_date=yesterday
                                 ).exclude(history_type='+', modified_by=event.created_by.id
                                           ).values_list('modified_by__username', 'modified_by__id')))
        # only create notifications if there were truly updates and not just creates (exclude history_type='+')
        if event_updaters:
            event_collaborator_ids = list(set(User.objects.filter(
                Q(eventwriteusers__event_id=event.id) |
                Q(eventreadusers__event_id=event.id)
            ).values_list('id', flat=True)))
            for cue in standard_notification_cues_updated:
                if cue.created_by.id in event_collaborator_ids:
                    for event_updater in event_updaters:
                        source = event_updater[0]
                        source_id = event_updater[1]
                        updates = get_updates(event, source_id, yesterday, 'user', cue.created_by)

                        # only create notifications if there are update details (non-empty string)
                        if updates:
                            notifications.append(get_notification_details(cue, event, msg_tmp, updates, source))

    return notifications


@shared_task()
def all_events(events_created_yesterday, events_updated_yesterday, yesterday):
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
            all_evt_locs = ""
            for evtloc in eventlocations:
                evt_loc_name = ""
                if evtloc.administrative_level_two:
                    evt_loc_name += evtloc.administrative_level_two.name
                evt_loc_name += ", " + evtloc.administrative_level_one.abbreviation
                evt_loc_name += ", " + evtloc.country.abbreviation
                all_evt_locs = evt_loc_name if len(all_evt_locs) == 0 else all_evt_locs + "; " + evt_loc_name

            subject = msg_tmp.subject_template.format(event_id=event.id)
            body = msg_tmp.body_template.format(
                event_id=event.id, organization=event.created_by.organization.name, event_location=all_evt_locs,
                event_date=event.created_date, new_updated="New", created_updated="created", updates="N/A")
            source = event.created_by.organization.name
            org = source

            notifications.append([recipients, source, event.id, 'event', subject, body, send_email, email_to, org])

    standard_notification_cues_updated = NotificationCueStandard.objects.filter(
        standard_type__name='All', notification_cue_preference__create_when_modified=True)
    for event in events_updated_yesterday:
        # Create one notification per distinct updater (not including the creator)
        # django_simple_history.history_type: + for create, ~ for update, and - for delete
        event_updaters = list(set(
            Event.history.filter(id=event.id, modified_date=yesterday
                                 ).exclude(history_type='+', modified_by=event.created_by.id
                                           ).values_list('modified_by__organization__name',
                                                         'modified_by__organization__id')))
        # only create notifications if there were truly updates and not just creates (exclude history_type='+')
        if event_updaters:
            for cue in standard_notification_cues_updated:
                send_email = cue.notification_cue_preference.send_email
                recipients = [cue.created_by.id, ]
                email_to = [cue.created_by.email, ] if send_email else []

                eventlocations = EventLocation.objects.filter(event=event.id)
                all_evt_locs = ""
                for evtloc in eventlocations:
                    evt_loc_name = ""
                    if evtloc.administrative_level_two:
                        evt_loc_name += evtloc.administrative_level_two.name
                    evt_loc_name += ", " + evtloc.administrative_level_one.abbreviation
                    evt_loc_name += ", " + evtloc.country.abbreviation
                    all_evt_locs = evt_loc_name if len(all_evt_locs) == 0 else all_evt_locs + "; " + evt_loc_name

                for event_updater in event_updaters:
                    source = event_updater[0]
                    source_id = event_updater[1]
                    org = source
                    updates = get_updates(event, source_id, yesterday, 'org', cue.created_by)

                    # only create notifications if there are update details (non-empty string)
                    if updates:
                        subject = msg_tmp.subject_template.format(event_id=event.id)
                        body = msg_tmp.body_template.format(
                            event_id=event.id, organization=source, event_location=all_evt_locs,
                            event_date=event.modified_date, new_updated="Updated", created_updated="updated",
                            updates=updates)

                        notifications.append([recipients, source, event.id, 'event', subject, body,
                                              send_email, email_to, org])

    return notifications


@shared_task()
def standard_notifications():
    yesterday = datetime.strftime(datetime.now() - timedelta(1), '%Y-%m-%d')
    new_events = Event.objects.filter(created_date=yesterday)
    updated_events = Event.objects.filter(modified_date=yesterday)

    own_evts = own_events(new_events, updated_events, yesterday)
    org_evts = organization_events(new_events, updated_events, yesterday)
    collab_evts = collaborator_events(new_events, updated_events, yesterday)
    all_evts = all_events(new_events, updated_events, yesterday)

    unique_notifications_user_source = []
    unique_notifications_org_source = []

    # send unique notifications (determined by combination of [recipient, source, event])
    # that include source user info (the own, org, and collab notifications), preferring own over org over collab
    # also collect unique notifications using org (not user) source info to later find unique 'All Event' notifications
    user_detail_notifications = own_evts + org_evts + collab_evts
    for notification in user_detail_notifications:
        # find unique by (recipients, user (source), event ID)
        if (notification[0], notification[1], notification[2]) not in unique_notifications_user_source:
            unique_notifications_user_source.append((notification[0], notification[1], notification[2]))

            # find unique by (recipients, org, event ID) (so these will not also be sent during 'ALL Event' processing)
            if (notification[0], notification[8], notification[2]) not in unique_notifications_org_source:
                unique_notifications_org_source.append((notification[0], notification[8], notification[2]))

            # remove the unnecessary 'org' attribute before generating the notification
            notification.pop(8)
            # generate the notification
            generate_notification.delay(*notification)

    # then send unique 'ALL Event' notifications (which user org as source info)
    for notification in all_evts:
        # find unique by (recipients, org, event ID)
        if (notification[0], notification[8], notification[2]) not in unique_notifications_org_source:
            unique_notifications_org_source.append((notification[0], notification[8], notification[2]))
            # remove the unnecessary 'org' (which here is a copy of source) attribute before generating the notification
            notification.pop(8)
            # generate the notification
            generate_notification.delay(*notification)

    return True


@shared_task()
def stale_events():
    stale_event_periods = Configuration.objects.filter(name='stale_event_periods').first()
    if stale_event_periods:
        stale_event_periods_list = stale_event_periods.value.split(',')
        if all(x.strip().isdigit() for x in stale_event_periods_list):
            stale_event_periods_list_ints = [int(x) for x in stale_event_periods_list]
            msg_tmp = NotificationMessageTemplate.objects.filter(name='Stale Events').first()
            for period in stale_event_periods_list_ints:
                period_date = datetime.strftime(datetime.now() - timedelta(period), '%Y-%m-%d')
                all_stale_events = Event.objects.filter(complete=False, created_date=period_date)
                for event in all_stale_events:
                    recipients = list(User.objects.filter(name='nwhc-epi').values_list('id', flat=True))
                    recipients += [event.created_by.id, ]
                    email_to = list(User.objects.filter(name='nwhc-epi').values_list('email', flat=True))
                    email_to += [event.created_by.email, ]

                    eventlocations = EventLocation.objects.filter(event=event.id)
                    all_evt_locs = ""
                    for evtloc in eventlocations:
                        evt_loc_name = ""
                        if evtloc.administrative_level_two:
                            evt_loc_name += evtloc.administrative_level_two.name
                        evt_loc_name += ", " + evtloc.administrative_level_one.abbreviation
                        evt_loc_name += ", " + evtloc.country.abbreviation
                        all_evt_locs = evt_loc_name if len(all_evt_locs) == 0 else all_evt_locs + "; " + evt_loc_name

                    subject = msg_tmp.subject_template.format(event_id=event.id)
                    body = msg_tmp.body_template.format(
                        event_id=event.id, event_location=all_evt_locs, event_date=event.created_date,
                        stale_period=str(period))
                    source = 'system'
                    generate_notification.delay(recipients, source, event.id, 'event', subject, body, True, email_to)
    return True


def build_custom_notifications_query(cue, base_queryset):
    queryset = None
    criteria = []

    # event
    if cue.event:
        criteria.append(('Event', str(cue.event)))
        if not queryset:
            queryset = base_queryset
        queryset = queryset.filter(id=cue.event)

    # event_affected_count
    if cue.event_affected_count:
        operator = cue.event_affected_count_operator.upper()

        # criteria
        value = str(cue.event_affected_count)

        # queryset
        if not queryset:
            queryset = base_queryset
        if operator == "LTE":
            queryset = queryset.filter(affected_count__lte=value)
            criteria.append(('Affected Count', '<= ' + value))
        else:
            # default to GTE
            queryset = queryset.filter(affected_count__gte=value)
            criteria.append(('Affected Count', '>= ' + value))

    # event_location_land_ownership
    if cue.event_location_land_ownership:
        values = cue.event_location_land_ownership['values']
        if len(values) > 0:
            operator = cue.event_location_land_ownership['operator'].upper()

            # criteria
            names_list = list(LandOwnership.objects.filter(id__in=values).values_list('name', flat=True))
            if len(values) == 1:
                names = names_list[0]
            else:
                names = (' ' + operator + ' ').join(names_list)
            criteria.append(('Land Ownership', names))

            # queryset
            if not queryset:
                queryset = base_queryset
            if operator == "OR":
                queries = [Q(eventlocations__land_ownership=value) for value in values]
                query = queries.pop()
                for item in queries:
                    query |= item
                queryset = queryset.filter(query)
            else:
                # default to AND
                # figure out how to query if an event has a child with one of each
                for value in values:
                    queryset = queryset.filter(eventlocations__land_ownership=value)

    # event_location_administrative_level_one
    if cue.event_location_administrative_level_one:
        values = cue.event_location_administrative_level_one['values']
        if len(values) > 0:
            operator = cue.event_location_administrative_level_one['operator'].upper()

            # criteria
            # use locality name when possible
            ctry_ids = list(Country.objects.filter(
                administrativelevelones__in=values).values_list('id', flat=True))
            field_name = 'Administrative Level One'
            if ctry_ids:
                locality = AdministrativeLevelLocality.objects.filter(country=ctry_ids[0]).first()
                if locality and locality.admin_level_one_name:
                    field_name = locality.admin_level_one_name

            names_list = list(AdministrativeLevelOne.objects.filter(id__in=values).values_list('name', flat=True))
            if len(values) == 1:
                names = names_list[0]
            else:
                names = (' ' + operator + ' ').join(names_list)
            criteria.append((field_name, names))

            # queryset
            if not queryset:
                queryset = base_queryset
            queryset = queryset.prefetch_related('eventlocations__administrative_level_two').filter(
                eventlocations__administrative_level_one__in=values).distinct()
            if operator == 'AND':
                # this _should_ be fairly straight forward with the postgresql ArrayAgg function,
                # (which would offload the hard work to postgresql and make this whole operation faster)
                # but that function is just throwing an error about a Serial data type,
                # so the following is a work-around

                # first, count the eventlocations for each returned event
                # and only allow those with the same or greater count as the length of the query_param list
                queryset = queryset.annotate(
                    count_evtlocs=Count('eventlocations')).filter(count_evtlocs__gte=len(values))
                admin_level_one_list_ints = [int(i) for i in values]
                # next, find only the events that have _all_ the requested values, not just any of them
                for item in queryset:
                    evtlocs = EventLocation.objects.filter(event_id=item.id)
                    all_a1s = [evtloc.administrative_level_one.id for evtloc in evtlocs]
                    if not set(admin_level_one_list_ints).issubset(set(all_a1s)):
                        queryset = queryset.exclude(pk=item.id)

    # species
    if cue.species:
        values = cue.species['values']
        if len(values) > 0:
            operator = cue.species['operator'].upper()

            # criteria
            names_list = list(Species.objects.filter(id__in=values).values_list('name', flat=True))
            if len(values) == 1:
                names = names_list[0]
            else:
                names = (' ' + operator + ' ').join(names_list)
            criteria.append(('Species', names))

            # queryset
            if not queryset:
                queryset = base_queryset
            queryset = queryset.prefetch_related('eventlocations__locationspecies__species').filter(
                eventlocations__locationspecies__species__in=values).distinct()
            if operator == "AND":
                # first, count the species for each returned event
                # and only allow those with the same or greater count as the length of the query_param list
                queryset = queryset.annotate(count_species=Count(
                    'eventlocations__locationspecies__species')).filter(count_species__gte=len(values))
                species_list_ints = [int(i) for i in values]
                # next, find only the events that have _all_ the requested values, not just any of them
                for item in queryset:
                    evtlocs = EventLocation.objects.filter(event_id=item.id)
                    locspecs = LocationSpecies.objects.filter(event_location__in=evtlocs)
                    all_species = [locspec.species.id for locspec in locspecs]
                    if not set(species_list_ints).issubset(set(all_species)):
                        queryset = queryset.exclude(pk=item.id)

    # species_diagnosis_diagnosis
    if cue.species_diagnosis_diagnosis:
        values = cue.species_diagnosis_diagnosis['values']
        if len(values) > 0:
            operator = cue.species_diagnosis_diagnosis['operator'].upper()

            # criteria
            names_list = list(Diagnosis.objects.filter(id__in=values).values_list('name', flat=True))
            if len(values) == 1:
                names = names_list[0]
            else:
                names = (' ' + operator + ' ').join(names_list)
            criteria.append(('Diagnosis', names))

            # queryset
            if not queryset:
                queryset = base_queryset
            queryset = queryset.prefetch_related('eventlocations__locationspecies__speciesdiagnoses__diagnosis').filter(
                eventlocations__locationspecies__speciesdiagnoses__diagnosis__in=values).distinct()
            if operator == "AND":
                # first, count the species for each returned event
                # and only allow those with the same or greater count as the length of the query_param list
                queryset = queryset.annotate(count_diagnoses=Count(
                    'eventlocations__locationspecies__speciesdiagnoses__diagnosis', distinct=True)).filter(
                    count_diagnoses__gte=len(values))
                diagnosis_list_ints = [int(i) for i in values]
                # next, find only the events that have _all_ the requested values, not just any of them
                for item in queryset:
                    evtdiags = EventDiagnosis.objects.filter(event_id=item.id)
                    all_diagnoses = [evtdiag.diagnosis.id for evtdiag in evtdiags]
                    if not set(diagnosis_list_ints).issubset(set(all_diagnoses)):
                        queryset = queryset.exclude(pk=item.id)

    criteria_string = ''
    for criterion in criteria:
        criteria_string += criterion[0] + ": " + criterion[1] + "<br />"

    return queryset, criteria_string


@shared_task()
def custom_notifications():
    # An event with a number affected greater than or equal to the provided integer is created,
    # OR an event location is added/updated that meets that criteria
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Custom Notification').first()
    yesterday = datetime.strftime(datetime.now() - timedelta(1), '%Y-%m-%d')

    custom_notification_cues_new = NotificationCueCustom.objects.filter(
        notification_cue_preference__create_when_new=True)
    base_queryset = Event.objects.filter(created_date=yesterday)
    for cue in custom_notification_cues_new:
        queryset, criteria = build_custom_notifications_query(cue, base_queryset)

        if queryset:
            for event in queryset:
                send_email = cue.notification_cue_preference.send_email
                # recipients: users with this notification configured
                recipients = [cue.created_by.id, ]
                # email forwarding: Optional, set by user.
                email_to = [cue.created_by.email, ] if send_email else []

                subject = msg_tmp.subject_template.format(event_id=event.id)
                body = msg_tmp.body_template.format(
                    new_updated="New", criteria=criteria, organization=event.created_by.organization.name,
                    created_updated="created", event_id=event.id, event_date=event.created_date, updates="N/A")
                # source: any organization who creates or updates an event that meets the trigger criteria
                source = event.created_by.organization.name
                generate_notification.delay(recipients, source, event.id, 'event', subject, body, send_email, email_to)

    custom_notification_cues_updated = NotificationCueCustom.objects.filter(
        notification_cue_preference__create_when_modified=True)
    base_queryset = Event.objects.filter(modified_date=yesterday)
    for cue in custom_notification_cues_updated:
        queryset, criteria = build_custom_notifications_query(cue, base_queryset)

        if queryset:
            for event in queryset:
                # Create one notification per distinct updater (not including the creator)
                # django_simple_history.history_type: + for create, ~ for update, and - for delete
                event_updaters = list(set(
                    Event.history.filter(id=event.id, modified_date=yesterday
                                         ).exclude(history_type='+', modified_by=event.created_by.id
                                                   ).values_list('modified_by__organization__name',
                                                                 'modified_by__organization__id')))
                # only create notifications if there were truly updates and not just creates (exclude history_type='+')
                if event_updaters:
                    for event_updater in event_updaters:
                        send_email = cue.notification_cue_preference.send_email
                        # recipients: users with this notification configured
                        recipients = [cue.created_by.id, ]
                        # email forwarding: Optional, set by user.
                        email_to = [cue.created_by.email, ] if send_email else []

                        # source: any organization who creates or updates an event that meets the trigger criteria
                        source = event_updater[0]
                        source_id = event_updater[1]
                        updates = get_updates(event, source_id, yesterday, 'org', cue.created_by)

                        # only create notifications if there are update details (non-empty string)
                        if updates:
                            subject = msg_tmp.subject_template.format(event_id=event.id)
                            body = msg_tmp.body_template.format(
                                new_updated="Updated", criteria=criteria, organization=source,
                                created_updated="updated", event_id=event.id, event_date=event.modified_date,
                                updates=updates)

                            generate_notification.delay(recipients, source, event.id, 'event', subject, body,
                                                        send_email, email_to)

    return True
