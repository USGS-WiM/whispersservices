from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from datetime import date
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField
from django.conf import settings
from simple_history.models import HistoricalRecords


# Default fields of the core User model: username, first_name, last_name, email, password, groups, user_permissions,
# is_staff, is_active, is_superuser, last_login, date_joined
# For more information, see: https://docs.djangoproject.com/en/2.0/ref/contrib/auth/#user


######
#
#  Abstract Base Classes
#
######


class HistoryModel(models.Model):
    """
    An abstract base class model to track creation, modification, and data change history.
    """

    created_date = models.DateField(default=date.today, null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, db_index=True,
                                   related_name='%(class)s_creator')
    modified_date = models.DateField(auto_now=True, null=True, blank=True)
    modified_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, db_index=True,
                                    related_name='%(class)s_modifier')
    history = HistoricalRecords(inherit=True)

    class Meta:
        abstract = True
        default_permissions = ('add', 'change', 'delete', 'view')


class HistoryNameModel(HistoryModel):
    """
    An abstract base class model for the common name field.
    """

    name = models.CharField(max_length=128, unique=True)

    class Meta:
        abstract = True


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
        # Currently this list is 'SuperAdmin', 'Admin', 'PartnerAdmin', 'PartnerManager', 'Partner'
        # (which only excludes 'Affiliate' and 'Public', but could possibly change... explicit is better than implicit)
        if not request.user.is_authenticated:
            return False
        else:
            return (request.user.role.is_superadmin or request.user.role.is_admin or request.user.role.is_partneradmin
                    or request.user.role.is_partnermanager or request.user.role.is_partner)

    def has_object_update_permission(self, request):
        # Only admins or the creator or a manager/admin member of the creator's organization can update
        if not request.user.is_authenticated:
            return False
        else:
            return (request.user.role.is_superadmin or request.user.role.is_admin
                    or request.user.id == self.created_by.id
                    or (request.user.organization.id == self.created_by.organization.id
                        and (request.user.role.is_partneradmin or request.user.role.is_partnermanager)))

    def has_object_destroy_permission(self, request):
        # Only superadmins or the creator or a manager/admin member of the creator's organization can delete
        if not request.user.is_authenticated:
            return False
        else:
            return (request.user.role.is_superadmin or request.user.role.is_admin
                    or request.user.id == self.created_by.id
                    or (request.user.organization.id == self.created_by.organization.id
                        and (request.user.role.is_partneradmin or request.user.role.is_partnermanager)))

    class Meta:
        abstract = True


class PermissionsHistoryNameModel(PermissionsHistoryModel):
    """
    An abstract base class model for common permissions with the common name field.
    """

    name = models.CharField(max_length=128, unique=True)

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
        if not request.user.is_authenticated:
            return False
        else:
            return request.user.role.is_superadmin or request.user.role.is_admin

    def has_object_write_permission(self, request):
        # Only superadmins or admins can write (create, update, delete)
        if not request.user.is_authenticated:
            return False
        else:
            return request.user.role.is_superadmin or request.user.role.is_admin

    class Meta:
        abstract = True


class AdminPermissionsHistoryNameModel(AdminPermissionsHistoryModel):
    """
    An abstract base class model for administrator-only permissions with the common name field.
    """

    name = models.CharField(max_length=128, unique=True)

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

    event_type = models.ForeignKey('EventType', models.PROTECT, related_name='events')
    event_reference = models.CharField(max_length=128, blank=True, default='')
    complete = models.BooleanField(default=False)
    start_date = models.DateField(null=True, blank=True, db_index=True)
    end_date = models.DateField(null=True, blank=True, db_index=True)
    affected_count = models.IntegerField(null=True, db_index=True)
    staff = models.ForeignKey('Staff', models.PROTECT, null=True, related_name='events')
    event_status = models.ForeignKey('EventStatus', models.PROTECT, null=True, related_name='events', default=1)
    legal_status = models.ForeignKey('LegalStatus', models.PROTECT, null=True, related_name='events', default=1)
    legal_number = models.CharField(max_length=128, blank=True, default='')
    quality_check = models.DateField(null=True)
    public = models.BooleanField(default=True)
    circle_read = models.ForeignKey('Circle', models.PROTECT, null=True, related_name='readevents')
    circle_write = models.ForeignKey('Circle', models.PROTECT, null=True, related_name='writeevents')
    eventgroups = models.ManyToManyField('EventGroup', through='EventEventGroup', related_name='events')
    organizations = models.ManyToManyField('Organization', through='EventOrganization', related_name='events')
    contacts = models.ManyToManyField('Contact', through='EventContact', related_name='event')
    comments = GenericRelation('Comment', related_name='events')

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

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_event"
        ordering = ['id']
        # TODO: 'unique together' fields
        # The event record must be uniquely identified by the submission agency, event date, and location.


