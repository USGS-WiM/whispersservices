from django.db import models
from datetime import date
from django.db.models import Q
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField, ArrayField
from django.conf import settings
from simple_history.models import HistoricalRecords
from celery import current_app


# Default fields of the core User model: username, first_name, last_name, email, password, groups, user_permissions,
# is_staff, is_active, is_superuser, last_login, date_joined
# For more information, see: https://docs.djangoproject.com/en/2.0/ref/contrib/auth/#user


def partner_create_permission(request):
    # anyone with role of Partner or above can create
    if (not request or not request.user or not request.user.is_authenticated or request.user.role.is_public
            or request.user.role.is_affiliate):
        return False
    elif (request.user.role.is_superadmin or request.user.role.is_admin or request.user.role.is_partneradmin
          or request.user.role.is_partnermanager or request.user.role.is_partner):
        return True
    else:
        return False


def determine_create_permission(request, event):
    # For models that are children of events (e.g., eventlocation, locationspecies, speciesdiagnosis),
    # only admins or the creator or a manager/admin member of the creator's org or a write_collaborator can create
    if (not request or not request.user or not request.user.is_authenticated
            or request.user.role.is_public or request.user.role.is_affiliate):
        return False
    elif request.user.role.is_superadmin or request.user.role.is_admin:
        return True
    else:
        if (request.user.id == event.created_by.id
                or (request.user.organization.id == event.created_by.organization.id
                    and (request.user.role.is_partneradmin or request.user.role.is_partnermanager))):
            return True
        else:
            write_collaborators = list(User.objects.filter(writeevents__in=[event.id]).values_list('id', flat=True))
            return request.user.id in write_collaborators


def determine_object_update_permission(self, request, event_id):
    # Only admins or the creator or a manager/admin member of the creator's org or a write_collaborator can update
    if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
        return False
    elif (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.created_by.id
          or (request.user.organization.id == self.created_by.organization.id
              and (request.user.role.is_partneradmin or request.user.role.is_partnermanager))):
        return True
    else:
        write_collaborators = list(User.objects.filter(writeevents__in=[event_id]).values_list('id', flat=True))
        return request.user.id in write_collaborators


######
#
#  Abstract Base Classes
#
######


class HistoryModel(models.Model):
    """
    An abstract base class model to track creation, modification, and data change history.
    """

    created_date = models.DateField(default=date.today, null=True, blank=True, db_index=True, help_text='The date this object was created in "YYYY-MM-DD" format')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, db_index=True,
                                   related_name='%(class)s_creator', help_text='A foreign key integer identifying the user who created the object')
    modified_date = models.DateField(auto_now=True, null=True, blank=True, help_text='The date this object was last modified on in "YYYY-MM-DD" format')
    modified_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, db_index=True,
                                    related_name='%(class)s_modifier', help_text='A foreign key integer identifying the user who last modified the object')
    history = HistoricalRecords(inherit=True)

    class Meta:
        abstract = True
        default_permissions = ('add', 'change', 'delete', 'view')


class PermissionsHistoryModel(HistoryModel):
    """
    An abstract base class model for the common permissions.
    """

    @staticmethod
    def has_read_permission(request):
        # Everyone can read (list and retrieve), but some fields may be private
        return True

    def has_object_read_permission(self, request):
        # Everyone can read (list and retrieve), but some fields may be private
        return True

    @staticmethod
    def has_write_permission(request):
        # Only users with specific roles can 'write'
        # (note that update and destroy are handled explicitly below, so 'write' now only pertains to create)
        # Currently this list is 'SuperAdmin', 'Admin', 'PartnerAdmin', 'PartnerManager', 'Partner', and 'Affiliate'
        # (which only excludes 'Public', but could possibly change... explicit is better than implicit)
        if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            return False
        else:
            return (request.user.role.is_superadmin or request.user.role.is_admin or request.user.role.is_partneradmin
                    or request.user.role.is_partnermanager or request.user.role.is_partner
                    or request.user.role.is_affiliate)

    # # moved this to each child model instead of abstract model
    # @staticmethod
    # def has_create_permission(request):
    #     # For models that are children of events (e.g., eventlocation, locationspecies, speciesdiagnosis),
    #     # only admins or the creator or a manager/admin member of the creator's org or a write_collaborator can update
    #     if (not request or not request.user or not request.user.is_authenticated
    #             or request.user.role.is_public or request.user.role.is_affiliate):
    #         return False
    #     elif request.user.role.is_superadmin or request.user.role.is_admin:
    #         return True
    #     elif request.user.role.is_partneradmin or request.user.role.is_partnermanager or request.user.role.is_partner:
    #         model = request.parser_context['view'].get_serializer_class().Meta.model
    #         model_name = ContentType.objects.get_for_model(model, for_concrete_model=True).model
    #         if model_name in ['event', 'servicerequest', 'circle', 'circleuser', 'contact', 'search']:
    #             return True
    #         else:
    #             if model_name not in ['eventlocation', 'eventdiagnosis', 'eventorganization', 'eventcontact',
    #                                   'locationspecies', 'eventlocationcontact', 'eventlocationflyway',
    #                                   'speciesdiagnosis', 'speciesdiagnosisorganization']:
    #                 return False
    #             elif model_name in ['eventlocation', 'eventdiagnosis', 'eventorganization', 'eventcontact']:
    #                 event = Event.objects.get(pk=int(request.data['event']))
    #             elif model_name in ['locationspecies', 'eventlocationcontact', 'eventlocationflyway']:
    #                 event = EventLocation.objects.get(pk=int(request.data['event_location'])).event
    #             elif model_name == 'speciesdiagnosis':
    #                 event = LocationSpecies.objects.get(
    #                     pk=int(request.data['location_species'])).event_location.event
    #             elif model_name == 'speciesdiagnosisorganization':
    #                 event = LocationSpecies.objects.get(
    #                     pk=int(request.data['species_diagnosis'])).location_species.event_location.event
    #             if (request.user.id == event.created_by.id
    #                     or (request.user.organization.id == event.created_by.organization.id
    #                         and (request.user.role.is_partneradmin or request.user.role.is_partnermanager))):
    #                 return True
    #             else:
    #                 return False
    #     else:
    #         return False
    #
    # # moved this to each child model instead of abstract model
    # def has_object_update_permission(self, request):
    #     # Only admins or the creator or a manager/admin member of the creator's org or a write_collaborator can update
    #     if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
    #         return False
    #     elif (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.created_by.id
    #           or (request.user.organization.id == self.created_by.organization.id
    #               and (request.user.role.is_partneradmin or request.user.role.is_partnermanager))):
    #         return True
    #     else:
    #         model_name = ContentType.objects.get_for_model(self, for_concrete_model=True).model
    #         if model_name not in ['event', 'eventlocation', 'eventdiagnosis', 'eventorganization', 'eventcontact',
    #                               'locationspecies', 'eventlocationcontact', 'eventlocationflyway',
    #                               'speciesdiagnosis', 'speciesdiagnosisorganization']:
    #             return False
    #         elif model_name == 'event':
    #             event_id = self.id
    #         elif model_name in ['eventlocation', 'eventdiagnosis', 'eventorganization', 'eventcontact']:
    #             event_id = self.event.id
    #         elif model_name in ['locationspecies', 'eventlocationcontact', 'eventlocationflyway']:
    #             event_id = self.event_location.event.id
    #         elif model_name == 'speciesdiagnosis':
    #             event_id = self.location_species.event_location.event.id
    #         elif model_name == 'speciesdiagnosisorganization':
    #             event_id = self.species_diagnosis.location_species.event_location.event.id
    #         write_collaborators = list(User.objects.filter(writeevents__in=[event_id]).values_list('id', flat=True))
    #         return True if request.user.id in write_collaborators else False

    def has_object_destroy_permission(self, request):
        # Only superadmins or the creator or a manager/admin member of the creator's organization can delete
        if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            return False
        else:
            return (request.user.role.is_superadmin or request.user.role.is_admin
                    or request.user.id == self.created_by.id
                    or (request.user.organization.id == self.created_by.organization.id
                        and (request.user.role.is_partneradmin or request.user.role.is_partnermanager)))

    class Meta:
        abstract = True


class AdminPermissionsHistoryModel(HistoryModel):
    """
    An abstract base class model for administrator-only permissions.
    """

    @staticmethod
    def has_read_permission(request):
        # Everyone can read (list and retrieve), but some fields may be private
        return True

    def has_object_read_permission(self, request):
        # Everyone can read (list and retrieve), but some fields may be private
        return True

    @staticmethod
    def has_write_permission(request):
        # Only superadmins or admins can write (create, update, delete)
        if not request or not request.user.is_authenticated:
            return False
        else:
            return request.user.role.is_superadmin or request.user.role.is_admin

    def has_object_write_permission(self, request):
        # Only superadmins or admins can write (create, update, delete)
        if not request or not request.user or not request.user.is_authenticated:
            return False
        else:
            return request.user.role.is_superadmin or request.user.role.is_admin

    class Meta:
        abstract = True


class AdminPermissionsHistoryNameModel(AdminPermissionsHistoryModel):
    """
    An abstract base class model for administrator-only permissions with the common name field.
    """

    name = models.CharField(max_length=128, unique=True, help_text='An alphanumeric value of the name of this object')

    class Meta:
        abstract = True


