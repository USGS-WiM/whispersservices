from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db.models import Count
from whispersservices.serializers import *
from whispersservices.models import *
from whispersservices.immediate_tasks import generate_notification, construct_notification_email


def get_yesterday():
    return datetime.strftime(datetime.now() - timedelta(days=1), '%Y-%m-%d')


def send_missing_notification_template_message_email(task_name, template_name):
    recip = EMAIL_WHISPERS
    subject = "WHISPERS ADMIN: Notification Message Template Not Found During " + task_name + " task"
    body = "The \"" + template_name + "\" Notification Message Template was not found"
    body += " at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    notif_email = construct_notification_email(recip, subject, body, False)
    print(notif_email.__dict__)


def send_missing_notification_cue_standard_email(user, template_name):
    recip = EMAIL_WHISPERS
    subject = "WHISPERS ADMIN: Standard Notification Cue Not Found During standard_notifications task"
    body = "The \"" + template_name + "\" Standard Notification Cue was not found for user "
    body += user.first_name + " " + user.last_name + " (username " + user.username + ", ID " + str(user.id) + ")"
    body += " at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    notif_email = construct_notification_email(recip, subject, body, False)
    print(notif_email.__dict__)


def get_change_info(history_record, model_name):
    if history_record.history_type == '+':
        action = 'created'
        alt_action = 'assigned'
    elif history_record.history_type == '-':
        action = 'deleted'
        alt_action = 'unassigned'
    else:
        action = 'changed'
        alt_action = 'reassigned'
    model = " ".join([part.capitalize() for part in model_name.split('_')])
    if model_name == 'event_comment':
        details = "<br />An {} was {}: {}".format(model, action, history_record.comment)
    elif model_name == 'event_diagnosis':
        suspect = "suspect" if history_record.suspect else ""
        details = "<br />An {} was {}: {} {}".format(model, action, history_record.diagnosis.name, suspect)
    elif model_name == 'event_group':
        details = "<br />Event was added to {} {}".format(model, history_record.name)
    elif model_name == 'event_group_comment':
        details = "<br />An {} was {}: {}".format(model, action, history_record.comment)
    elif model_name == 'event_organization':
        details = "<br />An Event Organization was {}: {}".format(alt_action, history_record.organization.name)
    elif model_name == 'event_contact':
        name = history_record.contact.first_name + " " + history_record.contact.last_name
        details = "<br />An Event Contact was {}: {}".format(alt_action, name)
    elif model_name == 'event_location':
        name = history_record.administrative_level_two.name
        name += ", " + history_record.administrative_level_one.abbreviation + ", " + history_record.country.abbreviation
        details = "<br />An {} was {}: {}".format(model, action, name)
    elif model_name == 'event_location_comment':
        details = "<br />An {} was {}: {}".format(model, action, history_record.comment)
    elif model_name == 'event_location_contact':
        name = history_record.contact.first_name + " " + history_record.contact.last_name
        details = "<br />An Event Location Contact was {}: {}".format(alt_action, name)
    elif model_name == 'event_location_flyway':
        details = "<br />An Event Location Flyway was {}: {}".format(alt_action, history_record.flyway.name)
    elif model_name == 'location_species':
        details = "<br />A {} was {}: {}".format(model, action, history_record.species.name)
    elif model_name == 'species_diagnosis':
        suspect = "suspect" if history_record.suspect else ""
        details = "<br />A {} was {}: {} {}".format(model, action, history_record.diagnosis.name, suspect)
    elif model_name == 'species_diagnosis_organization':
        details = "<br />A Species Diagnosis Organization was {}: {}".format(
            alt_action, history_record.organization.name)
    else:
        a_an = "An" if model[0].lower() in ['a', 'e', 'i', 'o', 'u'] else "A"
        details = "<br />{} {} was {}".format(a_an, model, action)
    return details.rstrip()


