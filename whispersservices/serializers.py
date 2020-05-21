import re
import requests
import json
from operator import itemgetter
from datetime import datetime, timedelta
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.forms.models import model_to_dict
from rest_framework import serializers, validators
from rest_framework.settings import api_settings
from whispersservices.models import *
from dry_rest_permissions.generics import DRYPermissionsField

# TODO: implement required field validations for nested objects
# TODO: consider implementing type checking for nested objects
# TODO: turn every ListField into a set to prevent errors caused by duplicates

COMMENT_CONTENT_TYPES = ['event', 'eventgroup', 'eventlocation', 'servicerequest']
GEONAMES_USERNAME = settings.GEONAMES_USERNAME
GEONAMES_API = 'http://api.geonames.org/'
FLYWAYS_API = 'https://services.arcgis.com/'
FLYWAYS_API += 'QVENGdaPbd4LUkLV/ArcGIS/rest/services/FWS_HQ_MB_Waterfowl_Flyway_Boundaries/FeatureServer/0/query'


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
    elif user.organization.id == obj.created_by.organization.id:
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


def construct_service_request_email(event_id, requester_org_name, request_type_name, requester_email, comments):
    # construct and send the request email
    event_id_string = str(event_id)
    url = settings.APP_WHISPERS_URL + 'event/' + event_id_string
    subject = "Service request for Event " + event_id_string
    body = "A user (" + requester_email + ") with organization " + requester_org_name + " has requested "
    body += "<strong>" + request_type_name + "</strong> for event " + event_id_string + "."
    if comments:
        body += "<br><br>Comments:"
        for comment in comments:
            body += "<br>&nbsp;&nbsp;&nbsp;&nbsp;" + comment
    body += "<br><br>Event Details:<br>&nbsp;&nbsp;&nbsp;&nbsp;"
    html_body = body + "<a href='" + url + "/'>" + url + "/</a>"
    body = body.replace('<strong>', '').replace('</strong>', '').replace('<br>', '    ').replace('&nbsp;', ' ')
    body += url + "/"
    from_address = settings.EMAIL_WHISPERS
    if settings.ENVIRONMENT == 'production':
        to_list = [settings.EMAIL_NWHC_EPI, ]
    else:
        to_list = [settings.EMAIL_WHISPERS, ]
    bcc_list = []
    reply_list = [requester_email, ]
    headers = None  # {'Message-ID': 'foo'}
    email = EmailMultiAlternatives(subject, body, from_address, to_list, bcc_list, reply_to=reply_list, headers=headers)
    email.attach_alternative(html_body, "text/html")
    if settings.ENVIRONMENT in ['production', 'test']:
        try:
            email.send(fail_silently=False)
        except TypeError:
            message = "Service Request saved but send email failed, please contact the administrator."
            raise serializers.ValidationError(jsonify_errors(message))
    return email


def construct_user_request_email(requester_email, message):
    # construct and send the request email
    subject = "Assistance Request"
    body = "A person (" + requester_email + ") has requested assistance:\r\n\r\n"
    body += message
    from_address = settings.EMAIL_WHISPERS
    to_list = [settings.EMAIL_WHISPERS, ]
    bcc_list = []
    reply_list = [requester_email, ]
    headers = None  # {'Message-ID': 'foo'}
    email = EmailMessage(subject, body, from_address, to_list, bcc_list, reply_to=reply_list, headers=headers)
    if settings.ENVIRONMENT in ['production', 'test']:
        try:
            email.send(fail_silently=False)
        except TypeError:
            message = "User saved but send email failed, please contact the administrator."
            raise serializers.ValidationError(jsonify_errors(message))
    return email


def construct_email(subject, message):
    # construct and send the email
    subject = subject
    body = message
    from_address = settings.EMAIL_WHISPERS
    to_list = [settings.EMAIL_WHISPERS, ]
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
    return email


def confirm_geonames_api_responsive(endpoint):
    responsive = False
    r = None
    if endpoint == 'extendedFindNearbyJSON':
        payload = {'lat': '-90.0', 'lng': '45.0', 'username': GEONAMES_USERNAME}
        r = requests.get(GEONAMES_API + endpoint, params=payload, verify=settings.SSL_CERT)
        content = decode_json(r)
        if 'address' in content or 'geonames' in content:
            responsive = True
    elif endpoint == 'countryInfoJSON':
        payload = {'country': 'US', 'username': GEONAMES_USERNAME}
        r = requests.get(GEONAMES_API + endpoint, params=payload, verify=settings.SSL_CERT)
        content = decode_json(r)
        if ('geonames' in content and content['geonames'] is not None
                and len(content['geonames']) > 0 and 'isoAlpha3' in content['geonames'][0]):
            responsive = True
    elif endpoint == 'searchJSON':
        payload = {'name': 'Dane', 'featureCode': 'ADM2', 'maxRows': 1, 'username': GEONAMES_USERNAME}
        r = requests.get(GEONAMES_API + endpoint, params=payload, verify=settings.SSL_CERT)
        content = decode_json(r)
        if ('geonames' in content and content['geonames'] is not None
                and len(content['geonames']) > 0
                and 'lng' in content['geonames'][0] and 'lat' in content['geonames'][0]):
            responsive = True
    else:
        message = "The Geonames API is unresponsive (the following query returned an unexpected format).\r\n\r\n"
        message += r.url + "\r\n\r\n"
        message += "This API is used by WHISPers for Event Location validation"
        message += " and so validation for latitude, longitude, country, and administrative levels was skipped."
        construct_email("Geonames API Unresponsive", message)
    return responsive


def calculate_priority_event_organization(instance):

    # calculate the priority value:
    # Sort by owner organization first, then by order of entry.
    priority = 1
    evt_orgs = EventOrganization.objects.filter(organization=instance.organization).order_by('id')
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
        event=instance.event).exclude(id=instance.id).order_by('diagnosis__name')
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
                    and instance.administrative_level_two.name <= evtloc.administrative_level_two.name):
                if instance.event.event_type.id == 1:
                    if self_sick_dead_count >= (evtloc.affected_count or 0):
                        instance.priority = priority
                        priority += 1
                        self_priority_updated = True
                elif instance.event.event_type.id == 2:
                    if self_positive_count >= (evtloc.affected_count or 0):
                        instance.priority = priority
                        priority += 1
                        self_priority_updated = True
            evtloc.priority = priority
            evtloc.save()
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
                    if self_sick_dead_count >= (locspec.affected_count or 0):
                        instance.priority = priority
                        priority += 1
                        self_priority_updated = True
                elif instance.event_location.event.event_type.id == 2:
                    if self_positive_count >= (locspec.affected_count or 0):
                        instance.priority = priority
                        priority += 1
                        self_priority_updated = True
            locspec.priority = priority
            locspec.save()
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
        location_species=instance.location_species).exclude(
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
        content_type = ContentType.objects.filter(app_label='whispersservices', model=new_content_type).first()
        content_object = content_type.model_class().objects.filter(id=validated_data['object_id']).first()
        if not content_object:
            message = "An object of type (" + str(new_content_type)
            message += ") and ID (" + str(validated_data['object_id']) + ") could not be found."
            raise serializers.ValidationError(jsonify_errors(message))
        comment = Comment.objects.create(**validated_data, content_object=content_object)
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


class EventPublicSerializer(serializers.ModelSerializer):
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    event_status_string = serializers.StringRelatedField(source='event_status')

    def get_permission_source(self, obj):
        return determine_permission_source(self.context['request'].user, obj)

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'complete', 'start_date', 'end_date', 'affected_count',
                  'event_status', 'event_status_string', 'permissions', 'permission_source',)


