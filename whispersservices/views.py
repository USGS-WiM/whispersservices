import datetime as dtmod
from datetime import datetime as dt
from django.utils import timezone
from django.shortcuts import render
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from rest_framework import views, viewsets, generics, permissions, authentication, status
from rest_framework.response import Response
from whispersservices.serializers import *
from whispersservices.models import *
from whispersservices.permissions import *
from dry_rest_permissions.generics import DRYPermissions
User = get_user_model()


########################################################################################################################
#
#  copyright: 2017 WiM - USGS
#  authors: Aaron Stephenson USGS WIM (Web Informatics and Mapping)
#
#  In Django, a view is what takes a Web request and returns a Web response. The response can be many things, but most
#  of the time it will be a Web page, a redirect, or a document. In this case, the response will almost always be data
#  in JSON format.
#
#  All these views are written as Class-Based Views (https://docs.djangoproject.com/en/2.0/topics/class-based-views/)
#  because that is the paradigm used by Django Rest Framework (http://www.django-rest-framework.org/api-guide/views/)
#  which is the toolkit we used to create web services in Django.
#
#
########################################################################################################################


######
#
#  Abstract Base Classes
#
######


class AuthLastLoginMixin(object):
    """
    This class will update the user's last_login field each time a request is received
    """

    permission_classes = (permissions.IsAuthenticated,)

    def finalize_response(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated:
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])
        return super(AuthLastLoginMixin, self).finalize_response(request, *args, **kwargs)


class HistoryViewSet(AuthLastLoginMixin, viewsets.ModelViewSet):
    """
    This class will automatically assign the User ID to the created_by and modified_by history fields when appropriate
    """

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, modified_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(modified_by=self.request.user)


######
#
#  Events
#
######


class EventViewSet(HistoryViewSet):
    permission_classes = (DRYPermissions,)
    queryset = Event.objects.all()
    serializer_class = EventSerializer


class EventDetailViewSet(HistoryViewSet):
    queryset = Event.objects.all()
    serializer_class = EventDetailSerializer


class SuperEventViewSet(HistoryViewSet):
    queryset = SuperEvent.objects.all()
    serializer_class = SuperEventSerializer


class EventTypeViewSet(HistoryViewSet):
    queryset = EventType.objects.all()
    serializer_class = EventTypeSerializer


class EpiStaffViewSet(HistoryViewSet):
    queryset = EpiStaff.objects.all()
    serializer_class = EpiStaffSerializer


class LegalStatusViewSet(HistoryViewSet):
    queryset = LegalStatus.objects.all()
    serializer_class = LegalStatusSerializer


class EventStatusViewSet(HistoryViewSet):
    queryset = EventStatus.objects.all()
    serializer_class = EventStatusSerializer


class EventAbstractViewSet(HistoryViewSet):
    # queryset = EventAbstract.objects.all()
    serializer_class = EventAbstractSerializer

    def get_queryset(self):
        queryset = EventAbstract.objects.all()
        contains = self.request.query_params.get('contains', None)
        if contains is not None:
            queryset = queryset.filter(text__contains=contains)
        return queryset


class EventCaseViewSet(HistoryViewSet):
    queryset = EventCase.objects.all()
    serializer_class = EventCaseSerializer


class EventLabsiteViewSet(HistoryViewSet):
    queryset = EventLabsite.objects.all()
    serializer_class = EventLabsiteSerializer


class EventOrganizationViewSet(HistoryViewSet):
    queryset = EventOrganization.objects.all()
    serializer_class = EventOrganizationSerializer


class EventContactViewSet(HistoryViewSet):
    queryset = EventContact.objects.all()
    serializer_class = EventContactSerializer


######
#
#  Locations
#
######


class EventLocationViewSet(HistoryViewSet):
    queryset = EventLocation.objects.all()
    serializer_class = EventLocationSerializer


class EventLocationContactViewSet(HistoryViewSet):
    queryset = EventLocationContact.objects.all()
    serializer_class = EventLocationContactSerializer


class CountryViewSet(HistoryViewSet):
    queryset = Country.objects.all()
    serializer_class = CountrySerializer


class AdministrativeLevelOneViewSet(HistoryViewSet):
    # queryset = AdministrativeLevelOne.objects.all()
    serializer_class = AdministrativeLevelOneSerializer

    def get_queryset(self):
        queryset = AdministrativeLevelOne.objects.all()
        countries = self.request.query_params.get('country', None)
        if countries is not None:
            countries_list = countries.split(',')
            queryset = queryset.filter(country__in=countries_list)
        return queryset


class AdministrativeLevelTwoViewSet(HistoryViewSet):
    # queryset = AdministrativeLevelTwo.objects.all()
    serializer_class = AdministrativeLevelTwoSerializer

    def get_queryset(self):
        queryset = AdministrativeLevelTwo.objects.all()
        administrative_level_one = self.request.query_params.get('administrativelevelone', None)
        if administrative_level_one is not None:
            administrative_level_one_list = administrative_level_one.split(',')
            queryset = queryset.filter(administrative_level_one__in=administrative_level_one_list)
        return queryset