def get_changes(history, source_id, yesterday, model_name, source_type, cue_user):
    yesterday_date = datetime.strptime(yesterday, '%Y-%m-%d').date()
    changes = ""

    if len(history) == 0:
        # no history records for the model, so ignore
        pass
    elif len(history) == 1:
        # only one history record for the model
        h = history[0]
        # only include creates made yesterday by the source user (or org)
        #  (a single history record can only ever be a create, but better to be safe by being explicit)
        h_id = h.history_user.id if source_type == 'user' else h.history_user.organization.id
        if h.history_date.date() == yesterday_date and h_id == source_id and h.history_type in ['+', '-']:
            # check permissions for comments and contacts (visible to privileged users only!)
            check_permissions = False
            event = None
            if model_name == 'event_comment':
                check_permissions = True
                event = Event.objects.filter(id=h.object_id).first()
            elif model_name == 'event_location_comment':
                check_permissions = True
                event_location = EventLocation.objects.filter(id=h.object_id).first()
                event = Event.objects.filter(id=event_location.event_id).first()
            elif model_name == 'event_contact':
                check_permissions = True
                event = Event.objects.filter(id=h.event_id).first()
            elif model_name == 'event_location_contact':
                check_permissions = True
                event_location = EventLocation.objects.filter(id=h.event_location_id).first()
                event = Event.objects.filter(id=event_location.event_id).first()
            if check_permissions and not (cue_user.id == event.created_by.id
                                          or cue_user.organization.id == event.created_by.organization.id
                                          or cue_user.organization.id in event.created_by.parent_organizations
                                          or cue_user.id in list(User.objects.filter(
                        Q(writeevents__in=[event.id]) | Q(readevents__in=[event.id])
                    ).values_list('id', flat=True))):
                pass
            elif model_name == 'event_group_comment' and not (cue_user.role.is_superadmin or cue_user.role.is_admin
                                                              or cue_user.organization.id == int(
                        Configuration.objects.filter(name='nwhc_organization').first().value)):
                # Event Group comments visible only to NWHC staff
                pass
            else:
                changes += get_change_info(h, model_name)
    else:
        # more than one history record for the model
        for h in history:
            # only include changes made yesterday
            if not h.history_date.date() == yesterday_date:
                # no changes from yesterday found, so move on
                continue
            else:
                # only include changes made by this particular updater (source)
                h_id = h.history_user.id if source_type == 'user' else h.history_user.organization.id
                if not h_id == source_id:
                    # keep the loop going in case changes made by this updater are interspersed among other changes
                    continue
                else:
                    # check permissions for comments and event contacts (visible to privileged users only!)
                    check_permissions = False
                    event = None
                    if model_name == 'event_comment':
                        check_permissions = True
                        event = Event.objects.filter(id=h.object_id).first()
                    elif model_name == 'event_location_comment':
                        check_permissions = True
                        event_location = EventLocation.objects.filter(id=h.object_id).first()
                        event = Event.objects.filter(id=event_location.event_id).first()
                    elif model_name == 'event_contact':
                        check_permissions = True
                        event = Event.objects.filter(id=h.event_id).first()
                    elif model_name == 'event_location_contact':
                        check_permissions = True
                        event_location = EventLocation.objects.filter(id=h.event_location_id).first()
                        event = Event.objects.filter(id=event_location.event_id).first()
                    if check_permissions and not (cue_user.id == event.created_by.id
                                                  or cue_user.organization.id == event.created_by.organization.id
                                                  or cue_user.organization.id in event.created_by.parent_organizations
                                                  or cue_user.id in list(User.objects.filter(
                                Q(writeevents__in=[event.id]) | Q(readevents__in=[event.id])
                            ).values_list('id', flat=True))):
                        # keep the loop going in case changes made by this updater are interspersed among other changes
                        continue
                    elif model_name == 'event_group_comment' and not (
                            cue_user.role.is_superadmin or cue_user.role.is_admin
                            or cue_user.organization.id == int(
                        Configuration.objects.filter(name='nwhc_organization').first().value)):
                        # Event Group comments visible only to NWHC staff
                        # keep the loop going in case changes made by this updater are interspersed among other changes
                        continue
                    # process object creates and deletes (and legacy data) differently,
                    #  since there is no earlier record to diff against for changes
                    if h.history_type in ['+', '-'] or h.prev_record is None:
                        changes += get_change_info(h, model_name)
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
                                if fld == 'event_type':
                                    change.new = EventType.objects.get(id=change.new) if change.new else change.new
                                    change.old = EventType.objects.get(id=change.old) if change.old else change.old
                                elif fld == 'event_reference':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id
                                            or cue_user.organization.id in h.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[h.id]) | Q(readevents__in=[h.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                elif fld == 'staff':
                                    # check permissions (visible to NWHC only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id):
                                        change.new = Staff.objects.get(id=change.new) if change.new else change.new
                                        change.old = Staff.objects.get(id=change.old) if change.old else change.old
                                    else:
                                        continue
                                elif fld == 'event_status':
                                    # check permissions (visible to NWHC only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id):
                                        chg = change
                                        change.new = EventStatus.objects.get(id=chg.new) if chg.new else chg.new
                                        change.old = EventStatus.objects.get(id=chg.old) if chg.old else chg.old
                                    else:
                                        continue
                                elif fld == 'quality_check':
                                    # check permissions (visible to NWHC only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                elif fld == 'legal_status':
                                    # check permissions (visible to NWHC only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id):
                                        chg = change
                                        change.new = LegalStatus.objects.get(id=chg.new) if chg.new else chg.new
                                        change.old = LegalStatus.objects.get(id=chg.old) if chg.old else chg.old
                                    else:
                                        continue
                                elif fld == 'legal_number':
                                    # check permissions (visible to NWHC only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                elif fld == 'public':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id
                                            or cue_user.organization.id in h.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[h.id]) | Q(readevents__in=[h.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                            elif model_name == 'event_location':
                                if fld == 'name':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id
                                            or cue_user.organization.id in h.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[h.event.id]) | Q(readevents__in=[h.event.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                elif fld == 'country':
                                    change.new = Country.objects.get(id=change.new) if change.new else change.new
                                    change.old = Country.objects.get(id=change.old) if change.old else change.old
                                elif fld == 'administrative_level_one':
                                    chg = change
                                    change.new = AdministrativeLevelOne.objects.get(id=chg.new) if chg.new else chg.new
                                    change.old = AdministrativeLevelOne.objects.get(id=chg.old) if chg.old else chg.old
                                    # substitute locality name if applicable
                                    locality = AdministrativeLevelLocality.objects.filter(country=h.country).first()
                                    if locality and locality.admin_level_one_name:
                                        change.field = locality.admin_level_one_name
                                elif fld == 'administrative_level_two':
                                    chg = change
                                    change.new = AdministrativeLevelTwo.objects.get(id=chg.new) if chg.new else chg.new
                                    change.old = AdministrativeLevelTwo.objects.get(id=chg.old) if chg.old else chg.old
                                    # substitute locality name if applicable
                                    locality = AdministrativeLevelLocality.objects.filter(country=h.country).first()
                                    if locality and locality.admin_level_two_name:
                                        change.field = locality.admin_level_two_name
                                elif fld == 'latitude':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id
                                            or cue_user.organization.id in h.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[h.event.id]) | Q(readevents__in=[h.event.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                elif fld == 'longitude':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id
                                            or cue_user.organization.id in h.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[h.event.id]) | Q(readevents__in=[h.event.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                elif fld == 'land_ownership':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id
                                            or cue_user.organization.id in h.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[h.event.id]) | Q(readevents__in=[h.event.id])
                                            ).values_list('id', flat=True))):
                                        chg = change
                                        change.new = LandOwnership.objects.get(id=chg.new) if chg.new else chg.new
                                        change.old = LandOwnership.objects.get(id=chg.old) if chg.old else chg.old
                                    else:
                                        continue
                                elif fld == 'gnis_name':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id
                                            or cue_user.organization.id in h.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[h.event.id]) | Q(readevents__in=[h.event.id])
                                            ).values_list('id', flat=True))):
                                        change.new = "\"\"" if change.new == '' else change.new
                                        change.old = "\"\"" if change.old == '' else change.old
                                    else:
                                        continue
                                elif fld == 'gnis_id':
                                    # check permissions (visible to privileged users only!)
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id
                                            or cue_user.organization.id in h.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[h.event.id]) | Q(readevents__in=[h.event.id])
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
                                    # check permissions (visible to privileged users only!)
                                    event_id = h.location_species.event_location.event.id
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id
                                            or cue_user.organization.id in h.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[event_id]) | Q(readevents__in=[event_id])
                                            ).values_list('id', flat=True))):
                                        chg = change
                                        change.new = DiagnosisCause.objects.get(id=chg.new) if chg.new else chg.new
                                        change.old = DiagnosisCause.objects.get(id=chg.old) if chg.old else chg.old
                                    else:
                                        continue
                                if fld == 'basis':
                                    # check permissions (visible to privileged users only!)
                                    event_id = h.location_species.event_location.event.id
                                    if (cue_user.id == h.created_by.id
                                            or cue_user.organization.id == h.created_by.organization.id
                                            or cue_user.organization.id in h.created_by.parent_organizations
                                            or cue_user.id in list(User.objects.filter(
                                                Q(writeevents__in=[event_id]) | Q(readevents__in=[event_id])
                                            ).values_list('id', flat=True))):
                                        chg = change
                                        change.new = DiagnosisBasis.objects.get(id=chg.new) if chg.new else chg.new
                                        change.old = DiagnosisBasis.objects.get(id=chg.old) if chg.old else chg.old
                                    else:
                                        continue

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
    # get changes from the event and its children (event comments, event diagnoses, event groups,
    #  event group comments, event locations, event location comments, event location contacts,
    #  event location flyways, location species, species diagnoses, species diagnosis organizations)
    updates = ""

    # event
    event_history = Event.history.filter(id=event.id).order_by('-id', '-history_id')
    updates += get_changes(event_history, source_id, yesterday, 'event', source_type, cue_user)

    # event comments
    event_content_type = ContentType.objects.filter(model='event').first()
    event_comment_history = Comment.history.filter(
        object_id=event.id, content_type=event_content_type.id, modified_date=event.modified_date).order_by('-id')
    updates += get_changes(event_comment_history, source_id, yesterday, 'event_comment', source_type, cue_user)

    # event diagnoses
    event_diagnosis_history = EventDiagnosis.history.filter(event=event.id).order_by('-id', '-history_id')
    updates += get_changes(event_diagnosis_history, source_id, yesterday, 'event_diagnosis', source_type, cue_user)

    # get distinct event group IDs to ensure each event group's children are each only processed once
    event_group_ids = list(set(EventEventGroup.objects.filter(event_id=event.id).values_list('id', flat=True)))
    for event_group_id in event_group_ids:

        # event groups
        event_group_history = EventGroup.history.filter(id=event_group_id).order_by('-id', '-history_id')
        updates += get_changes(event_group_history, source_id, yesterday, 'event_group', source_type, cue_user)

        # event group comments
        event_group_content_type = ContentType.objects.filter(model='eventgroup').first()
        event_group_comment_history = Comment.history.filter(
            object_id=event_group_id, content_type=event_group_content_type.id, modified_date=event.modified_date
        ).order_by('-id', '-history_id')
        updates += get_changes(
            event_group_comment_history, source_id, yesterday, 'event_group_comment', source_type, cue_user)

    # event organizations
    event_organization_history = EventOrganization.history.filter(event=event.id).order_by('-id', '-history_id')
    updates += get_changes(event_organization_history, source_id, yesterday, 'event_organization', source_type, cue_user)

    # event contacts
    event_contact_history = EventContact.history.filter(event=event.id).order_by('-id', '-history_id')
    updates += get_changes(event_contact_history, source_id, yesterday, 'event_contact', source_type, cue_user)

    # event locations
    event_location_history = EventLocation.history.filter(event=event.id).order_by('-id', '-history_id')
    updates += get_changes(event_location_history, source_id, yesterday, 'event_location', source_type, cue_user)

    # get distinct event location IDs to ensure each event location's children are each only processed once
    event_location_ids = list(set(EventLocation.objects.filter(event=event.id).values_list('id', flat=True)))
    for event_location_id in event_location_ids:

        # event location comments
        event_location_content_type = ContentType.objects.filter(model='eventlocation').first()
        event_location_comment_history = Comment.history.filter(
            object_id=event_location_id, content_type=event_location_content_type.id, modified_date=event.modified_date
        ).order_by('-id', '-history_id')
        updates += get_changes(
            event_location_comment_history, source_id, yesterday, 'event_location_comment', source_type, cue_user)

        # event location contacts
        event_location_contact_history = EventLocationContact.history.filter(
            event_location=event_location_id).order_by('-id', '-history_id')
        updates += get_changes(
            event_location_contact_history, source_id, yesterday, 'event_location_contact', source_type, cue_user)

        # event location flyways
        event_location_flyway_history = EventLocationFlyway.history.filter(
            event_location=event_location_id).order_by('-id', '-history_id')
        updates += get_changes(
            event_location_flyway_history, source_id, yesterday, 'event_location_flyway', source_type, cue_user)

        # location species
        location_species_history = LocationSpecies.history.filter(
            event_location=event_location_id).order_by('-id', '-history_id')
        updates += get_changes(
            location_species_history, source_id, yesterday, 'location_species', source_type, cue_user)

        # get distinct location species IDs to ensure each location species' children are each only processed once
        location_species_ids = list(set(LocationSpecies.objects.filter(
            event_location=event_location_id).values_list('id', flat=True)))
        for location_species_id in location_species_ids:

            # species diagnoses
            species_diagnosis_history = SpeciesDiagnosis.history.filter(
                location_species=location_species_id).order_by('-id', '-history_id')
            updates += get_changes(
                species_diagnosis_history, source_id, yesterday, 'species_diagnosis', source_type, cue_user)

            # get distinct species diagnosis IDs to ensure each species diagnosis' children are each only processed once
            species_diagnosis_ids = list(set(SpeciesDiagnosis.objects.filter(
                location_species=location_species_id).values_list('id', flat=True)))
            for species_diagnosis_id in species_diagnosis_ids:

                # species diagnosis organizations
                species_diagnosis_organization_history = SpeciesDiagnosisOrganization.history.filter(
                    species_diagnosis=species_diagnosis_id).order_by('-id', '-history_id')
                updates += get_changes(
                    species_diagnosis_organization_history, source_id, yesterday, 'species_diagnosis_organization',
                    source_type, cue_user)

    return updates