class EventEventGroup(AdminPermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Events and Super Events.
    """

    event = models.ForeignKey('Event', models.CASCADE)
    eventgroup = models.ForeignKey('EventGroup', models.CASCADE)

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

    category = models.ForeignKey('EventGroupCategory', models.CASCADE)
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

    first_name = models.CharField(max_length=128)
    last_name = models.CharField(max_length=128)
    role = models.ForeignKey('Role', models.PROTECT, related_name='staff')
    active = models.BooleanField(default=False)

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

    event = models.ForeignKey('Event', models.CASCADE, related_name='eventabstracts')
    text = models.TextField(blank=True)
    lab_id = models.IntegerField(null=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventabstract"
        ordering = ['id']


class EventCase(PermissionsHistoryModel):
    """
    Event Case
    """

    event = models.ForeignKey('Event', models.CASCADE, related_name='eventcases')
    case = models.CharField(max_length=6, blank=True, default='')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventcase"
        ordering = ['id']


class EventLabsite(PermissionsHistoryModel):
    """
    Event Labsite
    """

    event = models.ForeignKey('Event', models.CASCADE, related_name='eventlabsites')
    lab_id = models.IntegerField(null=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventlabsite"
        ordering = ['id']


class EventOrganization(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Events and Organizations.
    """

    event = models.ForeignKey('Event', models.CASCADE)
    organization = models.ForeignKey('Organization', models.CASCADE)
    priority = models.IntegerField(null=True)

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

    event = models.ForeignKey('Event', models.CASCADE)
    contact = models.ForeignKey('Contact', models.CASCADE)

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

    name = models.CharField(max_length=128, blank=True, default='')
    event = models.ForeignKey('Event', models.CASCADE, related_name='eventlocations')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    country = models.ForeignKey('Country', models.PROTECT, related_name='eventlocations')
    administrative_level_one = models.ForeignKey(
        'AdministrativeLevelOne', models.PROTECT, related_name='eventlocations')
    administrative_level_two = models.ForeignKey(
        'AdministrativeLevelTwo', models.PROTECT, null=True, related_name='eventlocations')
    county_multiple = models.BooleanField(default=False)
    county_unknown = models.BooleanField(default=False)
    latitude = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    priority = models.IntegerField(null=True)
    land_ownership = models.ForeignKey('LandOwnership', models.PROTECT, null=True, related_name='eventlocations')
    contacts = models.ManyToManyField('Contact', through='EventLocationContact', related_name='eventlocations')
    flyways = models.ManyToManyField('Flyway', through='EventLocationFlyway', related_name='eventlocations')
    gnis_name = models.CharField(max_length=256, blank=True, default='')
    gnis_id = models.CharField(max_length=256, blank=True, db_index=True, default='')
    comments = GenericRelation('Comment', related_name='eventlocations')

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

    event_location = models.ForeignKey('EventLocation', models.CASCADE)
    contact = models.ForeignKey('Contact', models.CASCADE)
    contact_type = models.ForeignKey('ContactType', models.PROTECT, null=True, related_name='eventlocationcontacts')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventlocationcontact"
        ordering = ['id']


class Country(AdminPermissionsHistoryNameModel):
    """
    Country
    """

    abbreviation = models.CharField(max_length=128, blank=True, default='')
    calling_code = models.IntegerField(null=True)

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

    country = models.ForeignKey('Country', models.CASCADE, related_name='administrativelevelones')
    abbreviation = models.CharField(max_length=128, blank=True, default='')

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

    name = models.CharField(max_length=128)
    administrative_level_one = models.ForeignKey(
        'AdministrativeLevelOne', models.CASCADE, related_name='administrativeleveltwos')
    points = models.TextField(blank=True, default='')  # QUESTION: what is the purpose of this field?
    centroid_latitude = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    centroid_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    fips_code = models.CharField(max_length=128, blank=True, default='')

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

    country = models.ForeignKey('Country', models.CASCADE, related_name='country')
    admin_level_one_name = models.CharField(max_length=128, blank=True, default='')
    admin_level_two_name = models.CharField(max_length=128, blank=True, default='')

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

    event_location = models.ForeignKey('EventLocation', models.CASCADE, related_name='locationspecies')
    species = models.ForeignKey('Species', models.PROTECT, related_name='locationspecies')
    population_count = models.IntegerField(null=True)
    sick_count = models.IntegerField(null=True)
    dead_count = models.IntegerField(null=True)
    sick_count_estimated = models.IntegerField(null=True)
    dead_count_estimated = models.IntegerField(null=True)
    priority = models.IntegerField(null=True)
    captive = models.BooleanField(default=False)
    age_bias = models.ForeignKey('AgeBias', models.PROTECT, null=True, related_name='locationspecies')
    sex_bias = models.ForeignKey('SexBias', models.PROTECT, null=True, related_name='locationspecies')

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

    name = models.CharField(max_length=128, blank=True, default='')
    class_name = models.CharField(max_length=128, blank=True, default='')
    order_name = models.CharField(max_length=128, blank=True, default='')
    family_name = models.CharField(max_length=128, blank=True, default='')
    sub_family_name = models.CharField(max_length=128, blank=True, default='')
    genus_name = models.CharField(max_length=128, blank=True, default='')
    species_latin_name = models.CharField(max_length=128, blank=True, default='')
    subspecies_latin_name = models.CharField(max_length=128, blank=True, default='')
    tsn = models.IntegerField(null=True)

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

    diagnosis_type = models.ForeignKey('DiagnosisType', models.PROTECT, related_name='diagnoses')

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

    color = models.CharField(max_length=128, blank=True, default='')

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

    event = models.ForeignKey('Event', models.CASCADE, related_name='eventdiagnoses')
    diagnosis = models.ForeignKey('Diagnosis', models.PROTECT, related_name='eventdiagnoses')
    suspect = models.BooleanField(default=True)
    major = models.BooleanField(default=False)
    priority = models.IntegerField(null=True)

    def __str__(self):
        return str(self.diagnosis) + " suspect" if self.suspect else str(self.diagnosis)

    class Meta:
        db_table = "whispers_eventdiagnosis"
        verbose_name_plural = "eventdiagnoses"
        unique_together = ('event', 'diagnosis')
        ordering = ['event', 'priority']


# After an EventDiagnosis is deleted,
# ensure there is at least one EventDiagnosis for the deleted EventDiagnosis's parent Event,
# and if there are none left, will need to create a new Pending or Undetermined EventDiagnosis,
# depending on the Event's complete status
# However, if Event has been deleted, then don't attempt to create another EventDiagnosis
@receiver(post_delete, sender=EventDiagnosis)
def delete_event_diagnosis(sender, instance, **kwargs):

    # only continue if parent Event still exists
    if not instance.event.DoesNotExist:
        if not EventDiagnosis.objects.filter(event=instance.event.id):
            new_diagnosis_name = 'Pending' if not instance.event.complete else 'Undetermined'
            new_diagnosis = Diagnosis.objects.filter(name=new_diagnosis_name).first()
            # All "Pending" and "Undetermined" must be confirmed OR some other way of coding this
            # such that we never see "Pending suspect" or "Undetermined suspect" on front end.
            EventDiagnosis.objects.create(
                event=instance.event, diagnosis=new_diagnosis, suspect=False, priority=1,
                created_by=instance.created_by, modified_by=instance.modified_by)


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

    location_species = models.ForeignKey('LocationSpecies', models.CASCADE, related_name='speciesdiagnoses')
    diagnosis = models.ForeignKey('Diagnosis', models.PROTECT, related_name='speciesdiagnoses')
    cause = models.ForeignKey('DiagnosisCause', models.PROTECT, null=True, related_name='speciesdiagnoses')
    basis = models.ForeignKey('DiagnosisBasis', models.PROTECT, null=True, related_name='speciesdiagnoses')
    suspect = models.BooleanField(default=True)
    priority = models.IntegerField(null=True)
    tested_count = models.IntegerField(null=True)
    diagnosis_count = models.IntegerField(null=True)
    positive_count = models.IntegerField(null=True)
    suspect_count = models.IntegerField(null=True)
    pooled = models.BooleanField(default=False)
    organizations = models.ManyToManyField(
        'Organization', through='SpeciesDiagnosisOrganization', related_name='speciesdiagnoses')

    # override the save method to calculate the parent event's affected_count
    def save(self, *args, **kwargs):

        # If diagnosis is confirmed and pooled is selected,
        # then automatically list 1 for number_positive if number_positive was zero or null.
        # If diagnosis is suspect and pooled is selected,
        # then automatically list 1 for number_suspect if number_suspect was zero or null.
        if not self.suspect and self.pooled:
            if self.positive_count is None or self.positive_count == 0:
                self.positive_count = 1
            if self.suspect_count is None or self.suspect_count == 0:
                self.suspect_count = 1

        super(SpeciesDiagnosis, self).save(*args, **kwargs)

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

    # override the delete method to ensure that wen all speciesdiagnoses with a particular diagnosis are deleted,
    # then eventdiagnosis of same diagnosis for this parent event needs to be deleted as well
    def delete(self, *args, **kwargs):
        event = self.location_species.event_location.event
        diagnosis = self.diagnosis
        super(SpeciesDiagnosis, self).delete(*args, **kwargs)

        same_speciesdiagnoses_diagnosis = SpeciesDiagnosis.objects.filter(
            diagnosis=diagnosis.id, location_species__event_location__event=event.id)
        if not same_speciesdiagnoses_diagnosis:
            EventDiagnosis.objects.filter(diagnosis=diagnosis.id, event=event.id).delete()

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

    event = models.ForeignKey('Event', models.CASCADE, related_name='servicerequests')
    request_type = models.ForeignKey('ServiceRequestType', models.PROTECT, related_name='servicerequests')
    request_response = models.ForeignKey('ServiceRequestResponse', models.PROTECT, null=True,
                                         related_name='servicerequests')
    response_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, db_index=True,
                                    related_name='servicerequests_responder')
    created_time = models.TimeField(auto_now_add=True)
    comments = GenericRelation('Comment', related_name='servicerequests')

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
#  Misc
#
######