# TODO: allow read-only staff field for event owner org
# TODO: validate expected fields and field data types for all submitted nested objects
class EventSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    event_status_string = serializers.StringRelatedField(source='event_status')
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
                latlng_matches_county = True
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
                    geonames_endpoint = 'extendedFindNearbyJSON'
                    if confirm_geonames_api_responsive(geonames_endpoint):
                        if ('latitude' in item and item['latitude'] is not None
                                and 'longitude' in item and item['longitude'] is not None):
                            payload = {'lat': item['latitude'], 'lng': item['longitude'],
                                       'username': GEONAMES_USERNAME}
                            r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                            content = decode_json(r)
                            if 'address' not in content and 'geonames' not in content:
                                latlng_is_valid = False
                        if (latlng_is_valid and 'latitude' in item and item['latitude'] is not None
                                and 'longitude' in item and item['longitude'] is not None
                                and 'country' in item and item['country'] is not None):
                            payload = {'lat': item['latitude'], 'lng': item['longitude'], 'username': GEONAMES_USERNAME}
                            r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                            geonames_object_list = decode_json(r)
                            if 'address' in geonames_object_list:
                                address = geonames_object_list['address']
                                if 'name' in address:
                                    address['adminName2'] = address['name']
                            elif 'geonames' in geonames_object_list:
                                geonames_objects_adm2 = [item for item in geonames_object_list['geonames'] if
                                                         item['fcode'] == 'ADM2']
                                address = geonames_objects_adm2[0]
                            else:
                                # the response from the Geonames web service is in an unexpected format
                                address = None
                            geonames_endpoint = 'countryInfoJSON'
                            if address and confirm_geonames_api_responsive(geonames_endpoint):
                                country_code = address['countryCode']
                                if len(country_code) == 2:
                                    payload = {'country': country_code, 'username': GEONAMES_USERNAME}
                                    r = requests.get(GEONAMES_API + geonames_endpoint, params=payload,
                                                     verify=settings.SSL_CERT)
                                    content = decode_json(r)
                                    if ('geonames' in content and content['geonames'] is not None
                                            and len(content['geonames']) > 0
                                            and 'isoAlpha3' in content['geonames'][0]):
                                        alpha3 = content['geonames'][0]['isoAlpha3']
                                        country = Country.objects.filter(abbreviation=alpha3).first()
                                else:
                                    country = Country.objects.filter(abbreviation=country_code).first()
                                if int(item['country']) != country.id:
                                    latlng_matches_county = False
                                elif ('administrative_level_one' in item
                                      and item['administrative_level_one'] is not None):
                                    admin_l1 = AdministrativeLevelOne.objects.filter(
                                        name=address['adminName1']).first()
                                    if int(item['administrative_level_one']) != admin_l1.id:
                                        latlng_matches_admin_l1 = False
                                    elif ('administrative_level_two' in item
                                          and item['administrative_level_two'] is not None):
                                        a2 = address['adminName2'] if 'adminName2' in address else address['name']
                                        admin_l2 = AdministrativeLevelTwo.objects.filter(name=a2).first()
                                        if int(item['administrative_level_two']) != admin_l2.id:
                                            latlng_matches_admin_21 = False
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
                if not latlng_matches_county:
                    message = "latitude and longitude are not in the user-specified country."
                    details.append(message)
                if not latlng_matches_admin_l1:
                    message = "latitude and longitude are not in the user-specified administrative level one."
                    details.append(message)
                if not latlng_matches_admin_21:
                    message = "latitude and longitude are not in the user-specified administrative level two."
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
                if read_user is not None:
                    EventReadUser.objects.create(user=read_user, event=event, created_by=user, modified_by=user)

        if new_write_user_ids is not None:
            for write_user_id in new_write_user_ids:
                write_user = User.objects.filter(id=write_user_id).first()
                if write_user is not None:
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
                        event_org.save()
        else:
            event_org = EventOrganization.objects.create(event=event, organization=user.organization,
                                                         created_by=user, modified_by=user)
            event_org.priority = calculate_priority_event_organization(event_org)
            event_org.save()

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
        pending = list(Diagnosis.objects.filter(name='Pending').values_list('id', flat=True))[0]
        undetermined = list(Diagnosis.objects.filter(name='Undetermined').values_list('id', flat=True))[0]
        existing_evt_diag_ids = list(EventDiagnosis.objects.filter(event=event.id).values_list('diagnosis', flat=True))
        if len(existing_evt_diag_ids) > 0 and undetermined in existing_evt_diag_ids:
            remove_diagnoses = [pending, undetermined]
        else:
            remove_diagnoses = [pending, ]

        # remove Pending if in the list because it should never be submitted by the user
        # and remove Undetermined if in the list and the event already has an Undetermined
        [new_event_diagnoses.remove(x) for x in new_event_diagnoses if int(x['diagnosis']) in remove_diagnoses]

        if new_event_diagnoses:
            is_valid = True
            valid_data = []
            errors = []
            for event_diagnosis in new_event_diagnoses:
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
            #         diagnosis_id = event_diagnosis.pop('diagnosis', None)
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
            #             event_diagnosis.save()
            #             new_event_diagnoses_created.append(event_diagnosis)
            #     # If any new event diagnoses were created, check for existing Pending record and delete it
            #     if len(new_event_diagnoses_created) > 0:
            #         event_diagnoses = EventDiagnosis.objects.filter(event=event.id)
            #         [diag.delete() for diag in event_diagnoses if diag.diagnosis.id == pending]

        # Create the child service requests for this event
        if new_service_request is not None:
            if ('request_type' in new_service_request and new_service_request['request_type'] is not None
                    and new_service_request['request_type'] in [1, 2]):
                new_comments = new_service_request.pop('new_comments', None)
                request_type = ServiceRequestType.objects.filter(id=new_service_request['request_type']).first()
                request_response = ServiceRequestResponse.objects.filter(name='Pending').first()
                admin = User.objects.filter(id=1).first()
                service_request = ServiceRequest.objects.create(event=event, request_type=request_type,
                                                                request_response=request_response, response_by=admin,
                                                                created_by=user, modified_by=user)
                service_request_comments = []

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
                            service_request_comments.append(comment['comment'])

                # construct and send the request email
                service_request_email = construct_service_request_email(service_request.event.id,
                                                                        user.organization.name,
                                                                        service_request.request_type.name,
                                                                        user.email,
                                                                        service_request_comments)
                if settings.ENVIRONMENT not in ['production', 'test']:
                    event.service_request_email = service_request_email.__dict__

        return event

    # on update, any submitted nested objects (new_organizations, new_comments, new_event_locations) will be ignored
    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        new_complete = validated_data.get('complete', None)

        # check if Event is complete
        if instance.complete:
            # only event owner or higher roles can re-open ('un-complete') a closed ('completed') event
            # but if the complete field is not included or set to True, the event cannot be changed
            if new_complete is None or (new_complete and (user.id == instance.created_by.id or (
                    user.organization.id == instance.created_by.organization.id and (
                    user.role.is_partneradmin or user.role.is_partnermanager)))):
                message = "Complete events may only be changed by the event owner or an administrator"
                message += " if the 'complete' field is set to False."
                raise serializers.ValidationError(jsonify_errors(message))
            elif (user != instance.created_by
                  or (user.organization.id != instance.created_by.organization.id
                      and not (user.role.is_partneradmin or user.role.is_partnermanager))):
                message = "Complete events may not be changed"
                message += " unless first re-opened by the event owner or an administrator."
                raise serializers.ValidationError(jsonify_errors(message))

        # otherwise if the Event is not complete but being set to complete, apply business rules
        if not instance.complete and new_complete and (user.id == instance.created_by.id or (
                user.organization.id == instance.created_by.organization.id and (
                user.role.is_partneradmin or user.role.is_partnermanager))):
            # only let the status be changed to 'complete=True' if
            # 1. All child locations have an end date and each location's end date is later than its start date
            # 2. For morbidity/mortality events, there must be at least one number between sick, dead, estimated_sick,
            #   and estimated_dead per species at the time of event completion.
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
                    if not location.end_date or not location.start_date or not location.end_date >= location.start_date:
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
                                if spec.sick_count > 0 and not spec.sick_count_estimated > spec.sick_count:
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
            new_read_user_ids_prelim = []
        if 'new_write_collaborators' in validated_data:
            new_write_collaborators = validated_data.pop('new_write_collaborators', None)
            new_write_user_ids = set(new_write_collaborators) if new_write_collaborators else set([])
        else:
            new_write_user_ids = []

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
            for user_id in add_read_users:
                EventReadUser.objects.create(user=user_id, event=instance, created_by=user, modified_by=user)

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
            for user_id in add_write_users:
                EventWriteUser.objects.create(user=user_id, event=instance, created_by=user, modified_by=user)

        # update the Event object
        instance.event_type = validated_data.get('event_type', instance.event_type)
        instance.event_reference = validated_data.get('event_reference', instance.event_reference)
        instance.complete = validated_data.get('complete', instance.complete)
        instance.public = validated_data.get('public', instance.public)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

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

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'event_status', 'event_status_string', 'public', 'read_collaborators',
                  'write_collaborators', 'organizations', 'contacts', 'comments', 'new_event_diagnoses',
                  'new_organizations', 'new_comments', 'new_event_locations', 'new_eventgroups',
                  'new_service_request', 'new_read_collaborators', 'new_write_collaborators', 'created_date',
                  'created_by', 'created_by_string', 'modified_date', 'modified_by', 'modified_by_string',
                  'service_request_email', 'permissions', 'permission_source',)