def get_notification_details(cue, event, msg_tmp, updates, event_user):
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
        first_name = event_user.first_name
        last_name = event_user.last_name
        org = event_user.organization.name

    subject = msg_tmp.subject_template.format(event_id=event.id)
    body = msg_tmp.body_template.format(
        first_name=first_name, last_name=last_name, created_updated=created_updated,
        event_id=event.id, event_date=event_date, updates=updates, new_updated=new_updated)

    return [recipients, event_user.username, event.id, 'event', subject, body, send_email, email_to, org]


def get_event_notifications_own_new(events_created_yesterday, user):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Your Events').first()
    cue = NotificationCueStandard.objects.filter(standard_type__name='Own', created_by=user.id).first()

    if not cue:
        send_missing_notification_cue_standard_email(user, 'Own')
        return []

    elif cue.notification_cue_preference.create_when_new:
        for event in events_created_yesterday:
            updates = "N/A"
            notifications.append(get_notification_details(cue, event, msg_tmp, updates, event.created_by))

    return notifications


def get_event_notifications_own_updated(events_updated_yesterday, yesterday, user):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Your Events').first()
    cue = NotificationCueStandard.objects.filter(standard_type__name='Own', created_by=user.id).first()

    if not cue:
        send_missing_notification_cue_standard_email(user, 'Own')
        return []

    elif cue.notification_cue_preference.create_when_modified:
        for event in events_updated_yesterday:
            # Create one notification per distinct updater (not including the creator)
            # django_simple_history.history_type: + for create, ~ for update, and - for delete
            event_updater_ids = list(set(
                Event.history.filter(id=event.id, modified_date=yesterday
                                     ).exclude(history_type='+', modified_by=event.created_by.id
                                               ).values_list('modified_by', flat=True)))
            event_updaters = User.objects.filter(id__in=event_updater_ids)
            # only create notifications if there were truly updates and not just creates (exclude history_type='+')
            if event_updater_ids:
                for event_updater in event_updaters:
                    updates = get_updates(event, event_updater.id, yesterday, 'user', cue.created_by)

                    # only create notifications if there are update details (non-empty string)
                    if updates:
                        notifications.append(get_notification_details(cue, event, msg_tmp, updates, event_updater))

    return notifications