######
#
#  Events
#
######


class Event(PermissionsHistoryModel):
    """
    Event
    """

    event_type = models.ForeignKey('EventType', models.PROTECT, related_name='events', help_text='A foreign key integer value identifying a wildlife morbidity or mortality event')
    event_reference = models.CharField(max_length=128, blank=True, default='', help_text='Name or number for an event designated by event owner')
    complete = models.BooleanField(default=False, help_text='A boolean value indicating if an event is complete or incomplete. A complete event means it has ended, diagnostic tests are completed, and all information is updated in WHISPers')
    start_date = models.DateField(null=True, blank=True, db_index=True, help_text='The date this event started on')
    end_date = models.DateField(null=True, blank=True, db_index=True, help_text='The date this event ended on')
    affected_count = models.IntegerField(null=True, db_index=True, help_text='An integer value for total number affected in this event')
    staff = models.ForeignKey('Staff', models.PROTECT, null=True, related_name='events', help_text='A foreign key integer value identifying a staff member')
    event_status = models.ForeignKey('EventStatus', models.PROTECT, null=True, related_name='events', default=1, help_text='A foreign key integer value identifying event statuses specific to NWHC.')
    legal_status = models.ForeignKey('LegalStatus', models.PROTECT, null=True, related_name='events', default=1, help_text='A foreign key integer value identifying legal procedures associated with an event')
    legal_number = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of legal case identifier')
    quality_check = models.DateField(null=True, help_text='The date an NWHC staff and event owner make changes and check the record')
    public = models.BooleanField(default=True, help_text='A boolean value indicating if an event is public or not')
    read_collaborators = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through='EventReadUser', through_fields=('event', 'user'), related_name='readevents')
    write_collaborators = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through='EventWriteUser', through_fields=('event', 'user'), related_name='writeevents')
    eventgroups = models.ManyToManyField('EventGroup', through='EventEventGroup', related_name='events', help_text='A foreign key integer identifying the user who last modified the object')
    organizations = models.ManyToManyField('Organization', through='EventOrganization', related_name='events', help_text='A many to many releationship of organizations based on a foreign key integer value indentifying an organization')
    contacts = models.ManyToManyField('Contact', through='EventContact', related_name='event')
    comments = GenericRelation('Comment', related_name='events')

    @staticmethod
    def has_create_permission(request):
        # anyone with role of Partner or above can create
        return partner_create_permission(request)

    def has_object_update_permission(self, request):
        return determine_object_update_permission(self, request, self.id)

    # override the save method to toggle quality check field when complete field changes
    # and update event diagnoses as necessary so there is always at least one
    def save(self, *args, **kwargs):
        # Disable Quality check field until field "complete" =1.
        # If event reopened ("complete" = 0) then "quality_check" = null AND quality check field is disabled
        if not self.complete:
            self.quality_check = None
        super(Event, self).save(*args, **kwargs)

        def get_event_diagnoses():
            event_diagnoses = EventDiagnosis.objects.filter(event=self.id)
            return event_diagnoses if event_diagnoses is not None else []

        diagnosis = None

        # If complete = 0 then: a. delete if diagnosis is Undetermined, b. if count of event_diagnosis = 0
        #  then insert diagnosis Pending, c. if count of event_diagnosis >= 1 then do nothing
        if not self.complete:
            [evt_diag.delete() for evt_diag in get_event_diagnoses() if evt_diag.diagnosis.name == 'Undetermined']
            if len(get_event_diagnoses()) == 0:
                diagnosis = Diagnosis.objects.filter(name='Pending').first()
        # If complete = 1 then: a. delete if diagnosis is Pending, b. if count of event_diagnosis = 0
        #  then insert diagnosis Undetermined, c. if count of event_diagnosis >= 1 then do nothing
        else:
            [evt_diag.delete() for evt_diag in get_event_diagnoses() if evt_diag.diagnosis.name == 'Pending']
            if len(get_event_diagnoses()) == 0:
                diagnosis = Diagnosis.objects.filter(name='Undetermined').first()

        if diagnosis:
            # All "Pending" and "Undetermined" must be confirmed OR some other way of coding this
            # such that we never see "Pending suspect" or "Undetermined suspect" on front end.
            EventDiagnosis.objects.create(event=self, diagnosis=diagnosis, suspect=False, priority=1,
                                          created_by=self.created_by, modified_by=self.modified_by)

        # calculate event start_date and end_date and affected_count based on child locations
        locations = EventLocation.objects.filter(event=self.id).values('id', 'start_date', 'end_date')

        # start_date and end_date
        # Start date: Earliest date from locations to be used.
        # End date: If 1 or more location end dates is null then leave blank, otherwise use latest date from locations.
        if len(locations) > 0:
            start_dates = [loc['start_date'] for loc in locations if loc['start_date'] is not None]
            self.start_date = min(start_dates) if len(start_dates) > 0 else None
            end_dates = [loc['end_date'] for loc in locations]
            if len(end_dates) < 1 or None in end_dates:
                self.end_date = None
            else:
                self.end_date = max(end_dates)
        else:
            self.start_date = None
            self.end_date = None

        # affected_count
        # If EventType = Morbidity/Mortality
        # then Sum(Max(estimated_dead, dead) + Max(estimated_sick, sick)) from location_species table
        # If Event Type = Surveillance then Sum(number_positive) from species_diagnosis table
        event_type_id = self.event_type.id
        if event_type_id not in [1, 2]:
            self.affected_count = None
        else:
            loc_ids = [loc['id'] for loc in locations]
            loc_species = LocationSpecies.objects.filter(
                event_location_id__in=loc_ids).values(
                'id', 'dead_count_estimated', 'dead_count', 'sick_count_estimated', 'sick_count')
            if event_type_id == 1:
                affected_counts = [max(spec.get('dead_count_estimated') or 0, spec.get('dead_count') or 0)
                                   + max(spec.get('sick_count_estimated') or 0, spec.get('sick_count') or 0)
                                   for spec in loc_species]
                self.affected_count = sum(affected_counts)
            elif event_type_id == 2:
                loc_species_ids = [spec['id'] for spec in loc_species]
                species_dx_positive_counts = SpeciesDiagnosis.objects.filter(
                    location_species_id__in=loc_species_ids).values_list('positive_count', flat=True)
                # positive_counts = [dx.get('positive_count') or 0 for dx in species_dx]
                self.affected_count = sum(species_dx_positive_counts) if len(species_dx_positive_counts) == 0 else None

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_event"
        ordering = ['-id']
        # TODO: 'unique together' fields
        # The event record must be uniquely identified by the submission agency, event date, and location.


