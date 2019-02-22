import re
import requests
import json
from datetime import datetime, timedelta
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.forms.models import model_to_dict
from rest_framework import serializers, validators
from whispersservices.models import *
from dry_rest_permissions.generics import DRYPermissionsField

# TODO: implement required field validations for nested objects
# TODO: consider implementing type checking for nested objects

COMMENT_CONTENT_TYPES = ['event', 'superevent', 'eventlocation', 'servicerequest']
GEONAMES_USERNAME = settings.GEONAMES_USERNAME
GEONAMES_API = 'http://api.geonames.org/'
FLYWAYS_API = 'https://services.arcgis.com/'
FLYWAYS_API += 'QVENGdaPbd4LUkLV/ArcGIS/rest/services/FWS_HQ_MB_Waterfowl_Flyway_Boundaries/FeatureServer/0/query'


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
            raise serializers.ValidationError(message)
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
            raise serializers.ValidationError(message)
    return email


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
        if self.context['request'].method == 'POST':
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
            raise serializers.ValidationError(message)
        comment = Comment.objects.create(**validated_data, content_object=content_object)
        return comment

    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

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
        user = self.context['request'].user
        if not user.is_authenticated:
            permission_source = ''
        elif user.id == obj.created_by.id:
            permission_source = 'user'
        elif user.organization.id == obj.created_by.organization.id:
            permission_source = 'organization'
        elif obj.circle_read is not None and obj.circle_write is not None and (
                user in obj.circle_read or user in obj.circle_write):
            permission_source = 'circle'
        else:
            permission_source = ''
        return permission_source

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'complete', 'start_date', 'end_date', 'affected_count',
                  'event_status', 'event_status_string', 'permissions', 'permission_source',)