def get_event_notifications_organization_new(events_created_yesterday, user):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Organization Events').first()
    cue = NotificationCueStandard.objects.filter(standard_type__name='Organization', created_by=user.id).first()

    if not cue:
        send_missing_notification_cue_standard_email(user, 'Organization')
        return []

    elif cue.notification_cue_preference.create_when_new:
        for event in events_created_yesterday:
            updates = "N/A"
            notifications.append(get_notification_details(cue, event, msg_tmp, updates, event.created_by))

    return notifications


def get_event_notifications_organization_updated(events_updated_yesterday, yesterday, user):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Organization Events').first()
    cue = NotificationCueStandard.objects.filter(standard_type__name='Organization', created_by=user.id).first()

    if not cue:
        send_missing_notification_cue_standard_email(user, 'Organization')
        return []

    elif cue.notification_cue_preference.create_when_modified:
        for event in events_updated_yesterday:
            # Create one notification per distinct updater (not including the creator)
            # django_simple_history.history_type: + for create, ~ for update, and - for delete
            event_updater_ids = list(set(
                Event.history.filter(id=event.id, modified_date=yesterday
                                     ).exclude(history_type='+', modified_by=event.created_by.id
                                               ).values_list('modified_by', flat=True)))
            event_updaters = User.objects.filter(id__in=event_updater_ids)
            # only create notifications if there were truly updates and not just creates (exclude history_type='+')
            if event_updaters:
                for event_updater in event_updaters:
                    updates = get_updates(event, event_updater.id, yesterday, 'user', cue.created_by)

                    # only create notifications if there are update details (non-empty string)
                    if updates:
                        notifications.append(get_notification_details(cue, event, msg_tmp, updates, event_updater))

    return notifications


