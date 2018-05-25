from django.conf.urls import url, include
from whispersservices import views
from rest_framework.routers import DefaultRouter


router = DefaultRouter()

router.register(r'events', views.EventViewSet, 'events')
router.register(r'eventsummaries', views.EventSummaryViewSet, 'eventsummaries')
router.register(r'eventdetails', views.EventDetailViewSet, 'eventdetails')
router.register(r'eventtypes', views.EventTypeViewSet, 'eventtypes')
router.register(r'epistaff', views.EpiStaffViewSet, 'epistaff')
router.register(r'legalstatuses', views.LegalStatusViewSet, 'legalstatuses')
router.register(r'eventstatuses', views.EventStatusViewSet, 'eventstatuses')
router.register(r'eventabstracts', views.EventAbstractViewSet, 'eventabstracts')
router.register(r'eventcases', views.EventCaseViewSet, 'eventcases')
router.register(r'eventlabsites', views.EventLabsiteViewSet, 'eventlabsites')
router.register(r'eventorganizations', views.EventOrganizationViewSet, 'eventorganizations')
router.register(r'eventcontacts', views.EventContactViewSet, 'eventcontacts')
router.register(r'eventlocations', views.EventLocationViewSet, 'eventlocations')
router.register(r'eventlocationcontacts', views.EventLocationContactViewSet, 'eventlocationcontacts')
router.register(r'countries', views.CountryViewSet, 'countries')
router.register(r'states', views.StateViewSet, 'states')
router.register(r'administrativelevelone', views.AdministrativeLevelOneViewSet, 'administrativelevelone')
router.register(r'counties', views.CountyViewSet, 'counties')
router.register(r'administrativeleveltwo', views.AdministrativeLevelTwoViewSet, 'administrativeleveltwo')
router.register(r'landownerships', views.LandOwnershipViewSet, 'landownerships')
router.register(r'locationspecies', views.LocationSpeciesViewSet, 'locationspecies')
router.register(r'species', views.SpeciesViewSet, 'species')
router.register(r'agebiases', views.AgeBiasViewSet, 'agebiases')
router.register(r'sexbiases', views.SexBiasViewSet, 'sexbiases')
router.register(r'diagnoses', views.DiagnosisViewSet, 'diagnoses')
router.register(r'diagnosistypes', views.DiagnosisTypeViewSet, 'diagnosistypes')
router.register(r'eventdiagnoses', views.EventDiagnosisViewSet, 'eventdiagnoses')
router.register(r'speciesdiagnoses', views.SpeciesDiagnosisViewSet, 'speciesdiagnoses')
router.register(r'permissions', views.PermissionViewSet, 'permissions')
router.register(r'permissiontypes', views.PermissionTypeViewSet, 'permissiontypes')
router.register(r'comments', views.CommentViewSet, 'comments')
router.register(r'artifacts', views.ArtifactViewSet, 'artifacts')
router.register(r'users', views.UserProfileViewSet, 'users')
router.register(r'roles', views.RoleViewSet, 'roles')
router.register(r'organizations', views.OrganizationViewSet, 'organizations')
router.register(r'contacts', views.ContactViewSet, 'contacts')
router.register(r'groups', views.GroupViewSet, 'groups')
router.register(r'searches', views.SearchViewSet, 'searches')

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    url(r'^auth/$', views.AuthView.as_view(), name='authenticate')
]
