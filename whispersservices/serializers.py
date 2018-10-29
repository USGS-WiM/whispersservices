from datetime import timedelta
from django.core.mail import EmailMessage
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.forms.models import model_to_dict
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from whispersservices.models import *
from dry_rest_permissions.generics import DRYPermissionsField

# TODO: implement required field validations for nested objects

COMMENT_CONTENT_TYPES = ['event', 'superevent', 'eventlocation', 'servicerequest']


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
        instance.object_id = instance.object_id
        instance.new_content_type = instance.content_type
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modifed_by)

        instance.save()
        return instance

    class Meta:
        model = Comment
        fields = ('id', 'comment', 'comment_type', 'object_id', 'content_type_string', 'new_content_type',
                  'created_date', 'created_by', 'created_by_string',
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
                  'permissions', 'permission_source',)


# TODO: allow read-only staff field for event owner org
class EventSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    comments = CommentSerializer(many=True, read_only=True)
    new_event_diagnoses = serializers.ListField(write_only=True, required=False)
    new_organizations = serializers.ListField(write_only=True, required=False)
    new_comments = serializers.ListField(write_only=True, required=False)
    new_event_locations = serializers.ListField(write_only=True, required=False)
    new_superevents = serializers.ListField(write_only=True, required=False)
    new_service_request = serializers.JSONField(write_only=True, required=False)

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

    # TODO: properly validate child objects too rather than naively trust submitted data
    def validate(self, data):
        if 'request' in self.context and self.context['request'].method == 'POST':
            if 'new_event_locations' not in data:
                raise serializers.ValidationError("new_event_locations is a required field")
            # 1. Not every location needs a start date at initiation, but at least one location must.
            # 2. Not every location needs a species at initiation, but at least one location must.
            # 3. location_species Population >= max(estsick, knownsick) + max(estdead, knowndead)
            # 4. For morbidity/mortality events, there must be at least one number between sick, dead, estimated_sick,
            #    and estimated_dead for at least one species in the event at the time of event initiation.
            #    (sick + dead + estimated_sick + estimated_dead >= 1)
            # 5. estimated_sick must be higher than known sick (estimated_sick > sick).
            # 6. estimated dead must be higher than known dead (estimated_dead > dead).
            # 7. Every location needs at least one comment, which must be one of the following types:
            #    Site description, History, Environmental factors, Clinical signs
            if 'new_event_locations' in data:
                comments_is_valid = []
                required_comment_types = ['site_description', 'history', 'environmental_factors', 'clinical_signs']
                min_start_date = False
                min_location_species = False
                min_species_count = False
                pop_is_valid = []
                est_sick_is_valid = True
                est_dead_is_valid = True
                details = []
                mortality_morbidity = EventType.objects.filter(name='Mortality/Morbidity').first()
                for item in data['new_event_locations']:
                    if [i for i in required_comment_types if i in item]:
                        comments_is_valid.append(True)
                    else:
                        comments_is_valid.append(False)
                    if 'start_date' in item:
                        try:
                            datetime.strptime(item['start_date'], '%Y-%m-%d').date()
                        except ValueError:
                            details.append("All start_date values must be valid dates in ISO format ('YYYY-MM-DD').")
                        min_start_date = True
                    if 'new_location_species' in item:
                        for spec in item['new_location_species']:
                            if 'species' in spec and spec['species'] is not None:
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
                                if 'dead_count_estimated' in spec and spec['dead_count_estimated'] > 0:
                                    min_species_count = True
                                elif 'dead_count' in spec and spec['dead_count'] > 0:
                                    min_species_count = True
                                elif 'sick_count_estimated' in spec and spec['sick_count_estimated'] > 0:
                                    min_species_count = True
                                elif 'sick_count' in spec and spec['sick_count'] > 0:
                                    min_species_count = True
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
                if not min_species_count:
                    message = "At least one new_location_species requires at least one species count in any of the"
                    message += " following fields: dead_count_estimated, dead_count, sick_count_estimated, sick_count."
                    details.append(message)
                if not est_sick_is_valid:
                    details.append("Estimated sick count must always be more than known sick count.")
                if not est_dead_is_valid:
                    details.append("Estimated dead count must always be more than known dead count.")
                if details:
                    raise serializers.ValidationError(details)

            # 1. End Date is Mandatory for event to be marked as 'Complete'. Should always be after Start Date.
            # 2. For morbidity/mortality events, there must be at least one number between sick, dead, estimated_sick,
            #   and estimated_dead per species at the time of event completion.
            #   (sick + dead + estimated_sick + estimated_dead >= 1)
            if 'complete' in data and data['complete'] is True:
                location_message = "The event may not be marked complete until all of its locations have an end date"
                location_message += " and each location's end date is after that location's start date."
                if 'new_event_locations' not in data:
                    raise serializers.ValidationError(location_message)
                else:
                    end_date_is_valid = True
                    species_count_is_valid = []
                    est_sick_is_valid = True
                    est_dead_is_valid = True
                    details = []
                    mortality_morbidity = EventType.objects.filter(name='Mortality/Morbidity').first()
                    for item in data['new_event_locations']:
                        for spec in item['location_species']:
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
                                if not start_date < end_date:
                                    end_date_is_valid = False
                            else:
                                end_date_is_valid = False
                            if ('sick_count_estimated' in spec and spec['sick_count_estimated'] is not None
                                    and 'sick_count' in spec and spec['sick_count'] is not None
                                    and not spec['sick_count_estimated'] > spec['sick_count']):
                                est_sick_is_valid = False
                            if ('dead_count_estimated' in spec and spec['dead_count_estimated'] is not None
                                    and 'dead_count' in spec and spec['dead_count'] is not None
                                    and not spec['dead_count_estimated'] > spec['dead_count']):
                                est_dead_is_valid = False
                            if data['event_type'] == mortality_morbidity.id:
                                if 'dead_count_estimated' in spec and spec['dead_count_estimated'] > 0:
                                    species_count_is_valid.append(True)
                                elif 'dead_count' in spec and spec['dead_count'] > 0:
                                    species_count_is_valid.append(True)
                                elif 'sick_count_estimated' in spec and spec['sick_count_estimated'] > 0:
                                    species_count_is_valid.append(True)
                                elif 'sick_count' in spec and spec['sick_count'] > 0:
                                    species_count_is_valid.append(True)
                                else:
                                    species_count_is_valid.append(False)
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
                    if details:
                        raise serializers.ValidationError(details)
        return data

    def create(self, validated_data):
        # TODO: figure out if this logic is necessary, see: https://www.django-rest-framework.org/api-guide/requests/#user
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        if not user:
            raise serializers.ValidationError("User could not be identified, please contact the administrator.")

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
                        EventOrganization.objects.create(event=event, organization=org,
                                                         created_by=user, modified_by=user)
        else:
            EventOrganization.objects.create(event=event, organization=user.organization,
                                             created_by=user, modified_by=user)

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
            if new_service_request is not None and new_service_request in [1, 2]:
                new_comments = new_service_request.pop('new_comments', None)
                request_type = ServiceRequestType.objects.filter(pk=new_service_request).first()
                service_request = ServiceRequest.objects.create(event=event, request_type=request_type,
                                                                created_by=user, modified_by=user)

                # create the child comments for this service request
                if new_comments is not None:
                    for comment in new_comments:
                        if comment is not None:
                            comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                            Comment.objects.create(content_object=service_request, comment=comment['comment'],
                                                   comment_type=comment_type, created_by=user, modified_by=user)

                # construct and send the request email
                subject = "Service request for Event " + str(service_request.event.id)
                body = "A user  (" + user.email + ") with " + user.organization.name + " has requested "
                body += service_request.request_type.name + " for event " + str(
                    service_request.event.id) + ".\r\n\r\n"
                from_address = user.email
                to_list = ['nwhc-epi@usgs.gov', ]
                bcc_list = []
                reply_to_list = [user.email, ]
                headers = None  # {'Message-ID': 'foo'}
                email = EmailMessage(subject, body, from_address, to_list, bcc_list, reply_to=reply_to_list,
                                     headers=headers)
                # TODO: uncomment next block when code is deployed on the production server
                # try:
                #     email.send(fail_silently=False)
                # except TypeError:
                #     message = "Service Request saved but send email failed, please contact the administrator."
                #     raise serializers.ValidationError(message)

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

                    # create object for comment creation while removing unserialized fields for EventLocation
                    comments = {'site_description': event_location.pop('site_description', None),
                                'history': event_location.pop('history', None),
                                'environmental_factors': event_location.pop('environmental_factors', None),
                                'clinical_signs': event_location.pop('clinical_signs', None),
                                'other': event_location.pop('comment', None)}

                    # create the event_location and return object for use in event_location_contacts object
                    event_location['created_by'] = user
                    event_location['modified_by'] = user

                    # if the event_location has no name value but does have a gnis_name value,
                    # then copy the value of gnis_name to name
                    # this need only happen on creation since the two fields should maintain no durable relationship
                    if event_location['name'] == '' and event_location['gnis_name'] != '':
                        event_location['name'] = event_location['gnis_name']
                    evt_location = EventLocation.objects.create(**event_location)

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

                            location_contact['created_by'] = user
                            location_contact['modified_by'] = user
                            EventLocationContact.objects.create(**location_contact)

                    # Create EventLocationSpecies
                    if new_location_species is not None:
                        for location_spec in new_location_species:
                            location_spec['event_location'] = evt_location
                            new_species_diagnoses = location_spec.pop('new_species_diagnoses', None)

                            # Convert ids to ForeignKey objects
                            location_spec['species'] = Species.objects.filter(pk=location_spec['species']).first()
                            location_spec['age_bias'] = AgeBias.objects.filter(pk=location_spec['age_bias']).first()
                            location_spec['sex_bias'] = SexBias.objects.filter(pk=location_spec['sex_bias']).first()

                            location_spec['created_by'] = user
                            location_spec['modified_by'] = user
                            location_species = LocationSpecies.objects.create(**location_spec)

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
                                        species_diagnosis = SpeciesDiagnosis.objects.create(**spec_diag)

                                        # create the child organizations for this species diagnosis
                                        if new_species_diagnosis_organizations is not None:
                                            for org_id in new_species_diagnosis_organizations:
                                                if org_id is not None:
                                                    org = Organization.objects.filter(pk=org_id).first()
                                                    if org is not None:
                                                        SpeciesDiagnosisOrganization.objects.create(
                                                            species_diagnosis=species_diagnosis, organization=org,
                                                            created_by=user, modified_by=user)

        # create the child event diagnoses for this event
        pending = Diagnosis.objects.filter(name='Pending').first()
        undetermined = Diagnosis.objects.filter(name='Undetermined').first()

        # remove Pending or Undetermined if in the list because one or the other already exists from event save
        [new_event_diagnoses.remove(x) for x in new_event_diagnoses if x['diagnosis'] in [pending.id, undetermined.id]]

        if new_event_diagnoses is not None:
            # Can only use diagnoses that are already used by this event's species diagnoses
            valid_diagnosis_ids = SpeciesDiagnosis.objects.filter(
                location_species__event_location__event=event.id
            ).exclude(id__in=[pending.id, undetermined.id]).values_list('diagnosis', flat=True).distinct()
            # If any new event diagnoses have a matching species diagnosis, then continue, else ignore
            if valid_diagnosis_ids is not None:
                for event_diagnosis in new_event_diagnoses:
                    if event_diagnosis in valid_diagnosis_ids:
                        diagnosis = Diagnosis.objects.filter(pk=event_diagnosis['diagnosis']).first()
                        EventDiagnosis.objects.create(event=event, diagnosis=diagnosis, **event_diagnosis)
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
            else:
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
                    if not location.end_date or not location.start_date or not location.end_date > location.start_date:
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
            validated_data.pop('new_eservice_requests')

        # update the Event object
        instance.event_type = validated_data.get('event_type', instance.event_type)
        instance.event_reference = validated_data.get('event_reference', instance.event_reference)
        instance.complete = validated_data.get('complete', instance.complete)
        instance.start_date = validated_data.get('start_date', instance.start_date)
        instance.end_date = validated_data.get('end_date', instance.end_date)
        instance.affected_count = validated_data.get('affected_count', instance.affected_count)
        instance.staff = instance.staff
        instance.event_status = instance.event_status
        instance.legal_status = instance.legal_status
        instance.legal_number = instance.legal_number
        instance.public = validated_data.get('public', instance.public)
        instance.circle_read = validated_data.get('circle_read', instance.circle_read)
        instance.circle_write = validated_data.get('circle_write', instance.circle_write)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)
        instance.save()

        return instance

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'public', 'circle_read', 'circle_write', 'organizations', 'contacts', 'comments',
                  'new_event_diagnoses', 'new_organizations', 'new_comments', 'new_event_locations', 'new_superevents',
                  'new_service_request', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string', 'permissions', 'permission_source',)


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

    # TODO: properly validate child objects too rather than naively trust submitted data
    def validate(self, data):
        if 'request' in self.context and self.context['request'].method == 'POST':
            if 'new_event_locations' not in data:
                raise serializers.ValidationError("new_event_locations is a required field")
            # 1. Not every location needs a start date at initiation, but at least one location must.
            # 2. Not every location needs a species at initiation, but at least one location must.
            # 3. location_species Population >= max(estsick, knownsick) + max(estdead, knowndead)
            # 4. For morbidity/mortality events, there must be at least one number between sick, dead, estimated_sick,
            #    and estimated_dead for at least one species in the event at the time of event initiation.
            #    (sick + dead + estimated_sick + estimated_dead >= 1)
            # 5. estimated_sick must be higher than known sick (estimated_sick > sick).
            # 6. estimated dead must be higher than known dead (estimated_dead > dead).
            # 7. Every location needs at least one comment, which must be one of the following types:
            #    Site description, History, Environmental factors, Clinical signs
            if 'new_event_locations' in data:
                comments_is_valid = []
                required_comment_types = ['site_description', 'history', 'environmental_factors', 'clinical_signs']
                min_start_date = False
                min_location_species = False
                min_species_count = False
                pop_is_valid = []
                est_sick_is_valid = True
                est_dead_is_valid = True
                details = []
                mortality_morbidity = EventType.objects.filter(name='Mortality/Morbidity').first()
                for item in data['new_event_locations']:
                    if [i for i in required_comment_types if i in item]:
                        comments_is_valid.append(True)
                    else:
                        comments_is_valid.append(False)
                    if 'start_date' in item:
                        try:
                            datetime.strptime(item['start_date'], '%Y-%m-%d').date()
                        except ValueError:
                            details.append("All start_date values must be valid dates in ISO format ('YYYY-MM-DD').")
                        min_start_date = True
                    if 'new_location_species' in item:
                        for spec in item['new_location_species']:
                            if 'species' in spec and spec['species'] is not None:
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
                                if 'dead_count_estimated' in spec and spec['dead_count_estimated'] > 0:
                                    min_species_count = True
                                elif 'dead_count' in spec and spec['dead_count'] > 0:
                                    min_species_count = True
                                elif 'sick_count_estimated' in spec and spec['sick_count_estimated'] > 0:
                                    min_species_count = True
                                elif 'sick_count' in spec and spec['sick_count'] > 0:
                                    min_species_count = True
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
                if not min_species_count:
                    message = "At least one new_location_species requires at least one species count in any of the"
                    message += " following fields: dead_count_estimated, dead_count, sick_count_estimated, sick_count."
                    details.append(message)
                if not est_sick_is_valid:
                    details.append("Estimated sick count must always be more than known sick count.")
                if not est_dead_is_valid:
                    details.append("Estimated dead count must always be more than known dead count.")
                if details:
                    raise serializers.ValidationError(details)

            # 1. End Date is Mandatory for event to be marked as 'Complete'. Should always be after Start Date.
            # 2. For morbidity/mortality events, there must be at least one number between sick, dead, estimated_sick,
            #   and estimated_dead per species at the time of event completion.
            #   (sick + dead + estimated_sick + estimated_dead >= 1)
            if 'complete' in data and data['complete'] is True:
                location_message = "The event may not be marked complete until all of its locations have an end date"
                location_message += " and each location's end date is after that location's start date."
                if 'new_event_locations' not in data:
                    raise serializers.ValidationError(location_message)
                else:
                    end_date_is_valid = True
                    species_count_is_valid = []
                    est_sick_is_valid = True
                    est_dead_is_valid = True
                    details = []
                    mortality_morbidity = EventType.objects.filter(name='Mortality/Morbidity').first()
                    for item in data['new_event_locations']:
                        for spec in item['location_species']:
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
                                if not start_date < end_date:
                                    end_date_is_valid = False
                            else:
                                end_date_is_valid = False
                            if ('sick_count_estimated' in spec and spec['sick_count_estimated'] is not None
                                    and 'sick_count' in spec and spec['sick_count'] is not None
                                    and not spec['sick_count_estimated'] > spec['sick_count']):
                                est_sick_is_valid = False
                            if ('dead_count_estimated' in spec and spec['dead_count_estimated'] is not None
                                    and 'dead_count' in spec and spec['dead_count'] is not None
                                    and not spec['dead_count_estimated'] > spec['dead_count']):
                                est_dead_is_valid = False
                            if data['event_type'] == mortality_morbidity.id:
                                if 'dead_count_estimated' in spec and spec['dead_count_estimated'] > 0:
                                    species_count_is_valid.append(True)
                                elif 'dead_count' in spec and spec['dead_count'] > 0:
                                    species_count_is_valid.append(True)
                                elif 'sick_count_estimated' in spec and spec['sick_count_estimated'] > 0:
                                    species_count_is_valid.append(True)
                                elif 'sick_count' in spec and spec['sick_count'] > 0:
                                    species_count_is_valid.append(True)
                                else:
                                    species_count_is_valid.append(False)
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
                    if details:
                        raise serializers.ValidationError(details)
        return data

    def create(self, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        if not user:
            raise serializers.ValidationError("User could not be identified, please contact the administrator.")

        comment_types = {'site_description': 'Site description', 'history': 'History',
                         'environmental_factors': 'Environmental factors', 'clinical_signs': 'Clinical signs',
                         'general': 'General'}

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
                        EventOrganization.objects.create(event=event, organization=org,
                                                         created_by=user, modified_by=user)
        else:
            EventOrganization.objects.create(event=event, organization=user.organization,
                                             created_by=user, modified_by=user)

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
            if new_service_request is not None and new_service_request in [1, 2]:
                new_comments = new_service_request.pop('new_comments', None)
                request_type = ServiceRequestType.objects.filter(pk=new_service_request).first()
                service_request = ServiceRequest.objects.create(event=event, request_type=request_type,
                                                                created_by=user, modified_by=user)

                # create the child comments for this service request
                if new_comments is not None:
                    for comment in new_comments:
                        if comment is not None:
                            comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                            Comment.objects.create(content_object=service_request, comment=comment['comment'],
                                                   comment_type=comment_type, created_by=user, modified_by=user)

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

                    # create object for comment creation while removing unserialized fields for EventLocation
                    comments = {'site_description': event_location.pop('site_description', None),
                                'history': event_location.pop('history', None),
                                'environmental_factors': event_location.pop('environmental_factors', None),
                                'clinical_signs': event_location.pop('clinical_signs', None),
                                'general': event_location.pop('comment', None)}

                    # create the event_location and return object for use in event_location_contacts object
                    event_location['created_by'] = user
                    event_location['modified_by'] = user

                    # if the event_location has no name value but does have a gnis_name value,
                    # then copy the value of gnis_name to name
                    # this need only happen on creation since the two fields should maintain no durable relationship
                    if event_location['name'] == '' and event_location['gnis_name'] != '':
                        event_location['name'] = event_location['gnis_name']
                    evt_location = EventLocation.objects.create(**event_location)

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

                            location_contact['created_by'] = user
                            location_contact['modified_by'] = user
                            EventLocationContact.objects.create(**location_contact)

                    # Create EventLocationSpecies
                    if new_location_species is not None:
                        for location_spec in new_location_species:
                            location_spec['event_location'] = evt_location
                            new_species_diagnoses = location_spec.pop('new_species_diagnoses', None)

                            # Convert ids to ForeignKey objects
                            location_spec['species'] = Species.objects.filter(pk=location_spec['species']).first()
                            location_spec['age_bias'] = AgeBias.objects.filter(pk=location_spec['age_bias']).first()
                            location_spec['sex_bias'] = SexBias.objects.filter(pk=location_spec['sex_bias']).first()

                            location_spec['created_by'] = user
                            location_spec['modified_by'] = user
                            location_species = LocationSpecies.objects.create(**location_spec)

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
                                        species_diagnosis = SpeciesDiagnosis.objects.create(**spec_diag)

                                        # create the child organizations for this species diagnosis
                                        if new_species_diagnosis_organizations is not None:
                                            for org_id in new_species_diagnosis_organizations:
                                                if org_id is not None:
                                                    org = Organization.objects.filter(pk=org_id).first()
                                                    if org is not None:
                                                        SpeciesDiagnosisOrganization.objects.create(
                                                            species_diagnosis=species_diagnosis, organization=org,
                                                            created_by=user, modified_by=user)

        # create the child event diagnoses for this event
        pending = Diagnosis.objects.filter(name='Pending').first()
        undetermined = Diagnosis.objects.filter(name='Undetermined').first()

        # remove Pending or Undetermined if in the list because one or the other already exists from event save
        [new_event_diagnoses.remove(x) for x in new_event_diagnoses if x['diagnosis'] in [pending.id, undetermined.id]]

        if new_event_diagnoses is not None:
            # Can only use diagnoses that are already used by this event's species diagnoses
            valid_diagnosis_ids = SpeciesDiagnosis.objects.filter(
                location_species__event_location__event=event.id
            ).exclude(id__in=[pending.id, undetermined.id]).values_list('diagnosis', flat=True).distinct()
            # If any new event diagnoses have a matching species diagnosis, then continue, else ignore
            if valid_diagnosis_ids is not None:
                for event_diagnosis in new_event_diagnoses:
                    if event_diagnosis in valid_diagnosis_ids:
                        diagnosis = Diagnosis.objects.filter(pk=event_diagnosis['diagnosis']).first()
                        EventDiagnosis.objects.create(event=event, diagnosis=diagnosis, **event_diagnosis)
                # Now that we have the new event diagnoses created,
                # check for existing Pending or Undetermined records and delete them
                event_diagnoses = EventDiagnosis.objects.filter(event=event.id)
                [diag.delete() for diag in event_diagnoses if diag.diagnosis.id in [pending.id, undetermined.id]]

        return event

    # TODO: properly validate child objects too rather than naively trust submitted data
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
                    if not location.end_date or not location.start_date or not location.end_date > location.start_date:
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
            validated_data.pop('new_eservice_requests')

        # update the Event object
        instance.event_type = validated_data.get('event_type', instance.event_type)
        instance.event_reference = validated_data.get('event_reference', instance.event_reference)
        instance.complete = validated_data.get('complete', instance.complete)
        instance.start_date = validated_data.get('start_date', instance.start_date)
        instance.end_date = validated_data.get('end_date', instance.end_date)
        instance.affected_count = validated_data.get('affected_count', instance.affected_count)
        instance.staff = validated_data.get('staff', instance.staff)
        instance.event_status = validated_data.get('event_status', instance.event_status)
        instance.quality_check = validated_data.get('quality_check', instance.quality_check)
        instance.legal_status = validated_data.get('legal_status', instance.legal_status)
        instance.legal_number = validated_data.get('legal_number', instance.legal_number)
        instance.public = validated_data.get('public', instance.public)
        instance.circle_read = validated_data.get('circle_read', instance.circle_read)
        instance.circle_write = validated_data.get('circle_write', instance.circle_write)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)
        instance.save()

        return instance

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string',
                  'legal_status', 'legal_status_string', 'legal_number', 'quality_check', 'public',
                  'circle_read', 'circle_write', 'superevents', 'organizations', 'contacts', 'comments',
                  'new_event_diagnoses', 'new_organizations', 'new_comments', 'new_event_locations', 'new_superevents',
                  'new_service_request', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string', 'permissions', 'permission_source',)


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

        # calculate the priorty value:
        # Sort by owner organization first, then by order of entry.
        priority = 1
        evt_orgs = EventOrganization.objects.filter(organization=event_organization.organization).order_by('id')
        for evt_org in evt_orgs:
            if evt_org.id == event_organization.id:
                event_organization.priority = priority
            else:
                evt_org.priority = priority
                evt_org.save()
            priority += 1

        event_organization.save()

        return event_organization

    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        instance.event = validated_data.get('event', instance.event)
        instance.organization = validated_data.get('organization', instance.organization)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

        # calculate the priorty value:
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
    site_description = serializers.CharField(write_only=True, required=False)
    history = serializers.CharField(write_only=True, required=False)
    environmental_factors = serializers.CharField(write_only=True, required=False)
    clinical_signs = serializers.CharField(write_only=True, required=False)
    comment = serializers.CharField(write_only=True, required=False)

    def validate(self, data):

        message_complete = "Locations from a complete event may not be changed"
        message_complete += " unless the event is first re-opened by the event owner or an administrator."

        # TODO: repeat this code block on all event.complete checks
        if 'request' in self.context:
            # if this is a new EventLocation check if the Event is complete
            if self.context['request'].method == 'POST' and data['event'].complete:
                raise serializers.ValidationError(message_complete)
            # else this is an existing EventLocation so check if this is an update and if parent Event is complete
            elif self.context['request'].method in ['PUT', 'PATCH'] and self.instance.event.complete:
                raise serializers.ValidationError(message_complete)

        # 1. Not every location needs a start date at initiation, but at least one location must.
        # 2. Not every location needs a species at initiation, but at least one location must.
        # 3. location_species Population >= max(estsick, knownsick) + max(estdead, knowndead)
        # 4. For morbidity/mortality events, there must be at least one number between sick, dead, estimated_sick,
        #    and estimated_dead for at least one species in the event at the time of event initiation.
        #    (sick + dead + estimated_sick + estimated_dead >= 1)
        # 5. estimated_sick must be higher than known sick (estimated_sick > sick).
        # 6. estimated dead must be higher than known dead (estimated_dead > dead).
        # 7. Every location needs at least one comment, which must be one of the following types:
        #    Site description, History, Environmental factors, Clinical signs
        comments_is_valid = []
        required_comment_types = ['site_description', 'history', 'environmental_factors', 'clinical_signs']
        min_start_date = False
        min_location_species = False
        min_species_count = False
        pop_is_valid = []
        est_sick_is_valid = True
        est_dead_is_valid = True
        details = []
        mortality_morbidity = EventType.objects.filter(name='Mortality/Morbidity').first()

        if [i for i in required_comment_types if i in data]:
            comments_is_valid.append(True)
        else:
            comments_is_valid.append(False)
        if 'start_date' in data:
            min_start_date = True
        if 'new_location_species' in data:
            for spec in data['new_location_species']:
                if 'species' in spec and spec['species'] is not None:
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
                if data['event'].event_type.id == mortality_morbidity.id:
                    if 'dead_count_estimated' in spec and spec['dead_count_estimated'] > 0:
                        min_species_count = True
                    elif 'dead_count' in spec and spec['dead_count'] > 0:
                        min_species_count = True
                    elif 'sick_count_estimated' in spec and spec['sick_count_estimated'] > 0:
                        min_species_count = True
                    elif 'sick_count' in spec and spec['sick_count'] > 0:
                        min_species_count = True
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
        if not min_species_count:
            message = "At least one new_location_species requires at least one species count in any of the"
            message += " following fields: dead_count_estimated, dead_count, sick_count_estimated, sick_count."
            details.append(message)
        if not est_sick_is_valid:
            details.append("Estimated sick count must always be more than known sick count.")
        if not est_dead_is_valid:
            details.append("Estimated dead count must always be more than known dead count.")
        if details:
            raise serializers.ValidationError(details)

        return data

    def create(self, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        if not user:
            raise serializers.ValidationError("User could not be identified, please contact the administrator.")

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

        # create the event_location and return object for use in event_location_contacts object
        # validated_data['created_by'] = user
        # validated_data['modified_by'] = user
        evt_location = EventLocation.objects.create(**validated_data)

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

                location_contact['created_by'] = user
                location_contact['modified_by'] = user
                EventLocationContact.objects.create(**location_contact)

        # Create EventLocationSpecies
        if new_location_species is not None:
            for location_spec in new_location_species:
                location_spec['event_location'] = evt_location
                new_species_diagnoses = location_spec.pop('new_species_diagnoses', None)

                # Convert ids to ForeignKey objects
                location_spec['species'] = Species.objects.filter(pk=location_spec['species']).first()
                location_spec['age_bias'] = AgeBias.objects.filter(pk=location_spec['age_bias']).first()
                location_spec['sex_bias'] = SexBias.objects.filter(pk=location_spec['sex_bias']).first()

                location_spec['created_by'] = user
                location_spec['modified_by'] = user
                LocationSpecies.objects.create(**location_spec)

                # create the child species diagnoses for this event
                if new_species_diagnoses is not None:
                    for diagnosis_id in new_species_diagnoses:
                        if diagnosis_id is not None:
                            diagnosis = Diagnosis.objects.filter(pk=diagnosis_id).first()
                            if diagnosis is not None:
                                SpeciesDiagnosis.objects.create(
                                    location_speccies=location_spec, diagnosis=diagnosis,
                                    created_by=user, modified_by=user)

        # calculate the priority value:
        # Group by county first. Order counties by decreasing number of sick plus dead (for morbidity/mortality events)
        # or number_positive (for surveillance). Order locations within counties similarly.
        # TODO: figure out the following rule:
        # If no numbers provided then order by country, state, and county (alphabetical).
        priority = 1
        self_priority_updated = False
        # get all event_locations for the parent event except self, and sort by county name asc and affected count desc
        evtlocs = EventLocation.objects.filter(
            event=evt_location.event.id
        ).exclude(
            id=evt_location.id
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
            evt_location.priority = priority
        else:
            location_species = LocationSpecies.objects.filter(event_location=evt_location.id)
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
                        and evt_location.administrative_level_two.name <= evtloc.administrative_level_two.name):
                    if evt_location.event.event_type.id == 1:
                        if self_sick_dead_count >= (evtloc.affected_count or 0):
                            evt_location.priority = priority
                            priority += 1
                            self_priority_updated = True
                    elif evt_location.event.event_type.id == 2:
                        if self_positive_count >= (evtloc.affected_count or 0):
                            evt_location.priority = priority
                            priority += 1
                            self_priority_updated = True
                evtloc.priority = priority
                evtloc.save()
                priority += 1

        evt_location.priority = evt_location.priority if self_priority_updated else priority
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

        # update the EventLocation object
        instance.name = validated_data.get('name', instance.name)
        instance.event = validated_data.get('event', instance.event)
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
        instance.priority = validated_data.get('priority', instance.priority)
        instance.land_ownership = validated_data.get('land_ownership', instance.land_ownership)
        instance.gnis_name = validated_data.get('gnis_name', instance.gnis_name)
        instance.gnis_id = validated_data.get('gnis_id', instance.gnis_id)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

        # if an event_location has no name value but does have a gnis_name value, copy the value of gnis_name to name
        # this need only happen on creation since the two fields should maintain no durable relationship
        if validated_data['name'] == '' and validated_data['gnis_name'] != '':
            validated_data['name'] = validated_data['gnis_name']

        # calculate the priorty value:
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

        instance.priority = instance.priority if self_priority_updated else priority
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


class EventLocationContactSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        if data['event_location'].event.complete:
            message = "Contacts from a location from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

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


class AdministrativeLevelTwoPublicSerializer(serializers.ModelSerializer):
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')

    class Meta:
        model = AdministrativeLevelTwo
        fields = ('id', 'name', 'administrative_level_one', 'administrative_level_one_string', 'points',
                  'centroid_latitude', 'centroid_longitude', 'fips_code',)


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


class EventLocationFlywaySerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        if data['event_location'].event.complete:
            message = "Flyways from a location from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

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

        if data['event_location'].event.complete:
            message = "Species from a location from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        return data

    def create(self, validated_data):

        location_species = LocationSpecies.objects.create(**validated_data)

        # calculate the priorty value:
        # Order species by decreasing number of sick plus dead (for morbidity/mortality events)
        # or number_positive (for surveillance).
        # If no numbers were provided then order by SpeciesName (alphabetical).
        priority = 1
        self_priority_updated = False
        # get all location_species for the parent event_location except self, and sort by affected count desc
        locspecs = LocationSpecies.objects.filter(
            event_location=validated_data['event_location'].id
        ).exclude(
            id=location_species.id
        ).annotate(
            sick_dead_ct=(Coalesce(F('sick_count'), 0) + Coalesce(F('sick_count_estimated'), 0)
                          + Coalesce(F('dead_count'), 0) + Coalesce(F('dead_count_estimated'), 0))
        ).annotate(
            positive_ct=Sum('speciesdiagnoses__positive_count', filter=Q(event_location__event__event_type__exact=2))
        ).annotate(
            affected_count=Coalesce(F('sick_dead_ct'), 0) + Coalesce(F('positive_ct'), 0)
        ).order_by('-affected_count', 'species__name')
        if not locspecs:
            location_species.priority = priority
        else:
            self_sick_dead_count = (max(location_species.dead_count_estimated or 0, location_species.dead_count or 0)
                                    + max(location_species.sick_count_estimated or 0, location_species.sick_count or 0))
            species_dx_positive_counts = SpeciesDiagnosis.objects.filter(
                location_species_id__exact=location_species.id).values_list(
                'positive_count', flat=True).exclude(positive_count__isnull=True)
            self_positive_count = sum(species_dx_positive_counts)
            for locspec in locspecs:
                # if self has not been updated,
                # and self affected count is greater than or equal to this locspec affected count,
                # first update self priority then update this locspec priority
                if not self_priority_updated:
                    if location_species.event_location.event.event_type.id == 1:
                        if self_sick_dead_count >= (locspec.affected_count or 0):
                            location_species.priority = priority
                            priority += 1
                            self_priority_updated = True
                    elif location_species.event_location.event.event_type.id == 2:
                        if self_positive_count >= (locspec.affected_count or 0):
                            location_species.priority = priority
                            priority += 1
                            self_priority_updated = True
                locspec.priority = priority
                locspec.save()
                priority += 1

        location_species.priority = location_species.priority if self_priority_updated else priority
        location_species.save()

        return location_species

    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        # update the LocationSpecies object
        instance.event_location = validated_data.get('event_location', instance.event_location)
        instance.species = validated_data.get('species', instance.species)
        instance.population_count = validated_data.get('population_count', instance.population_count)
        instance.sick_count = validated_data.get('sick_count', instance.sick_count)
        instance.dead_count = validated_data.get('dead_count', instance.dead_count)
        instance.sick_count_estimated = validated_data.get('sick_count_estimated', instance.sick_count_estimated)
        instance.dead_count_estimated = validated_data.get('dead_count_estimated', instance.dead_count_estimated)
        instance.priority = validated_data.get('priority', instance.priority)
        instance.captive = validated_data.get('captive', instance.captive)
        instance.age_bias = validated_data.get('age_bias', instance.age_bias)
        instance.sex_bias = validated_data.get('sex_bias', instance.sex_bias)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

        if instance.population_count is not None:
            dead_count = 0
            sick_count = 0
            if instance.dead_count_estimated or instance.dead_count:
                dead_count = max(instance.dead_count_estimated or 0, instance.dead_count or 0)
            if instance.sick_count_estimated or instance.sick_count:
                sick_count = max(instance.sick_count_estimated or 0, instance.sick_count or 0)
            if instance.population_count < dead_count + sick_count:
                message = "location_species population_count cannot be less than the sum of dead_count"
                message += " and sick_count (where those counts are the maximum of the estimated or known count)"
                raise serializers.ValidationError(message)

        # calculate the priorty value:
        # Order species by decreasing number of sick plus dead (for morbidity/mortality events)
        # or number_positive (for surveillance).
        # If no numbers were provided then order by SpeciesName (alphabetical).
        priority = 1
        self_priority_updated = False
        # get all location_species for the parent event_location except self, and sort by affected count desc
        locspecs = LocationSpecies.objects.filter(
            event_location=validated_data['event_location'].id
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

        instance.priority = instance.priority if self_priority_updated else priority
        instance.save()

        return instance

    class Meta:
        model = LocationSpecies
        fields = ('id', 'event_location', 'species', 'population_count', 'sick_count', 'dead_count',
                  'sick_count_estimated', 'dead_count_estimated', 'priority', 'captive', 'age_bias', 'sex_bias',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class SpeciesPublicSerializer(serializers.ModelSerializer):

    class Meta:
        model = Species
        fields = ('id', 'name', 'class_name', 'order_name', 'family_name', 'sub_family_name', 'genus_name',
                  'species_latin_name', 'subspecies_latin_name', 'tsn',)


class SpeciesSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = Species
        fields = ('id', 'name', 'class_name', 'order_name', 'family_name', 'sub_family_name', 'genus_name',
                  'species_latin_name', 'subspecies_latin_name', 'tsn',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


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


class DiagnosisPublicSerializer(serializers.ModelSerializer):
    diagnosis_type_string = serializers.StringRelatedField(source='diagnosis_type')

    class Meta:
        model = Diagnosis
        fields = ('name', 'diagnosis_type', 'diagnosis_type_string')


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

        if data['event'].complete:
            message = "Diagnosis from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        event_specdiags = SpeciesDiagnosis.objects.filter(
            location_species__event_location__event=data['event'].id).values_list('diagnosis', flat=True).distinct()
        diagnosis = Diagnosis.objects.filter(id=data['diagnosis'].id).first()
        if diagnosis is not None and (not event_specdiags or diagnosis.id not in event_specdiags
                                      or diagnosis.name in ['Pending', 'Undetermined']):
            message = "A diagnosis for Event Diagnosis must match a diagnosis of a Species Diagnosis of this event."
            raise serializers.ValidationError(message)

        return data

    def create(self, validated_data):

        # TODO: Check on this... the rule seeme pointless unless a user can manually assign Undetermined, which seemingly contradicts other rules
        # # If have "Undetermined" at the event level, should have no other diagnoses at event level.
        # if validated_data['event'].complete and validated_data['diagnosis'] == undetermined.id:
        #     [evt_diag.delete() for evt_diag in get_event_diagnoses()]

        event_diagnosis = EventDiagnosis.objects.create(**validated_data)

        # Now that we have the new event diagnoses created,
        # check for existing Pending records and delete them
        evt_diags = EventDiagnosis.objects.filter(event=validated_data['event'].id)
        [evt_diag.delete() for evt_diag in evt_diags if evt_diag.diagnosis.name == 'Pending']

        # calculate the priorty value:
        # TODO: following rule cannot be applied because cause field does not exist on this model
        # Order event diagnoses by causal (cause of death first, then cause of sickness,
        # then incidental findings, then unknown) and within each causal category...
        # (TODO: NOTE following rule is valid and enforceable right now:)
        # ...by diagnosis name (alphabetical).
        priority = 1
        self_priority_updated = False
        # get all event_diagnoses for the parent event except self, and sort by diagnosis name ascending
        evtdiags = EventDiagnosis.objects.filter(
            event=event_diagnosis.event).exclude(id=event_diagnosis.id).order_by('diagnosis__name')
        for evtdiag in evtdiags:
            # if self has not been updated and self diagnosis less than or equal to this evtdiag diagnosis name,
            # first update self priority then update this evtdiag priority
            if not self_priority_updated and event_diagnosis.diagnosis.name <= evtdiag.diagnosis.name:
                event_diagnosis.priority = priority
                priority += 1
                self_priority_updated = True
            evtdiag.priority = priority
            evtdiag.save()
            priority += 1

        event_diagnosis.priority = event_diagnosis.priority if self_priority_updated else priority
        event_diagnosis.save()

        return event_diagnosis

    def update(self, instance, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        # update the EventDiagnosis object
        instance.event = validated_data.get('event', instance.event)
        instance.diagnosis = validated_data.get('diagnosis', instance.diagnosis)
        instance.suspect = validated_data.get('suspect', instance.suspect)
        instance.major = validated_data.get('major', instance.major)
        instance.priority = validated_data.get('priority', instance.priority)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

        # calculate the priorty value:
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
            # if self has not been updated and self diagnosis name is less than or equal to this evtdiag diagnosis name,
            # first update self priority then update this evtdiag priority
            if not self_priority_updated and instance.diagnosis.name <= evtdiag.diagnosis.name:
                instance.priority = priority
                priority += 1
                self_priority_updated = True
            evtdiag.priority = priority
            evtdiag.save()
            priority += 1

        instance.priority = instance.priority if self_priority_updated else priority
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
    new_species_diagnosis_organizations = serializers.ListField(write_only=True)

    def validate(self, data):

        if data['location_species'].event_location.event.complete:
            message = "Diagnoses from a species from a location from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        suspect = data['suspect'] if 'suspect' in data and data['suspect'] else None
        tested_count = data['tested_count'] if 'tested_count' in data and data['tested_count'] is not None else None
        suspect_count = data['suspect_count'] if 'suspect_count' in data and data['suspect_count'] is not None else None
        pos_count = data['positive_count'] if 'positive_count' in data and data['positive_count'] is not None else None
        if 'new_species_diagnosis_organizations' in data and data['new_species_diagnosis_organizations'] is not None:
            new_species_diagnosis_organizations = data['new_species_diagnosis_organizations']
        else:
            new_species_diagnosis_organizations = None

        if new_species_diagnosis_organizations is not None:
            for org_id in new_species_diagnosis_organizations:
                org = Organization.objects.filter(id=org_id).first()
                if org and not org.laboratory:
                    raise serializers.ValidationError("SpeciesDiagnosis Organization can only be a laboratory.")

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
            # Within each species diagnosis, number_positive+number_suspect =< number_tested
            if pos_count and suspect_count and not (pos_count + suspect_count <= tested_count):
                message = "The positive count and suspect count together cannot be more than the diagnosed count."
                raise serializers.ValidationError(message)
            elif pos_count and not (pos_count <= tested_count):
                message = "The positive count cannot be more than the diagnosed count."
                raise serializers.ValidationError(message)
            elif suspect_count and not (suspect_count <= tested_count):
                message = "The suspect count together cannot be more than the diagnosed count."
                raise serializers.ValidationError(message)
        # Within each species diagnosis, number_with_diagnosis =< number_tested.
        # here, tested_count was not submitted, so if diagnosis_count was submitted and is not null, raise an error
        elif 'diagnosis_count' in data and data['diagnosis_count'] is not None:
            raise serializers.ValidationError("The diagnosed count cannot be more than the tested count.")

        # If diagnosis is non-suspect (suspect=False), then number_positive must be null or greater than zero,
        # else diagnosis is suspect (suspect=True) and so number_positive must be zero
        # TODO: following rule would only work on update due to M:N relate to orgs, so on-hold until further notice
        # Only allowed to enter >0 if provide laboratory name.
        if not suspect and (not pos_count or pos_count > 0):
            raise serializers.ValidationError("The positive count cannot be zero when the diagnosis is non-suspect.")

        if 'pooled' in data and data['pooled'] and tested_count <= 1:
            raise serializers.ValidationError("A diagnosis can only be pooled if the tested count is greater than one.")

        return data

    def create(self, validated_data):
        if 'request' in self.context and hasattr(self.context['request'], 'user'):
            user = self.context['request'].user
        else:
            user = None

        if not user:
            raise serializers.ValidationError("User could not be identified, please contact the administrator.")

        new_species_diagnosis_organizations = validated_data.pop('new_species_diagnosis_organizations', None)

        # TODO: following rule would only work on update due to M:N relate to orgs, so on-hold until further notice
        # For new data, if no Lab provided, then suspect = True; although all "Pending" and "Undetermined"
        # diagnosis must be confirmed (suspect = False), even if no lab OR some other way of coding this such that we
        # (TODO: NOTE following rule is valid and enforceable right now:)
        # never see "Pending suspect" or "Undetermined suspect" on front end.
        # pending = Diagnosis.objects.filter(name='Pending').first().id
        # undetermined = Diagnosis.objects.filter(name='Undetermined').first().id
        # if 'diagnosis' in validated_data and validated_data['diagnosis'] in [pending, undetermined]:
        #     validated_data['suspect'] = False

        species_diagnosis = SpeciesDiagnosis.objects.create(**validated_data)

        # calculate the priorty value:
        # TODO: the following...
        # Order species diagnoses by causal
        # (cause of death first, then cause of sickness, then incidental findings, then unknown)
        # and within each causal category by diagnosis name (alphabetical).
        priority = 1
        self_priority_updated = False
        # get all species_diagnoses for the parent location_species except self, and sort by diagnosis cause then name
        specdiags = SpeciesDiagnosis.objects.filter(
            location_species=species_diagnosis.location_species).exclude(
            id=species_diagnosis.id).order_by('cause__id', 'diagnosis__name')
        for specdiag in specdiags:
            # if self has not been updated and self diagnosis cause equal to or less than this specdiag diagnosis cause,
            # and self diagnosis name equal to or less than this specdiag diagnosis name
            # first update self priority then update this specdiag priority
            if not self_priority_updated:
                # first check if self diagnosis cause is equal to this specdiag diagnosis cause
                if species_diagnosis.cause and species_diagnosis.cause.id == specdiag.cause.id:
                    if species_diagnosis.diagnosis.name == specdiag.diagnosis.name:
                        species_diagnosis.priority = priority
                        priority += 1
                        self_priority_updated = True
                    elif species_diagnosis.diagnosis.name < specdiag.diagnosis.name:
                        species_diagnosis.priority = priority
                        priority += 1
                        self_priority_updated = True
                # else check if self diagnosis cause is less than this specdiag diagnosis cause
                elif species_diagnosis.cause and species_diagnosis.cause.id < specdiag.cause.id:
                    if species_diagnosis.diagnosis.name == specdiag.diagnosis.name:
                        species_diagnosis.priority = priority
                        priority += 1
                        self_priority_updated = True
                    elif species_diagnosis.diagnosis.name < specdiag.diagnosis.name:
                        species_diagnosis.priority = priority
                        priority += 1
                        self_priority_updated = True
                # else check if both self diagnosis cause and this specdiag diagnosis cause are null
                elif species_diagnosis.cause is None and specdiag.cause is None:
                    if species_diagnosis.diagnosis.name == specdiag.diagnosis.name:
                        species_diagnosis.priority = priority
                        priority += 1
                        self_priority_updated = True
                    elif species_diagnosis.diagnosis.name < specdiag.diagnosis.name:
                        species_diagnosis.priority = priority
                        priority += 1
                        self_priority_updated = True
            specdiag.priority = priority
            specdiag.save()
            priority += 1

        species_diagnosis.priority = species_diagnosis.priority if self_priority_updated else priority
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

        # get the old (current) org ID list for this Species Diagnosis
        old_org_ids = SpeciesDiagnosisOrganization.objects.filter(
            species_diagnosis=instance.id).values_list('id', flat=True)

        # pull out org ID list from the request
        if 'new_species_diagnosis_organizations' in self.initial_data:
            new_org_ids = self.initial_data['new_species_diagnosis_organizations']
        else:
            new_org_ids = []

        # for positive_count, only allowed to enter >0 if provide laboratory name.
        if ('positive_count' in validated_data and validated_data['positive_count'] is not None
                and validated_data['positive_count'] > 0 and (len(old_org_ids) == 0 or len(new_org_ids) == 0)):
            message = "The positive count cannot be greater than zero if there is no laboratory for this diagnosis."
            raise serializers.ValidationError(message)

        # a diagnosis can only be used once for a location-species-labID combination
        loc_specdiags = SpeciesDiagnosis.objects.filter(
            location_species=validated_data['location_species']).values('id', 'diagnosis').exclude(id=instance.id)
        if validated_data['diagnosis'].id in [specdiag['diagnosis'] for specdiag in loc_specdiags]:
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

        # update the SpeciesDiagnosis object
        instance.location_species = validated_data.get('location_species', instance.location_species)
        instance.diagnosis = validated_data.get('diagnosis', instance.diagnosis)
        instance.cause = validated_data.get('cause', instance.cause)
        instance.basis = validated_data.get('basis', instance.basis)
        instance.suspect = validated_data.get('suspect', instance.suspect)
        instance.priority = validated_data.get('priority', instance.priority)
        instance.tested_count = validated_data.get('tested_count', instance.tested_count)
        instance.diagnosis_count = validated_data.get('diagnosis_count', instance.diagnosis_count)
        instance.positive_count = validated_data.get('positive_count', instance.positive_count)
        instance.suspect_count = validated_data.get('suspect_count', instance.suspect_count)
        instance.pooled = validated_data.get('pooled', instance.pooled)
        instance.modified_by = user if user else validated_data.get('modified_by', instance.modified_by)

        # calculate the priorty value:
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
                if instance.cause.id == specdiag.cause.id:
                    if instance.diagnosis.name == specdiag.diagnosis.name:
                        instance.priority = priority
                        priority += 1
                        self_priority_updated = True
                    elif instance.diagnosis.name < specdiag.diagnosis.name:
                        instance.priority = priority
                        priority += 1
                        self_priority_updated = True
                # else check if self diagnosis cause is less than this specdiag diagnosis cause
                elif instance.cause.id < specdiag.cause.id:
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

        instance.priority = instance.priority if self_priority_updated else priority
        instance.save()

        # identify and delete relates where sample IDs are present in old list but not new list
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
                  'suspect', 'priority', 'tested_count', 'diagnosis_count', 'positive_count', 'suspect_count', 'pooled',
                  'organizations', 'new_species_diagnosis_organizations',
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class SpeciesDiagnosisOrganizationSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    def validate(self, data):

        if data['species_diagnosis'].location_species.event_location.event.complete:
            message = "Organizations from a diagnosis from a species from a location from a complete event"
            message += " may not be changed unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        if data['organization'].laboratory:
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

        # create the child comments for this service request
        if new_comments is not None:
            for comment in new_comments:
                if comment is not None:
                    comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                    Comment.objects.create(content_object=service_request, comment=comment['comment'],
                                           comment_type=comment_type, created_by=user, modified_by=user)

        # construct and send the request email
        subject = "Service request for Event " + str(service_request.event.id)
        body = "A user  (" + user.email + ") with " + user.organization.name + " has requested "
        body += service_request.request_type.name + " for event " + str(service_request.event.id) + ".\r\n\r\n"
        from_address = user.email
        to_list = ['nwhc-epi@usgs.gov', ]
        bcc_list = []
        reply_to_list = [user.email, ]
        headers = None  # {'Message-ID': 'foo'}
        email = EmailMessage(subject, body, from_address, to_list, bcc_list, reply_to=reply_to_list, headers=headers)
        # TODO: uncomment next block when code is deployed on the production server
        # try:
        #     email.send(fail_silently=False)
        # except TypeError:
        #     message = "Service Request saved but send email failed, please contact the administrator."
        #     raise serializers.ValidationError(message)

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

        instance.event = validated_data.get('event', instance.event)
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
                  'modified_date', 'modified_by', 'modified_by_string',)


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
# TODO: better protect this endpoint: anon and partner users can create a user but should only be able to submit 'username', 'password', 'first_name', 'last_name', 'email', others auto-assigned, admins can submit all except is_superuser
class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    organization_string = serializers.StringRelatedField(source='organization')

    def create(self, validated_data):
        created_by = validated_data.pop('created_by')
        modified_by = validated_data.pop('modified_by')
        password = validated_data['password']
        user = User.objects.create(**validated_data)

        user.created_by = created_by
        user.modified_by = modified_by
        user.set_password(password)
        user.save()

        return user

    def update(self, instance, validated_data):
        instance.username = validated_data.get('username', instance.username)
        instance.first_name = validated_data.get('first_name', instance.first_name)
        instance.last_name = validated_data.get('last_name', instance.last_name)
        instance.email = validated_data.get('email', instance.email)
        instance.is_superuser = validated_data.get('is_superuser', instance.is_superuser)
        instance.is_staff = validated_data.get('is_staff', instance.is_staff)
        instance.is_active = validated_data.get('is_active', instance.is_active)
        instance.role = validated_data.get('role', instance.role)
        instance.organization = validated_data.get('organization', instance.organization)
        instance.active_key = validated_data.get('active_key', instance.active_key)
        instance.user_status = validated_data.get('user_status', instance.user_status)
        instance.modified_by = self.context['request'].user

        new_password = validated_data.get('password', None)
        if new_password is not None:
            instance.set_password(new_password)
        instance.save()

        return instance

    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'first_name', 'last_name', 'email', 'is_superuser', 'is_staff',
                  'is_active', 'role', 'organization', 'organization_string', 'circles', 'last_login', 'active_key',
                  'user_status',)


class RoleSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')

    class Meta:
        model = Role
        fields = ('id', 'name', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string',)


class CircleSerlializer(serializers.ModelSerializer):
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
                    al2 = AdministrativeLevelTwo.objects.filter(id=al2_id).first()
                    unique_l2s.append(model_to_dict(al2))
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
                flyway_ids = eventlocation.get('flyway_ids')
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
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ('id', 'affected_count', 'start_date', 'end_date', 'complete', 'event_type', 'event_type_string',
                  'eventdiagnoses', 'administrativelevelones', 'administrativeleveltwos', 'flyways', 'species',
                  'permissions', 'permission_source',)


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
                    al2 = AdministrativeLevelTwo.objects.filter(id=al2_id).first()
                    unique_l2s.append(model_to_dict(al2))
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
                flyway_ids = eventlocation.get('flyway_ids')
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
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ('id', 'event_reference', 'affected_count', 'start_date', 'end_date', 'complete', 'event_type',
                  'event_type_string', 'public', 'eventdiagnoses', 'administrativelevelones', 'administrativeleveltwos',
                  'flyways', 'species', 'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string', 'permissions', 'permission_source',)


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
                                           "created_by_string": created_by_string,
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
                    al2 = AdministrativeLevelTwo.objects.filter(id=al2_id).first()
                    unique_l2s.append(model_to_dict(al2))
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
                flyway_ids = eventlocation.get('flyway_ids')
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

    class Meta:
        model = SpeciesDiagnosis
        fields = ('diagnosis', 'diagnosis_string', 'suspect', 'tested_count', 'diagnosis_count', 'positive_count',
                  'suspect_count', 'pooled',)


class SpeciesDiagnosisDetailSerializer(serializers.ModelSerializer):
    organizations_string = serializers.StringRelatedField(many=True, source='organizations')

    class Meta:
        model = SpeciesDiagnosis
        fields = ('id', 'location_species', 'diagnosis', 'diagnosis_string', 'cause', 'cause_string', 'basis',
                  'suspect', 'priority', 'tested_count', 'diagnosis_count', 'positive_count', 'suspect_count', 'pooled',
                  'organizations', 'organizations_string',)


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
    eventlocations = EventLocationDetailPublicSerializer(many=True)
    eventdiagnoses = EventDiagnosisDetailPublicSerializer(many=True)
    eventorganizations = serializers.SerializerMethodField()  # OrganizationPublicSerializer(many=True)

    def get_eventorganizations(self, obj):
        pub_orgs = []
        if obj.organizations is not None:
            orgs = obj.organizations.all()
            for org in orgs:
                if not org.do_not_publish:
                    new_org = {'id': org.id, 'name': org.name, 'address_one': org.address_one,
                               'address_two': org.address_two, 'city': org.city, 'postal_code': org.postal_code,
                               'administrative_level_one': org.administrative_level_one.name,
                               'country': org.country.name, 'phone': org.phone}
                    pub_orgs.append(new_org)
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
                  'eventdiagnoses', 'eventlocations', 'eventorganizations', 'permissions', 'permission_source',)


class EventDetailSerializer(serializers.ModelSerializer):
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    eventlocations = EventLocationDetailSerializer(many=True)
    # eventdiagnoses = EventDiagnosisDetailSerializer(many=True)
    eventdiagnoses = serializers.SerializerMethodField()
    eventorganizations = OrganizationSerializer(many=True, source='organizations')
    comments = CommentSerializer(many=True)
    servicerequests = ServiceRequestDetailSerializer(many=True)

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
                  'affected_count', 'public', 'eventdiagnoses', 'eventlocations', 'eventorganizations', 'comments',
                  'servicerequests', 'permissions', 'permission_source',)


class EventDetailAdminSerializer(serializers.ModelSerializer):
    created_by_string = serializers.StringRelatedField(source='created_by')
    modified_by_string = serializers.StringRelatedField(source='modified_by')
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    staff_string = serializers.StringRelatedField(source='staff')
    event_status_string = serializers.StringRelatedField(source='event_status')
    legal_status_string = serializers.StringRelatedField(source='legal_status')
    eventlocations = EventLocationDetailSerializer(many=True)
    # eventdiagnoses = EventDiagnosisDetailSerializer(many=True)
    eventdiagnoses = serializers.SerializerMethodField()
    eventorganizations = OrganizationSerializer(many=True, source='organizations')
    comments = CommentSerializer(many=True)
    servicerequests = ServiceRequestDetailSerializer(many=True)

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
                  'created_date', 'created_by', 'created_by_string',
                  'modified_date', 'modified_by', 'modified_by_string', 'permissions', 'permission_source',)


class FlatEventDetailSerializer(serializers.Serializer):
    # a flattened (not nested) version of the essential fields of the FullResultSerializer, to populate CSV files
    # requested from the EventDetails Search

    event_id = serializers.IntegerField()
    event_reference = serializers.CharField()
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
    causal = serializers.CharField()
    suspect = serializers.BooleanField()
    number_tested = serializers.IntegerField()
    number_positive = serializers.IntegerField()