class AdministrativeLevelLocalityViewSet(HistoryViewSet):
    queryset = AdministrativeLevelLocality.objects.all()
    serializer_class = AdministrativeLevelLocalitySerializer


class LandOwnershipViewSet(HistoryViewSet):
    queryset = LandOwnership.objects.all()
    serializer_class = LandOwnershipSerializer


######
#
#  Species
#
######


class LocationSpeciesViewSet(HistoryViewSet):
    queryset = LocationSpecies.objects.all()
    serializer_class = LocationSpeciesSerializer


class SpeciesViewSet(HistoryViewSet):
    queryset = Species.objects.all()
    serializer_class = SpeciesSerializer


class AgeBiasViewSet(HistoryViewSet):
    queryset = AgeBias.objects.all()
    serializer_class = AgeBiasSerializer


class SexBiasViewSet(HistoryViewSet):
    queryset = SexBias.objects.all()
    serializer_class = SexBiasSerializer


######
#
#  Diagnoses
#
######


class DiagnosisViewSet(HistoryViewSet):
    # queryset = Diagnosis.objects.all()
    serializer_class = DiagnosisSerializer

    # override the default queryset to allow filtering by URL argument diagnosis_type
    def get_queryset(self):
        queryset = Diagnosis.objects.all()
        diagnosis_type = self.request.query_params.get('diagnosis_type', None)
        if diagnosis_type is not None:
            diagnosis_type_list = diagnosis_type.split(',')
            queryset = queryset.filter(diagnosis_type__in=diagnosis_type_list)
        return queryset


class DiagnosisTypeViewSet(HistoryViewSet):
    queryset = DiagnosisType.objects.all()
    serializer_class = DiagnosisTypeSerializer


class EventDiagnosisViewSet(HistoryViewSet):
    queryset = EventDiagnosis.objects.all()
    serializer_class = EventDiagnosisSerializer


class SpeciesDiagnosisViewSet(HistoryViewSet):
    queryset = SpeciesDiagnosis.objects.all()
    serializer_class = SpeciesDiagnosisSerializer


######
#
#  Misc
#
######


class PermissionViewSet(HistoryViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer


class PermissionTypeViewSet(HistoryViewSet):
    queryset = PermissionType.objects.all()
    serializer_class = PermissionTypeSerializer


class CommentViewSet(HistoryViewSet):
    # queryset = Comment.objects.all()
    serializer_class = CommentSerializer

    def get_queryset(self):
        queryset = Comment.objects.all()
        contains = self.request.query_params.get('contains', None)
        if contains is not None:
            queryset = queryset.filter(comment__contains=contains)
        return queryset


class ArtifactViewSet(HistoryViewSet):
    queryset = Artifact.objects.all()
    serializer_class = ArtifactSerializer


######
#
#  Users
#
######


class UserViewSet(HistoryViewSet):
    serializer_class = UserSerializer

    def get_queryset(self):
        # do not return the admin user
        queryset = User.objects.all().exclude(id__exact=1)
        # filter by username, exact
        username = self.request.query_params.get('username', None)
        if username is not None:
            queryset = queryset.filter(username__exact=username)
        email = self.request.query_params.get('email', None)
        if email is not None:
            queryset = queryset.filter(email__exact=email)
        role = self.request.query_params.get('role', None)
        if role is not None:
            queryset = queryset.filter(role__exact=role)
        organization = self.request.query_params.get('organization', None)
        if email is not None:
            queryset = queryset.filter(organization__exact=organization)
        return queryset


class AuthView(views.APIView):
    authentication_classes = (authentication.BasicAuthentication,)
    serializer_class = UserSerializer

    def post(self, request):
        user = request.user
        if user.is_authenticated:
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])
        return Response(self.serializer_class(user).data)