class EventEventGroup(AdminPermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Events and Super Events.
    """

    event = models.ForeignKey('Event', models.CASCADE, help_text='A foreign key integer value identifying an event')
    eventgroup = models.ForeignKey('EventGroup', models.CASCADE, help_text='A foreign key integer identifying an event group')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventeventgroup"
        ordering = ['id']
        unique_together = ('event', 'eventgroup')


class EventGroup(AdminPermissionsHistoryModel):
    """
    Event Group
    """

    @property
    def name(self):
        return "G" + str(self.id)

    category = models.ForeignKey('EventGroupCategory', models.CASCADE, related_name='eventgroups')
    comments = GenericRelation('Comment', related_name='eventgroups')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventgroup"
        ordering = ['id']


class EventGroupCategory(AdminPermissionsHistoryNameModel):
    """
    Event Group Category
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_eventgroupcategory"
        verbose_name_plural = "categories"
        ordering = ['id']


class EventType(AdminPermissionsHistoryNameModel):
    """
    Event Type
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_eventtype"
        ordering = ['id']


class Staff(AdminPermissionsHistoryModel):
    """
    Staff
    """

    first_name = models.CharField(max_length=128, help_text='An alphanumeric value of the staff members first name')
    last_name = models.CharField(max_length=128, help_text='An alphanumeric value of the staff members last name')
    role = models.ForeignKey('Role', models.PROTECT, related_name='staff', help_text='A foreign key integer value for the staff role')
    active = models.BooleanField(default=False, help_text='A boolean value indication if a staff memeber is active or not')

    def __str__(self):
        return self.first_name + " " + self.last_name

    class Meta:
        db_table = "whispers_staff"
        ordering = ['id']


class LegalStatus(AdminPermissionsHistoryNameModel):
    """
    Legal Status
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_legalstatus"
        ordering = ['id']


class EventStatus(AdminPermissionsHistoryNameModel):
    """
    Event Status
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_eventstatus"
        verbose_name_plural = "eventstatuses"
        ordering = ['id']


class EventAbstract(PermissionsHistoryModel):
    """
    Event Abstract
    """

    event = models.ForeignKey('Event', models.CASCADE, related_name='eventabstracts', help_text='A foreign key integer value identifying an event')
    text = models.TextField(blank=True, help_text='An alphanumeric value of information')
    lab_id = models.IntegerField(null=True, help_text='An integer value identifying a lab')

    @staticmethod
    def has_create_permission(request):
        if request and 'event' in request.data:
            event = Event.objects.get(pk=int(request.data['event']))
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.event.id
        return determine_object_update_permission(self, request, event_id)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventabstract"
        ordering = ['id']


class EventCase(PermissionsHistoryModel):
    """
    Event Case
    """

    event = models.ForeignKey('Event', models.CASCADE, related_name='eventcases', help_text='A foreign key integer value identifying an event')
    case = models.CharField(max_length=6, blank=True, default='', help_text='An alphanumeric value of information on a case')

    @staticmethod
    def has_create_permission(request):
        if request and 'event' in request.data:
            event = Event.objects.get(pk=int(request.data['event']))
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.event.id
        return determine_object_update_permission(self, request, event_id)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventcase"
        ordering = ['id']


class EventLabsite(PermissionsHistoryModel):
    """
    Event Labsite
    """

    event = models.ForeignKey('Event', models.CASCADE, related_name='eventlabsites', help_text='A foreign key integer value identifying an event')
    lab_id = models.IntegerField(null=True, help_text='An integer value identifying a lab')

    @staticmethod
    def has_create_permission(request):
        if request and 'event' in request.data:
            event = Event.objects.get(pk=int(request.data['event']))
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.event.id
        return determine_object_update_permission(self, request, event_id)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventlabsite"
        ordering = ['id']


class EventOrganization(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Events and Organizations.
    """

    event = models.ForeignKey('Event', models.CASCADE, help_text='A foreign key integer value identifying an event')
    organization = models.ForeignKey('Organization', models.CASCADE, help_text='A foreign key integer value identifying a organization')
    priority = models.IntegerField(null=True, help_text='An integer value indicating the event organizations priority')

    @staticmethod
    def has_create_permission(request):
        if request and 'event' in request.data:
            event = Event.objects.get(pk=int(request.data['event']))
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.event.id
        return determine_object_update_permission(self, request, event_id)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventorganization"
        ordering = ['event', 'priority']
        unique_together = ('event', 'organization')


class EventContact(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Events and Contacts.
    """

    event = models.ForeignKey('Event', models.CASCADE, help_text='A foreign key integer value identifying an event')
    contact = models.ForeignKey('Contact', models.CASCADE, help_text='A foreign key integer value indentifying a contact')

    @staticmethod
    def has_create_permission(request):
        if request and 'event' in request.data:
            event = Event.objects.get(pk=int(request.data['event']))
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.event.id
        return determine_object_update_permission(self, request, event_id)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventcontact"
        ordering = ['id']


######
#
#  Locations
#
######


class EventLocation(PermissionsHistoryModel):
    """
    Event Location
    """

    name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the name of this event location')
    event = models.ForeignKey('Event', models.CASCADE, related_name='eventlocations', help_text='A foreign key integer value identifying an event')
    start_date = models.DateField(null=True, blank=True, help_text='The date of the event start at this location in "YYYY-MM-DD" format')
    end_date = models.DateField(null=True, blank=True, help_text='The date of the event end at this location in "YYYY-MM-DD" format')
    country = models.ForeignKey('Country', models.PROTECT, related_name='eventlocations', help_text='A foreign key integer value identifying the country to which this event location belongs')
    administrative_level_one = models.ForeignKey(
        'AdministrativeLevelOne', models.PROTECT, related_name='eventlocations', help_text='A foreign key integer value identifying the administrative level one to which this event location belongs')
    administrative_level_two = models.ForeignKey(
        'AdministrativeLevelTwo', models.PROTECT, null=True, related_name='eventlocations', help_text='A foreign key integer value identifying the administrative level two to which this event location belongs')
    county_multiple = models.BooleanField(default=False, help_text='A boolean value indicating that the event location spans multiple counties or not')
    county_unknown = models.BooleanField(default=False, help_text='A boolean value indicating that the event location county is unkown or not')
    latitude = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True, help_text='A fixed-precision decimal number value indentifying the latitude for this event location')
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text='A fixed-precision decimal number value indentifying the longitude for this event location')
    priority = models.IntegerField(null=True, help_text='An intger value indicating the event locations priority. Can be used to set order of display based on importance')
    land_ownership = models.ForeignKey('LandOwnership', models.PROTECT, null=True, related_name='eventlocations', help_text='A foreign key integer value identifying the entity that owns the land for this event location')
    contacts = models.ManyToManyField('Contact', through='EventLocationContact', related_name='eventlocations', help_text='')
    flyways = models.ManyToManyField('Flyway', through='EventLocationFlyway', related_name='eventlocations')
    gnis_name = models.CharField(max_length=256, blank=True, default='', help_text='An alphanumeric value of the GNIS name of this event location')
    gnis_id = models.CharField(max_length=256, blank=True, db_index=True, default='')
    comments = GenericRelation('Comment', related_name='eventlocations')

    @staticmethod
    def has_create_permission(request):
        if request and 'event' in request.data:
            event = Event.objects.get(pk=int(request.data['event']))
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.event.id
        return determine_object_update_permission(self, request, event_id)

    # override the save method to calculate the parent event's start_date and end_date and affected_count
    def save(self, *args, **kwargs):
        super(EventLocation, self).save(*args, **kwargs)

        event = Event.objects.filter(id=self.event.id).first()
        locations = EventLocation.objects.filter(event=event.id).values('id', 'start_date', 'end_date')

        # start_date and end_date
        # Start date: Earliest date from locations to be used.
        # End date: If 1 or more location end dates is null then leave blank, otherwise use latest date from locations.
        if len(locations) > 0:
            start_dates = [loc['start_date'] for loc in locations if loc['start_date'] is not None]
            event.start_date = min(start_dates) if len(start_dates) > 0 else None
            end_dates = [loc['end_date'] for loc in locations]
            if len(end_dates) < 1 or None in end_dates:
                event.end_date = None
            else:
                event.end_date = max(end_dates)
        else:
            event.start_date = None
            event.end_date = None

        # affected_count
        # If EventType = Morbidity/Mortality
        # then Sum(Max(estimated_dead, dead) + Max(estimated_sick, sick)) from location_species table
        # If Event Type = Surveillance then Sum(number_positive) from species_diagnosis table
        event_type_id = event.event_type.id
        if event_type_id not in [1, 2]:
            event.affected_count = None
        else:
            loc_ids = [loc['id'] for loc in locations]
            loc_species = LocationSpecies.objects.filter(
                event_location_id__in=loc_ids).values(
                'id', 'dead_count_estimated', 'dead_count', 'sick_count_estimated', 'sick_count')
            if event_type_id == 1:
                affected_counts = [max(spec.get('dead_count_estimated') or 0, spec.get('dead_count') or 0)
                                   + max(spec.get('sick_count_estimated') or 0, spec.get('sick_count') or 0)
                                   for spec in loc_species]
                event.affected_count = sum(affected_counts)
            elif event_type_id == 2:
                loc_species_ids = [spec['id'] for spec in loc_species]
                species_dx_positive_counts = SpeciesDiagnosis.objects.filter(
                    location_species_id__in=loc_species_ids).values_list('positive_count', flat=True)
                # positive_counts = [dx.get('positive_count') or 0 for dx in species_dx]
                event.affected_count = sum(species_dx_positive_counts) if len(species_dx_positive_counts) == 0 else None

        event.save()

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_eventlocation"
        ordering = ['event', 'priority']


class EventLocationContact(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Event Locations and Contacts.
    """

    event_location = models.ForeignKey('EventLocation', models.CASCADE, help_text='A foreign key integer value identifying the event location')
    contact = models.ForeignKey('Contact', models.CASCADE, help_text='A foreign key integer value identifying the contact')
    contact_type = models.ForeignKey('ContactType', models.PROTECT, null=True, related_name='eventlocationcontacts', help_text='A foreign key integer value identifying the contact type for this event location contact')

    @staticmethod
    def has_create_permission(request):
        if request and 'event_location' in request.data:
            event = EventLocation.objects.get(pk=int(request.data['event_location'])).event
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.event_location.event.id
        return determine_object_update_permission(self, request, event_id)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventlocationcontact"
        ordering = ['id']


class Country(AdminPermissionsHistoryNameModel):
    """
    Country
    """

    abbreviation = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the usual abbreviation of this country')
    calling_code = models.IntegerField(null=True, help_text='An integer value identifying the calling code for this country')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_country"
        verbose_name_plural = "countries"
        ordering = ['id']


class AdministrativeLevelOne(AdminPermissionsHistoryNameModel):
    """
    Administrative Level One (ex. in US it is State)
    """

    country = models.ForeignKey('Country', models.CASCADE, related_name='administrativelevelones', help_text='A foreign key integer value identifying the country to with this administrative level one belongs')
    abbreviation = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the usual abbreviation of this administrative level one')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_administrativelevelone"
        ordering = ['id']


class AdministrativeLevelTwo(AdminPermissionsHistoryModel):
    """
    Administrative Level Two (ex. in US it is counties)
    """

    @staticmethod
    def has_request_new_permission(request):
        return True

    name = models.CharField(max_length=128, help_text='An alphanumeric value of the name of this administrative level two')
    administrative_level_one = models.ForeignKey(
        'AdministrativeLevelOne', models.CASCADE, related_name='administrativeleveltwos', help_text='A foreign key integer value identifying the administrative level one to which this administrative level two belongs')
    points = models.TextField(blank=True, default='', help_text='An alphanumeric value of the points of this administrative level two')  # QUESTION: what is the purpose of this field?
    centroid_latitude = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True, help_text='A fixed-precision decimal number value indentifying the latitude for this administrative level two')
    centroid_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text='A fixed-precision decimal number value indentifying the longitude for this administrative level two')
    fips_code = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the FIPS code for this administrative level two')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_administrativeleveltwo"
        unique_together = ('name', 'administrative_level_one')
        ordering = ['id']


