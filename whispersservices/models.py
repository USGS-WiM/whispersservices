from django.db import models
from datetime import date
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
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
    history = HistoricalRecords()

    class Meta:
        abstract = True
        default_permissions = ('add', 'change', 'delete', 'view')


class NameModel(HistoryModel):
    """
    An abstract base class model for the common name field.
    """

    name = models.CharField(max_length=128, unique=True)

    class Meta:
        abstract = True


# TODO: impose read-only permissions on lookup tables except for admins
class PermissionsHistoryModel(HistoryModel):
    """
    An abstract base class model for the common permissions.
    """

    @staticmethod
    def has_read_permission(request):
        # Everyone can read (list and retrieve) all events, but some fields may be private
        return True

    def has_object_read_permission(self, request):
        # Everyone can read (list and retrieve) all events, but some fields may be private
        return True

    @staticmethod
    def has_write_permission(request):
        # Only a superuser and users with specific roles can 'write' an event
        # (note that update and destroy are handled explicitly below, so 'write' now only pertains to create)
        # Currently this list is 'SuperAdmin', 'Admin', 'PartnerAdmin', 'PartnerManager', 'Partner'
        # (which only excludes 'Affiliate' and 'Public', but could possibly change... explicit is better than implicit)
        allowed_role_names = ['SuperAdmin', 'Admin', 'PartnerAdmin', 'PartnerManager', 'Partner']
        allowed_role_ids = Role.objects.filter(name__in=allowed_role_names).values_list('id', flat=True)
        if not request.user.is_authenticated:
            return False
        else:
            return request.user.role.id in allowed_role_ids or request.user.is_superuser

    def has_object_update_permission(self, request):
        # Only the creator or a manager/admin member of the creator's organization or a superuser can update an event
        if not request.user.is_authenticated:
            return False
        else:
            return request.user == self.created_by or (request.user.organization == self.created_by.organization and (
                request.user.role.is_partnermanager or request.user.role.is_partneradmin)) or request.user.is_superuser

    def has_object_destroy_permission(self, request):
        # Only the creator or a manager/admin member of the creator's organization or a superuser can delete an event
        if not request.user.is_authenticated:
            return False
        else:
            return request.user == self.created_by or (request.user.organization == self.created_by.organization and (
                request.user.role.is_partnermanager or request.user.role.is_partneradmin)) or request.user.is_superuser

    class Meta:
        abstract = True


class PermissionsNameModel(PermissionsHistoryModel):
    """
    An abstract base class model for the common name field and the common permissions.
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
    quality_check = models.BooleanField(default=False)  # TODO: value needs to change when complete field changes
    public = models.BooleanField(default=True)
    circle_read = models.ForeignKey('Circle', models.PROTECT, null=True, related_name='readevents')
    circle_write = models.ForeignKey('Circle', models.PROTECT, null=True, related_name='writeevents')
    superevents = models.ManyToManyField('SuperEvent', through='EventSuperEvent', related_name='events')
    organizations = models.ManyToManyField('Organization', through='EventOrganization', related_name='events')
    contacts = models.ManyToManyField('Contact', through='EventContact', related_name='event')
    comments = GenericRelation('Comment', related_name='events')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_event"
        # TODO: 'unique together' fields


class EventSuperEvent(HistoryModel):
    """
    Table to allow many-to-many relationship between Events and Super Events.
    """

    event = models.ForeignKey('Event', models.PROTECT)
    superevent = models.ForeignKey('SuperEvent', models.PROTECT)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventsuperevent"


class SuperEvent(HistoryModel):
    """
    Super Event
    """

    category = models.IntegerField(null=True)
    comments = GenericRelation('Comment', related_name='superevents')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_superevent"


class EventType(NameModel):
    """
    Event Type
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_eventtype"


class Staff(HistoryModel):
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


class LegalStatus(NameModel):
    """
    Legal Status
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_legalstatus"


class EventStatus(NameModel):
    """
    Event Status
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_eventstatus"
        verbose_name_plural = "eventstatuses"