class EventAdminSerializer(serializers.ModelSerializer):
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
                latlng_matches_county = True
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
                    geonames_endpoint = 'extendedFindNearbyJSON'
                    if confirm_geonames_api_responsive(geonames_endpoint):
                        if ('latitude' in item and item['latitude'] is not None
                                and 'longitude' in item and item['longitude'] is not None):
                            payload = {'lat': item['latitude'], 'lng': item['longitude'],
                                       'username': GEONAMES_USERNAME}
                            r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                            content = decode_json(r)
                            if 'address' not in content and 'geonames' not in content:
                                latlng_is_valid = False
                        if (latlng_is_valid and 'latitude' in item and item['latitude'] is not None
                                and 'longitude' in item and item['longitude'] is not None
                                and 'country' in item and item['country'] is not None):
                            payload = {'lat': item['latitude'], 'lng': item['longitude'], 'username': GEONAMES_USERNAME}
                            r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                            geonames_object_list = decode_json(r)
                            if 'address' in geonames_object_list:
                                address = geonames_object_list['address']
                                if 'name' in address:
                                    address['adminName2'] = address['name']
                            elif 'geonames' in geonames_object_list:
                                geonames_objects_adm2 = [item for item in geonames_object_list['geonames'] if
                                                         item['fcode'] == 'ADM2']
                                address = geonames_objects_adm2[0]
                            else:
                                # the response from the Geonames web service is in an unexpected format
                                address = None
                            geonames_endpoint = 'countryInfoJSON'
                            if address and confirm_geonames_api_responsive(geonames_endpoint):
                                country_code = address['countryCode']
                                if len(country_code) == 2:
                                    payload = {'country': country_code, 'username': GEONAMES_USERNAME}
                                    r = requests.get(GEONAMES_API + geonames_endpoint, params=payload,
                                                     verify=settings.SSL_CERT)
                                    content = decode_json(r)
                                    if ('geonames' in content and content['geonames'] is not None
                                            and len(content['geonames']) > 0 and 'isoAlpha3' in content['geonames'][0]):
                                        alpha3 = content['geonames'][0]['isoAlpha3']
                                        country = Country.objects.filter(abbreviation=alpha3).first()
                                else:
                                    country = Country.objects.filter(abbreviation=country_code).first()
                                if int(item['country']) != country.id:
                                    latlng_matches_county = False
                                elif ('administrative_level_one' in item
                                      and item['administrative_level_one'] is not None):
                                    admin_l1 = AdministrativeLevelOne.objects.filter(name=address['adminName1']).first()
                                    if int(item['administrative_level_one']) != admin_l1.id:
                                        latlng_matches_admin_l1 = False
                                    elif 'administrative_level_two' in item and item[
                                        'administrative_level_two'] is not None:
                                        a2 = address['adminName2'] if 'adminName2' in address else address['name']
                                        admin_l2 = AdministrativeLevelTwo.objects.filter(name=a2).first()
                                        if int(item['administrative_level_two']) != admin_l2.id:
                                            latlng_matches_admin_21 = False
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
                if not latlng_matches_county:
                    message = "latitude and longitude are not in the user-specified country."
                    details.append(message)
                if not latlng_matches_admin_l1:
                    message = "latitude and longitude are not in the user-specified administrative level one."
                    details.append(message)
                if not latlng_matches_admin_21:
                    message = "latitude and longitude are not in the user-specified administrative level two."
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
                location_message += " and each location's end date is after that location's start date."
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
                        if data['event_type'] == mortality_morbidity.id:
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
                if read_user is not None:
                    EventReadUser.objects.create(user=read_user, event=event, created_by=user, modified_by=user)

        if new_write_user_ids is not None:
            for write_user_id in new_write_user_ids:
                write_user = User.objects.filter(id=write_user_id).first()
                if write_user is not None:
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
                        event_org.save()
        else:
            event_org = EventOrganization.objects.create(event=event, organization=user.organization,
                                                         created_by=user, modified_by=user)
            event_org.priority = calculate_priority_event_organization(event_org)
            event_org.save()

        # create the child comments for this event
        if new_comments is not None:
            for comment in new_comments:
                if comment is not None:
                    if 'comment_type' in comment and comment['comment_type'] is not None:
                        comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                        if comment_type is not None:
                            Comment.objects.create(content_object=event, comment=comment['comment'],
                                                   comment_type=comment_type, created_by=user, modified_by=user)

        # create the child eventgroups for this event
        if new_eventgroups is not None:
            for eventgroup_id in new_eventgroups:
                if eventgroup_id is not None:
                    eventgroup = EventGroup.objects.filter(id=eventgroup_id).first()
                    if eventgroup is not None:
                        EventEventGroup.objects.create(event=event, eventgroup=eventgroup,
                                                       created_by=user, modified_by=user)

        # create the child event diagnoses for this event
        pending = list(Diagnosis.objects.filter(name='Pending').values_list('id', flat=True))[0]
        undetermined = list(Diagnosis.objects.filter(name='Undetermined').values_list('id', flat=True))[0]
        existing_evt_diag_ids = list(EventDiagnosis.objects.filter(event=event.id).values_list('diagnosis', flat=True))
        if len(existing_evt_diag_ids) > 0 and undetermined in existing_evt_diag_ids:
            remove_diagnoses = [pending, undetermined]
        else:
            remove_diagnoses = [pending, ]

        # remove Pending if in the list because it should never be submitted by the user
        # and remove Undetermined if in the list and the event already has an Undetermined
        [new_event_diagnoses.remove(x) for x in new_event_diagnoses if int(x['diagnosis']) in remove_diagnoses]

        if new_event_diagnoses:
            is_valid = True
            valid_data = []
            errors = []
            for event_diagnosis in new_event_diagnoses:
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
            #             event_diagnosis.save()
            #             new_event_diagnoses_created.append(event_diagnosis)
            #     # If any new event diagnoses were created, check for existing Pending record and delete it
            #     if len(new_event_diagnoses_created) > 0:
            #         event_diagnoses = EventDiagnosis.objects.filter(event=event.id)
            #         [diag.delete() for diag in event_diagnoses if diag.diagnosis.id == pending]

        # Create the child service requests for this event
        if new_service_request is not None:
            if ('request_type' in new_service_request and new_service_request['request_type'] is not None
                    and new_service_request['request_type'] in [1, 2]):
                new_comments = new_service_request.pop('new_comments', None)
                request_type = ServiceRequestType.objects.filter(id=new_service_request['request_type']).first()
                request_response = ServiceRequestResponse.objects.filter(name='Pending').first()
                admin = User.objects.filter(id=1).first()
                service_request = ServiceRequest.objects.create(event=event, request_type=request_type,
                                                                request_response=request_response, response_by=admin,
                                                                created_by=user, modified_by=user)
                service_request_comments = []

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
                            service_request_comments.append(comment['comment'])

                # construct and send the request email
                service_request_email = construct_service_request_email(service_request.event.id,
                                                                        user.organization.name,
                                                                        service_request.request_type.name,
                                                                        user.email,
                                                                        service_request_comments)
                if settings.ENVIRONMENT not in ['production', 'test']:
                    event.service_request_email = service_request_email.__dict__

        return event

    # on update, any submitted nested objects (new_organizations, new_comments, new_event_locations) will be ignored
    def update(self, instance, validated_data):
        new_complete = validated_data.get('complete', None)
        quality_check = validated_data.get('quality_check', None)

        # if event is complete only a few things are permitted (admin can set quality_check or reopen event)
        if instance.complete:
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
                message = "Complete events may only be changed by the event owner or an administrator"
                message += " if the 'complete' field is set to False in the request."
                raise serializers.ValidationError(jsonify_errors(message))

        # otherwise event is not yet complete
        if not instance.complete and new_complete:
            # only let the status be changed to 'complete=True' if
            # 1. All child locations have an end date and each location's end date is later than its start date
            # 2. For morbidity/mortality events, there must be at least one number between sick, dead, estimated_sick,
            #   and estimated_dead per species at the time of event completion.
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
                    if not location.end_date or not location.start_date or not location.end_date >= location.start_date:
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
                                if (spec.sick_count or 0) > 0 and spec.sick_count_estimated <= (
                                        spec.sick_count or 0):
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

        user = get_user(self.context, self.initial_data)
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
            for user_id in add_read_users:
                EventReadUser.objects.create(user=user_id, event=instance, created_by=user, modified_by=user)

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
            for user_id in add_write_users:
                EventWriteUser.objects.create(user=user_id, event=instance, created_by=user, modified_by=user)

        # update the Event object
        instance.event_type = validated_data.get('event_type', instance.event_type)
        instance.event_reference = validated_data.get('event_reference', instance.event_reference)
        instance.complete = validated_data.get('complete', instance.complete)
        instance.staff = validated_data.get('staff', instance.staff)
        instance.event_status = validated_data.get('event_status', instance.event_status)
        instance.quality_check = validated_data.get('quality_check', instance.quality_check)
        instance.legal_status = validated_data.get('legal_status', instance.legal_status)
        instance.legal_number = validated_data.get('legal_number', instance.legal_number)
        instance.public = validated_data.get('public', instance.public)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

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

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string',
                  'legal_status', 'legal_status_string', 'legal_number', 'quality_check', 'public',
                  'read_collaborators', 'write_collaborators', 'eventgroups', 'organizations', 'contacts', 'comments',
                  'new_read_collaborators', 'new_write_collaborators','new_event_diagnoses', 'new_organizations',
                  'new_comments', 'new_event_locations', 'new_eventgroups', 'new_service_request', 'created_date',
                  'created_by', 'created_by_string', 'modified_date', 'modified_by', 'modified_by_string',
                  'service_request_email', 'permissions', 'permission_source',)