class AdministrativeLevelLocality(AdminPermissionsHistoryModel):
    """
    Table for looking up local names for adminstrative levels based on country
    """

    country = models.ForeignKey('Country', models.CASCADE, related_name='adminstrativelevellocalities', help_text='A foreign key integer value identifying the country to which this administrative level locality belongs')
    admin_level_one_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the name of the administrative level one')
    admin_level_two_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the name of the administrative level two')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_adminstrativelevellocality"
        ordering = ['id']


class LandOwnership(AdminPermissionsHistoryNameModel):
    """
    Land Ownership
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_landownership"
        ordering = ['id']


class EventLocationFlyway(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Event Locations and Flyways.
    """

    event_location = models.ForeignKey('EventLocation', models.CASCADE)
    flyway = models.ForeignKey('Flyway', models.CASCADE)

    @staticmethod
    def has_create_permission(request):
        if request and 'event_location' in request.data:
            event = EventLocation.objects.get(pk=int(request.data['event_location'])).event
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.event_location.event.id
        return determine_object_update_permission(self, request, event_id)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventlocationflyway"
        ordering = ['id']


class Flyway(AdminPermissionsHistoryNameModel):
    """
    Flyway
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_flyway"
        ordering = ['id']


######
#
#  Species
#
######


class LocationSpecies(PermissionsHistoryModel):
    """
    Location Species
    """
    #species = models.CharField(unique=True, help_text=_("unique alphanumeric identifier"))

    event_location = models.ForeignKey('EventLocation', models.CASCADE, related_name='locationspecies', help_text='A foreign key integer value identifying the event location')
    species = models.ForeignKey('Species', models.PROTECT, related_name='locationspecies', help_text='Animal species')
    population_count = models.IntegerField(null=True, help_text='An integer value indicating the population count')
    sick_count = models.IntegerField(null=True, help_text='An integer value indicating the sick count')
    dead_count = models.IntegerField(null=True, help_text='An integer value indicating the dead count')
    sick_count_estimated = models.IntegerField(null=True, help_text='An integer value indicating the estimated sick count')
    dead_count_estimated = models.IntegerField(null=True, help_text='An integer value indicating the estimated dead count')
    priority = models.IntegerField(null=True, help_text='An integer value indicating the location species priority')
    captive = models.BooleanField(default=False, help_text='A boolean value indicating if the location species was captive or not')
    age_bias = models.ForeignKey('AgeBias', models.PROTECT, null=True, related_name='locationspecies')
    sex_bias = models.ForeignKey('SexBias', models.PROTECT, null=True, related_name='locationspecies')

    @staticmethod
    def has_create_permission(request):
        if request and 'event_location' in request.data:
            event = EventLocation.objects.get(pk=int(request.data['event_location'])).event
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.event_location.event.id
        return determine_object_update_permission(self, request, event_id)

    # override the save method to calculate the parent event's affected_count
    def save(self, *args, **kwargs):
        super(LocationSpecies, self).save(*args, **kwargs)

        event = Event.objects.filter(id=self.event_location.event.id).first()

        # affected_count
        # If EventType = Morbidity/Mortality
        # then Sum(Max(estimated_dead, dead) + Max(estimated_sick, sick)) from location_species table
        # If Event Type = Surveillance then Sum(number_positive) from species_diagnosis table
        event_type_id = event.event_type.id
        if event_type_id not in [1, 2]:
            event.affected_count = None
        else:
            locations = EventLocation.objects.filter(event=event.id).values('id', 'start_date', 'end_date')
            loc_ids = [loc['id'] for loc in locations]
            loc_species = LocationSpecies.objects.filter(
                event_location_id__in=loc_ids).values(
                'id', 'dead_count_estimated', 'dead_count', 'sick_count_estimated', 'sick_count')
            if event_type_id == 1:
                affected_counts = [max(spec.get('dead_count_estimated') or 0, spec.get('dead_count') or 0)
                                   + max(spec.get('sick_count_estimated') or 0, spec.get('sick_count') or 0)
                                   for spec in loc_species]
                event.affected_count = sum(affected_counts)
            elif event_type_id == 2:
                loc_species_ids = [spec['id'] for spec in loc_species]
                species_dx_positive_counts = SpeciesDiagnosis.objects.filter(
                    location_species_id__in=loc_species_ids).values_list('positive_count', flat=True)
                # positive_counts = [dx.get('positive_count') or 0 for dx in species_dx]
                event.affected_count = sum(species_dx_positive_counts) if len(species_dx_positive_counts) == 0 else None

        event.save()

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_locationspecies"
        verbose_name_plural = "locationspecies"
        ordering = ['event_location', 'priority']


class Species(AdminPermissionsHistoryModel):
    """
    Species
    """

    @staticmethod
    def has_request_new_permission(request):
        return True

    name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the the name of this species')
    class_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the name of this species class')
    order_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the name of this species order')
    family_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the name of this species family')
    sub_family_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the name of this species sub family')
    genus_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the name of this species genus')
    species_latin_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the latin name of this species')
    subspecies_latin_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the latin name of this subspecies')
    tsn = models.IntegerField(null=True, help_text='An intger value identifying a TSN')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_species"
        verbose_name_plural = "species"
        ordering = ['id']


class AgeBias(AdminPermissionsHistoryNameModel):
    """
    Age Bias
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_agebias"
        verbose_name_plural = "agebiases"
        ordering = ['id']