def get_event_notifications_collaborator_new(events_created_yesterday, user):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Collaborator Events').first()
    cue = NotificationCueStandard.objects.filter(standard_type__name='Collaborator', created_by=user.id).first()

    if not cue:
        send_missing_notification_cue_standard_email(user, 'Collaborator')
        return []

    elif cue.notification_cue_preference.create_when_new:
        for event in events_created_yesterday:
            updates = "N/A"
            notifications.append(get_notification_details(cue, event, msg_tmp, updates, event.created_by))

    return notifications


def get_event_notifications_collaborator_updated(events_updated_yesterday, yesterday, user):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Collaborator Events').first()
    cue = NotificationCueStandard.objects.filter(standard_type__name='Collaborator', created_by=user.id).first()

    if not cue:
        send_missing_notification_cue_standard_email(user, 'Collaborator')
        return []

    elif cue.notification_cue_preference.create_when_modified:
        for event in events_updated_yesterday:
            # Create one notification per distinct updater (not including the creator)
            # django_simple_history.history_type: + for create, ~ for update, and - for delete
            event_updater_ids = list(set(
                Event.history.filter(id=event.id, modified_date=yesterday
                                     ).exclude(history_type='+', modified_by=event.created_by.id
                                               ).values_list('modified_by', flat=True)))
            # only create notifications if there were truly updates and not just creates (exclude history_type='+')
            if event_updater_ids:
                event_updaters = User.objects.filter(id__in=event_updater_ids)
                for event_updater in event_updaters:
                    updates = get_updates(event, event_updater.id, yesterday, 'user', cue.created_by)

                    # only create notifications if there are update details (non-empty string)
                    if updates:
                        notifications.append(get_notification_details(cue, event, msg_tmp, updates, event_updater))

    return notifications


def get_event_notifications_all_new(events_created_yesterday, user):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='ALL Events').first()
    cue = NotificationCueStandard.objects.filter(standard_type__name='All', created_by=user.id).first()

    if not cue:
        send_missing_notification_cue_standard_email(user, 'All')
        return []

    elif cue.notification_cue_preference.create_when_new:
        for event in events_created_yesterday:
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

    return notifications


