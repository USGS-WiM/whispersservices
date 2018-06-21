from django.forms.models import model_to_dict
from rest_framework import serializers
from whispersservices.models import *
from dry_rest_permissions.generics import DRYPermissionsField


######
#
#  Events
#
######


class EventPublicSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    permissions = DRYPermissionsField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    staff_string = serializers.StringRelatedField(source='staff')
    event_status_string = serializers.StringRelatedField(source='event_status')
    legal_status_string = serializers.StringRelatedField(source='legal_status')

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'complete', 'start_date', 'end_date', 'affected_count',
                  'permissions',)


class EventSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    permissions = DRYPermissionsField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    new_event_locations = serializers.ListField(write_only=True)

    def create(self, data):

        # pull out child event_locations list from the request
        event_locations = data.pop('new_event_locations', None)

        user = self.context['request'].user
        event = Event.objects.create(**data)

        # create the child event_locations for this event
        # if event_locations is not None:
        for event_location in event_locations:
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
            event_location['land_ownership'] = LandOwnership.objects.filter(pk=event_location['land_ownership']).first()

            # create object for comment creation while removing unserialized fields for EventLocation
            comments = {'site_description': event_location.pop('site_description', None),
                        'history': event_location.pop('history', None),
                        'environmental_factors': event_location.pop('environmental_factors', None),
                        'clinical_signs': event_location.pop('clinical_signs', None)}

            # delete comments in object until I have methods to deal with them
            comment_temp = event_location.pop('comment', None)

            # create the event_location and return object for use in event_location_contacts object
            evt_location = EventLocation.objects.create(**event_location)

            # loop through comments and create comments that will add to event_location as a FK
            comment_names = {'site_description': 3, 'history': 4, 'environmental_factors': 5, 'clinical_signs': 6}

            for key, value in comment_names.items():

                comment_type = CommentType.objects.filter(pk=value).first()

                if comments[key] is not None and len(comments[key]) > 0:
                    # need to figure out how to get instance of event for the id field in Comment
                    Comment.objects.create(table="EventLocation", object=evt_location.id, comment=comments[key],
                                           comment_type=comment_type, keywords="")

            # Create EventLocationContacts
            if location_contacts is not None:
                for location_contact in location_contacts:
                    location_contact['event_location'] = evt_location

                    # Convert ids to ForeignKey objects
                    location_contact['contact'] = Contact.objects.filter(pk=location_contact['id']).first()
                    location_contact['contact_type'] = ContactType.objects.filter(
                        pk=location_contact['contact_type']).first()
                    del location_contact['id']

                    EventLocationContact.objects.create(**location_contact)

            # Create EventLocationSpecies
            if location_species is not None:
                for location_spec in location_species:
                    location_spec['event_location'] = evt_location

                    # Convert ids to ForeignKey objects
                    location_spec['species'] = Species.objects.filter(pk=location_spec['species']).first()
                    location_spec['age_bias'] = AgeBias.objects.filter(pk=location_spec['age_bias']).first()
                    location_spec['sex_bias'] = SexBias.objects.filter(pk=location_spec['sex_bias']).first()

                    LocationSpecies.objects.create(**location_spec)

        return event

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'public',
                  'created_date', 'created_by', 'modified_date', 'modified_by', 'permissions',)


class EventAdminSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    permissions = DRYPermissionsField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    staff_string = serializers.StringRelatedField(source='staff')
    event_status_string = serializers.StringRelatedField(source='event_status')
    legal_status_string = serializers.StringRelatedField(source='legal_status')

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string',
                  'legal_status', 'legal_status_string', 'legal_number', 'quality_check', 'public',
                  'superevents', 'organizations', 'contacts',
                  'created_date', 'created_by', 'modified_date', 'modified_by', 'permissions',)


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


class EpiStaffSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = EpiStaff
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
        fields = ('organization',)


class EventOrganizationSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = EventOrganization
        fields = ('id', 'event', 'organization', 'created_date', 'created_by', 'modified_date', 'modified_by',)


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

    class Meta:
        model = EventLocation
        fields = ('id', 'name', 'event', 'start_date', 'end_date', 'country', 'country_string',
                  'administrative_level_one', 'administrative_level_one_string', 'administrative_level_two',
                  'administrative_level_two_string', 'county_multiple', 'county_unknown', 'latitude', 'longitude',
                  'priority', 'land_ownership', 'flyway', 'contacts',
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


class DiagnosisSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Diagnosis
        fields = ('id', 'name', 'diagnosis_type', 'created_date', 'created_by', 'modified_date', 'modified_by',)


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


class SpeciesDiagnosisSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    diagnosis_string = serializers.StringRelatedField(source='diagnosis')

    class Meta:
        model = SpeciesDiagnosis
        fields = ('id', 'location_species', 'diagnosis', 'diagnosis_string', 'confirmed', 'major', 'priority', 'causal',
                  'tested_count', 'positive_count', 'suspect_count', 'pooled', 'organization',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


######
#
#  Misc
#
######


class PermissionSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Permission
        fields = ('id', 'organization', 'role', 'group', 'table', 'object', 'permission_type',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class PermissionTypeSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = PermissionType
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class CommentSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Comment
        fields = ('id', 'table', 'object', 'comment', 'comment_type', 'keywords', 'link', 'link_type',
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
#  Users
#
######


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    role = serializers.PrimaryKeyRelatedField(source='userprofile.role', queryset=Role.objects.all())
    organization = serializers.PrimaryKeyRelatedField(source='userprofile.organization',
                                                      queryset=Organization.objects.all())

    def create(self, validated_data):
        password = validated_data['password']
        user = User.objects.create(**validated_data)

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
        fields = ('id', 'username', 'password', 'first_name', 'last_name', 'email', 'groups', 'user_permissions',
                  'is_superuser', 'is_staff', 'is_active', 'role', 'organization', 'circles',
                  'last_login', 'active_key', 'user_status',)


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
        fields = ('id', 'name', 'private_name', 'address_one', 'address_two', 'city', 'zip_postal_code',
                  'administrative_level_one', 'country', 'phone', 'parent_organization', 'do_not_publish',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class ContactSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Contact
        fields = ('id', 'first_name', 'last_name', 'email', 'phone', 'affiliation', 'title', 'position', 'organization',
                  'owner_organization', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class ContactTypeSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = ContactType
        fields = ('id', 'name', 'created_date', 'created_by', 'modified_date', 'modified_by',)


class SearchSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()

    class Meta:
        model = Search
        fields = ('id', 'name', 'owner', 'data', 'created_date', 'created_by', 'modified_date', 'modified_by',)


######
#
#  Special
#
######


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

    eventdiagnoses = EventDiagnosisSerializer(many=True)
    administrativelevelones = serializers.SerializerMethodField()
    administrativeleveltwos = serializers.SerializerMethodField()
    flyways = serializers.SerializerMethodField()
    species = serializers.SerializerMethodField()
    event_type_string = serializers.StringRelatedField(source='event_type')
    event_status_string = serializers.StringRelatedField(source='event_status')

    class Meta:
        model = Event
        fields = ('id', 'affected_count', 'start_date', 'end_date', 'complete', 'event_type', 'event_type_string',
                  'eventdiagnoses', 'administrativelevelones', 'administrativeleveltwos', 'flyways', 'species',
                  'created_date', 'created_by', 'modified_date', 'modified_by',)


class OrganizationDetailSerializer(serializers.ModelSerializer):

    class Meta:
        model = Organization
        fields = ('id', 'name',)


class DiagnosisDetailSerializer(serializers.ModelSerializer):
    diagnosis_type_string = serializers.StringRelatedField(many=True, source='diagnosis_type')

    class Meta:
        model = Diagnosis
        fields = ('id', 'name', 'diagnosis_type', 'diagnosis_type_string')


class SpeciesDiagnosisDetailSerializer(serializers.ModelSerializer):
    diagnosis = DiagnosisSerializer(many=True, source='diagnosis')
    organization = OrganizationDetailSerializer(many=True, source='organization')

    class Meta:
        model = SpeciesDiagnosis
        fields = ('id', 'location_species', 'diagnosis', 'confirmed', 'major', 'priority', 'causal',
                  'tested_count', 'positive_count', 'suspect_count', 'pooled', 'organization',)


class LocationSpeciesDetailSerializer(serializers.ModelSerializer):
    species_string = serializers.StringRelatedField(source='species')
    species_diagnosis = SpeciesDiagnosisDetailSerializer(many=True, source='speciesdiagnoses')

    class Meta:
        model = LocationSpecies
        fields = ('id', 'event_location', 'species', 'species_string', 'population_count', 'sick_count', 'dead_count',
                  'sick_count_estimated', 'dead_count_estimated', 'priority', 'captive', 'age_bias', 'sex_bias',
                  'species_diagnosis',)


class EventLocationDetailSerializer(serializers.ModelSerializer):
    administrative_level_two_string = serializers.StringRelatedField(source='administrative_level_two')
    administrative_level_one_string = serializers.StringRelatedField(source='administrative_level_one')
    country_string = serializers.StringRelatedField(source='country')
    location_species = LocationSpeciesDetailSerializer(many=True, source='locationspecies')

    class Meta:
        model = EventLocation
        fields = ('id', 'name', 'event', 'start_date', 'end_date', 'country', 'country_string',
                  'administrative_level_one', 'administrative_level_one_string', 'administrative_level_two',
                  'administrative_level_two_string', 'county_multiple', 'county_unknown', 'latitude', 'longitude',
                  'priority', 'land_ownership', 'flyway', 'location_species',)


class EventDiagnosisDetailSerializer(serializers.ModelSerializer):
    diagnosis_string = serializers.StringRelatedField(source='diagnosis')

    class Meta:
        model = EventDiagnosis
        fields = ('id', 'event', 'diagnosis', 'diagnosis_string', 'confirmed', 'major', 'priority',)


class EventDetailSerializer(serializers.ModelSerializer):
    event_type_string = serializers.StringRelatedField(source='event_type')
    staff_string = serializers.StringRelatedField(source='staff')
    event_status_string = serializers.StringRelatedField(source='event_status')
    legal_status_string = serializers.StringRelatedField(source='legal_status')
    event_locations = EventLocationDetailSerializer(many=True, source='eventlocations')
    event_diagnoses = EventDiagnosisDetailSerializer(many=True, source='eventdiagnoses')

    class Meta:
        model = Event
        fields = ('id', 'event_type', 'event_type_string', 'event_reference', 'complete', 'start_date', 'end_date',
                  'affected_count', 'staff', 'staff_string', 'event_status', 'event_status_string',
                  'legal_status', 'legal_status_string', 'legal_number', 'superevent', 'event_diagnoses',
                  'event_locations', 'created_date', 'created_by', 'modified_date', 'modified_by',)