class EventEventGroupPublicSerializer(serializers.ModelSerializer):

    def validate(self, data):

        message_complete = "EventEventGroup for a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."

        # TODO: determine if this is true
        # if this is a new EventEventGroup check if the Event is complete
        if not self.instance and 'FULL_EVENT_CHAIN_CREATE' not in self.initial_data and data['event'].complete:
            raise serializers.ValidationError(message_complete)

        # else this is an existing EventEventGroup, check if parent Event is complete
        elif self.instance and self.instance.event.complete:
            raise serializers.ValidationError(message_complete)

        return data

    class Meta:
        model = EventEventGroup
        fields = ('id', 'event', 'eventgroup',)


class EventEventGroupSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        # TODO: determine if this is true
        if data['event'].complete:
            message = "EventEventGroup for a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        return data

    class Meta:
        model = EventEventGroup
        fields = ('id', 'event', 'eventgroup', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class EventGroupPublicSerializer(serializers.ModelSerializer):
    events = serializers.SerializerMethodField()

    def get_events(self, obj):
        return list(Event.objects.filter(public=True, eventgroups=obj.id).values_list('id', flat=True))

    class Meta:
        model = EventGroup
        fields = ('id', 'name', 'events',)


class EventGroupSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    comments = CommentSerializer(many=True, read_only=True)
    new_comment = serializers.CharField(write_only=True, required=True, allow_blank=False)
    new_events = serializers.ListField(write_only=True, required=True)

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

    class Meta:
        model = EventGroup
        fields = ('id', 'name', 'category', 'comments', 'events', "new_events", 'new_comment',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


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


class EventOrganizationPublicSerializer(serializers.ModelSerializer):

    class Meta:
        model = EventOrganization
        fields = ('event', 'organization',)


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
        event_organization.save()

        return event_organization

    def update(self, instance, validated_data):
        user = get_user(self.context, self.initial_data)

        instance.organization = validated_data.get('organization', instance.organization)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

        # calculate the priority value:
        instance.priority = calculate_priority_event_organization(instance)
        instance.save()

        return instance

    class Meta:
        model = EventOrganization
        fields = ('id', 'event', 'organization', 'priority',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


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


class EventLocationPublicSerializer(serializers.ModelSerializer):
    administrative_level_two_string = serializers.StringRelatedField(source='administrative_level_two')
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')
    country_string = serializers.StringRelatedField(source='country')

    class Meta:
        model = EventLocation
        fields = ('start_date', 'end_date', 'country', 'country_string', 'administrative_level_one',
                  'administrative_level_one_string', 'administrative_level_two', 'administrative_level_two_string',
                  'county_multiple', 'county_unknown', 'flyways',)


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
        geonames_params.update({'maxRows': 1, 'username': GEONAMES_USERNAME})
        gr = requests.get(GEONAMES_API + geonames_endpoint, params=geonames_params)
        grj = gr.json()
        if gn in grj and len(grj[gn]) > 0 and lng in grj[gn][0] and lat in grj[gn][0]:
            coords = {lng: grj[gn][0][lng], lat: grj[gn][0][lat]}
        return coords

    # find the centroid coordinates (lng/lat) for a county or equivalent
    def search_geonames_adm2(self, adm2_name, adm1_name, adm1_code, country_code):
        geonames_endpoint = 'searchJSON'
        gn = 'geonames'
        lng = 'lng'
        lat = 'lat'
        geonames_params = {'name': adm2_name, 'featureCode': 'ADM2'}
        geonames_params.update({'adminCode1': adm1_code, 'country': country_code})
        geonames_params.update({'maxRows': 1, 'username': GEONAMES_USERNAME})
        gr = requests.get(GEONAMES_API + geonames_endpoint, params=geonames_params)
        grj = gr.json()
        if gn in grj and len(grj[gn]) > 0 and lng in grj[gn][0] and lat in grj[gn][0]:
            coords = {lng: grj[gn][0][lng], lat: grj[gn][0][lat]}
        else:
            # adm2 search failed so look up the adm1 coordinates as a fallback
            coords = self.search_geonames_adm1(adm1_name, country_code)
        return coords

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
                latlng_matches_county = True
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
                if confirm_geonames_api_responsive(geonames_endpoint):
                    if ('latitude' in data and data['latitude'] is not None
                            and 'longitude' in data and data['longitude'] is not None):
                        payload = {'lat': data['latitude'], 'lng': data['longitude'], 'username': GEONAMES_USERNAME}
                        r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                        content = decode_json(r)
                        if 'address' not in content and 'geonames' not in content:
                            latlng_is_valid = False
                    if (latlng_is_valid and 'latitude' in data and data['latitude'] is not None
                            and 'longitude' in data and data['longitude'] is not None
                            and 'country' in data and data['country'] is not None):
                        payload = {'lat': data['latitude'], 'lng': data['longitude'], 'username': GEONAMES_USERNAME}
                        r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                        geonames_object_list = decode_json(r)
                        if 'address' in geonames_object_list:
                            address = geonames_object_list['address']
                            if 'name' in address:
                                address['adminName2'] = address['name']
                        elif 'geonames' in geonames_object_list:
                            gn_adm2 = [data for data in geonames_object_list['geonames'] if data['fcode'] == 'ADM2']
                            address = gn_adm2[0]
                        else:
                            # the response from the Geonames web service is in an unexpected format
                            address = None
                        geonames_endpoint = 'countryInfoJSON'
                        if address and confirm_geonames_api_responsive(geonames_endpoint):
                            country_code = address['countryCode']
                            country = None
                            if len(country_code) == 2:
                                payload = {'country': country_code, 'username': GEONAMES_USERNAME}
                                r = requests.get(GEONAMES_API + geonames_endpoint, params=payload,
                                                 verify=settings.SSL_CERT)
                                content = decode_json(r)
                                if ('geonames' in content and content['geonames'] is not None
                                        and len(content['geonames']) > 0 and 'isoAlpha3' in content['geonames'][0]):
                                    alpha3 = content['geonames'][0]['isoAlpha3']
                                    country = Country.objects.filter(abbreviation=alpha3).first()
                            else:
                                country = Country.objects.filter(abbreviation=country_code).first()
                            # TODO: create separate case for when no country found
                            if not country or data['country'].id != country.id:
                                latlng_matches_county = False
                            # TODO: check submitted admin L1 and L2 against lat/lng, not just ids
                            elif ('administrative_level_one' in data
                                  and data['administrative_level_one'] is not None):
                                admin_l1 = AdministrativeLevelOne.objects.filter(name=address['adminName1']).first()
                                if data['administrative_level_one'].id != admin_l1.id:
                                    latlng_matches_admin_l1 = False
                                elif ('administrative_level_two' in data
                                      and data['administrative_level_two'] is not None):
                                    admin2 = address['adminName2'] if 'adminName2' in address else address['name']
                                    admin_l2 = AdministrativeLevelTwo.objects.filter(name=admin2).first()
                                    if data['administrative_level_two'].id != admin_l2.id:
                                        latlng_matches_admin_21 = False
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
                if not latlng_matches_county:
                    message = "latitude and longitude are not in the user-specified country."
                    details.append(message)
                if not latlng_matches_admin_l1:
                    message = "latitude and longitude are not in the user-specified administrative level one."
                    details.append(message)
                if not latlng_matches_admin_21:
                    message = "latitude and longitude are not in the user-specified administrative level two."
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
        geonames_endpoint = 'extendedFindNearbyJSON'
        if confirm_geonames_api_responsive(geonames_endpoint):
            if ('country' not in validated_data or validated_data['country'] is None
                    or 'administrative_level_one' not in validated_data
                    or validated_data['administrative_level_one'] is None
                    or 'administrative_level_two' not in validated_data
                    or validated_data['administrative_level_two'] is None):
                payload = {'lat': validated_data['latitude'], 'lng': validated_data['longitude'],
                           'username': GEONAMES_USERNAME}
                r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                geonames_object_list = decode_json(r)
                if 'address' in geonames_object_list:
                    address = geonames_object_list['address']
                    address['adminName2'] = address['name']
                elif 'geonames' in geonames_object_list:
                    gn_adm2 = [item for item in geonames_object_list['geonames'] if item['fcode'] == 'ADM2']
                    address = gn_adm2[0]
                else:
                    # the response from the Geonames web service is in an unexpected format
                    address = None
                geonames_endpoint = 'countryInfoJSON'
                if address and confirm_geonames_api_responsive(geonames_endpoint):
                    if 'country' not in validated_data or validated_data['country'] is None:
                        country_code = address['countryCode']
                        if len(country_code) == 2:
                            payload = {'country': country_code, 'username': GEONAMES_USERNAME}
                            r = requests.get(GEONAMES_API + geonames_endpoint, params=payload, verify=settings.SSL_CERT)
                            content = decode_json(r)
                            if ('geonames' in content and content['geonames'] is not None
                                    and len(content['geonames']) > 0 and 'isoAlpha3' in content['geonames'][0]):
                                alpha3 = content['geonames'][0]['isoAlpha3']
                                validated_data['country'] = Country.objects.filter(abbreviation=alpha3).first()
                        else:
                            validated_data['country'] = Country.objects.filter(abbreviation=country_code).first()
                    if ('administrative_level_one' not in validated_data
                            or validated_data['administrative_level_one'] is None):
                        validated_data['administrative_level_one'] = AdministrativeLevelOne.objects.filter(
                            name=address['adminName1']).first()
                    if ('administrative_level_two' not in validated_data
                            or validated_data['administrative_level_two'] is None):
                        admin2 = address['adminName2'] if 'adminName2' in address else address['name']
                        validated_data['administrative_level_two'] = AdministrativeLevelTwo.objects.filter(
                            name=admin2).first()

        # auto-assign flyway for locations in the USA (exclude territories and minor outlying islands)
        # but first test the FWS flyway web service to confirm it is working
        test_params = {'geometryType': 'esriGeometryPoint', 'returnGeometry': 'false'}
        test_params.update({'outFields': 'NAME', 'f': 'json', 'spatialRel': 'esriSpatialRelIntersects'})
        test_params.update({'geometry': '-90.0,45.0'})
        r = requests.get(FLYWAYS_API, params=test_params, verify=settings.SSL_CERT)
        fws_flyway_service_responsive = True if 'features' in r.json() else False
        if fws_flyway_service_responsive:
            territories = ['PR', 'VI', 'MP', 'AS', 'UM', 'NOPO', 'SOPO']
            country = validated_data['country']
            admin_l1 = validated_data['administrative_level_one']
            admin_l2 = validated_data['administrative_level_two']
            if (country.id == Country.objects.filter(abbreviation='USA').first().id
                    and admin_l1.abbreviation not in territories):
                geonames_endpoint = 'searchJSON'
                params = {'geometryType': 'esriGeometryPoint', 'returnGeometry': 'false',
                          'outFields': 'NAME', 'f': 'json', 'spatialRel': 'esriSpatialRelIntersects'}
                # if lat/lng is present, use it to get the intersecting flyway
                if ('latitude' in validated_data and validated_data['latitude'] is not None
                        and 'longitude' in validated_data and validated_data['longitude'] is not None):
                    geom = str(validated_data['longitude']) + ',' + str(validated_data['latitude'])
                    params.update({'geometry': geom})
                # otherwise if county is present, look up the county centroid and use it to get the intersecting flyway
                elif admin_l2 and confirm_geonames_api_responsive(geonames_endpoint):
                    coords = self.search_geonames_adm2(
                        admin_l2.name, admin_l1.name, admin_l1.abbreviation, country.abbreviation)
                    if coords:
                        params.update({'geometry': coords['lng'] + ',' + coords['lat']})
                # MT, WY, CO, and NM straddle two flyways, and without lat/lng or county info, flyway
                # cannot be determined, otherwise look up the state centroid, then use it to get the intersecting flyway
                elif (admin_l1.abbreviation not in ['MT', 'WY', 'CO', 'NM', 'HI']
                      and confirm_geonames_api_responsive(geonames_endpoint)):
                    coords = self.search_geonames_adm1(admin_l1.name, country.abbreviation)
                    if coords:
                        params.update({'geometry': coords['lng'] + ',' + coords['lat']})
                # HI is not in a flyway, so assign it to Pacific ("Include all of Hawaii in with Pacific Americas")
                elif admin_l1.abbreviation == 'HI':
                    flyway = Flyway.objects.filter(name__contains='Pacific').first()

                if flyway is None and 'geometry' in params:
                    r = requests.get(FLYWAYS_API, params=params, verify=settings.SSL_CERT)
                    rj = r.json()
                    if 'features' in rj and len(rj['features']) > 0:
                        flyway_name = rj['features'][0]['attributes']['NAME'].replace(' Flyway', '')
                        flyway = Flyway.objects.filter(name__contains=flyway_name).first()

        # create the event_location and return object for use in event_location_contacts object
        evt_location = EventLocation.objects.create(**validated_data)

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

        user = get_user(self.context, self.initial_data)

        if flyway is not None:
            EventLocationFlyway.objects.create(event_location=evt_location, flyway=flyway,
                                               created_by=user, modified_by=user)

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
        evt_location.save()

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

        # calculate the priority value:
        instance.priority = calculate_priority_event_location(instance)
        instance.save()

        return instance

    class Meta:
        model = EventLocation
        fields = ('id', 'name', 'event', 'start_date', 'end_date', 'country', 'country_string',
                  'administrative_level_one', 'administrative_level_one_string', 'administrative_level_two',
                  'administrative_level_two_string', 'county_multiple', 'county_unknown', 'latitude', 'longitude',
                  'priority', 'land_ownership', 'flyways', 'contacts', 'gnis_name', 'gnis_id', 'comments',
                  'site_description', 'history', 'environmental_factors', 'clinical_signs', 'comment',
                  'new_location_contacts', 'new_location_species', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)
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


# TODO: implement check that flyway instersects location?
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


class LocationSpeciesPublicSerializer(serializers.ModelSerializer):

    class Meta:
        model = LocationSpecies
        fields = ('species', 'population_count', 'sick_count', 'dead_count', 'sick_count_estimated',
                  'dead_count_estimated', 'captive', 'age_bias', 'sex_bias',)


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
                        and not data['sick_count_estimated'] > data['sick_count']):
                    est_sick_is_valid = False
                if ('dead_count_estimated' in data and data['dead_count_estimated'] is not None
                        and 'dead_count' in data and data['dead_count'] is not None
                        and not data['dead_count_estimated'] > data['dead_count']):
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

                if self.instance.population_count:
                    dead_count = 0
                    sick_count = 0
                    if self.instance.dead_count_estimated or self.instance.dead_count:
                        dead_count = max(self.instance.dead_count_estimated or 0, self.instance.dead_count or 0)
                    if self.instance.sick_count_estimated or self.instance.sick_count:
                        sick_count = max(self.instance.sick_count_estimated or 0, self.instance.sick_count or 0)
                    if self.instance.population_count < dead_count + sick_count:
                        pop_is_valid = False

                if (self.instance.sick_count_estimated and self.instance.sick_count
                        and not self.instance.sick_count_estimated > self.instance.sick_count):
                    est_sick_is_valid = False
                if (self.instance.dead_count_estimated and self.instance.dead_count
                        and not self.instance.dead_count_estimated > self.instance.dead_count):
                    est_dead_is_valid = False
                mm = EventType.objects.filter(name='Mortality/Morbidity').first()
                mm_locspecs = None
                if self.instance.event_location.event.event_type.id == mm.id:
                    locspecs = LocationSpecies.objects.filter(event_location=self.instance.event_location.id)
                    mm_locspecs = [locspec for locspec in locspecs if
                                   locspec.event_location.event.event_type.id == mm.id]
                    if mm_locspecs is None:
                        if self.instance.dead_count_estimated and self.instance.dead_count_estimated > 0:
                            min_species_count = True
                        elif self.instance.dead_count and self.instance.dead_count > 0:
                            min_species_count = True
                        elif self.instance.sick_count_estimated and self.instance.sick_count_estimated > 0:
                            min_species_count = True
                        elif self.instance.sick_count and self.instance.sick_count > 0:
                            min_species_count = True

                if not pop_is_valid:
                    message = "New location_species population_count cannot be less than the sum of dead_count"
                    message += " and sick_count (where those counts are the maximum of the estimated or known count)."
                    details.append(message)
                if (self.instance.event_location.event.event_type.id == mm.id
                        and mm_locspecs is None and not min_species_count):
                    message = "For Mortality/Morbidity events,"
                    message += " at least one new_location_species requires at least one species"
                    message += " count in any of the following fields:"
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
        location_species.save()

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

        # calculate the priority value:
        instance.priority = calculate_priority_location_species(instance)
        instance.save()

        return instance

    class Meta:
        model = LocationSpecies
        fields = ('id', 'event_location', 'species', 'population_count', 'sick_count', 'dead_count',
                  'sick_count_estimated', 'dead_count_estimated', 'priority', 'captive', 'age_bias', 'sex_bias',
                  'new_species_diagnoses', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


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


class EventDiagnosisPublicSerializer(serializers.ModelSerializer):
    diagnosis_type = serializers.PrimaryKeyRelatedField(source='diagnosis.diagnosis_type', read_only=True)
    diagnosis_type_string = serializers.StringRelatedField(source='diagnosis.diagnosis_type')

    class Meta:
        model = EventDiagnosis
        fields = ('diagnosis', 'diagnosis_string', 'diagnosis_type', 'diagnosis_type_string', 'suspect', 'major',)


class EventDiagnosisSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    diagnosis_type = serializers.PrimaryKeyRelatedField(source='diagnosis.diagnosis_type', read_only=True)
    diagnosis_type_string = serializers.StringRelatedField(source='diagnosis.diagnosis_type')

    def validate(self, data):

        message_complete = "Diagnosis from a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."
        eventdiags = EventDiagnosis.objects.filter(event=data['event'].id)
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
        event_diagnosis.save()

        # Now that we have the new event diagnoses created,
        # check for existing Pending record and delete it
        event_diagnoses = EventDiagnosis.objects.filter(event=event_diagnosis.event.id)
        [diag.delete() for diag in event_diagnoses if diag.diagnosis.name == 'Pending']

        # If the parent event is complete, also check for existing Undetermined record and delete it
        if event_diagnosis.event.complete:
            [diag.delete() for diag in event_diagnoses if diag.diagnosis.name == 'Undetermined']

        # calculate the priority value:
        event_diagnosis.priority = calculate_priority_event_diagnosis(event_diagnosis)
        event_diagnosis.save()

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

        # calculate the priority value:
        instance.priority = calculate_priority_event_diagnosis(instance)
        instance.save()

        return instance

    class Meta:
        model = EventDiagnosis
        fields = ('id', 'event', 'diagnosis', 'diagnosis_string', 'diagnosis_type', 'diagnosis_type_string',
                  'suspect', 'major', 'priority', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class SpeciesDiagnosisPublicSerializer(serializers.ModelSerializer):

    class Meta:
        model = SpeciesDiagnosis
        fields = ('diagnosis', 'diagnosis_string', 'suspect', 'tested_count', 'diagnosis_count', 'positive_count',
                  'suspect_count', 'pooled',)


class SpeciesDiagnosisSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    new_species_diagnosis_organizations = serializers.ListField(write_only=True, required=False)
    basis_string = serializers.StringRelatedField(source='basis')

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
        species_diagnosis.save()

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
        instance.save()

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

    class Meta:
        model = SpeciesDiagnosis
        fields = ('id', 'location_species', 'diagnosis', 'diagnosis_string', 'cause', 'cause_string', 'basis',
                  'basis_string', 'suspect', 'priority', 'tested_count', 'diagnosis_count', 'positive_count',
                  'suspect_count', 'pooled', 'organizations', 'new_species_diagnosis_organizations',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)
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
    # comments = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True, read_only=True)
    new_comments = serializers.ListField(write_only=True, required=False)
    service_request_email = serializers.JSONField(read_only=True)

    # def get_comments(self, obj):
    #     content_type = ContentType.objects.get_for_model(self.Meta.model)
    #     comments = Comment.objects.filter(object_id=obj.id, content_type=content_type)
    #     comments_comments = [comment.comment for comment in comments]
    #     return comments_comments

    def validate(self, data):
        if 'new_comments' in data and data['new_comments'] is not None:
            for item in data['new_comments']:
                if 'comment' not in item or not item['comment']:
                    raise serializers.ValidationError("A comment must have comment text.")
                elif 'comment_type' not in item or not item['comment_type']:
                    raise serializers.ValidationError("A comment must have a comment type.")

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
        service_request_comments = []

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
                    service_request_comments.append(comment['comment'])

        # construct and send the request email
        service_request_email = construct_service_request_email(service_request.event.id,
                                                                user.organization.name,
                                                                service_request.request_type.name, user.email,
                                                                service_request_comments)
        if settings.ENVIRONMENT not in ['production', 'test']:
            service_request.service_request_email = vars(service_request_email)

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
#  Users
#
######


class UserPublicSerializer(serializers.ModelSerializer):
    organization_string = serializers.StringRelatedField(source='organization')

    class Meta:
        model = User
        fields = ('id', 'username', 'first_name', 'last_name', 'email', 'organization', 'organization_string',)


# Password must be at least 12 characters long.
# Password cannot contain your username.
# Password cannot have been used in previous 20 passwords.
# Password cannot have been changed less than 24 hours ago.
# Password must satisfy 3 out of the following requirements:
# Contain lowercase letters (a, b, c, ..., z)
# Contain uppercase letters (A, B, C, ..., Z)
# Contain numbers (0, 1, 2, ..., 9)
# Contain symbols (~, !, @, #, etc.)
# TODO: better protect this endpoint: anon and partner users can create a user but should only be able to submit 'username', 'password', 'first_name', 'last_name', 'email', others auto-assigned, admins can submit all except is_superuser
class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, allow_blank=True, required=False)
    organization_string = serializers.StringRelatedField(source='organization')
    message = serializers.CharField(write_only=True, allow_blank=True, required=False)
    user_email = serializers.JSONField(read_only=True)

    def validate(self, data):

        if self.context['request'].method == 'POST':
            if 'role' not in data or ('role' in data and data['role'] is None):
                data['role'] = Role.objects.filter(name='Public').first()
            if 'organization' not in data or ('organization' in data and data['organization'] is None):
                data['organization'] = Organization.objects.filter(name='Public').first()
            if 'password' not in data:
                raise serializers.ValidationError("password is required")
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
            if any(character.isdigit() for character in password):
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

        password = validated_data.pop('password', None)
        message = validated_data.pop('message', None)

        # non-admins (not SuperAdmin, Admin, or even PartnerAdmin) cannot create any kind of user other than public
        if (not requesting_user.is_authenticated or requesting_user.role.is_public or requesting_user.role.is_affiliate
                or requesting_user.role.is_partner or requesting_user.role.is_partnermanager):
            requested_org = validated_data.pop('organization')
            requested_role = validated_data.pop('role')
            validated_data['role'] = Role.objects.filter(name='Public').first()
            validated_data['organization'] = Organization.objects.filter(name='Public').first()
            original_message = message
            message = "Please change the role for this user to:" + requested_role.name + "\r\n"
            message += "Please change the organization for this user to:" + requested_org.name + "\r\n"
            message += "\r\n" + original_message

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

        # only SuperAdmins and Admins can edit is_superuser, is_staff, and is_active fields
        if (requesting_user.is_authenticated
                and not (requesting_user.role.is_superadmin or requesting_user.role.is_admin)):
            validated_data['is_superuser'] = False
            validated_data['is_staff'] = False
            validated_data['is_active'] = True

        user = User.objects.create(**validated_data)
        requesting_user = user if not requesting_user.is_authenticated else requesting_user

        user.set_password(password)
        user.save()

        if message is not None:
            user_email = construct_user_request_email(user.email, message)
            if settings.ENVIRONMENT not in ['production', 'test']:
                user.user_email = user_email.__dict__

        return user

    def update(self, instance, validated_data):
        requesting_user = get_user(self.context, self.initial_data)

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
            instance.username = validated_data.get('username', instance.username)
            instance.email = validated_data.get('email', instance.email)

            if requesting_user.role.is_partneradmin:
                if validated_data['role'].name in ['SuperAdmin', 'Admin']:
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

        instance.modified_by = requesting_user

        new_password = validated_data.get('password', None)
        if new_password is not None:
            instance.set_password(new_password)
        instance.save()

        return instance

    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'first_name', 'last_name', 'email', 'is_superuser', 'is_staff',
                  'is_active', 'role', 'organization', 'organization_string', 'circles', 'last_login', 'active_key',
                  'user_status', 'message', 'user_email')


class RoleSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = Role
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class CircleSerlializer(serializers.ModelSerializer):
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


class OrganizationPublicSerializer(serializers.ModelSerializer):

    class Meta:
        model = Organization
        fields = ('id', 'name', 'address_one', 'address_two', 'city', 'postal_code', 'administrative_level_one',
                  'country', 'phone', 'parent_organization', 'laboratory',)


class OrganizationSerializer(serializers.ModelSerializer):

    class Meta:
        model = Organization
        fields = ('id', 'name', 'private_name', 'address_one', 'address_two', 'city', 'postal_code',
                  'administrative_level_one', 'country', 'phone', 'parent_organization', 'laboratory',)


class OrganizationAdminSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = Organization
        fields = ('id', 'name', 'private_name', 'address_one', 'address_two', 'city', 'postal_code',
                  'administrative_level_one', 'country', 'phone', 'parent_organization', 'do_not_publish', 'laboratory',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class OrganizationPublicSlimSerializer(serializers.ModelSerializer):

    class Meta:
        model = Organization
        fields = ('id', 'name', 'laboratory',)


class OrganizationSlimSerializer(serializers.ModelSerializer):

    class Meta:
        model = Organization
        fields = ('id', 'name', 'private_name', 'laboratory',)


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


class SearchPublicSerializer(serializers.ModelSerializer):
    use_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Search
        fields = ('data', 'use_count',)


class SearchSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()

    def get_permission_source(self, obj):
        return determine_permission_source(self.context['request'].user, obj)

    def create(self, validated_data):
        user = get_user(self.context, self.initial_data)

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

    class Meta:
        model = Search
        fields = ('id', 'name', 'data', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string', 'permissions', 'permission_source',)
        extra_kwargs = {'count': {'read_only': True}}


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


# TODO: Make these three EventSummary serializers adhere to DRY Principle
class EventSummaryPublicSerializer(serializers.ModelSerializer):

    # diagnosis = Diagnosis.objects.get(pk=obj.diagnosis.id).name if obj.diagnosis else None
    # if diagnosis:
    #     diagnosis = diagnosis + " suspect" if obj.suspect else diagnosis
    # return diagnosis

    def get_eventdiagnoses(self, obj):
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
                altered_event_diagnosis = {"id": event_diagnosis.id, "event": event_diagnosis.event.id,
                                           "diagnosis": diag_id, "diagnosis_string": diag_name,
                                           "diagnosis_type": diag_type_id, "diagnosis_type_string": diag_type_name,
                                           "suspect": event_diagnosis.suspect, "major": event_diagnosis.major,
                                           "priority": event_diagnosis.priority}
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

    # eventdiagnoses = EventDiagnosisSerializer(many=True)
    eventdiagnoses = serializers.SerializerMethodField()
    administrativelevelones = serializers.SerializerMethodField()
    administrativeleveltwos = serializers.SerializerMethodField()
    flyways = serializers.SerializerMethodField()
    species = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    event_status_string = serializers.StringRelatedField(source='event_status')
    organizations = OrganizationSerializer(many=True)
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ('id', 'affected_count', 'start_date', 'end_date', 'complete', 'event_type', 'event_type_string',
                  'event_status', 'event_status_string', 'eventdiagnoses', 'administrativelevelones',
                  'administrativeleveltwos', 'flyways', 'species', 'organizations', 'permissions', 'permission_source',)


class EventSummarySerializer(serializers.ModelSerializer):

    def get_eventdiagnoses(self, obj):
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

    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    # eventdiagnoses = EventDiagnosisSerializer(many=True)
    eventdiagnoses = serializers.SerializerMethodField()
    administrativelevelones = serializers.SerializerMethodField()
    administrativeleveltwos = serializers.SerializerMethodField()
    flyways = serializers.SerializerMethodField()
    species = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    event_status_string = serializers.StringRelatedField(source='event_status')
    organizations = OrganizationSerializer(many=True)
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ('id', 'event_reference', 'affected_count', 'start_date', 'end_date', 'complete', 'event_type',
                  'event_type_string', 'event_status', 'event_status_string', 'public', 'eventdiagnoses',
                  'administrativelevelones', 'administrativeleveltwos', 'flyways', 'species', 'created_date',
                  'created_by', 'created_by_string', 'modified_date', 'modified_by', 'modified_by_string',
                  'organizations', 'permissions', 'permission_source',)


class EventSummaryAdminSerializer(serializers.ModelSerializer):

    def get_eventdiagnoses(self, obj):
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

    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    # eventdiagnoses = EventDiagnosisSerializer(many=True)
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

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string', 'legal_status',
                  'legal_status_string', 'legal_number', 'quality_check', 'public', 'eventgroups', 'organizations',
                  'contacts', 'eventdiagnoses', 'administrativelevelones', 'administrativeleveltwos', 'flyways',
                  'species', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string', 'permissions', 'permission_source',)


class SpeciesDiagnosisDetailPublicSerializer(serializers.ModelSerializer):
    organizations_string = serializers.StringRelatedField(many=True, source='organizations')

    class Meta:
        model = SpeciesDiagnosis
        fields = ('diagnosis', 'diagnosis_string', 'suspect', 'tested_count', 'diagnosis_count', 'positive_count',
                  'suspect_count', 'pooled', 'organizations', 'organizations_string')


class SpeciesDiagnosisDetailSerializer(serializers.ModelSerializer):
    organizations_string = serializers.StringRelatedField(many=True, source='organizations')
    basis_string = serializers.StringRelatedField(source='basis')

    class Meta:
        model = SpeciesDiagnosis
        fields = ('id', 'location_species', 'diagnosis', 'diagnosis_string', 'cause', 'cause_string', 'basis',
                  'basis_string', 'suspect', 'priority', 'tested_count', 'diagnosis_count', 'positive_count',
                  'suspect_count', 'pooled', 'organizations', 'organizations_string',)


class LocationSpeciesDetailPublicSerializer(serializers.ModelSerializer):
    species_string = serializers.StringRelatedField(source='species')
    speciesdiagnoses = SpeciesDiagnosisDetailPublicSerializer(many=True)

    class Meta:
        model = LocationSpecies
        fields = ('species', 'species_string', 'population_count', 'sick_count', 'dead_count', 'sick_count_estimated',
                  'dead_count_estimated', 'captive', 'age_bias', 'sex_bias', 'speciesdiagnoses',)


class LocationSpeciesDetailSerializer(serializers.ModelSerializer):
    species_string = serializers.StringRelatedField(source='species')
    speciesdiagnoses = SpeciesDiagnosisDetailSerializer(many=True)

    class Meta:
        model = LocationSpecies
        fields = ('id', 'event_location', 'species', 'species_string', 'population_count', 'sick_count', 'dead_count',
                  'sick_count_estimated', 'dead_count_estimated', 'priority', 'captive', 'age_bias', 'sex_bias',
                  'speciesdiagnoses',)


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


class EventLocationDetailPublicSerializer(serializers.ModelSerializer):
    administrative_level_two_string = serializers.StringRelatedField(source='administrative_level_two')
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')
    administrative_level_two_points = serializers.CharField(source='administrative_level_two.points', default='')
    country_string = serializers.StringRelatedField(source='country')
    locationspecies = LocationSpeciesDetailPublicSerializer(many=True)
    flyways = serializers.SerializerMethodField()

    def get_flyways(self, obj):
        flyway_ids = [flyway['id'] for flyway in obj.flyways.values()]
        return list(Flyway.objects.filter(id__in=flyway_ids).values('id', 'name'))

    class Meta:
        model = EventLocation
        fields = ('start_date', 'end_date', 'country', 'country_string', 'administrative_level_one',
                  'administrative_level_one_string', 'administrative_level_two', 'administrative_level_two_string',
                  'administrative_level_two_points', 'county_multiple', 'county_unknown', 'flyways', 'locationspecies')


class EventLocationDetailSerializer(serializers.ModelSerializer):
    administrative_level_two_string = serializers.StringRelatedField(source='administrative_level_two')
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')
    administrative_level_two_points = serializers.CharField(source='administrative_level_two.points', default='')
    country_string = serializers.StringRelatedField(source='country')
    locationspecies = LocationSpeciesDetailSerializer(many=True)
    comments = CommentSerializer(many=True)
    eventlocationcontacts = EventLocationContactDetailSerializer(source='eventlocationcontact_set', many=True)
    flyways = serializers.SerializerMethodField()

    def get_flyways(self, obj):
        flyway_ids = [flyway['id'] for flyway in obj.flyways.values()]
        return list(Flyway.objects.filter(id__in=flyway_ids).values('id', 'name'))

    class Meta:
        model = EventLocation
        fields = ('id', 'name', 'event', 'start_date', 'end_date', 'country', 'country_string',
                  'administrative_level_one', 'administrative_level_one_string', 'administrative_level_two',
                  'administrative_level_two_string', 'administrative_level_two_points', 'county_multiple',
                  'county_unknown', 'latitude', 'longitude', 'priority', 'land_ownership', 'gnis_name', 'gnis_id',
                  'flyways', 'eventlocationcontacts', 'locationspecies', 'comments',)


class EventDiagnosisDetailPublicSerializer(serializers.ModelSerializer):

    class Meta:
        model = EventDiagnosis
        fields = ('diagnosis', 'diagnosis_string', 'suspect', 'major',)


class EventDiagnosisDetailSerializer(serializers.ModelSerializer):

    class Meta:
        model = EventDiagnosis
        fields = ('id', 'event', 'diagnosis', 'diagnosis_string', 'suspect', 'major', 'priority',)


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


class EventDetailPublicSerializer(serializers.ModelSerializer):
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    event_status_string = serializers.StringRelatedField(source='event_status')
    eventlocations = EventLocationDetailPublicSerializer(many=True)
    eventdiagnoses = EventDiagnosisDetailPublicSerializer(many=True)
    organizations = serializers.SerializerMethodField()  # OrganizationPublicSerializer(many=True)
    eventgroups = serializers.SerializerMethodField()  # EventGroupPublicSerializer(many=True)

    def get_eventgroups(self, obj):
        pub_groups = []
        if obj.eventgroups is not None:
            evtgrp_ids = list(EventEventGroup.objects.filter(event=obj.id).values_list('eventgroup_id', flat=True))
            evtgrps = EventGroup.objects.filter(id__in=evtgrp_ids, category__name='Biologically Equivalent (Public)')
            for evtgrp in evtgrps:
                evt_ids = list(Event.objects.filter(eventgroups=evtgrp.id, public=True).values_list('id', flat=True))
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
                new_org = {'id': org.id, 'name': org.name, 'address_one': org.address_one,
                           'address_two': org.address_two, 'city': org.city, 'postal_code': org.postal_code,
                           'administrative_level_one': org.administrative_level_one.id,
                           'administrative_level_one_string': org.administrative_level_one.name,
                           'country': org.country.id, 'country_string': org.country.name, 'phone': org.phone}
                pub_orgs.append({"id": evtorg.id, "priority": evtorg.priority, "organization": new_org})
        return pub_orgs

    def get_permission_source(self, obj):
        return determine_permission_source(self.context['request'].user, obj)

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'complete', 'start_date', 'end_date', 'affected_count',
                  'event_status', 'event_status_string', 'eventgroups', 'eventdiagnoses', 'eventlocations',
                  'organizations', 'permissions', 'permission_source',)


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
    event_status_string = serializers.StringRelatedField(source='event_status')
    eventlocations = EventLocationDetailSerializer(many=True)
    # eventdiagnoses = EventDiagnosisDetailSerializer(many=True)
    eventdiagnoses = serializers.SerializerMethodField()
    combined_comments = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True)
    servicerequests = ServiceRequestDetailSerializer(many=True)
    organizations = serializers.SerializerMethodField()
    eventgroups = serializers.SerializerMethodField()  # EventGroupPublicSerializer(many=True)
    read_collaborators = UserPublicSerializer(many=True)
    write_collaborators = UserPublicSerializer(many=True)

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
        return combined_comments

    def get_eventgroups(self, obj):
        pub_groups = []
        if obj.eventgroups is not None:
            evtgrp_ids = list(EventEventGroup.objects.filter(event=obj.id).values_list('eventgroup_id', flat=True))
            evtgrps = EventGroup.objects.filter(id__in=evtgrp_ids, category__name='Biologically Equivalent (Public)')
            for evtgrp in evtgrps:
                evt_ids = list(EventEventGroup.objects.filter(eventgroup=evtgrp.id).values_list('event_id', flat=True))
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
                new_org = {'id': org.id, 'name': org.name, 'address_one': org.address_one,
                           'address_two': org.address_two, 'city': org.city, 'postal_code': org.postal_code,
                           'administrative_level_one': org.administrative_level_one.id,
                           'administrative_level_one_string': org.administrative_level_one.name,
                           'country': org.country.id, 'country_string': org.country.name, 'phone': org.phone}
                pub_orgs.append({"id": evtorg.id, "priority": evtorg.priority, "organization": new_org})
        return pub_orgs

    def get_eventdiagnoses(self, obj):
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

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'event_status', 'event_status_string', 'public', 'read_collaborators',
                  'write_collaborators', 'eventgroups', 'eventdiagnoses', 'eventlocations', 'organizations',
                  'combined_comments', 'comments', 'servicerequests', 'created_date', 'created_by', 'created_by_string',
                  'created_by_first_name', 'created_by_last_name', 'created_by_organization',
                  'created_by_organization_string', 'modified_date', 'modified_by', 'modified_by_string',
                  'permissions', 'permission_source',)


class EventDetailAdminSerializer(serializers.ModelSerializer):
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
    eventlocations = EventLocationDetailSerializer(many=True)
    # eventdiagnoses = EventDiagnosisDetailSerializer(many=True)
    eventdiagnoses = serializers.SerializerMethodField()
    combined_comments = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True)
    servicerequests = ServiceRequestDetailSerializer(many=True)
    organizations = serializers.SerializerMethodField()
    eventgroups = EventGroupSerializer(many=True)
    read_collaborators = UserPublicSerializer(many=True)
    write_collaborators = UserPublicSerializer(many=True)

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
    def get_organizations(self, obj):
        pub_orgs = []
        if obj.organizations is not None:
            orgs = obj.organizations.all()
            evtorgs = EventOrganization.objects.filter(
                event=obj.id, organization__do_not_publish=False).order_by('priority')
            for evtorg in evtorgs:
                org = [org for org in orgs if org.id == evtorg.organization.id][0]
                new_org = {'id': org.id, 'name': org.name, 'address_one': org.address_one,
                           'address_two': org.address_two, 'city': org.city, 'postal_code': org.postal_code,
                           'administrative_level_one': org.administrative_level_one.id,
                           'administrative_level_one_string': org.administrative_level_one.name,
                           'country': org.country.id, 'country_string': org.country.name, 'phone': org.phone}
                pub_orgs.append({"id": evtorg.id, "priority": evtorg.priority, "organization": new_org})
        return pub_orgs

    def get_eventdiagnoses(self, obj):
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

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string', 'legal_status',
                  'legal_status_string', 'legal_number', 'quality_check', 'public', 'read_collaborators',
                  'write_collaborators', 'eventgroups', 'eventdiagnoses', 'eventlocations', 'organizations',
                  'combined_comments', 'comments', 'servicerequests', 'created_date', 'created_by',
                  'created_by_string', 'created_by_first_name', 'created_by_last_name', 'created_by_organization',
                  'created_by_organization_string', 'modified_date', 'modified_by', 'modified_by_string',
                  'permissions', 'permission_source',)


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