def get_event_notifications_all_updated(events_updated_yesterday, yesterday, user):
    notifications = []
    msg_tmp = NotificationMessageTemplate.objects.filter(name='ALL Events').first()
    cue = NotificationCueStandard.objects.filter(standard_type__name='All', created_by=user.id,).first()

    if not cue:
        send_missing_notification_cue_standard_email(user, 'All')
        return []

    elif cue.notification_cue_preference.create_when_modified:
        for event in events_updated_yesterday:
            send_email = cue.notification_cue_preference.send_email
            recipients = [cue.created_by.id, ]
            email_to = [cue.created_by.email, ] if send_email else []
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
                    source = event_updater[0]
                    source_id = event_updater[1]
                    org = source
                    updates = get_updates(event, source_id, yesterday, 'org', cue.created_by)

                    # only create notifications if there are update details (non-empty string)
                    if updates:
                        eventlocations = EventLocation.objects.filter(event=event.id)
                        all_evt_locs = ""
                        for evtloc in eventlocations:
                            evt_loc_name = ""
                            if evtloc.administrative_level_two:
                                evt_loc_name += evtloc.administrative_level_two.name
                            evt_loc_name += ", " + evtloc.administrative_level_one.abbreviation
                            evt_loc_name += ", " + evtloc.country.abbreviation
                            all_evt_locs = evt_loc_name if len(
                                all_evt_locs) == 0 else all_evt_locs + "; " + evt_loc_name

                        subject = msg_tmp.subject_template.format(event_id=event.id)
                        body = msg_tmp.body_template.format(
                            event_id=event.id, organization=source, event_location=all_evt_locs,
                            event_date=event.modified_date, new_updated="Updated", created_updated="updated",
                            updates=updates)

                        notifications.append([recipients, source, event.id, 'event', subject, body,
                                              send_email, email_to, org])

    return notifications


def send_unique_notifications(own_evt, org_evts, collab_evts, all_evts):
    unique_notifications_user_source = []
    unique_notifications_org_source = []

    # send unique notifications (determined by combination of [source, event])
    # that include source user info (the own, org, and collab notifications), preferring own over org over collab
    # also collect unique notifications using org (not user) source info to find unique 'All Event' notifications
    user_detail_notifications = own_evt + org_evts + collab_evts
    for notification in user_detail_notifications:
        # find unique by (user (source), event ID)
        if (notification[1], notification[2]) not in unique_notifications_user_source:
            unique_notifications_user_source.append((notification[1], notification[2]))

            # find unique by (org, event ID) (so these will not also be sent during 'ALL Event' processing)
            if (notification[8], notification[2]) not in unique_notifications_org_source:
                unique_notifications_org_source.append((notification[8], notification[2]))

            # remove the unnecessary 'org' attribute before generating the notification
            notification.pop(8)
            # generate the notification
            generate_notification.delay(*notification)

    # then send unique 'ALL Event' notifications (which user org as source info)
    all_evts = all_evts
    for notification in all_evts:
        # find unique by (org, event ID)
        if (notification[8], notification[2]) not in unique_notifications_org_source:
            unique_notifications_org_source.append((notification[8], notification[2]))
            # remove the unnecessary 'org' (which here is a copy of source) attribute before generating notification
            notification.pop(8)
            # generate the notification
            generate_notification.delay(*notification)
    return True


@shared_task(soft_time_limit=595, time_limit=600)
def standard_notifications_by_user(new_event_count, updated_event_count, yesterday, user_id):
    user = User.objects.filter(id=user_id).first()

    try:
        # zero evaluates to False and any positive number evaluates to True
        if new_event_count:
            own_events = Event.objects.filter(created_date=yesterday, created_by=user_id)
            own_notifs = get_event_notifications_own_new(own_events, user) if own_events else []

            org_events = Event.objects.filter(created_date=yesterday).filter(
                Q(created_by__organization__exact=user.organization.id)
                | Q(created_by__organization__in=user.organization.child_organizations)
            ).distinct()
            org_notifs = get_event_notifications_organization_new(org_events, user) if org_events else []

            collab_events = Event.objects.filter(created_date=yesterday).filter(
                Q(read_collaborators__in=[user.id])
                | Q(write_collaborators__in=[user.id])
            ).distinct()
            collab_notifs = get_event_notifications_collaborator_new(collab_events, user) if collab_events else []

            # do not create notifications for private events for users who are not the event owner
            #  or not in their org or are not event collaborators
            all_events_public = Event.objects.filter(created_date=yesterday, public=True).distinct()
            all_events_personal = Event.objects.filter(created_date=yesterday).filter(
                Q(created_by__exact=user.id) | Q(created_by__organization__exact=user.organization.id)
                | Q(created_by__organization__in=user.organization.child_organizations)
                | Q(read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])
            ).distinct()
            all_events = all_events_public | all_events_personal
            all_notifs = get_event_notifications_all_new(all_events, user) if all_events else []

            if own_notifs or org_notifs or collab_notifs or all_notifs:
                send_unique_notifications(own_notifs, org_notifs, collab_notifs, all_notifs)

        # zero evaluates to False and any positive number evaluates to True
        if updated_event_count:
            own_events = Event.objects.filter(modified_date=yesterday, created_by=user_id)
            own_notifs = get_event_notifications_own_updated(own_events, yesterday, user) if own_events else []

            org_events = Event.objects.filter(modified_date=yesterday).filter(
                Q(created_by__organization__exact=user.organization.id)
                | Q(created_by__organization__in=user.organization.child_organizations)
            ).distinct()
            org_notifs = get_event_notifications_organization_updated(org_events, yesterday, user) if org_events else []

            collab_events = Event.objects.filter(modified_date=yesterday).filter(
                Q(read_collaborators__in=[user.id])
                | Q(write_collaborators__in=[user.id])
            ).distinct()
            collab_notifs = get_event_notifications_collaborator_updated(
                collab_events, yesterday, user) if collab_events else []

            # do not create notifications for private events for users who are not the event owner
            #  or not in their org or are not event collaborators
            all_events_public = Event.objects.filter(modified_date=yesterday, public=True).distinct()
            all_events_personal = Event.objects.filter(modified_date=yesterday).filter(
                Q(created_by__exact=user.id) | Q(created_by__organization__exact=user.organization.id)
                | Q(created_by__organization__in=user.organization.child_organizations)
                | Q(read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])
            ).distinct()
            all_events = all_events_public | all_events_personal
            all_notifs = get_event_notifications_all_updated(all_events, yesterday, user) if all_events else []

            if own_notifs or org_notifs or collab_notifs or all_notifs:
                send_unique_notifications(own_notifs, org_notifs, collab_notifs, all_notifs)

    except SoftTimeLimitExceeded:
        recip = EMAIL_WHISPERS
        subject = "WHISPERS ADMIN: Timeout Encountered During standard_notifications_by_user_task"
        body = "A timeout was encountered while generating standard notifications for user "
        body += user.first_name + " " + user.last_name + " (username " + user.username + ", ID " + str(user.id) + ")."
        body += " Timeout encountered at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        notif_email = construct_notification_email(recip, subject, body, False)
        print(notif_email.__dict__)

    return True