class SexBias(AdminPermissionsHistoryNameModel):
    """
    Sex Bias
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_sexbias"
        verbose_name_plural = "sexbiases"
        ordering = ['id']


######
#
#  Diagnoses
#
######


class Diagnosis(AdminPermissionsHistoryNameModel):
    """
    Diagnosis
    """

    @staticmethod
    def has_request_new_permission(request):
        return True

    high_impact = models.BooleanField(default=False, help_text='A boolean value indicating if the diagnosis is high impact (reportable) or not')
    diagnosis_type = models.ForeignKey('DiagnosisType', models.PROTECT, related_name='diagnoses', help_text='A foreign key integer value identifying the diagnosis type')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_diagnosis"
        verbose_name_plural = "diagnoses"
        ordering = ['id']


class DiagnosisType(AdminPermissionsHistoryNameModel):
    """
    Diagnosis Type
    """

    color = models.CharField(max_length=128, blank=True, default='', help_text='A alphanumeric value of the color of this diagnosis type')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_diagnosistype"
        ordering = ['id']


class EventDiagnosis(PermissionsHistoryModel):
    """
    Event Diagnosis
    """

    @property
    def diagnosis_string(self):
        """Returns diagnosis name of the record, appended with word 'suspect' if record has suspect=True"""
        return str(self.diagnosis) + " suspect" if self.suspect else str(self.diagnosis)

    event = models.ForeignKey('Event', models.CASCADE, related_name='eventdiagnoses', help_text='A foreign key integer value identifying an event')
    diagnosis = models.ForeignKey('Diagnosis', models.PROTECT, related_name='eventdiagnoses', help_text='A foreign key integer value identifying a diagnosis')
    suspect = models.BooleanField(default=True, help_text='A boolean value where if "true" then the diagnosis is suspect')
    major = models.BooleanField(default=False, help_text='A boolean value indicating if the event diagnosis is major or not')
    priority = models.IntegerField(null=True, help_text='An integer value indicating the event diagnosis priority')

    @staticmethod
    def has_create_permission(request):
        if request and 'event' in request.data:
            event = Event.objects.get(pk=int(request.data['event']))
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.event.id
        return determine_object_update_permission(self, request, event_id)

    # override the save method to ensure that a Pending or Undetermined diagnosis is never suspect
    # All "Pending" and "Undetermined" must be confirmed OR some other way of coding this
    # such that we never see "Pending suspect" or "Undetermined suspect" on front end.
    def save(self, *args, **kwargs):
        if self.diagnosis.name in ['Pending', 'Undetermined']:
            self.suspect = False
        super(EventDiagnosis, self).save(*args, **kwargs)

    def __str__(self):
        return str(self.diagnosis) + " suspect" if self.suspect else str(self.diagnosis)

    class Meta:
        db_table = "whispers_eventdiagnosis"
        verbose_name_plural = "eventdiagnoses"
        unique_together = ('event', 'diagnosis')
        ordering = ['event', 'priority']


# # After an EventDiagnosis is deleted,
# # ensure there is at least one EventDiagnosis for the deleted EventDiagnosis's parent Event,
# # and if there are none left, will need to create a new Pending or Undetermined EventDiagnosis,
# # depending on the Event's complete status
# # However, if Event has been deleted, then don't attempt to create another EventDiagnosis
# @receiver(post_delete, sender=EventDiagnosis)
# def delete_event_diagnosis(sender, instance, **kwargs):
#
#     # only continue if parent Event still exists
#     event = Event.objects.filter(id=instance.event.id).first()
#     if event:
#         evt_diags = EventDiagnosis.objects.filter(event=instance.event.id)
#         if not len(evt_diags) > 0:
#             new_diagnosis_name = 'Pending' if not instance.event.complete else 'Undetermined'
#             new_diagnosis = Diagnosis.objects.filter(name=new_diagnosis_name).first()
#             # All "Pending" and "Undetermined" must be confirmed OR some other way of coding this
#             # such that we never see "Pending suspect" or "Undetermined suspect" on front end.
#             EventDiagnosis.objects.create(
#                 event=instance.event, diagnosis=new_diagnosis, suspect=False, priority=1,
#                 created_by=instance.created_by, modified_by=instance.modified_by)


class SpeciesDiagnosis(PermissionsHistoryModel):
    """
    SpeciesDiagnosis
    """

    @property
    def diagnosis_string(self):
        """Returns diagnosis name of the record, appended with word 'suspect' if record has suspect=True"""
        return str(self.diagnosis) + " suspect" if self.suspect else str(self.diagnosis)

    @property
    def cause_string(self):
        """Returns cause name of the record, appended with word 'suspect' if record has suspect=True"""
        return 'Suspect ' + str(self.cause) if self.suspect and self.cause else str(self.cause) if self.cause else ''

    location_species = models.ForeignKey('LocationSpecies', models.CASCADE, related_name='speciesdiagnoses', help_text='A foreign key integer value identifying a location species for this species diagnosis')
    diagnosis = models.ForeignKey('Diagnosis', models.PROTECT, related_name='speciesdiagnoses', help_text='A foreign key integer value identifying a diagnosis for this species diagnosis')
    cause = models.ForeignKey('DiagnosisCause', models.PROTECT, null=True, related_name='speciesdiagnoses', help_text='A foreign key integer value identifying the incidents cause for this species diagnosis')
    basis = models.ForeignKey('DiagnosisBasis', models.PROTECT, null=True, related_name='speciesdiagnoses', help_text='A foreign key integer value identifying a basis (how a species diagnosis was determined) for this species diagnosis')
    suspect = models.BooleanField(default=True, help_text='A boolean value where if "true" then the species diagnosis is suspect')
    priority = models.IntegerField(null=True, help_text='An integer value indicating the priority of this species diagnosis')
    tested_count = models.IntegerField(null=True, help_text='An integer value indicating the tested count for this species diagnosis')
    diagnosis_count = models.IntegerField(null=True, help_text='An integer value indicating the diagnosis count for this species diagnosis')
    positive_count = models.IntegerField(null=True, help_text='An integer value indicating the positive count for this species diagnosis ')
    suspect_count = models.IntegerField(null=True, help_text='An integer value indicating the suspect count for this species diagnosis')
    pooled = models.BooleanField(default=False, help_text='A boolean value indicating if the species diagnosis was pooled or not')
    organizations = models.ManyToManyField(
        'Organization', through='SpeciesDiagnosisOrganization', related_name='speciesdiagnoses', help_text='A many to many releationship of organizations based on a foreign key integer value indentifying an organization')

    @staticmethod
    def has_create_permission(request):
        if request and 'location_species' in request.data:
            event = LocationSpecies.objects.get(pk=int(request.data['location_species'])).event_location.event
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.location_species.event_location.event.id
        return determine_object_update_permission(self, request, event_id)

    # override the save method to ensure that a Pending or Undetermined diagnosis is never suspect
    # and to create real time notifications for high impact diseases
    # and to calculate the parent event's affected_count
    def save(self, *args, **kwargs):
        is_new = False if self.id else True

        # all "Pending" and "Undetermined" diagnosis must be confirmed (not suspect) = false, even if no lab OR
        # some other way of coding this such that we never see "Pending suspect" or "Undetermined suspect" on front end
        if self.diagnosis.name in ['Pending', 'Undetermined']:
            self.suspect = False

        # If diagnosis is confirmed and pooled is selected,
        # then automatically list 1 for number_positive if number_positive was zero or null.
        # If diagnosis is suspect and pooled is selected,
        # then automatically list 1 for number_suspect if number_suspect was zero or null.
        if self.suspect and self.pooled:
            if self.positive_count is None or self.positive_count == 0:
                self.positive_count = 1
            if self.suspect_count is None or self.suspect_count == 0:
                self.suspect_count = 1

        super(SpeciesDiagnosis, self).save(*args, **kwargs)

        # create real time notifications for high impact diseases
        if is_new and self.diagnosis.high_impact:
            recipients = list(User.objects.filter(role__in=[1,2]).values_list('id', flat=True))
            email_to = [settings.EMAIL_WHISPERS, settings.EMAIL_NWHC_EPI]
            msg_tmp = NotificationMessageTemplate.objects.filter(name='High Impact Diseases').first().message_template
            message = msg_tmp.format(
                species_diagnosis=self.diagnosis.name, event_id=self.location_species.event_location.event.id)
            source = self.created_by.username
            event = self.location_species.event_location.event.id
            # current_app.send_task('myapp.tasks.do_stuff', args=(1, 'two'), kwargs={'foo': 'bar'})
            # current_app.send_task('tasks.generate_notification_task',
            #                       args=(recipients, source, event, 'event', message, True))
            # generate_notification.delay(recipients, source, event, 'event', message, True)
            from whispersservices.tasks import generate_notification
            generate_notification.delay(recipients, source, event, 'event', message, True, email_to)

        event = Event.objects.filter(id=self.location_species.event_location.event.id).first()
        diagnosis = self.diagnosis

        # affected_count
        # If EventType = Morbidity/Mortality
        # then Sum(Max(estimated_dead, dead) + Max(estimated_sick, sick)) from location_species table
        # If Event Type = Surveillance then Sum(number_positive) from species_diagnosis table
        event_type_id = event.event_type.id
        if event_type_id not in [1, 2]:
            event.affected_count = None
        else:
            locations = EventLocation.objects.filter(event=event.id).values('id', 'start_date', 'end_date')
            loc_ids = [loc['id'] for loc in locations]
            loc_species = LocationSpecies.objects.filter(
                event_location_id__in=loc_ids).values(
                'id', 'dead_count_estimated', 'dead_count', 'sick_count_estimated', 'sick_count')
            if event_type_id == 1:
                affected_counts = [max(spec.get('dead_count_estimated') or 0, spec.get('dead_count') or 0)
                                   + max(spec.get('sick_count_estimated') or 0, spec.get('sick_count') or 0)
                                   for spec in loc_species]
                event.affected_count = sum(affected_counts)
            elif event_type_id == 2:
                loc_species_ids = [spec['id'] for spec in loc_species]
                species_dx_positive_counts = SpeciesDiagnosis.objects.filter(
                    location_species_id__in=loc_species_ids).values_list('positive_count', flat=True)
                positive_counts = [dx or 0 for dx in species_dx_positive_counts]
                event.affected_count = sum(positive_counts)

        event.save()

        # if any speciesdiagnosis is confirmed, then the eventdiagnosis with the same diagnosis is also confirmed
        if not self.suspect:
            matching_eventdiagnosis = EventDiagnosis.objects.filter(diagnosis=diagnosis.id, event=event.id).first()
            if matching_eventdiagnosis:
                matching_eventdiagnosis.suspect = False if matching_eventdiagnosis else True
                matching_eventdiagnosis.save()

        # conversely, if all speciesdiagnoses with the same diagnosis are un-confirmed (suspect set to True),
        # then the eventdiagnosis with the same diagnosis is also un-confirmed
        # (i.e, eventdiagnosis cannot be confirmed if no speciesdiagnoses with the same diagnosis are confirmed)
        if self.suspect:
            no_confirmed_speciesdiagnoses = True
            matching_speciesdiagnoses = SpeciesDiagnosis.objects.filter(
                diagnosis=diagnosis.id, location_species__event_location__event=event.id)
            for matching_speciesdiagnosis in matching_speciesdiagnoses:
                if not matching_speciesdiagnosis.suspect:
                    no_confirmed_speciesdiagnoses = False
            if no_confirmed_speciesdiagnoses:
                matching_eventdiagnosis = EventDiagnosis.objects.filter(diagnosis=diagnosis.id, event=event.id).first()
                if matching_eventdiagnosis:
                    matching_eventdiagnosis.suspect = True
                    matching_eventdiagnosis.save()

    # override the delete method to ensure that when all speciesdiagnoses with a particular diagnosis are deleted,
    # then eventdiagnosis of same diagnosis for this parent event needs to be deleted as well
    def delete(self, *args, **kwargs):
        event = self.location_species.event_location.event
        diagnosis = self.diagnosis
        super(SpeciesDiagnosis, self).delete(*args, **kwargs)

        same_speciesdiagnoses_diagnosis = SpeciesDiagnosis.objects.filter(
            diagnosis=diagnosis.id, location_species__event_location__event=event.id)
        if not same_speciesdiagnoses_diagnosis:
            EventDiagnosis.objects.filter(diagnosis=diagnosis.id, event=event.id).delete()

        # Ensure at least one other EventDiagnosis exists for the parent Event after any EventDiagnosis deletions above,
        # and if there are no EventDiagnoses left, create a new Pending or Undetermined EventDiagnosis,
        # depending on the parent Event's complete status
        evt_diags = EventDiagnosis.objects.filter(event=event.id)
        if not len(evt_diags) > 0:
            new_diagnosis_name = 'Pending' if not event.complete else 'Undetermined'
            new_diagnosis = Diagnosis.objects.filter(name=new_diagnosis_name).first()
            # All "Pending" and "Undetermined" must be confirmed OR some other way of coding this
            # such that we never see "Pending suspect" or "Undetermined suspect" on front end.
            EventDiagnosis.objects.create(
                event=event, diagnosis=new_diagnosis, suspect=False, priority=1,
                created_by=self.created_by, modified_by=self.modified_by)

    def __str__(self):
        return str(self.diagnosis) + " suspect" if self.suspect else str(self.diagnosis)

    class Meta:
        db_table = "whispers_speciesdiagnosis"
        verbose_name_plural = "speciesdiagnoses"
        # unique_together = ("location_species", "diagnosis")
        ordering = ['location_species', 'priority']


class SpeciesDiagnosisOrganization(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between SpeciesDiagnosis and Organizations.
    """

    species_diagnosis = models.ForeignKey('SpeciesDiagnosis', models.CASCADE)
    organization = models.ForeignKey('Organization', models.CASCADE)

    @staticmethod
    def has_create_permission(request):
        if request and 'species_diagnosis' in request.data:
            event = SpeciesDiagnosis.objects.get(
                pk=int(request.data['species_diagnosis'])).location_species.event_location.event
            return determine_create_permission(request, event)
        else:
            return False

    def has_object_update_permission(self, request):
        event_id = self.species_diagnosis.location_species.event_location.event.id
        return determine_object_update_permission(self, request, event_id)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_speciesdiagnosisorganization"
        # unique_together = ("species_diagnosis", "organization")
        ordering = ['id']


