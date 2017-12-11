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
    queryset = EventAbstract.objects.all()
    serializer_class = EventAbstractSerializer


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
    queryset = Diagnosis.objects.all()
    serializer_class = DiagnosisSerializer


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
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer


class ArtifactViewSet(HistoryViewSet):
    queryset = Artifact.objects.all()
    serializer_class = ArtifactSerializer


######
#
#  Users
#
######


class UserProfileViewSet(HistoryViewSet):
    serializer_class = UserProfileSerializer

    def get_queryset(self):
        # do not return the admin user
        queryset = UserProfile.objects.all().exclude(id__exact=1)
        # filter by username, exact
        username = self.request.query_params.get('username', None)
        if username is not None:
            queryset = queryset.filter(username__exact=username)
        return queryset


class AuthView(views.APIView):
    authentication_classes = (authentication.BasicAuthentication,)
    serializer_class = UserProfileSerializer

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