@shared_task(soft_time_limit=595, time_limit=600)
def standard_notifications():
    msg_tmp_names = ['Your Events', 'Organization Events', 'Collaborator Events', 'ALL Events']
    msg_tmps = list(NotificationMessageTemplate.objects.filter(name__in=msg_tmp_names).values_list('name', flat=True))

    if len(msg_tmps) < len(msg_tmp_names):
        for msg_tmp_name in msg_tmp_names:
            if msg_tmp_name not in msg_tmps:
                send_missing_notification_template_message_email('standard_notifications', msg_tmp_name)
        return True

    try:
        yesterday = get_yesterday()
        new_event_count = Event.objects.filter(created_date=yesterday).count()
        updated_event_count = Event.objects.filter(modified_date=yesterday).count()
        # zero evaluates to False and any positive number evaluates to True
        if new_event_count or updated_event_count:
            active_user_ids = list(User.objects.filter(is_active=True).exclude(role=7).values_list('id', flat=True))
            for user_id in active_user_ids:
                standard_notifications_by_user.delay(new_event_count, updated_event_count, yesterday, user_id)

    except SoftTimeLimitExceeded:
        recip = EMAIL_WHISPERS
        subject = "WHISPERS ADMIN: Timeout Encountered During standard_notifications_task"
        body = "A timeout was encountered while generating standard notifications."
        body += " Some notifications may have been created before the task timed out."
        body += " Timeout encountered at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        notif_email = construct_notification_email(recip, subject, body, False)
        print(notif_email.__dict__)
    return True


# purge old notifications, regardless whether they have been read: 90 days with 500 messages max
@shared_task()
def purge_stale_notifications():
    # 90 days purge (all notifications)
    ninety_days_ago = datetime.strftime(datetime.now() - timedelta(days=90), '%Y-%m-%d')
    Notification.objects.filter(created_date__lte=ninety_days_ago).delete()

    # 500 max purge (notifications per user)
    users_with_notifs_over_500 = Notification.objects.values('recipient').order_by().annotate(
        user_notif_count=Count('recipient')).filter(user_notif_count__gt=500)
    for user in users_with_notifs_over_500:
        ids_over_500 = Notification.objects.filter(
            recipient=user['recipient']).order_by("-pk").values_list("pk", flat=True)[500:]
        Notification.objects.filter(pk__in=list(ids_over_500)).delete()
    return True


@shared_task()
def stale_event_notifications():
    stale_event_periods = Configuration.objects.filter(name='stale_event_periods').first()
    if stale_event_periods:
        stale_event_periods_list = stale_event_periods.value.split(',')
        if all(x.strip().isdigit() for x in stale_event_periods_list):
            stale_event_periods_list_ints = [int(x) for x in stale_event_periods_list]
            msg_tmp = NotificationMessageTemplate.objects.filter(name='Stale Events').first()
            for period in stale_event_periods_list_ints:
                period_date = datetime.strftime(datetime.now() - timedelta(days=period), '%Y-%m-%d')
                all_stale_events = Event.objects.filter(complete=False, created_date__gte=period_date)
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