# TODO: allow read-only staff field for event owner org
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
    new_superevents = serializers.ListField(write_only=True, required=False)
    new_service_request = serializers.JSONField(write_only=True, required=False)
    service_request_email = serializers.JSONField(read_only=True)

    def get_permission_source(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            permission_source = ''
        elif user.id == obj.created_by.id:
            permission_source = 'user'
        elif user.organization.id == obj.created_by.organization.id:
            permission_source = 'organization'
        elif obj.circle_read is not None and obj.circle_write is not None and (
                user in obj.circle_read or user in obj.circle_write):
            permission_source = 'circle'
        else:
            permission_source = ''
        return permission_source

    def create(self, validated_data):
        # TODO: figure out if this logic is necessary
        #  see: https://www.django-rest-framework.org/api-guide/requests/#user
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        if not user:
            raise serializers.ValidationError("User could not be identified, please contact the administrator.")

        if 'new_event_locations' not in validated_data:
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
        if 'new_event_locations' in validated_data:
            country_admin_is_valid = True
            latlng_is_valid = True
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
            for item in validated_data['new_event_locations']:
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
                    if (validated_data['event_type'].id == mortality_morbidity.id
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
                    adminl1 = AdministrativeLevelOne.objects.filter(id=item['administrative_level_one']).first()
                    if country.id != adminl1.country.id:
                        country_admin_is_valid = False
                    if 'administrative_level_two' in item and item['administrative_level_two'] is not None:
                        adminl2 = AdministrativeLevelTwo.objects.filter(id=item['administrative_level_two']).first()
                        if adminl1.id != adminl2.administrative_level_one.id:
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
                if ('latitude' in item and item['latitude'] is not None
                        and 'longitude' in item and item['longitude'] is not None
                        and ('country' not in item or 'administrative_level_one' not in item)):
                    payload = {'lat': item['latitude'], 'lng': item['longitude'],
                               'username': GEONAMES_USERNAME}
                    r = requests.get(GEONAMES_API + 'extendedFindNearbyJSON', params=payload, verify=settings.SSL_CERT)
                    if 'address' not in r.json() or 'geonames' not in r.json():
                        latlng_is_valid = False
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
                        if validated_data['event_type'].id == mortality_morbidity.id:
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
                        if Contact.objects.filter(id=loc_contact['contact']).first() is None:
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
            if validated_data['event_type'].id == mortality_morbidity.id and not min_species_count:
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
        if 'complete' in validated_data and validated_data['complete'] is True:
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
            for item in validated_data['new_event_locations']:
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
                    if validated_data['event_type'] == mortality_morbidity.id:
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

        comment_types = {'site_description': 'Site description', 'history': 'History',
                         'environmental_factors': 'Environmental factors', 'clinical_signs': 'Clinical signs',
                         'other': 'Other'}

        # pull out child event diagnoses list from the request
        new_event_diagnoses = validated_data.pop('new_event_diagnoses', None)

        # pull out child organizations list from the request
        new_organizations = validated_data.pop('new_organizations', None)

        # pull out child comments list from the request
        new_comments = validated_data.pop('new_comments', None)

        # pull out child event_locations list from the request
        new_event_locations = validated_data.pop('new_event_locations', None)

        # pull out child superevents list from the request
        new_superevents = validated_data.pop('new_superevents', None)

        # pull out child service request from the request
        new_service_request = validated_data.pop('new_service_request', None)

        event = Event.objects.create(**validated_data)

        # create the child organizations for this event
        if new_organizations is not None:
            for org_id in new_organizations:
                if org_id is not None:
                    org = Organization.objects.filter(pk=org_id).first()
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
                    comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                    Comment.objects.create(content_object=event, comment=comment['comment'], comment_type=comment_type,
                                           created_by=user, modified_by=user)

        # create the child superevents for this event
        if new_superevents is not None:
            for superevent_id in new_superevents:
                if superevent_id is not None:
                    superevent = SuperEvent.objects.filter(pk=superevent_id).first()
                    if superevent is not None:
                        EventSuperEvent.objects.create(event=event, superevent=superevent,
                                                       created_by=user, modified_by=user)

        # Create the child service requests for this event
        if new_service_request is not None:
            if ('request_type' in new_service_request and new_service_request['request_type'] is not None
                    and new_service_request['request_type'] in [1, 2]):
                new_comments = new_service_request.pop('new_comments', None)
                request_type = ServiceRequestType.objects.filter(pk=new_service_request['request_type']).first()
                service_request = ServiceRequest.objects.create(event=event, request_type=request_type,
                                                                created_by=user, modified_by=user)
                service_request_comments = []

                # create the child comments for this service request
                if new_comments is not None:
                    for comment in new_comments:
                        if comment is not None:
                            comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                            Comment.objects.create(content_object=service_request, comment=comment['comment'],
                                                   comment_type=comment_type, created_by=user, modified_by=user)
                            service_request_comments.append(comment.comment)

                # construct and send the request email
                service_request_email = construct_service_request_email(service_request.event.id,
                                                                        user.organization.name,
                                                                        service_request.request_type.name, user.email,
                                                                        service_request_comments)
                if settings.ENVIRONMENT not in ['production', 'test']:
                    event.service_request_email = service_request_email.__dict__

        # create the child event_locations for this event
        if new_event_locations is not None:
            for event_location in new_event_locations:
                if event_location is not None:
                    # use event to populate event field on event_location
                    event_location['event'] = event
                    new_location_contacts = event_location.pop('new_location_contacts', None)
                    new_location_species = event_location.pop('new_location_species', None)

                    # use id for country to get Country instance
                    event_location['country'] = Country.objects.filter(pk=event_location['country']).first()
                    # same for other things
                    event_location['administrative_level_one'] = AdministrativeLevelOne.objects.filter(
                        pk=event_location['administrative_level_one']).first()
                    event_location['administrative_level_two'] = AdministrativeLevelTwo.objects.filter(
                        pk=event_location['administrative_level_two']).first()
                    event_location['land_ownership'] = LandOwnership.objects.filter(
                        pk=event_location['land_ownership']).first()

                    flyway = None

                    # create object for comment creation while removing unserialized fields for EventLocation
                    comments = {'site_description': event_location.pop('site_description', None),
                                'history': event_location.pop('history', None),
                                'environmental_factors': event_location.pop('environmental_factors', None),
                                'clinical_signs': event_location.pop('clinical_signs', None),
                                'other': event_location.pop('comment', None)}

                    # create the event_location and return object for use in event_location_contacts object

                    # if the event_location has no name value but does have a gnis_name value,
                    # then copy the value of gnis_name to name
                    # this need only happen on creation since the two fields should maintain no durable relationship
                    if event_location['name'] == '' and event_location['gnis_name'] != '':
                        event_location['name'] = event_location['gnis_name']

                    # if event_location has lat/lng but no country/adminlevelone/adminleveltwo, populate missing fields
                    if ('country' not in event_location or event_location['country'] is None
                            or 'administrative_level_one' not in event_location
                            or event_location['administrative_level_one'] is None
                            or 'administrative_level_two' not in event_location
                            or event_location['administrative_level_two'] is None):
                        payload = {'lat': event_location['latitude'], 'lng': event_location['longitude'],
                                   'username': GEONAMES_USERNAME}
                        r = requests.get(GEONAMES_API + 'extendedFindNearbyJSON', params=payload, verify=settings.SSL_CERT)
                        geonames_object_list = r.json()
                        if 'address' in geonames_object_list:
                            address = geonames_object_list['address']
                            address['adminName2'] = address['name']
                        else:
                            geonames_objects_adm2 = [item for item in geonames_object_list['geonames'] if
                                                     item['fcode'] == 'ADM2']
                            address = geonames_objects_adm2[0]
                        if 'country' not in event_location or event_location['country'] is None:
                            country_code = address['countryCode']
                            if len(country_code) == 2:
                                payload = {'country': country_code, 'username': GEONAMES_USERNAME}
                                r = requests.get(GEONAMES_API + 'countryInfoJSON', params=payload, verify=settings.SSL_CERT)
                                alpha3 = r.json()['geonames'][0]['isoAlpha3']
                                event_location['country'] = Country.objects.filter(abbreviation=alpha3).first()
                            else:
                                event_location['country'] = Country.objects.filter(abbreviation=country_code).first()
                        if ('administrative_level_one' not in event_location
                                or event_location['administrative_level_one'] is None):
                            event_location['administrative_level_one'] = AdministrativeLevelOne.objects.filter(
                                name=address['adminName1']).first()
                        if ('administrative_level_two' not in event_location
                                or event_location['administrative_level_two'] is None):
                            admin2 = address['adminName2'] if 'adminName2' in address else address['name']
                            event_location['administrative_level_two'] = AdministrativeLevelTwo.objects.filter(
                                name=admin2).first()

                    # auto-assign flyway for locations in the USA
                    if event_location['country'].id == Country.objects.filter(abbreviation='USA').first().id:
                        payload = {'geometryType': 'esriGeometryPoint', 'returnGeometry': 'false', 'outFields': 'NAME',
                                   'f': 'json'}
                        payload.update({'spatialRel': 'esriSpatialRelIntersects'})
                        # if lat/lng is present, use it to get the intersecting flyway
                        if ('latitude' in event_location and event_location['latitude'] is not None
                                and 'longitude' in event_location and event_location['longitude'] is not None):
                            payload.update({'geometry': event_location['longitude'] + ',' + event_location['latitude']})
                        # otherwise if county is present, look up the county centroid,
                        # then use it to get the intersecting flyway
                        elif event_location['administrative_level_two']:
                            geonames_payload = {'name': event_location['administrative_level_two'].name,
                                                'featureCode': 'ADM2',
                                                'maxRows': 1, 'username': GEONAMES_USERNAME}
                            gr = requests.get(GEONAMES_API + 'searchJSON', params=geonames_payload)
                            payload.update(
                                {'geometry': gr.json()['geonames'][0]['lng'] + ',' + gr.json()['geonames'][0]['lat']})
                        # MT, WY, CO, and NM straddle two flyways,
                        # and without lat/lng or county info, flyway cannot be determined
                        # otherwise look up the state centroid, then use it to get the intersecting flyway
                        elif event_location['administrative_level_one'].abbreviation not in ['MT', 'WY', 'CO', 'NM',
                                                                                             'HI']:
                            geonames_payload = {'adminCode1': event_location['administrative_level_one'], 'maxRows': 1,
                                                'username': GEONAMES_USERNAME}
                            gr = requests.get(GEONAMES_API + 'searchJSON', params=geonames_payload)
                            payload.update(
                                {'geometry': gr.json()['geonames'][0]['lng'] + ',' + gr.json()['geonames'][0]['lat']})
                        # HI is not in a flyway, assign it to Pacific ("Include all of Hawaii in with Pacific Americas")
                        elif event_location['administrative_level_one'].abbreviation == 'HI':
                            flyway = Flyway.objects.filter(name__contains='Pacific').first()

                        if flyway is None and 'geometry' in payload:
                            r = requests.get(FLYWAYS_API, params=payload, verify=settings.SSL_CERT)
                            flyway_name = r.json()['features'][0]['attributes']['NAME'].replace(' Flyway', '')
                            flyway = Flyway.objects.filter(name__contains=flyway_name).first()

                    evt_location = EventLocation.objects.create(created_by=user, modified_by=user, **event_location)

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
                            location_contact['contact'] = Contact.objects.filter(pk=location_contact['contact']).first()
                            location_contact['contact_type'] = ContactType.objects.filter(
                                pk=location_contact['contact_type']).first()

                            EventLocationContact.objects.create(created_by=user, modified_by=user, **location_contact)

                    # Create EventLocationSpecies
                    if new_location_species is not None:
                        for location_spec in new_location_species:
                            location_spec['event_location'] = evt_location
                            new_species_diagnoses = location_spec.pop('new_species_diagnoses', None)

                            # Convert ids to ForeignKey objects
                            location_spec['species'] = Species.objects.filter(pk=location_spec['species']).first()
                            location_spec['age_bias'] = AgeBias.objects.filter(pk=location_spec['age_bias']).first()
                            location_spec['sex_bias'] = SexBias.objects.filter(pk=location_spec['sex_bias']).first()

                            location_species = LocationSpecies.objects.create(created_by=user, modified_by=user,
                                                                              **location_spec)

                            # create the child species diagnoses for this event
                            if new_species_diagnoses is not None:
                                for spec_diag in new_species_diagnoses:
                                    if spec_diag is not None:
                                        new_species_diagnosis_organizations = spec_diag.pop(
                                            'new_species_diagnosis_organizations', None)
                                        spec_diag['location_species'] = location_species
                                        spec_diag['diagnosis'] = Diagnosis.objects.filter(
                                            pk=spec_diag['diagnosis']).first()
                                        spec_diag['cause'] = DiagnosisCause.objects.filter(
                                            pk=spec_diag['cause']).first()
                                        spec_diag['basis'] = DiagnosisBasis.objects.filter(
                                            pk=spec_diag['basis']).first()
                                        species_diagnosis = SpeciesDiagnosis.objects.create(created_by=user,
                                                                                            modified_by=user,
                                                                                            **spec_diag)

                                        species_diagnosis.priority = calculate_priority_species_diagnosis(
                                            species_diagnosis)
                                        species_diagnosis.save()

                                        # create the child organizations for this species diagnosis
                                        if new_species_diagnosis_organizations is not None:
                                            for org_id in new_species_diagnosis_organizations:
                                                if org_id is not None:
                                                    org = Organization.objects.filter(pk=org_id).first()
                                                    if org is not None:
                                                        SpeciesDiagnosisOrganization.objects.create(
                                                            species_diagnosis=species_diagnosis, organization=org,
                                                            created_by=user, modified_by=user)

                            location_species.priority = calculate_priority_location_species(location_species)
                            location_species.save()

                    evt_location.priority = calculate_priority_event_location(evt_location)
                    evt_location.save()

        # create the child event diagnoses for this event
        pending = Diagnosis.objects.filter(name='Pending').first()
        undetermined = Diagnosis.objects.filter(name='Undetermined').first()

        # remove Pending or Undetermined if in the list because one or the other already exists from event save
        [new_event_diagnoses.remove(x) for x in new_event_diagnoses if x['diagnosis'] in [pending.id, undetermined.id]]

        if new_event_diagnoses:
            # Can only use diagnoses that are already used by this event's species diagnoses
            valid_diagnosis_ids = list(SpeciesDiagnosis.objects.filter(
                location_species__event_location__event=event.id
            ).exclude(id__in=[pending.id, undetermined.id]).values_list('diagnosis', flat=True).distinct())
            # If any new event diagnoses have a matching species diagnosis, then continue, else ignore
            if valid_diagnosis_ids is not None:
                for event_diagnosis in new_event_diagnoses:
                    diagnosis_id = event_diagnosis.pop('diagnosis', None)
                    if diagnosis_id in valid_diagnosis_ids:
                        # ensure this new event diagnosis has the correct suspect value
                        # (false if any matching species diagnoses are false, otherwise true)
                        diagnosis = Diagnosis.objects.filter(pk=diagnosis_id).first()
                        matching_specdiags_suspect = SpeciesDiagnosis.objects.filter(
                            location_species__event_location__event=event.id, diagnosis=diagnosis_id
                        ).values_list('suspect', flat=True)
                        suspect = False if False in matching_specdiags_suspect else True
                        event_diagnosis = EventDiagnosis.objects.create(**event_diagnosis, event=event,
                                                                        diagnosis=diagnosis, suspect=suspect,
                                                                        created_by=user, modified_by=user)
                        event_diagnosis.priority = calculate_priority_event_diagnosis(event_diagnosis)
                        event_diagnosis.save()
                # Now that we have the new event diagnoses created,
                # check for existing Pending or Undetermined records and delete them
                event_diagnoses = EventDiagnosis.objects.filter(event=event.id)
                [diag.delete() for diag in event_diagnoses if diag.diagnosis.id in [pending.id, undetermined.id]]

        return event

    # on update, any submitted nested objects (new_organizations, new_comments, new_event_locations) will be ignored
    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        new_complete = validated_data.get('complete', None)

        if instance.complete:
            # only event owner or higher roles can re-open ('un-complete') a closed ('completed') event
            # but if the complete field is not included or set to True, the event cannot be changed
            if new_complete is None or (new_complete and (user == instance.created_by or (
                    user.organization == instance.created_by.organization and (
                    user.role.is_partneradmin or user.role.is_partnermanager)))):
                message = "Complete events may only be changed by the event owner or an administrator"
                message += " if the 'complete' field is set to False."
                raise serializers.ValidationError(message)
            elif (user != instance.created_by
                  or (user.organization != instance.created_by.organization
                      and not (user.role.is_partneradmin or user.role.is_partnermanager))):
                message = "Complete events may not be changed"
                message += " unless first re-opened by the event owner or an administrator."
                raise serializers.ValidationError(message)

        if not instance.complete and new_complete and (user == instance.created_by or (
                user.organization == instance.created_by.organization and (
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
                        raise serializers.ValidationError(location_message)
                    if instance.event_type.id == mortality_morbidity.id:
                        location_species = LocationSpecies.objects.filter(event_location=location.id)
                        for spec in location_species:
                            if spec.dead_count_estimated is not None and spec.dead_count_estimated > 0:
                                species_count_is_valid.append(True)
                                if spec.dead_count > 0 and not spec.dead_count_estimated > spec.dead_count:
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
                    raise serializers.ValidationError(details)
            else:
                raise serializers.ValidationError(location_message)

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

        # update the Event object
        instance.event_type = validated_data.get('event_type', instance.event_type)
        instance.event_reference = validated_data.get('event_reference', instance.event_reference)
        instance.complete = validated_data.get('complete', instance.complete)
        instance.public = validated_data.get('public', instance.public)
        instance.circle_read = validated_data.get('circle_read', instance.circle_read)
        instance.circle_write = validated_data.get('circle_write', instance.circle_write)
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
                  'affected_count', 'event_status', 'event_status_string', 'public', 'circle_read', 'circle_write',
                  'organizations', 'contacts', 'comments', 'new_event_diagnoses', 'new_organizations', 'new_comments',
                  'new_event_locations', 'new_superevents', 'new_service_request', 'created_date', 'created_by',
                  'created_by_string', 'modified_date', 'modified_by', 'modified_by_string', 'service_request_email',
                  'permissions', 'permission_source',)


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
    new_superevents = serializers.ListField(write_only=True, required=False)
    new_service_request = serializers.JSONField(write_only=True, required=False)
    service_request_email = serializers.JSONField(read_only=True)

    def get_permission_source(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            permission_source = ''
        elif user.id == obj.created_by.id:
            permission_source = 'user'
        elif user.organization.id == obj.created_by.organization.id:
            permission_source = 'organization'
        elif obj.circle_read is not None and obj.circle_write is not None and (
                user in obj.circle_read or user in obj.circle_write):
            permission_source = 'circle'
        else:
            permission_source = ''
        return permission_source

    def create(self, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        if not user:
            raise serializers.ValidationError("User could not be identified, please contact the administrator.")

        if 'new_event_locations' not in validated_data:
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
        if 'new_event_locations' in validated_data:
            country_admin_is_valid = True
            latlng_is_valid = True
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
            for item in validated_data['new_event_locations']:
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
                    if (validated_data['event_type'].id == mortality_morbidity.id
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
                    adminl1 = AdministrativeLevelOne.objects.filter(id=item['administrative_level_one']).first()
                    if country.id != adminl1.country.id:
                        country_admin_is_valid = False
                    if 'administrative_level_two' in item and item['administrative_level_two'] is not None:
                        adminl2 = AdministrativeLevelTwo.objects.filter(id=item['administrative_level_two']).first()
                        if adminl1.id != adminl2.administrative_level_one.id:
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
                if ('latitude' in item and item['latitude'] is not None
                        and 'longitude' in item and item['longitude'] is not None
                        and ('country' not in item or 'administrative_level_one' not in item)):
                    payload = {'lat': item['latitude'], 'lng': item['longitude'],
                               'username': GEONAMES_USERNAME}
                    r = requests.get(GEONAMES_API + 'extendedFindNearbyJSON', params=payload, verify=settings.SSL_CERT)
                    if 'address' not in r.json() or 'geonames' not in r.json():
                        latlng_is_valid = False
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
                        if validated_data['event_type'].id == mortality_morbidity.id:
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
                        if Contact.objects.filter(id=loc_contact['contact']).first() is None:
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
            if validated_data['event_type'].id == mortality_morbidity.id and not min_species_count:
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
        if 'complete' in validated_data and validated_data['complete'] is True:
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
            for item in validated_data['new_event_locations']:
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
                    if validated_data['event_type'] == mortality_morbidity.id:
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

        comment_types = {'site_description': 'Site description', 'history': 'History',
                         'environmental_factors': 'Environmental factors', 'clinical_signs': 'Clinical signs',
                         'other': 'Other'}

        # pull out child event diagnoses list from the request
        new_event_diagnoses = validated_data.pop('new_event_diagnoses', None)

        # pull out child organizations list from the request
        new_organizations = validated_data.pop('new_organizations', None)

        # pull out child comments list from the request
        new_comments = validated_data.pop('new_comments', None)

        # pull out child event_locations list from the request
        new_event_locations = validated_data.pop('new_event_locations', None)

        # pull out child superevents list from the request
        new_superevents = validated_data.pop('new_superevents', None)

        # pull out child service request from the request
        new_service_request = validated_data.pop('new_service_request', None)

        event = Event.objects.create(**validated_data)

        # create the child organizations for this event
        if new_organizations is not None:
            for org_id in new_organizations:
                if org_id is not None:
                    org = Organization.objects.filter(pk=org_id).first()
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
                    comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                    Comment.objects.create(content_object=event, comment=comment['comment'], comment_type=comment_type,
                                           created_by=user, modified_by=user)

        # create the child superevents for this event
        if new_superevents is not None:
            for superevent_id in new_superevents:
                if superevent_id is not None:
                    superevent = SuperEvent.objects.filter(pk=superevent_id).first()
                    if superevent is not None:
                        EventSuperEvent.objects.create(event=event, superevent=superevent,
                                                       created_by=user, modified_by=user)

        # Create the child service requests for this event
        if new_service_request is not None:
            if ('request_type' in new_service_request and new_service_request['request_type'] is not None
                    and new_service_request['request_type'] in [1, 2]):
                new_comments = new_service_request.pop('new_comments', None)
                request_type = ServiceRequestType.objects.filter(pk=new_service_request['request_type']).first()
                service_request = ServiceRequest.objects.create(event=event, request_type=request_type,
                                                                created_by=user, modified_by=user)
                service_request_comments = []

                # create the child comments for this service request
                if new_comments is not None:
                    for comment in new_comments:
                        if comment is not None:
                            comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                            Comment.objects.create(content_object=service_request, comment=comment['comment'],
                                                   comment_type=comment_type, created_by=user, modified_by=user)
                            service_request_comments.append(comment.comment)

                # construct and send the request email
                service_request_email = construct_service_request_email(service_request.event.id,
                                                                        user.organization.name,
                                                                        service_request.request_type.name, user.email,
                                                                        service_request_comments)
                if settings.ENVIRONMENT not in ['production', 'test']:
                    event.service_request_email = service_request_email.__dict__

        # create the child event_locations for this event
        if new_event_locations is not None:
            for event_location in new_event_locations:
                if event_location is not None:
                    # use event to populate event field on event_location
                    event_location['event'] = event
                    new_location_contacts = event_location.pop('new_location_contacts', None)
                    new_location_species = event_location.pop('new_location_species', None)

                    # use id for country to get Country instance
                    event_location['country'] = Country.objects.filter(pk=event_location['country']).first()
                    # same for other things
                    event_location['administrative_level_one'] = AdministrativeLevelOne.objects.filter(
                        pk=event_location['administrative_level_one']).first()
                    event_location['administrative_level_two'] = AdministrativeLevelTwo.objects.filter(
                        pk=event_location['administrative_level_two']).first()
                    event_location['land_ownership'] = LandOwnership.objects.filter(
                        pk=event_location['land_ownership']).first()

                    flyway = None

                    # create object for comment creation while removing unserialized fields for EventLocation
                    comments = {'site_description': event_location.pop('site_description', None),
                                'history': event_location.pop('history', None),
                                'environmental_factors': event_location.pop('environmental_factors', None),
                                'clinical_signs': event_location.pop('clinical_signs', None),
                                'other': event_location.pop('comment', None)}

                    # create the event_location and return object for use in event_location_contacts object

                    # if the event_location has no name value but does have a gnis_name value,
                    # then copy the value of gnis_name to name
                    # this need only happen on creation since the two fields should maintain no durable relationship
                    if event_location['name'] == '' and event_location['gnis_name'] != '':
                        event_location['name'] = event_location['gnis_name']

                    # if event_location has lat/lng but no country/adminlevelone/adminleveltwo, populate missing fields
                    if ('country' not in event_location or event_location['country'] is None
                            or 'administrative_level_one' not in event_location
                            or event_location['administrative_level_one'] is None
                            or 'administrative_level_two' not in event_location
                            or event_location['administrative_level_two'] is None):
                        payload = {'lat': event_location['latitude'], 'lng': event_location['longitude'],
                                   'username': GEONAMES_USERNAME}
                        r = requests.get(GEONAMES_API + 'extendedFindNearbyJSON', params=payload, verify=settings.SSL_CERT)
                        geonames_object_list = r.json()
                        if 'address' in geonames_object_list:
                            address = geonames_object_list['address']
                            address['adminName2'] = address['name']
                        else:
                            geonames_objects_adm2 = [item for item in geonames_object_list['geonames'] if
                                                     item['fcode'] == 'ADM2']
                            address = geonames_objects_adm2[0]
                        if 'country' not in event_location or event_location['country'] is None:
                            country_code = address['countryCode']
                            if len(country_code) == 2:
                                payload = {'country': country_code, 'username': GEONAMES_USERNAME}
                                r = requests.get(GEONAMES_API + 'countryInfoJSON', params=payload, verify=settings.SSL_CERT)
                                alpha3 = r.json()['geonames'][0]['isoAlpha3']
                                event_location['country'] = Country.objects.filter(abbreviation=alpha3).first()
                            else:
                                event_location['country'] = Country.objects.filter(
                                    abbreviation=country_code).first()
                        if ('administrative_level_one' not in event_location
                                or event_location['administrative_level_one'] is None):
                            event_location['administrative_level_one'] = AdministrativeLevelOne.objects.filter(
                                name=address['adminName1']).first()
                        if ('administrative_level_two' not in event_location
                                or event_location['administrative_level_two'] is None):
                            admin2 = address['adminName2'] if 'adminName2' in address else address['name']
                            event_location['administrative_level_two'] = AdministrativeLevelTwo.objects.filter(
                                name=admin2).first()

                    # auto-assign flyway for states in the USA (exclude territories and minor outlying islands)
                    if (event_location['country'].id == Country.objects.filter(abbreviation='USA').first().id
                            and event_location['administrative_level_one'].abbreviation not in
                            ['PR', 'VI', 'MP', 'AS', 'UM', 'NOPO', 'SOPO']):
                        payload = {'geometryType': 'esriGeometryPoint', 'returnGeometry': 'false', 'outFields': 'NAME',
                                   'f': 'json'}
                        payload.update({'spatialRel': 'esriSpatialRelIntersects'})
                        # if lat/lng is present, use it to get the intersecting flyway
                        if ('latitude' in event_location and event_location['latitude'] is not None
                                and 'longitude' in event_location and event_location['longitude'] is not None):
                            payload.update({'geometry': event_location['longitude'] + ',' + event_location['latitude']})
                        # otherwise if county is present, look up the county centroid,
                        # then use it to get the intersecting flyway
                        elif event_location['administrative_level_two']:
                            geonames_payload = {'name': event_location['administrative_level_two'].name,
                                                'featureCode': 'ADM2', 'country': 'US',
                                                'maxRows': 1, 'username': GEONAMES_USERNAME}
                            gr = requests.get(GEONAMES_API + 'searchJSON', params=geonames_payload)
                            payload.update(
                                {'geometry': gr.json()['geonames'][0]['lng'] + ',' + gr.json()['geonames'][0]['lat']})
                        # MT, WY, CO, and NM straddle two flyways,
                        # and without lat/lng or county info, flyway cannot be determined,
                        # but otherwise look up the state centroid, then use it to get the intersecting flyway
                        elif (event_location['administrative_level_one'].abbreviation not in
                              ['MT', 'WY', 'CO', 'NM', 'HI']):
                            geonames_payload = {'adminCode1': event_location['administrative_level_one'], 'maxRows': 1,
                                                'username': GEONAMES_USERNAME}
                            gr = requests.get(GEONAMES_API + 'searchJSON', params=geonames_payload)
                            payload.update(
                                {'geometry': gr.json()['geonames'][0]['lng'] + ',' + gr.json()['geonames'][0]['lat']})
                        # HI is not in a flyway, assign it to Pacific ("Include all of Hawaii in with Pacific Americas")
                        elif event_location['administrative_level_one'].abbreviation == 'HI':
                            flyway = Flyway.objects.filter(name__contains='Pacific').first()

                        if flyway is None and 'geometry' in payload:
                            r = requests.get(FLYWAYS_API, params=payload, verify=settings.SSL_CERT)
                            flyway_name = r.json()['features'][0]['attributes']['NAME'].replace(' Flyway', '')
                            flyway = Flyway.objects.filter(name__contains=flyway_name).first()

                    evt_location = EventLocation.objects.create(created_by=user, modified_by=user, **event_location)

                    if flyway is not None:
                        EventLocationFlyway.objects.create(event_location=evt_location, flyway=flyway,
                                                           created_by=user, modified_by=user)

                    for key, value in comment_types.items():

                        comment_type = CommentType.objects.filter(name=value).first()

                        if comments[key] is not None and len(comments[key]) > 0 and comments[key] != '':
                            Comment.objects.create(content_object=evt_location, comment=comments[key],
                                                   comment_type=comment_type, created_by=user, modified_by=user)

                    # Create EventLocationContacts
                    if new_location_contacts is not None:
                        for location_contact in new_location_contacts:
                            location_contact['event_location'] = evt_location

                            # Convert ids to ForeignKey objects
                            location_contact['contact'] = Contact.objects.filter(pk=location_contact['contact']).first()
                            location_contact['contact_type'] = ContactType.objects.filter(
                                pk=location_contact['contact_type']).first()

                            EventLocationContact.objects.create(created_by=user, modified_by=user, **location_contact)

                    # Create EventLocationSpecies
                    if new_location_species is not None:
                        for location_spec in new_location_species:
                            location_spec['event_location'] = evt_location
                            new_species_diagnoses = location_spec.pop('new_species_diagnoses', None)

                            # Convert ids to ForeignKey objects
                            location_spec['species'] = Species.objects.filter(pk=location_spec['species']).first()
                            location_spec['age_bias'] = AgeBias.objects.filter(pk=location_spec['age_bias']).first()
                            location_spec['sex_bias'] = SexBias.objects.filter(pk=location_spec['sex_bias']).first()

                            location_species = LocationSpecies.objects.create(created_by=user, modified_by=user,
                                                                              **location_spec)

                            # create the child species diagnoses for this event
                            if new_species_diagnoses is not None:
                                for spec_diag in new_species_diagnoses:
                                    if spec_diag is not None:
                                        new_species_diagnosis_organizations = spec_diag.pop(
                                            'new_species_diagnosis_organizations', None)
                                        spec_diag['location_species'] = location_species
                                        spec_diag['diagnosis'] = Diagnosis.objects.filter(
                                            pk=spec_diag['diagnosis']).first()
                                        spec_diag['cause'] = DiagnosisCause.objects.filter(
                                            pk=spec_diag['cause']).first()
                                        spec_diag['basis'] = DiagnosisBasis.objects.filter(
                                            pk=spec_diag['basis']).first()
                                        species_diagnosis = SpeciesDiagnosis.objects.create(created_by=user,
                                                                                            modified_by=user,
                                                                                            **spec_diag)

                                        species_diagnosis.priority = calculate_priority_species_diagnosis(
                                            species_diagnosis)
                                        species_diagnosis.save()

                                        # create the child organizations for this species diagnosis
                                        if new_species_diagnosis_organizations is not None:
                                            for org_id in new_species_diagnosis_organizations:
                                                if org_id is not None:
                                                    org = Organization.objects.filter(pk=org_id).first()
                                                    if org is not None:
                                                        SpeciesDiagnosisOrganization.objects.create(
                                                            species_diagnosis=species_diagnosis, organization=org,
                                                            created_by=user, modified_by=user)

                            location_species.priority = calculate_priority_location_species(location_species)
                            location_species.save()

                    evt_location.priority = calculate_priority_event_location(evt_location)
                    evt_location.save()

        # create the child event diagnoses for this event
        pending = Diagnosis.objects.filter(name='Pending').first()
        undetermined = Diagnosis.objects.filter(name='Undetermined').first()

        # remove Pending or Undetermined if in the list because one or the other already exists from event save
        [new_event_diagnoses.remove(x) for x in new_event_diagnoses if x['diagnosis'] in [pending.id, undetermined.id]]

        if new_event_diagnoses:
            # Can only use diagnoses that are already used by this event's species diagnoses
            valid_diagnosis_ids = list(SpeciesDiagnosis.objects.filter(
                location_species__event_location__event=event.id
            ).exclude(id__in=[pending.id, undetermined.id]).values_list('diagnosis', flat=True).distinct())
            # If any new event diagnoses have a matching species diagnosis, then continue, else ignore
            if valid_diagnosis_ids is not None:
                for event_diagnosis in new_event_diagnoses:
                    diagnosis_id = int(event_diagnosis.pop('diagnosis', None))
                    if diagnosis_id in valid_diagnosis_ids:
                        # ensure this new event diagnosis has the correct suspect value
                        # (false if any matching species diagnoses are false, otherwise true)
                        diagnosis = Diagnosis.objects.filter(pk=diagnosis_id).first()
                        matching_specdiags_suspect = SpeciesDiagnosis.objects.filter(
                            location_species__event_location__event=event.id, diagnosis=diagnosis_id
                        ).values_list('suspect', flat=True)
                        suspect = False if False in matching_specdiags_suspect else True
                        event_diagnosis = EventDiagnosis.objects.create(**event_diagnosis, event=event,
                                                                        diagnosis=diagnosis, suspect=suspect,
                                                                        created_by=user, modified_by=user)
                        event_diagnosis.priority = calculate_priority_event_diagnosis(event_diagnosis)
                        event_diagnosis.save()
                # Now that we have the new event diagnoses created,
                # check for existing Pending or Undetermined records and delete them
                event_diagnoses = EventDiagnosis.objects.filter(event=event.id)
                [diag.delete() for diag in event_diagnoses if diag.diagnosis.id in [pending.id, undetermined.id]]

        return event

    # on update, any submitted nested objects (new_organizations, new_comments, new_event_locations) will be ignored
    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

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
                raise serializers.ValidationError(message)

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
                        raise serializers.ValidationError(location_message)
                    if instance.event_type.id == mortality_morbidity.id:
                        location_species = LocationSpecies.objects.filter(event_location=location.id)
                        for spec in location_species:
                            if spec.dead_count_estimated is not None and spec.dead_count_estimated > 0:
                                species_count_is_valid.append(True)
                                if spec.dead_count > 0 and not spec.dead_count_estimated > spec.dead_count:
                                    est_count_gt_known_count = False
                            elif spec.dead_count is not None and spec.dead_count > 0:
                                species_count_is_valid.append(True)
                            elif spec.sick_count_estimated is not None and spec.sick_count_estimated > 0:
                                species_count_is_valid.append(True)
                                if (spec.sick_count or 0) > 0 and spec.sick_count_estimated <= (spec.sick_count or 0):
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
                    raise serializers.ValidationError(details)
            else:
                raise serializers.ValidationError(location_message)

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
        instance.circle_read = validated_data.get('circle_read', instance.circle_read)
        instance.circle_write = validated_data.get('circle_write', instance.circle_write)
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
                  'circle_read', 'circle_write', 'superevents', 'organizations', 'contacts', 'comments',
                  'new_event_diagnoses', 'new_organizations', 'new_comments', 'new_event_locations', 'new_superevents',
                  'new_service_request', 'created_date', 'created_by', 'created_by_string', 'modified_date',
                  'modified_by', 'modified_by_string', 'service_request_email', 'permissions', 'permission_source',)


class EventSuperEventSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        if data['event'].complete:
            message = "SuperEvent for a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        return data

    class Meta:
        model = EventSuperEvent
        fields = ('id', 'event', 'superevent', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class SuperEventSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = SuperEvent
        fields = ('id', 'category', 'events', 'created_date', 'created_by', 'created_by_string',
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

        if data['event'].complete:
            message = "Organizations from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        return data

    def create(self, validated_data):

        event_organization = EventOrganization.objects.create(**validated_data)

        # calculate the priority value:
        event_organization.priority = calculate_priority_event_organization(event_organization)
        event_organization.save()

        return event_organization

    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

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

    def validate(self, data):

        message_complete = "Locations from a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."

        # if this is a new EventLocation check if the Event is complete
        if 'request' in self.context and self.context['request'].method == 'POST' and data['event'].complete:
            raise serializers.ValidationError(message_complete)

        # else this is an existing EventLocation so check if this is an update and if parent Event is complete
        elif self.context['request'].method in ['PUT', 'PATCH'] and self.instance.event.complete:
            raise serializers.ValidationError(message_complete)

        return data

    def create(self, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        if not user:
            raise serializers.ValidationError("User could not be identified, please contact the administrator.")

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
        country_admin_is_valid = True
        latlng_is_valid = True
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
        if [i for i in required_comment_types if i in validated_data and validated_data[i]]:
            comments_is_valid.append(True)
        else:
            comments_is_valid.append(False)
        if 'start_date' in validated_data and validated_data['start_date'] is not None:
            min_start_date = True
            if (validated_data['event'].event_type.id == mortality_morbidity.id
                    and validated_data['start_date'] > date.today()):
                start_date_is_valid = False
            if ('end_date' in validated_data and validated_data['end_date'] is not None
                    and validated_data['end_date'] < validated_data['start_date']):
                end_date_is_valid = False
        elif 'end_date' in validated_data and validated_data['end_date'] is not None:
            end_date_is_valid = False
        if ('country' in validated_data and validated_data['country'] is not None
                and 'administrative_level_one' in validated_data
                and validated_data['administrative_level_one'] is not None):
            country = validated_data['country']
            adminl1 = validated_data['administrative_level_one']
            if country.id != adminl1.country.id:
                country_admin_is_valid = False
            if 'administrative_level_two' in validated_data and validated_data['administrative_level_two'] is not None:
                adminl2 = validated_data['administrative_level_two']
                if adminl1.id != adminl2.administrative_level_one.id:
                    country_admin_is_valid = False
        if (('country' not in validated_data or validated_data['country'] is None
             or 'administrative_level_one' not in validated_data or validated_data['administrative_level_one'] is None)
                and ('latitude' not in validated_data or validated_data['latitude'] is None
                     or 'longitude' not in validated_data and validated_data['longitude'] is None)):
            message = "country and administrative_level_one are required if latitude or longitude is null."
            details.append(message)
        if ('latitude' in validated_data and validated_data['latitude'] is not None
                and not re.match(r"(-?)([\d]{1,2})(\.)(\d+)", str(validated_data['latitude']))):
            latlng_is_valid = False
        if ('longitude' in validated_data and validated_data['longitude'] is not None
                and not re.match(r"(-?)([\d]{1,3})(\.)(\d+)", str(validated_data['longitude']))):
            latlng_is_valid = False
        if ('latitude' in validated_data and validated_data['latitude'] is not None
                and 'longitude' in validated_data and validated_data['longitude'] is not None
                and ('country' not in validated_data or 'administrative_level_one' not in validated_data)):
            payload = {'lat': validated_data['latitude'], 'lng': validated_data['longitude'],
                       'username': GEONAMES_USERNAME}
            r = requests.get(GEONAMES_API + 'extendedFindNearbyJSON', params=payload, verify=settings.SSL_CERT)
            if 'address' not in r.json() or 'geonames' not in r.json():
                latlng_is_valid = False
        if 'new_location_species' in validated_data:
            for spec in validated_data['new_location_species']:
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
                        dead_count = max(spec.get('dead_count_estimated') or 0,
                                         spec.get('dead_count') or 0)
                    if 'sick_count_estimated' in spec or 'sick_count' in spec:
                        sick_count = max(spec.get('sick_count_estimated') or 0,
                                         spec.get('sick_count') or 0)
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
                if validated_data['event'].event_type.id == mortality_morbidity.id:
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
            if 'new_location_contacts' in validated_data and validated_data['new_location_contacts'] is not None:
                for loc_contact in validated_data['new_location_contacts']:
                    if Contact.objects.filter(id=loc_contact['contact']).first() is None:
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
        if validated_data['event'].event_type.id == mortality_morbidity.id and not min_species_count:
            message = "For Mortality/Morbidity events, at least one new_location_species requires at least one species"
            message += " count in any of the following fields:"
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

        flyway = None

        comment_types = {'site_description': 'Site description', 'history': 'History',
                         'environmental_factors': 'Environmental factors', 'clinical_signs': 'Clinical signs',
                         'other': 'Other'}

        # event = Event.objects.filter(pk=validated_data['event']).first()
        new_location_contacts = validated_data.pop('new_location_contacts', None)
        new_location_species = validated_data.pop('new_location_species', None)

        # # use id for country to get Country instance
        # country = Country.objects.filter(pk=validated_data['country']).first()
        # # same for other things
        # administrative_level_one = AdministrativeLevelOne.objects.filter(
        #     pk=validated_data['administrative_level_one']).first()
        # administrative_level_two = AdministrativeLevelTwo.objects.filter(
        #     pk=validated_data['administrative_level_two']).first()
        # land_ownership = LandOwnership.objects.filter(pk=validated_data['land_ownership']).first()

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
        if ('country' not in validated_data or validated_data['country'] is None
                or 'administrative_level_one' not in validated_data
                or validated_data['administrative_level_one'] is None
                or 'administrative_level_two' not in validated_data
                or validated_data['administrative_level_two'] is None):
            payload = {'lat': validated_data['latitude'], 'lng': validated_data['longitude'],
                       'username': GEONAMES_USERNAME}
            r = requests.get(GEONAMES_API + 'extendedFindNearbyJSON', params=payload, verify=settings.SSL_CERT)
            geonames_object_list = r.json()
            if 'address' in geonames_object_list:
                address = geonames_object_list['address']
                address['adminName2'] = address['name']
            else:
                geonames_objects_adm2 = [item for item in geonames_object_list['geonames'] if item['fcode'] == 'ADM2']
                address = geonames_objects_adm2[0]
            if 'country' not in validated_data or validated_data['country'] is None:
                country_code = address['countryCode']
                if len(country_code) == 2:
                    payload = {'country': country_code, 'username': GEONAMES_USERNAME}
                    r = requests.get(GEONAMES_API + 'countryInfoJSON', params=payload, verify=settings.SSL_CERT)
                    alpha3 = r.json()['geonames'][0]['isoAlpha3']
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

        # auto-assign flyway for locations in the USA
        if validated_data['country'].id == Country.objects.filter(abbreviation='USA').first().id:
            payload = {'geometryType': 'esriGeometryPoint', 'returnGeometry': 'false', 'outFields': 'NAME', 'f': 'json'}
            payload.update({'spatialRel': 'esriSpatialRelIntersects'})
            # if lat/lng is present, use it to get the intersecting flyway
            if ('latitude' in validated_data and validated_data['latitude'] is not None
                    and 'longitude' in validated_data and validated_data['longitude'] is not None):
                payload.update({'geometry': validated_data['longitude'] + ',' + validated_data['latitude']})
            # otherwise if county is present, look up the county centroid, then use it to get the intersecting flyway
            elif validated_data['administrative_level_two']:
                geonames_payload = {'name': validated_data['administrative_level_two'].name, 'featureCode': 'ADM2',
                                    'maxRows': 1, 'username': GEONAMES_USERNAME}
                gr = requests.get(GEONAMES_API + 'searchJSON', params=geonames_payload)
                payload.update({'geometry': gr.json()['geonames'][0]['lng'] + ',' + gr.json()['geonames'][0]['lat']})
            # MT, WY, CO, and NM straddle two flyways, and without lat/lng or county info, flyway cannot be determined
            # otherwise look up the state centroid, then use it to get the intersecting flyway
            elif validated_data['administrative_level_one'].abbreviation not in ['MT', 'WY', 'CO', 'NM', 'HI']:
                geonames_payload = {'adminCode1': validated_data['administrative_level_one'], 'maxRows': 1,
                                    'username': GEONAMES_USERNAME}
                gr = requests.get(GEONAMES_API + 'searchJSON', params=geonames_payload)
                payload.update({'geometry': gr.json()['geonames'][0]['lng'] + ',' + gr.json()['geonames'][0]['lat']})
            # HI is not in a flyway, so assign it to Pacific ("Include all of Hawaii in with Pacific Americas")
            elif validated_data['administrative_level_one'].abbreviation == 'HI':
                flyway = Flyway.objects.filter(name__contains='Pacific').first()

            if flyway is None and 'geometry' in payload:
                r = requests.get(FLYWAYS_API, params=payload, verify=settings.SSL_CERT)
                flyway_name = r.json()['features'][0]['attributes']['NAME'].replace(' Flyway', '')
                flyway = Flyway.objects.filter(name__contains=flyway_name).first()

        # create the event_location and return object for use in event_location_contacts object
        # validated_data['created_by'] = user
        # validated_data['modified_by'] = user
        evt_location = EventLocation.objects.create(**validated_data)

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
                location_contact['contact'] = Contact.objects.filter(pk=location_contact['contact']).first()
                location_contact['contact_type'] = ContactType.objects.filter(
                    pk=location_contact['contact_type']).first()

                EventLocationContact.objects.create(created_by=user, modified_by=user, **location_contact)

        # Create EventLocationSpecies
        if new_location_species is not None:
            for location_spec in new_location_species:
                location_spec['event_location'] = evt_location
                new_species_diagnoses = location_spec.pop('new_species_diagnoses', None)

                # Convert ids to ForeignKey objects
                location_spec['species'] = Species.objects.filter(pk=location_spec['species']).first()
                location_spec['age_bias'] = AgeBias.objects.filter(pk=location_spec['age_bias']).first()
                location_spec['sex_bias'] = SexBias.objects.filter(pk=location_spec['sex_bias']).first()

                location_species = LocationSpecies.objects.create(created_by=user, modified_by=user, **location_spec)

                # create the child species diagnoses for this event
                if new_species_diagnoses is not None:
                    for spec_diag in new_species_diagnoses:
                        if spec_diag is not None:
                            new_species_diagnosis_organizations = spec_diag.pop(
                                'new_species_diagnosis_organizations', None)
                            spec_diag['location_species'] = location_species
                            spec_diag['diagnosis'] = Diagnosis.objects.filter(pk=spec_diag['diagnosis']).first()
                            spec_diag['cause'] = DiagnosisCause.objects.filter(pk=spec_diag['cause']).first()
                            spec_diag['basis'] = DiagnosisBasis.objects.filter(pk=spec_diag['basis']).first()
                            species_diagnosis = SpeciesDiagnosis.objects.create(created_by=user, modified_by=user,
                                                                                **spec_diag)

                            species_diagnosis.priority = calculate_priority_species_diagnosis(species_diagnosis)
                            species_diagnosis.save()

                            # create the child organizations for this species diagnosis
                            if new_species_diagnosis_organizations is not None:
                                for org_id in new_species_diagnosis_organizations:
                                    if org_id is not None:
                                        org = Organization.objects.filter(pk=org_id).first()
                                        if org is not None:
                                            SpeciesDiagnosisOrganization.objects.create(
                                                species_diagnosis=species_diagnosis, organization=org,
                                                created_by=user, modified_by=user)

                location_species.priority = calculate_priority_location_species(location_species)
                location_species.save()

        # calculate the priority value:
        evt_location.priority = calculate_priority_event_location(evt_location)
        evt_location.save()

        return evt_location

    # on update, any submitted nested objects (new_location_contacts, new_location_species) will be ignored
    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

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
        if validated_data['name'] == '' and validated_data['gnis_name'] != '':
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
        if ('request' in self.context and self.context['request'].method == 'POST'
                and data['event_location'].event.complete):
            raise serializers.ValidationError(message_complete)

        # else this is an existing EventLocationContact so check if this is an update and if parent Event is complete
        elif self.context['request'].method in ['PUT', 'PATCH'] and self.instance.event_location.event.complete:
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
        if ('request' in self.context and self.context['request'].method == 'POST'
                and data['event_location'].event.complete):
            raise serializers.ValidationError(message_complete)

        # else this is an existing EventLocationFlyway so check if this is an update and if parent Event is complete
        elif self.context['request'].method in ['PUT', 'PATCH'] and self.instance.event_location.event.complete:
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

    def validate(self, data):

        message_complete = "Species from a location from a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."

        # if this is a new LocationSpecies check if the Event is complete
        if ('request' in self.context and self.context['request'].method == 'POST'
                and data['event_location'].event.complete):
            raise serializers.ValidationError(message_complete)

        # else this is an existing LocationSpecies so check if this is an update and if parent Event is complete
        elif self.context['request'].method in ['PUT', 'PATCH'] and self.instance.event_location.event.complete:
            raise serializers.ValidationError(message_complete)

        return data

    def create(self, validated_data):

        # 1. location_species Population >= max(estsick, knownsick) + max(estdead, knowndead)
        # 2. For morbidity/mortality events, there must be at least one number between sick, dead, estimated_sick,
        #    and estimated_dead for at least one species in the event at the time of event initiation.
        #    (sick + dead + estimated_sick + estimated_dead >= 1)
        # 3. If present, estimated_sick must be higher than known sick (estimated_sick > sick).
        # 4. If present, estimated dead must be higher than known dead (estimated_dead > dead).
        min_species_count = False
        pop_is_valid = True
        est_sick_is_valid = True
        est_dead_is_valid = True
        details = []

        if 'population_count' in validated_data and validated_data['population_count'] is not None:
            dead_count = 0
            sick_count = 0
            if 'dead_count_estimated' in validated_data or 'dead_count' in validated_data:
                dead_count = max(validated_data.get('dead_count_estimated') or 0, validated_data.get('dead_count') or 0)
            if 'sick_count_estimated' in validated_data or 'sick_count' in validated_data:
                sick_count = max(validated_data.get('sick_count_estimated') or 0, validated_data.get('sick_count') or 0)
            if validated_data['population_count'] < dead_count + sick_count:
                pop_is_valid = False
        if ('sick_count_estimated' in validated_data and validated_data['sick_count_estimated'] is not None
                and 'sick_count' in validated_data and validated_data['sick_count'] is not None
                and not validated_data['sick_count_estimated'] > validated_data['sick_count']):
            est_sick_is_valid = False
        if ('dead_count_estimated' in validated_data and validated_data['dead_count_estimated'] is not None
                and 'dead_count' in validated_data and validated_data['dead_count'] is not None
                and not validated_data['dead_count_estimated'] > validated_data['dead_count']):
            est_dead_is_valid = False
        mm = EventType.objects.filter(name='Mortality/Morbidity').first()
        mm_lsps = None
        if validated_data['event_location'].event.event_type.id == mm.id:
            locspecs = LocationSpecies.objects.filter(event_location=validated_data['event_location'].id)
            mm_lsps = [locspec for locspec in locspecs if locspec.event_location.event.event_type.id == mm.id]
            if mm_lsps is None:
                if ('dead_count_estimated' in validated_data and validated_data['dead_count_estimated'] is not None
                        and validated_data['dead_count_estimated'] > 0):
                    min_species_count = True
                elif ('dead_count' in validated_data and validated_data['dead_count'] is not None
                      and validated_data['dead_count'] > 0):
                    min_species_count = True
                elif ('sick_count_estimated' in validated_data and validated_data['sick_count_estimated'] is not None
                      and validated_data['sick_count_estimated'] > 0):
                    min_species_count = True
                elif ('sick_count' in validated_data and validated_data['sick_count'] is not None
                      and validated_data['sick_count'] > 0):
                    min_species_count = True

        if not pop_is_valid:
            message = "New location_species population_count cannot be less than the sum of dead_count"
            message += " and sick_count (where those counts are the maximum of the estimated or known count)."
            details.append(message)
        if validated_data['event_location'].event.event_type.id == mm.id and mm_lsps is None and not min_species_count:
            message = "For Mortality/Morbidity events, at least one new_location_species requires at least one species"
            message += " count in any of the following fields:"
            message += " dead_count_estimated, dead_count, sick_count_estimated, sick_count."
            details.append(message)
        if not est_sick_is_valid:
            details.append("Estimated sick count must always be more than known sick count.")
        if not est_dead_is_valid:
            details.append("Estimated dead count must always be more than known dead count.")
        if details:
            raise serializers.ValidationError(details)

        location_species = LocationSpecies.objects.create(**validated_data)

        # calculate the priority value:
        location_species.priority = calculate_priority_location_species(location_species)
        location_species.save()

        return location_species

    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

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

        # 1. location_species Population >= max(estsick, knownsick) + max(estdead, knowndead)
        # 2. For morbidity/mortality events, there must be at least one number between sick, dead, estimated_sick,
        #    and estimated_dead for at least one species in the event at the time of event initiation.
        #    (sick + dead + estimated_sick + estimated_dead >= 1)
        # 3. If present, estimated_sick must be higher than known sick (estimated_sick > sick).
        # 4. If present, estimated dead must be higher than known dead (estimated_dead > dead).
        min_species_count = False
        pop_is_valid = True
        est_sick_is_valid = True
        est_dead_is_valid = True
        details = []

        if instance.population_count:
            dead_count = 0
            sick_count = 0
            if instance.dead_count_estimated or instance.dead_count:
                dead_count = max(instance.dead_count_estimated or 0, instance.dead_count or 0)
            if instance.sick_count_estimated or instance.sick_count:
                sick_count = max(instance.sick_count_estimated or 0, instance.sick_count or 0)
            if instance.population_count < dead_count + sick_count:
                pop_is_valid = False

        if (instance.sick_count_estimated and instance.sick_count
                and not instance.sick_count_estimated > instance.sick_count):
            est_sick_is_valid = False
        if (instance.dead_count_estimated and instance.dead_count
                and not instance.dead_count_estimated > instance.dead_count):
            est_dead_is_valid = False
        mm = EventType.objects.filter(name='Mortality/Morbidity').first()
        mm_locspecs = None
        if instance.event_location.event.event_type.id == mm.id:
            locspecs = LocationSpecies.objects.filter(event_location=instance.event_location.id)
            mm_locspecs = [locspec for locspec in locspecs if locspec.event_location.event.event_type.id == mm.id]
            if mm_locspecs is None:
                if instance.dead_count_estimated and instance.dead_count_estimated > 0:
                    min_species_count = True
                elif instance.dead_count and instance.dead_count > 0:
                    min_species_count = True
                elif instance.sick_count_estimated and instance.sick_count_estimated > 0:
                    min_species_count = True
                elif instance.sick_count and instance.sick_count > 0:
                    min_species_count = True

        if not pop_is_valid:
            message = "New location_species population_count cannot be less than the sum of dead_count"
            message += " and sick_count (where those counts are the maximum of the estimated or known count)."
            details.append(message)
        if instance.event_location.event.event_type.id == mm.id and mm_locspecs is None and not min_species_count:
            message = "For Mortality/Morbidity events, at least one new_location_species requires at least one species"
            message += " count in any of the following fields:"
            message += " dead_count_estimated, dead_count, sick_count_estimated, sick_count."
            details.append(message)
        if not est_sick_is_valid:
            details.append("Estimated sick count must always be more than known sick count.")
        if not est_dead_is_valid:
            details.append("Estimated dead count must always be more than known dead count.")
        if details:
            raise serializers.ValidationError(details)

        # calculate the priority value:
        instance.priority = calculate_priority_location_species(instance)
        instance.save()

        return instance

    class Meta:
        model = LocationSpecies
        fields = ('id', 'event_location', 'species', 'population_count', 'sick_count', 'dead_count',
                  'sick_count_estimated', 'dead_count_estimated', 'priority', 'captive', 'age_bias', 'sex_bias',
                  'created_date', 'created_by', 'created_by_string',
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
        fields = ('id', 'name', 'diagnosis_type', 'diagnosis_type_string',
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
        diagnosis = None
        event_specdiags = []

        # if this is a new EventDiagnosis check if the Event is complete
        if 'request' in self.context and self.context['request'].method == 'POST':

            if data['event'].complete:
                raise serializers.ValidationError(message_complete)

            diagnosis = data['diagnosis']
            event_specdiags = SpeciesDiagnosis.objects.filter(
                location_species__event_location__event=data['event'].id).values_list('diagnosis', flat=True).distinct()

        # else this is an existing EventDiagnosis so check if this is an update and if parent Event is complete
        elif self.context['request'].method in ['PUT', 'PATCH']:

            if self.instance.event.complete:
                raise serializers.ValidationError(message_complete)

            diagnosis = data['diagnosis'] if 'diagnosis' in data else self.instance.diagnosis
            event_specdiags = list(SpeciesDiagnosis.objects.filter(
                location_species__event_location__event=self.instance.event.id).values_list(
                'diagnosis', flat=True).distinct())

            if 'diagnosis' not in data or data['diagnosis'] is None:
                data['diagnosis'] = self.instance.diagnosis

        # check that submitted diagnoses are also in this event's species diagnoses
        if diagnosis is not None and ((not event_specdiags or diagnosis.id not in event_specdiags)
                                      and diagnosis.name not in ['Pending', 'Undetermined']):
                message = "A diagnosis for Event Diagnosis must match a diagnosis of a Species Diagnosis of this event."
                raise serializers.ValidationError(message)

        return data

    def create(self, validated_data):

        # TODO: Check on this... the rule seeme pointless unless a user can manually assign Undetermined, which seemingly contradicts other rules
        # # If have "Undetermined" at the event level, should have no other diagnoses at event level.
        # if validated_data['event'].complete and validated_data['diagnosis'] == undetermined.id:
        #     [evt_diag.delete() for evt_diag in get_event_diagnoses()]

        # ensure this new event diagnosis has the correct suspect value
        # (false if any matching species diagnoses are false, otherwise true)
        event = validated_data['event']
        diagnosis = validated_data['diagnosis']
        matching_specdiags_suspect = SpeciesDiagnosis.objects.filter(
            location_species__event_location__event=event.id, diagnosis=diagnosis.id
        ).values_list('suspect', flat=True)
        suspect = False if False in matching_specdiags_suspect else True
        event_diagnosis = EventDiagnosis.objects.create(**validated_data, suspect=suspect)
        event_diagnosis.priority = calculate_priority_event_diagnosis(event_diagnosis)
        event_diagnosis.save()

        # Now that we have the new event diagnoses created,
        # check for existing Pending or Undetermined records and delete them
        event_diagnoses = EventDiagnosis.objects.filter(event=event_diagnosis.event.id)
        [diag.delete() for diag in event_diagnoses if diag.diagnosis.name in ['Pending', 'Undetermined']]

        # calculate the priority value:
        event_diagnosis.priority = calculate_priority_event_diagnosis(event_diagnosis)
        event_diagnosis.save()

        return event_diagnosis

    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

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

        # Now that we have the new event diagnoses created,
        # check for existing Pending or Undetermined records and delete them
        event_diagnoses = EventDiagnosis.objects.filter(event=instance.event.id)
        [diag.delete() for diag in event_diagnoses if diag.diagnosis.name in ['Pending', 'Undetermined']]

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

        # if this is a new SpeciesDiagnosis check if the Event is complete
        if 'request' in self.context and self.context['request'].method == 'POST':

            if data['location_species'].event_location.event.complete:
                raise serializers.ValidationError(message_complete)

        # else this is an existing SpeciesDiagnosis so check if this is an update and if parent Event is complete
        elif self.context['request'].method in ['PUT', 'PATCH']:

            if self.instance.location_species.event_location.event.complete:
                raise serializers.ValidationError(message_complete)

        return data

    def create(self, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        if not user:
            raise serializers.ValidationError("User could not be identified, please contact the administrator.")

        new_species_diagnosis_organizations = validated_data.pop('new_species_diagnosis_organizations', None)

        if new_species_diagnosis_organizations is not None:
            for org_id in new_species_diagnosis_organizations:
                org = Organization.objects.filter(id=org_id).first()
                if org and not org.laboratory:
                    raise serializers.ValidationError("SpeciesDiagnosis Organization can only be a laboratory.")

        suspect = validated_data['suspect'] if 'suspect' in validated_data and validated_data['suspect'] else None
        tested_count = validated_data['tested_count'] if 'tested_count' in validated_data and validated_data[
            'tested_count'] is not None else None
        suspect_count = validated_data['suspect_count'] if 'suspect_count' in validated_data and validated_data[
            'suspect_count'] is not None else None
        pos_count = validated_data['positive_count'] if 'positive_count' in validated_data and validated_data[
            'positive_count'] is not None else None

        # Non-suspect diagnosis cannot have basis_of_dx = 1,2, or 4.
        # TODO: following rule would only work on update due to M:N relate to orgs, so on-hold until further notice
        # If 3 is selected user must provide a lab.
        if suspect and 'basis' in validated_data and validated_data['basis'] in [1, 2, 4]:
            message = "The basis of diagnosis can only be 'Necropsy and/or ancillary tests performed"
            message += " at a diagnostic laboratory' when the diagnosis is non-suspect."
            raise serializers.ValidationError(message)

        if tested_count is not None:
            # Within each species diagnosis, number_with_diagnosis =< number_tested.
            if ('diagnosis_count' in validated_data and validated_data['diagnosis_count'] is not None
                    and not validated_data['diagnosis_count'] <= tested_count):
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
        # elif 'diagnosis_count' in validated_data and validated_data['diagnosis_count'] is not None:
        #     raise serializers.ValidationError("The diagnosed count cannot be more than the tested count.")

        # If diagnosis is non-suspect (suspect=False), then number_positive must be null or greater than zero,
        # else diagnosis is suspect (suspect=True) and so number_positive must be zero
        # TODO: following rule would only work on update due to M:N relate to orgs, so on-hold until further notice
        # Only allowed to enter >0 if provide laboratory name.
        # if not suspect and (not pos_count or pos_count > 0):
        #     raise serializers.ValidationError("The positive count cannot be zero when the diagnosis is non-suspect.")

        # TODO: temporarily disabling this rule
        # if 'pooled' in validated_data and validated_data['pooled'] and tested_count <= 1:
        #     raise serializers.ValidationError("A diagnosis can only be pooled if the tested count is greater than one.")

        # TODO: following rule would only work on update due to M:N relate to orgs, so on-hold until further notice
        # For new validated_data, if no Lab provided, then suspect = True; although all "Pending" and "Undetermined"
        # diagnosis must be confirmed (suspect = False), even if no lab OR some other way of coding this such that we
        # (TODO: NOTE following rule is valid and enforceable right now:)
        # never see "Pending suspect" or "Undetermined suspect" on front end.
        # pending = Diagnosis.objects.filter(name='Pending').first().id
        # undetermined = Diagnosis.objects.filter(name='Undetermined').first().id
        # if 'diagnosis' in validated_data and validated_data['diagnosis'] in [pending, undetermined]:
        #     validated_data['suspect'] = False

        species_diagnosis = SpeciesDiagnosis.objects.create(**validated_data)

        # calculate the priority value:
        species_diagnosis.priority = calculate_priority_species_diagnosis(species_diagnosis)
        species_diagnosis.save()

        if new_species_diagnosis_organizations is not None:
            for org_id in new_species_diagnosis_organizations:
                org = Organization.objects.filter(id=org_id).first()
                if org:
                    SpeciesDiagnosisOrganization.objects.create(species_diagnosis=species_diagnosis, organization=org,
                                                                created_by=user, modified_by=user)

        return species_diagnosis

    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

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

        if new_org_ids is not None:
            new_org_ids = [int(org_id) for org_id in new_org_ids]
            for org_id in new_org_ids:
                org = Organization.objects.filter(id=org_id).first()
                if org and not org.laboratory:
                    raise serializers.ValidationError("SpeciesDiagnosis Organization can only be a laboratory.")

        # for positive_count, only allowed to enter >0 if provide laboratory name.
        if instance.positive_count and instance.positive_count > 0 and (len(old_org_ids) == 0 or len(new_org_ids) == 0):
            message = "The positive count cannot be greater than zero if there is no laboratory for this diagnosis."
            raise serializers.ValidationError(message)

        # a diagnosis can only be used once for a location-species-labID combination
        loc_specdiags = SpeciesDiagnosis.objects.filter(
            location_species=instance.location_species).values('id', 'diagnosis').exclude(id=instance.id)
        if instance.diagnosis.id in [specdiag['diagnosis'] for specdiag in loc_specdiags]:
            loc_specdiags_ids = [specdiag['id'] for specdiag in loc_specdiags]
            loc_specdiags_labs_ids = set(SpeciesDiagnosisOrganization.objects.filter(
                species_diagnosis__in=loc_specdiags_ids).values_list('id', flat=True))
            my_labs_ids = [org.id for org in instance.organizations.all()]
            if len([lab_id for lab_id in my_labs_ids if lab_id in loc_specdiags_labs_ids]) > 0:
                message = "A diagnosis can only be used once for a location-species-laboratory combination."
                raise serializers.ValidationError(message)

        # All "Pending" and "Undetermined" must be confirmed OR some other way of coding this
        # such that we never see "Pending suspect" or "Undetermined suspect" on front end.
        # pending = Diagnosis.objects.filter(name='Pending').first().id
        # undetermined = Diagnosis.objects.filter(name='Undetermined').first().id
        # if instance.diagnosis in [pending, undetermined]:
        #     instance.suspect = False

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
        if 'request' in self.context and self.context['request'].method == 'POST':

            if data['species_diagnosis'].location_species.event_location.event.complete:
                raise serializers.ValidationError(message_complete)

            if data['organization'].laboratory:
                raise serializers.ValidationError("SpeciesDiagnosis Organization can only be a laboratory.")

        # else this is an existing SpeciesDiagnosis so check if this is an update and if parent Event is complete
        elif self.context['request'].method in ['PUT', 'PATCH']:

            if self.instance.location_species.event_location.event.complete:
                raise serializers.ValidationError(message_complete)

            if 'organization' in data and data['organization'].laboratory:
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
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        if not user:
            raise serializers.ValidationError("User could not be identified, please contact the administrator.")

        # pull out child comments list from the request
        new_comments = validated_data.pop('new_comments', None)

        # Only allow NWHC admins to alter the request response
        if 'request_response' in validated_data and validated_data['request_response'] is not None:
            if not (user.role.is_superadmin or user.role.is_admin):
                raise serializers.ValidationError("You do not have permission to alter the request response.")
            else:
                validated_data['response_by'] = user

        service_request = ServiceRequest.objects.create(**validated_data)
        service_request_comments = []

        # create the child comments for this service request
        if new_comments is not None:
            for comment in new_comments:
                if comment is not None:
                    comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                    comment = Comment.objects.create(content_object=service_request, comment=comment['comment'],
                                                     comment_type=comment_type, created_by=user, modified_by=user)
                    service_request_comments.append(comment.comment)

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
            if 'request' in self.context and hasattr(self.context['request'], 'user'):
                user = self.context['request'].user
            else:
                user = None

            if not user:
                raise serializers.ValidationError("User could not be identified, please contact the administrator.")

            if not (user.role.is_superadmin or user.role.is_admin):
                raise serializers.ValidationError("You do not have permission to alter the request response.")
            else:
                instance.response_by = user

        instance.request_type = validated_data.get('request_type', instance.request_type)
        instance.request_response = validated_data.get('request_response', instance.request_response)

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


# TODO: impose minimum security requirements on passwords
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

        if self.context['request'].method in ['POST', 'PUT']:
            if 'role' not in data or ('role' in data and data['role'] is None):
                data['role'] = Role.objects.filter(name='Public').first()
            if 'organization' not in data or ('organization' in data and data['organization'] is None):
                data['organization'] = Organization.objects.filter(name='Public').first()
            if 'password' not in data and self.context['request'].method == 'POST':
                raise serializers.ValidationError("password is required")
        return data

    # currently only public users can be created through the API
    def create(self, validated_data):
        requesting_user = self.context['request'].user

        created_by = validated_data.pop('created_by', None)
        modified_by = validated_data.pop('modified_by', None)
        password = validated_data['password']
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
                    raise serializers.ValidationError(message)

            # PartnerAdmins can only create users in their own org with equal or lower roles
            if requesting_user.role.is_partneradmin:
                if validated_data['role'].name in ['SuperAdmin', 'Admin']:
                    message = "You can only assign roles with equal or lower permissions to your own."
                    raise serializers.ValidationError(message)
                validated_data['organization'] = requesting_user.organization

        # only SuperAdmins and Admins can edit is_superuser, is_staff, and is_active fields
        if (requesting_user.is_authenticated
                and not (requesting_user.role.is_superadmin or requesting_user.role.is_admin)):
            validated_data['is_superuser'] = False
            validated_data['is_staff'] = False
            validated_data['is_active'] = True

        user = User.objects.create(**validated_data)
        requesting_user = user if not requesting_user.is_authenticated else requesting_user

        user.created_by = created_by or requesting_user
        user.modified_by = modified_by or requesting_user
        user.set_password(password)
        user.save()

        if message is not None:
            user_email = construct_user_request_email(user.email, message)
            if settings.ENVIRONMENT not in ['production', 'test']:
                user.user_email = user_email.__dict__

        return user

    def update(self, instance, validated_data):
        requesting_user = self.context['request'].user

        # non-admins (not SuperAdmin, Admin, or even PartnerAdmin) can only edit their first and last names and password
        if not requesting_user.is_authenticated:
            raise serializers.ValidationError("You cannot edit user data.")
        elif (requesting_user.role.is_public or requesting_user.role.is_affiliate
                or requesting_user.role.is_partner or requesting_user.role.is_partnermanager):
            if instance.id == requesting_user.id:
                instance.first_name = validated_data.get('first_name', instance.first_name)
                instance.last_name = validated_data.get('last_name', instance.last_name)
            else:
                raise serializers.ValidationError("You can only edit your own user information.")

        elif (requesting_user.role.is_superadmin or requesting_user.role.is_admin
              or requesting_user.role.is_partneradmin):
            instance.username = validated_data.get('username', instance.username)
            instance.email = validated_data.get('email', instance.email)

            if requesting_user.role.is_partneradmin:
                if validated_data['role'].name in ['SuperAdmin', 'Admin']:
                    message = "You can only assign roles with equal or lower permissions to your own."
                    raise serializers.ValidationError(message)
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

    # on create, also create child objects (circle-user M:M relates)
    def create(self, validated_data):
        # pull out user ID list from the request
        new_users = validated_data.pop('new_users', None)

        # create the Circle object
        circle = Circle.objects.create(**validated_data)

        # create a CicleUser object for each User ID submitted
        if new_users:
            if 'request' in self.context and hasattr(self.context['request'], 'user'):
                user = self.context['request'].user
            else:
                user = None

            if not user:
                raise serializers.ValidationError("User could not be identified, please contact the administrator.")

            for new_user_id in new_users:
                new_user = User.objects.get(id=new_user_id)
                CircleUser.objects.create(user=new_user, circle=circle, created_by=user, modified_by=user)

        return circle

    # on update, also update child objects (circle-user M:M relates), including additions and deletions
    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        if not user:
            raise serializers.ValidationError("User could not be identified, please contact the administrator.")

        # get the old (current) user ID list for this circle
        old_users = User.objects.filter(circles=instance.id)

        # pull out user ID list from the request
        if 'new_users' in self.initial_data:
            new_user_ids = self.initial_data['new_users']
            new_users = User.objects.filter(id__in=new_user_ids)
        else:
            new_users = []

        # update the Circle object
        instance.name = validated_data.get('name', instance.name)
        instance.modified_by = user
        instance.save()

        # identify and delete relates where user IDs are present in old list but not new list
        delete_users = list(set(old_users) - set(new_users))
        for user_id in delete_users:
            delete_user = CircleUser.objects.filter(user=user_id, circle=instance)
            delete_user.delete()

        # identify and create relates where user IDs are present in new list but not old list
        add_users = list(set(new_users) - set(old_users))
        for user_id in add_users:
            CircleUser.objects.create(user=user_id, circle=instance, created_by=user, modified_by=user)

        return instance

    class Meta:
        model = Circle
        fields = ('id', 'name', 'description', 'new_users',
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
        user = self.context['request'].user
        if not user.is_authenticated:
            permission_source = ''
        elif user.id == obj.created_by.id:
            permission_source = 'user'
        elif user.organization.id == obj.created_by.organization.id:
            permission_source = 'organization'
        else:
            permission_source = ''
        return permission_source

    class Meta:
        model = Contact
        fields = ('id', 'first_name', 'last_name', 'email', 'phone', 'affiliation', 'title', 'position', 'organization',
                  'organization_string', 'owner_organization', 'owner_organization_string',
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
        user = self.context['request'].user
        if not user.is_authenticated:
            permission_source = ''
        elif user.id == obj.created_by.id:
            permission_source = 'user'
        elif user.organization.id == obj.created_by.organization.id:
            permission_source = 'organization'
        else:
            permission_source = ''
        return permission_source

    # def create(self, validated_data):
    #     user = self.context['request'].user
    #     existing_search = Search.objects.filter(data=validated_data['data'], created_by=user)
    #     if not existing_search:
    #         validated_data['created_by'] = user
    #         validated_data['modified_by'] = user
    #         return Search.objects.create(**validated_data)
    #     else:
    #         return existing_search

    def create(self, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        if not user:
            raise serializers.ValidationError("User could not be identified, please contact the administrator.")

        validated_data['created_by'] = user
        validated_data['modified_by'] = user
        search = Search.objects.create(**validated_data)
        return search

    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

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

    # def get_eventdiagnoses(self, obj):
    #     unique_eventdiagnoses_ids = []
    #     unique_eventdiagnoses = ''
    #     eventdiagnoses = obj.eventdiagnoses.values()
    #     if eventdiagnoses is not None:
    #         for eventdiagnosis in eventdiagnoses:
    #             locationspecies = LocationSpecies.objects.filter(event_location=eventdiagnosis['id'])
    #             if locationspecies is not None:
    #                 for alocationspecies in locationspecies:
    #                     species = Species.objects.filter(id=alocationspecies.species_id).first()
    #                     if species is not None:
    #                         if species.id not in unique_eventdiagnoses_ids:
    #                             unique_eventdiagnoses_ids.append(species.id)
    #                             unique_eventdiagnoses += '; ' + species.name if unique_eventdiagnoses else species.name
    #     return unique_eventdiagnoses

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
                    unique_eventdiagnoses += '; ' + diag if unique_eventdiagnoses_ids else diag
        return unique_eventdiagnoses

    type = serializers.StringRelatedField(source='event_type')
    affected = serializers.IntegerField(source='affected_count', read_only=True)
    states = serializers.SerializerMethodField()
    counties = serializers.SerializerMethodField()
    species = serializers.SerializerMethodField()
    eventdiagnoses = serializers.SerializerMethodField()
    # states = serializers.StringRelatedField(source='administrativelevelones', many=True)
    # counties = serializers.StringRelatedField(source='administrativeleveltwos', many=True)
    # species = serializers.StringRelatedField(many=True)
    # eventdiagnoses = serializers.StringRelatedField(source='eventdiagnoses', many=True)

    class Meta:
        model = Event
        fields = ('id', 'type', 'affected', 'start_date', 'end_date', 'states', 'counties',  'species',
                  'eventdiagnoses',)


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
        user = self.context['request'].user
        if not user.is_authenticated:
            permission_source = ''
        elif user.id == obj.created_by.id:
            permission_source = 'user'
        elif user.organization.id == obj.created_by.organization.id:
            permission_source = 'organization'
        elif obj.circle_read is not None and obj.circle_write is not None and (
                user in obj.circle_read or user in obj.circle_write):
            permission_source = 'circle'
        else:
            permission_source = ''
        return permission_source

    # eventdiagnoses = EventDiagnosisSerializer(many=True)
    eventdiagnoses = serializers.SerializerMethodField()
    administrativelevelones = serializers.SerializerMethodField()
    administrativeleveltwos = serializers.SerializerMethodField()
    flyways = serializers.SerializerMethodField()
    species = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    event_status_string = serializers.StringRelatedField(source='event_status')
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ('id', 'affected_count', 'start_date', 'end_date', 'complete', 'event_type', 'event_type_string',
                  'event_status', 'event_status_string', 'eventdiagnoses', 'administrativelevelones',
                  'administrativeleveltwos', 'flyways', 'species', 'permissions', 'permission_source',)


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
        user = self.context['request'].user
        if not user.is_authenticated:
            permission_source = ''
        elif user.id == obj.created_by.id:
            permission_source = 'user'
        elif user.organization.id == obj.created_by.organization.id:
            permission_source = 'organization'
        elif obj.circle_read is not None and obj.circle_write is not None and (
                user in obj.circle_read or user in obj.circle_write):
            permission_source = 'circle'
        else:
            permission_source = ''
        return permission_source

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
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ('id', 'event_reference', 'affected_count', 'start_date', 'end_date', 'complete', 'event_type',
                  'event_type_string', 'event_status', 'event_status_string', 'public', 'eventdiagnoses',
                  'administrativelevelones', 'administrativeleveltwos', 'flyways', 'species', 'created_date',
                  'created_by', 'created_by_string', 'modified_date', 'modified_by', 'modified_by_string',
                  'permissions', 'permission_source',)


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
        user = self.context['request'].user
        if not user.is_authenticated:
            permission_source = ''
        elif user.id == obj.created_by.id:
            permission_source = 'user'
        elif user.organization.id == obj.created_by.organization.id:
            permission_source = 'organization'
        elif obj.circle_read is not None and obj.circle_write is not None and (
                user in obj.circle_read or user in obj.circle_write):
            permission_source = 'circle'
        else:
            permission_source = ''
        return permission_source

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
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string', 'legal_status',
                  'legal_status_string', 'legal_number', 'quality_check', 'public', 'superevents', 'organizations',
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
    comments = CommentSerializer(many=True)

    class Meta:
        model = ServiceRequest
        fields = ('id', 'request_type', 'request_type_string', 'request_response', 'request_response_string',
                  'response_by', 'created_time', 'created_date', 'comments',)


class EventDetailPublicSerializer(serializers.ModelSerializer):
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    event_status_string = serializers.StringRelatedField(source='event_status')
    eventlocations = EventLocationDetailPublicSerializer(many=True)
    eventdiagnoses = EventDiagnosisDetailPublicSerializer(many=True)
    eventorganizations = serializers.SerializerMethodField()  # OrganizationPublicSerializer(many=True)

    def get_eventorganizations(self, obj):
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
        user = self.context['request'].user
        if not user.is_authenticated:
            permission_source = ''
        elif user.id == obj.created_by.id:
            permission_source = 'user'
        elif user.organization.id == obj.created_by.organization.id:
            permission_source = 'organization'
        elif obj.circle_read is not None and obj.circle_write is not None and (
                user in obj.circle_read or user in obj.circle_write):
            permission_source = 'circle'
        else:
            permission_source = ''
        return permission_source

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'complete', 'start_date', 'end_date', 'affected_count',
                  'event_status', 'event_status_string','eventdiagnoses', 'eventlocations', 'eventorganizations',
                  'permissions', 'permission_source',)


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
    comments = CommentSerializer(many=True)
    servicerequests = ServiceRequestDetailSerializer(many=True)
    eventorganizations = serializers.SerializerMethodField()

    def get_eventorganizations(self, obj):
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
        user = self.context['request'].user
        if not user.is_authenticated:
            permission_source = ''
        elif user.id == obj.created_by.id:
            permission_source = 'user'
        elif user.organization.id == obj.created_by.organization.id:
            permission_source = 'organization'
        elif obj.circle_read is not None and obj.circle_write is not None and (
                user in obj.circle_read or user in obj.circle_write):
            permission_source = 'circle'
        else:
            permission_source = ''
        return permission_source

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'event_status', 'event_status_string', 'public', 'created_date', 'created_by',
                  'created_by_string', 'created_by_first_name', 'created_by_last_name', 'created_by_organization',
                  'created_by_organization_string', 'modified_date', 'modified_by', 'modified_by_string',
                  'eventdiagnoses', 'eventlocations', 'eventorganizations', 'comments', 'servicerequests',
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
    comments = CommentSerializer(many=True)
    servicerequests = ServiceRequestDetailSerializer(many=True)
    eventorganizations = serializers.SerializerMethodField()

    def get_eventorganizations(self, obj):
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
        user = self.context['request'].user
        if not user.is_authenticated:
            permission_source = ''
        elif user.id == obj.created_by.id:
            permission_source = 'user'
        elif user.organization.id == obj.created_by.organization.id:
            permission_source = 'organization'
        elif obj.circle_read is not None and obj.circle_write is not None and (
                user in obj.circle_read or user in obj.circle_write):
            permission_source = 'circle'
        else:
            permission_source = ''
        return permission_source

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string',
                  'legal_status', 'legal_status_string', 'legal_number', 'quality_check', 'public', 'superevents',
                  'eventdiagnoses', 'eventlocations', 'eventorganizations', 'comments', 'servicerequests',
                  'created_date', 'created_by', 'created_by_string', 'created_by_first_name', 'created_by_last_name',
                  'created_by_organization', 'created_by_organization_string', 'modified_date', 'modified_by',
                  'modified_by_string', 'permissions', 'permission_source',)


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
    nation = serializers.CharField()
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