class EventAbstract(HistoryModel):
    """
    Event Abstract
    """

    event = models.ForeignKey('Event', models.PROTECT, related_name='eventabstracts')
    text = models.TextField(blank=True)
    lab_id = models.IntegerField(null=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventabstract"


class EventCase(HistoryModel):
    """
    Event Case
    """

    event = models.ForeignKey('Event', models.PROTECT, related_name='eventcases')
    case = models.IntegerField(null=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventcase"


class EventLabsite(HistoryModel):
    """
    Event Labsite
    """

    event = models.ForeignKey('Event', models.PROTECT, related_name='eventlabsites')
    lab_id = models.IntegerField(null=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventlabsite"


class EventOrganization(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Events and Organizations.
    """

    event = models.ForeignKey('Event', models.PROTECT)
    organization = models.ForeignKey('Organization', models.PROTECT)
    priority = models.IntegerField(null=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventorganization"


class EventContact(PermissionsHistoryModel):
    """
    Table to allow many-to-many relationship between Events and Contacts.
    """

    event = models.ForeignKey('Event', models.PROTECT)
    contact = models.ForeignKey('Contact', models.PROTECT)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventcontact"


######
#
#  Locations
#
######


class EventLocation(PermissionsHistoryModel):
    """
    Event Location
    """

    name = models.CharField(max_length=128)
    event = models.ForeignKey('Event', models.PROTECT, related_name='eventlocations')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    country = models.ForeignKey('Country', models.PROTECT, related_name='eventlocations')
    administrative_level_one = models.ForeignKey(
        'AdministrativeLevelOne', models.PROTECT, related_name='eventlocations')
    administrative_level_two = models.ForeignKey(
        'AdministrativeLevelTwo', models.PROTECT, null=True, related_name='eventlocations')
    county_multiple = models.BooleanField(default=False)
    county_unknown = models.BooleanField(default=False)
    latitude = models.DecimalField(max_digits=12, decimal_places=10, null=True, blank=True)
    longitude = models.DecimalField(max_digits=13, decimal_places=10, null=True, blank=True)
    priority = models.IntegerField(null=True)
    land_ownership = models.ForeignKey('LandOwnership', models.PROTECT, null=True, related_name='eventlocations')
    contacts = models.ManyToManyField('Contact', through='EventLocationContact', related_name='eventlocations')
    flyways =models.ManyToManyField('Flyway', through='EventLocationFlyway', related_name='eventlocations')
    # gnis_name = models.ForeignKey('GNISName', models.PROTECT, related_name='eventlocations')  # COMMENT: this related table is not shown in the ERD
    comments = GenericRelation('Comment', related_name='eventlocations')

    # override the save method to calculate the parent event's start_date and end_date and affected_count
    def save(self, *args, **kwargs):
        super(EventLocation, self).save(*args, **kwargs)

        event = self.event
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
                event.affected_count = sum(species_dx_positive_counts)

        event.save()

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_eventlocation"


class EventLocationContact(HistoryModel):
    """
    Table to allow many-to-many relationship between Event Locations and Contacts.
    """

    event_location = models.ForeignKey('EventLocation', models.PROTECT)
    contact = models.ForeignKey('Contact', models.PROTECT)
    contact_type = models.ForeignKey('ContactType', models.PROTECT, null=True, related_name='eventlocationcontacts')
    
    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventlocationcontact"


class Country(NameModel):
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


class AdministrativeLevelOne(NameModel):
    """
    Administrative Level One (ex. in US it is State)
    """

    country = models.ForeignKey('Country', models.PROTECT, related_name='administrativelevelones')
    abbreviation = models.CharField(max_length=128, blank=True, default='')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_administrativelevelone"


class AdministrativeLevelTwo(HistoryModel):
    """
    Administrative Level Two (ex. in US it is counties)
    """

    name = models.CharField(max_length=128)
    administrative_level_one = models.ForeignKey(
        'AdministrativeLevelOne', models.PROTECT, related_name='administrativeleveltwos')
    points = models.TextField(blank=True, default='')  # QUESTION: what is the purpose of this field?
    centroid_latitude = models.DecimalField(max_digits=12, decimal_places=10, null=True, blank=True)
    centroid_longitude = models.DecimalField(max_digits=13, decimal_places=10, null=True, blank=True)
    fips_code = models.CharField(max_length=128, blank=True, default='')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_administrativeleveltwo"
        unique_together = ('name', 'administrative_level_one')


class AdministrativeLevelLocality(NameModel):
    """
    Table for looking up local names for adminstrative levels based on country
    """

    country = models.ForeignKey('Country', models.PROTECT, related_name='country')
    admin_level_one_name = models.CharField(max_length=128, blank=True, default='')
    admin_level_two_name = models.CharField(max_length=128, blank=True, default='')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_adminstrativelevellocality"


class LandOwnership(NameModel):
    """
    Land Ownership
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_landownership"


class EventLocationFlyway(HistoryModel):
    """
    Table to allow many-to-many relationship between Event Locations and Flyways.
    """

    event_location = models.ForeignKey('EventLocation', models.PROTECT)
    flyway = models.ForeignKey('Flyway', models.PROTECT)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventlocationflyway"


class Flyway(NameModel):
    """
    Flyway
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_flyway"


######
#
#  Species
#
######


class LocationSpecies(PermissionsHistoryModel):
    """
    Location Species
    """

    event_location = models.ForeignKey('EventLocation', models.PROTECT, related_name='locationspecies')
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

        event = self.event_location.event
        locations = EventLocation.objects.filter(event=event.id).values('id', 'start_date', 'end_date')

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
                event.affected_count = sum(species_dx_positive_counts)

        event.save()

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_locationspecies"
        verbose_name_plural = "locationspecies"


class Species(HistoryModel):
    """
    Species
    """

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


class AgeBias(NameModel):
    """
    Age Bias
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_agebias"
        verbose_name_plural = "agebiases"


class SexBias(NameModel):
    """
    Sex Bias
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_sexbias"
        verbose_name_plural = "sexbiases"


######
#
#  Diagnoses
#
######


class Diagnosis(NameModel):
    """
    Diagnosis
    """

    diagnosis_type = models.ForeignKey('DiagnosisType', models.PROTECT, related_name='diagnoses')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_diagnosis"
        verbose_name_plural = "diagnoses"


class DiagnosisType(NameModel):
    """
    Diagnosis Type
    """

    color = models.CharField(max_length=128, blank=True, default='')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_diagnosistype"


class EventDiagnosis(PermissionsHistoryModel):
    """
    Event Diagnosis
    """

    event = models.ForeignKey('Event', models.PROTECT, related_name='eventdiagnoses')
    diagnosis = models.ForeignKey('Diagnosis', models.PROTECT, related_name='eventdiagnoses')
    confirmed = models.BooleanField(default=False)
    major = models.BooleanField(default=False)
    priority = models.IntegerField(null=True)

    def __str__(self):
        return str(self.diagnosis)

    class Meta:
        db_table = "whispers_eventdiagnosis"
        verbose_name_plural = "eventdiagnoses"


class SpeciesDiagnosis(PermissionsHistoryModel):
    """
    SpeciesDiagnosis
    """

    location_species = models.ForeignKey('LocationSpecies', models.PROTECT, related_name='speciesdiagnoses')
    diagnosis = models.ForeignKey('Diagnosis', models.PROTECT, related_name='speciesdiagnoses')
    cause = models.ForeignKey('DiagnosisCause', models.PROTECT, null=True, related_name='speciesdiagnoses')
    basis = models.ForeignKey('DiagnosisBasis', models.PROTECT, null=True, related_name='speciesdiagnoses')
    confirmed = models.BooleanField(default=False)
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
        super(SpeciesDiagnosis, self).save(*args, **kwargs)

        event = self.location_species.event_location.event
        locations = EventLocation.objects.filter(event=event.id).values('id', 'start_date', 'end_date')

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
                event.affected_count = sum(species_dx_positive_counts)

        event.save()
    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_speciesdiagnosis"
        verbose_name_plural = "speciesdiagnoses"


class SpeciesDiagnosisOrganization(HistoryModel):
    """
    Table to allow many-to-many relationship between SpeciesDiagnosis and Organizations.
    """

    species_diagnosis = models.ForeignKey('SpeciesDiagnosis', models.PROTECT)
    organization = models.ForeignKey('Organization', models.PROTECT)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_speciesdiagnosisorganization"


class DiagnosisBasis(NameModel):
    """
    Diagnosis Basis
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_diagnosisbasis"
        verbose_name_plural = "diagnosisbases"


class DiagnosisCause(NameModel):
    """
    Diagnosis Cause
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_diagnosiscause"


######
#
#  Misc
#
######


class Comment(HistoryModel):  # TODO: implement relates to other models that use comments
    """
    Comment
    """

    comment = models.TextField(blank=True)
    comment_type = models.ForeignKey('CommentType', models.PROTECT, related_name='comments', null=True)

    # Below the mandatory fields for generic relation
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey()

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_comment"


class CommentType(NameModel):
    """
    Comment Type
    """

    def __str__(self):
        return str(self.name)

    class Meta:
        db_table = "whispers_commenttype"


class Artifact(HistoryModel):  # TODO: implement file fields
    """
    Artifact
    """

    filename = models.CharField(max_length=128, blank=True, default='')
    keywords = models.CharField(max_length=128, blank=True, default='')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_artifact"


######
#
#  Users
#
######


class User(AbstractUser):
    """
    Extends the default User model.
    Default fields of the User model: username, first_name, last_name, email, password, groups, user_permissions,
       is_staff, is_active, is_superuser, last_login, date_joined
    """
    role = models.ForeignKey('Role', models.PROTECT, null=True, related_name='users')
    organization = models.ForeignKey('Organization', models.PROTECT, null=True, related_name='users')
    circles = models.ManyToManyField(
        'Circle', through='CircleUser', through_fields=('user', 'circle'), related_name='users')
    active_key = models.TextField(blank=True, default='')
    user_status = models.CharField(max_length=128, blank=True, default='')

    def __str__(self):
        return self.username

    class Meta:
        db_table = "whispers_user"


class Role(NameModel):
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


class Circle(NameModel):
    """
    Circle of Trust
    """

    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_circle"


class CircleUser(HistoryModel):
    """
    Table to allow many-to-many relationship between Circles and Users.
    """

    circle = models.ForeignKey('Circle', models.PROTECT)
    user = models.ForeignKey('User', models.PROTECT)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_circleuser"


# TODO: apply permissions to this model such that only admins and up can write (create/update/delete)
class Organization(NameModel):
    """
    Organization
    """

    private_name = models.CharField(max_length=128, blank=True, default='')
    address_one = models.CharField(max_length=128, blank=True, default='')
    address_two = models.CharField(max_length=128, blank=True, default='')
    city = models.CharField(max_length=128, blank=True, default='')
    postal_code = models.CharField(max_length=128, blank=True, default='')  # models.BigIntegerField(null=True, blank=True)
    administrative_level_one = models.ForeignKey(
        'AdministrativeLevelOne', models.PROTECT, null=True, related_name='organizations')
    country = models.ForeignKey('Country', models.PROTECT, null=True, related_name='organizations')
    phone = models.CharField(max_length=128, blank=True, default='')
    parent_organization = models.ForeignKey('self', models.PROTECT, null=True, related_name='child_organizations')
    do_not_publish = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_organization"


class Contact(HistoryModel):
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
    phone = models.TextField(blank=True, default='')
    affiliation = models.TextField(blank=True)
    title = models.CharField(max_length=128, blank=True, default='')
    position = models.CharField(max_length=128, blank=True, default='')
    # contact_type = models.ForeignKey('ContactType', models.PROTECT, related_name='contacts')  # COMMENT: this related table is not shown in the ERD
    organization = models.ForeignKey('Organization', models.PROTECT, related_name='contacts', null=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_contact"


class ContactType(HistoryModel):
    """
    Contact Type
    """

    name = models.CharField(max_length=128, blank=True, default='')

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_contacttype"


class Search(NameModel):
    """
    Searches
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT)  # QUESTION: is this field necessary? doesn't 'created_by' fulfill the same need?
    data = models.TextField(blank=True)

    class Meta:
        db_table = "whispers_search"
        verbose_name_plural = "searches"


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
    confirmed = models.BooleanField()
    number_tested = models.IntegerField()
    number_positive = models.IntegerField()
    row_num = models.IntegerField(primary_key=True)

    def __str__(self):
        return str(self.row_num)

    class Meta:
        db_table = "flat_event_details"
        managed = False