class Comment(PermissionsHistoryModel):
    """
    Comment
    """

    comment = models.TextField(blank=True)
    comment_type = models.ForeignKey('CommentType', models.PROTECT, related_name='comments')

    # Below the mandatory fields for generic relation
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey()

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

    filename = models.CharField(max_length=128, blank=True, default='')
    keywords = models.CharField(max_length=128, blank=True, default='')

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
        # Anyone can 'write'
        # (note that update and destroy are handled explicitly below, so 'write' now only pertains to create)
        return True

    def has_object_update_permission(self, request):
        # Only admins or the creator or an admin member of the creator's organization can update
        if not request.user.is_authenticated:
            return False
        else:
            return (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.id
                    or (request.user.organization.id == self.organization.id and request.user.role.is_partneradmin))

    def has_object_destroy_permission(self, request):
        # Only superadmins or the creator or an admin member of the creator's organization can delete
        if not request.user.is_authenticated:
            return False
        else:
            return (request.user.role.is_superadmin or request.user.role.is_admin or request.user.id == self.id
                    or (request.user.organization.id == self.organization.id and request.user.role.is_partneradmin))

    role = models.ForeignKey('Role', models.PROTECT, null=True, related_name='users')
    organization = models.ForeignKey('Organization', models.PROTECT, null=True, related_name='users')
    circles = models.ManyToManyField(
        'Circle', through='CircleUser', through_fields=('user', 'circle'), related_name='users')
    active_key = models.TextField(blank=True, default='')
    user_status = models.CharField(max_length=128, blank=True, default='')

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