class DiagnosisBasis(AdminPermissionsHistoryNameModel):
    """
    Diagnosis Basis
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_diagnosisbasis"
        verbose_name_plural = "diagnosisbases"
        ordering = ['id']


class DiagnosisCause(AdminPermissionsHistoryNameModel):
    """
    Diagnosis Cause
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_diagnosiscause"
        ordering = ['id']


######
#
#  Service Requests
#
######


class ServiceRequest(PermissionsHistoryModel):
    """
    Service Submission Request
    """

    event = models.ForeignKey('Event', models.CASCADE, related_name='servicerequests', help_text='A foreign key integer value identifying an event')
    request_type = models.ForeignKey('ServiceRequestType', models.PROTECT, related_name='servicerequests', help_text='A foreign key integer value identifying a request type for this service submission request')
    request_response = models.ForeignKey('ServiceRequestResponse', models.PROTECT, null=True, default=4,
                                         related_name='servicerequests', help_text='A foreign key integer value identifying a response to this request')
    response_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, db_index=True,
                                    related_name='servicerequests')
    created_time = models.TimeField(auto_now_add=True, help_text='The time this service request was submitted')
    comments = GenericRelation('Comment', related_name='servicerequests', help_text='An alphanumeric value for the comment of the service submission request')

    @staticmethod
    def has_create_permission(request):
        # anyone can create
        return True

    def has_object_update_permission(self, request):
        # Only admins can update
        if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            return False
        elif request.user.role.is_superadmin or request.user.role.is_admin:
            return True
        else:
            return False

    # override the save method to create real time notifications
    def save(self, *args, **kwargs):
        is_new = False if self.id else True

        super(ServiceRequest, self).save(*args, **kwargs)

        # if this is a new service request, create a 'Service Request' notification
        if is_new:
            madison_epi = User.objects.filter(username='madisonepi').first()
            recipients = [madison_epi.id, ]
            email_to = [madison_epi.email, ]
            message = NotificationMessageTemplate.objects.filter(name='Service Request').first().message_template
            source = self.created_by.username
            event = None
            from whispersservices.tasks import generate_notification
            generate_notification.delay(recipients, source, event, '', message, True, email_to)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_servicerequest"
        ordering = ['id']


class ServiceRequestType(AdminPermissionsHistoryNameModel):
    """
    Service Submission Request Type
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_servicerequesttype"
        ordering = ['id']


class ServiceRequestResponse(AdminPermissionsHistoryNameModel):
    """
    Service Request Response
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_servicerequestresponse"
        ordering = ['id']


######
#
#  Notifications
#
######


class Notification(PermissionsHistoryModel):
    """
    Notification
    """

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, models.CASCADE, related_name='notifications', help_text='A foreign key integer value identifying the user receiving this notification')
    source = models.CharField(max_length=128, blank=True, default='', help_text='A alphanumeric value of the source of this notification')
    event = models.ForeignKey('Event', models.CASCADE, null=True, related_name='notifications', help_text='A foreign key integer value identifying an event')
    read = models.BooleanField(default=False, help_text='A boolean value indicating if this notification has been read or not')
    client_page = models.CharField(max_length=128, blank=True, default='', help_text='A alphanumeric value of the page of the client application where the topic of this notification can be addressed')
    message = models.TextField(blank=True, help_text='An alphanumeric value of the message of this notification')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_notification"


class NotificationMessageTemplate(PermissionsHistoryModel):

    name = models.CharField(max_length=128, unique=True, help_text='An alphanumeric value of the name of this notification')
    message_template = models.TextField(blank=True, help_text='An alphanumeric value of the message of this notification')
    message_variables = ArrayField(models.CharField(max_length=128), blank=True, help_text='An array of alphanumeric values of the variable names of this notification message')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_notificationmessagetemplate"


class NotificationCuePreference(PermissionsHistoryModel):
    """
    Notification Cue Preference
    """

    create_when_new = models.BooleanField(default=True, help_text='A boolean value indicating if a notification should be created when a record is new')
    create_when_modified = models.BooleanField(default=True, help_text='A boolean value indicating if a notification should be created when a record is modified')
    send_email = models.BooleanField(default=True, help_text='A boolean value indicating if a notification should be sent by email or not')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_notificationcuepreference"


# TODO: ensure that these are deactivated somehow when a user is_active values is False
class NotificationCueCustom(PermissionsHistoryModel):
    """
    Notification Cue Custom
    """

    notification_cue_preference = models.OneToOneField('NotificationCuePreference', models.CASCADE, related_name='notificationcuecustoms', help_text='A foreign key integer value identifying a notificationcuepreference')
    event = JSONField(blank=True, help_text='A JSON object containing the event ID data')
    event_affected_count = JSONField(blank=True, help_text='A JSON object containing the event affected_count data')
    event_location_land_ownership = JSONField(blank=True, help_text='A JSON object containing the eventlocation land_ownership ID data')
    event_location_administrative_level_one = JSONField(blank=True, help_text='A JSON object containing the eventlocation administrativelevelone ID data')
    species = JSONField(blank=True, help_text='A JSON object containing the species ID data')
    species_diagnosis_diagnosis = JSONField(blank=True, help_text='A JSON object containing the speciesdiagnosis diagnosis ID data')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_notificationcuecustom"


# TODO: ensure that these are deactivated somehow when a user is_active value is False
class NotificationCueStandard(PermissionsHistoryModel):
    """
    Notification Cue Standard
    """

    notification_cue_preference = models.OneToOneField('NotificationCuePreference', models.CASCADE, related_name='notificationcuestandards', help_text='A foreign key integer value identifying a notificationcuepreference')
    standard_type = models.ForeignKey('NotificationCueStandardType', models.CASCADE, related_name='notificationcuestandards', help_text='A foreign key integer value identifying a notificationcuestandardtype')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_notificationcuestandard"


class NotificationCueStandardType(AdminPermissionsHistoryNameModel):
    """
    Notification Cue Standard Types
    """

    def __str__(self):
        return str(self.name)

    class Meta:
        db_table = "whispers_notificationcuestandardtype"


######
#
#  Misc
#
######


# TODO: revisit read permissions on comment
class Comment(PermissionsHistoryModel):
    """
    Comment
    """

    comment = models.TextField(blank=True, help_text='An alphanumeric value of the comment of this object')
    comment_type = models.ForeignKey('CommentType', models.PROTECT, related_name='comments', help_text='A foreign key integer value identifying the comment time of this comment')

    # Below the mandatory fields for generic relation
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, help_text='A foreign key integer value identifying the content type for this comment')
    object_id = models.PositiveIntegerField(help_text='A positive integer value identifying an object')
    content_object = GenericForeignKey()

    @staticmethod
    def determine_comment_permission(request):
        # For models that are children of events (e.g., eventlocation, locationspecies, speciesdiagnosis),
        # only admins or the creator or a manager/admin member of the creator's org or a write_collaborator can create
        if (not request or not request.user or not request.user.is_authenticated
                or request.user.role.is_public or request.user.role.is_affiliate):
            return False
        elif request.user.role.is_superadmin or request.user.role.is_admin:
            return True
        else:
            model_name = None
            if 'content_type' in request.data:
                model_name = request.data['content_type'].model
            elif 'new_content_type' in request.data:
                model_name = request.data['new_content_type']
            if model_name:
                if model_name not in ['servicerequest', 'event', 'eventlocation', 'eventeventgroup']:
                    return False
                if model_name == 'servicerequest':
                    return True
                if model_name in ['event', 'eventlocation', 'eventeventgroup']:
                    event = None
                    if model_name == 'event':
                        event = Event.objects.get(pk=int(request.data['object_id']))
                    elif model_name == 'eventlocation':
                        event = EventLocation.objects.get(pk=int(request.data['object_id'])).event
                    elif model_name == 'eventeventgroup':
                        event = EventEventGroup.objects.get(pk=int(request.data['object_id'])).event
                    if event:
                        if (request.user.id == event.created_by.id
                                or (request.user.organization.id == event.created_by.organization.id
                                    and (request.user.role.is_partneradmin or request.user.role.is_partnermanager))):
                            return True
                        else:
                            write_collaborators = list(
                                User.objects.filter(writeevents__in=[event.id]).values_list('id', flat=True))
                            return request.user.id in write_collaborators
                    else:
                        return False
                else:
                    return False
            else:
                return False

    # @classmethod
    # def has_read_permission(cls, request):
    #     return cls.determine_comment_permission(request)
    #
    # def has_object_read_permission(self, request):
    #     return self.determine_comment_permission(request)

    @classmethod
    def has_create_permission(cls, request):
        return cls.determine_comment_permission(request)

    def has_object_update_permission(self, request):
        # Only admins or the creator or a manager/admin member of the creator's org or a write_collaborator can update
        return determine_object_update_permission(self, request, None)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_comment"
        ordering = ['id']


