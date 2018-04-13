from django.db import models
from datetime import date
from django.contrib.auth.models import User
from django.conf import settings
from simple_history.models import HistoricalRecords


# Users will be stored in the core User model instead of a custom model.
# Default fields of the core User model: username, first_name, last_name, email, password, groups, user_permissions,
# is_staff, is_active, is_superuser, last_login, date_joined
# For more information, see: https://docs.djangoproject.com/en/1.11/ref/contrib/auth/#user


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


######
#
#  Events
#
######


class Event(HistoryModel):
    """
    Event
    """

    event_type = models.ForeignKey('EventType', models.PROTECT, related_name='events')
    event_reference = models.CharField(max_length=128, null=True, blank=True)
    complete = models.BooleanField(default=False)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    affected_count = models.IntegerField(null=True)
    epi_staff = models.ForeignKey('EpiStaff', 'events')  # QUESTION: what is the purpose of this field? shouldn't it be a relate to the User table?
    event_status = models.ForeignKey('EventStatus', 'events')
    legal_status = models.ForeignKey('LegalStatus', 'events', null=True)
    legal_number = models.CharField(max_length=128, null=True, blank=True)
    superevent = models.ForeignKey('SuperEvent', 'events', null=True)

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


class EpiStaff(NameModel):  # QUESTION: what is the purpose of this table? see related comment in Event model
    """
    Epi Staff
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_epistaff"


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


class EventOrganization(HistoryModel):
    """
    Table to allow many-to-many relationship between Events and Organizations.
    """

    event = models.ForeignKey('Event', models.PROTECT)
    organization = models.ForeignKey('Organization', models.PROTECT)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventorganization"


class EventContact(HistoryModel):
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


class EventLocation(NameModel):
    """
    Event Location
    """

    event = models.ForeignKey('Event', models.PROTECT, related_name='eventlocations')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    country = models.ForeignKey('Country', models.PROTECT, related_name='eventlocations')
    state = models.ForeignKey('State', models.PROTECT, related_name='eventlocations')
    county = models.ForeignKey('County', models.PROTECT, related_name='eventlocations')
    county_multiple = models.BooleanField(default=False)
    county_unknown = models.BooleanField(default=False)
    latitude = models.DecimalField(max_digits=12, decimal_places=10, null=True, blank=True)
    longitude = models.DecimalField(max_digits=13, decimal_places=10, null=True, blank=True)
    priority = models.IntegerField(null=True)
    land_ownership = models.ForeignKey('LandOwnership', models.PROTECT, related_name='eventlocations')
    flyway = models.CharField(max_length=128, null=True, blank=True)
    # gnis_name = models.ForeignKey('GNISName', models.PROTECT, related_name='eventlocations')  # COMMENT: this related table is not shown in the ERD

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_eventlocation"


class Country(NameModel):
    """
    Country
    """

    abbreviation = models.CharField(max_length=128, null=True, blank=True)
    calling_code = models.IntegerField(null=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_country"
        verbose_name_plural = "countries"


class State(NameModel):  # COMMENT: if we're including countries, then we should probably rename this to 'first-level division' or something not US-specific
    """
    State
    """

    country = models.ForeignKey('Country', models.PROTECT, related_name='states')
    abbreviation = models.CharField(max_length=128, null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_state"


class County(NameModel):  # COMMENT: if we're including countries, then we should probably rename this to 'second-level division' or something not US-specific
    """
    County
    """

    state = models.ForeignKey('Country', models.PROTECT, related_name='counties')
    points = models.CharField(max_length=128, null=True, blank=True)  # QUESTION: what is the purpose of this field?
    centroid_latitude = models.DecimalField(max_digits=12, decimal_places=10, null=True, blank=True)
    centroid_longitude = models.DecimalField(max_digits=13, decimal_places=10, null=True, blank=True)
    fips_code = models.CharField(max_length=128, null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_county"
        verbose_name_plural = "counties"


class LandOwnership(NameModel):
    """
    Land Ownership
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_landownership"


######
#
#  Species
#
######


class LocationSpecies(HistoryModel):
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
    age_bias = models.ForeignKey('AgeBias', models.PROTECT, related_name='locationspecies')
    sex_bias = models.ForeignKey('SexBias', models.PROTECT, related_name='locationspecies')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_locationspecies"
        verbose_name_plural = "locationspecies"


class Species(NameModel):
    """
    Species
    """

    class_name = models.CharField(max_length=128, null=True, blank=True)
    order_name = models.CharField(max_length=128, null=True, blank=True)
    family_name = models.CharField(max_length=128, null=True, blank=True)
    sub_family_name = models.CharField(max_length=128, null=True, blank=True)
    genus_name = models.CharField(max_length=128, null=True, blank=True)
    species_latin_name = models.CharField(max_length=128, null=True, blank=True)
    subspecies_latin_name = models.CharField(max_length=128, null=True, blank=True)
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


class Diagnosis(HistoryModel):
    """
    Diagnosis
    """

    diagnosis_type = models.ForeignKey('DiagnosisType', models.PROTECT, related_name='diagnoses')
    diagnosis = models.CharField(max_length=128)

    def __str__(self):
        return self.diagnosis

    class Meta:
        db_table = "whispers_diagnosis"
        verbose_name_plural = "diagnoses"