class Circle(PermissionsHistoryNameModel):
    """
    Circle of Trust
    """

    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_circle"
        ordering = ['id']


class CircleUser(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Circles and Users.
    """

    circle = models.ForeignKey('Circle', models.CASCADE)
    user = models.ForeignKey('User', models.CASCADE)

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

    private_name = models.CharField(max_length=128, blank=True, default='')
    address_one = models.CharField(max_length=128, blank=True, default='')
    address_two = models.CharField(max_length=128, blank=True, default='')
    city = models.CharField(max_length=128, blank=True, default='')
    postal_code = models.CharField(max_length=128, blank=True, default='')
    administrative_level_one = models.ForeignKey(
        'AdministrativeLevelOne', models.PROTECT, null=True, related_name='organizations')
    country = models.ForeignKey('Country', models.PROTECT, null=True, related_name='organizations')
    phone = models.CharField(max_length=128, blank=True, default='')
    parent_organization = models.ForeignKey('self', models.CASCADE, null=True, related_name='child_organizations')
    do_not_publish = models.BooleanField(default=False)
    laboratory = models.BooleanField(default=False)

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

    first_name = models.CharField(max_length=128, blank=True, default='')
    last_name = models.CharField(max_length=128, blank=True, default='')
    email = models.CharField(max_length=128, blank=True, default='')
    # email = models.CharField(max_length=128, null=True, blank=True, default=None, unique=True)  # COMMENT: this can only be applied after the cooperator fixes their duplicate records
    phone = models.TextField(blank=True, default='')
    affiliation = models.TextField(blank=True, default='')
    title = models.CharField(max_length=128, blank=True, default='')
    position = models.CharField(max_length=128, blank=True, default='')
    # contact_type = models.ForeignKey('ContactType', models.PROTECT, related_name='contacts')  # COMMENT: this related table is not shown in the ERD
    organization = models.ForeignKey('Organization', models.PROTECT, related_name='contacts', null=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_contact"
        ordering = ['id']


class ContactType(AdminPermissionsHistoryModel):
    """
    Contact Type
    """

    name = models.CharField(max_length=128, blank=True, default='')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_contacttype"
        ordering = ['id']


class Search(HistoryModel):
    """
    Searches
    """

    @staticmethod
    def has_read_permission(request):
        # Only admins or the creator can 'read' (list)
        # but this cannot be controlled here in this model; it can only be controlled in the views using this model
        return True

    def has_object_read_permission(self, request):
        # Only admins or the creator can 'read' (retrieve)
        if not request.user.is_authenticated:
            return False
        else:
            return request.user.role.is_superadmin or request.user.role.is_admin or request.user == self.created_by

    @staticmethod
    def has_write_permission(request):
        # Anyone can 'write'
        # (note that update and destroy are handled explicitly below, so 'write' now only pertains to create)
        return True

    def has_object_update_permission(self, request):
        # Only admins or the creator can update
        if not request.user.is_authenticated:
            return False
        else:
            return request.user.role.is_superadmin or request.user.role.is_admin or request.user == self.created_by

    def has_object_destroy_permission(self, request):
        # Only superadmins or the creator can delete
        if not request.user.is_authenticated:
            return False
        else:
            return request.user.role.is_superadmin or request.user.role.is_admin or request.user == self.created_by

    name = models.CharField(max_length=128, blank=True, default='')
    data = JSONField(blank=True)
    count = models.IntegerField(default=0)

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
    nation = models.CharField(max_length=128)
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
