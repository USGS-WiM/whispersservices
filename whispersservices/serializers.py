from django.forms.models import model_to_dict
from rest_framework import serializers
from whispersservices.models import *
from dry_rest_permissions.generics import DRYPermissionsField


######
#
#  Misc
#
######


class CommentSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Comment
        fields = ('id', 'comment', 'comment_type',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class CommentTypeSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = CommentType
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class ArtifactSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Artifact
        fields = ('id', 'filename', 'keywords', 'created_date', 'created_by', 'modified_date', 'modified_by',)


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


class EventSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    comments = CommentSerializer(many=True, read_only=True)
    new_organizations = serializers.ListField(write_only=True)
    new_comments = serializers.ListField(write_only=True)
    new_event_locations = serializers.ListField(write_only=True)

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

        comment_types = {'site_description': 'Site description', 'history': 'History',
                         'environmental_factors': 'Environmental factors', 'clinical_signs': 'Clinical signs',
                         'general': 'General'}

        # pull out child organizations list from the request
        new_organizations = validated_data.pop('new_organizations', None)

        # pull out child comments list from the request
        new_comments = validated_data.pop('new_comments', None)

        # pull out child event_locations list from the request
        new_event_locations = validated_data.pop('new_event_locations', None)

        user = self.context['request'].user
        event = Event.objects.create(**validated_data)

        # create the child organizations for this event
        if new_organizations is not None:
            for org_id in new_organizations:
                if org_id is not None:
                    org = Organization.objects.filter(pk=org_id).first()
                    if org is not None:
                        EventOrganization.objects.create(event=event, organization=org)

        # create the child comments for this event
        if new_comments is not None:
            for comment in new_comments:
                if comment is not None:
                    comment_type = CommentType.objects.filter(id=comment['comment_type']).first()
                    Comment.objects.create(content_object=event, comment=comment['comment'], comment_type=comment_type,
                                           created_by=user, modified_by=user)

        # create the child event_locations for this event
        if new_event_locations is not None:
            for event_location in new_event_locations:
                if event_location is not None:
                    # use event to populate event field on event_location
                    event_location['event'] = event
                    location_contacts = event_location.pop('location_contacts', None)
                    location_species = event_location.pop('location_species', None)

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
                    evt_location = EventLocation.objects.create(**event_location)

                    for key, value in comment_types.items():

                        comment_type = CommentType.objects.filter(name=value).first()

                        if comments[key] is not None and len(comments[key]) > 0:
                            Comment.objects.create(content_object=evt_location, comment=comments[key],
                                                   comment_type=comment_type, created_by=user, modified_by=user)

                    # Create EventLocationContacts
                    if location_contacts is not None:
                        for location_contact in location_contacts:
                            location_contact['event_location'] = evt_location

                            # Convert ids to ForeignKey objects
                            location_contact['contact'] = Contact.objects.filter(pk=location_contact['id']).first()
                            location_contact['contact_type'] = ContactType.objects.filter(
                                pk=location_contact['contact_type']).first()
                            del location_contact['id']

                            location_contact['created_by'] = user
                            location_contact['modified_by'] = user
                            EventLocationContact.objects.create(**location_contact)

                    # Create EventLocationSpecies
                    if location_species is not None:
                        for location_spec in location_species:
                            location_spec['event_location'] = evt_location

                            # Convert ids to ForeignKey objects
                            location_spec['species'] = Species.objects.filter(pk=location_spec['species']).first()
                            location_spec['age_bias'] = AgeBias.objects.filter(pk=location_spec['age_bias']).first()
                            location_spec['sex_bias'] = SexBias.objects.filter(pk=location_spec['sex_bias']).first()

                            location_spec['created_by'] = user
                            location_spec['modified_by'] = user
                            LocationSpecies.objects.create(**location_spec)

        return event

    # on update, any submitted nested objects (new_organizations, new_comments, new_event_locations) will be ignored
    def update(self, instance, validated_data):
        user = self.context['request'].user

        # remove child organizations list from the request
        if 'new_organizations' in validated_data:
            validated_data.pop('new_organizations')

        # remove child comments list from the request
        if 'new_comments' in validated_data:
            validated_data.pop('new_comments')

        # remove child event_locations list from the request
        if 'new_event_locations' in validated_data:
            validated_data.pop('new_event_locations')

        # # get the old (current) organization ID list for this Event
        # old_organizations = Organization.objects.filter(events=instance.id)
        #
        # # pull out organization ID list from the request
        # if 'new_organizations' in self.initial_data:
        #     new_organizations_ids = self.initial_data['new_organizations']
        #     new_organizations = Organization.objects.filter(id__in=new_organizations_ids)
        # else:
        #     new_organizations = []
        #
        # # get the old (current) comment ID list for this Event
        # old_comments = Comment.objects.filter(events=instance.id)
        #
        # # pull out organization ID list from the request
        # if 'new_comments' in self.initial_data:
        #     new_comments_ids = self.initial_data['new_comments']
        #     new_comments = Comment.objects.filter(id__in=new_comments_ids)
        # else:
        #     new_comments = []
        #
        # # get the old (current) event_location ID list for this Event
        # old_event_locations = Comment.objects.filter(events=instance.id)
        #
        # # pull out event_location ID list from the request
        # if 'new_event_locations' in self.initial_data:
        #     new_event_locations_ids = self.initial_data['new_event_locations']
        #     new_event_locations = Comment.objects.filter(id__in=new_event_locations_ids)
        # else:
        #     new_event_locations = []

        # update the Event object
        instance.event_type = validated_data.get('event_type', instance.event_type)
        instance.event_reference = validated_data.get('event_reference', instance.event_reference)
        instance.complete = validated_data.get('complete', instance.complete)
        instance.start_date = validated_data.get('start_date', instance.start_date)
        instance.end_date = validated_data.get('end_date', instance.end_date)
        instance.affected_count = validated_data.get('affected_count', instance.affected_count)
        instance.staff = instance.staff
        instance.event_status = instance.event_status
        instance.quality_check = instance.quality_check
        instance.legal_status = instance.legal_status
        instance.legal_number = instance.legal_number
        instance.public = validated_data.get('public', instance.public)
        instance.circle_read = validated_data.get('circle_read', instance.circle_read)
        instance.circle_write = validated_data.get('circle_write', instance.circle_write)
        if 'request' in self.context and 'user' in self.context['request']:
            instance.modified_by = self.context['request'].user
        else:
            instance.modified_by = validated_data.get('modified_by', instance.modified_by)
        instance.save()

        # # identify and delete relates where organization IDs are present in old list but not new list
        # delete_organizations = list(set(old_organizations) - set(new_organizations))
        # for organization in delete_organizations:
        #     delete_organization = EventOrganization.objects.filter(event=instance, organization=organization)
        #     delete_organization.delete()
        #
        # # identify and create relates where organization IDs are present in new list but not old list
        # add_organizations = list(set(new_organizations) - set(old_organizations))
        # for organization in add_organizations:
        #     EventOrganization.objects.create(event=instance, organization=organization,
        #                                      created_by=user, modified_by=user)
        #
        # # identify and delete relates where organization IDs are present in old list but not new list
        # delete_comments = list(set(old_comments) - set(new_comments))
        # for comment in delete_comments:
        #     delete_comment = Comment.objects.filter(pk=comment.id)
        #     delete_comment.delete()
        #
        # # identify and create relates where organization IDs are present in new list but not old list
        # add_comments = list(set(new_comments) - set(old_comments))
        # for comment in add_comments:
        #     Comment.objects.create(content_object=instance, comment=comment.comment,
        #                            comment_type=comment.comment_type, created_by=user, modified_by=user)
        #
        # # identify and delete relates where event_location IDs are present in old list but not new list
        # delete_event_locations = list(set(old_event_locations) - set(new_event_locations))
        # for event_location in delete_event_locations:
        #     delete_event_location = EventLocation.objects.filter(event=instance, event_location=event_location)
        #     delete_event_location.delete()
        #
        # # identify and create relates where event_location IDs are present in new list but not old list
        # add_event_locations = list(set(new_event_locations) - set(old_event_locations))
        # for event_location in add_event_locations:
        #     EventLocation.objects.create(event=instance, event_location=event_location,
        #                                  created_by=user, modified_by=user)

        return instance

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'public', 'circle_read', 'circle_write', 'organizations', 'contacts', 'comments',
                  'new_organizations', 'new_comments', 'new_event_locations',
                  'created_date', 'created_by', 'modified_date', 'modified_by', 'permissions', 'permission_source',)


class EventAdminSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    staff_string = serializers.StringRelatedField(source='staff')
    event_status_string = serializers.StringRelatedField(source='event_status')
    legal_status_string = serializers.StringRelatedField(source='legal_status')
    comments = CommentSerializer(many=True, read_only=True)

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

    # on update, any submitted nested objects (new_organizations, new_comments, new_event_locations) will be ignored
    def update(self, instance, validated_data):
        # user = self.context['request'].user

        # remove child organizations list from the request
        if 'new_organizations' in validated_data:
            validated_data.pop('new_organizations')

        # remove child comments list from the request
        if 'new_comments' in validated_data:
            validated_data.pop('new_comments')

        # remove child event_locations list from the request
        if 'new_event_locations' in validated_data:
            validated_data.pop('new_event_locations')

        # # get the old (current) organization ID list for this Event
        # old_organizations = Organization.objects.filter(events=instance.id)
        #
        # # pull out organization ID list from the request
        # if 'new_organizations' in self.initial_data:
        #     new_organizations_ids = self.initial_data['new_organizations']
        #     new_organizations = Organization.objects.filter(id__in=new_organizations_ids)
        # else:
        #     new_organizations = []
        #
        # # get the old (current) comment ID list for this Event
        # old_comments = Comment.objects.filter(events=instance.id)
        #
        # # pull out organization ID list from the request
        # if 'new_comments' in self.initial_data:
        #     new_comments_ids = self.initial_data['new_comments']
        #     new_comments = Comment.objects.filter(id__in=new_comments_ids)
        # else:
        #     new_comments = []
        #
        # # get the old (current) event_location ID list for this Event
        # old_event_locations = Comment.objects.filter(events=instance.id)
        #
        # # pull out event_location ID list from the request
        # if 'new_event_locations' in self.initial_data:
        #     new_event_locations_ids = self.initial_data['new_event_locations']
        #     new_event_locations = Comment.objects.filter(id__in=new_event_locations_ids)
        # else:
        #     new_event_locations = []

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
        if 'request' in self.context and 'user' in self.context['request']:
            instance.modified_by = self.context['request'].user
        else:
            instance.modified_by = validated_data.get('modified_by', instance.modified_by)
        instance.save()

        # # identify and delete relates where organization IDs are present in old list but not new list
        # delete_organizations = list(set(old_organizations) - set(new_organizations))
        # for organization in delete_organizations:
        #     delete_organization = EventOrganization.objects.filter(event=instance, organization=organization)
        #     delete_organization.delete()
        #
        # # identify and create relates where organization IDs are present in new list but not old list
        # add_organizations = list(set(new_organizations) - set(old_organizations))
        # for organization in add_organizations:
        #     EventOrganization.objects.create(event=instance, organization=organization,
        #                                      created_by=user, modified_by=user)
        #
        # # identify and delete relates where organization IDs are present in old list but not new list
        # delete_comments = list(set(old_comments) - set(new_comments))
        # for comment in delete_comments:
        #     delete_comment = Comment.objects.filter(pk=comment.id)
        #     delete_comment.delete()
        #
        # # identify and create relates where organization IDs are present in new list but not old list
        # add_comments = list(set(new_comments) - set(old_comments))
        # for comment in add_comments:
        #     Comment.objects.create(content_object=instance, comment=comment.comment,
        #                            comment_type=comment.comment_type, created_by=user, modified_by=user)
        #
        # # identify and delete relates where event_location IDs are present in old list but not new list
        # delete_event_locations = list(set(old_event_locations) - set(new_event_locations))
        # for event_location in delete_event_locations:
        #     delete_event_location = EventLocation.objects.filter(event=instance, event_location=event_location)
        #     delete_event_location.delete()
        #
        # # identify and create relates where event_location IDs are present in new list but not old list
        # add_event_locations = list(set(new_event_locations) - set(old_event_locations))
        # for event_location in add_event_locations:
        #     EventLocation.objects.create(event=instance, event_location=event_location,
        #                                  created_by=user, modified_by=user)

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string',
                  'legal_status', 'legal_status_string', 'legal_number', 'quality_check', 'public',
                  'circle_read', 'circle_write', 'superevents', 'organizations', 'contacts', 'comments',
                  'created_date', 'created_by', 'modified_date', 'modified_by', 'permissions', 'permission_source',)


class EventSuperEventSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = EventSuperEvent
        fields = ('id', 'event', 'superevent', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class SuperEventSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = SuperEvent
        fields = ('id', 'category', 'events', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class EventTypeSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = EventType
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class StaffSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Staff
        fields = ('id', 'first_name', 'last_name', 'role', 'active',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class LegalStatusSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = LegalStatus
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class EventStatusSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = EventStatus
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class EventAbstractSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = EventAbstract
        fields = ('id', 'event', 'text', 'lab_id', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class EventCaseSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = EventCase
        fields = ('id', 'event', 'case', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class EventLabsiteSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = EventLabsite
        fields = ('id', 'event', 'lab_id', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class EventOrganizationPublicSerializer(serializers.ModelSerializer):

    class Meta:
        model = EventOrganization
        fields = ('event', 'organization',)


class EventOrganizationSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = EventOrganization
        fields = ('id', 'event', 'organization', 'priority',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class EventContactSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = EventContact
        fields = ('id', 'event', 'contact', 'created_date', 'created_by', 'modified_date', 'modified_by',)


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
                  'county_multiple', 'county_unknown', 'flyway',)


class EventLocationSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    administrative_level_two_string = serializers.StringRelatedField(source='administrative_level_two')
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')
    country_string = serializers.StringRelatedField(source='country')
    comments = CommentSerializer(many=True, read_only=True)
    new_location_contacts = serializers.ListField(write_only=True)
    new_location_species = serializers.ListField(write_only=True)

    def create(self, validated_data):
        user = self.context['request'].user

        comment_types = {'site_description': 'Site description', 'history': 'History',
                         'environmental_factors': 'Environmental factors', 'clinical_signs': 'Clinical signs',
                         'general': 'General'}

        # event = Event.objects.filter(pk=validated_data['event']).first()
        location_contacts = validated_data.pop('new_location_contacts', None)
        location_species = validated_data.pop('new_location_species', None)

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
                    'general': validated_data.pop('comment', None)}

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
        if location_contacts is not None:
            for location_contact in location_contacts:
                location_contact['event_location'] = evt_location

                # Convert ids to ForeignKey objects
                location_contact['contact'] = Contact.objects.filter(pk=location_contact['id']).first()
                location_contact['contact_type'] = ContactType.objects.filter(
                    pk=location_contact['contact_type']).first()
                del location_contact['id']

                location_contact['created_by'] = user
                location_contact['modified_by'] = user
                EventLocationContact.objects.create(**location_contact)

        # Create EventLocationSpecies
        if location_species is not None:
            for location_spec in location_species:
                location_spec['event_location'] = evt_location

                # Convert ids to ForeignKey objects
                location_spec['species'] = Species.objects.filter(pk=location_spec['species']).first()
                location_spec['age_bias'] = AgeBias.objects.filter(pk=location_spec['age_bias']).first()
                location_spec['sex_bias'] = SexBias.objects.filter(pk=location_spec['sex_bias']).first()

                location_spec['created_by'] = user
                location_spec['modified_by'] = user
                LocationSpecies.objects.create(**location_spec)

        return evt_location

    class Meta:
        model = EventLocation
        fields = ('id', 'name', 'event', 'start_date', 'end_date', 'country', 'country_string',
                  'administrative_level_one', 'administrative_level_one_string', 'administrative_level_two',
                  'administrative_level_two_string', 'county_multiple', 'county_unknown', 'latitude', 'longitude',
                  'priority', 'land_ownership', 'flyway', 'contacts', 'comments',
                  'new_location_contacts', 'new_location_species',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class EventLocationContactSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = EventLocationContact
        fields = ('id', 'event_location', 'contact', 'contact_type',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class CountrySerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Country
        fields = ('id', 'name', 'abbreviation', 'calling_code',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class AdministrativeLevelOneSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    country_string = serializers.StringRelatedField(source='country')

    class Meta:
        model = AdministrativeLevelOne
        fields = ('id', 'name', 'country', 'country_string', 'abbreviation',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class AdministrativeLevelTwoSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')

    class Meta:
        model = AdministrativeLevelTwo
        fields = ('id', 'name', 'administrative_level_one', 'administrative_level_one_string', 'points',
                  'centroid_latitude', 'centroid_longitude', 'fips_code', 'created_date',
                  'created_by', 'modified_date', 'modified_by',)


class AdministrativeLevelLocalitySerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = AdministrativeLevelLocality
        fields = ('id', 'country', 'admin_level_one_name', 'admin_level_two_name',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class LandOwnershipSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = LandOwnership
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


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
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = LocationSpecies
        fields = ('id', 'event_location', 'species', 'population_count', 'sick_count', 'dead_count',
                  'sick_count_estimated', 'dead_count_estimated', 'priority', 'captive', 'age_bias', 'sex_bias',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class SpeciesSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Species
        fields = ('id', 'name', 'class_name', 'order_name', 'family_name', 'sub_family_name', 'genus_name',
                  'species_latin_name', 'subspecies_latin_name', 'tsn',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class AgeBiasSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = AgeBias
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class SexBiasSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = SexBias
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


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
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    diagnosis_type_string = serializers.StringRelatedField(source='diagnosis_type')

    class Meta:
        model = Diagnosis
        fields = ('id', 'name', 'diagnosis_type', 'diagnosis_type_string',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class DiagnosisTypeSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = DiagnosisType
        fields = ('id', 'name', 'color', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class EventDiagnosisPublicSerializer(serializers.ModelSerializer):
    diagnosis_string = serializers.StringRelatedField(source='diagnosis')

    class Meta:
        model = EventDiagnosis
        fields = ('diagnosis', 'diagnosis_string', 'confirmed', 'major',)


class EventDiagnosisSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    diagnosis_string = serializers.StringRelatedField(source='diagnosis')

    class Meta:
        model = EventDiagnosis
        fields = ('id', 'event', 'diagnosis', 'diagnosis_string', 'confirmed', 'major', 'priority',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class SpeciesDiagnosisPublicSerializer(serializers.ModelSerializer):
    diagnosis_string = serializers.StringRelatedField(source='diagnosis')

    class Meta:
        model = SpeciesDiagnosis
        fields = ('diagnosis', 'diagnosis_string', 'confirmed', 'tested_count', 'diagnosis_count', 'positive_count',
                  'suspect_count', 'pooled',)


class SpeciesDiagnosisSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    diagnosis_string = serializers.StringRelatedField(source='diagnosis')

    class Meta:
        model = SpeciesDiagnosis
        fields = ('id', 'location_species', 'diagnosis', 'diagnosis_string', 'cause', 'basis', 'confirmed', 'priority',
                  'tested_count', 'diagnosis_count', 'positive_count', 'suspect_count', 'pooled', 'organizations',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class SpeciesDiagnosisOrganizationSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = SpeciesDiagnosisOrganization
        fields = ('id', 'species_diagnosis', 'organization',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class DiagnosisBasisSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = DiagnosisBasis
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class DiagnosisCauseSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = DiagnosisCause
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


######
#
#  Users
#
######


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

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

        instance.set_password(validated_data.get('password', instance.password))
        instance.save()

        return instance

    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'first_name', 'last_name', 'email', 'is_superuser', 'is_staff',
                  'is_active', 'role', 'organization', 'circles', 'last_login', 'active_key', 'user_status',)


class RoleSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Role
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class CircleSerlializer(serializers.ModelSerializer):
    new_users = serializers.ListField(write_only=True)

    # on create, also create child objects (circle-user M:M relates)
    def create(self, validated_data):
        # pull out user ID list from the request
        new_users = validated_data.pop('new_users', None)

        # create the Circle object
        circle = Circle.objects.create(**validated_data)

        # create a Sample Analysis Batch object for each sample ID submitted
        if new_users:
            user = self.context['request'].user
            for new_user_id in new_users:
                new_user = User.objects.get(id=new_user_id)
                CircleUser.objects.create(user=new_user, circle=circle, created_by=user, modified_by=user)

        return circle

    # on update, also update child objects (circle-user M:M relates), including additions and deletions
    def update(self, instance, validated_data):
        user = self.context['request'].user

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
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class OrganizationSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Organization
        fields = ('id', 'name', 'private_name', 'address_one', 'address_two', 'city', 'postal_code',
                  'administrative_level_one', 'country', 'phone', 'parent_organization', 'do_not_publish',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class ContactSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
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

    class Meta:
        model = Contact
        fields = ('id', 'first_name', 'last_name', 'email', 'phone', 'affiliation', 'title', 'position', 'organization',
                  'owner_organization', 'created_date', 'created_by', 'modified_date', 'modified_by', 'permissions',
                  'permission_source',)


class ContactTypeSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = ContactType
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class SearchSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
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
    #     print(validated_data)
    #     user = self.context['request'].user
    #     validated_data['created_by'] = user
    #     validated_data['modified_by'] = user
    #     search = Search.objects.create(**validated_data)
    #     return search

    class Meta:
        model = Search
        fields = ('id', 'name', 'owner', 'data', 'created_date', 'created_by', 'modified_date', 'modified_by',
                  'permissions', 'permission_source',)


######
#
#  Special
#
######


# TODO: Make these three EventSummary serializers adhere to DRY Principle
class EventSummaryPublicSerializer(serializers.ModelSerializer):

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
        # TODO: implement this once flyways are figured out
        # eventlocations = obj.eventlocations.values()
        # if eventlocations is not None:
        #     for eventlocation in eventlocations:
        #         flyway_id = eventlocation.get('flyway_id')
        #         if flyway_id is not None and flyway_id not in unique_flyway_ids:
        #             unique_flyway_ids.append(flyway_id)
        #             flyway = Flyway.objects.filter(id=flyway_id).first()
        #             unique_flyways.append(model_to_dict(flyway))
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

    eventdiagnoses = EventDiagnosisSerializer(many=True)
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
        # TODO: implement this once flyways are figured out
        # eventlocations = obj.eventlocations.values()
        # if eventlocations is not None:
        #     for eventlocation in eventlocations:
        #         flyway_id = eventlocation.get('flyway_id')
        #         if flyway_id is not None and flyway_id not in unique_flyway_ids:
        #             unique_flyway_ids.append(flyway_id)
        #             flyway = Flyway.objects.filter(id=flyway_id).first()
        #             unique_flyways.append(model_to_dict(flyway))
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

    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    eventdiagnoses = EventDiagnosisSerializer(many=True)
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
                  'flyways', 'species', 'created_date', 'created_by', 'modified_date', 'modified_by', 'permissions',
                  'permission_source',)


class EventSummaryAdminSerializer(serializers.ModelSerializer):

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
        # TODO: implement this once flyways are figured out
        # eventlocations = obj.eventlocations.values()
        # if eventlocations is not None:
        #     for eventlocation in eventlocations:
        #         flyway_id = eventlocation.get('flyway_id')
        #         if flyway_id is not None and flyway_id not in unique_flyway_ids:
        #             unique_flyway_ids.append(flyway_id)
        #             flyway = Flyway.objects.filter(id=flyway_id).first()
        #             unique_flyways.append(model_to_dict(flyway))
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

    eventdiagnoses = EventDiagnosisSerializer(many=True)
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
                  'species', 'created_date', 'created_by', 'modified_date', 'modified_by', 'permissions',
                  'permission_source',)


class SpeciesDiagnosisDetailPublicSerializer(serializers.ModelSerializer):
    diagnosis_string = serializers.StringRelatedField(source='diagnosis')

    class Meta:
        model = SpeciesDiagnosis
        fields = ('diagnosis', 'diagnosis_string', 'confirmed', 'tested_count', 'diagnosis_count', 'positive_count',
                  'suspect_count', 'pooled',)


class SpeciesDiagnosisDetailSerializer(serializers.ModelSerializer):
    diagnosis_string = serializers.StringRelatedField(source='diagnosis')
    organization_string = serializers.StringRelatedField(source='organization')

    class Meta:
        model = SpeciesDiagnosis
        fields = ('id', 'location_species', 'diagnosis', 'diagnosis_string', 'cause', 'basis', 'confirmed', 'priority',
                  'tested_count', 'diagnosis_count', 'positive_count', 'suspect_count', 'pooled', 'organization',
                  'organization_string',)


class LocationSpeciesDetailPublicSerializer(serializers.ModelSerializer):
    species_string = serializers.StringRelatedField(source='species')
    species_diagnosis = SpeciesDiagnosisDetailPublicSerializer(many=True, source='speciesdiagnoses')

    class Meta:
        model = LocationSpecies
        fields = ('species', 'species_string', 'population_count', 'sick_count', 'dead_count', 'sick_count_estimated',
                  'dead_count_estimated', 'captive', 'age_bias', 'sex_bias', 'species_diagnosis',)


class LocationSpeciesDetailSerializer(serializers.ModelSerializer):
    species_string = serializers.StringRelatedField(source='species')
    species_diagnosis = SpeciesDiagnosisDetailSerializer(many=True, source='speciesdiagnoses')

    class Meta:
        model = LocationSpecies
        fields = ('id', 'event_location', 'species', 'species_string', 'population_count', 'sick_count', 'dead_count',
                  'sick_count_estimated', 'dead_count_estimated', 'priority', 'captive', 'age_bias', 'sex_bias',
                  'species_diagnosis',)


class EventLocationDetailPublicSerializer(serializers.ModelSerializer):
    administrative_level_two_string = serializers.StringRelatedField(source='administrative_level_two')
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')
    country_string = serializers.StringRelatedField(source='country')
    location_species = LocationSpeciesDetailPublicSerializer(many=True, source='locationspecies')

    class Meta:
        model = EventLocation
        fields = ('start_date', 'end_date', 'country', 'country_string', 'administrative_level_one',
                  'administrative_level_one_string', 'administrative_level_two', 'administrative_level_two_string',
                  'county_multiple', 'county_unknown', 'flyway', 'location_species',)


class EventLocationDetailSerializer(serializers.ModelSerializer):
    administrative_level_two_string = serializers.StringRelatedField(source='administrative_level_two')
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')
    country_string = serializers.StringRelatedField(source='country')
    location_species = LocationSpeciesDetailSerializer(many=True, source='locationspecies')
    comments = CommentSerializer(many=True)

    class Meta:
        model = EventLocation
        fields = ('id', 'name', 'event', 'start_date', 'end_date', 'country', 'country_string',
                  'administrative_level_one', 'administrative_level_one_string', 'administrative_level_two',
                  'administrative_level_two_string', 'county_multiple', 'county_unknown', 'latitude', 'longitude',
                  'priority', 'land_ownership', 'flyway', 'location_species', 'comments',)


class EventDiagnosisDetailPublicSerializer(serializers.ModelSerializer):
    diagnosis_string = serializers.StringRelatedField(source='diagnosis')

    class Meta:
        model = EventDiagnosis
        fields = ('diagnosis', 'diagnosis_string', 'confirmed', 'major',)


class EventDiagnosisDetailSerializer(serializers.ModelSerializer):
    diagnosis_string = serializers.StringRelatedField(source='diagnosis')

    class Meta:
        model = EventDiagnosis
        fields = ('id', 'event', 'diagnosis', 'diagnosis_string', 'confirmed', 'major', 'priority',)


class EventDetailPublicSerializer(serializers.ModelSerializer):
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    event_locations = EventLocationDetailPublicSerializer(many=True, source='eventlocations')
    event_diagnoses = EventDiagnosisDetailPublicSerializer(many=True, source='eventdiagnoses')

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
                  'event_diagnoses', 'event_locations', 'permissions', 'permission_source',)


class EventDetailSerializer(serializers.ModelSerializer):
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    event_locations = EventLocationDetailSerializer(many=True, source='eventlocations')
    event_diagnoses = EventDiagnosisDetailSerializer(many=True, source='eventdiagnoses')
    event_organizations = EventOrganizationSerializer(many=True, source='organizations')
    comments = CommentSerializer(many=True)

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
                  'affected_count', 'public', 'event_diagnoses', 'event_locations', 'event_organizations', 'comments',
                  'permissions', 'permission_source',)


class EventDetailAdminSerializer(serializers.ModelSerializer):
    permissions = DRYPermissionsField()
    permission_source = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    staff_string = serializers.StringRelatedField(source='staff')
    event_status_string = serializers.StringRelatedField(source='event_status')
    legal_status_string = serializers.StringRelatedField(source='legal_status')
    event_locations = EventLocationDetailSerializer(many=True, source='eventlocations')
    event_diagnoses = EventDiagnosisDetailSerializer(many=True, source='eventdiagnoses')
    event_organizations = EventOrganizationSerializer(many=True, source='organizations')
    comments = CommentSerializer(many=True)

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
                  'legal_status', 'legal_status_string', 'legal_number', 'quality_check', 'public',
                  'superevents', 'event_diagnoses', 'event_locations', 'event_organizations', 'comments',
                  'created_date', 'created_by', 'modified_date', 'modified_by', 'permissions', 'permission_source',)