class RoleViewSet(HistoryViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer


class OrganizationViewSet(HistoryViewSet):
    # queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        queryset = Organization.objects.all()
        users = self.request.query_params.get('users', None)
        if users is not None:
            users_list = users.split(',')
            queryset = queryset.filter(users__in=users_list)
        contacts = self.request.query_params.get('contacts', None)
        if contacts is not None:
            contacts_list = contacts.split(',')
            queryset = queryset.filter(contacts__in=contacts_list)
        return queryset


class ContactViewSet(HistoryViewSet):
    # queryset = Contact.objects.all()
    serializer_class = ContactSerializer

    def get_queryset(self):
        queryset = Contact.objects.all()
        orgs = self.request.query_params.get('org', None)
        if orgs is not None:
            orgs_list = orgs.split(',')
            queryset = queryset.filter(organization__in=orgs_list)
        owner_orgs = self.request.query_params.get('ownerorg', None)
        if owner_orgs is not None:
            owner_orgs_list = owner_orgs.split(',')
            queryset = queryset.filter(owner_organization__in=owner_orgs_list)
        return queryset


class ContactTypeViewSet(HistoryViewSet):
    queryset = ContactType.objects.all()
    serializer_class = ContactTypeSerializer


class GroupViewSet(HistoryViewSet):
    # queryset = Group.objects.all()
    serializer_class = GroupSerializer

    def get_queryset(self):
        queryset = Group.objects.all()
        owners = self.request.query_params.get('owner', None)
        if owners is not None:
            owners_list = owners.split(',')
            queryset = queryset.filter(owner__in=owners_list)
        return queryset


class SearchViewSet(HistoryViewSet):
    serializer_class = SearchSerializer

    def get_queryset(self):
        queryset = Search.objects.all()
        owners = self.request.query_params.get('owner', None)
        if owners is not None:
            owners_list = owners.split(',')
            queryset = queryset.filter(owner__in=owners_list)
        return queryset


######
#
#  Special
#
######


class EventSummaryViewSet(HistoryViewSet):
    serializer_class = EventSummarySerializer

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        queryset = Event.objects.all().prefetch_related(
            'sample_bottle', 'sample_bottle__bottle',
            'sample_bottle__bottle__bottle_prefix', 'sample_bottle__sample',
            'sample_bottle__sample__site', 'sample_bottle__sample__project', 'constituent', 'isotope_flag',
            'detection_flag', 'method'
        )

        # filter by eventtype ID, exact list
        eventtype = self.request.query_params.get('eventtype', None)
        if eventtype is not None:
            eventtype_list = eventtype.split(',')
            queryset = queryset.filter(eventtype__in=eventtype_list)
        # filter by eventstatus ID, exact list
        eventstatus = self.request.query_params.get('eventstatus', None)
        if eventstatus is not None:
            eventstatus_list = eventstatus.split(',')
            queryset = queryset.filter(eventstatus__in=eventstatus_list)
        # filter by diagnosis ID, exact list
        diagnosis = self.request.query_params.get('diagnosis', None)
        if diagnosis is not None:
            diagnosis_list = diagnosis.split(',')
            queryset = queryset.filter(eventdiagnoses__diagnois__in=diagnosis_list)
        # filter by diagnosistype ID, exact list
        diagnosistype = self.request.query_params.get('diagnosistype', None)
        if diagnosistype is not None:
            diagnosistype_list = diagnosistype.split(',')
            queryset = queryset.filter(eventdiagnoses__diagnois__diagnosistype__in=diagnosistype_list)
        # filter by species ID, exact list
        species = self.request.query_params.get('species', None)
        if species is not None:
            species_list = species.split(',')
            queryset = queryset.filter(eventlocations__locationspecies__species__in=species_list)
        # filter by administrative_level_one, exact list
        administrative_level_one = self.request.query_params.get('administrative_level_one', None)
        if administrative_level_one is not None:
            administrative_level_one_list = administrative_level_one.split(',')
            queryset = queryset.filter(eventlocations__administrative_level_one__in=administrative_level_one_list)
        # filter by administrative_level_two, exact list
        administrative_level_two = self.request.query_params.get('administrative_level_two', None)
        if administrative_level_two is not None:
            administrative_level_two_list = administrative_level_two.split(',')
            queryset = queryset.filter(eventlocations__administrative_level_two__in=administrative_level_two_list)
        # filter by flyway, exact list
        flyway = self.request.query_params.get('flyway', None)
        if flyway is not None:
            flyway_list = flyway.split(',')
            queryset = queryset.filter(eventlocations__flyway__in=flyway_list)
        # filter by country, exact list
        country = self.request.query_params.get('country', None)
        if country is not None:
            country_list = country.split(',')
            queryset = queryset.filter(eventlocations__country__in=country_list)
        # filter by affected, exact list
        affected_count = self.request.query_params.get('affected_count', None)
        if affected_count is not None:
            affected_count_list = affected_count.split(',')
            queryset = queryset.filter(affected_count__in=affected_count_list)
        # filter by start and end date (after only, before only, or between both, depending on which URL params appear)
        # the date filters below are date-exclusive
        startdate = self.request.query_params.get('startdate', None)
        enddate = self.request.query_params.get('enddate', None)
        if startdate is not None and enddate is not None:
            queryset = queryset.filter(start_date__gt=startdate,
                                       end_date__lt=enddate)
        elif startdate is not None:
            queryset = queryset.filter(start_date__gt=startdate)
        elif enddate is not None:
            queryset = queryset.filter(end_date__lt=enddate)
        # filter by owner ID, exact
        owner = self.request.query_params.get('owner', None)
        if owner is not None:
            queryset = queryset.filter(created_by__exact=owner)
        # filter by ownerorg ID, exact
        # ownerorg = self.request.query_params.get('ownerorg', None)
        # if ownerorg is not None:
        #     queryset = queryset.filter(created_by__organization__exact=ownerorg)
        # # filter by group ID, exact
        # group = self.request.query_params.get('group', None)
        # if group is not None:
        #     queryset = queryset.filter(group__exact=group)
        # return queryset
