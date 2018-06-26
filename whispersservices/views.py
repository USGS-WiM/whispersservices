import datetime as dtmod
from datetime import datetime as dt
from django.utils import timezone
from django.shortcuts import render
from django.db.models import Q
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from rest_framework import views, viewsets, generics, permissions, authentication, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csv_renderers
from drf_renderer_xlsx import renderers as xlsx_renderers
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


PK_REQUESTS = ['retrieve', 'update', 'partial_update', 'destroy']
LIST_DELIMETER = ','

# TODO: figure out how to handle anonymous (unauthenticated) requesters

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


# TODO: implement greater controls over specific actions
# e.g., circle_read members should not be able to update or delete and no circle_write members should be able to delete
# and no regular org partner should be able to delete, only owner or org partner manager(?) or org partner admin
class EventViewSet(HistoryViewSet):
    permission_classes = (DRYPermissions,)
    # queryset = Event.objects.all()
    # serializer_class = EventSerializer

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = self.request.user
        queryset = Event.objects.all()

        # all list requests, and all requests from public users, must only return public data
        if self.action == 'list' or user.role.is_public:
            return queryset.filter(public=True)
        # for all non-admins, non-public data can only be returned to the owner or their org or shared circles
        # and only for primary key requests
        elif self.action in PK_REQUESTS:
            pk = self.request.parser_context['kwargs'].get('pk', None)
            if pk is not None:
                queryset = Event.objects.filter(id=pk)
                obj = queryset[0]
                if obj is not None and (user == obj.created_by or user.organization == obj.created_by.organization
                                        or user in obj.circle_read or user in obj.circle_write
                                        or user.is_superuser or user.role.is_superadmin or user.role.is_admin):
                    return queryset
            return queryset.filter(public=True)
        else:
            return queryset

    # override the default serializer_class to ensure the requester sees only permitted data
    def get_serializer_class(self):
        user = self.request.user
        # all list requests, and all requests from public users, must use the public serializer
        if self.action == 'list' or user.role.is_public:
            return EventPublicSerializer
        # all post requests imply that the requester is the owner, so use the owner serializer
        if self.action == 'create':
            return EventSerializer
        # for all other requests admins have access to all fields
        if user.is_superuser or user.role.is_admin or user.role.is_superadmin:
            return EventAdminSerializer
        # for all non-admins, primary key requests can only be performed by the owner or their org or shared circles
        elif self.action in PK_REQUESTS:
            pk = self.request.parser_context['kwargs'].get('pk', None)
            if pk is not None:
                obj = Event.objects.filter(id=pk).first()
                if obj is not None and (user == obj.created_by or user.organization == obj.created_by.organization
                                        or user in obj.circle_read or user in obj.circle_write):
                    return EventSerializer
            return EventPublicSerializer
        # non-admins and non-owners (and non-owner orgs) must use the public serializer
        else:
            return EventPublicSerializer


# TODO: implement permissions and greater controls over specific actions (this endpoint should be read-only)
class EventDetailViewSet(HistoryViewSet):
    queryset = Event.objects.all()
    serializer_class = EventDetailSerializer


class SuperEventViewSet(HistoryViewSet):
    queryset = SuperEvent.objects.all()
    serializer_class = SuperEventSerializer


class EventTypeViewSet(HistoryViewSet):
    queryset = EventType.objects.all()
    serializer_class = EventTypeSerializer


class StaffViewSet(HistoryViewSet):
    queryset = Staff.objects.all()
    serializer_class = StaffSerializer


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
    # serializer_class = EventOrganizationSerializer

    # override the default serializer_class to ensure the requester sees only permitted data
    def get_serializer_class(self):
        user = self.request.user
        # all list requests, and all requests from public users, must use the public serializer
        if self.action == 'list' or user.role.is_public:
            return EventOrganizationPublicSerializer
        # for all other requests admins have access to all fields
        if user.is_superuser or user.role.is_admin or user.role.is_superadmin:
            return EventOrganizationSerializer
        # for all non-admins, all post requests imply that the requester is the owner, so use the owner serializer
        elif self.action == 'create':
            return EventOrganizationSerializer
        # for all non-admins, requests requiring a primary key can only be performed by the owner or their org
        elif self.action in PK_REQUESTS:
            pk = self.request.parser_context['kwargs'].get('pk', None)
            if pk is not None:
                obj = EventOrganization.objects.filter(id=pk).first()
                if obj is not None and (user == obj.created_by or user.organization == obj.created_by.organization):
                    return EventOrganizationSerializer
            return EventOrganizationPublicSerializer
        # non-admins and non-owners (and non-owner orgs) must use the public serializer
        else:
            return EventOrganizationPublicSerializer


