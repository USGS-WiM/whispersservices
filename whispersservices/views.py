import datetime as dtmod
from datetime import datetime as dt
from django.shortcuts import render
from django.contrib.auth import authenticate, login, logout
from rest_framework import views, viewsets, generics, permissions, authentication, status
from rest_framework.response import Response
from whispersservices.serializers import *
from whispersservices.models import *
from whispersservices.permissions import *


########################################################################################################################
#
#  copyright: 2017 WiM - USGS
#  authors: Aaron Stephenson USGS WiM (Web Informatics and Mapping)
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


class HistoryViewSet(viewsets.ModelViewSet):
    """
    This class will automatically assign the User ID to the created_by and modified_by history fields when appropriate
    """

    permission_classes = (permissions.IsAuthenticated,)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        serializer.save(modified_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(modified_by=self.request.user)


######
#
#  Events
#
######


class EventViewSet(HistoryViewSet):
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


class CountryViewSet(HistoryViewSet):
    queryset = Country.objects.all()
    serializer_class = CountrySerializer


class StateViewSet(HistoryViewSet):
    queryset = State.objects.all()
    serializer_class = StateSerializer


class CountyViewSet(HistoryViewSet):
    queryset = County.objects.all()
    serializer_class = CountySerializer


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


class UserProfileViewSet(HistoryViewSet):
    serializer_class = UserSerializer

    def get_queryset(self):
        # do not return the admin user
        queryset = User.objects.all().exclude(id__exact=1)
        # filter by username, exact
        username = self.request.query_params.get('username', None)
        if username is not None:
            queryset = queryset.filter(username__exact=username)
        return queryset


class AuthView(views.APIView):
    authentication_classes = (authentication.BasicAuthentication,)
    serializer_class = UserSerializer

    def post(self, request):
        return Response(self.serializer_class(request.user).data)


class RoleViewSet(HistoryViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer


class OrganizationViewSet(HistoryViewSet):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer


class ContactViewSet(HistoryViewSet):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer


class GroupViewSet(HistoryViewSet):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer

    '''def get_queryset(self):
        queryset = Group.objects.all()
        owner_list = self.request.query_params.get('owners', None)
        if diagnosis_type is not None:
            diagnosis_type_list = diagnosis_type.split(',')
            queryset = queryset.filter(diagnosis_type__in=diagnosis_type_list)
        return queryset'''


class EventSummaryViewSet(viewsets.ModelViewSet):
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
            queryset = queryset.filter(diagnosis__in=diagnosis_list)
        # filter by diagnosistype ID, exact list
        diagnosistype = self.request.query_params.get('diagnosistype', None)
        if diagnosistype is not None:
            diagnosistype_list = diagnosistype.split(',')
            queryset = queryset.filter(diagnosistype__in=diagnosistype_list)
        # filter by species ID, exact list
        species = self.request.query_params.get('species', None)
        if species is not None:
            species_list = species.split(',')
            queryset = queryset.filter(species__in=species_list)
        # filter by state, exact list
        state = self.request.query_params.get('state', None)
        if state is not None:
            state_list = state.split(',')
            queryset = queryset.filter(state__in=state_list)
        # filter by county, exact list
        county = self.request.query_params.get('county', None)
        if county is not None:
            county_list = county.split(',')
            queryset = queryset.filter(county__in=county_list)
        # filter by flyway, exact list
        flyway = self.request.query_params.get('flyway', None)
        if flyway is not None:
            flyway_list = flyway.split(',')
            queryset = queryset.filter(flyway__in=flyway_list)
        # filter by country, exact list
        country = self.request.query_params.get('country', None)
        if country is not None:
            country_list = country.split(',')
            queryset = queryset.filter(country__in=country_list)
        # filter by affected, exact list
        affected = self.request.query_params.get('affected', None)
        if affected is not None:
            affected_list = affected.split(',')
            queryset = queryset.filter(affected__in=affected_list)
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
