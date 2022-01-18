import re
import requests
import json
from urllib.parse import urlencode
from operator import itemgetter
from datetime import datetime, timedelta
from django.apps import apps
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.forms.models import model_to_dict
from drf_recaptcha.fields import ReCaptchaV2Field
from django.urls import reverse
from rest_framework import serializers, validators
from rest_framework.settings import api_settings
from whispersapi.tokens import email_verification_token
from whispersapi.models import *
from whispersapi.immediate_tasks import *
from dry_rest_permissions.generics import DRYPermissionsField

# TODO: implement required field validations for nested objects
# TODO: consider implementing type checking for nested objects
# TODO: turn every ListField into a set to prevent errors caused by duplicates

PK_REQUESTS = ['retrieve', 'update', 'partial_update', 'destroy']
COMMENT_CONTENT_TYPES = ['event', 'eventgroup', 'eventlocation', 'servicerequest']


def get_geonames_username():
    geonames_username_record = Configuration.objects.filter(name='geonames_username').first()
    if geonames_username_record:
        GEONAMES_USERNAME = geonames_username_record.value
    else:
        GEONAMES_USERNAME = settings.GEONAMES_USERNAME
        send_missing_configuration_value_email('geonames_username')
    return GEONAMES_USERNAME


def get_geonames_api():
    geonames_api_url_record = Configuration.objects.filter(name='geonames_api_url').first()
    if geonames_api_url_record:
        GEONAMES_API = geonames_api_url_record.value
    else:
        GEONAMES_API = settings.GEONAMES_API
        send_missing_configuration_value_email('geonames_api_url')
    return GEONAMES_API


def get_flyways_api():
    flyways_api_url_record = Configuration.objects.filter(name='flyways_api_url').first()
    if flyways_api_url_record:
        FLYWAYS_API = flyways_api_url_record.value
    else:
        FLYWAYS_API = settings.FLYWAYS_API
        send_missing_configuration_value_email('flyways_api_url')
    return FLYWAYS_API


def get_whispers_admin_user_id():
    whispers_admin_user_record = Configuration.objects.filter(name='whispers_admin_user').first()
    if whispers_admin_user_record:
        if whispers_admin_user_record.value.isdecimal():
            WHISPERS_ADMIN_USER_ID = int(whispers_admin_user_record.value)
        else:
            WHISPERS_ADMIN_USER_ID = settings.WHISPERS_ADMIN_USER_ID
            encountered_type = type(whispers_admin_user_record.value).__name__
            send_wrong_type_configuration_value_email('whispers_admin_user', encountered_type, 'int')
    else:
        WHISPERS_ADMIN_USER_ID = settings.WHISPERS_ADMIN_USER_ID
        send_missing_configuration_value_email('whispers_admin_user')
    return WHISPERS_ADMIN_USER_ID


def get_whispers_email_address():
    whispers_email_address = Configuration.objects.filter(name='whispers_email_address').first()
    if whispers_email_address:
        if whispers_email_address.value.count('@') == 1:
            EMAIL_WHISPERS = whispers_email_address.value
        else:
            EMAIL_WHISPERS = settings.EMAIL_WHISPERS
            encountered_type = type(whispers_email_address.value).__name__
            send_wrong_type_configuration_value_email('whispers_email_address', encountered_type, 'email_address')
    else:
        EMAIL_WHISPERS = settings.EMAIL_WHISPERS
        send_missing_configuration_value_email('whispers_email_address')
    return EMAIL_WHISPERS


def get_hfs_locations():
    hfs_locations_record = Configuration.objects.filter(name='hfs_locations').first()
    if hfs_locations_record:
        hfs_locations_str = hfs_locations_record.value.split(',')
        if all(x.strip().isdecimal() for x in hfs_locations_str):
            HFS_LOCATIONS = [int(hfs_loc) for hfs_loc in hfs_locations_str]
        else:
            HFS_LOCATIONS = settings.HFS_LOCATIONS
            encountered_types = ''.join(list(set([type(x).__name__ for x in hfs_locations_str])))
            send_wrong_type_configuration_value_email('hfs_locations', encountered_types, 'int')
    else:
        HFS_LOCATIONS = settings.HFS_LOCATIONS
        send_missing_configuration_value_email('hfs_locations')
    return HFS_LOCATIONS


def get_hfs_epi_user_id():
    hfs_epi_user_id_record = Configuration.objects.filter(name='hfs_epi_user').first()
    if hfs_epi_user_id_record:
        if hfs_epi_user_id_record.value.isdecimal():
            HFS_EPI_USER_ID = hfs_epi_user_id_record.value
        else:
            HFS_EPI_USER_ID = settings.WHISPERS_ADMIN_USER_ID
            encountered_type = type(hfs_epi_user_id_record.value).__name__
            send_wrong_type_configuration_value_email('hfs_epi_user', encountered_type, 'int')
    else:
        HFS_EPI_USER_ID = settings.WHISPERS_ADMIN_USER_ID
        send_missing_configuration_value_email('hfs_epi_user')
    return HFS_EPI_USER_ID


def get_madison_epi_user_id():
    madison_epi_user_id_record = Configuration.objects.filter(name='madison_epi_user').first()
    if madison_epi_user_id_record:
        if madison_epi_user_id_record.value.isdecimal():
            MADISON_EPI_USER_ID = madison_epi_user_id_record.value
        else:
            MADISON_EPI_USER_ID = settings.WHISPERS_ADMIN_USER_ID
            encountered_type = type(madison_epi_user_id_record.value).__name__
            send_wrong_type_configuration_value_email('madison_epi_user', encountered_type, 'int')
    else:
        MADISON_EPI_USER_ID = settings.WHISPERS_ADMIN_USER_ID
        send_missing_configuration_value_email('madison_epi_user')
    return MADISON_EPI_USER_ID


def jsonify_errors(data):
    if isinstance(data, list) or isinstance(data, str):
        # Errors raised as a list are non-field errors.
        if hasattr(settings, 'NON_FIELD_ERRORS_KEY'):
            key = settings.NON_FIELD_ERRORS_KEY
        else:
            key = api_settings.NON_FIELD_ERRORS_KEY
        return {key: data}
    else:
        return data


def decode_json(response):
    try:
        content = response.json()
    except ValueError:
        content = {}
    return content


def get_user(context, initial_data):
    # TODO: figure out if this logic is necessary
    #  see: https://www.django-rest-framework.org/api-guide/requests/#user
    if 'request' in context and hasattr(context['request'], 'user'):
        user = context['request'].user
    elif 'created_by' in initial_data:
        user = User.objects.filter(id=initial_data['created_by']).first()
    else:
        raise serializers.ValidationError(
            jsonify_errors("User could not be identified, please contact the administrator."))
    return user


def determine_permission_source(user, obj):
    if not user.is_authenticated:
        permission_source = ''
    elif user.id == obj.created_by.id:
        permission_source = 'user'
    elif (user.organization.id == obj.created_by.organization.id
          or user.organization.id in obj.created_by.organization.child_organizations):
        permission_source = 'organization'
    elif ContentType.objects.get_for_model(obj, for_concrete_model=True).model == 'event':
        write_collaborators = list(User.objects.filter(writeevents__in=[obj.id]).values_list('id', flat=True))
        read_collaborators = list(User.objects.filter(readevents__in=[obj.id]).values_list('id', flat=True))
        if user.id in write_collaborators:
            permission_source = 'write_collaborators'
        elif user.id in read_collaborators:
            permission_source = 'read_collaborators'
        else:
            permission_source = ''
    else:
        permission_source = ''
    return permission_source


def construct_email(subject, message):
    # construct and send the email
    subject = subject
    body = message
    EMAIL_WHISPERS = get_whispers_email_address()
    from_address = EMAIL_WHISPERS
    to_list = [EMAIL_WHISPERS, ]
    bcc_list = []
    reply_list = []
    headers = None
    email = EmailMessage(subject, body, from_address, to_list, bcc_list, reply_to=reply_list, headers=headers)
    if settings.ENVIRONMENT in ['production', 'test']:
        try:
            email.send(fail_silently=False)
        except TypeError:
            message = "Send email failed, please contact the administrator."
            raise serializers.ValidationError(jsonify_errors(message))
    else:
        print(email.__dict__)
    return email


def calculate_priority_event_organization(instance):

    # calculate the priority value:
    # Sort by owner organization first, then by order of entry.
    priority = 1
    evt_orgs = EventOrganization.objects.filter(event=instance.event.id).order_by('created_by__organization__id', 'id')
    for evt_org in evt_orgs:
        if evt_org.id == instance.id:
            instance.priority = priority
        else:
            evt_org.priority = priority
            evt_org.save()
        priority += 1

    return instance.priority


def calculate_priority_event_diagnosis(instance):

    # calculate the priority value:
    # TODO: following rule cannot be applied because cause field does not exist on this model
    # Order event diagnoses by causal (cause of death first, then cause of sickness,
    # then incidental findings, then unknown) and within each causal category...
    # (TODO: NOTE following rule is valid and enforceable right now:)
    # ...by diagnosis name (alphabetical).
    priority = 1
    self_priority_updated = False
    # get all event_diagnoses for the parent event except self, and sort by diagnosis name ascending
    evtdiags = EventDiagnosis.objects.filter(
        event=instance.event.id).exclude(id=instance.id).order_by('diagnosis__name')
    for evtdiag in evtdiags:
        # if self has not been updated and self diagnosis less than or equal to this evtdiag diagnosis name,
        # first update self priority then update this evtdiag priority
        if not self_priority_updated and instance.diagnosis.name <= evtdiag.diagnosis.name:
            instance.priority = priority
            priority += 1
            self_priority_updated = True
        evtdiag.priority = priority
        evtdiag.save()
        priority += 1

    return instance.priority if self_priority_updated else priority


def calculate_priority_event_location(instance):

    # calculate the priority value:
    # Group by county first. Order counties by decreasing number of sick plus dead (for morbidity/mortality events)
    # or number_positive (for surveillance). Order locations within counties similarly.
    # TODO: figure out the following rule:
    # If no numbers provided then order by country, state, and county (alphabetical).
    priority = 1
    self_priority_updated = False
    # get all event_locations for the parent event except self, and sort by county name asc and affected count desc
    evtlocs = EventLocation.objects.filter(
        event=instance.event.id
    ).exclude(
        id=instance.id
    ).annotate(
        sick_ct=Sum('locationspecies__sick_count', filter=Q(event__event_type__exact=1))
    ).annotate(
        sick_ct_est=Sum('locationspecies__sick_count_estimated', filter=Q(event__event_type__exact=1))
    ).annotate(
        dead_ct=Sum('locationspecies__dead_count', filter=Q(event__event_type__exact=1))
    ).annotate(
        dead_ct_est=Sum('locationspecies__dead_count_estimated', filter=Q(event__event_type__exact=1))
    ).annotate(
        positive_ct=Sum('locationspecies__speciesdiagnoses__positive_count',
                        filter=Q(event__event_type__exact=2))
    ).annotate(
        affected_count=(Coalesce(F('sick_ct'), 0) + Coalesce(F('sick_ct_est'), 0) + Coalesce(F('dead_ct'), 0)
                        + Coalesce(F('dead_ct_est'), 0) + Coalesce(F('positive_ct'), 0))
    ).values(
        # use values function to avoid 'must appear in the GROUP BY clause or be used in an aggregate function' errors
        'id', 'administrative_level_two__name', 'affected_count'
    ).order_by('administrative_level_two__name', '-affected_count')
    if not evtlocs:
        instance.priority = priority
    else:
        location_species = LocationSpecies.objects.filter(event_location=instance.id)
        sick_dead_counts = [max(spec.dead_count_estimated or 0, spec.dead_count or 0)
                            + max(spec.sick_count_estimated or 0, spec.sick_count or 0)
                            for spec in location_species]
        self_sick_dead_count = sum(sick_dead_counts)
        loc_species_ids = [spec.id for spec in location_species]
        species_dx_positive_counts = SpeciesDiagnosis.objects.filter(
            location_species_id__in=loc_species_ids).values_list(
            'positive_count', flat=True).exclude(positive_count__isnull=True)
        self_positive_count = sum(species_dx_positive_counts)
        for evtloc in evtlocs:
            # if self has not been updated,
            # and self county name is less than or equal to this evtloc county name,
            # and self affected count is greater than or equal to this evtloc affected count
            # first update self priority then update this evtloc priority
            if (not self_priority_updated
                    and instance.administrative_level_two.name <= evtloc['administrative_level_two__name']):
                if instance.event.event_type.id == 1:
                    if self_sick_dead_count >= (evtloc['affected_count'] or 0):
                        instance.priority = priority
                        priority += 1
                        self_priority_updated = True
                elif instance.event.event_type.id == 2:
                    if self_positive_count >= (evtloc['affected_count'] or 0):
                        instance.priority = priority
                        priority += 1
                        self_priority_updated = True
            # update the evtloc (must retrieve object since we're using dicts in previous lines)
            el = EventLocation.objects.get(id=evtloc['id'])
            el.priority = priority
            el.save()
            priority += 1

    return instance.priority if self_priority_updated else priority


def calculate_priority_location_species(instance):

    # calculate the priority value:
    # Order species by decreasing number of sick plus dead (for morbidity/mortality events)
    # or number_positive (for surveillance).
    # If no numbers were provided then order by SpeciesName (alphabetical).
    priority = 1
    self_priority_updated = False
    # get all location_species for the parent event_location except self, and sort by affected count desc
    locspecs = LocationSpecies.objects.filter(
        event_location=instance.event_location.id
    ).exclude(
        id=instance.id
    ).annotate(
        sick_dead_ct=(Coalesce(F('sick_count'), 0) + Coalesce(F('sick_count_estimated'), 0)
                      + Coalesce(F('dead_count'), 0) + Coalesce(F('dead_count_estimated'), 0))
    ).annotate(
        positive_ct=Sum('speciesdiagnoses__positive_count', filter=Q(event_location__event__event_type__exact=2))
    ).annotate(
        affected_count=Coalesce(F('sick_dead_ct'), 0) + Coalesce(F('positive_ct'), 0)
    ).values(
        # use values function to avoid 'must appear in the GROUP BY clause or be used in an aggregate function' errors
        'id', 'affected_count'
    ).order_by('-affected_count', 'species__name')
    if not locspecs:
        instance.priority = priority
    else:
        self_sick_dead_count = (max(instance.dead_count_estimated or 0, instance.dead_count or 0)
                                + max(instance.sick_count_estimated or 0, instance.sick_count or 0))
        species_dx_positive_counts = SpeciesDiagnosis.objects.filter(
            location_species_id__exact=instance.id).values_list(
            'positive_count', flat=True).exclude(positive_count__isnull=True)
        self_positive_count = sum(species_dx_positive_counts)
        for locspec in locspecs:
            # if self has not been updated,
            # and self affected count is greater than or equal to this locspec affected count,
            # first update self priority then update this locspec priority
            if not self_priority_updated:
                if instance.event_location.event.event_type.id == 1:
                    if self_sick_dead_count >= (locspec['affected_count'] or 0):
                        instance.priority = priority
                        priority += 1
                        self_priority_updated = True
                elif instance.event_location.event.event_type.id == 2:
                    if self_positive_count >= (locspec['affected_count'] or 0):
                        instance.priority = priority
                        priority += 1
                        self_priority_updated = True
            # update the locspec (must retrieve object since we're using dicts in previous lines)
            ls = LocationSpecies.objects.get(id=locspec['id'])
            ls.priority = priority
            ls.save()
            priority += 1

    return instance.priority if self_priority_updated else priority


def calculate_priority_species_diagnosis(instance):

    # calculate the priority value:
    # TODO: the following...
    # Order species diagnoses by causal
    # (cause of death first, then cause of sickness, then incidental findings, then unknown)
    # and within each causal category by diagnosis name (alphabetical).
    priority = 1
    self_priority_updated = False
    # get all species_diagnoses for the parent location_species except self, and sort by diagnosis cause then name
    specdiags = SpeciesDiagnosis.objects.filter(
        location_species=instance.location_species.id).exclude(
        id=instance.id).order_by('cause__id', 'diagnosis__name')
    for specdiag in specdiags:
        # if self has not been updated and self diagnosis cause equal to or less than this specdiag diagnosis cause,
        # and self diagnosis name equal to or less than this specdiag diagnosis name
        # first update self priority then update this specdiag priority
        if not self_priority_updated:
            # first check if self diagnosis cause is equal to this specdiag diagnosis cause
            if instance.cause and specdiag.cause and instance.cause.id == specdiag.cause.id:
                if instance.diagnosis.name == specdiag.diagnosis.name:
                    instance.priority = priority
                    priority += 1
                    self_priority_updated = True
                elif instance.diagnosis.name < specdiag.diagnosis.name:
                    instance.priority = priority
                    priority += 1
                    self_priority_updated = True
            # else check if self diagnosis cause is less than this specdiag diagnosis cause
            elif instance.cause and specdiag.cause and instance.cause.id < specdiag.cause.id:
                if instance.diagnosis.name == specdiag.diagnosis.name:
                    instance.priority = priority
                    priority += 1
                    self_priority_updated = True
                elif instance.diagnosis.name < specdiag.diagnosis.name:
                    instance.priority = priority
                    priority += 1
                    self_priority_updated = True
                    # else check if both self diagnosis cause and this specdiag diagnosis cause are null
            elif instance.cause is None and specdiag.cause is None:
                if instance.diagnosis.name == specdiag.diagnosis.name:
                    instance.priority = priority
                    priority += 1
                    self_priority_updated = True
                elif instance.diagnosis.name < specdiag.diagnosis.name:
                    instance.priority = priority
                    priority += 1
                    self_priority_updated = True
        specdiag.priority = priority
        specdiag.save()
        priority += 1

    return instance.priority if self_priority_updated else priority


######
#
#  Misc
#
######


class CommentSerializer(serializers.ModelSerializer):
    def get_content_type_string(self, obj):
        return obj.content_type.model

    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    created_by_first_name = serializers.StringRelatedField(source='created_by.first_name')
    created_by_last_name = serializers.StringRelatedField(source='created_by.last_name')
    created_by_organization = serializers.StringRelatedField(source='created_by.organization.id')
    created_by_organization_string = serializers.StringRelatedField(source='created_by.organization.name')
    content_type_string = serializers.SerializerMethodField()
    new_content_type = serializers.CharField(write_only=True, required=False)

    def validate(self, data):
        if not self.instance:
            if 'object_id' not in data or data['object_id'] is None:
                raise serializers.ValidationError("object_id is required.")
            if 'new_content_type' not in data or data['new_content_type'] is None:
                raise serializers.ValidationError("new_content_type is required.")
            elif data['new_content_type'] not in COMMENT_CONTENT_TYPES:
                raise serializers.ValidationError("new_content_type mut be one of: " + ", ".join(COMMENT_CONTENT_TYPES))
        return data

    def create(self, validated_data):
        new_content_type = validated_data.pop('new_content_type')
        content_type = ContentType.objects.filter(app_label='whispersapi', model=new_content_type).first()
        content_object = content_type.model_class().objects.filter(id=validated_data['object_id']).first()
        if not content_object:
            message = "An object of type (" + str(new_content_type)
            message += ") and ID (" + str(validated_data['object_id']) + ") could not be found."
            raise serializers.ValidationError(jsonify_errors(message))
        comment = Comment.objects.create(**validated_data, content_object=content_object)

        # if this is a comment with a service request content type, create a 'Service Request Comment' notification
        if content_type.model == 'servicerequest':
            service_request = ServiceRequest.objects.filter(id=comment.object_id).first()
            event_id = service_request.event.id
            hfs_epi_user = User.objects.filter(id=get_hfs_epi_user_id()).first()
            madison_epi_user = User.objects.filter(id=get_madison_epi_user_id()).first()
            # source: NWHC Epi staff/HFS staff or user with read/write privileges
            # recipients: toggles between nwhc-epi@usgs or HFS AND user who made the request and event owner
            # email forwarding:
            #  Automatic, toggles between nwhc-epi@usgs or HFS AND user who made the request and event owner
            if comment.created_by.id in [hfs_epi_user.id, madison_epi_user.id]:
                msg_tmp = NotificationMessageTemplate.objects.filter(name='Service Request Comment').first()
                if not msg_tmp:
                    send_missing_notification_template_message_email('commentserializer_create',
                                                                     'Service Request Comment')
                else:
                    try:
                        subject = msg_tmp.subject_template.format(event_id=event_id)
                    except KeyError as e:
                        send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                        subject = ""
                    try:
                        body = msg_tmp.body_template.format(event_id=event_id)
                    except KeyError as e:
                        send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                        body = ""
                    source = comment.created_by.username
                    recipients = [service_request.created_by.id, service_request.event.created_by.id, ]
                    email_to = [service_request.created_by.email, service_request.event.created_by.email, ]
                    generate_notification.delay(recipients, source, event_id, 'event', subject, body, True, email_to)
            else:
                msg_tmp = NotificationMessageTemplate.objects.filter(name='Service Request Comment').first()
                if not msg_tmp:
                    send_missing_notification_template_message_email('commentserializer_create',
                                                                     'Service Request Comment')
                else:
                    try:
                        subject = msg_tmp.subject_template.format(event_id=event_id)
                    except KeyError as e:
                        send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                        subject = ""
                    try:
                        body = msg_tmp.body_template.format(event_id=event_id)
                    except KeyError as e:
                        send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                        body = ""
                    evt_locs = EventLocation.objects.filter(event=event_id)
                    HFS_LOCATIONS = get_hfs_locations()
                    if HFS_LOCATIONS and any(
                            [evt_loc.administrative_level_one.id in HFS_LOCATIONS for evt_loc in evt_locs]):
                        epi_user = hfs_epi_user
                    else:
                        epi_user = madison_epi_user
                    # comment created by service request creator and service request event's creator
                    if (comment.created_by.id == service_request.event.created_by.id
                            and comment.created_by.id == service_request.created_by.id):
                        recipients = [epi_user.id, ]
                        email_to = [epi_user.email, ]
                    # comment service request event's creator but not created by service request creator
                    elif (comment.created_by.id == service_request.event.created_by.id
                          and comment.created_by.id != service_request.created_by.id):
                        recipients = [epi_user.id, service_request.created_by.id, ]
                        email_to = [epi_user.email, service_request.created_by.email, ]
                    # comment created by service request creator but not service request event's creator
                    elif (comment.created_by.id != service_request.event.created_by.id
                          and comment.created_by.id == service_request.created_by.id):
                        recipients = [epi_user.id, service_request.event.created_by.id, ]
                        email_to = [epi_user.email, service_request.event.created_by.email, ]
                    # comment created by by neither service request creator nor service request event's creator
                    else:
                        recipients = [epi_user.id, service_request.created_by.id,
                                      service_request.event.created_by.id, ]
                        email_to = [epi_user.email, service_request.created_by.email,
                                    service_request.event.created_by.email, ]
                    source = comment.created_by.username
                    generate_notification.delay(recipients, source, event_id, 'event', subject, body, True, email_to)

        return comment

    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        # Do not allow the user to change the related content_type of object_id;
        # if they really need to make such a change, they should delete the comment and create a new one
        instance.comment = validated_data.get('comment', instance.comment)
        instance.comment_type = validated_data.get('comment_type', instance.comment_type)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modifed_by)

        instance.save()
        return instance

    class Meta:
        model = Comment
        fields = ('id', 'comment', 'comment_type', 'object_id', 'content_type_string', 'new_content_type',
                  'created_date', 'created_by', 'created_by_string', 'created_by_first_name', 'created_by_last_name',
                  'created_by_organization', 'created_by_organization_string',
                  'modified_date', 'modified_by', 'modified_by_string',)
        extra_kwargs = {'object_id': {'required': False}}


class CommentTypeSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = CommentType
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class ArtifactSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = Artifact
        fields = ('id', 'filename', 'keywords', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


######
#
#  Events
#
######


# TODO: validate expected fields and field data types for all submitted nested objects
class EventSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    staff_string = serializers.StringRelatedField(source='staff')
    event_status_string = serializers.StringRelatedField(source='event_status')
    legal_status_string = serializers.StringRelatedField(source='legal_status')
    comments = CommentSerializer(many=True, read_only=True)
    new_event_diagnoses = serializers.ListField(write_only=True, required=False)
    new_organizations = serializers.ListField(write_only=True, required=False)
    new_comments = serializers.ListField(write_only=True, required=False)
    new_event_locations = serializers.ListField(write_only=True, required=False)
    new_eventgroups = serializers.ListField(write_only=True, required=False)
    new_service_request = serializers.JSONField(write_only=True, required=False)
    new_read_collaborators = serializers.ListField(write_only=True, required=False)
    new_write_collaborators = serializers.ListField(write_only=True, required=False)
    service_request_email = serializers.JSONField(read_only=True)

    def get_permission_source(self, obj):
        return determine_permission_source(self.context['request'].user, obj)

    def validate(self, data):

        # if this is a new Event
        if not self.instance:
            if 'new_event_locations' not in data:
                raise serializers.ValidationError("new_event_locations is a required field")
            # 1. Not every location needs a start date at initiation, but at least one location must.
            # 2. Not every location needs a species at initiation, but at least one location must.
            # 3. location_species Population >= max(estsick, knownsick) + max(estdead, knowndead)
            # 4. For morbidity/mortality events, there must be at least one number between sick, dead, estimated_sick,
            #    and estimated_dead for at least one species in the event at the time of event initiation.
            #    (sick + dead + estimated_sick + estimated_dead >= 1)
            # 5. If present, estimated_sick must be higher than known sick (estimated_sick > sick).
            # 6. If present, estimated dead must be higher than known dead (estimated_dead > dead).
            # 7. Every location needs at least one comment, which must be one of the following types:
            #    Site description, History, Environmental factors, Clinical signs
            # 8. Standardized lat/long format (e.g., decimal degrees WGS84). Update county, state, and country
            #    if county is null.  Update state and country if state is null. If don't enter country, state, and
            #    county at initiation, then have to enter lat/long, which would autopopulate country, state, and county.
            # 9. Ensure admin level 2 actually belongs to admin level 1 which actually belongs to country.
            # 10. Location start date cannot be after today if event type is Mortality/Morbidity
            # 11. Location end date must be equal to or greater than start date.
            # 12: Non-suspect diagnosis cannot have basis_of_dx = 1,2, or 4.  If 3 is selected user must provide a lab.
            # 13: A diagnosis can only be used once for a location-species-labID combination
            if 'new_event_locations' in data:
                country_admin_is_valid = True
                latlng_is_valid = True
                latlng_country_found = True
                latlng_matches_country = True
                latlng_matches_admin_l1 = True
                latlng_matches_admin_21 = True
                comments_is_valid = []
                required_comment_types = ['site_description', 'history', 'environmental_factors', 'clinical_signs']
                min_start_date = False
                start_date_is_valid = True
                end_date_is_valid = True
                min_location_species = False
                min_species_count = False
                pop_is_valid = []
                est_sick_is_valid = True
                est_dead_is_valid = True
                specdiag_nonsuspect_basis_is_valid = True
                specdiag_lab_is_valid = True
                details = []
                mortality_morbidity = EventType.objects.filter(name='Mortality/Morbidity').first()
                for item in data['new_event_locations']:
                    if [i for i in required_comment_types if i in item and item[i]]:
                        comments_is_valid.append(True)
                    else:
                        comments_is_valid.append(False)
                    if 'start_date' in item and item['start_date'] is not None:
                        try:
                            datetime.strptime(item['start_date'], '%Y-%m-%d').date()
                        except ValueError:
                            details.append("All start_date values must be valid dates in ISO format ('YYYY-MM-DD').")
                        min_start_date = True
                        if (data['event_type'].id == mortality_morbidity.id
                                and datetime.strptime(item['start_date'], '%Y-%m-%d').date() > date.today()):
                            start_date_is_valid = False
                        if ('end_date' in item and item['end_date'] is not None
                                and item['end_date'] < item['start_date']):
                            end_date_is_valid = False
                    elif 'end_date' in item and item['end_date'] is not None:
                        end_date_is_valid = False
                    if ('country' in item and item['country'] is not None and 'administrative_level_one' in item
                            and item['administrative_level_one'] is not None):
                        country = Country.objects.filter(id=item['country']).first()
                        admin_l1 = AdministrativeLevelOne.objects.filter(id=item['administrative_level_one']).first()
                        if country.id != admin_l1.country.id:
                            country_admin_is_valid = False
                        if 'administrative_level_two' in item and item['administrative_level_two'] is not None:
                            admin_l2 = AdministrativeLevelTwo.objects.filter(
                                id=item['administrative_level_two']).first()
                            if admin_l1.id != admin_l2.administrative_level_one.id:
                                country_admin_is_valid = False
                    if (('country' not in item or item['country'] is None or 'administrative_level_one' not in item
                         or item['administrative_level_one'] is None)
                            and ('latitude' not in item or item['latitude'] is None
                                 or 'longitude' not in item and item['longitude'] is None)):
                        message = "country and administrative_level_one are required if latitude or longitude is null."
                        details.append(message)
                    if ('latitude' in item and item['latitude'] is not None
                            and not re.match(r"(-?)([\d]{1,2})(\.)(\d+)", str(item['latitude']))):
                        latlng_is_valid = False
                    if ('longitude' in item and item['longitude'] is not None
                            and not re.match(r"(-?)([\d]{1,3})(\.)(\d+)", str(item['longitude']))):
                                                latlng_is_valid = False
                    # NOTE: the following validations are also done in the EventLocation serializer,
                    #  so I'm commenting these to prevent two identical emails being sent to the admins
                    # geonames_endpoint = 'extendedFindNearbyJSON'
                    # GEONAMES_USERNAME = get_geonames_username()
                    # GEONAMES_API = get_geonames_api()
                    # if (latlng_is_valid
                    #         and 'latitude' in item and item['latitude'] is not None
                    #         and 'longitude' in item and item['longitude'] is not None
                    #         and 'country' in item and item['country'] is not None):
                    #     payload = {'lat': item['latitude'], 'lng': item['longitude'], 'username': GEONAMES_USERNAME}
                    #     r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                    #     geonames_latlng_url = r.request.url
                    #     try:
                    #         geonames_object_list = decode_json(r)
                    #         if 'address' in geonames_object_list:
                    #             address = geonames_object_list['address']
                    #             if 'name' in address:
                    #                 address['adminName2'] = address['name']
                    #         elif 'geonames' in geonames_object_list:
                    #             geonames_objects_adm2 = [item for item in geonames_object_list['geonames'] if
                    #                                      item['fcode'] == 'ADM2']
                    #             # NOTE: some countries have fcode of PPL (city) instead of ADM2 immediately below ADM1,
                    #             #  which are not in our database at this time, so skip over this
                    #             address = geonames_objects_adm2[0] if geonames_objects_adm2 else None
                    #         else:
                    #             # the response from the Geonames web service is in an unexpected format
                    #             address = None
                    #     except requests.exceptions.RequestException as e:
                    #         # email admins
                    #         send_third_party_service_exception_email('Geonames', GEONAMES_API + geonames_endpoint, e)
                    #         address = None
                    #     geonames_endpoint = 'countryInfoJSON'
                    #     if address:
                    #         country = None
                    #         country_code = address['countryCode']
                    #         if len(country_code) == 2:
                    #             payload = {'country': country_code, 'username': GEONAMES_USERNAME}
                    #             r = requests.get(GEONAMES_API + geonames_endpoint, params=payload,
                    #                              verify=settings.SSL_CERT)
                    #             try:
                    #                 content = decode_json(r)
                    #                 if ('geonames' in content and content['geonames'] is not None
                    #                         and len(content['geonames']) > 0
                    #                         and 'isoAlpha3' in content['geonames'][0]):
                    #                     alpha3 = content['geonames'][0]['isoAlpha3']
                    #                     country = Country.objects.filter(abbreviation=alpha3).first()
                    #             except requests.exceptions.RequestException as e:
                    #                 # email admins
                    #                 send_third_party_service_exception_email(
                    #                     'Geonames', GEONAMES_API + geonames_endpoint, e)
                    #         elif len(country_code) == 3:
                    #             country = Country.objects.filter(abbreviation=country_code).first()
                    #         if not country:
                    #             # Instead of causing a validation error, email admins and let the create proceed
                    #             # latlng_country_found = False
                    #             message = f"Geonames returned a Country ({country_code})"
                    #             message += " that could not be found in the WHISPers database"
                    #             message += f" when using the latitude and longitude submitted by the user"
                    #             message += f" ({item['longitude']}, {item['latitude']})."
                    #             message += f" The request made to Geonames was: {geonames_latlng_url}"
                    #             construct_email("WHISPERS ADMIN: Third Party Service Validation Warning", message)
                    #         elif int(item['country']) != country.id:
                    #             # Instead of causing a validation error, email admins and let the create proceed
                    #             # latlng_matches_country = False
                    #             user_country = Country.objects.filter(id=item['country']).first()
                    #             user_country = user_country.name if user_country else item['country']
                    #             message = f"Geonames returned a Country ({country_code})"
                    #             message += " different from the one submitted by the user"
                    #             message += f" ({user_country}) when using the latitude"
                    #             message += " and longitude submitted by the user"
                    #             message += f" ({item['longitude']}, {item['latitude']})."
                    #             message += f" The request made to Geonames was: {geonames_latlng_url}"
                    #             construct_email("WHISPERS ADMIN: Third Party Service Validation Warning", message)
                    #         elif 'administrative_level_one' in item and item['administrative_level_one'] is not None:
                    #             admin_l1 = AdministrativeLevelOne.objects.filter(name=address['adminName1']).first()
                    #             if not admin_l1 or int(item['administrative_level_one']) != admin_l1.id:
                    #                 # Instead of causing a validation error, email admins and let the create proceed
                    #                 # latlng_matches_admin_l1 = False
                    #                 user_al1 = AdministrativeLevelOne.objects.filter(
                    #                     id=item['administrative_level_one']).first()
                    #                 user_al1 = user_al1.name if user_al1 else item['administrative_level_one']
                    #                 message = f"Geonames returned an Administrative Level One ({address['adminName1']})"
                    #                 message += " different from the one submitted by the user"
                    #                 message += f" ({user_al1}) when using the latitude"
                    #                 message += " and longitude submitted by the user"
                    #                 message += f" ({item['longitude']}, {item['latitude']})."
                    #                 message += f" The request made to Geonames was: {geonames_latlng_url}"
                    #                 construct_email("WHISPERS ADMIN: Third Party Service Validation Warning", message)
                    #             elif ('administrative_level_two' in item
                    #                   and item['administrative_level_two'] is not None):
                    #                 admin_name2 = address['adminName2'] if 'adminName2' in address else address['name']
                    #                 admin_l2 = AdministrativeLevelTwo.objects.filter(
                    #                     name__icontains=admin_name2, administrative_level_one__id=admin_l1.id).first()
                    #                 if not admin_l2 or int(item['administrative_level_two']) != admin_l2.id:
                    #                     # Instead of causing a validation error, email admins and let the create proceed
                    #                     # latlng_matches_admin_21 = False
                    #                     user_al2 = AdministrativeLevelTwo.objects.filter(
                    #                         id=item['administrative_level_two']).first()
                    #                     user_al2 = user_al2.name if user_al2 else item['administrative_level_two']
                    #                     message = f"Geonames returned an Administrative Level Two ({admin_name2})"
                    #                     message += " different from the one submitted by the user"
                    #                     message += f" ({user_al2}) when using the latitude"
                    #                     message += " and longitude submitted by the user"
                    #                     message += f" ({item['longitude']}, {item['latitude']})."
                    #                     message += f" The request made to Geonames was: {geonames_latlng_url}"
                    #                     construct_email("WHISPERS ADMIN: Third Party Service Validation Warning",
                    #                                     message)
                    #     else:
                    #         # Instead of causing a validation error, email admins and let the create proceed
                    #         message = f"Geonames returned data in an unexpected format"
                    #         message += " that could not be validated against data in the WHISPers database"
                    #         message += f" when using the latitude and longitude submitted by the user"
                    #         message += f" ({data['longitude']}, {data['latitude']})."
                    #         message += f" The request made to Geonames was: {geonames_latlng_url}"
                    #         construct_email("WHISPERS ADMIN: Third Party Service Validation Warning", message)
                    if 'new_location_species' in item:
                        for spec in item['new_location_species']:
                            if 'species' in spec and spec['species'] is not None:
                                if Species.objects.filter(id=spec['species']).first() is None:
                                    message = "A submitted species ID (" + str(spec['species'])
                                    message += ") in new_location_species was not found in the database."
                                    details.append(message)
                                else:
                                    min_location_species = True
                            if 'population_count' in spec and spec['population_count'] is not None:
                                dead_count = 0
                                sick_count = 0
                                if 'dead_count_estimated' in spec or 'dead_count' in spec:
                                    dead_count = max(spec.get('dead_count_estimated') or 0, spec.get('dead_count') or 0)
                                if 'sick_count_estimated' in spec or 'sick_count' in spec:
                                    sick_count = max(spec.get('sick_count_estimated') or 0, spec.get('sick_count') or 0)
                                if spec['population_count'] >= dead_count + sick_count:
                                    pop_is_valid.append(True)
                                else:
                                    pop_is_valid.append(False)
                            if ('sick_count_estimated' in spec and spec['sick_count_estimated'] is not None
                                    and 'sick_count' in spec and spec['sick_count'] is not None
                                    and not spec['sick_count_estimated'] > spec['sick_count']):
                                est_sick_is_valid = False
                            if ('dead_count_estimated' in spec and spec['dead_count_estimated'] is not None
                                    and 'dead_count' in spec and spec['dead_count'] is not None
                                    and not spec['dead_count_estimated'] > spec['dead_count']):
                                est_dead_is_valid = False
                            if data['event_type'].id == mortality_morbidity.id:
                                if ('dead_count_estimated' in spec and spec['dead_count_estimated'] is not None
                                        and spec['dead_count_estimated'] > 0):
                                    min_species_count = True
                                elif ('dead_count' in spec and spec['dead_count'] is not None
                                      and spec['dead_count'] > 0):
                                    min_species_count = True
                                elif ('sick_count_estimated' in spec and spec['sick_count_estimated'] is not None
                                      and spec['sick_count_estimated'] > 0):
                                    min_species_count = True
                                elif ('sick_count' in spec and spec['sick_count'] is not None
                                      and spec['sick_count'] > 0):
                                    min_species_count = True
                            if 'new_species_diagnoses' in spec and spec['new_species_diagnoses'] is not None:
                                specdiag_labs = []
                                for specdiag in spec['new_species_diagnoses']:
                                    [specdiag_labs.append((specdiag['diagnosis'], specdiag_lab)) for specdiag_lab in
                                     specdiag['new_species_diagnosis_organizations']]
                                    if not specdiag['suspect']:
                                        if specdiag['basis'] in [1, 2, 4]:
                                            undetermined = list(Diagnosis.objects.filter(
                                                name='Undetermined').values_list('id', flat=True))[0]
                                            if specdiag['diagnosis'] != undetermined:
                                                specdiag_nonsuspect_basis_is_valid = False
                                        elif specdiag['basis'] == 3:
                                            if ('new_species_diagnosis_organizations' in specdiag
                                                    and specdiag['new_species_diagnosis_organizations'] is not None):
                                                for org_id in specdiag['new_species_diagnosis_organizations']:
                                                    org = Organization.objects.filter(id=org_id).first()
                                                    if not org or not org.laboratory:
                                                        specdiag_nonsuspect_basis_is_valid = False
                                if len(specdiag_labs) != len(set(specdiag_labs)):
                                    specdiag_lab_is_valid = False
                    if 'new_location_contacts' in item and item['new_location_contacts'] is not None:
                        for loc_contact in item['new_location_contacts']:
                            if 'contact' not in loc_contact or loc_contact['contact'] is None:
                                message = "A required contact ID was not included in new_location_contacts."
                                details.append(message)
                            elif Contact.objects.filter(id=loc_contact['contact']).first() is None:
                                message = "A submitted contact ID (" + str(loc_contact['contact'])
                                message += ") in new_location_contacts was not found in the database."
                                details.append(message)
                if not country_admin_is_valid:
                    message = "administrative_level_one must belong to the submitted country,"
                    message += " and administrative_level_two must belong to the submitted administrative_level_one."
                    details.append(message)
                if not start_date_is_valid:
                    message = "If event_type is 'Mortality/Morbidity'"
                    message += " start_date for a new event_location must be current date or earlier."
                    details.append(message)
                if not end_date_is_valid:
                    details.append("end_date may not be before start_date.")
                if not latlng_is_valid:
                    message = "latitude and longitude must be in decimal degrees and represent a point in a country."
                    details.append(message)
                if not latlng_country_found:
                    message = "A country matching the submitted latitude and longitude could not be found."
                    details.append(message)
                if not latlng_matches_country:
                    message = "latitude and longitude are not in the user-specified country."
                    details.append(message)
                if not latlng_matches_admin_l1:
                    message = "latitude and longitude are not in"
                    message += " the user-specified administrative level one (e.g., state)."
                    details.append(message)
                if not latlng_matches_admin_21:
                    message = "latitude and longitude are not in"
                    message += " the user-specified administrative level two (e.g., county)."
                    details.append(message)
                if False in comments_is_valid:
                    message = "Each new_event_location requires at least one new_comment, which must be one of"
                    message += " the following types: Site description, History, Environmental factors, Clinical signs"
                    details.append(message)
                if not min_start_date:
                    details.append("start_date is required for at least one new event_location.")
                if not min_location_species:
                    details.append("Each new_event_location requires at least one new_location_species.")
                if False in pop_is_valid:
                    message = "new_location_species population_count cannot be less than the sum of dead_count"
                    message += " and sick_count (where those counts are the maximum of the estimated or known count)."
                    details.append(message)
                if data['event_type'].id == mortality_morbidity.id and not min_species_count:
                    message = "For Mortality/Morbidity events, at least one new_location_species requires"
                    message += " at least one species count in any of the following fields:"
                    message += " dead_count_estimated, dead_count, sick_count_estimated, sick_count."
                    details.append(message)
                if not est_sick_is_valid:
                    details.append("Estimated sick count must always be more than known sick count.")
                if not est_dead_is_valid:
                    details.append("Estimated dead count must always be more than known dead count.")
                if not specdiag_nonsuspect_basis_is_valid:
                    message = "A non-suspect diagnosis can only have a basis of"
                    message += " 'Necropsy and/or ancillary tests performed at a diagnostic laboratory'"
                    message += " and only if that diagnosis has a related laboratory"
                    details.append(message)
                if not specdiag_lab_is_valid:
                    message = "A diagnosis can only be used once for any combination of a location, species, and lab."
                    details.append(message)
                if details:
                    raise serializers.ValidationError(details)

            # 1. End Date is Mandatory for event to be marked as 'Complete'. Should always be same or after Start Date.
            # 2. For morbidity/mortality events, there must be at least one number between sick, dead, estimated_sick,
            #   and estimated_dead per species at the time of event completion.
            #   (sick + dead + estimated_sick + estimated_dead >= 1)
            if 'complete' in data and data['complete'] is True:
                location_message = "The event may not be marked complete until all of its locations have an end date"
                location_message += " and each location's end date is same as or after that location's start date."
                end_date_is_valid = True
                species_count_is_valid = []
                est_sick_is_valid = True
                est_dead_is_valid = True
                specdiag_basis_is_valid = True
                specdiag_cause_is_valid = True
                details = []
                mortality_morbidity = EventType.objects.filter(name='Mortality/Morbidity').first()
                for item in data['new_event_locations']:
                    if ('start_date' in item and item['start_date'] is not None
                            and 'end_date' in item and item['end_date'] is not None):
                        try:
                            start_date = datetime.strptime(item['start_date'], '%Y-%m-%d').date()
                        except ValueError:
                            # use a fake date to prevent type comparison error in "if not start_date < end_date"
                            start_date = datetime.now().date
                            details.append("All start_date values must be valid ISO format dates (YYYY-MM-DD).")
                        try:
                            end_date = datetime.strptime(item['end_date'], '%Y-%m-%d').date()
                        except ValueError:
                            # use a fake date to prevent type comparison error in "if not start_date < end_date"
                            end_date = datetime.now().date() + timedelta(days=1)
                            details.append("All end_date values must be valid ISO format dates (YYYY-MM-DD).")
                        if not start_date <= end_date:
                            end_date_is_valid = False
                    else:
                        end_date_is_valid = False
                    for spec in item['new_location_species']:
                        if ('sick_count_estimated' in spec and spec['sick_count_estimated'] is not None
                                and 'sick_count' in spec and spec['sick_count'] is not None
                                and not spec['sick_count_estimated'] > spec['sick_count']):
                            est_sick_is_valid = False
                        if ('dead_count_estimated' in spec and spec['dead_count_estimated'] is not None
                                and 'dead_count' in spec and spec['dead_count'] is not None
                                and not spec['dead_count_estimated'] > spec['dead_count']):
                            est_dead_is_valid = False
                        if data['event_type'].id == mortality_morbidity.id:
                            if ('dead_count_estimated' in spec and spec['dead_count_estimated'] is not None
                                    and spec['dead_count_estimated'] > 0):
                                species_count_is_valid.append(True)
                            elif ('dead_count' in spec and spec['dead_count'] is not None
                                  and spec['dead_count'] > 0):
                                species_count_is_valid.append(True)
                            elif ('sick_count_estimated' in spec and spec['sick_count_estimated'] is not None
                                  and spec['sick_count_estimated'] > 0):
                                species_count_is_valid.append(True)
                            elif ('sick_count' in spec and spec['sick_count'] is not None
                                  and spec['sick_count'] > 0):
                                species_count_is_valid.append(True)
                            else:
                                species_count_is_valid.append(False)
                        if 'new_species_diagnoses' in spec and spec['new_species_diagnoses'] is not None:
                            for specdiag in spec['new_species_diagnoses']:
                                if 'basis' not in specdiag or specdiag['basis'] is None:
                                    specdiag_basis_is_valid = False
                                if 'cause' not in specdiag or specdiag['cause'] is None:
                                    specdiag_cause_is_valid = False
                        else:
                            specdiag_basis_is_valid = False
                            specdiag_cause_is_valid = False
                if not end_date_is_valid:
                    details.append(location_message)
                if False in species_count_is_valid:
                    message = "Each new_location_species requires at least one species count in any of these"
                    message += " fields: dead_count_estimated, dead_count, sick_count_estimated, sick_count."
                    details.append(message)
                if not est_sick_is_valid:
                    details.append("Estimated sick count must always be more than known sick count.")
                if not est_dead_is_valid:
                    details.append("Estimated dead count must always be more than known dead count.")
                if not specdiag_basis_is_valid:
                    details.append("Each new_location_species requires a basis of diagnosis")
                if not specdiag_cause_is_valid:
                    details.append("Each new_location_species requires a significance of diagnosis for species (cause)")
                if details:
                    raise serializers.ValidationError(details)
        return data

    def create(self, validated_data):
        # set the FULL_EVENT_CHAIN_CREATE variable to True in case there is an error somewhere in the chain
        # and all objects created by this request before the error need to be deleted
        FULL_EVENT_CHAIN_CREATE = True

        # pull out child event diagnoses list from the request
        new_event_diagnoses = validated_data.pop('new_event_diagnoses', None)

        # pull out child organizations list from the request
        new_organizations = validated_data.pop('new_organizations', None)

        # pull out child comments list from the request
        new_comments = validated_data.pop('new_comments', None)

        # pull out child event_locations list from the request
        new_event_locations = validated_data.pop('new_event_locations', None)

        # pull out child eventgroups list from the request
        new_eventgroups = validated_data.pop('new_eventgroups', None)

        # pull out child service request from the request
        new_service_request = validated_data.pop('new_service_request', None)

        # pull out user ID list from the request
        if 'new_read_collaborators' in validated_data:
            new_read_collaborators = validated_data.pop('new_read_collaborators', None)
            new_read_user_ids_prelim = set(new_read_collaborators) if new_read_collaborators else set([])
        else:
            new_read_user_ids_prelim = set([])
        if 'new_write_collaborators' in validated_data:
            new_write_collaborators = validated_data.pop('new_write_collaborators', None)
            new_write_user_ids = set(new_write_collaborators) if new_write_collaborators else set([])
        else:
            new_write_user_ids = set([])

        # remove users from the read list if they are also in the write list (these lists are already unique sets)
        new_read_user_ids = new_read_user_ids_prelim - new_write_user_ids

        event = Event.objects.create(**validated_data)

        # create the child event_locations for this event
        if new_event_locations is not None:
            is_valid = True
            valid_data = []
            errors = []
            for event_location in new_event_locations:
                if event_location is not None:
                    # use event to populate event field on event_location
                    event_location['event'] = event.id
                    event_location['created_by'] = event.created_by.id
                    event_location['modified_by'] = event.modified_by.id
                    event_location['FULL_EVENT_CHAIN_CREATE'] = FULL_EVENT_CHAIN_CREATE
                    evt_loc_serializer = EventLocationSerializer(data=event_location)
                    if evt_loc_serializer.is_valid():
                        valid_data.append(evt_loc_serializer)
                    else:
                        is_valid = False
                        errors.append(evt_loc_serializer.errors)
            if is_valid:
                # now that all items are proven valid, save and return them to the user
                for item in valid_data:
                    item.save()
            else:
                # delete this event (related collaborators, organizations, eventgroups, service requests,
                # contacts, and comments will be cascade deleted automatically if any exist)
                event.delete()
                raise serializers.ValidationError(jsonify_errors(errors))

        user = get_user(self.context, self.initial_data)

        # create the child collaborators for this event
        if new_read_user_ids is not None:
            for read_user_id in new_read_user_ids:
                read_user = User.objects.filter(id=read_user_id).first()
                if read_user is not None and not read_user.id == event.created_by.id:
                    # only create collaborator if not the event owner
                    EventReadUser.objects.create(user=read_user, event=event, created_by=user, modified_by=user)

        if new_write_user_ids is not None:
            for write_user_id in new_write_user_ids:
                write_user = User.objects.filter(id=write_user_id).first()
                if write_user is not None and not write_user.id == event.created_by.id:
                    # only create collaborator if not the event owner
                    EventWriteUser.objects.create(user=write_user, event=event, created_by=user, modified_by=user)

        # create the child organizations for this event
        if new_organizations is not None:
            # only create unique records (silently ignore duplicates submitted by user)
            new_unique_organizations = list(set(new_organizations))
            for org_id in new_unique_organizations:
                if org_id is not None:
                    org = Organization.objects.filter(id=org_id).first()
                    if org is not None:
                        event_org = EventOrganization.objects.create(event=event, organization=org,
                                                                     created_by=user, modified_by=user)
                        event_org.priority = calculate_priority_event_organization(event_org)
                        event_org.save(update_fields=['priority', ])
        else:
            event_org = EventOrganization.objects.create(event=event, organization=user.organization,
                                                         created_by=user, modified_by=user)
            event_org.priority = calculate_priority_event_organization(event_org)
            event_org.save(update_fields=['priority', ])

        # create the child comments for this event
        if new_comments is not None:
            for comment in new_comments:
                if comment is not None:
                    if 'comment_type' in comment and comment['comment_type'] is not None:
                        comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                        if comment_type is not None:
                            Comment.objects.create(content_object=event, comment=comment['comment'],
                                                   comment_type=comment_type,
                                                   created_by=user, modified_by=user)

        # create the child eventgroups for this event
        if new_eventgroups is not None:
            for eventgroup_id in new_eventgroups:
                if eventgroup_id is not None:
                    eventgroup = EventGroup.objects.filter(id=eventgroup_id).first()
                    if eventgroup is not None:
                        EventEventGroup.objects.create(event=event, eventgroup=eventgroup,
                                                       created_by=user, modified_by=user)

        # create the child event diagnoses for this event

        # remove Pending if in the list because it should never be submitted by the user
        # and remove Undetermined if in the list and the event already has an Undetermined
        pending = list(Diagnosis.objects.filter(name='Pending').values_list('id', flat=True))[0]
        undetermined = list(Diagnosis.objects.filter(name='Undetermined').values_list('id', flat=True))[0]
        existing_evt_diag_ids = list(EventDiagnosis.objects.filter(event=event.id).values_list('diagnosis', flat=True))
        if len(existing_evt_diag_ids) > 0 and undetermined in existing_evt_diag_ids:
            rm_dg = [pending, undetermined]
        else:
            rm_dg = [pending, ]
        new_evt_dg = new_event_diagnoses
        [new_evt_dg.remove(x) for x in new_evt_dg if x['diagnosis'] is not None and int(x['diagnosis']) in rm_dg]

        if new_evt_dg:
            is_valid = True
            valid_data = []
            errors = []
            for event_diagnosis in new_evt_dg:
                if event_diagnosis is not None:
                    # use event to populate event field on event_diagnosis
                    event_diagnosis['event'] = event.id
                    event_diagnosis['created_by'] = event.created_by.id
                    event_diagnosis['modified_by'] = event.modified_by.id
                    event_diagnosis['FULL_EVENT_CHAIN_CREATE'] = FULL_EVENT_CHAIN_CREATE
                    evt_diag_serializer = EventDiagnosisSerializer(data=event_diagnosis)
                    if evt_diag_serializer.is_valid():
                        valid_data.append(evt_diag_serializer)
                    else:
                        is_valid = False
                        errors.append(evt_diag_serializer.errors)
            if is_valid:
                # now that all items are proven valid, save and return them to the user
                for item in valid_data:
                    item.save()
            else:
                # delete this event (related collaborators, organizations, eventgroups, service requests,
                # contacts, and comments will be cascade deleted automatically if any exist)
                event.delete()
                raise serializers.ValidationError(jsonify_errors(errors))

            # # Can only use diagnoses that are already used by this event's species diagnoses
            # valid_diagnosis_ids = list(SpeciesDiagnosis.objects.filter(
            #     location_species__event_location__event=event.id
            # ).exclude(id__in=[pending, undetermined]).values_list('diagnosis', flat=True).distinct())
            # # If any new event diagnoses have a matching species diagnosis, then continue, else ignore
            # if valid_diagnosis_ids is not None:
            #     new_event_diagnoses_created = []
            #     for event_diagnosis in new_event_diagnoses:
            #         diagnosis_id = int(event_diagnosis.pop('diagnosis', None))
            #         if diagnosis_id in valid_diagnosis_ids:
            #             # ensure this new event diagnosis has the correct suspect value
            #             # (false if any matching species diagnoses are false, otherwise true)
            #             diagnosis = Diagnosis.objects.filter(pk=diagnosis_id).first()
            #             matching_specdiags_suspect = SpeciesDiagnosis.objects.filter(
            #                 location_species__event_location__event=event.id, diagnosis=diagnosis_id
            #             ).values_list('suspect', flat=True)
            #             suspect = False if False in matching_specdiags_suspect else True
            #             event_diagnosis = EventDiagnosis.objects.create(**event_diagnosis, event=event,
            #                                                             diagnosis=diagnosis, suspect=suspect,
            #                                                             created_by=user, modified_by=user)
            #             event_diagnosis.priority = calculate_priority_event_diagnosis(event_diagnosis)
            #             event_diagnosis.save(update_fields=['priority', ])
            #             new_event_diagnoses_created.append(event_diagnosis)
            #     # If any new event diagnoses were created, check for existing Pending record and delete it
            #     if len(new_event_diagnoses_created) > 0:
            #         event_diagnoses = EventDiagnosis.objects.filter(event=event.id)
            #         [diag.delete() for diag in event_diagnoses if diag.diagnosis.id == pending]

        # Create the child service requests for this event
        if new_service_request is not None:
            if ('request_type' in new_service_request and new_service_request['request_type'] is not None
                    and new_service_request['request_type'] in [1, 2]):
                request_type = ServiceRequestType.objects.filter(id=new_service_request['request_type']).first()
                # request_response = ServiceRequestResponse.objects.filter(name='Pending').first()
                admin = User.objects.filter(id=get_whispers_admin_user_id()).first()
                # use event to populate event field on new_service_request
                new_service_request['event'] = event.id
                new_service_request['request_type'] = request_type.id
                # new_service_request['request_response'] = request_response.id
                new_service_request['response_by'] = admin.id
                new_service_request['created_by'] = event.created_by.id
                new_service_request['modified_by'] = event.modified_by.id
                new_service_request['FULL_EVENT_CHAIN_CREATE'] = FULL_EVENT_CHAIN_CREATE
                service_request_serializer = ServiceRequestSerializer(data=new_service_request)
                if service_request_serializer.is_valid():
                    service_request_serializer.save()
                else:
                    # delete this event (related collaborators, organizations, eventgroups, service requests,
                    # contacts, and comments will be cascade deleted automatically if any exist)
                    event.delete()
                    raise serializers.ValidationError(jsonify_errors(service_request_serializer.errors))

        return event

    # on update, any submitted nested objects (new_organizations, new_comments, new_event_locations) will be ignored
    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        new_complete = validated_data.get('complete', None)
        quality_check = validated_data.get('quality_check', None)

        # if event is complete only a few things are permitted (admin can set quality_check or reopen event)
        if instance.complete:
            if user.role.is_superadmin or user.role.is_admin:
                # if the event is complete and the quality_check field is included and set to a date,
                # update the quality_check field and return the event
                # (ignoring any other submitted changes since the event is 'locked' by virtue of being complete)
                if quality_check:
                    instance.quality_check = quality_check
                    instance.modified_by = validated_data.get('modified_by', instance.modified_by)
                    instance.save()
                    return instance
                # if the event is complete and the complete field is not included or True, the event cannot be changed
                if new_complete is None or new_complete:
                    message = "Complete events may not be changed"
                    message += " unless the event owner or an administrator first re-opens the event"
                    message += " OR the event owner or an administrator also re-opens the event in the same request"
                    message += "  (by including the 'complete' field in the request and setting it to False)."
                    raise serializers.ValidationError(jsonify_errors(message))
            else:
                # only event owner or higher roles can re-open ('un-complete') a closed ('completed') event
                # but if the complete field is not included or set to True, the event cannot be changed
                if new_complete is None or (new_complete and (
                        user.id == instance.created_by.id or (
                        user.organization.id == instance.created_by.organization.id and (
                        user.role.is_partneradmin or user.role.is_partnermanager)))):
                    message = "Complete events may not be changed"
                    message += " unless the event owner or an administrator first re-opens the event"
                    message += " OR the event owner or an administrator also re-opens the event in the same request"
                    message += "  (by including the 'complete' field in the request and setting it to False)."
                    raise serializers.ValidationError(jsonify_errors(message))
                elif (user != instance.created_by
                      or (user.organization.id != instance.created_by.organization.id
                          and not (user.role.is_partneradmin or user.role.is_partnermanager))):
                    message = "Complete events may not be changed"
                    message += " unless first re-opened by the event owner or an administrator."
                    raise serializers.ValidationError(jsonify_errors(message))

        # otherwise if the Event is not complete but being set to complete, apply business rules
        if not instance.complete and new_complete:
            if (user.role.is_superadmin or user.role.is_admin or user.id == instance.created_by.id
                    or (user.organization.id == instance.created_by.organization.id
                        and (user.role.is_partneradmin or user.role.is_partnermanager))
                    or user.id in list(User.objects.filter(
                        writeevents__in=[instance.id]).values_list('id', flat=True))):
                # only let the status be changed to 'complete=True' if
                # 1. All child locations have an end date and each location's end date is later than its start date
                # 2. For morbidity/mortality events, there must be at least one number between sick, dead,
                #   estimated_sick, and estimated_dead per species at the time of event completion.
                #   (sick + dead + estimated_sick + estimated_dead >= 1)
                # 3. All child species diagnoses must have a basis and a cause
                locations = EventLocation.objects.filter(event=instance.id)
                location_message = "The event may not be marked complete until all of its locations have an end date"
                location_message += " and each location's end date is after that location's start date."
                if locations is not None:
                    species_count_is_valid = []
                    est_count_gt_known_count = True
                    species_diagnosis_basis_is_valid = []
                    species_diagnosis_cause_is_valid = []
                    details = []
                    mortality_morbidity = EventType.objects.filter(name='Mortality/Morbidity').first()
                    for location in locations:
                        if (not location.end_date or not location.start_date
                                or not location.end_date >= location.start_date):
                            raise serializers.ValidationError(jsonify_errors(location_message))
                        if instance.event_type.id == mortality_morbidity.id:
                            location_species = LocationSpecies.objects.filter(event_location=location.id)
                            for spec in location_species:
                                if spec.dead_count_estimated is not None and spec.dead_count_estimated > 0:
                                    species_count_is_valid.append(True)
                                    if (spec.dead_count is not None and spec.dead_count > 0
                                            and not spec.dead_count_estimated > spec.dead_count):
                                        est_count_gt_known_count = False
                                elif spec.dead_count is not None and spec.dead_count > 0:
                                    species_count_is_valid.append(True)
                                elif spec.sick_count_estimated is not None and spec.sick_count_estimated > 0:
                                    species_count_is_valid.append(True)
                                    if ((spec.sick_count or 0) > 0
                                            and spec.sick_count_estimated <= (spec.sick_count or 0)):
                                        est_count_gt_known_count = False
                                elif spec.sick_count is not None and spec.sick_count > 0:
                                    species_count_is_valid.append(True)
                                else:
                                    species_count_is_valid.append(False)
                                species_diagnoses = SpeciesDiagnosis.objects.filter(location_species=spec.id)
                                for specdiag in species_diagnoses:
                                    if specdiag.basis:
                                        species_diagnosis_basis_is_valid.append(True)
                                    else:
                                        species_diagnosis_basis_is_valid.append(False)
                                    if specdiag.cause:
                                        species_diagnosis_cause_is_valid.append(True)
                                    else:
                                        species_diagnosis_cause_is_valid.append(False)
                    if False in species_count_is_valid:
                        message = "Each location_species requires at least one species count in any of the following"
                        message += " fields: dead_count_estimated, dead_count, sick_count_estimated, sick_count."
                        details.append(message)
                    if not est_count_gt_known_count:
                        message = "Estimated sick or dead counts must always be more than known sick or dead counts."
                        details.append(message)
                    if False in species_diagnosis_basis_is_valid:
                        message = "The event may not be marked complete until all of its location species diagnoses"
                        message += " have a basis of diagnosis."
                        details.append(message)
                    if False in species_diagnosis_cause_is_valid:
                        message = "The event may not be marked complete until all of its location species diagnoses"
                        message += " have a cause."
                        details.append(message)
                    if details:
                        raise serializers.ValidationError(jsonify_errors(details))
                else:
                    raise serializers.ValidationError(jsonify_errors(location_message))
            else:
                message = "You do not have sufficient permission to set the event status to complete."
                raise serializers.ValidationError(jsonify_errors(message))

        # remove child event diagnoses list from the request
        if 'new_event_diagnoses' in validated_data:
            validated_data.pop('new_event_diagnoses')

        # remove child organizations list from the request
        if 'new_organizations' in validated_data:
            validated_data.pop('new_organizations')

        # remove child comments list from the request
        if 'new_comments' in validated_data:
            validated_data.pop('new_comments')

        # remove child event_locations list from the request
        if 'new_event_locations' in validated_data:
            validated_data.pop('new_event_locations')

        # remove child service_requests list from the request
        if 'new_service_requests' in validated_data:
            validated_data.pop('new_service_requests')

        # pull out read and write collaborators ID lists from the request
        if 'new_read_collaborators' in validated_data:
            new_read_collaborators = validated_data.pop('new_read_collaborators', None)
            new_read_user_ids_prelim = set(new_read_collaborators) if new_read_collaborators else set([])
        else:
            new_read_user_ids_prelim = set([])
        if 'new_write_collaborators' in validated_data:
            new_write_collaborators = validated_data.pop('new_write_collaborators', None)
            new_write_user_ids = set(new_write_collaborators) if new_write_collaborators else set([])
        else:
            new_write_user_ids = set([])

        request_method = self.context['request'].method

        # update the read_collaborators list if new_read_collaborators submitted
        if request_method == 'PUT' or (new_read_user_ids_prelim and request_method == 'PATCH'):
            # get the old (current) read collaborator ID list for this event
            old_read_users = User.objects.filter(readevents=instance.id)
            # remove users from the read list if they are also in the write list (these lists are already unique sets)
            new_read_user_ids = new_read_user_ids_prelim - new_write_user_ids
            # get the new (submitted) read collaborator ID list for this event
            new_read_users = User.objects.filter(id__in=new_read_user_ids)

            # identify and delete relates where user IDs are present in old read list but not new read list
            delete_read_users = list(set(old_read_users) - set(new_read_users))
            for user_id in delete_read_users:
                delete_user = EventReadUser.objects.filter(user=user_id, event=instance)
                delete_user.delete()

            # identify and create relates where user IDs are present in new read list but not old read list
            add_read_users = list(set(new_read_users) - set(old_read_users))
            for read_user in add_read_users:
                if not read_user.id == instance.created_by.id:
                    # only create collaborator if not the event owner
                    EventReadUser.objects.create(user=read_user, event=instance, created_by=user, modified_by=user)

        # update the write_collaborators list if new_write_user_ids submitted
        if request_method == 'PUT' or (new_write_user_ids and request_method == 'PATCH'):
            # get the old (current) write collaborator ID list for this event
            old_write_users = User.objects.filter(writeevents=instance.id)
            # get the new (submitted) write collaborator ID list for this event
            new_write_users = User.objects.filter(id__in=new_write_user_ids)

            # identify and delete relates where user IDs are present in old write list but not new write list
            delete_write_users = list(set(old_write_users) - set(new_write_users))
            for user_id in delete_write_users:
                delete_user = EventWriteUser.objects.filter(user=user_id, event=instance)
                delete_user.delete()

            # identify and create relates where user IDs are present in new write list but not old write list
            add_write_users = list(set(new_write_users) - set(old_write_users))
            for write_user in add_write_users:
                if not write_user.id == instance.created_by.id:
                    # only create collaborator if not the event owner
                    EventWriteUser.objects.create(user=write_user, event=instance, created_by=user, modified_by=user)

        # update the Event object
        instance.event_type = validated_data.get('event_type', instance.event_type)
        instance.event_reference = validated_data.get('event_reference', instance.event_reference)
        instance.complete = validated_data.get('complete', instance.complete)
        instance.public = validated_data.get('public', instance.public)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

        if user.role.is_superadmin or user.role.is_admin:
            instance.staff = validated_data.get('staff', instance.staff)
            instance.event_status = validated_data.get('event_status', instance.event_status)
            instance.quality_check = validated_data.get('quality_check', instance.quality_check)
            instance.legal_status = validated_data.get('legal_status', instance.legal_status)
            instance.legal_number = validated_data.get('legal_number', instance.legal_number)

        # affected_count
        # If EventType = Morbidity/Mortality
        # then Sum(Max(estimated_dead, dead) + Max(estimated_sick, sick)) from location_species table
        # If Event Type = Surveillance then Sum(number_positive) from species_diagnosis table
        event_type_id = instance.event_type.id
        if event_type_id not in [1, 2]:
            instance.affected_count = None
        else:
            locations = EventLocation.objects.filter(event=instance.id).values('id', 'start_date', 'end_date')
            loc_ids = [loc['id'] for loc in locations]
            loc_species = LocationSpecies.objects.filter(
                event_location_id__in=loc_ids).values(
                'id', 'dead_count_estimated', 'dead_count', 'sick_count_estimated', 'sick_count')
            if event_type_id == 1:
                affected_counts = [max(spec.get('dead_count_estimated') or 0, spec.get('dead_count') or 0)
                                   + max(spec.get('sick_count_estimated') or 0, spec.get('sick_count') or 0)
                                   for spec in loc_species]
                instance.affected_count = sum(affected_counts)
            elif event_type_id == 2:
                loc_species_ids = [spec['id'] for spec in loc_species]
                species_dx_positive_counts = SpeciesDiagnosis.objects.filter(
                    location_species_id__in=loc_species_ids).values_list('positive_count', flat=True)
                positive_counts = [dx or 0 for dx in species_dx_positive_counts]
                instance.affected_count = sum(positive_counts)

        instance.save()

        return instance

    def __init__(self, *args, **kwargs):
        user = None
        action = 'list'
        if 'context' in kwargs:
            if 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
                user = kwargs['context']['request'].user
            if 'view' in kwargs['context'] and hasattr(kwargs['context']['view'], 'action'):
                action = kwargs['context']['view'].action

        fields = ('id', 'event_type', 'event_type_string', 'complete', 'start_date', 'end_date', 'affected_count',
                  'event_status', 'event_status_string', 'permissions', 'permission_source',)
        private_fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date',
                          'end_date', 'affected_count', 'event_status', 'event_status_string', 'public',
                          'read_collaborators', 'write_collaborators', 'organizations', 'contacts', 'comments',
                          'new_event_diagnoses', 'new_organizations', 'new_comments', 'new_event_locations',
                          'new_eventgroups', 'new_service_request', 'new_read_collaborators', 'new_write_collaborators',
                          'created_date', 'created_by', 'created_by_string', 'modified_date', 'modified_by',
                          'modified_by_string', 'service_request_email', 'permissions', 'permission_source',)
        admin_fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date',
                        'end_date', 'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string',
                        'legal_status', 'legal_status_string', 'legal_number', 'quality_check', 'public',
                        'read_collaborators', 'write_collaborators', 'eventgroups', 'organizations', 'contacts',
                        'comments', 'new_read_collaborators', 'new_write_collaborators','new_event_diagnoses',
                        'new_organizations', 'new_comments', 'new_event_locations', 'new_eventgroups',
                        'new_service_request', 'created_date', 'created_by', 'created_by_string', 'modified_date',
                        'modified_by', 'modified_by_string', 'service_request_email', 'permissions',
                        'permission_source',)

        if user and user.is_authenticated:
            if user.role.is_superadmin or user.role.is_admin:
                fields = admin_fields
            elif action == 'create':
                fields = private_fields
            elif action in PK_REQUESTS and hasattr(kwargs['context']['request'], 'parser_context'):
                pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdecimal():
                    obj = Event.objects.filter(id=pk).first()
                    if obj and (user.id == obj.created_by.id or user.organization.id == obj.created_by.organization.id
                                or user.organization.id in obj.created_by.parent_organizations
                                or user.id in list(User.objects.filter(
                                Q(writeevents__in=[obj.id]) | Q(readevents__in=[obj.id])
                            ).values_list('id', flat=True))):
                        fields = private_fields

        super(EventSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = Event
        fields = '__all__'


class EventEventGroupSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        message_complete = "EventEventGroup for a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."

        # if this is a new EventEventGroup check if the Event is complete
        if not self.instance and 'FULL_EVENT_CHAIN_CREATE' not in self.initial_data and data['event'].complete:
            raise serializers.ValidationError(message_complete)

        # else this is an existing EventEventGroup, check if parent Event is complete
        elif self.instance and self.instance.event.complete:
            raise serializers.ValidationError(message_complete)

        return data

    def __init__(self, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            # this was triggered by a direct request to the endpoint
            user = kwargs['context']['request'].user
        elif 'data' in kwargs:
            # this was triggered by another serializer or view
            user = User.objects.filter(id=kwargs['data']['created_by']).first()

        if not user or not user.is_authenticated or user.role.is_public:
            fields = ('id', 'event', 'eventgroup',)

        else:
            fields = ('id', 'event', 'eventgroup', 'created_date', 'created_by', 'created_by_string',
                      'modified_date', 'modified_by', 'modified_by_string',)

        super(EventEventGroupSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = EventEventGroup
        fields = '__all__'


class EventGroupSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    name = serializers.CharField(read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    new_comment = serializers.CharField(write_only=True, required=True, allow_blank=False)
    new_events = serializers.ListField(write_only=True, required=True)
    events = serializers.SerializerMethodField()

    def get_events(self, obj):
        user = get_user(self.context, model_to_dict(obj))
        if not user or not user.is_authenticated or user.role.is_public:
            return list(Event.objects.filter(public=True, eventgroups=obj.id).values_list('id', flat=True))
        else:
            return list(Event.objects.filter(eventgroups=obj.id).values_list('id', flat=True))

    def create(self, validated_data):
        if 'new_events' in validated_data and len(validated_data['new_events']) < 2:
            raise serializers.ValidationError(jsonify_errors("An EventGroup must have at least two Events"))

        # pull out event ID list from the request
        new_event_ids = set(validated_data.pop('new_events', []))
        event_ids = set(list(Event.objects.filter(id__in=new_event_ids).values_list('id', flat=True)))
        not_event_ids = list(new_event_ids - event_ids)
        if not_event_ids:
            raise serializers.ValidationError(jsonify_errors("No Events were found with IDs of " + str(not_event_ids)))

        # pull out comment from the request
        new_comment = validated_data.pop("new_comment")

        eventgroup = EventGroup.objects.create(**validated_data)

        user = get_user(self.context, self.initial_data)

        # create the related comment
        comment_type = CommentType.objects.filter(name='Event Group').first()
        Comment.objects.create(content_object=eventgroup, comment=new_comment,
                               comment_type=comment_type, created_by=user, modified_by=user)

        # create the related event-eventgroups
        for event_id in new_event_ids:
            event = Event.objects.filter(id=event_id).first()
            if event:
                EventEventGroup.objects.create(eventgroup=eventgroup, event=event, created_by=user, modified_by=user)

        return eventgroup

    def update(self, instance, validated_data):
        if 'new_events' in validated_data and len(validated_data['new_events']) < 2:
            raise serializers.ValidationError(jsonify_errors("An EventGroup must have at least two Events"))

        # pull out event ID list from the request
        new_event_ids = set(validated_data.pop('new_events', []))
        event_ids = set(list(Event.objects.filter(id__in=new_event_ids).values_list('id', flat=True)))
        not_event_ids = list(new_event_ids - event_ids)
        if not_event_ids:
            raise serializers.ValidationError(jsonify_errors("No Events were found with IDs of " + str(not_event_ids)))

        user = get_user(self.context, self.initial_data)

        # update the comment
        new_comment = validated_data.pop("new_comment", None)
        if new_comment:
            content_type = ContentType.objects.get_for_model(self.Meta.model)
            comment = Comment.objects.filter(object_id=instance.id, content_type=content_type).first()
            comment.comment = new_comment
            comment.save()

        if new_event_ids:
            # get the old (current) event ID list for this Event Group
            old_event_ids = list(EventEventGroup.objects.filter(
                eventgroup=instance.id).values_list('event_id', flat=True))

            # identify and delete relates where event IDs are present in old list but not new list
            delete_event_ids = list(set(old_event_ids) - set(new_event_ids))
            for event_id in delete_event_ids:
                delete_event = EventEventGroup.objects.filter(eventgroup=instance.id, event=event_id)
                delete_event.delete()

            # identify and create relates where sample IDs are present in new list but not old list
            add_event_ids = list(set(new_event_ids) - set(old_event_ids))
            for event_id in add_event_ids:
                event = Event.objects.filter(id=event_id).first()
                if event:
                    EventEventGroup.objects.create(eventgroup=instance, event=event, created_by=user, modified_by=user)

        instance.category = validated_data.get('category', instance.category)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

        instance.save()

        return instance

    def __init__(self, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user

        if not user or not user.is_authenticated or user.role.is_public:
            fields = ('id', 'name', 'events',)

        else:
            fields = ('id', 'name', 'category', 'comments', 'events', "new_events", 'new_comment',
                      'created_date', 'created_by', 'created_by_string',
                      'modified_date', 'modified_by', 'modified_by_string',)

        super(EventGroupSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = EventGroup
        fields = '__all__'


class EventGroupCategorySerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = EventGroupCategory
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class EventTypeSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = EventType
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class StaffSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = Staff
        fields = ('id', 'first_name', 'last_name', 'role', 'active',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class LegalStatusSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = LegalStatus
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class EventStatusSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = EventStatus
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class EventAbstractSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        if data['event'].complete:
            message = "Abstracts from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        return data

    class Meta:
        model = EventAbstract
        fields = ('id', 'event', 'text', 'lab_id', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class EventCaseSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        if data['event'].complete:
            message = "Cases from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        return data

    class Meta:
        model = EventCase
        fields = ('id', 'event', 'case', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class EventLabsiteSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        if data['event'].complete:
            message = "Labsites from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        return data

    class Meta:
        model = EventLabsite
        fields = ('id', 'event', 'lab_id', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class EventOrganizationSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        message_complete = "Organizations from a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."

        # if this is a new EventOrganization check if the Event is complete
        if not self.instance and 'FULL_EVENT_CHAIN_CREATE' not in self.initial_data and data['event'].complete:
            raise serializers.ValidationError(message_complete)

        # else this is an existing EventOrganization, check if parent Event is complete
        elif self.instance and self.instance.event.complete:
            raise serializers.ValidationError(message_complete)

        return data

    def create(self, validated_data):

        event_organization = EventOrganization.objects.create(**validated_data)

        # calculate the priority value:
        event_organization.priority = calculate_priority_event_organization(event_organization)
        event_organization.save(update_fields=['priority', ])

        return event_organization

    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        instance.organization = validated_data.get('organization', instance.organization)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)
        instance.save()

        # calculate the priority value:
        instance.priority = calculate_priority_event_organization(instance)
        instance.save(update_fields=['priority', ])

        return instance

    def __init__(self, *args, **kwargs):
        user = None
        action = 'list'
        if 'context' in kwargs:
            # this was triggered by a direct request to the endpoint
            if 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
                user = kwargs['context']['request'].user
            if 'view' in kwargs['context'] and hasattr(kwargs['context']['view'], 'action'):
                action = kwargs['context']['view'].action
        elif 'data' in kwargs:
            # this was triggered by another serializer or view
            user = User.objects.filter(id=kwargs['data']['created_by']).first()
            action = 'create'

        fields = ('event', 'organization',)
        private_fields = ('id', 'event', 'organization', 'priority', 'created_date', 'created_by', 'created_by_string',
                          'modified_date', 'modified_by', 'modified_by_string',)

        if user and user.is_authenticated:
            if action == 'create' or user.role.is_superadmin or user.role.is_admin:
                fields = private_fields
            elif action in PK_REQUESTS and hasattr(kwargs['context']['request'], 'parser_context'):
                pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdecimal():
                    obj = EventOrganization.objects.filter(id=pk).first()
                    if obj and (user.id == obj.created_by.id or user.id == obj.event.created_by.id
                                or user.organization.id == obj.created_by.organization.id
                                or user.organization.id == obj.event.created_by.organization.id
                                or user.organization.id in obj.created_by.parent_organizations
                                or user.organization.id in obj.event.created_by.parent_organizations
                                or user.id in list(User.objects.filter(
                                Q(writeevents__in=[obj.event.id]) | Q(readevents__in=[obj.event.id])
                            ).values_list('id', flat=True))):
                        fields = private_fields

        super(EventOrganizationSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = EventOrganization
        fields = '__all__'


class EventContactSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        if data['event'].complete:
            message = "Contacts from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        return data

    class Meta:
        model = EventContact
        fields = ('id', 'event', 'contact', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


######
#
#  Locations
#
######


class EventLocationSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    administrative_level_two_string = serializers.StringRelatedField(source='administrative_level_two')
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')
    country_string = serializers.StringRelatedField(source='country')
    comments = CommentSerializer(many=True, read_only=True)
    new_location_contacts = serializers.ListField(write_only=True, required=False)
    new_location_species = serializers.ListField(write_only=True, required=False)
    site_description = serializers.CharField(write_only=True, required=False, allow_blank=True)
    history = serializers.CharField(write_only=True, required=False, allow_blank=True)
    environmental_factors = serializers.CharField(write_only=True, required=False, allow_blank=True)
    clinical_signs = serializers.CharField(write_only=True, required=False, allow_blank=True)
    comment = serializers.CharField(write_only=True, required=False, allow_blank=True)

    # find the centroid coordinates (lng/lat) for a state or equivalent
    def search_geonames_adm1(self, adm1_name, country_code):
        coords = None
        geonames_endpoint = 'searchJSON'
        gn = 'geonames'
        lng = 'lng'
        lat = 'lat'
        geonames_params = {'name': adm1_name, 'featureCode': 'ADM1', 'country': country_code}
        geonames_params.update({'maxRows': 1, 'username': get_geonames_username()})
        gr = requests.get(get_geonames_api() + geonames_endpoint, params=geonames_params)
        try:
            grj = gr.json()
            if gn in grj and len(grj[gn]) > 0 and lng in grj[gn][0] and lat in grj[gn][0]:
                coords = {lng: grj[gn][0][lng], lat: grj[gn][0][lat]}
            return coords
        except requests.exceptions.RequestException as e:
            # email admins
            send_third_party_service_exception_email('Geonames', get_geonames_api() + geonames_endpoint, e)
            return None

    # find the centroid coordinates (lng/lat) for a county or equivalent
    def search_geonames_adm2(self, adm2_name, adm1_name, adm1_code, country_code):
        geonames_endpoint = 'searchJSON'
        gn = 'geonames'
        lng = 'lng'
        lat = 'lat'
        geonames_params = {'name': adm2_name, 'featureCode': 'ADM2'}
        geonames_params.update({'adminCode1': adm1_code, 'country': country_code})
        geonames_params.update({'maxRows': 1, 'username': get_geonames_username()})
        gr = requests.get(get_geonames_api() + geonames_endpoint, params=geonames_params)
        try:
            grj = gr.json()
            if gn in grj and len(grj[gn]) > 0 and lng in grj[gn][0] and lat in grj[gn][0]:
                coords = {lng: grj[gn][0][lng], lat: grj[gn][0][lat]}
            else:
                # adm2 search failed so look up the adm1 coordinates as a fallback
                coords = self.search_geonames_adm1(adm1_name, country_code)
            return coords
        except requests.exceptions.RequestException as e:
            # email admins
            send_third_party_service_exception_email('Geonames', get_geonames_api() + geonames_endpoint, e)
            return None

    def validate(self, data):

        message_complete = "Locations from a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."

        # if this is a new EventLocation
        if not self.instance:
            # check if the Event is complete
            if data['event'].complete and 'FULL_EVENT_CHAIN_CREATE' not in self.initial_data:
                raise serializers.ValidationError(message_complete)
            # otherwise the Event is not complete (or complete but created in this chain), so apply business rules
            else:
                # 3. location_species Population >= max(estsick, knownsick) + max(estdead, knowndead)
                # 4. For morbidity/mortality events, there must be at least one number between sick, dead,
                #    estimated_sick, and estimated_dead for at least one species in the event
                #    at the time of event initiation. (sick + dead + estimated_sick + estimated_dead >= 1)
                # 5. If present, estimated_sick must be higher than known sick (estimated_sick > sick).
                # 6. If present, estimated dead must be higher than known dead (estimated_dead > dead).
                # 7. Every location needs at least one comment, which must be one of the following types:
                #    Site description, History, Environmental factors, Clinical signs
                # 8. Standardized lat/long format (e.g., decimal degrees WGS84). Update county, state, and country
                #    if county is null. Update state and country if state is null. If don't enter country, state, and
                #    county at initiation, then have to enter lat/long, which autopopulates country, state, and county.
                # 9. Ensure admin level 2 actually belongs to admin level 1 which actually belongs to country.
                # 10. Location start date cannot be after today if event type is Mortality/Morbidity
                # 11. Location end date must be equal to or greater than start date.
                # 12: Non-suspect diagnosis cannot have basis_of_dx = 1,2, or 4.  If 3, user must provide a lab.
                # 13: A diagnosis can only be used once for a location-species-labID combination
                country_admin_is_valid = True
                latlng_is_valid = True
                latlng_country_found = True
                latlng_matches_country = True
                latlng_matches_admin_l1 = True
                latlng_matches_admin_21 = True
                comments_is_valid = []
                required_comment_types = ['site_description', 'history', 'environmental_factors', 'clinical_signs']
                start_date_is_valid = True
                end_date_is_valid = True
                min_species_count = False
                pop_is_valid = []
                est_sick_is_valid = True
                est_dead_is_valid = True
                specdiag_nonsuspect_basis_is_valid = True
                specdiag_lab_is_valid = True
                details = []
                mortality_morbidity = EventType.objects.filter(name='Mortality/Morbidity').first()
                if [i for i in required_comment_types if i in data and data[i]]:
                    comments_is_valid.append(True)
                else:
                    comments_is_valid.append(False)
                if 'start_date' in data and data['start_date'] is not None:
                    min_start_date = True
                    if data['event'].event_type.id == mortality_morbidity.id and data['start_date'] > date.today():
                        start_date_is_valid = False
                    if 'end_date' in data and data['end_date'] is not None and data['end_date'] < data['start_date']:
                        end_date_is_valid = False
                elif 'end_date' in data and data['end_date'] is not None:
                    end_date_is_valid = False
                if ('country' in data and data['country'] is not None and 'administrative_level_one' in data
                        and data['administrative_level_one'] is not None):
                    admin_l1 = data['administrative_level_one']
                    if data['country'].id != admin_l1.country.id:
                        country_admin_is_valid = False
                    if 'administrative_level_two' in data and data['administrative_level_two'] is not None:
                        if admin_l1.id != data['administrative_level_two'].administrative_level_one.id:
                            country_admin_is_valid = False
                if (('country' not in data or data['country'] is None or 'administrative_level_one' not in data
                     or data['administrative_level_one'] is None)
                        and ('latitude' not in data or data['latitude'] is None
                             or 'longitude' not in data and data['longitude'] is None)):
                    message = "country and administrative_level_one are required if latitude or longitude is null."
                    details.append(message)
                if ('latitude' in data and data['latitude'] is not None
                        and not re.match(r"(-?)([\d]{1,2})(\.)(\d+)", str(data['latitude']))):
                    latlng_is_valid = False
                if ('longitude' in data and data['longitude'] is not None
                        and not re.match(r"(-?)([\d]{1,3})(\.)(\d+)", str(data['longitude']))):
                    latlng_is_valid = False
                geonames_endpoint = 'extendedFindNearbyJSON'
                GEONAMES_USERNAME = get_geonames_username()
                GEONAMES_API = get_geonames_api()
                if (latlng_is_valid
                        and 'latitude' in data and data['latitude'] is not None
                        and 'longitude' in data and data['longitude'] is not None
                        and 'country' in data and data['country'] is not None):
                    payload = {'lat': data['latitude'], 'lng': data['longitude'], 'username': GEONAMES_USERNAME}
                    r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                    geonames_latlng_url = r.request.url
                    try:
                        geonames_object_list = decode_json(r)
                        if 'address' in geonames_object_list:
                            address = geonames_object_list['address']
                            if 'name' in address:
                                address['adminName2'] = address['name']
                        elif 'geonames' in geonames_object_list:
                            gn_adm2 = [data for data in geonames_object_list['geonames'] if data['fcode'] == 'ADM2']
                            # NOTE: some countries have fcode of PPL (city) instead of ADM2 immediately below ADM1,
                            #  which are not in our database at this time, so skip over this
                            address = gn_adm2[0] if gn_adm2 else None
                        else:
                            # the response from the Geonames web service is in an unexpected format
                            address = None
                    except requests.exceptions.RequestException as e:
                        # email admins
                        send_third_party_service_exception_email('Geonames', GEONAMES_API + geonames_endpoint, e)
                        address = None
                    geonames_endpoint = 'countryInfoJSON'
                    if address:
                        country_code = address['countryCode']
                        country = None
                        if len(country_code) == 2:
                            payload = {'country': country_code, 'username': GEONAMES_USERNAME}
                            r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                            try:
                                content = decode_json(r)
                                if ('geonames' in content and content['geonames'] is not None
                                        and len(content['geonames']) > 0 and 'isoAlpha3' in content['geonames'][0]):
                                    alpha3 = content['geonames'][0]['isoAlpha3']
                                    country = Country.objects.filter(abbreviation=alpha3).first()
                            except requests.exceptions.RequestException as e:
                                # email admins
                                send_third_party_service_exception_email(
                                    'Geonames', GEONAMES_API + geonames_endpoint, e)
                        elif len(country_code) == 3:
                            country = Country.objects.filter(abbreviation=country_code).first()
                        if not country:
                            # Instead of causing a validation error, email admins and let the create proceed
                            # latlng_country_found = False
                            message = f"Geonames returned a Country ({country_code})"
                            message += " that could not be found in the WHISPers database"
                            message += f" when using the latitude and longitude submitted by the user"
                            message += f" ({data['longitude']}, {data['latitude']})."
                            message += f" The request made to Geonames was: {geonames_latlng_url}"
                            construct_email("WHISPERS ADMIN: Third Party Service Validation Warning", message)
                        elif data['country'].id != country.id:
                            # Instead of causing a validation error, email admins and let the create proceed
                            # latlng_matches_country = False
                            message = f"Geonames returned a Country ({country_code})"
                            message += " different from the one submitted by the user"
                            message += f" ({data['country'].name}) when using the latitude"
                            message += " and longitude submitted by the user"
                            message += f" ({data['longitude']}, {data['latitude']})."
                            message += f" The request made to Geonames was: {geonames_latlng_url}"
                            construct_email("WHISPERS ADMIN: Third Party Service Validation Warning", message)
                        # TODO: check submitted admin L1 and L2 against lat/lng, not just ids
                        elif ('administrative_level_one' in data
                              and data['administrative_level_one'] is not None):
                            admin_l1 = AdministrativeLevelOne.objects.filter(name=address['adminName1']).first()
                            if not admin_l1 or data['administrative_level_one'].id != admin_l1.id:
                                # Instead of causing a validation error, email admins and let the create proceed
                                # latlng_matches_admin_l1 = False
                                message = f"Geonames returned an Administrative Level One ({address['adminName1']})"
                                message += " different from the one submitted by the user"
                                message += f" ({data['administrative_level_one'].name}) when using the latitude"
                                message += " and longitude submitted by the user"
                                message += f" ({data['longitude']}, {data['latitude']})."
                                message += f" The request made to Geonames was: {geonames_latlng_url}"
                                construct_email("WHISPERS ADMIN: Third Party Service Validation Warning", message)
                            elif ('administrative_level_two' in data
                                  and data['administrative_level_two'] is not None):
                                admin_name2 = address['adminName2'] if 'adminName2' in address else address['name']
                                admin_l2 = AdministrativeLevelTwo.objects.filter(
                                    name__icontains=admin_name2, administrative_level_one__id=admin_l1.id).first()
                                if not admin_l2 or data['administrative_level_two'].id != admin_l2.id:
                                    # Instead of causing a validation error, email admins and let the create proceed
                                    # latlng_matches_admin_21 = False
                                    message = f"Geonames returned an Administrative Level Two ({admin_name2})"
                                    message += " different from the one submitted by the user"
                                    message += f" ({data['administrative_level_two'].name}) when using the latitude"
                                    message += " and longitude submitted by the user"
                                    message += f" ({data['longitude']}, {data['latitude']}).\r\n"
                                    message += f" The request made to Geonames was: {geonames_latlng_url}"
                                    construct_email("WHISPERS ADMIN: Third Party Service Validation Warning", message)
                    else:
                        # Instead of causing a validation error, email admins and let the create proceed
                        message = f"Geonames returned data in an unexpected format"
                        message += " that could not be validated against data in the WHISPers database"
                        message += f" when using the latitude and longitude submitted by the user"
                        message += f" ({data['longitude']}, {data['latitude']})."
                        message += f" The request made to Geonames was: {geonames_latlng_url}"
                        construct_email("WHISPERS ADMIN: Third Party Service Validation Warning", message)
                if 'new_location_species' in data:
                    for spec in data['new_location_species']:
                        if 'species' in spec and spec['species'] is not None:
                            if Species.objects.filter(id=spec['species']).first() is None:
                                message = "A submitted species ID (" + str(spec['species'])
                                message += ") in new_location_species was not found in the database."
                                details.append(message)
                            else:
                                min_location_species = True
                        if 'population_count' in spec and spec['population_count'] is not None:
                            dead_count = 0
                            sick_count = 0
                            if 'dead_count_estimated' in spec or 'dead_count' in spec:
                                dead_count = max(spec.get('dead_count_estimated') or 0, spec.get('dead_count') or 0)
                            if 'sick_count_estimated' in spec or 'sick_count' in spec:
                                sick_count = max(spec.get('sick_count_estimated') or 0, spec.get('sick_count') or 0)
                            if spec['population_count'] >= dead_count + sick_count:
                                pop_is_valid.append(True)
                            else:
                                pop_is_valid.append(False)
                        if ('sick_count_estimated' in spec and spec['sick_count_estimated'] is not None
                                and 'sick_count' in spec and spec['sick_count'] is not None
                                and not spec['sick_count_estimated'] > spec['sick_count']):
                            est_sick_is_valid = False
                        if ('dead_count_estimated' in spec and spec['dead_count_estimated'] is not None
                                and 'dead_count' in spec and spec['dead_count'] is not None
                                and not spec['dead_count_estimated'] > spec['dead_count']):
                            est_dead_is_valid = False
                        if data['event'].event_type.id == mortality_morbidity.id:
                            if ('dead_count_estimated' in spec and spec['dead_count_estimated'] is not None
                                    and spec['dead_count_estimated'] > 0):
                                min_species_count = True
                            elif 'dead_count' in spec and spec['dead_count'] is not None and spec['dead_count'] > 0:
                                min_species_count = True
                            elif ('sick_count_estimated' in spec and spec['sick_count_estimated'] is not None
                                  and spec['sick_count_estimated'] > 0):
                                min_species_count = True
                            elif 'sick_count' in spec and spec['sick_count'] is not None and spec['sick_count'] > 0:
                                min_species_count = True
                        if 'new_species_diagnoses' in spec and spec['new_species_diagnoses'] is not None:
                            specdiag_labs = []
                            for specdiag in spec['new_species_diagnoses']:
                                [specdiag_labs.append((specdiag['diagnosis'], specdiag_lab)) for specdiag_lab in
                                 specdiag['new_species_diagnosis_organizations']]
                                if not specdiag['suspect']:
                                    if specdiag['basis'] in [1, 2, 4]:
                                        undetermined = list(Diagnosis.objects.filter(
                                            name='Undetermined').values_list('id', flat=True))[0]
                                        if specdiag['diagnosis'] != undetermined:
                                            specdiag_nonsuspect_basis_is_valid = False
                                    elif specdiag['basis'] == 3:
                                        if ('new_species_diagnosis_organizations' in specdiag
                                                and specdiag['new_species_diagnosis_organizations'] is not None):
                                            for org_id in specdiag['new_species_diagnosis_organizations']:
                                                org = Organization.objects.filter(id=org_id).first()
                                                if not org or not org.laboratory:
                                                    specdiag_nonsuspect_basis_is_valid = False
                            if len(specdiag_labs) != len(set(specdiag_labs)):
                                specdiag_lab_is_valid = False
                    if 'new_location_contacts' in data and data['new_location_contacts'] is not None:
                        for loc_contact in data['new_location_contacts']:
                            if 'contact' not in loc_contact or loc_contact['contact'] is None:
                                message = "A required contact ID was not included in new_location_contacts."
                                details.append(message)
                            elif Contact.objects.filter(id=loc_contact['contact']).first() is None:
                                message = "A submitted contact ID (" + str(loc_contact['contact'])
                                message += ") in new_location_contacts was not found in the database."
                                details.append(message)
                if not country_admin_is_valid:
                    message = "administrative_level_one must belong to the submitted country,"
                    message += " and administrative_level_two must belong to the submitted administrative_level_one."
                    details.append(message)
                if not start_date_is_valid:
                    message = "If event_type is 'Mortality/Morbidity'"
                    message += " start_date for a new event_location must be current date or earlier."
                    details.append(message)
                if not end_date_is_valid:
                    details.append("end_date may not be before start_date.")
                if not latlng_is_valid:
                    message = "latitude and longitude must be in decimal degrees and represent a point in a country."
                    details.append(message)
                if not latlng_country_found:
                    message = "A country matching the submitted latitude and longitude could not be found."
                    details.append(message)
                if not latlng_matches_country:
                    message = "latitude and longitude are not in the user-specified country."
                    details.append(message)
                if not latlng_matches_admin_l1:
                    message = "latitude and longitude are not in"
                    message += " the user-specified administrative level one (e.g., state)."
                    details.append(message)
                if not latlng_matches_admin_21:
                    message = "latitude and longitude are not in"
                    message += " the user-specified administrative level two (e.g., county)."
                    details.append(message)
                if False in comments_is_valid:
                    message = "Each new_event_location requires at least one new_comment, which must be one of"
                    message += " the following types: Site description, History, Environmental factors, Clinical signs"
                    details.append(message)
                if False in pop_is_valid:
                    message = "new_location_species population_count cannot be less than the sum of dead_count"
                    message += " and sick_count (where those counts are the maximum of the estimated or known count)."
                    details.append(message)
                if data['event'].event_type.id == mortality_morbidity.id and not min_species_count:
                    message = "For Mortality/Morbidity events, at least one new_location_species requires"
                    message += " at least one species count in any of the following fields:"
                    message += " dead_count_estimated, dead_count, sick_count_estimated, sick_count."
                    details.append(message)
                if not est_sick_is_valid:
                    details.append("Estimated sick count must always be more than known sick count.")
                if not est_dead_is_valid:
                    details.append("Estimated dead count must always be more than known dead count.")
                if not specdiag_nonsuspect_basis_is_valid:
                    message = "A non-suspect diagnosis can only have a basis of"
                    message += " 'Necropsy and/or ancillary tests performed at a diagnostic laboratory'"
                    message += " and only if that diagnosis has a related laboratory"
                    details.append(message)
                if not specdiag_lab_is_valid:
                    message = "A diagnosis can only be used once for any combination of a location, species, and lab."
                    details.append(message)
                if details:
                    raise serializers.ValidationError(details)

        # else this is an existing EventLocation
        elif self.instance:
            # check if parent Event is complete
            if self.instance.event.complete:
                raise serializers.ValidationError(message_complete)

        return data

    def create(self, validated_data):
        user = get_user(self.context, self.initial_data)
        flyway = None

        comment_types = {'site_description': 'Site description', 'history': 'History',
                         'environmental_factors': 'Environmental factors', 'clinical_signs': 'Clinical signs',
                         'other': 'Other'}

        # event = Event.objects.filter(pk=validated_data['event']).first()
        new_location_contacts = validated_data.pop('new_location_contacts', None)
        new_location_species = validated_data.pop('new_location_species', None)

        # create object for comment creation while removing unserialized fields for EventLocation
        comments = {'site_description': validated_data.pop('site_description', None),
                    'history': validated_data.pop('history', None),
                    'environmental_factors': validated_data.pop('environmental_factors', None),
                    'clinical_signs': validated_data.pop('clinical_signs', None),
                    'other': validated_data.pop('comment', None)}

        # if the event_location has no name value but does have a gnis_name value,
        # then copy the value of gnis_name to name
        # this need only happen on creation since the two fields should maintain no durable relationship
        if validated_data['name'] == '' and validated_data['gnis_name'] != '':
            validated_data['name'] = validated_data['gnis_name']

        # if event_location has lat/lng but no country/adminlevelone/adminleveltwo, populate missing fields
        # NOTE that this will overwrite the user-submitted values for country and adminlevelone and adminleveltwo
        # because lat/lng takes precedence over those values, and the user may have submitted incorrect
        # country/adminlevelone/adminleveltwo combination values
        if (('latitude' in validated_data and validated_data['latitude'] is not None
             and 'longitude' in validated_data and validated_data['longitude'] is not None)
                and ('country' not in validated_data or validated_data['country'] is None
                     or 'administrative_level_one' not in validated_data
                     or validated_data['administrative_level_one'] is None
                     or 'administrative_level_two' not in validated_data
                     or validated_data['administrative_level_two'] is None)):
            geonames_endpoint = 'extendedFindNearbyJSON'
            GEONAMES_USERNAME = get_geonames_username()
            GEONAMES_API = get_geonames_api()
            address = None
            payload = {'lat': validated_data['latitude'], 'lng': validated_data['longitude'],
                       'username': GEONAMES_USERNAME}
            r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
            try:
                geonames_object_list = decode_json(r)
                if 'address' in geonames_object_list:
                    address = geonames_object_list['address']
                    address['adminName2'] = address['name']
                elif 'geonames' in geonames_object_list:
                    gn_adm2 = [item for item in geonames_object_list['geonames'] if item['fcode'] == 'ADM2']
                    address = gn_adm2[0]
            except requests.exceptions.RequestException as e:
                # email admins
                send_third_party_service_exception_email('Geonames', GEONAMES_API + geonames_endpoint, e)
            geonames_endpoint = 'countryInfoJSON'
            if address:
                if 'country' not in validated_data or validated_data['country'] is None:
                    country_code = address['countryCode']
                    if len(country_code) == 2:
                        payload = {'country': country_code, 'username': GEONAMES_USERNAME}
                        r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                        try:
                            content = decode_json(r)
                            if ('geonames' in content and content['geonames'] is not None
                                    and len(content['geonames']) > 0 and 'isoAlpha3' in content['geonames'][0]):
                                alpha3 = content['geonames'][0]['isoAlpha3']
                                validated_data['country'] = Country.objects.filter(abbreviation=alpha3).first()
                        except requests.exceptions.RequestException as e:
                            # email admins
                            send_third_party_service_exception_email(
                                'Geonames', GEONAMES_API + geonames_endpoint, e)
                    elif len(country_code) == 3:
                        validated_data['country'] = Country.objects.filter(abbreviation=country_code).first()
                    else:
                        # fail POST because country and admin levels one and two are required
                        if self.initial_data['FULL_EVENT_CHAIN_CREATE']:
                            # delete the parent event, which will also delete this event location thru a cascade
                            validated_data['event'].delete()
                        message = "A country matching the submitted latitude and longitude could not be found."
                        raise serializers.ValidationError(message)
                if ('administrative_level_one' not in validated_data
                        or validated_data['administrative_level_one'] is None):
                    validated_data['administrative_level_one'] = AdministrativeLevelOne.objects.filter(
                        name=address['adminName1']).first()
                if ('administrative_level_two' not in validated_data
                        or validated_data['administrative_level_two'] is None):
                    admin2 = address['adminName2'] if 'adminName2' in address else address['name']
                    validated_data['administrative_level_two'] = AdministrativeLevelTwo.objects.filter(
                        name=admin2).first()
            else:
                # fail POST because country and admin levels one and two are required
                if self.initial_data['FULL_EVENT_CHAIN_CREATE']:
                    # delete the parent event, which will also delete this event location thru a cascade
                    validated_data['event'].delete()
                message = "A country matching the submitted latitude and longitude could not be found."
                raise serializers.ValidationError(message)

        # create the event_location and return object for use in child objects
        evt_location = EventLocation.objects.create(**validated_data)

        # auto-assign flyway for locations in the USA (exclude territories and minor outlying islands)

        # HI is not in a flyway, so assign to Pacific ("Include all of Hawaii in with Pacific Americas")
        if validated_data['administrative_level_one'].abbreviation == 'HI':
            flyway = Flyway.objects.filter(name__contains='Pacific').first()

        # All others must be determined by spatial overlay
        else:
            # first test the FWS flyway web service to confirm it is working
            test_params = {'geometryType': 'esriGeometryPoint', 'returnGeometry': 'false'}
            test_params.update({'outFields': 'NAME', 'f': 'json', 'spatialRel': 'esriSpatialRelIntersects'})
            test_params.update({'geometry': '-90.0,45.0'})
            r = requests.get(get_flyways_api(), params=test_params, verify=settings.SSL_CERT)
            try:
                if 'features' in r.json():
                    territories = ['PR', 'VI', 'MP', 'AS', 'UM', 'NOPO', 'SOPO']
                    country = validated_data['country']
                    admin_l1 = validated_data['administrative_level_one']
                    admin_l2 = validated_data['administrative_level_two']
                    if (country.id == Country.objects.filter(abbreviation='USA').first().id
                            and admin_l1.abbreviation not in territories):
                        params = {'geometryType': 'esriGeometryPoint', 'returnGeometry': 'false',
                                  'outFields': 'NAME', 'f': 'json', 'spatialRel': 'esriSpatialRelIntersects'}
                        # if lat/lng is present, use it to get the intersecting flyway
                        if ('latitude' in validated_data and validated_data['latitude'] is not None
                                and 'longitude' in validated_data and validated_data['longitude'] is not None):
                            geom = str(validated_data['longitude']) + ',' + str(validated_data['latitude'])
                            params.update({'geometry': geom})
                        # otherwise if county is present,
                        # look up the county centroid and use it to get the intersecting flyway
                        elif admin_l2 is not None:
                            coords = self.search_geonames_adm2(
                                admin_l2.name, admin_l1.name, admin_l1.abbreviation, country.abbreviation)
                            if coords:
                                params.update({'geometry': coords['lng'] + ',' + coords['lat']})
                        # MT, WY, CO, and NM straddle two flyways, and without lat/lng or county info,
                        # flyway cannot be determined, otherwise look up the state centroid,
                        # then use it to get the intersecting flyway
                        elif admin_l1.abbreviation not in ['MT', 'WY', 'CO', 'NM', 'HI']:
                            coords = self.search_geonames_adm1(admin_l1.name, country.abbreviation)
                            if coords:
                                params.update({'geometry': coords['lng'] + ',' + coords['lat']})
                        # Look up the flyway from the FWS flyway web service
                        if 'geometry' in params:
                            r = requests.get(get_flyways_api(), params=params, verify=settings.SSL_CERT)
                            try:
                                rj = r.json()
                                if 'features' in rj and len(rj['features']) > 0:
                                    flyway_name = rj['features'][0]['attributes']['NAME'].replace(' Flyway', '')
                                    flyway = Flyway.objects.filter(name__contains=flyway_name).first()
                            except requests.exceptions.RequestException as e:
                                # email admins
                                send_third_party_service_exception_email('FWS Flyways', get_flyways_api(), e)
                                # flyways is not a required field, the admins can populate it after investigating
                                pass
            except requests.exceptions.RequestException as e:
                # email admins
                send_third_party_service_exception_email('FWS Flyways', get_flyways_api(), e)
                # flyways is not a required field, the admins can populate it after investigating
                pass

        if flyway is not None:
            EventLocationFlyway.objects.create(event_location=evt_location, flyway=flyway,
                                               created_by=user, modified_by=user)
        else:
            # No flyway can be determined
            # Instead of causing a validation error, email admins and let the create proceed
            message = f"No flyway could be determined from the data submitted by the user"
            message += f" for Event Location {evt_location.name} (ID {evt_location.id})"
            message += f" in Event {evt_location.event.event_reference} (ID {evt_location.event.id})."
            construct_email("WHISPERS ADMIN: No Flyway Validation Warning", message)

        # Create EventLocationSpecies
        if new_location_species is not None:
            is_valid = True
            valid_data = []
            errors = []
            for new_location_spec in new_location_species:
                if new_location_spec is not None:
                    new_location_spec['event_location'] = evt_location.id
                    new_location_spec['created_by'] = evt_location.created_by.id
                    new_location_spec['modified_by'] = evt_location.modified_by.id
                    if 'FULL_EVENT_CHAIN_CREATE' in self.initial_data:
                        new_location_spec['FULL_EVENT_CHAIN_CREATE'] = self.initial_data['FULL_EVENT_CHAIN_CREATE']
                    loc_spec_serializer = LocationSpeciesSerializer(data=new_location_spec)
                    if loc_spec_serializer.is_valid():
                        valid_data.append(loc_spec_serializer)
                    else:
                        is_valid = False
                        errors.append(loc_spec_serializer.errors)
            if is_valid:
                # now that all items are proven valid, save and return them to the user
                for item in valid_data:
                    item.save()
            else:
                if self.initial_data['FULL_EVENT_CHAIN_CREATE']:
                    # delete the parent event, which will also delete this event location thru a cascade
                    evt_location.event.delete()
                else:
                    # delete this event location
                    # (related contacts and comments will be cascade deleted automatically if any exist)
                    evt_location.delete()
                raise serializers.ValidationError(jsonify_errors(errors))

        for key, value in comment_types.items():

            comment_type = CommentType.objects.filter(name=value).first()

            if comments[key] is not None and len(comments[key]) > 0:
                Comment.objects.create(content_object=evt_location, comment=comments[key],
                                       comment_type=comment_type, created_by=user, modified_by=user)

        # Create EventLocationContacts
        if new_location_contacts is not None:
            for location_contact in new_location_contacts:
                location_contact['event_location'] = evt_location

                # Convert ids to ForeignKey objects
                if 'contact' in location_contact and location_contact['contact'] is not None:
                    location_contact['contact'] = Contact.objects.filter(id=location_contact['contact']).first()
                    location_contact['contact_type'] = ContactType.objects.filter(
                        pk=location_contact['contact_type']).first()

                    EventLocationContact.objects.create(created_by=user, modified_by=user, **location_contact)

        # calculate the priority value:
        evt_location.priority = calculate_priority_event_location(evt_location)
        evt_location.save(update_fields=['priority', ])

        return evt_location

    # on update, any submitted nested objects (new_location_contacts, new_location_species) will be ignored
    # TODO: consider updating flyway if instance had null value and/or when lat/lng or country/state/county change
    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        # remove child location_contacts list from the request
        if 'new_location_contacts' in validated_data:
            validated_data.pop('new_location_contacts')

        # remove child location_species list from the request
        if 'new_location_species' in validated_data:
            validated_data.pop('new_location_species')

        # TODO: consider updating flyway if lat/lng or country/state/county change
        # update the EventLocation object
        instance.name = validated_data.get('name', instance.name)
        instance.start_date = validated_data.get('start_date', instance.start_date)
        instance.end_date = validated_data.get('end_date', instance.end_date)
        instance.country = validated_data.get('country', instance.country)
        instance.administrative_level_one = validated_data.get(
            'administrative_level_one', instance.administrative_level_one)
        instance.administrative_level_two = validated_data.get(
            'administrative_level_two', instance.administrative_level_two)
        instance.county_multiple = validated_data.get('county_multiple', instance.county_multiple)
        instance.county_unknown = validated_data.get('county_unknown', instance.county_unknown)
        instance.latitude = validated_data.get('latitude', instance.latitude)
        instance.longitude = validated_data.get('longitude', instance.longitude)
        instance.land_ownership = validated_data.get('land_ownership', instance.land_ownership)
        instance.gnis_name = validated_data.get('gnis_name', instance.gnis_name)
        instance.gnis_id = validated_data.get('gnis_id', instance.gnis_id)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

        # if an event_location has no name value but does have a gnis_name value, copy the value of gnis_name to name
        # this need only happen on creation since the two fields should maintain no durable relationship
        if ('name' in validated_data and 'gnis_name' in validated_data
                and validated_data['name'] == '' and validated_data['gnis_name'] != ''):
            validated_data['name'] = validated_data['gnis_name']
        instance.save()

        # calculate the priority value:
        instance.priority = calculate_priority_event_location(instance)
        instance.save(update_fields=['priority', ])

        return instance

    def __init__(self, *args, **kwargs):
        user = None
        action = 'list'
        if 'context' in kwargs:
            # this was triggered by a direct request to the endpoint
            if 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
                user = kwargs['context']['request'].user
            if 'view' in kwargs['context'] and hasattr(kwargs['context']['view'], 'action'):
                action = kwargs['context']['view'].action
        elif 'data' in kwargs:
            # this was triggered by another serializer or view
            user = User.objects.filter(id=kwargs['data']['created_by']).first()
            action = 'create'

        fields = ('start_date', 'end_date', 'country', 'country_string', 'administrative_level_one',
                  'administrative_level_one_string', 'administrative_level_two', 'administrative_level_two_string',
                  'county_multiple', 'county_unknown', 'flyways',)
        private_fields = ('id', 'name', 'event', 'start_date', 'end_date', 'country', 'country_string',
                          'administrative_level_one', 'administrative_level_one_string', 'administrative_level_two',
                          'administrative_level_two_string', 'county_multiple', 'county_unknown', 'latitude', 'longitude',
                          'priority', 'land_ownership', 'flyways', 'contacts', 'gnis_name', 'gnis_id', 'comments',
                          'site_description', 'history', 'environmental_factors', 'clinical_signs', 'comment',
                          'new_location_contacts', 'new_location_species', 'created_date', 'created_by',
                          'created_by_string', 'modified_date', 'modified_by', 'modified_by_string',)

        if action == 'create' or (user and user.is_authenticated):
            if action == 'create' or user.role.is_superadmin or user.role.is_admin:
                fields = private_fields
            elif action in PK_REQUESTS and hasattr(kwargs['context']['request'], 'parser_context'):
                pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdecimal():
                    obj = EventLocation.objects.filter(id=pk).first()
                    if obj and (user.id == obj.created_by.id or user.id == obj.event.created_by.id
                                or user.organization.id == obj.created_by.organization.id
                                or user.organization.id == obj.event.created_by.organization.id
                                or user.organization.id in obj.created_by.parent_organizations
                                or user.organization.id in obj.event.created_by.parent_organizations
                                or user.id in list(User.objects.filter(
                                Q(writeevents__in=[obj.event.id]) | Q(readevents__in=[obj.event.id])
                            ).values_list('id', flat=True))):
                        fields = private_fields

        super(EventLocationSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = EventLocation
        fields = '__all__'
        extra_kwargs = {
            'country': {'required': False},
            'administrative_level_one': {'required': False}
        }


# TODO: implement check that only a user's org's contacts can be related to the org's event locations
class EventLocationContactSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        message_complete = "Contacts from a location from a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."

        # if this is a new EventLocationContact check if the Event is complete
        if not self.instance and data['event_location'].event.complete:
            raise serializers.ValidationError(message_complete)

        # else this is an existing EventLocationContact so check if this is an update and if parent Event is complete
        elif self.instance and self.instance.event_location.event.complete:
            raise serializers.ValidationError(message_complete)

        return data

    class Meta:
        model = EventLocationContact
        fields = ('id', 'event_location', 'contact', 'contact_type',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class CountrySerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = Country
        fields = ('id', 'name', 'abbreviation', 'calling_code',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class AdministrativeLevelOneSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    country_string = serializers.StringRelatedField(source='country')

    class Meta:
        model = AdministrativeLevelOne
        fields = ('id', 'name', 'country', 'country_string', 'abbreviation',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class AdministrativeLevelOneSlimSerializer(serializers.ModelSerializer):

    class Meta:
        model = AdministrativeLevelOne
        fields = ('id', 'name',)


class AdministrativeLevelTwoSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')

    class Meta:
        model = AdministrativeLevelTwo
        fields = ('id', 'name', 'administrative_level_one', 'administrative_level_one_string', 'points',
                  'centroid_latitude', 'centroid_longitude', 'fips_code',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class AdministrativeLevelTwoSlimSerializer(serializers.ModelSerializer):

    class Meta:
        model = AdministrativeLevelTwo
        fields = ('id', 'name',)


class AdministrativeLevelLocalitySerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = AdministrativeLevelLocality
        fields = ('id', 'country', 'admin_level_one_name', 'admin_level_two_name',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class LandOwnershipSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = LandOwnership
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


# TODO: implement check that flyway intersects location?
class EventLocationFlywaySerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        message_complete = "Flyways from a location from a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."

        # if this is a new EventLocationFlyway check if the Event is complete
        if not self.instance and data['event_location'].event.complete:
            raise serializers.ValidationError(message_complete)

        # else this is an existing EventLocationFlyway so check if this is an update and if parent Event is complete
        elif self.instance and self.instance.event_location.event.complete:
            raise serializers.ValidationError(message_complete)

        return data

    class Meta:
        model = EventLocationFlyway
        fields = ('id', 'event_location', 'flyway',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class FlywaySerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = Flyway
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


######
#
#  Species
#
######


class LocationSpeciesSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    new_species_diagnoses = serializers.ListField(write_only=True, required=False)

    def validate(self, data):

        message_complete = "Species from a location from a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."

        # if this is a new LocationSpecies
        if not self.instance:
            #  check if the Event is complete
            if data['event_location'].event.complete and 'FULL_EVENT_CHAIN_CREATE' not in self.initial_data:
                raise serializers.ValidationError(message_complete)
            # otherwise the Event is not complete (or complete but created in this chain), so apply business rules
            else:
                # 1. location_species Population >= max(estsick, knownsick) + max(estdead, knowndead)
                # 2. For morbidity/mortality events, there must be at least one number between sick, dead,
                #    estimated_sick, and estimated_dead for at least one species in the event
                #    at the time of event initiation. (sick + dead + estimated_sick + estimated_dead >= 1)
                # 3. If present, estimated_sick must be higher than known sick (estimated_sick > sick).
                # 4. If present, estimated dead must be higher than known dead (estimated_dead > dead).
                min_species_count = False
                pop_is_valid = True
                est_sick_is_valid = True
                est_dead_is_valid = True
                details = []

                if 'population_count' in data and data['population_count'] is not None:
                    dead_count = 0
                    sick_count = 0
                    if 'dead_count_estimated' in data or 'dead_count' in data:
                        dead_count = max(data.get('dead_count_estimated') or 0, data.get('dead_count') or 0)
                    if 'sick_count_estimated' in data or 'sick_count' in data:
                        sick_count = max(data.get('sick_count_estimated') or 0, data.get('sick_count') or 0)
                    if data['population_count'] < dead_count + sick_count:
                        pop_is_valid = False
                if ('sick_count_estimated' in data and data['sick_count_estimated'] is not None
                        and 'sick_count' in data and data['sick_count'] is not None
                        and data['sick_count_estimated'] <= data['sick_count']):
                    est_sick_is_valid = False
                if ('dead_count_estimated' in data and data['dead_count_estimated'] is not None
                        and 'dead_count' in data and data['dead_count'] is not None
                        and data['dead_count_estimated'] <= data['dead_count']):
                    est_dead_is_valid = False
                mm = EventType.objects.filter(name='Mortality/Morbidity').first()
                mm_lsps = None
                if data['event_location'].event.event_type.id == mm.id:
                    locspecs = LocationSpecies.objects.filter(event_location=data['event_location'].id)
                    mm_lsps = [locspec for locspec in locspecs if locspec.event_location.event.event_type.id == mm.id]
                    if mm_lsps is None:
                        if ('dead_count_estimated' in data and data['dead_count_estimated'] is not None
                                and data['dead_count_estimated'] > 0):
                            min_species_count = True
                        elif 'dead_count' in data and data['dead_count'] is not None and data['dead_count'] > 0:
                            min_species_count = True
                        elif ('sick_count_estimated' in data and data['sick_count_estimated'] is not None
                              and data['sick_count_estimated'] > 0):
                            min_species_count = True
                        elif 'sick_count' in data and data['sick_count'] is not None and data['sick_count'] > 0:
                            min_species_count = True

                if not pop_is_valid:
                    message = "New location_species population_count cannot be less than the sum of dead_count"
                    message += " and sick_count (where those counts are the maximum of the estimated or known count)."
                    details.append(message)
                if data['event_location'].event.event_type.id == mm.id and mm_lsps is None and not min_species_count:
                    message = "For Mortality/Morbidity events, at least one new_location_species requires"
                    message += " at least one species count in any of the following fields:"
                    message += " dead_count_estimated, dead_count, sick_count_estimated, sick_count."
                    details.append(message)
                if not est_sick_is_valid:
                    details.append("Estimated sick count must always be more than known sick count.")
                if not est_dead_is_valid:
                    details.append("Estimated dead count must always be more than known dead count.")
                if details:
                    raise serializers.ValidationError(details)

        # TODO: fix this to test against submitted data!!!
        # else this is an existing LocationSpecies
        elif self.instance:
            # check if parent Event is complete
            if self.instance.event_location.event.complete:
                raise serializers.ValidationError(message_complete)
            else:
                # 1. location_species Population >= max(estsick, knownsick) + max(estdead, knowndead)
                # 2. For morbidity/mortality events, there must be at least one number between sick, dead,
                #    estimated_sick, and estimated_dead for at least one species in the event
                #    at the time of event initiation. (sick + dead + estimated_sick + estimated_dead >= 1)
                # 3. If present, estimated_sick must be higher than known sick (estimated_sick > sick).
                # 4. If present, estimated dead must be higher than known dead (estimated_dead > dead).
                min_species_count = False
                pop_is_valid = True
                est_sick_is_valid = True
                est_dead_is_valid = True
                details = []

                # get the pop count
                if 'population_count' in data:
                    # can be null, per NWHC staff
                    pop_count = data.get('population_count')
                else:
                    pop_count = self.instance.population_count

                # get the dead count
                if 'dead_count_estimated' in data:
                    dead_count_est = data.get('dead_count_estimated')
                else:
                    dead_count_est = self.instance.dead_count_estimated
                if 'dead_count' in data:
                    dead_count = data.get('dead_count')
                else:
                    dead_count = self.instance.dead_count
                any_dead_count = max(dead_count_est or 0, dead_count or 0)

                # get the sick count
                if 'sick_count_estimated' in data:
                    sick_count_est = data.get('sick_count_estimated')
                else:
                    sick_count_est = self.instance.sick_count_estimated
                if 'sick_count' in data:
                    sick_count = data.get('sick_count')
                else:
                    sick_count = self.instance.sick_count
                any_sick_count = max(sick_count_est or 0, sick_count or 0)

                if pop_count and pop_count < (any_dead_count + any_sick_count):
                    pop_is_valid = False

                if sick_count_est and sick_count and sick_count_est <= sick_count:
                    est_sick_is_valid = False

                if dead_count_est and dead_count and dead_count_est <= dead_count:
                    est_dead_is_valid = False

                mm = EventType.objects.filter(name='Mortality/Morbidity').first()
                mm_lsps = None
                event_type_id = self.instance.event_location.event.event_type.id
                if event_type_id == mm.id:
                    locspecs = LocationSpecies.objects.filter(event_location=self.instance.event_location.id)
                    mm_lsps = [locspec for locspec in locspecs if event_type_id == mm.id]
                    if mm_lsps is None:
                        min_species_count = True if any_sick_count > 0 or any_dead_count > 0 else False

                if not pop_is_valid:
                    message = "New location_species population_count cannot be less than the sum of dead_count"
                    message += " and sick_count (where those counts are the maximum of the estimated or known count)."
                    details.append(message)
                if event_type_id == mm.id and mm_lsps is None and not min_species_count:
                    message = "For Mortality/Morbidity events, at least one new_location_species requires"
                    message += " at least one species count in any of the following fields:"
                    message += " dead_count_estimated, dead_count, sick_count_estimated, sick_count."
                    details.append(message)
                if not est_sick_is_valid:
                    details.append("Estimated sick count must always be more than known sick count.")
                if not est_dead_is_valid:
                    details.append("Estimated dead count must always be more than known dead count.")
                if details:
                    raise serializers.ValidationError(details)

        return data

    def create(self, validated_data):
        new_species_diagnoses = validated_data.pop('new_species_diagnoses', None)

        location_species = LocationSpecies.objects.create(**validated_data)

        if new_species_diagnoses is not None:
            is_valid = True
            valid_data = []
            errors = []
            for spec_diag in new_species_diagnoses:
                if spec_diag is not None:
                    # ensure this species diagnosis does not already exist
                    existing_spec_diag = SpeciesDiagnosis.objects.filter(
                        location_species=location_species.id, diagnosis=spec_diag['diagnosis'])

                    if len(existing_spec_diag) == 0:
                        spec_diag['location_species'] = location_species.id
                        spec_diag['created_by'] = location_species.created_by.id
                        spec_diag['modified_by'] = location_species.modified_by.id
                        if 'FULL_EVENT_CHAIN_CREATE' in self.initial_data:
                            spec_diag['FULL_EVENT_CHAIN_CREATE'] = self.initial_data['FULL_EVENT_CHAIN_CREATE']
                        spec_diag_serializer = SpeciesDiagnosisSerializer(data=spec_diag)
                        if spec_diag_serializer.is_valid():
                            valid_data.append(spec_diag_serializer)
                        else:
                            is_valid = False
                            errors.append(spec_diag_serializer.errors)
            if is_valid:
                # now that all items are proven valid, save and return them to the user
                for item in valid_data:
                    item.save()
            else:
                if self.initial_data['FULL_EVENT_CHAIN_CREATE']:
                    # delete the parent event, which will also delete this location species thru a cascade
                    location_species.event_location.event.delete()
                    # content_type = ContentType.objects.get_for_model(self.Meta.model).model
                    # cascade_delete_event_chain(content_type, location_species.event_location.event.id)
                else:
                    # delete this location species
                    location_species.delete()
                raise serializers.ValidationError(jsonify_errors(errors))

        # calculate the priority value:
        location_species.priority = calculate_priority_location_species(location_species)
        location_species.save(update_fields=['priority', ])

        return location_species

    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        # update the LocationSpecies object
        instance.species = validated_data.get('species', instance.species)
        instance.population_count = validated_data.get('population_count', instance.population_count)
        instance.sick_count = validated_data.get('sick_count', instance.sick_count)
        instance.dead_count = validated_data.get('dead_count', instance.dead_count)
        instance.sick_count_estimated = validated_data.get('sick_count_estimated', instance.sick_count_estimated)
        instance.dead_count_estimated = validated_data.get('dead_count_estimated', instance.dead_count_estimated)
        instance.captive = validated_data.get('captive', instance.captive)
        instance.age_bias = validated_data.get('age_bias', instance.age_bias)
        instance.sex_bias = validated_data.get('sex_bias', instance.sex_bias)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)
        instance.save()

        # calculate the priority value:
        instance.priority = calculate_priority_location_species(instance)
        instance.save(update_fields=['priority', ])

        return instance

    def __init__(self, *args, **kwargs):
        user = None
        action = 'list'
        if 'context' in kwargs:
            # this was triggered by a direct request to the endpoint
            if 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
                user = kwargs['context']['request'].user
            if 'view' in kwargs['context'] and hasattr(kwargs['context']['view'], 'action'):
                action = kwargs['context']['view'].action
        elif 'data' in kwargs:
            # this was triggered by another serializer or view
            user = User.objects.filter(id=kwargs['data']['created_by']).first()
            action = 'create'

        fields = ('species', 'population_count', 'sick_count', 'dead_count', 'sick_count_estimated',
                  'dead_count_estimated', 'captive', 'age_bias', 'sex_bias',)
        private_fields = ('id', 'event_location', 'species', 'population_count', 'sick_count', 'dead_count',
                          'sick_count_estimated', 'dead_count_estimated', 'priority', 'captive', 'age_bias', 'sex_bias',
                          'new_species_diagnoses', 'created_date', 'created_by', 'created_by_string',
                          'modified_date', 'modified_by', 'modified_by_string',)

        if user and user.is_authenticated:
            if action == 'create' or user.role.is_superadmin or user.role.is_admin:
                fields = private_fields
            elif action in PK_REQUESTS and hasattr(kwargs['context']['request'], 'parser_context'):
                pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdecimal():
                    obj = LocationSpecies.objects.filter(id=pk).first()
                    if obj and (user.id == obj.created_by.id or user.id == obj.event_location.event.created_by.id
                                or user.organization.id == obj.created_by.organization.id
                                or user.organization.id == obj.event_location.event.created_by.organization.id
                                or user.organization.id in obj.created_by.parent_organizations
                                or user.organization.id in obj.event_location.event.created_by.parent_organizations
                                or user.id in list(User.objects.filter(
                                Q(writeevents__in=[obj.event_location.event.id]) | Q(
                                    readevents__in=[obj.event_location.event.id])
                            ).values_list('id', flat=True))):
                        fields = private_fields

        super(LocationSpeciesSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = LocationSpecies
        fields = '__all__'


class SpeciesSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = Species
        fields = ('id', 'name', 'class_name', 'order_name', 'family_name', 'sub_family_name', 'genus_name',
                  'species_latin_name', 'subspecies_latin_name', 'tsn',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class SpeciesSlimSerializer(serializers.ModelSerializer):

    class Meta:
        model = Species
        fields = ('id', 'name',)


class AgeBiasSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = AgeBias
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class SexBiasSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = SexBias
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


######
#
#  Diagnoses
#
######


class DiagnosisSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    diagnosis_type_string = serializers.StringRelatedField(source='diagnosis_type')

    class Meta:
        model = Diagnosis
        fields = ('id', 'name', 'high_impact', 'diagnosis_type', 'diagnosis_type_string',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class DiagnosisTypeSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = DiagnosisType
        fields = ('id', 'name', 'color', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class EventDiagnosisSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    diagnosis_string = serializers.CharField(read_only=True)
    diagnosis_type = serializers.PrimaryKeyRelatedField(source='diagnosis.diagnosis_type', read_only=True)
    diagnosis_type_string = serializers.StringRelatedField(source='diagnosis.diagnosis_type')

    def validate(self, data):

        message_complete = "Diagnosis from a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."
        # if this is a new EventDiagnosis
        if not self.instance:
            eventdiags = EventDiagnosis.objects.filter(event=data['event'].id)
        else:
            # else this is an existing EventDiagnosis
            eventdiags = EventDiagnosis.objects.filter(event=self.instance.id)
        event_specdiags = []

        # if this is a new EventDiagnosis check if the Event is complete
        if not self.instance:
            # check if the Event is complete
            if data['event'].complete and 'FULL_EVENT_CHAIN_CREATE' not in self.initial_data:
                raise serializers.ValidationError(message_complete)

            else:
                diagnosis = data['diagnosis']

                # check that submitted diagnosis is not Pending if even one EventDiagnosis for this event already exists
                if eventdiags and diagnosis.name == 'Pending':
                    message = "A Pending diagnosis for Event Diagnosis is not allowed"
                    message += " when other event diagnoses already exist for this event."
                    raise serializers.ValidationError(message)

                event_specdiags = SpeciesDiagnosis.objects.filter(
                    location_species__event_location__event=data['event'].id
                ).values_list('diagnosis', flat=True).distinct()

        # else this is an existing EventDiagnosis
        elif self.instance:
            # check if parent Event is complete
            if self.instance.event.complete:
                raise serializers.ValidationError(message_complete)

            else:
                diagnosis = data['diagnosis'] if 'diagnosis' in data else self.instance.diagnosis

                # check that submitted diagnosis is not Pending if even one EventDiagnosis for this event already exists
                if eventdiags and diagnosis.name == 'Pending':
                    message = "A Pending diagnosis for Event Diagnosis is not allowed"
                    message += " when other event diagnoses already exist for this event."
                    raise serializers.ValidationError(message)

                event_specdiags = list(SpeciesDiagnosis.objects.filter(
                    location_species__event_location__event=self.instance.event.id).values_list(
                    'diagnosis', flat=True).distinct())

                if 'diagnosis' not in data or data['diagnosis'] is None:
                    data['diagnosis'] = self.instance.diagnosis

        # check that submitted diagnosis is also in this event's species diagnoses
        if ((not event_specdiags or diagnosis.id not in event_specdiags)
                and diagnosis.name not in ['Pending', 'Undetermined']):
            message = "A diagnosis for Event Diagnosis must match a diagnosis of a Species Diagnosis of this event."
            raise serializers.ValidationError(message)

        return data

    def create(self, validated_data):

        # ensure this new event diagnosis has the correct suspect value
        # (false if any matching species diagnoses are false, otherwise true)
        event = validated_data['event']
        diagnosis = validated_data['diagnosis']
        submitted_suspect = validated_data.pop('suspect') if 'suspect' in validated_data else True
        matching_specdiags_suspect = SpeciesDiagnosis.objects.filter(
            location_species__event_location__event=event.id, diagnosis=diagnosis.id
        ).values_list('suspect', flat=True)
        suspect = False if False in matching_specdiags_suspect else submitted_suspect
        event_diagnosis = EventDiagnosis.objects.create(**validated_data, suspect=suspect)
        event_diagnosis.priority = calculate_priority_event_diagnosis(event_diagnosis)
        event_diagnosis.save(update_fields=['priority', ])

        # Now that we have the new event diagnoses created,
        # check for existing Pending record and delete it
        event_diagnoses = EventDiagnosis.objects.filter(event=event_diagnosis.event.id)
        [diag.delete() for diag in event_diagnoses if diag.diagnosis.name == 'Pending']

        # If the parent event is complete, also check for existing Undetermined record and delete it
        if event_diagnosis.event.complete:
            [diag.delete() for diag in event_diagnoses if diag.diagnosis.name == 'Undetermined']

        # calculate the priority value:
        event_diagnosis.priority = calculate_priority_event_diagnosis(event_diagnosis)
        event_diagnosis.save(update_fields=['priority', ])

        return event_diagnosis

    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        # update the EventDiagnosis object
        instance.diagnosis = validated_data.get('diagnosis', instance.diagnosis)
        instance.major = validated_data.get('major', instance.major)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

        # ensure this event diagnosis has the correct suspect value
        # (false if any matching species diagnoses are false, otherwise true)
        matching_specdiags_suspect = SpeciesDiagnosis.objects.filter(
            location_species__event_location__event=instance.event.id, diagnosis=instance.diagnosis.id
        ).values_list('suspect', flat=True)
        instance.suspect = False if False in matching_specdiags_suspect else True

        # Now that we have the new event diagnoses created, check for existing Pending record and delete it
        event_diagnoses = EventDiagnosis.objects.filter(event=instance.event.id)
        [diag.delete() for diag in event_diagnoses if diag.diagnosis.name == 'Pending']

        # If the parent event is complete, also check for existing Undetermined record and delete it
        if instance.event.complete:
            [diag.delete() for diag in event_diagnoses if diag.diagnosis.name == 'Undetermined']

        instance.save()

        # calculate the priority value:
        instance.priority = calculate_priority_event_diagnosis(instance)
        instance.save(update_fields=['priority', ])

        return instance

    def __init__(self, *args, **kwargs):
        user = None
        action = 'list'
        if 'context' in kwargs:
            # this was triggered by a direct request to the endpoint
            if 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
                user = kwargs['context']['request'].user
            if 'view' in kwargs['context'] and hasattr(kwargs['context']['view'], 'action'):
                action = kwargs['context']['view'].action
        elif 'data' in kwargs:
            # this was triggered by another serializer or view
            user = User.objects.filter(id=kwargs['data']['created_by']).first()
            action = 'create'

        fields = ('diagnosis', 'diagnosis_string', 'diagnosis_type', 'diagnosis_type_string', 'suspect', 'major',)
        private_fields = ('id', 'event', 'diagnosis', 'diagnosis_string', 'diagnosis_type', 'diagnosis_type_string',
                          'suspect', 'major', 'priority', 'created_date', 'created_by', 'created_by_string',
                          'modified_date', 'modified_by', 'modified_by_string',)

        if user and user.is_authenticated:
            if action == 'create' or user.role.is_superadmin or user.role.is_admin:
                fields = private_fields
            elif action in PK_REQUESTS and hasattr(kwargs['context']['request'], 'parser_context'):
                pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdecimal():
                    obj = EventDiagnosis.objects.filter(id=pk).first()
                    if obj and (user.id == obj.created_by.id or user.id == obj.event.created_by.id
                                or user.organization.id == obj.created_by.organization.id
                                or user.organization.id == obj.event.created_by.organization.id
                                or user.organization.id in obj.created_by.parent_organizations
                                or user.organization.id in obj.event.created_by.parent_organizations
                                or user.id in list(User.objects.filter(
                                Q(writeevents__in=[obj.event.id]) | Q(readevents__in=[obj.event.id])
                            ).values_list('id', flat=True))):
                        fields = private_fields

        super(EventDiagnosisSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = EventDiagnosis
        fields = '__all__'


class SpeciesDiagnosisSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    new_species_diagnosis_organizations = serializers.ListField(write_only=True, required=False)
    diagnosis_string = serializers.CharField(read_only=True)
    basis_string = serializers.StringRelatedField(source='basis')
    cause_string = serializers.StringRelatedField(source='cause')

    def validate(self, data):

        message_complete = "Diagnoses from a species from a location from a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."

        # if this is a new SpeciesDiagnosis
        if not self.instance:
            # check if this is an update and if parent Event is complete
            if (data['location_species'].event_location.event.complete
                    and 'FULL_EVENT_CHAIN_CREATE' not in self.initial_data):
                raise serializers.ValidationError(message_complete)
            # otherwise the Event is not complete (or complete but created in this chain), so apply business rules
            else:
                suspect = data['suspect'] if 'suspect' in data and data['suspect'] else None
                tested_count = data['tested_count'] if 'tested_count' in data and data[
                    'tested_count'] is not None else None
                suspect_count = data['suspect_count'] if 'suspect_count' in data and data[
                    'suspect_count'] is not None else None
                pos_count = data['positive_count'] if 'positive_count' in data and data[
                    'positive_count'] is not None else None

                # Non-suspect diagnosis cannot have basis_of_dx = 1,2, or 4.
                # TODO: following rule would only work on update due to M:N relate to orgs, so on-hold until further notice
                # If 3 is selected user must provide a lab.
                if suspect and 'basis' in data and data['basis'] in [1, 2, 4]:
                    message = "The basis of diagnosis can only be 'Necropsy and/or ancillary tests performed"
                    message += " at a diagnostic laboratory' when the diagnosis is non-suspect."
                    raise serializers.ValidationError(message)

                if tested_count is not None:
                    # Within each species diagnosis, number_with_diagnosis =< number_tested.
                    if ('diagnosis_count' in data and data['diagnosis_count'] is not None
                            and not data['diagnosis_count'] <= tested_count):
                        raise serializers.ValidationError("The diagnosed count cannot be more than the tested count.")
                    # TODO: temporarily disabling the following three rule per instructions from cooperator (November 2018)
                    # Within each species diagnosis, number_positive+number_suspect =< number_tested
                    # if pos_count and suspect_count and not (pos_count + suspect_count <= tested_count):
                    #     message = "The positive count and suspect count together cannot be more than the diagnosed count."
                    #     raise serializers.ValidationError(message)
                    # elif pos_count and not (pos_count <= tested_count):
                    #     message = "The positive count cannot be more than the diagnosed count."
                    #     raise serializers.ValidationError(message)
                    # elif suspect_count and not (suspect_count <= tested_count):
                    #     message = "The suspect count together cannot be more than the diagnosed count."
                    #     raise serializers.ValidationError(message)
                # Within each species diagnosis, number_with_diagnosis =< number_tested.
                # here, tested_count was not submitted, so if diagnosis_count was submitted and is not null, raise an error
                # elif 'diagnosis_count' in data and data['diagnosis_count'] is not None:
                #     raise serializers.ValidationError("The diagnosed count cannot be more than the tested count.")

                # If diagnosis is non-suspect (suspect=False), then number_positive must be null or greater than zero,
                # else diagnosis is suspect (suspect=True) and so number_positive must be zero
                # TODO: following rule would only work on update due to M:N relate to orgs, so on-hold until further notice
                # Only allowed to enter >0 if provide laboratory name.
                # if not suspect and (not pos_count or pos_count > 0):
                #     raise serializers.ValidationError("The positive count cannot be zero when the diagnosis is non-suspect.")

                # TODO: temporarily disabling this rule
                # if 'pooled' in data and data['pooled'] and tested_count <= 1:
                #     raise serializers.ValidationError("A diagnosis can only be pooled if the tested count is greater than one.")

                # TODO: following rule would only work on update due to M:N relate to orgs, so on-hold until further notice
                # For new data, if no Lab provided, then suspect = True; although all "Pending" and "Undetermined"
                # diagnosis must be confirmed (suspect = False), even if no lab OR some other way of coding this such that we

        # else this is an existing SpeciesDiagnosis
        elif self.instance:
            # check if parent Event is complete
            if self.instance.location_species.event_location.event.complete:
                raise serializers.ValidationError(message_complete)
            else:
                # for positive_count, only allowed to enter >0 if provide laboratory name.
                if self.instance.positive_count and self.instance.positive_count > 0:
                    # get the old (current) org ID list for this Species Diagnosis
                    old_org_ids = list(SpeciesDiagnosisOrganization.objects.filter(
                        species_diagnosis=self.instance.id).values_list('organization_id', flat=True))

                    # pull out org ID list from the request
                    new_org_ids = data['new_species_diagnosis_organizations']

                    if len(old_org_ids) == 0 or len(new_org_ids) == 0:
                        message = "The positive count cannot be greater than zero"
                        message += " if there is no laboratory for this diagnosis."
                        raise serializers.ValidationError(message)

                # a diagnosis can only be used once for a location-species-labID combination
                loc_specdiags = SpeciesDiagnosis.objects.filter(
                    location_species=self.instance.location_species
                ).values('id', 'diagnosis').exclude(id=self.instance.id)
                if self.instance.diagnosis.id in [specdiag['diagnosis'] for specdiag in loc_specdiags]:
                    loc_specdiags_ids = [specdiag['id'] for specdiag in loc_specdiags]
                    loc_specdiags_labs_ids = set(SpeciesDiagnosisOrganization.objects.filter(
                        species_diagnosis__in=loc_specdiags_ids).values_list('id', flat=True))
                    my_labs_ids = [org.id for org in self.instance.organizations.all()]
                    if len([lab_id for lab_id in my_labs_ids if lab_id in loc_specdiags_labs_ids]) > 0:
                        message = "A diagnosis can only be used once for a location-species-laboratory combination."
                        raise serializers.ValidationError(message)

        if 'new_species_diagnosis_organizations' in data and data['new_species_diagnosis_organizations'] is not None:
            for org_id in data['new_species_diagnosis_organizations']:
                org = Organization.objects.filter(id=org_id).first()
                if org and not org.laboratory:
                    raise serializers.ValidationError("SpeciesDiagnosis Organization can only be a laboratory.")

        return data

    def create(self, validated_data):
        new_species_diagnosis_organizations = validated_data.pop('new_species_diagnosis_organizations', None)

        species_diagnosis = SpeciesDiagnosis.objects.create(**validated_data)

        # calculate the priority value:
        species_diagnosis.priority = calculate_priority_species_diagnosis(species_diagnosis)
        species_diagnosis.save(update_fields=['priority', ])

        if new_species_diagnosis_organizations is not None:
            for org_id in new_species_diagnosis_organizations:
                org = Organization.objects.filter(id=org_id).first()
                if org:
                    user = get_user(self.context, self.initial_data)
                    SpeciesDiagnosisOrganization.objects.create(species_diagnosis=species_diagnosis,
                                                                organization=org, created_by=user, modified_by=user)

        return species_diagnosis

    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        # update the SpeciesDiagnosis object
        instance.diagnosis = validated_data.get('diagnosis', instance.diagnosis)
        instance.cause = validated_data.get('cause', instance.cause)
        instance.basis = validated_data.get('basis', instance.basis)
        instance.suspect = validated_data.get('suspect', instance.suspect)
        instance.tested_count = validated_data.get('tested_count', instance.tested_count)
        instance.diagnosis_count = validated_data.get('diagnosis_count', instance.diagnosis_count)
        instance.positive_count = validated_data.get('positive_count', instance.positive_count)
        instance.suspect_count = validated_data.get('suspect_count', instance.suspect_count)
        instance.pooled = validated_data.get('pooled', instance.pooled)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

        # get the old (current) org ID list for this Species Diagnosis
        old_org_ids = list(SpeciesDiagnosisOrganization.objects.filter(
            species_diagnosis=instance.id).values_list('organization_id', flat=True))

        # pull out org ID list from the request
        new_org_ids = validated_data.pop('new_species_diagnosis_organizations', [])

        instance.save()

        # calculate the priority value:
        instance.priority = calculate_priority_species_diagnosis(instance)
        instance.save(update_fields=['priority', ])

        # identify and delete relates where org IDs are present in old list but not new list
        delete_org_ids = list(set(old_org_ids) - set(new_org_ids))
        for org_id in delete_org_ids:
            delete_org = SpeciesDiagnosisOrganization.objects.filter(species_diagnosis=instance.id, organization=org_id)
            delete_org.delete()

        # identify and create relates where sample IDs are present in new list but not old list
        add_org_ids = list(set(new_org_ids) - set(old_org_ids))
        for org_id in add_org_ids:
            org = Organization.objects.filter(id=org_id).first()
            if org:
                SpeciesDiagnosisOrganization.objects.create(species_diagnosis=instance, organization=org,
                                                            created_by=user, modified_by=user)

        return instance

    def __init__(self, *args, **kwargs):
        user = None
        action = 'list'
        if 'context' in kwargs:
            # this was triggered by a direct request to the endpoint
            if 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
                user = kwargs['context']['request'].user
            if 'view' in kwargs['context'] and hasattr(kwargs['context']['view'], 'action'):
                action = kwargs['context']['view'].action
        elif 'data' in kwargs:
            # this was triggered by another serializer or view
            user = User.objects.filter(id=kwargs['data']['created_by']).first()
            action = 'create'

        fields = ('diagnosis', 'diagnosis_string', 'suspect', 'tested_count', 'diagnosis_count', 'positive_count',
                  'suspect_count', 'pooled',)
        private_fields = ('id', 'location_species', 'diagnosis', 'diagnosis_string', 'cause', 'cause_string', 'basis',
                          'basis_string', 'suspect', 'priority', 'tested_count', 'diagnosis_count', 'positive_count',
                          'suspect_count', 'pooled', 'organizations', 'new_species_diagnosis_organizations',
                          'created_date', 'created_by', 'created_by_string',
                          'modified_date', 'modified_by', 'modified_by_string',)

        if user and user.is_authenticated:
            if action == 'create' or user.role.is_superadmin or user.role.is_admin:
                fields = private_fields
            elif action in PK_REQUESTS and hasattr(kwargs['context']['request'], 'parser_context'):
                pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdecimal():
                    obj = SpeciesDiagnosis.objects.filter(id=pk).first()
                    if obj and (user.id == obj.created_by.id or user.id == obj.location_species.event_location.event.created_by.id
                                or user.organization.id == obj.created_by.organization.id
                                or user.organization.id == obj.location_species.event_location.event.created_by.organization.id
                                or user.organization.id in obj.created_by.parent_organizations
                                or user.organization.id in obj.location_species.event_location.event.created_by.parent_organizations
                                or user.id in list(User.objects.filter(
                                Q(writeevents__in=[obj.location_species.event_location.event.id]) | Q(
                                    readevents__in=[obj.location_species.event_location.event.id])
                            ).values_list('id', flat=True))):
                        fields = private_fields

        super(SpeciesDiagnosisSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = SpeciesDiagnosis
        fields = '__all__'
        validators = [
            validators.UniqueTogetherValidator(
                queryset=SpeciesDiagnosis.objects.all(),
                fields=('location_species', 'diagnosis')
            )
        ]


class SpeciesDiagnosisOrganizationSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        message_complete = "Organizations from a diagnosis from a species from a location from a complete event may not"
        message_complete += " be changed unless the event is first re-opened by the event owner or an administrator."

        # if this is a new SpeciesDiagnosis check if the Event is complete
        if not self.instance:
            # check if the Event is complete
            if data['species_diagnosis'].location_species.event_location.event.complete:
                raise serializers.ValidationError(message_complete)

            if not data['organization'].laboratory:
                raise serializers.ValidationError("SpeciesDiagnosis Organization can only be a laboratory.")

        # else this is an existing SpeciesDiagnosis
        elif self.instance:
            # check if parent Event is complete
            if self.instance.location_species.event_location.event.complete:
                raise serializers.ValidationError(message_complete)

            if 'organization' in data and not data['organization'].laboratory:
                raise serializers.ValidationError("SpeciesDiagnosis Organization can only be a laboratory.")

        # a diagnosis can only be used once for a location-species-labID combination
        # NOTE: this works better as a model unique_together constraint, confirmed with cooperator
        # specdiag = SpeciesDiagnosis.objects.filter(id=data['species_diagnosis'].id).first()
        # other_specdiag_same_locspec_diag_ids = SpeciesDiagnosis.objects.filter(
        #     location_species=specdiag.location_species, diagnosis=specdiag.diagnosis).values_list('id', flat=True)
        # org_combos = SpeciesDiagnosisOrganization.objects.filter(
        #     species_diagnosis__in=other_specdiag_same_locspec_diag_ids).values_list('organization_id', flat=True)
        # if data['organization'].id in org_combos:
        #     message = "A diagnosis can only be used once for a location-species-lab combination."
        #     raise serializers.ValidationError(message)

        return data

    class Meta:
        model = SpeciesDiagnosisOrganization
        fields = ('id', 'species_diagnosis', 'organization',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)
        validators = [
            validators.UniqueTogetherValidator(
                queryset=SpeciesDiagnosisOrganization.objects.all(),
                fields=('species_diagnosis', 'organization')
            )
        ]


class DiagnosisBasisSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = DiagnosisBasis
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class DiagnosisCauseSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = DiagnosisCause
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


######
#
#  Service Requests
#
######


class ServiceRequestSerializer(serializers.ModelSerializer):
    comments = CommentSerializer(many=True, read_only=True)
    new_comments = serializers.ListField(write_only=True, required=False)
    service_request_email = serializers.JSONField(read_only=True)

    def validate(self, data):
        if 'new_comments' in data and data['new_comments'] is not None:
            for item in data['new_comments']:
                if 'comment' not in item or not item['comment']:
                    raise serializers.ValidationError("A comment must have comment text.")
                elif 'comment_type' not in item or not item['comment_type']:
                    item["comment_type"] = CommentType.objects.filter(name='Diagnostic').first().id

        return data

    def create(self, validated_data):
        user = get_user(self.context, self.initial_data)

        # pull out child comments list from the request
        new_comments = validated_data.pop('new_comments', None)

        # Only allow NWHC admins to alter the request response
        if 'request_response' in validated_data and validated_data['request_response'] is not None:
            if not (user.role.is_superadmin or user.role.is_admin):
                raise serializers.ValidationError(
                    jsonify_errors("You do not have permission to alter the request response."))
            else:
                validated_data['response_by'] = user

        # if a request_response is not submitted, assign the default
        if 'request_response' not in validated_data or validated_data['request_response'] is None:
            validated_data['request_response'] = ServiceRequestResponse.objects.filter(name='Pending').first()
            validated_data['response_by'] = User.objects.filter(id=1).first()

        service_request = ServiceRequest.objects.create(**validated_data)

        # create the child comments for this service request
        if new_comments is not None:
            for comment in new_comments:
                if comment is not None:
                    if 'comment_type' in comment and comment['comment_type'] is not None:
                        comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                        if not comment_type:
                            comment_type = CommentType.objects.filter(name='Diagnostic').first()
                    else:
                        comment_type = CommentType.objects.filter(name='Diagnostic').first()
                    Comment.objects.create(content_object=service_request, comment=comment['comment'],
                                           comment_type=comment_type, created_by=user, modified_by=user)

        # Create a 'Service Request' notification
        msg_tmp = NotificationMessageTemplate.objects.filter(name='Service Request').first()
        if not msg_tmp:
            send_missing_notification_template_message_email('servicerequestserializer_create',
                                                             'Service Request')
        else:
            # determine which epi user (madison or hawaii (hfs)) receive notification (depends on event location)
            event_id = service_request.event.id
            evt_locs = EventLocation.objects.filter(event=event_id)
            HFS_LOCATIONS = get_hfs_locations()
            if HFS_LOCATIONS and any([evt_loc.administrative_level_one.id in HFS_LOCATIONS for evt_loc in evt_locs]):
                epi_user = User.objects.filter(id=get_hfs_epi_user_id()).first()
            else:
                epi_user = User.objects.filter(id=get_madison_epi_user_id()).first()
            # source: User making a service request.
            source = user.username
            # recipients: nwhc-epi@usgs.gov or HFS dropbox
            recipients = [epi_user.id, ]
            # email forwarding: Automatic, to nwhc-epi@usgs.gov or email for HFS, depending on location of event.
            email_to = [epi_user.email, ]
            short_evt_locs = ""
            for evt_loc in evt_locs:
                short_evt_loc = ""
                if evt_loc.administrative_level_two:
                    short_evt_loc += evt_loc.administrative_level_two.name + ", "
                short_evt_loc += evt_loc.administrative_level_one.abbreviation + ", " + evt_loc.country.abbreviation
                short_evt_locs = short_evt_loc if len(short_evt_locs) == 0 else short_evt_locs + "; " + short_evt_loc
            content_type = ContentType.objects.get_for_model(self.Meta.model, for_concrete_model=True)
            comments = Comment.objects.filter(content_type=content_type, object_id=service_request.id)
            if comments:
                combined_comment = ""
                for comment in comments:
                    combined_comment = combined_comment + "<br />" + comment.comment
            else:
                combined_comment = "None"
            try:
                subject = msg_tmp.subject_template.format(service_request=service_request.request_type.name,
                                                          event_id=event_id)
            except KeyError as e:
                send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                subject = ""
            try:
                body = msg_tmp.body_template.format(first_name=user.first_name, last_name=user.last_name,
                                                    organization=user.organization.name,
                                                    service_request=service_request.request_type.name,
                                                    event_id=event_id, event_location=short_evt_locs,
                comment=combined_comment)
            except KeyError as e:
                send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                body = ""
            generate_notification.delay(recipients, source, event_id, 'event', subject, body, True, email_to)

        return service_request

    def update(self, instance, validated_data):

        # remove child comments list from the request
        if 'new_comments' in validated_data:
            validated_data.pop('new_comments')

        # Only allow NWHC admins to alter the request response
        if 'request_response' in validated_data and validated_data['request_response'] is not None:
            user = get_user(self.context, self.initial_data)

            if not (user.role.is_superadmin or user.role.is_admin):
                raise serializers.ValidationError(
                    jsonify_errors("You do not have permission to alter the request response."))
            else:
                instance.response_by = user
                instance.request_response = validated_data.get('request_response', instance.request_response)

                # capture the service request response as a comment
                cmt = "Service Request Response: " + instance.request_response.name
                cmt_type = CommentType.objects.filter(name='Other').first()
                Comment.objects.create(content_object=instance, comment=cmt,
                                       comment_type=cmt_type, created_by=user, modified_by=user)

        instance.request_type = validated_data.get('request_type', instance.request_type)

        instance.save()
        return instance

    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    response_by = serializers.StringRelatedField()

    class Meta:
        model = ServiceRequest
        fields = ('id', 'event', 'request_type', 'request_response', 'response_by', 'created_time', 'comments',
                  'new_comments', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string', 'service_request_email')


class ServiceRequestTypeSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = ServiceRequestType
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class ServiceRequestResponseSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = ServiceRequestResponse
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


######
#
#  Service Requests
#
######


class NotificationSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def update(self, instance, validated_data):
        # only the 'read' field can be updated
        instance.read = validated_data.get('read', instance.read)
        instance.save()
        return instance

    class Meta:
        model = Notification
        fields = ('id', 'recipient', 'source', 'event', 'read', 'client_page', 'subject', 'body',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class NotificationCuePreferenceSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = NotificationCuePreference
        fields = ('id', 'create_when_new', 'create_when_modified', 'send_email',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class NotificationCueCustomSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    notification_cue_preference = NotificationCuePreferenceSerializer(read_only=True)
    new_notification_cue_preference = serializers.JSONField(write_only=True, required=True)
    cue_strings = serializers.SerializerMethodField()

    def get_cue_strings(self, obj):
        data = []
        model_fields = ['event', 'event_affected_count', 'event_location_land_ownership',
                        'event_location_administrative_level_one', 'species', 'species_diagnosis_diagnosis']
        string_repr_fields = ['Event', 'Affected Count', 'Land Ownership', 'Administrative Level One', 'Species',
                              'Diagnosis']
        model_fields_models = ['Event', 'Event', 'LandOwnership', 'AdministrativeLevelOne', 'Species', 'Diagnosis']
        for field in model_fields:
            field_value = getattr(obj, field)
            if field_value is not None and field_value != {}:
                string_repr = string_repr_fields[model_fields.index(field)] + ": "
                # if field is admin level one, use locality name when possible
                if field == 'event_location_administrative_level_one':
                    al1 = obj.event_location_administrative_level_one
                    if al1 is not None and 'values' in al1:
                        al1s = obj.event_location_administrative_level_one['values']
                        ctry_ids = list(Country.objects.filter(
                            administrativelevelones__in=al1s).values_list('id', flat=True))
                        if ctry_ids:
                            locality = AdministrativeLevelLocality.objects.filter(country=ctry_ids[0]).first()
                            if locality and locality.admin_level_one_name is not None:
                                string_repr = locality.admin_level_one_name + ": "

                if field == 'event':
                    string_repr += str(field_value)
                    data.append(string_repr)
                # if field is event affected_count, include the operators from event_affected_count_operator field
                elif field == 'event_affected_count':
                    operator = getattr(obj, 'event_affected_count_operator')
                    if operator == 'LTE':
                        string_repr += "<= " + str(field_value)
                    else:
                        string_repr += ">= " + str(field_value)
                    data.append(string_repr)
                else:
                    # it is a JSON field
                    values = getattr(obj, field)['values']
                    ThisModel = apps.get_model('whispersapi', model_fields_models[model_fields.index(field)])
                    if len(values) == 1:
                        string_repr += str(ThisModel.objects.filter(id=values[0]).first())
                        data.append(string_repr)
                    elif len(values) > 1:
                        list_len = len(values)
                        count = 0
                        operator = getattr(obj, field)['operator']
                        values_items = ""
                        for value in values:
                            values_items += str(ThisModel.objects.filter(id=value).first())
                            count += 1
                            if count != list_len:
                                values_items += " " + operator + " "
                        string_repr += values_items
                        data.append(string_repr)
                    # ignore empty value lists

        return data

    def validate(self, data):
        # validate that event_affected_count_operator is present when event_affected_count is present, and vice-versa
        if ('event_affected_count_operator' in data and data['event_affected_count_operator'] is not None
                and ('event_affected_count' not in data or data['event_affected_count'] is None)):
            message = "event_affected_count must be submitted when event_affected_count_operator is submitted"
            raise serializers.ValidationError(message)
        elif ('event_affected_count' in data and data['event_affected_count'] is not None
              and ('event_affected_count_operator' not in data or data['event_affected_count_operator'] is None)):
            message = "event_affected_count_operator must be submitted when event_affected_count is submitted"
            raise serializers.ValidationError(message)
        # validate event_affected_count_operator field
        if ('event_affected_count_operator' in data and data['event_affected_count_operator'] is not None
                and data['event_affected_count_operator'] not in ['GTE', 'LTE']):
            message = "event_affected_count_operator can only be \"GTE\" or \"LTE\""
            message += " (greater-than-or-equal-to or less-than-or-equal-to)"
            raise serializers.ValidationError(message)
        # validate JSON fields
        json_fields = ['event_location_land_ownership', 'event_location_administrative_level_one', 'species',
                       'species_diagnosis_diagnosis']
        for field in json_fields:
            if field in data and data[field] is not None:
                if (not isinstance(data[field], dict)
                        or (len(data[field]) > 0) and ('values' not in data[field] or 'operator' not in data[field])
                        or (not isinstance(data[field]['values'], list))
                        or (not isinstance(data[field]['operator'], str)
                            or data[field]['operator'] not in ["AND", "OR"])):
                    message = field + " must be valid JSON with only two keys:"
                    message += " \"values\" (an array or list of integers)"
                    message += " and \"operator\" (which can only be \"AND\" or \"OR\"), or an empty JSON object"
                    raise serializers.ValidationError(message)

        return data

    def create(self, validated_data):
        user = get_user(self.context, self.initial_data)

        # pull out child notification cue preferences from the request
        new_pref = validated_data.pop('new_notification_cue_preference', None)
        create_when_new = NotificationCuePreference._meta.get_field('create_when_new').get_default()
        create_when_modified = NotificationCuePreference._meta.get_field('create_when_modified').get_default()
        send_email = NotificationCuePreference._meta.get_field('send_email').get_default()
        if new_pref:
            if ('create_when_new' in new_pref and new_pref['create_when_new'] is not None
                    and isinstance(new_pref['create_when_new'], bool)):
                create_when_new = new_pref['create_when_new']
            if ('create_when_modified' in new_pref and new_pref['create_when_modified'] is not None
                    and isinstance(new_pref['create_when_modified'], bool)):
                create_when_modified = new_pref['create_when_modified']
            if ('send_email' in new_pref and new_pref['send_email'] is not None
                    and isinstance(new_pref['send_email'], bool)):
                send_email = new_pref['send_email']
        pref = {'create_when_new': create_when_new, 'create_when_modified': create_when_modified,
                'send_email': send_email, 'created_by': user.id, 'modified_by': user.id}
        pref_serializer = NotificationCuePreferenceSerializer(data=pref)
        if pref_serializer.is_valid():
            validated_data['notification_cue_preference'] = pref_serializer.save()
            return NotificationCueCustom.objects.create(**validated_data)
        else:
            raise serializers.ValidationError(jsonify_errors(pref_serializer.errors))

    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        # pull out child notification cue preferences from the request and update it if necessary
        new_pref = validated_data.pop('new_notification_cue_preference', None)
        if new_pref:
            pref = NotificationCuePreference.objects.filter(id=instance.notification_cue_preference.id).first()
            if ('create_when_new' in new_pref and new_pref['create_when_new'] is not None
                    and isinstance(new_pref['create_when_new'], bool)):
                pref.create_when_new = new_pref['create_when_new']
            if ('create_when_modified' in new_pref and new_pref['create_when_modified'] is not None
                    and isinstance(new_pref['create_when_modified'], bool)):
                pref.create_when_modified = new_pref['create_when_modified']
            if ('send_email' in new_pref and new_pref['send_email'] is not None
                    and isinstance(new_pref['send_email'], bool)):
                pref.send_email = new_pref['send_email']
            pref.modified_by = user if user else pref.modified_by
            pref.save()

        # update the NotificationCueCustom object
        instance.event = validated_data.get('event', instance.event)
        instance.event_affected_count = validated_data.get('event_affected_count', instance.event_affected_count)
        instance.event_affected_count_operator = validated_data.get(
            'event_affected_count_operator', instance.event_affected_count_operator)
        instance.event_location_land_ownership = validated_data.get('event_location_land_ownership',
                                                                    instance.event_location_land_ownership)
        instance.event_location_administrative_level_one = validated_data.get(
            'event_location_administrative_level_one',
            instance.event_location_administrative_level_one)
        instance.species = validated_data.get('species', instance.species)
        instance.species_diagnosis_diagnosis = validated_data.get('species_diagnosis_diagnosis',
                                                                  instance.species_diagnosis_diagnosis)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)
        instance.save()

        # ensure that the post-save instance and its nested objecs is returned, not the pre-saved instance
        instance = NotificationCueCustom.objects.filter(id=instance.id).first()

        return instance

    class Meta:
        model = NotificationCueCustom
        fields = ('id', 'notification_cue_preference', 'new_notification_cue_preference',
                  'event', 'event_affected_count', 'event_affected_count_operator', 'event_location_land_ownership',
                  'event_location_administrative_level_one', 'species', 'species_diagnosis_diagnosis', 'cue_strings',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


# NOTE: these are only to be created when a user is created, and only deleted when a user is deleted
class NotificationCueStandardSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    notification_cue_preference = NotificationCuePreferenceSerializer(read_only=True)
    new_notification_cue_preference = serializers.JSONField(write_only=True, required=True)

    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        # pull out child notification cue preferences from the request and update it if necessary
        new_pref = validated_data.pop('new_notification_cue_preference', None)
        if new_pref:
            pref = NotificationCuePreference.objects.filter(id=instance.notification_cue_preference.id).first()
            if ('create_when_new' in new_pref and new_pref['create_when_new'] is not None
                    and isinstance(new_pref['create_when_new'], bool)):
                pref.create_when_new = new_pref['create_when_new']
            if ('create_when_modified' in new_pref and new_pref['create_when_modified'] is not None
                    and isinstance(new_pref['create_when_modified'], bool)):
                pref.create_when_modified = new_pref['create_when_modified']
            if ('send_email' in new_pref and new_pref['send_email'] is not None
                    and isinstance(new_pref['send_email'], bool)):
                pref.send_email = new_pref['send_email']
            pref.modified_by = user if user else pref.modified_by
            pref.save()

        # update the NotificationCueStandard object (note that there is nothing that the user should be able to update)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)
        instance.save()

        # ensure that the post-save instance and its nested objecs is returned, not the pre-saved instance
        instance = NotificationCueStandard.objects.filter(id=instance.id).first()

        return instance

    class Meta:
        model = NotificationCueStandard
        fields = ('id', 'standard_type', 'notification_cue_preference', 'new_notification_cue_preference',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class NotificationCueStandardTypeSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = NotificationCueStandardType
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


######
#
#  Users
#
######


# Password must be at least 12 characters long.
# Password cannot contain your username.
# Password cannot have been used in previous 20 passwords.
# Password cannot have been changed less than 24 hours ago.
# Password must satisfy 3 out of the following requirements:
# Contain lowercase letters (a, b, c, ..., z)
# Contain uppercase letters (A, B, C, ..., Z)
# Contain numbers (0, 1, 2, ..., 9)
# Contain symbols (~, !, @, #, etc.)
class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, allow_blank=True, required=False)
    organization_string = serializers.StringRelatedField(source='organization')
    notification_cue_standards = NotificationCueStandardSerializer(
        read_only=True, many=True, source='notificationcuestandard_creator')
    new_user_change_request = serializers.JSONField(write_only=True, required=False)
    new_notification_cue_standard_preferences = serializers.JSONField(write_only=True, required=False)
    recaptcha = ReCaptchaV2Field()

    def validate(self, data):

        if self.context['request'].method == 'POST':
            if 'role' not in data or ('role' in data and data['role'] is None):
                data['role'] = Role.objects.filter(name='Public').first()
            if 'organization' not in data or ('organization' in data and data['organization'] is None):
                data['organization'] = Organization.objects.filter(name='Public').first()
            if 'password' not in data:
                raise serializers.ValidationError("password is required")
            if 'new_user_change_request' in data and data['new_user_change_request'] is not None:
                ucr = data['new_user_change_request']
                if ('role_requested' in ucr and ucr['role_requested'] is not None
                        and str(ucr['role_requested']).isdecimal()):
                    role_ids = list(Role.objects.values_list('id', flat=True))
                    if int(ucr['role_requested']) not in role_ids:
                        raise serializers.ValidationError("Requested role does not exist.")
                if ('organization_requested' in ucr and ucr['organization_requested'] is not None
                        and str(ucr['organization_requested']).isdecimal()):
                    org_ids = list(Organization.objects.values_list('id', flat=True))
                    if int(ucr['organization_requested']) not in org_ids:
                        raise serializers.ValidationError("Requested organization does not exist.")
        if 'password' in data:
            password = data['password']
            details = []
            char_type_requirements_met = []
            symbols = '~!@#$%^&*'

            username = self.initial_data['username'] if 'username' in self.initial_data else self.instance.username

            if len(password) < 12:
                details.append("Password must be at least 12 characters long.")
            if username.lower() in password.lower():
                details.append("Password cannot contain username.")
            if any(character.islower() for character in password):
                char_type_requirements_met.append('lowercase')
            if any(character.isupper() for character in password):
                char_type_requirements_met.append('uppercase')
            if any(character.isdecimal() for character in password):
                char_type_requirements_met.append('number')
            if any(character in password for character in symbols):
                char_type_requirements_met.append('special')
            if len(char_type_requirements_met) < 3:
                message = "Password must satisfy three of the following requirements: "
                message += "Contain lowercase letters (a, b, c, ..., z); "
                message += "Contain uppercase letters (A, B, C, ..., Z); "
                message += "Contain numbers (0, 1, 2, ..., 9); "
                message += "Contain symbols (~, !, @, #, $, %, ^, &, *); "
                details.append(message)
            if details:
                raise serializers.ValidationError(details)

        return data

    # currently only public users can be created through the API
    def create(self, validated_data):
        requesting_user = get_user(self.context, self.initial_data)

        # pull out child notification cue standard preferences from the request (cannot be created here, only in model)
        validated_data.pop('new_notification_cue_standard_preferences', None)

        password = validated_data.pop('password', None)

        # remove the recaptcha response
        recaptcha = validated_data.pop('recaptcha', None)

        # pull out child service request from the request
        new_user_change_request = validated_data.pop('new_user_change_request', None)

        # non-admins (not SuperAdmin, Admin, or even PartnerAdmin) cannot create any kind of user other than public
        if (not requesting_user.is_authenticated or requesting_user.role.is_public or requesting_user.role.is_affiliate
                or requesting_user.role.is_partner or requesting_user.role.is_partnermanager):
            validated_data['role'] = Role.objects.filter(name='Public').first()
            validated_data['organization'] = Organization.objects.filter(name='Public').first()

        else:

            # Admins can create users with any org and any role except SuperAdmin
            if requesting_user.role.is_admin:
                if validated_data['role'].name == 'SuperAdmin':
                    message = "You can only assign roles with equal or lower permissions to your own."
                    raise serializers.ValidationError(jsonify_errors(message))

            # PartnerAdmins can only create users in their own org with equal or lower roles
            if requesting_user.role.is_partneradmin:
                if validated_data['role'].name in ['SuperAdmin', 'Admin']:
                    message = "You can only assign roles with equal or lower permissions to your own."
                    raise serializers.ValidationError(jsonify_errors(message))
                validated_data['organization'] = requesting_user.organization

        # only SuperAdmins and Admins can edit is_staff
        if (requesting_user.is_authenticated
                and not (requesting_user.role.is_superadmin or requesting_user.role.is_admin)):
            validated_data['is_staff'] = False

        # is_active is false for new users until email address is verified
        validated_data['is_active'] = False

        # only SuperAdmins can edit is_superuser field
        if (requesting_user.is_authenticated
                and not (requesting_user.role.is_superadmin or requesting_user.is_superuser)):
            validated_data['is_superuser'] = False

        user = User.objects.create(**validated_data)
        user.set_password(password)
        user.save()

        UserSerializer.send_email_verification_message(user)

        if new_user_change_request is not None:
            role_requested = None
            organization_requested = None
            if ('role_requested' in new_user_change_request
                    and new_user_change_request['role_requested'] is not None):
                role_requested = new_user_change_request['role_requested']
            if ('organization_requested' in new_user_change_request
                    and new_user_change_request['organization_requested'] is not None):
                organization_requested = new_user_change_request['organization_requested']

            if role_requested or organization_requested:
                role_requested = role_requested if role_requested else user.role.id
                organization_requested = organization_requested if organization_requested else user.organization.id
                comment = new_user_change_request.pop('comment', '')
                user_change_request = {'requester': user.id, 'role_requested': role_requested,
                                       'organization_requested': organization_requested, 'comment': comment,
                                       'created_by': user.id, 'modified_by': user.id}
                ucr_serializer = UserChangeRequestSerializer(data=user_change_request)
                if ucr_serializer.is_valid():
                    ucr_serializer.save()
                else:
                    NotificationCueStandard.objects.filter(created_by=user.id).delete()
                    NotificationCuePreference.objects.filter(created_by=user.id).delete()
                    user.delete()
                    raise serializers.ValidationError(jsonify_errors(ucr_serializer.errors))

        return user

    @staticmethod
    def send_email_verification_message(user):
        """Send email to user with link to verify their email address."""
        # Create email verification link
        token = email_verification_token.make_token(user)
        verification_link = (settings.APP_WHISPERS_URL +
                             "?" +
                             urlencode({'user-id': user.id, 'email-token': token}))

        # create a 'User Email Verification' notification
        msg_tmp = NotificationMessageTemplate.objects.filter(name='User Email Verification').first()
        if not msg_tmp:
            send_missing_notification_template_message_email('userserializer_send_email_verification_message',
                                                             'User Email Verification')
        else:
            source = 'system'
            # recipients: user
            recipients = [user.id]
            # email forwarding: Automatic, to user's email
            email_to = [user.email]
            subject = msg_tmp.subject_template
            body = msg_tmp.body_template.format(
                first_name=user.first_name,
                last_name=user.last_name,
                verification_link=verification_link)
            event = None
            generate_notification.delay(recipients, source, event, 'homepage', subject, body, True, email_to)

    def update(self, instance, validated_data):
        requesting_user = get_user(self.context, self.initial_data)

        # pull out child notification cue standard preferences from the request and validate if necessary
        new_prefs = validated_data.pop('new_notification_cue_standard_preferences', None)
        if new_prefs:
            if not isinstance(new_prefs, list):
                message = "new_notification_cue_standard_preferences must be a list/array."
                raise serializers.ValidationError(jsonify_errors(message))
            else:
                details = []
                for new_cue in new_prefs:
                    if 'standard_type' not in new_cue and 'id' not in new_cue:
                        message = "Either id or standard_type is a required field"
                        message += " for each new_notification_cue_standard_preference"
                        details.append(jsonify_errors(message))
                    if 'standard_type' in new_cue and new_cue['standard_type'] is not None:
                        if not str(new_cue['standard_type']).isdecimal():
                            raise serializers.ValidationError("Submitted standard_type must be a valid integer.")
                        else:
                            std_type_ids = list(NotificationCueStandardType.objects.values_list('id', flat=True))
                            if int(new_cue['standard_type']) not in std_type_ids:
                                message = "Submitted standard_type does not exist."
                                raise serializers.ValidationError(message)
                    elif 'id' in new_cue and new_cue['id'] is not None:
                        if not str(new_cue['id']).isdecimal():
                            raise serializers.ValidationError("Submitted id must be a valid integer.")
                        else:
                            cue_ids = list(NotificationCueStandard.objects.filter(
                                created_by=instance.id).values_list('id', flat=True))
                            if int(new_cue['id']) not in cue_ids:
                                message = "Submitted id does not exist or you do not have permission to update it."
                                raise serializers.ValidationError(message)
                    if 'new_notification_cue_preference' not in new_cue:
                        message = "new_notification_cue_standard_preferences is a required field"
                        message += " for each new_notification_cue_standard_preference"
                        details.append(jsonify_errors(message))
                if details:
                    raise serializers.ValidationError(details)

        # non-admins (not SuperAdmin, Admin, or even PartnerAdmin) can only edit their first and last names and password
        if not requesting_user.is_authenticated:
            raise serializers.ValidationError(jsonify_errors("You cannot edit user data."))
        elif (requesting_user.role.is_public or requesting_user.role.is_affiliate
                or requesting_user.role.is_partner or requesting_user.role.is_partnermanager):
            if instance.id == requesting_user.id:
                instance.first_name = validated_data.get('first_name', instance.first_name)
                instance.last_name = validated_data.get('last_name', instance.last_name)
            else:
                raise serializers.ValidationError(jsonify_errors("You can only edit your own user information."))

        elif (requesting_user.role.is_superadmin or requesting_user.role.is_admin
              or requesting_user.role.is_partneradmin):

            if requesting_user.role.is_admin:
                if instance.role.is_superadmin:
                    message = "You can not alter superadmin user settings."
                    raise serializers.ValidationError(jsonify_errors(message))
            if requesting_user.role.is_partneradmin:
                if instance.role.is_superadmin or instance.role.is_admin:
                    message = "You can not alter admin user settings."
                    raise serializers.ValidationError(jsonify_errors(message))
                if 'role' in validated_data and validated_data['role'].name in ['SuperAdmin', 'Admin']:
                    message = "You can only assign roles with equal or lower permissions to your own."
                    raise serializers.ValidationError(jsonify_errors(message))
                instance.role = validated_data.get('role', instance.role)
                instance.organization = requesting_user.organization
            else:
                instance.is_superuser = validated_data.get('is_superuser', instance.is_superuser)
                instance.is_staff = validated_data.get('is_staff', instance.is_staff)
                instance.is_active = validated_data.get('is_active', instance.is_active)
                instance.role = validated_data.get('role', instance.role)
                instance.organization = validated_data.get('organization', instance.organization)
                instance.active_key = validated_data.get('active_key', instance.active_key)
                instance.user_status = validated_data.get('user_status', instance.user_status)

            instance.username = validated_data.get('username', instance.username)
            instance.email = validated_data.get('email', instance.email)
            instance.first_name = validated_data.get('first_name', instance.first_name)
            instance.last_name = validated_data.get('last_name', instance.last_name)

        instance.modified_by = requesting_user

        new_password = validated_data.get('password', None)
        if new_password is not None:
            instance.set_password(new_password)
        instance.save()

        # update child notification cue standard preferences if necessary
        if new_prefs:
            for new_cue in new_prefs:
                new_pref = new_cue['new_notification_cue_preference']
                # use the standard_type to find the requested standard cue, since each user can only have one per type
                if 'standard_type' in new_cue:
                    std_cue_id = NotificationCueStandard.objects.filter(
                        created_by=instance.id, standard_type=new_cue['standard_type']).values('id').first()['id']
                else:
                    # otherwise fall back to the standard cue ID (standard_type or ID must have been submitted)
                    std_cue_id = new_cue['id']
                pref = NotificationCuePreference.objects.filter(notificationcuestandard__id=std_cue_id).first()
                if ('create_when_new' in new_pref and new_pref['create_when_new'] is not None
                        and isinstance(new_pref['create_when_new'], bool)):
                    pref.create_when_new = new_pref['create_when_new']
                if ('create_when_modified' in new_pref and new_pref['create_when_modified'] is not None
                        and isinstance(new_pref['create_when_modified'], bool)):
                    pref.create_when_modified = new_pref['create_when_modified']
                if ('send_email' in new_pref and new_pref['send_email'] is not None
                        and isinstance(new_pref['send_email'], bool)):
                    pref.send_email = new_pref['send_email']
                pref.modified_by = requesting_user if requesting_user else pref.modified_by
                pref.save()

        return instance

    def __init__(self, *args, **kwargs):
        user = None
        action = 'list'
        view_name = ''
        if 'context' in kwargs:
            if 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
                user = kwargs['context']['request'].user
            if 'view' in kwargs['context'] and hasattr(kwargs['context']['view'], 'action'):
                action = kwargs['context']['view'].action
            if 'view_name' in kwargs['context']:
                view_name = kwargs['context']['view_name']
        fields = ('id', 'username', 'first_name', 'last_name', 'email', 'organization', 'organization_string',)
        private_fields = ('id', 'username', 'password', 'first_name', 'last_name', 'email', 'is_superuser', 'is_staff',
                          'is_active', 'role', 'organization', 'organization_string', 'circles', 'last_login',
                          'active_key', 'user_status', 'notification_cue_standards',
                          'new_notification_cue_standard_preferences', 'new_user_change_request', )

        if action == 'create' or view_name == 'auth' or action == 'reset_password':
            fields = private_fields
        elif user and user.is_authenticated:
            if user.role.is_superadmin or user.role.is_admin:
                fields = private_fields
            elif action in PK_REQUESTS and hasattr(kwargs['context']['request'], 'parser_context'):
                pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdecimal():
                    obj = User.objects.filter(id=pk).first()
                    if obj and (user.password == obj.password or
                                ((obj.organization.id == user.organization.id
                                  or obj.organization.id in user.organization.parent_organizations) and
                                 (user.role.is_partneradmin or user.role.is_partnermanager))):
                        fields = private_fields

        super(UserSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = User
        fields = '__all__'


class RoleSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = Role
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class UserChangeRequestSerializer(serializers.ModelSerializer):
    requester = serializers.PrimaryKeyRelatedField(read_only=True)

    def create(self, validated_data):
        user = get_user(self.context, self.initial_data)

        if not user or not user.is_authenticated:
            raise serializers.ValidationError(
                jsonify_errors("You must be an authenticated user to request a change."))
        else:
            validated_data['requester'] = user

        # pull out child comments list from the request
        comment = validated_data.pop('comment', None)

        # Only allow NWHC admins to alter the request response
        if 'request_response' in validated_data and validated_data['request_response'] is not None:
            if not (user.role.is_superadmin or user.role.is_admin):
                raise serializers.ValidationError(
                    jsonify_errors("You do not have permission to alter the request response."))
            else:
                validated_data['response_by'] = user

        # if a request_response is not submitted, assign the default
        if 'request_response' not in validated_data or validated_data['request_response'] is None:
            validated_data['request_response'] = UserChangeRequestResponse.objects.filter(name='Pending').first()

        ucr = UserChangeRequest.objects.create(**validated_data)
        # store comment as a Comment object associated with UserChangeRequest
        cmt_type = CommentType.objects.filter(name='Other').first()
        Comment.objects.create(content_object=ucr, comment=comment,
                               comment_type=cmt_type, created_by=user, modified_by=user)
        return ucr

    @staticmethod
    def send_user_change_request_email(ucr):
        # Email is sent only after user verifies their email address

        # Get user's comment from the user change request
        content_type = ContentType.objects.get_for_model(UserChangeRequest)
        comment_object = Comment.objects.filter(object_id=ucr.id, content_type=content_type).first()
        comment = comment_object.comment if comment_object else None
        # create a 'User Change Request' notification
        msg_tmp = NotificationMessageTemplate.objects.filter(name='User Change Request').first()
        if not msg_tmp:
            send_missing_notification_template_message_email('userchangerequestserializer_create',
                                                             'User Change Request')
        else:
            try:
                subject = msg_tmp.subject_template.format(new_organization=ucr.organization_requested.name)
            except KeyError as e:
                send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                subject = ""
            try:
                body = msg_tmp.body_template.format(first_name=ucr.requester.first_name,
                                                    last_name=ucr.requester.last_name,username=ucr.requester.username,
                                                    current_role=ucr.requester.role.name,
                                                    new_role=ucr.role_requested.name,
                                                    current_organization=ucr.requester.organization.name,
                                                    new_organization=ucr.organization_requested.name, comment=comment)
            except KeyError as e:
                send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                body = ""
            event = None
            # source: User that requests an account upgrade or requesting an account above public
            source = ucr.created_by.username
            # recipients: WHISPers admin team, Admins of organization requested
            # check if the requested org has itself as its parent org,
            #  and if so alert the admins (this situation should not be allowed)
            org_requested_id = ucr.organization_requested.id
            if (ucr.organization_requested.parent_organization
                    and ucr.organization_requested.parent_organization.id == org_requested_id):
                org_list = [org_requested_id, ]
                message = "Organization " + ucr.organization_requested.name
                message += " (ID: " + ucr.organization_requested.id + ")"
                message += " has itself as its parent organization, which can cause infinite recursion when the"
                message += " parent_organizations or child_organizations properties of this organization are accessed."
                message += " Please correct this situation before a RecursionError occurs. If this organization has no"
                message += " parent organization, set the parent organization value to null."
                construct_email("Infinite Recursive Organization Found", message)
            else:
                org_list = ucr.organization_requested.parent_organizations
            recipients = list(User.objects.exclude(is_active=False).filter(
                Q(role__in=[1, 2]) | Q(role=3, organization=org_requested_id) | Q(role=3, organization__in=org_list)
            ).values_list('id', flat=True))
            # email forwarding: Automatic, to whispers@usgs.gov, org admin, parent org admin
            email_to = list(User.objects.exclude(is_active=False).filter(
                Q(id=1) | Q(role=3, organization=ucr.organization_requested.id) | Q(role=3, organization__in=org_list)
            ).values_list('email', flat=True))
            generate_notification.delay(recipients, source, event, 'userdashboard', subject, body, True, email_to)

        # also create a 'User Change Request Response Pending' notification
        msg_tmp = NotificationMessageTemplate.objects.filter(name='User Change Request Response Pending').first()
        if not msg_tmp:
            send_missing_notification_template_message_email('userchangerequestserializer_create',
                                                             'User Change Request Response Pending')
        else:
            subject = msg_tmp.subject_template
            body = msg_tmp.body_template
            event = None
            # source: User that requests the natural resource management professional account
            source = ucr.created_by.username
            # recipients: user
            recipients = [ucr.created_by.id, ]
            # email forwarding: Automatic to the user's email
            email_to = [ucr.created_by.email, ]
            generate_notification.delay(recipients, source, event, 'userdashboard', subject, body, True, email_to)

        return ucr

    def update(self, instance, validated_data):
        request_response_updated = False

        # remove child comment from the request
        if 'comment' in validated_data:
            validated_data.pop('comment')

        # Only allow NWHC admins or requester's org admin to alter the request response
        if 'request_response' in validated_data and validated_data['request_response'] is not None:
            user = get_user(self.context, self.initial_data)

            if not user or not user.is_authenticated:
                raise serializers.ValidationError(
                    jsonify_errors("You must be an authenticated user to update a change request."))
            else:
                validated_data['requester'] = user

            if not (user.role.is_superadmin or user.role.is_admin or
                    (user.role.is_partneradmin and user.organization.id == instance.created_by.organization.id)):
                raise serializers.ValidationError(
                    jsonify_errors("You do not have permission to alter the request response."))
            else:
                instance.request_response = validated_data.get('request_response', instance.request_response)
                instance.response_by = user
                request_response_updated = True

                # capture the user change request response as a comment
                cmt = "User Change Request Response: " + instance.request_response.name
                cmt_type = CommentType.objects.filter(name='Other').first()
                Comment.objects.create(content_object=instance, comment=cmt,
                                       comment_type=cmt_type, created_by=user, modified_by=user)

        instance.role_requested = validated_data.get('role_requested', instance.role_requested)
        instance.organization_requested = validated_data.get('organization_requested', instance.organization_requested)
        instance.save()

        # if the response is updated to 'Yes' or 'No',
        # update the User and create a 'User Change Request Response' notification
        # TODO: what about 'Maybe'?
        if request_response_updated:
            if instance.request_response.name == 'Yes':
                requester = User.objects.filter(id=instance.requester.id).first()
                requester.role = instance.role_requested
                requester.organization = instance.organization_requested
                requester.save()
                msg_tmp = NotificationMessageTemplate.objects.filter(name='User Change Request Response Yes').first()
                if not msg_tmp:
                    send_missing_notification_template_message_email('userchangerequestserializer_update',
                                                                     'User Change Request Response Yes')
                else:
                    subject = msg_tmp.subject_template
                    try:
                        body = msg_tmp.body_template.format(role=instance.role_requested.name,
                                                            organization=instance.organization_requested.name)
                    except KeyError as e:
                        send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                        body = ""
                    event = None
                    # source: WHISPers Admin or Org Admin who assigns a WHISPers role.
                    source = instance.modified_by.username
                    # recipients: user, WHISPers admin team
                    recipients = list(User.objects.exclude(is_active=False).filter(
                        role__in=[1, 2]).values_list('id', flat=True)) + [instance.requester.id, ]
                    # email forwarding: Automatic, to user's email and to whispers@usgs.gov
                    email_to = [User.objects.filter(id=1).values('email').first()['email'], instance.requester.email, ]
                    generate_notification.delay(recipients, source, event, 'homepage', subject, body, True, email_to)
            elif instance.request_response.name == 'No':
                msg_tmp = NotificationMessageTemplate.objects.filter(name='User Change Request Response No').first()
                if not msg_tmp:
                    send_missing_notification_template_message_email('userchangerequestserializer_update',
                                                                     'User Change Request Response No')
                else:
                    subject = msg_tmp.subject_template
                    body = msg_tmp.body_template
                    event = None
                    # source: WHISPer Admin or Org Admin who assigns a WHISPers role.
                    source = instance.modified_by.username
                    # recipients: user, WHISPers admin team
                    recipients = list(User.objects.exclude(is_active=False).filter(
                        role__in=[1, 2]).values_list('id', flat=True)) + [instance.requester.id, ]
                    # email forwarding: Automatic, to user's email and to whispers@usgs.gov
                    email_to = [User.objects.filter(id=1).values('email').first()['email'], instance.requester.email, ]
                    generate_notification.delay(recipients, source, event, 'homepage', subject, body, True, email_to)

        return instance

    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    response_by = serializers.StringRelatedField()
    comment = serializers.CharField(write_only=True, required=False, allow_blank=True, default='')
    comments = CommentSerializer(many=True, read_only=True)

    class Meta:
        model = UserChangeRequest
        fields = ('id', 'requester', 'role_requested', 'organization_requested', 'request_response', 'response_by',
                  'comment', 'comments', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class UserChangeRequestResponseSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = UserChangeRequestResponse
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class CircleSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    new_users = serializers.ListField(write_only=True)
    users = UserSerializer(many=True, read_only=True)

    # on create, also create child objects (circle-user M:M relates)
    def create(self, validated_data):
        # pull out user ID list from the request
        new_users = validated_data.pop('new_users', None)

        # create the Circle object
        circle = Circle.objects.create(**validated_data)

        # create a CicleUser object for each User ID submitted
        if new_users:
            user = get_user(self.context, self.initial_data)

            for new_user_id in new_users:
                new_user = User.objects.get(id=new_user_id)
                CircleUser.objects.create(user=new_user, circle=circle, created_by=user, modified_by=user)

        return circle

    # on update, also update child objects (circle-user M:M relates), including additions and deletions
    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        # pull out user ID list from the request
        if 'new_users' in validated_data:
            new_user_ids = validated_data.get('new_users')
        else:
            new_user_ids = []

        # update the Circle object
        instance.name = validated_data.get('name', instance.name)
        instance.description = validated_data.get('description', instance.description)
        instance.modified_by = user
        instance.save()

        request_method = self.context['request'].method

        # update circle users if new_users submitted
        if request_method == 'PUT' or (new_user_ids and request_method == 'PATCH'):
            # get the old (current) user list for this circle
            old_users = User.objects.filter(circles=instance.id)
            # get the new (submitted) user list for this circle
            new_users = User.objects.filter(id__in=new_user_ids)

            # identify and delete relates where user IDs are present in old list but not new list
            delete_users = list(set(old_users) - set(new_users))
            for user_id in delete_users:
                delete_user = CircleUser.objects.filter(user=user_id, circle=instance)
                delete_user.delete()

            # identify and add relates where user IDs are present in new list but not old list
            add_users = list(set(new_users) - set(old_users))
            for user_id in add_users:
                CircleUser.objects.create(user=user_id, circle=instance, created_by=user, modified_by=user)

        return instance

    class Meta:
        model = Circle
        fields = ('id', 'name', 'description', 'users', 'new_users',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class OrganizationSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):
        if self.instance:
            if 'parent_organization' in data and data['parent_organization'] is not None:
                if 'id' in data and data['id'] is not None and data['parent_organization'].id == data['id']:
                    raise serializers.ValidationError("parent_organization cannot be the ID of the object itself.")
                elif data['parent_organization'].id == self.instance.id:
                    raise serializers.ValidationError("parent_organization cannot be the ID of the object itself.")
        return data

    def __init__(self, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user

        if not user or not user.is_authenticated or user.role.is_public:
            fields = ('id', 'name', 'address_one', 'address_two', 'city', 'postal_code', 'administrative_level_one',
                      'country', 'phone', 'parent_organization', 'laboratory',)
        elif user.role.is_superadmin or user.role.is_admin:
            fields = ('id', 'name', 'private_name', 'address_one', 'address_two', 'city', 'postal_code',
                      'administrative_level_one', 'country', 'phone', 'parent_organization', 'do_not_publish',
                      'laboratory', 'created_date', 'created_by', 'created_by_string',
                      'modified_date', 'modified_by', 'modified_by_string',)
        else:
            fields = ('id', 'name', 'private_name', 'address_one', 'address_two', 'city', 'postal_code',
                      'administrative_level_one', 'country', 'phone', 'parent_organization', 'laboratory',)

        super(OrganizationSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = Organization
        fields = '__all__'


class OrganizationSlimSerializer(serializers.ModelSerializer):

    def __init__(self, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user

        if not user or not user.is_authenticated or user.role.is_public:
            fields = ('id', 'name', 'laboratory',)
        else:
            fields = ('id', 'name', 'private_name', 'laboratory',)

        super(OrganizationSlimSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = Organization
        fields = '__all__'


class ContactSerializer(serializers.ModelSerializer):
    def get_owner_organization_string(self, obj):
        return Organization.objects.filter(id=obj.owner_organization).first().name

    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    organization_string = serializers.StringRelatedField(source='organization')
    owner_organization_string = serializers.SerializerMethodField()

    def get_permission_source(self, obj):
        return determine_permission_source(self.context['request'].user, obj)

    class Meta:
        model = Contact
        fields = ('id', 'first_name', 'last_name', 'email', 'phone', 'affiliation', 'title', 'position', 'organization',
                  'organization_string', 'owner_organization', 'owner_organization_string', 'active',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string', 'permissions', 'permission_source',)


class ContactSlimSerializer(serializers.ModelSerializer):
    organization_string = serializers.StringRelatedField(source='organization')

    class Meta:
        model = Contact
        fields = ('id', 'first_name', 'last_name', 'organization_string', )


class ContactTypeSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = ContactType
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class SearchSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()

    def get_permission_source(self, obj):
        return determine_permission_source(self.context['request'].user, obj)

    def create(self, validated_data):
        user = get_user(self.context, self.initial_data)

        if 'data' not in validated_data:
            validated_data['data'] = ''

        validated_data['created_by'] = user
        validated_data['modified_by'] = user
        search = Search.objects.create(**validated_data)
        return search

    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        instance.name = validated_data.get('name', instance.name)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modifed_by)
        instance.save()
        return instance

    def __init__(self, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user

        if not user or not user.is_authenticated:
            fields = ('data',)
        elif user.role.is_public:
            fields = ('name', 'data',)
        else:
            fields = ('id', 'name', 'data', 'created_date', 'created_by', 'created_by_string',
                      'modified_date', 'modified_by', 'modified_by_string', 'permissions', 'permission_source',)

        super(SearchSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = Search
        fields = '__all__'


######
#
#  Special
#
######


class FlatEventSummaryPublicSerializer(serializers.ModelSerializer):
    # a flat (not nested) version of the essential fields of the EventSummaryPublicSerializer, to populate CSV files
    # requested from the EventSummaries Search
    def get_countries(self, obj):
        unique_country_ids = []
        unique_countries = ''
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                country_id = eventlocation.get('country_id')
                if country_id is not None and country_id not in unique_country_ids:
                    unique_country_ids.append(country_id)
                    country = Country.objects.filter(id=country_id).first()
                    unique_countries += '; ' + country.name if unique_countries else country.name
        return unique_countries

    def get_states(self, obj):
        unique_l1_ids = []
        unique_l1s = ''
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                al1_id = eventlocation.get('administrative_level_one_id')
                if al1_id is not None and al1_id not in unique_l1_ids:
                    unique_l1_ids.append(al1_id)
                    al1 = AdministrativeLevelOne.objects.filter(id=al1_id).first()
                    unique_l1s += '; ' + al1.name if unique_l1s else al1.name
        return unique_l1s

    def get_counties(self, obj):
        unique_l2_ids = []
        unique_l2s = ''
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                al2_id = eventlocation.get('administrative_level_two_id')
                if al2_id is not None and al2_id not in unique_l2_ids:
                    unique_l2_ids.append(al2_id)
                    al2 = AdministrativeLevelTwo.objects.filter(id=al2_id).first()
                    if unique_l2s:
                        unique_l2s += '; ' + al2.name + ', ' + al2.administrative_level_one.abbreviation
                    else:
                        unique_l2s += al2.name + ', ' + al2.administrative_level_one.abbreviation
        return unique_l2s

    def get_species(self, obj):
        unique_species_ids = []
        unique_species = ''
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                locationspecies = LocationSpecies.objects.filter(event_location=eventlocation['id'])
                if locationspecies is not None:
                    for alocationspecies in locationspecies:
                        species = Species.objects.filter(id=alocationspecies.species_id).first()
                        if species is not None:
                            if species.id not in unique_species_ids:
                                unique_species_ids.append(species.id)
                                unique_species += '; ' + species.name if unique_species else species.name
        return unique_species

    def get_eventdiagnoses(self, obj):
        event_diagnoses = EventDiagnosis.objects.filter(event=obj.id)
        unique_eventdiagnoses_ids = []
        unique_eventdiagnoses = ''
        for event_diagnosis in event_diagnoses:
            diag_id = event_diagnosis.diagnosis.id if event_diagnosis.diagnosis else None
            if diag_id:
                diag = Diagnosis.objects.get(pk=diag_id).name
                if event_diagnosis.suspect:
                    diag = diag + " suspect"
                if diag_id not in unique_eventdiagnoses_ids:
                    unique_eventdiagnoses_ids.append(diag_id)
                    unique_eventdiagnoses += '; ' + diag if unique_eventdiagnoses else diag
        return unique_eventdiagnoses

    type = serializers.StringRelatedField(source='event_type')
    affected = serializers.IntegerField(source='affected_count', read_only=True)
    states = serializers.SerializerMethodField()
    countries = serializers.SerializerMethodField()
    counties = serializers.SerializerMethodField()
    species = serializers.SerializerMethodField()
    eventdiagnoses = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ('id', 'type', 'affected', 'start_date', 'end_date', 'countries', 'states', 'counties',  'species',
                  'eventdiagnoses',)


class FlatEventSummarySerializer(serializers.ModelSerializer):
    # a flat (not nested) version of the essential fields of the EventSummaryPublicSerializer, to populate CSV files
    # requested from the EventSummaries Search
    def get_countries(self, obj):
        unique_country_ids = []
        unique_countries = ''
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                country_id = eventlocation.get('country_id')
                if country_id is not None and country_id not in unique_country_ids:
                    unique_country_ids.append(country_id)
                    country = Country.objects.filter(id=country_id).first()
                    unique_countries += '; ' + country.name if unique_countries else country.name
        return unique_countries

    def get_states(self, obj):
        unique_l1_ids = []
        unique_l1s = ''
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                al1_id = eventlocation.get('administrative_level_one_id')
                if al1_id is not None and al1_id not in unique_l1_ids:
                    unique_l1_ids.append(al1_id)
                    al1 = AdministrativeLevelOne.objects.filter(id=al1_id).first()
                    unique_l1s += '; ' + al1.name if unique_l1s else al1.name
        return unique_l1s

    def get_counties(self, obj):
        unique_l2_ids = []
        unique_l2s = ''
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                al2_id = eventlocation.get('administrative_level_two_id')
                if al2_id is not None and al2_id not in unique_l2_ids:
                    unique_l2_ids.append(al2_id)
                    al2 = AdministrativeLevelTwo.objects.filter(id=al2_id).first()
                    if unique_l2s:
                        unique_l2s += '; ' + al2.name + ', ' + al2.administrative_level_one.abbreviation
                    else:
                        unique_l2s += al2.name + ', ' + al2.administrative_level_one.abbreviation
        return unique_l2s

    def get_species(self, obj):
        unique_species_ids = []
        unique_species = ''
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                locationspecies = LocationSpecies.objects.filter(event_location=eventlocation['id'])
                if locationspecies is not None:
                    for alocationspecies in locationspecies:
                        species = Species.objects.filter(id=alocationspecies.species_id).first()
                        if species is not None:
                            if species.id not in unique_species_ids:
                                unique_species_ids.append(species.id)
                                unique_species += '; ' + species.name if unique_species else species.name
        return unique_species

    def get_eventdiagnoses(self, obj):
        event_diagnoses = EventDiagnosis.objects.filter(event=obj.id)
        unique_eventdiagnoses_ids = []
        unique_eventdiagnoses = ''
        for event_diagnosis in event_diagnoses:
            diag_id = event_diagnosis.diagnosis.id if event_diagnosis.diagnosis else None
            if diag_id:
                diag = Diagnosis.objects.get(pk=diag_id).name
                if event_diagnosis.suspect:
                    diag = diag + " suspect"
                if diag_id not in unique_eventdiagnoses_ids:
                    unique_eventdiagnoses_ids.append(diag_id)
                    unique_eventdiagnoses += '; ' + diag if unique_eventdiagnoses else diag
        return unique_eventdiagnoses

    type = serializers.StringRelatedField(source='event_type')
    affected = serializers.IntegerField(source='affected_count', read_only=True)
    states = serializers.SerializerMethodField()
    countries = serializers.SerializerMethodField()
    counties = serializers.SerializerMethodField()
    species = serializers.SerializerMethodField()
    eventdiagnoses = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ('id', 'type', 'public', 'affected', 'start_date', 'end_date', 'countries', 'states', 'counties',
                  'species', 'eventdiagnoses',)


class EventSummarySerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    eventdiagnoses = serializers.SerializerMethodField()
    administrativelevelones = serializers.SerializerMethodField()
    administrativeleveltwos = serializers.SerializerMethodField()
    flyways = serializers.SerializerMethodField()
    species = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    staff_string = serializers.StringRelatedField(source='staff')
    event_status_string = serializers.StringRelatedField(source='event_status')
    legal_status_string = serializers.StringRelatedField(source='legal_status')
    organizations = OrganizationSerializer(many=True)
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()

    def get_eventdiagnoses(self, obj, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user

        event_diagnoses = EventDiagnosis.objects.filter(event=obj.id)
        eventdiagnoses = []
        for event_diagnosis in event_diagnoses:
            if event_diagnosis.diagnosis:
                diag_id = event_diagnosis.diagnosis.id
                diag_name = event_diagnosis.diagnosis.name
                if event_diagnosis.suspect:
                    diag_name = diag_name + " suspect"
                diag_type = event_diagnosis.diagnosis.diagnosis_type
                diag_type_id = event_diagnosis.diagnosis.diagnosis_type.id if diag_type else None
                diag_type_name = event_diagnosis.diagnosis.diagnosis_type.name if diag_type else ''
                created_by = event_diagnosis.created_by.id if event_diagnosis.created_by else None
                created_by_string = event_diagnosis.created_by.username if event_diagnosis.created_by else ''
                modified_by = event_diagnosis.modified_by.id if event_diagnosis.modified_by else None
                modified_by_string = event_diagnosis.modified_by.username if event_diagnosis.modified_by else ''
                if not user or not user.is_authenticated or user.role.is_public:
                    altered_event_diagnosis = {"id": event_diagnosis.id, "event": event_diagnosis.event.id,
                                              "diagnosis": diag_id, "diagnosis_string": diag_name,
                                              "diagnosis_type": diag_type_id, "diagnosis_type_string": diag_type_name,
                                              "suspect": event_diagnosis.suspect, "major": event_diagnosis.major,
                                              "priority": event_diagnosis.priority}
                else:
                    altered_event_diagnosis = {"id": event_diagnosis.id, "event": event_diagnosis.event.id,
                                           "diagnosis": diag_id, "diagnosis_string": diag_name,
                                           "diagnosis_type": diag_type_id, "diagnosis_type_string": diag_type_name,
                                           "suspect": event_diagnosis.suspect, "major": event_diagnosis.major,
                                           "priority": event_diagnosis.priority,
                                           "created_by": created_by, "created_by_string": created_by_string,
                                           "modified_date": event_diagnosis.modified_date, "modified_by": modified_by,
                                           "modified_by_string": modified_by_string}
                eventdiagnoses.append(altered_event_diagnosis)
        return eventdiagnoses

    def get_administrativelevelones(self, obj):
        unique_l1_ids = []
        unique_l1s = []
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                al1_id = eventlocation.get('administrative_level_one_id')
                if al1_id is not None and al1_id not in unique_l1_ids:
                    unique_l1_ids.append(al1_id)
                    al1 = AdministrativeLevelOne.objects.filter(id=al1_id).first()
                    unique_l1s.append(model_to_dict(al1))
        return unique_l1s

    def get_administrativeleveltwos(self, obj):
        unique_l2_ids = []
        unique_l2s = []
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                al2_id = eventlocation.get('administrative_level_two_id')
                if al2_id is not None and al2_id not in unique_l2_ids:
                    unique_l2_ids.append(al2_id)
                    al2_model = AdministrativeLevelTwo.objects.filter(id=al2_id).first()
                    al2_dict = model_to_dict(al2_model)
                    al2_dict.update({'administrative_level_one_string': al2_model.administrative_level_one.name})
                    al2_dict.update({'country': al2_model.administrative_level_one.country.id})
                    al2_dict.update({'country_string': al2_model.administrative_level_one.country.name})
                    unique_l2s.append(al2_dict)
        return unique_l2s

    def get_species(self, obj):
        unique_species_ids = []
        unique_species = []
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                locationspecies = LocationSpecies.objects.filter(event_location=eventlocation['id'])
                if locationspecies is not None:
                    for alocationspecies in locationspecies:
                        species = Species.objects.filter(id=alocationspecies.species_id).first()
                        if species is not None:
                            if species.id not in unique_species_ids:
                                unique_species_ids.append(species.id)
                                unique_species.append(model_to_dict(species))
        return unique_species

    def get_flyways(self, obj):
        unique_flyway_ids = []
        unique_flyways = []
        eventlocations = obj.eventlocations.values()
        if eventlocations is not None:
            for eventlocation in eventlocations:
                flyway_ids = list(EventLocationFlyway.objects.filter(
                    event_location=eventlocation['id']).values_list('flyway_id', flat=True))
                if flyway_ids is not None:
                    for flyway_id in flyway_ids:
                        if flyway_id is not None and flyway_id not in unique_flyway_ids:
                            unique_flyway_ids.append(flyway_id)
                            flyway = Flyway.objects.filter(id=flyway_id).first()
                            unique_flyways.append(model_to_dict(flyway))
        return unique_flyways

    def get_permission_source(self, obj):
        return determine_permission_source(self.context['request'].user, obj)

    def __init__(self, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user

        fields = ('id', 'affected_count', 'start_date', 'end_date', 'complete', 'event_type', 'event_type_string',
                  'event_status', 'event_status_string', 'eventdiagnoses', 'administrativelevelones',
                  'administrativeleveltwos', 'flyways', 'species', 'organizations', 'permissions',
                  'permission_source',)
        private_fields = ('id', 'event_reference', 'affected_count', 'start_date', 'end_date', 'complete', 'event_type',
                          'event_type_string', 'event_status', 'event_status_string', 'public', 'eventdiagnoses',
                          'administrativelevelones', 'administrativeleveltwos', 'flyways', 'species', 'created_date',
                          'created_by', 'created_by_string', 'modified_date', 'modified_by', 'modified_by_string',
                          'organizations', 'permissions', 'permission_source',)
        admin_fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date',
                        'end_date', 'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string',
                        'legal_status', 'legal_status_string', 'legal_number', 'quality_check', 'public', 'eventgroups',
                        'organizations', 'contacts', 'eventdiagnoses', 'administrativelevelones',
                        'administrativeleveltwos', 'flyways', 'species', 'created_date', 'created_by',
                        'created_by_string', 'modified_date', 'modified_by', 'modified_by_string', 'permissions',
                        'permission_source',)

        if user and user.is_authenticated:
            if user.role.is_superadmin or user.role.is_admin:
                fields = admin_fields
            # this is too complicated and leads to inconsistent field lists in the response,
            #  because a user could have different permissions for different events
            # elif hasattr(kwargs['context']['request'], 'parser_context'):
            #     pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
            #     if pk is not None and pk.isdecimal():
            #         obj = Event.objects.filter(id=pk).first()
            #         if obj and (user.id == obj.created_by.id or user.organization.id == obj.created_by.organization.id
            #                     or user.organization.id in obj.created_by.parent_organizations
            #                     or user.id in list(User.objects.filter(
            #                     Q(writeevents__in=[obj.id]) | Q(readevents__in=[obj.id])
            #                 ).values_list('id', flat=True))):
            #             fields = private_fields
            elif (user.role.is_partneradmin or user.role.is_partnermanager
                  or user.role.is_partner or user.role.is_affiliate):
                fields = private_fields

        super(EventSummarySerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = Event
        fields = '__all__'


class SpeciesDiagnosisDetailSerializer(serializers.ModelSerializer):
    organizations_string = serializers.StringRelatedField(many=True, source='organizations')
    diagnosis_string = serializers.CharField(read_only=True)
    basis_string = serializers.StringRelatedField(source='basis')
    cause_string = serializers.StringRelatedField(source='cause')

    def __init__(self, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user

        fields = ('diagnosis', 'diagnosis_string', 'suspect', 'tested_count', 'diagnosis_count', 'positive_count',
                  'suspect_count', 'pooled', 'organizations', 'organizations_string')
        private_fields = ('id', 'location_species', 'diagnosis', 'diagnosis_string', 'cause', 'cause_string', 'basis',
                          'basis_string', 'suspect', 'priority', 'tested_count', 'diagnosis_count', 'positive_count',
                          'suspect_count', 'pooled', 'organizations', 'organizations_string',)

        if user and user.is_authenticated:
            if user.role.is_superadmin or user.role.is_admin:
                fields = private_fields
            elif hasattr(kwargs['context']['request'], 'parser_context'):
                # pk is for the parent event
                pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdecimal():
                    obj = Event.objects.filter(id=pk).first()
                    if obj and (user.id == obj.created_by.id or user.organization.id == obj.created_by.organization.id
                                or user.organization.id in obj.created_by.parent_organizations
                                or user.id in list(User.objects.filter(
                                Q(writeevents__in=[obj.id]) | Q(readevents__in=[obj.id])
                            ).values_list('id', flat=True))):
                        fields = private_fields

        super(SpeciesDiagnosisDetailSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    class Meta:
        model = SpeciesDiagnosis
        fields = '__all__'


class LocationSpeciesDetailSerializer(serializers.ModelSerializer):
    species_string = serializers.StringRelatedField(source='species')
    # speciesdiagnoses = SpeciesDiagnosisDetailSerializer(many=True)

    def __init__(self, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user

        fields = ('species', 'species_string', 'population_count', 'sick_count', 'dead_count', 'sick_count_estimated',
                  'dead_count_estimated', 'captive', 'age_bias', 'sex_bias', 'speciesdiagnoses',)
        private_fields = ('id', 'event_location', 'species', 'species_string', 'population_count', 'sick_count',
                          'dead_count', 'sick_count_estimated', 'dead_count_estimated', 'priority', 'captive',
                          'age_bias', 'sex_bias', 'speciesdiagnoses',)

        if user and user.is_authenticated:
            if user.role.is_superadmin or user.role.is_admin:
                fields = private_fields
            elif hasattr(kwargs['context']['request'], 'parser_context'):
                # pk is for the parent event
                pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdecimal():
                    obj = Event.objects.filter(id=pk).first()
                    if obj and (user.id == obj.created_by.id or user.organization.id == obj.created_by.organization.id
                                or user.organization.id in obj.created_by.parent_organizations
                                or user.id in list(User.objects.filter(
                                Q(writeevents__in=[obj.id]) | Q(readevents__in=[obj.id])
                            ).values_list('id', flat=True))):
                        fields = private_fields

        super(LocationSpeciesDetailSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

        self.fields['speciesdiagnoses'] = SpeciesDiagnosisDetailSerializer(many=True, context=self.context)

    class Meta:
        model = LocationSpecies
        fields = '__all__'


class EventLocationContactDetailSerializer(serializers.ModelSerializer):
    def get_owner_organization_string(self, obj):
        return Organization.objects.filter(id=obj.contact.owner_organization).first().name

    contact_type_string = serializers.StringRelatedField(source='contact_type')
    first_name = serializers.StringRelatedField(source='contact.first_name')
    last_name = serializers.StringRelatedField(source='contact.last_name')
    email = serializers.StringRelatedField(source='contact.email')
    phone = serializers.StringRelatedField(source='contact.phone')
    affiliation = serializers.StringRelatedField(source='contact.affiliation')
    title = serializers.StringRelatedField(source='contact.title')
    position = serializers.StringRelatedField(source='contact.position')
    organization = serializers.PrimaryKeyRelatedField(source='contact.organization', read_only=True)
    organization_string = serializers.StringRelatedField(source='contact.organization')
    owner_organization = serializers.PrimaryKeyRelatedField(source='contact.owner_organization', read_only=True)
    owner_organization_string = serializers.SerializerMethodField()

    class Meta:
        model = EventLocationContact
        fields = ('id', 'contact', 'contact_type', 'contact_type_string', 'first_name', 'last_name',
                  'email', 'phone', 'affiliation', 'title', 'position', 'organization', 'organization_string',
                  'owner_organization', 'owner_organization_string',)


class EventLocationDetailSerializer(serializers.ModelSerializer):
    administrative_level_two_string = serializers.StringRelatedField(source='administrative_level_two')
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')
    administrative_level_two_points = serializers.CharField(source='administrative_level_two.points', default='')
    country_string = serializers.StringRelatedField(source='country')
    # locationspecies = LocationSpeciesDetailSerializer(many=True)
    # comments = CommentSerializer(many=True)
    # eventlocationcontacts = EventLocationContactDetailSerializer(source='eventlocationcontact_set', many=True)
    flyways = serializers.SerializerMethodField()

    def get_flyways(self, obj):
        flyway_ids = [flyway['id'] for flyway in obj.flyways.values()]
        return list(Flyway.objects.filter(id__in=flyway_ids).values('id', 'name'))

    def __init__(self, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user

        fields = ('start_date', 'end_date', 'country', 'country_string', 'administrative_level_one',
                  'administrative_level_one_string', 'administrative_level_two', 'administrative_level_two_string',
                  'administrative_level_two_points', 'county_multiple', 'county_unknown', 'flyways', 'locationspecies')
        private_fields = ('id', 'name', 'event', 'start_date', 'end_date', 'country', 'country_string',
                          'administrative_level_one', 'administrative_level_one_string', 'administrative_level_two',
                          'administrative_level_two_string', 'administrative_level_two_points', 'county_multiple',
                          'county_unknown', 'latitude', 'longitude', 'priority', 'land_ownership', 'gnis_name',
                          'gnis_id', 'flyways', 'eventlocationcontacts', 'locationspecies', 'comments',)
        use_private_fields = False

        if user and user.is_authenticated:
            if user.role.is_superadmin or user.role.is_admin:
                use_private_fields = True
            elif hasattr(kwargs['context']['request'], 'parser_context'):
                # pk is for the parent event
                pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdecimal():
                    obj = Event.objects.filter(id=pk).first()
                    if obj and (user.id == obj.created_by.id or user.organization.id == obj.created_by.organization.id
                                or user.organization.id in obj.created_by.parent_organizations
                                or user.id in list(User.objects.filter(
                                Q(writeevents__in=[obj.id]) | Q(readevents__in=[obj.id])
                            ).values_list('id', flat=True))):
                        use_private_fields = True

        super(EventLocationDetailSerializer, self).__init__(*args, **kwargs)

        fields = private_fields if use_private_fields else fields
        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

        self.fields['locationspecies'] = LocationSpeciesDetailSerializer(many=True, context=self.context)
        if use_private_fields:
            self.fields['comments'] = CommentSerializer(many=True, context=self.context)
            self.fields['eventlocationcontacts'] = EventLocationContactDetailSerializer(
                source='eventlocationcontact_set', many=True, context=self.context)

    class Meta:
        model = EventLocation
        fields = '__all__'


class ServiceRequestDetailSerializer(serializers.ModelSerializer):
    request_type_string = serializers.StringRelatedField(source='request_type')
    request_response_string = serializers.StringRelatedField(source='request_response')
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    created_by_first_name = serializers.StringRelatedField(source='created_by.first_name')
    created_by_last_name = serializers.StringRelatedField(source='created_by.last_name')
    created_by_organization = serializers.StringRelatedField(source='created_by.organization.id')
    created_by_organization_string = serializers.StringRelatedField(source='created_by.organization.name')
    comments = CommentSerializer(many=True)

    class Meta:
        model = ServiceRequest
        fields = ('id', 'request_type', 'request_type_string', 'request_response', 'request_response_string',
                  'response_by', 'created_time', 'created_date', 'created_by', 'created_by_string',
                  'created_by_first_name', 'created_by_last_name', 'created_by_organization',
                  'created_by_organization_string', 'modified_date', 'modified_by', 'modified_by_string', 'comments',)


class EventDetailSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    created_by_first_name = serializers.StringRelatedField(source='created_by.first_name')
    created_by_last_name = serializers.StringRelatedField(source='created_by.last_name')
    created_by_organization = serializers.StringRelatedField(source='created_by.organization.id')
    created_by_organization_string = serializers.StringRelatedField(source='created_by.organization.name')
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    staff_string = serializers.StringRelatedField(source='staff')
    event_status_string = serializers.StringRelatedField(source='event_status')
    legal_status_string = serializers.StringRelatedField(source='legal_status')
    # eventlocations = EventLocationDetailSerializer(many=True)
    eventdiagnoses = serializers.SerializerMethodField()
    combined_comments = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True)
    servicerequests = ServiceRequestDetailSerializer(many=True)
    organizations = serializers.SerializerMethodField()
    eventgroups = serializers.SerializerMethodField()
    read_collaborators = UserSerializer(many=True)
    write_collaborators = UserSerializer(many=True)
    is_privileged_user = serializers.SerializerMethodField()

    def get_is_privileged_user(self, obj, *args, **kwargs):
        user = None
        pk = None
        if 'request' in self.context:
            if hasattr(self.context['request'], 'user'):
                user = self.context['request'].user
            if hasattr(self.context['request'], 'parser_context'):
                pk = self.context['request'].parser_context['kwargs'].get('pk', None)
        if not user or not user.is_authenticated or user.role.is_public:
            return False
        elif user.role.is_superadmin or user.role.is_admin:
            return True
        elif pk is None and 'context' in kwargs and hasattr(kwargs['context']['request'], 'parser_context'):
            pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
        if pk is not None and pk.isdecimal():
            obj = Event.objects.filter(id=pk).first()
            if obj and (user.id == obj.created_by.id or user.organization.id == obj.created_by.organization.id
                        or user.organization.id in obj.created_by.parent_organizations
                        or user.id in list(User.objects.filter(
                        Q(writeevents__in=[obj.id]) | Q(readevents__in=[obj.id])
                    ).values_list('id', flat=True))):
                return True
            else:
                return False
        else:
            return False

    def get_combined_comments(self, obj):
        event_content_type = ContentType.objects.filter(model='event').first()
        event_comments = Comment.objects.filter(object_id=obj.id, content_type=event_content_type.id)
        evtloc_ids = list(EventLocation.objects.filter(event=obj.id).values_list('id', flat=True))
        evtloc_content_type = ContentType.objects.filter(model='eventlocation').first()
        evtloc_comments = Comment.objects.filter(object_id__in=evtloc_ids, content_type=evtloc_content_type.id)
        servreq_ids = list(ServiceRequest.objects.filter(event=obj.id).values_list('id', flat=True))
        servreq_content_type = ContentType.objects.filter(model='servicerequest').first()
        servreq_comments = Comment.objects.filter(object_id__in=servreq_ids, content_type=servreq_content_type)
        union_comments = event_comments.union(evtloc_comments).union(servreq_comments)#.order_by('-id')
        # return CommentSerializer(union_comments, many=True).data
        combined_comments = []
        for cmt in union_comments:
            # date_sort = datetime.strptime(str(cmt.created_date) + " 00:00:00." + str(cmt.id), "%Y-%m-%d %H:%M:%S.%f")
            date_sort = (str(cmt.created_date.year) + str(cmt.created_date.month).zfill(2)
                         + str(cmt.created_date.day).zfill(2) + "." + str(cmt.id).zfill(32))
            comment = {
                "id": cmt.id, "comment": cmt.comment, "comment_type": cmt.comment_type.id, "object_id": cmt.object_id,
                "content_type_string": cmt.content_type.model, "created_date": cmt.created_date,
                "created_by": cmt.created_by.id, "created_by_string": cmt.created_by.username,
                "created_by_first_name": cmt.created_by.first_name, "created_by_last_name": cmt.created_by.last_name,
                "created_by_organization": cmt.created_by.organization.id,
                "created_by_organization_string": cmt.created_by.organization.name,
                "modified_date": cmt.modified_date, "modified_by": cmt.modified_by.id,
                "modified_by_string": cmt.modified_by.username, "date_sort": date_sort
            }
            if cmt.content_type.model == 'event':
                comment['object_name'] = Event.objects.filter(id=cmt.object_id).first().event_reference
            elif cmt.content_type.model == 'eventlocation':
                comment['object_name'] = EventLocation.objects.filter(id=cmt.object_id).first().name
            combined_comments.append(comment)
        return sorted(combined_comments, key=itemgetter('date_sort'), reverse=True)

    def get_eventgroups(self, obj, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user
        elif 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        if user and user.is_authenticated and (user.role.is_superadmin or user.role.is_admin):
            pub_groups = []
            if obj.eventgroups is not None:
                evtgrp_ids = list(set(list(EventEventGroup.objects.filter(
                    event=obj.id).values_list('eventgroup_id', flat=True))))
                evtgrps = EventGroup.objects.filter(
                    id__in=evtgrp_ids, category__name='Biologically Equivalent (Public)')
                for evtgrp in evtgrps:
                    evt_ids = list(set(list(EventEventGroup.objects.filter(
                        eventgroup=evtgrp.id).values_list('event_id', flat=True))))
                    evtgrp_comments = Comment.objects.filter(object_id=evtgrp.id)
                    evtgrp_comments_dicts_list = [model_to_dict(x) for x in evtgrp_comments]
                    evtgrp_created_by_string = evtgrp.created_by.first_name + "" + evtgrp.created_by.last_name
                    evtgrp_modified_by_string = evtgrp.modified_by.first_name + "" + evtgrp.modified_by.last_name
                    group = {'id': evtgrp.id, 'name': evtgrp.name, 'category': evtgrp.category.id,
                             'comments': evtgrp_comments_dicts_list, 'events': evt_ids,
                             'created_date': str(evtgrp.created_date), 'created_by': evtgrp.created_by.id,
                             'created_by_string': evtgrp_created_by_string, 'modified_date': str(evtgrp.modified_date),
                             'modified_by': evtgrp.modified_by.id, 'modified_by_string': evtgrp_modified_by_string}
                    pub_groups.append(group)
            return pub_groups
        else:
            pub_groups = []
            if obj.eventgroups is not None:
                evtgrp_ids = list(set(list(EventEventGroup.objects.filter(
                    event=obj.id).values_list('eventgroup_id', flat=True))))
                evtgrps = EventGroup.objects.filter(
                    id__in=evtgrp_ids, category__name='Biologically Equivalent (Public)')
                for evtgrp in evtgrps:
                    evt_ids = list(set(list(EventEventGroup.objects.filter(
                        eventgroup=evtgrp.id).values_list('event_id', flat=True))))
                    group = {'id': evtgrp.id, 'name': evtgrp.name, 'events': evt_ids}
                    pub_groups.append(group)
            return pub_groups

    def get_organizations(self, obj):
        pub_orgs = []
        if obj.organizations is not None:
            orgs = obj.organizations.all()
            evtorgs = EventOrganization.objects.filter(
                event=obj.id, organization__do_not_publish=False).order_by('priority')
            for evtorg in evtorgs:
                org = [org for org in orgs if org.id == evtorg.organization.id][0]
                al1_id = org.administrative_level_one.id if org.administrative_level_one else None
                al1_name = org.administrative_level_one.name if org.administrative_level_one else ''
                country_id = org.country.id if org.country else None
                country_name = org.country.name if org.country else ''
                new_org = {'id': org.id, 'name': org.name, 'address_one': org.address_one,
                           'address_two': org.address_two, 'city': org.city, 'postal_code': org.postal_code,
                           'administrative_level_one': al1_id, 'administrative_level_one_string': al1_name,
                           'country': country_id, 'country_string': country_name, 'phone': org.phone}
                pub_orgs.append({"id": evtorg.id, "priority": evtorg.priority, "organization": new_org})
        return pub_orgs

    def get_eventdiagnoses(self, obj, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user
        elif 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        if not user or not user.is_authenticated or user.role.is_public:
            event_diagnoses = EventDiagnosis.objects.filter(event=obj.id)
            eventdiagnoses = []
            for event_diagnosis in event_diagnoses:
                if event_diagnosis.diagnosis:
                    diag_id = event_diagnosis.diagnosis.id
                    diag_name = event_diagnosis.diagnosis.name
                    if event_diagnosis.suspect:
                        diag_name = diag_name + " suspect"
                    altered_event_diagnosis = {"diagnosis": diag_id, "diagnosis_string": diag_name,
                                               "suspect": event_diagnosis.suspect, "major": event_diagnosis.major}
                    eventdiagnoses.append(altered_event_diagnosis)
            return eventdiagnoses

        event_diagnoses = EventDiagnosis.objects.filter(event=obj.id)
        eventdiagnoses = []
        for event_diagnosis in event_diagnoses:
            if event_diagnosis.diagnosis:
                diag_id = event_diagnosis.diagnosis.id
                diag_name = event_diagnosis.diagnosis.name
                if event_diagnosis.suspect:
                    diag_name = diag_name + " suspect"
                diag_type = event_diagnosis.diagnosis.diagnosis_type
                diag_type_id = event_diagnosis.diagnosis.diagnosis_type.id if diag_type else None
                diag_type_name = event_diagnosis.diagnosis.diagnosis_type.name if diag_type else ''
                created_by = event_diagnosis.created_by.id if event_diagnosis.created_by else None
                created_by_string = event_diagnosis.created_by.username if event_diagnosis.created_by else ''
                modified_by = event_diagnosis.modified_by.id if event_diagnosis.modified_by else None
                modified_by_string = event_diagnosis.modified_by.username if event_diagnosis.modified_by else ''
                altered_event_diagnosis = {"id": event_diagnosis.id, "event": event_diagnosis.event.id,
                                           "diagnosis": diag_id, "diagnosis_string": diag_name,
                                           "diagnosis_type": diag_type_id, "diagnosis_type_string": diag_type_name,
                                           "suspect": event_diagnosis.suspect, "major": event_diagnosis.major,
                                           "priority": event_diagnosis.priority,
                                           "created_date": event_diagnosis.created_date, "created_by": created_by,
                                           "created_by_string": created_by_string,
                                           "modified_date": event_diagnosis.modified_date, "modified_by": modified_by,
                                           "modified_by_string": modified_by_string}
                eventdiagnoses.append(altered_event_diagnosis)
        return eventdiagnoses

    def get_permission_source(self, obj):
        return determine_permission_source(self.context['request'].user, obj)

    def __init__(self, *args, **kwargs):
        user = None
        if 'context' in kwargs and 'request' in kwargs['context'] and hasattr(kwargs['context']['request'], 'user'):
            user = kwargs['context']['request'].user

        fields = ('id', 'event_type', 'event_type_string', 'complete', 'start_date', 'end_date', 'affected_count',
                  'event_status', 'event_status_string', 'eventgroups', 'eventdiagnoses', 'eventlocations',
                  'organizations', 'permissions', 'permission_source', 'is_privileged_user',)
        private_fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date',
                          'end_date', 'affected_count', 'event_status', 'event_status_string', 'public',
                          'read_collaborators', 'write_collaborators', 'eventgroups', 'eventdiagnoses',
                          'eventlocations', 'organizations', 'combined_comments', 'comments', 'servicerequests',
                          'created_date', 'created_by', 'created_by_string', 'created_by_first_name',
                          'created_by_last_name', 'created_by_organization', 'created_by_organization_string',
                          'modified_date', 'modified_by', 'modified_by_string', 'permissions', 'permission_source',
                          'is_privileged_user',)
        admin_fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date',
                        'end_date', 'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string',
                        'legal_status', 'legal_status_string', 'legal_number', 'quality_check', 'public',
                        'read_collaborators', 'write_collaborators', 'eventgroups', 'eventdiagnoses', 'eventlocations',
                        'organizations', 'combined_comments', 'comments', 'servicerequests', 'created_date',
                        'created_by', 'created_by_string', 'created_by_first_name', 'created_by_last_name',
                        'created_by_organization', 'created_by_organization_string', 'modified_date', 'modified_by',
                        'modified_by_string', 'permissions', 'permission_source', 'is_privileged_user',)

        if user and user.is_authenticated:
            if user.role.is_superadmin or user.role.is_admin:
                fields = admin_fields
            elif hasattr(kwargs['context']['request'], 'parser_context'):
                pk = kwargs['context']['request'].parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdecimal():
                    obj = Event.objects.filter(id=pk).first()
                    if obj and (user.id == obj.created_by.id or user.organization.id == obj.created_by.organization.id
                                or user.organization.id in obj.created_by.parent_organizations
                                or user.id in list(User.objects.filter(
                                Q(writeevents__in=[obj.id]) | Q(readevents__in=[obj.id])
                            ).values_list('id', flat=True))):
                        fields = private_fields

        super(EventDetailSerializer, self).__init__(*args, **kwargs)

        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

        self.fields['eventlocations'] = EventLocationDetailSerializer(many=True, context=self.context)

    class Meta:
        model = Event
        fields = '__all__'


class FlatEventDetailSerializer(serializers.Serializer):
    # a flattened (not nested) version of the essential fields of the FullResultSerializer, to populate CSV files
    # requested from the EventDetails Search

    event_id = serializers.IntegerField()
    # event_reference = serializers.CharField()
    event_type = serializers.CharField()
    complete = serializers.CharField()
    organization = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    affected_count = serializers.IntegerField()
    event_diagnosis = serializers.CharField()
    location_id = serializers.IntegerField()
    location_priority = serializers.IntegerField()
    county = serializers.CharField()
    state = serializers.CharField()
    country = serializers.CharField()
    location_start = serializers.DateField()
    location_end = serializers.DateField()
    location_species_id = serializers.IntegerField()
    species_priority = serializers.IntegerField()
    species_name = serializers.CharField()
    population = serializers.IntegerField()
    sick = serializers.IntegerField()
    dead = serializers.IntegerField()
    estimated_sick = serializers.IntegerField()
    estimated_dead = serializers.IntegerField()
    captive = serializers.CharField()
    age_bias = serializers.CharField()
    sex_bias = serializers.CharField()
    species_diagnosis_id = serializers.IntegerField()
    species_diagnosis_priority = serializers.IntegerField()
    speciesdx = serializers.CharField()
    # causal = serializers.CharField()
    suspect = serializers.BooleanField()
    number_tested = serializers.IntegerField()
    number_positive = serializers.IntegerField()
    lab = serializers.CharField()