class DiagnosisType(NameModel):
    """
    Diagnosis Type
    """

    color = models.CharField(max_length=128, null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_diagnosistype"


class EventDiagnosis(HistoryModel):
    """
    Event Diagnosis
    """

    event = models.ForeignKey('Event', models.PROTECT, related_name='eventdiagnoses')
    diagnosis = models.ForeignKey('Diagnosis', models.PROTECT, related_name='eventdiagnoses')
    confirmed = models.BooleanField(default=False)
    major = models.BooleanField(default=False)
    priority = models.IntegerField(null=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_eventdiagnosis"
        verbose_name_plural = "eventdiagnoses"


class SpeciesDiagnosis(HistoryModel):
    """
    SpeciesDiagnosis
    """

    location_species = models.ForeignKey('LocationSpecies', models.PROTECT, related_name='speciesdiagnoses')
    diagnosis = models.ForeignKey('Diagnosis', models.PROTECT, related_name='speciesdiagnoses')
    confirmed = models.BooleanField(default=False)
    major = models.BooleanField(default=False)
    priority = models.IntegerField(null=True)
    causal = models.BooleanField(default=False)
    tested_count = models.IntegerField(null=True)
    positive_count = models.IntegerField(null=True)
    suspect_count = models.IntegerField(null=True)
    pooled = models.BooleanField(default=False)
    organization = models.ForeignKey('Organization', models.PROTECT, related_name='speciesdiagnoses')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_speciesdiagnosis"
        verbose_name_plural = "speciesdiagnoses"


######
#
#  Misc
#
######


class Permission(HistoryModel):  # TODO: implement relates to other models that use permissions
    """
    Permission
    """

    organization = models.ForeignKey('Organization', models.PROTECT, related_name='permissions')
    role = models.ForeignKey('Role', models.PROTECT, related_name='permissions')
    group = models.ForeignKey('Group', models.PROTECT, related_name='permissions')
    table = models.CharField(max_length=128, null=True, blank=True)
    object = models.IntegerField(null=True, blank=True)
    permission_type = models.ForeignKey('PermissionType', models.PROTECT, related_name='permissions')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_permission"


class PermissionType(NameModel):
    """
    Permission Type: read, write, read+write
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_permissiontype"


class Comment(HistoryModel):  # TODO: implement relates to other models that use comments
    """
    Comment
    """

    table = models.CharField(max_length=128, null=True, blank=True)
    object = models.IntegerField(null=True, blank=True)
    comment = models.TextField(blank=True)
    keywords = models.CharField(max_length=128, null=True, blank=True)
    link = models.IntegerField(null=True, blank=True)  # QUESTION: what is the purpose of this field? shouldn't it be a relate to the User table?
    link_type = models.IntegerField(null=True, blank=True)  # QUESTION: what is the purpose of this field? shouldn't it be a relate to the User table?

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_comment"


class Artifact(HistoryModel):  # TODO: implement file fields
    """
    Artifact
    """

    filename = models.CharField(max_length=128, null=True, blank=True)
    keywords = models.CharField(max_length=128, null=True, blank=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_artifact"


######
#
#  Users
#
######


class UserProfile(HistoryModel):
    """
    Extends the default User model.
    Default fields of the User model: username, first_name, last_name, email, password, groups, user_permissions,
       is_staff, is_active, is_superuser, last_login, date_joined
    """
    user = models.OneToOneField(User, models.PROTECT)

    role = models.ForeignKey('Role', models.PROTECT, related_name='users')
    organization = models.ForeignKey('Organization', models.PROTECT, related_name='users')
    last_visit = models.DateField(null=True, blank=True)
    active_key = models.TextField(blank=True)
    user_status = models.CharField(max_length=128, null=True, blank=True)

    def __str__(self):
        return self.user.username

    class Meta:
        db_table = "whispers_userprofile"


class Role(NameModel):
    """
    User Role
    """

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_role"


class Organization(NameModel):
    """
    Organization
    """

    private_name = models.CharField(max_length=128, null=True, blank=True)
    address_one = models.CharField(max_length=128, null=True, blank=True)
    address_two = models.CharField(max_length=128, null=True, blank=True)
    city = models.CharField(max_length=128, null=True, blank=True)
    zip_postal_code = models.BigIntegerField(null=True, blank=True)
    state = models.ForeignKey('State', models.PROTECT, related_name='organizations')
    country = models.ForeignKey('Country', models.PROTECT, related_name='organizations')
    phone = models.BigIntegerField(null=True, blank=True)
    parent_organization = models.ForeignKey('self', models.PROTECT, related_name='child_organizations', null=True)
    do_not_publish = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_organization"


class Contact(HistoryModel):
    """
    Contact
    """

    first_name = models.CharField(max_length=128, null=True, blank=True)
    last_name = models.CharField(max_length=128, null=True, blank=True)
    email = models.CharField(max_length=128, null=True, blank=True)
    phone = models.BigIntegerField(null=True, blank=True)
    title = models.CharField(max_length=128, null=True, blank=True)
    position = models.CharField(max_length=128, null=True, blank=True)
    # contact_type = models.ForeignKey('ContactType', models.PROTECT, related_name='contacts')  # COMMENT: this related table is not shown in the ERD
    organization = models.ForeignKey('Organization', models.PROTECT, related_name='contacts')
    owner_organization = models.ForeignKey('Organization', models.PROTECT, related_name='owned_contacts')

    def __str__(self):
        return str(self.id)

    class Meta:
        db_table = "whispers_contact"


class Group(NameModel):
    """
    Group
    """
    description = models.TextField(blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True)
    # owner = models.ForeignKey('User', models.PROTECT)
    
    def __str__(self):
        return self.name

    class Meta:
        db_table = "whispers_group"


class Search(HistoryModel):
    """
    User saved searches
    """
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT)
    data = models.TextField(blank=True)

    class Meta:
        db_table = "whispers_savedsearches"