class EventContactViewSet(HistoryViewSet):
    queryset = EventContact.objects.all()
    serializer_class = EventContactSerializer


######
#
#  Locations
#
######


class EventLocationViewSet(HistoryViewSet):
    permission_classes = (DRYPermissions,)
    queryset = EventLocation.objects.all()
    # serializer_class = EventLocationSerializer

# override the default serializer_class to ensure the requester sees only permitted data
    def get_serializer_class(self):
        user = self.request.user
        # all list requests, and all requests from public users, must use the public serializer
        if self.action == 'list' or user.role.is_public:
            return EventLocationPublicSerializer
        # for all other requests admins have access to all fields
        if user.is_superuser or user.role.is_admin or user.role.is_superadmin:
            return EventLocationSerializer
        # for all non-admins, all post requests imply that the requester is the owner, so use the owner serializer
        elif self.action == 'create':
            return EventLocationSerializer
        # for all non-admins, requests requiring a primary key can only be performed by the owner or their org
        elif self.action in PK_REQUESTS:
            pk = self.request.parser_context['kwargs'].get('pk', None)
            if pk is not None:
                obj = EventLocation.objects.filter(id=pk).first()
                if obj is not None and (user == obj.created_by or user.organization == obj.created_by.organization):
                    return EventLocationSerializer
            return EventLocationPublicSerializer
        # non-admins and non-owners (and non-owner orgs) must use the public serializer
        else:
            return EventLocationPublicSerializer


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
    # serializer_class = LocationSpeciesSerializer

    # override the default serializer_class to ensure the requester sees only permitted data
    def get_serializer_class(self):
        user = self.request.user
        # all list requests, and all requests from public users, must use the public serializer
        if self.action == 'list' or user.role.is_public:
            return LocationSpeciesPublicSerializer
        # for all other requests admins have access to all fields
        if user.is_superuser or user.role.is_admin or user.role.is_superadmin:
            return LocationSpeciesSerializer
        # for all non-admins, all post requests imply that the requester is the owner, so use the owner serializer
        elif self.action == 'create':
            return LocationSpeciesSerializer
        # for all non-admins, requests requiring a primary key can only be performed by the owner or their org
        elif self.action in PK_REQUESTS:
            pk = self.request.parser_context['kwargs'].get('pk', None)
            if pk is not None:
                obj = LocationSpecies.objects.filter(id=pk).first()
                if obj is not None and (user == obj.created_by or user.organization == obj.created_by.organization):
                    return LocationSpeciesSerializer
            return LocationSpeciesPublicSerializer
        # non-admins and non-owners (and non-owner orgs) must use the public serializer
        else:
            return LocationSpeciesPublicSerializer


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
    permission_classes = (DRYPermissions,)
    queryset = EventDiagnosis.objects.all()
    # serializer_class = EventDiagnosisSerializer

    # override the default serializer_class to ensure the requester sees only permitted data
    def get_serializer_class(self):
        user = self.request.user
        # all list requests, and all requests from public users, must use the public serializer
        if self.action == 'list' or user.role.is_public:
            return EventDiagnosisPublicSerializer
        # for all other requests admins have access to all fields
        if user.is_superuser or user.role.is_admin or user.role.is_superadmin:
            return EventDiagnosisSerializer
        # for all non-admins, all post requests imply that the requester is the owner, so use the owner serializer
        elif self.action == 'create':
            return EventDiagnosisSerializer
        # for all non-admins, requests requiring a primary key can only be performed by the owner or their org
        elif self.action in PK_REQUESTS:
            pk = self.request.parser_context['kwargs'].get('pk', None)
            if pk is not None:
                obj = EventDiagnosis.objects.filter(id=pk).first()
                if obj is not None and (user == obj.created_by or user.organization == obj.created_by.organization):
                    return EventDiagnosisSerializer
            return EventDiagnosisPublicSerializer
        # non-admins and non-owners (and non-owner orgs) must use the public serializer
        else:
            return EventDiagnosisPublicSerializer