class CommentType(AdminPermissionsHistoryNameModel):
    """
    Comment Type
    """

    def __str__(self):
        return str(self.name)

    class Meta:
        db_table = "whispers_commenttype"
        ordering = ['id']


class Artifact(PermissionsHistoryModel):  # TODO: implement file fields
    """
    Artifact
    """

    filename = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the filename of this artifact')
    keywords = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the keywords of this artifact')

    @staticmethod
    def has_create_permission(request):
        # anyone with role of Partner or above can create
        return partner_create_permission(request)

    def has_object_update_permission(self, request):
        # Only admins or the creator or a manager/admin member of the creator's org or a write_collaborator can update
        return determine_object_update_permission(self, request, None)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_artifact"
        ordering = ['id']


######
#
#  Users
#
######


# TODO: revisit settings; role should default to Public, org should default to Public (doesn't exist yet)
class User(AbstractUser):
    """
    Extends the default User model.
    Default fields of the User model: username, first_name, last_name, email, password, groups, user_permissions,
       is_staff, is_active, is_superuser, last_login, date_joined
    """

    @staticmethod
    def has_request_new_permission(request):
        return True

    @staticmethod
    def has_read_permission(request):
        # Only admins or the creator or an admin member of the creator's organization can 'read' (list)
        # but this cannot be controlled here in this model; it can only be controlled in the views using this model
        return True

    def has_object_read_permission(self, request):
        # Only admins or the creator or an admin member of the creator's organization can 'read' (retrieve)
        if not request.user.is_authenticated:
            return False
        else:
            return (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.id
                    or (request.user.organization.id == self.organization.id and request.user.role.is_partneradmin))

    @staticmethod
    def has_write_permission(request):
        # # Prevent unsafe methods from appearing in the schema view/docs
        # return False
        # This must be true otherwise no one, not even superadmins or owners, can write objects (update or destroy)
        return True

    @staticmethod
    def has_create_permission(request):
        # Anyone can create a new user
        return True

    def has_object_update_permission(self, request):
        # Only admins or the creator or an admin member of the creator's organization can update
        if not request or not request.user or not request.user.is_authenticated:
            return False
        else:
            return (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.id
                    or (request.user.organization.id == self.organization.id and request.user.role.is_partneradmin))

    def has_object_destroy_permission(self, request):
        # Only superadmins or the creator or an admin member of the creator's organization can delete
        if not request or not request.user or not request.user.is_authenticated:
            return False
        else:
            return (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.id
                    or (request.user.organization.id == self.organization.id and request.user.role.is_partneradmin))

    role = models.ForeignKey('Role', models.PROTECT, null=True, related_name='users', help_text='A foreign key integer value identifying a role assigned to a user')
    organization = models.ForeignKey('Organization', models.PROTECT, null=True, related_name='users', help_text='A foreign key integer value identifying an organization assigned to a user')
    circles = models.ManyToManyField(
        'Circle', through='CircleUser', through_fields=('user', 'circle'), related_name='users', help_text='A many to many releationship of circles based on a foreign key integer value indentifying a circle')
    active_key = models.TextField(blank=True, default='', help_text='An alphanumeric value of the active key for this user')
    user_status = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the status for this user')

    history = HistoricalRecords()

    def __str__(self):
        return self.username

    class Meta:
        db_table = "whispers_user"
        ordering = ['id']


class Role(AdminPermissionsHistoryNameModel):
    """
    User Role
    """

    @property
    def is_superadmin(self):
        return True if self.name == 'SuperAdmin' else False

    @property
    def is_admin(self):
        return True if self.name == 'Admin' else False

    @property
    def is_partneradmin(self):
        return True if self.name == 'PartnerAdmin' else False

    @property
    def is_partnermanager(self):
        return True if self.name == 'PartnerManager' else False

    @property
    def is_partner(self):
        return True if self.name == 'Partner' else False

    @property
    def is_affiliate(self):
        return True if self.name == 'Affiliate' else False

    @property
    def is_public(self):
        return True if self.name == 'Public' else False

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_role"
        ordering = ['id']


class RoleChangeRequest(PermissionsHistoryModel):
    """
    Service Submission Request
    """

    requestor = models.ForeignKey(settings.AUTH_USER_MODEL, models.CASCADE, related_name='rolechangerequests_requestor', help_text='A foreign key integer value identifying a user')
    role_requested = models.ForeignKey('Role', models.PROTECT, related_name='rolechangerequests', help_text='A foreign key integer value identifying a role requested for this role change request')
    request_response = models.ForeignKey('RoleChangeRequestResponse', models.PROTECT, null=True, default=3,
                                         related_name='rolechangerequests', help_text='A foreign key integer value identifying a response to this request')
    response_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, db_index=True,
                                    related_name='rolechangerequests_responder')
    comments = GenericRelation('Comment', related_name='rolechangerequests', help_text='An alphanumeric value for the comment of the role change request')

    @staticmethod
    def has_create_permission(request):
        # anyone can create
        return True

    def has_object_update_permission(self, request):
        # Only admins can update
        if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            return False
        elif request.user.role.is_superadmin or request.user.role.is_admin:
            return True
        else:
            return False

    # override the save method to create real time notifications
    def save(self, *args, **kwargs):
        is_new = False if self.id else True

        super(RoleChangeRequest, self).save(*args, **kwargs)

        # if this is a new request, create a 'Role Change' notification
        if is_new:
            recipients = list(User.objects.filter(
                Q(role__in=[1, 2]) | Q(role=3, organization=self.requestor.organization.id)
            ).values_list('id', flat=True))
            org_admin_emails = list(User.objects.filter(
                role=3, organization=self.requestor.organization.id).values_list('email', flat=True))
            email_to = [settings.EMAIL_WHISPERS, ] + org_admin_emails
            msg_tmp = NotificationMessageTemplate.objects.filter(name='Role Change').first().message_template
            message = msg_tmp.format(
                first_name=self.requestor.first_name, last_name=self.requestor.last_name,
                username=self.requestor.username, role=self.role_requested.name)
            source = self.created_by.username
            event = None
            from whispersservices.tasks import generate_notification
            generate_notification.delay(recipients, source, event, 'userdashboard', message, True, email_to)
        else:
            # else this is an update to an existing request, so create a 'Role Change Response' notification
            recipients = list(User.objects.filter(role__in=[1, 2]).values_list('id', flat=True)) + [self.requestor.id, ]
            email_to = [settings.EMAIL_WHISPERS, self.requestor.email]
            msg_tmp = NotificationMessageTemplate.objects.filter(name='Role Change Response').first().message_template
            message = msg_tmp.format(
                role=self.role_requested.name, organization=self.requestor.organization.name)
            source = self.modified_by.username
            event = None
            from whispersservices.tasks import generate_notification
            generate_notification.delay(recipients, source, event, 'userdashboard', message, True, email_to)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_rolechangerequest"
        ordering = ['id']


class RoleChangeRequestResponse(AdminPermissionsHistoryNameModel):
    """
    Role Change Request Response
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_rolechangerequestresponse"
        ordering = ['id']


class EventReadUser(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Events and Read-Only Users.
    """

    event = models.ForeignKey('Event', models.CASCADE, related_name='eventreadusers')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.CASCADE, related_name='eventreadusers')

    @staticmethod
    def has_create_permission(request):
        event = Event.objects.get(pk=int(request.data['event']))
        # only admins or the event creator or a manager/admin member of the creator's org can create
        if (not request or not request.user or not request.user.is_authenticated
                or request.user.role.is_public or request.user.role.is_affiliate):
            return False
        elif request.user.role.is_superadmin or request.user.role.is_admin:
            return True
        else:
            if (request.user.id == event.created_by.id
                    or (request.user.organization.id == event.created_by.organization.id
                        and (request.user.role.is_partneradmin or request.user.role.is_partnermanager))):
                return True
            else:
                return False

    def has_object_update_permission(self, request):
        # Only admins or the creator or a manager/admin member of the creator's org can update
        if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            return False
        elif (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.created_by.id
              or (request.user.organization.id == self.created_by.organization.id
                  and (request.user.role.is_partneradmin or request.user.role.is_partnermanager))):
            return True
        else:
            return False

    # override the save method to create real time notifications
    def save(self, *args, **kwargs):
        is_new = False if self.id else True

        super(EventReadUser, self).save(*args, **kwargs)

        # if this is a new collaborator user, create a 'Collaborator Added' notification
        if is_new:
            recipients = [self.user.id, ]
            email_to = [self.user.email, ]
            event = self.event.id
            msg_tmp = NotificationMessageTemplate.objects.filter(name='Collaborator Added').first().message_template
            message = msg_tmp.format(collaborator_type="Read", event_id=event)
            source = self.created_by.username
            from whispersservices.tasks import generate_notification
            generate_notification.delay(recipients, source, event, 'event', message, True, email_to)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventreaduser"
        ordering = ['id']