@shared_task(soft_time_limit=595, time_limit=600)
def custom_notifications_by_user(yesterday, user_id):
    user = User.objects.filter(id=user_id).first()
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Custom Notification').first()

    try:
        # An event with a number affected greater than or equal to the provided integer is created,
        # OR an event location is added/updated that meets that criteria

        custom_notification_cues_new = NotificationCueCustom.objects.filter(
            notification_cue_preference__create_when_new=True, created_by=user.id)
        if custom_notification_cues_new:
            base_queryset = Event.objects.filter(created_date=yesterday)
            for cue in custom_notification_cues_new:
                queryset, criteria = build_custom_notifications_query(cue, base_queryset)

                if queryset:
                    for event in queryset:
                        # do not create notifications for private events for users who are not the event owner
                        #  or not in their org or are not event collaborators
                        if event.public or (user.id == event.created_by.id
                                            or user.organization.id == event.created_by.organization.id
                                            or user.organization.id in event.created_by.parent_organizations
                                            or user.id in list(User.objects.filter(
                                    Q(writeevents__in=[event.id]) | Q(readevents__in=[event.id])
                                ).values_list('id', flat=True))):
                            send_email = cue.notification_cue_preference.send_email
                            # recipients: users with this notification configured
                            recipients = [cue.created_by.id, ]
                            # email forwarding: Optional, set by user.
                            email_to = [cue.created_by.email, ] if send_email else []

                            subject = msg_tmp.subject_template.format(event_id=event.id)
                            body = msg_tmp.body_template.format(new_updated="New", criteria=criteria,
                                                                organization=event.created_by.organization.name,
                                                                created_updated="created", event_id=event.id,
                                                                event_date=event.created_date, updates="N/A")
                            # source: any organization who creates or updates an event that meets the trigger criteria
                            source = event.created_by.organization.name
                            generate_notification.delay(recipients, source, event.id, 'event', subject, body,
                                                        send_email, email_to)

        custom_notification_cues_updated = NotificationCueCustom.objects.filter(
            notification_cue_preference__create_when_modified=True, created_by=user_id)
        if custom_notification_cues_updated:
            base_queryset = Event.objects.filter(modified_date=yesterday)
            for cue in custom_notification_cues_updated:
                queryset, criteria = build_custom_notifications_query(cue, base_queryset)

                if queryset:
                    for event in queryset:
                        # do not create notifications for private events for users who are not the event owner
                        #  or not in their org or are not event collaborators
                        if event.public or (user.id == event.created_by.id
                                            or user.organization.id == event.created_by.organization.id
                                            or user.organization.id in event.created_by.parent_organizations
                                            or user.id in list(User.objects.filter(
                                    Q(writeevents__in=[event.id]) | Q(readevents__in=[event.id])
                                ).values_list('id', flat=True))):
                            # Create one notification per distinct updater (not including the creator)
                            # django_simple_history.history_type: + for create, ~ for update, and - for delete
                            event_updaters = list(set(
                                Event.history.filter(id=event.id, modified_date=yesterday
                                                     ).exclude(history_type='+', modified_by=event.created_by.id
                                                               ).values_list('modified_by__organization__name',
                                                                             'modified_by__organization__id')))
                            # only create notifications if there were truly updates
                            #  and not just creates (exclude history_type='+')
                            if event_updaters:
                                for event_updater in event_updaters:
                                    send_email = cue.notification_cue_preference.send_email
                                    # recipients: users with this notification configured
                                    recipients = [cue.created_by.id, ]
                                    # email forwarding: Optional, set by user.
                                    email_to = [cue.created_by.email, ] if send_email else []

                                    # source: any organization who creates or updates an event meeting trigger criteria
                                    source = event_updater[0]
                                    source_id = event_updater[1]
                                    updates = get_updates(event, source_id, yesterday, 'org', cue.created_by)

                                    # only create notifications if there are update details (non-empty string)
                                    if updates:
                                        subject = msg_tmp.subject_template.format(event_id=event.id)
                                        body = msg_tmp.body_template.format(
                                            new_updated="Updated", criteria=criteria, organization=source,
                                            created_updated="updated", event_id=event.id,
                                            event_date=event.modified_date, updates=updates)

                                        generate_notification.delay(recipients, source, event.id, 'event', subject,
                                                                    body, send_email, email_to)

    except SoftTimeLimitExceeded:
        recip = EMAIL_WHISPERS
        subject = "WHISPERS ADMIN: Timeout Encountered During custom_notifications_by_user_task"
        body = "A timeout was encountered while generating custom notifications for user "
        body += user.first_name + " " + user.last_name + " (username " + user.username + ", ID " + str(user.id) + ")."
        body += " Timeout encountered at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        notif_email = construct_notification_email(recip, subject, body, False)
        print(notif_email.__dict__)

    return True


@shared_task(soft_time_limit=595, time_limit=600)
def custom_notifications():
    msg_tmp = NotificationMessageTemplate.objects.filter(name='Custom Notification').first()

    if not msg_tmp:
        send_missing_notification_template_message_email('custom_notifications', 'Custom Notification')
        return True

    try:
        yesterday = get_yesterday()
        active_user_ids = list(User.objects.filter(is_active=True).values_list('id', flat=True))
        for user_id in active_user_ids:
            custom_notifications_by_user.delay(yesterday, user_id)
    except SoftTimeLimitExceeded:
        recip = EMAIL_WHISPERS
        subject = "WHISPERS ADMIN: Timeout Encountered During custom_notifications_task"
        body = "A timeout was encountered while generating custom notifications."
        body += " Some notifications may have been created before the task timed out."
        body += " Timeout encountered at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        notif_email = construct_notification_email(recip, subject, body, False)
        print(notif_email.__dict__)
    return True