class SpeciesDiagnosisViewSet(HistoryViewSet):
    queryset = SpeciesDiagnosis.objects.all()
    serializer_class = SpeciesDiagnosisSerializer


######
#
#  Misc
#
######


class CommentViewSet(HistoryViewSet):
    # queryset = Comment.objects.all()
    serializer_class = CommentSerializer

    def get_queryset(self):
        queryset = Comment.objects.all()
        contains = self.request.query_params.get('contains', None)
        if contains is not None:
            queryset = queryset.filter(comment__contains=contains)
        return queryset


class CommentTypeViewSet(HistoryViewSet):
    queryset = CommentType.objects.all()
    serializer_class = CommentTypeSerializer


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

    #  override the default serializer_class to ensure the requester sees only permitted data
    # TODO: get_serializer_class(self):

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = self.request.user
        # do not allow a public user to see anything except their own user data
        if user.role.is_public:
            return user
        else:
            # never return the admin user
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


class CircleViewSet(HistoryViewSet):
    queryset = Circle.objects.all()
    serializer_class = CircleSerlializer


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


class SearchViewSet(viewsets.ModelViewSet):
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


# TODO: implement greater controls over specific actions (this endpoint should be read-only)
class EventSummaryViewSet(HistoryViewSet):
    serializer_class = EventSummarySerializer

    # override the default renderers to use a csv or xslx renderer when requested
    def get_renderers(self):
        frmt = self.request.query_params.get('format', None)
        if frmt is not None and frmt == 'csv':
            renderer_classes = (csv_renderers.CSVRenderer,) + tuple(api_settings.DEFAULT_RENDERER_CLASSES)
        elif frmt is not None and frmt == 'xlsx':
            renderer_classes = (xlsx_renderers.XLSXRenderer,) + tuple(api_settings.DEFAULT_RENDERER_CLASSES)
        else:
            renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES)
        return [renderer_class() for renderer_class in renderer_classes]

    # override the default finalize_response to assign a filename to CSV and XLSX files
    # see https://github.com/mjumbewu/django-rest-framework-csv/issues/15
    def finalize_response(self, request, *args, **kwargs):
        response = super(viewsets.ModelViewSet, self).finalize_response(request, *args, **kwargs)
        renderer_format = self.request.accepted_renderer.format
        if renderer_format == 'csv':
            fileextension = '.csv'
        elif renderer_format == 'xlsx':
            fileextension = '.xlsx'
        if renderer_format in ['csv', 'xlsx']:
            filename = 'event_summary_'
            filename += dt.now().strftime("%Y") + '-' + dt.now().strftime("%m") + '-' + dt.now().strftime("%d")
            filename += fileextension
            response['Content-Disposition'] = "attachment; filename=%s" % filename
            response['Access-Control-Expose-Headers'] = 'Content-Disposition'
        return response

    @action(detail=False)
    def user_events(self):
        # if the user is not an admin or public limit data to:
        # what the user owns, what the user's org owns, and what has been shared with the user
        query_params = self.request.query_params
        queryset = self.build_queryset(query_params, get_user_events=True)
        user = self.request.user

        # determine the appropriate serializer to ensure the requester sees only permitted data
        # public users must use the public serializer
        if user.role.is_public:
            serializer = EventSummaryPublicSerializer(data=queryset)
        # admins have access to all fields
        elif user.is_superuser or user.role.is_admin or user.role.is_superadmin:
            serializer = EventSummaryAdminSerializer(data=queryset)
        # partner users can see public fields and event_reference field
        # TODO: figure out how circle fit in here
        elif user.role.is_partner or user.role.is_partnermanager or user.role.is_partneradmin or user.role.is_affiliate:
            serializer = EventSummarySerializer(data=queryset)
        # non-admins and non-owners (and non-owner orgs) must use the public serializer
        else:
            serializer = EventSummaryPublicSerializer(data=queryset)

        return Response(serializer.data, status=200)

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        query_params = self.request.query_params
        return self.build_queryset(query_params, get_user_events=False)

    # build a queryset using query_params
    # NOTE: this is being done in its own method to adhere to the DRY Principle
    def build_queryset(self, query_params, get_user_events):
        user = self.request.user
        queryset = Event.objects.all()

        # non-user-specific event requests can only return public data
        if not get_user_events:
            queryset = queryset.filter(public=True)
        # user-specific event requests can only return data owned by the user or the user's org, or shared with the user
        if get_user_events and not user.is_superuser and not user.role.is_admin and not user.role.is_superadmin:
            queryset = queryset.filter(
                Q(created_by__exact=user) | Q(created_by__organization__exact=user.organization)
                | Q(circle_read__in=user.circles) | Q(circle_write__in=user.circles))

        # TODO: implement this
        # check for params that should use the 'and' operator
        and_params = query_params.get('and_params', None)

        # filter by complete, exact
        complete = query_params.get('complete', None)
        if complete is not None and complete.lower() in ['true', 'false']:
            if complete.lower() == 'true':
                queryset = queryset.filter(complete__exact=True)
            else:
                queryset = queryset.filter(complete__exact=False)
        # filter by event_type ID, exact list
        event_type = query_params.get('event_type', None)
        if event_type is not None:
            if LIST_DELIMETER in event_type:
                event_type_list = event_type.split(',')
                queryset = queryset.filter(event_type__in=event_type_list)
            else:
                queryset = queryset.filter(event_type__exact=event_type)
        # filter by diagnosis ID, exact list
        diagnosis = query_params.get('diagnosis', None)
        if diagnosis is not None:
            if LIST_DELIMETER in diagnosis:
                diagnosis_list = diagnosis.split(',')
                if and_params is not None and 'diagnosis' in and_params:
                    queries = [Q(eventdiagnoses__diagnois__exact=val) for val in diagnosis_list]
                    query = queries.pop()
                    for item in queries:
                        query &= item
                    queryset = queryset.filter(query)
                else:
                    queryset = queryset.prefetch_related('eventdiagnoses').filter(
                        eventdiagnoses__diagnois__in=diagnosis_list)
            else:
                queryset = queryset.filter(eventdiagnoses__diagnois__exact=diagnosis)
        # filter by diagnosistype ID, exact list
        diagnosis_type = query_params.get('diagnosis_type', None)
        if diagnosis_type is not None:
            if LIST_DELIMETER in diagnosis_type:
                diagnosis_type_list = diagnosis_type.split(',')
                if and_params is not None and 'diagnosis_type' in and_params:
                    queries = [Q(eventdiagnoses__diagnois__diagnosis_type__exact=val) for val in diagnosis_type_list]
                    query = queries.pop()
                    for item in queries:
                        query &= item
                    queryset = queryset.filter(query)
                else:
                    queryset = queryset.prefetch_related('eventdiagnoses__diagnois__diagnosis_type').filter(
                        eventdiagnoses__diagnois__diagnosis_type__in=diagnosis_type_list)
            else:
                queryset = queryset.filter(eventdiagnoses__diagnois__diagnosis_type__exact=diagnosis_type)
        # filter by species ID, exact list
        species = query_params.get('species', None)
        if species is not None:
            if LIST_DELIMETER in species:
                species_list = species.split(',')
                if and_params is not None and 'species' in and_params:
                    queries = [Q(eventlocations__locationspecies__species__in=val) for val in species_list]
                    query = queries.pop()
                    for item in queries:
                        query &= item
                    queryset = queryset.filter(query)
                else:
                    queryset = queryset.prefetch_related('eventlocations__locationspecies__species').filter(
                        eventlocations__locationspecies__species__in=species_list)
            else:
                queryset = queryset.filter(eventlocations__locationspecies__species__exact=species)
        # filter by administrative_level_one, exact list
        administrative_level_one = query_params.get('administrative_level_one', None)
        if administrative_level_one is not None:
            if LIST_DELIMETER in administrative_level_one:
                admin_level_one_list = administrative_level_one.split(',')
                if and_params is not None and 'administrative_level_one' in and_params:
                    queries = [Q(eventlocations__administrative_level_one__exact=val) for val in admin_level_one_list]
                    query = queries.pop()
                    for item in queries:
                        query &= item
                    queryset = queryset.filter(query)
                else:
                    queryset = queryset.prefetch_related('eventlocations__administrative_level_one').filter(
                        eventlocations__administrative_level_one__in=admin_level_one_list)
            else:
                queryset = queryset.filter(eventlocations__administrative_level_one__exact=administrative_level_one)
        # filter by administrative_level_two, exact list
        administrative_level_two = query_params.get('administrative_level_two', None)
        if administrative_level_two is not None:
            if LIST_DELIMETER in administrative_level_two:
                admin_level_two_list = administrative_level_two.split(',')
                if and_params is not None and 'administrative_level_two' in and_params:
                    queries = [Q(eventlocations__administrative_level_two__exact=val) for val in admin_level_two_list]
                    query = queries.pop()
                    for item in queries:
                        query &= item
                    queryset = queryset.filter(query)
                else:
                    queryset = queryset.prefetch_related('eventlocations__administrative_level_two').filter(
                        eventlocations__administrative_level_two__in=admin_level_two_list)
            else:
                queryset = queryset.filter(eventlocations__administrative_level_two__exact=administrative_level_two)
        # filter by flyway, exact list
        flyway = query_params.get('flyway', None)
        if flyway is not None:
            queryset = queryset.prefetch_related('')
            if LIST_DELIMETER in flyway:
                flyway_list = flyway.split(',')
                queryset = queryset.filter(eventlocations__flyway__in=flyway_list)
            else:
                queryset = queryset.filter(eventlocations__flyway__exact=flyway)
        # filter by country, exact list
        country = query_params.get('country', None)
        if country is not None:
            queryset = queryset.prefetch_related('')
            if LIST_DELIMETER in country:
                country_list = country.split(',')
                queryset = queryset.filter(eventlocations__country__in=country_list)
            else:
                queryset = queryset.filter(eventlocations__country__exact=country)
        # filter by affected, exact list
        affected_count = query_params.get('affected_count', None)
        if affected_count is not None:
            queryset = queryset.prefetch_related('')
            if LIST_DELIMETER in affected_count:
                affected_count_list = affected_count.split(',')
                queryset = queryset.filter(affected_count__in=affected_count_list)
            else:
                queryset = queryset.filter(affected_count__exact=affected_count)
        # filter by start and end date (after only, before only, or between both, depending on which URL params appear)
        # the date filters below are date-exclusive
        startdate = query_params.get('startdate', None)
        enddate = query_params.get('enddate', None)
        if startdate is not None and enddate is not None:
            queryset = queryset.filter(start_date__gt=startdate, end_date__lt=enddate)
        elif startdate is not None:
            queryset = queryset.filter(start_date__gt=startdate)
        elif enddate is not None:
            queryset = queryset.filter(end_date__lt=enddate)
        # TODO: determine the intended use of the following three query params
        # because only admins or fellow org or circle members should even be able to filter on these values
        # perhaps these should instead be used implicitly based on the requester
        # (query will auto-filter based on the requester's ID/org/circle properties)
        # rather than something a requester explicitly queries?
        # # filter by owner ID, exact
        # owner = query_params.get('owner', None)
        # if owner is not None:
        #     queryset = queryset.filter(created_by__exact=owner)
        # # filter by ownerorg ID, exact
        # owner_org = query_params.get('owner_org', None)
        # if owner_org is not None:
        #     queryset = queryset.prefetch_related('created_by__organization')
        #     queryset = queryset.filter(created_by__organization__exact=owner_org)
        # # filter by circle ID, exact
        # TODO: this might need to be changed to select only events where the user is in a circle attached to this event
        # rather than the current set up where any circle ID can be used
        # circle = query_params.get('circle', None)
        # if circle is not None:
        #     queryset = queryset.filter(Q(circle_read__exact=circle) | Q(circle_write__exact=circle))
        return queryset