class EventWriteUser(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Events and Read+Write Users.
    """

    event = models.ForeignKey('Event', models.CASCADE, related_name='eventwriteusers')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.CASCADE, related_name='eventwriteusers')

    @staticmethod
    def has_create_permission(request):
        event = Event.objects.get(pk=int(request.data['event']))
        # only admins or the event creator or a manager/admin member of the creator's org can create
        if (not request or not request.user or not request.user.is_authenticated
                or request.user.role.is_public or request.user.role.is_affiliate):
            return False
        elif request.user.role.is_superadmin or request.user.role.is_admin:
            return True
        else:
            if (request.user.id == event.created_by.id
                    or (request.user.organization.id == event.created_by.organization.id
                        and (request.user.role.is_partneradmin or request.user.role.is_partnermanager))):
                return True
            else:
                return False

    def has_object_update_permission(self, request):
        # Only admins or the creator or a manager/admin member of the creator's org can update
        if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            return False
        elif (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.created_by.id
              or (request.user.organization.id == self.created_by.organization.id
                  and (request.user.role.is_partneradmin or request.user.role.is_partnermanager))):
            return True
        else:
            return False

    # override the save method to create real time notifications
    def save(self, *args, **kwargs):
        is_new = False if self.id else True

        super(EventWriteUser, self).save(*args, **kwargs)

        # if this is a new collaborator user, create a 'Collaborator Added' notification
        if is_new:
            recipients = [self.user.id, ]
            email_to = [self.user.email, ]
            event = self.event.id
            msg_tmp = NotificationMessageTemplate.objects.filter(name='Collaborator Added').first().message_template
            message = msg_tmp.format(collaborator_type="Write", event_id=event)
            source = self.created_by.username
            from whispersservices.tasks import generate_notification
            generate_notification.delay(recipients, source, event, 'event', message, True, email_to)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventwriteuser"
        ordering = ['id']


class Circle(PermissionsHistoryModel):
    """
    Circle of Trust
    """

    name = models.CharField(max_length=128, unique=True, help_text='An alphanumeric value of the name of this circle')
    description = models.TextField(blank=True, help_text='An alphanumeric value of the description of this circle')

    @staticmethod
    def has_create_permission(request):
        # anyone with role of Partner or above can create
        return partner_create_permission(request)

    def has_object_update_permission(self, request):
        # Only admins or the creator or the creator's org admin can update
        if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            return False
        elif (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.created_by.id
              or (request.user.organization.id == self.created_by.organization.id
                  and request.user.role.is_partneradmin)):
            return True
        else:
            return False

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_circle"
        ordering = ['id']


class CircleUser(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Circles and Users.
    """

    circle = models.ForeignKey('Circle', models.CASCADE, help_text='A foreign key integer value identifying a circle')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.CASCADE, help_text='A foreign key integer value identifying a circle user')

    @staticmethod
    def has_create_permission(request):
        # anyone with role of Partner or above can create
        return partner_create_permission(request)

    def has_object_update_permission(self, request):
        # Only admins or the creator or the creator's org admin can update
        if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            return False
        elif (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.created_by.id
              or (request.user.organization.id == self.created_by.organization.id
                  and request.user.role.is_partneradmin)):
            return True
        else:
            return False

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_circleuser"
        ordering = ['id']


class Organization(AdminPermissionsHistoryNameModel):
    """
    Organization
    """

    @staticmethod
    def has_request_new_permission(request):
        return True

    private_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the private name of this organization')
    address_one = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the address one of this organization')
    address_two = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the address two of this organization')
    city = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the city of this organization')
    postal_code = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the postal code of this organization')
    administrative_level_one = models.ForeignKey(
        'AdministrativeLevelOne', models.PROTECT, null=True, related_name='organizations', help_text='A foreign key integer value identifying the administrative level one to which this organization belongs')
    country = models.ForeignKey('Country', models.PROTECT, null=True, related_name='organizations', help_text='A foreign key integer value identifying the country to which this organization belongs')
    phone = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the phone number of this organization')
    parent_organization = models.ForeignKey('self', models.CASCADE, null=True, related_name='organizations')
    do_not_publish = models.BooleanField(default=False, help_text='A boolean value indicating if an organization is supposed to be published or not')
    laboratory = models.BooleanField(default=False, help_text='A boolean value indicating if an organization has a laboratory or not')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_organization"
        ordering = ['id']


class Contact(PermissionsHistoryModel):
    """
    Contact
    """

    @property
    def owner_organization(self):
        """Returns the organization ID of the record owner ('created_by')"""
        return self.created_by.organization.id

    first_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the first name of this contact')
    last_name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the last name of this contact')
    email = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the email of this contact')
    # email = models.CharField(max_length=128, null=True, blank=True, default=None, unique=True)  # COMMENT: this can only be applied after the cooperator fixes their duplicate records
    phone = models.TextField(blank=True, default='', help_text='An alphanumeric value of the phone of this contact')
    affiliation = models.TextField(blank=True, default='', help_text='An alphanumeric value of the first name of this contact')
    title = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the title of this contact')
    position = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the position of this contact')
    # contact_type = models.ForeignKey('ContactType', models.PROTECT, related_name='contacts')  # COMMENT: this related table is not shown in the ERD
    organization = models.ForeignKey('Organization', models.PROTECT, related_name='contacts', null=True, help_text='A foreign key integer value identifying the organization to which this contact belongs to')

    @staticmethod
    def has_create_permission(request):
        # anyone with role of Partner or above can create
        return partner_create_permission(request)

    def has_object_update_permission(self, request):
        # Only admins or the creator or the creator's org admin can update
        if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            return False
        elif (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.created_by.id
              or (request.user.organization.id == self.created_by.organization.id
                  and request.user.role.is_partneradmin)):
            return True
        else:
            return False

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_contact"
        ordering = ['id']


class ContactType(AdminPermissionsHistoryModel):
    """
    Contact Type
    """

    name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the name of this contact type')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_contacttype"
        ordering = ['id']


class Search(PermissionsHistoryModel):
    """
    Searches
    """

    name = models.CharField(max_length=128, blank=True, default='', help_text='An alphanumeric value of the name of this search')
    data = JSONField(blank=True, help_text='A JSON object containing the search data')
    count = models.IntegerField(default=0, help_text='An integer value indentifying the count of searches')

    @staticmethod
    def has_create_permission(request):
        # anyone with role of Partner or above can create
        return partner_create_permission(request)

    def has_object_update_permission(self, request):
        # Only admins or the creator or the creator's org admin can update
        if not request or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            return False
        elif (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.created_by.id
              or (request.user.organization.id == self.created_by.organization.id
                  and request.user.role.is_partneradmin)):
            return True
        else:
            return False

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_search"
        verbose_name_plural = "searches"
        ordering = ['id']


class FlatEventDetails(models.Model):
    event_id = models.IntegerField()
    created_by = models.IntegerField()
    event_reference = models.CharField(max_length=128)
    event_type = models.CharField(max_length=128)
    complete = models.CharField(max_length=128)
    organization = models.CharField(max_length=512)
    start_date = models.DateField()
    end_date = models.DateField()
    affected_count = models.IntegerField()
    event_diagnosis = models.CharField(max_length=512)
    location_id = models.IntegerField()
    location_priority = models.IntegerField()
    county = models.CharField(max_length=128)
    state = models.CharField(max_length=128)
    country = models.CharField(max_length=128)
    location_start = models.DateField()
    location_end = models.DateField()
    location_species_id = models.IntegerField()
    species_priority = models.IntegerField()
    species_name = models.CharField(max_length=128)
    population = models.IntegerField()
    sick = models.IntegerField()
    dead = models.IntegerField()
    estimated_sick = models.IntegerField()
    estimated_dead = models.IntegerField()
    captive = models.CharField(max_length=128)
    age_bias = models.CharField(max_length=128)
    sex_bias = models.CharField(max_length=128)
    species_diagnosis_id = models.IntegerField()
    species_diagnosis_priority = models.IntegerField()
    speciesdx = models.CharField(max_length=128)
    causal = models.CharField(max_length=128)
    suspect = models.BooleanField()
    number_tested = models.IntegerField()
    number_positive = models.IntegerField()
    lab = models.CharField(max_length=512)
    row_num = models.IntegerField(primary_key=True)

    def __str__(self):
        return str(self.row_num)

    class Meta:
        db_table = "flat_event_details"
        managed = False
