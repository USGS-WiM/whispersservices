from django.urls import path
from django.conf.urls import url, include
from django.contrib.auth import views as auth_views
from django.views.generic.base import TemplateView
from whispersservices import views
from rest_framework.routers import DefaultRouter
from rest_framework.schemas import get_schema_view


router = DefaultRouter()

router.register(r'events', views.EventViewSet, 'events')
router.register(r'eventeventgroups', views.EventEventGroupViewSet, 'eventeventgroups')
router.register(r'eventgroups', views.EventGroupViewSet, 'eventgroups')
router.register(r'eventgroupcategories', views.EventGroupCategoryViewSet, 'eventgroupcategories')
router.register(r'eventsummaries', views.EventSummaryViewSet, 'eventsummaries')
router.register(r'eventdetails', views.EventDetailViewSet, 'eventdetails')
router.register(r'eventtypes', views.EventTypeViewSet, 'eventtypes')
router.register(r'staff', views.StaffViewSet, 'staff')
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
router.register(r'administrativelevelones', views.AdministrativeLevelOneViewSet, 'administrativelevelones')
router.register(r'administrativeleveltwos', views.AdministrativeLevelTwoViewSet, 'administrativeleveltwos')
router.register(r'administrativelevellocalities', views.AdministrativeLevelLocalityViewSet, 'administrativelevellocalities')
router.register(r'landownerships', views.LandOwnershipViewSet, 'landownerships')
router.register(r'eventlocationflyways', views.EventLocationFlywayViewSet, 'eventlocationflyways')
router.register(r'flyways', views.FlywayViewSet, 'flyways')
router.register(r'locationspecies', views.LocationSpeciesViewSet, 'locationspecies')
router.register(r'species', views.SpeciesViewSet, 'species')
router.register(r'agebiases', views.AgeBiasViewSet, 'agebiases')
router.register(r'sexbiases', views.SexBiasViewSet, 'sexbiases')
router.register(r'diagnoses', views.DiagnosisViewSet, 'diagnoses')
router.register(r'diagnosistypes', views.DiagnosisTypeViewSet, 'diagnosistypes')
router.register(r'eventdiagnoses', views.EventDiagnosisViewSet, 'eventdiagnoses')
router.register(r'speciesdiagnoses', views.SpeciesDiagnosisViewSet, 'speciesdiagnoses')
router.register(r'speciesdiagnosisorganizations', views.SpeciesDiagnosisOrganizationViewSet, 'speciesdiagnosisorganizations')
router.register(r'diagnosisbases', views.DiagnosisBasisViewSet, 'diagnosisbases')
router.register(r'diagnosiscauses', views.DiagnosisCauseViewSet, 'diagnosiscauses')
router.register(r'servicerequests', views.ServiceRequestViewSet, 'servicerequests')
router.register(r'servicerequesttypes', views.ServiceRequestTypeViewSet, 'servicerequesttypes')
router.register(r'servicerequestresponses', views.ServiceRequestResponseViewSet, 'servicerequestresponses')
router.register(r'comments', views.CommentViewSet, 'comments')
router.register(r'commenttypes', views.CommentTypeViewSet, 'commenttypes')
router.register(r'artifacts', views.ArtifactViewSet, 'artifacts')
router.register(r'users', views.UserViewSet, 'users')
router.register(r'roles', views.RoleViewSet, 'roles')
router.register(r'rolechangerequests', views.RoleChangeRequestViewSet, 'rolechangerequests')
router.register(r'rolechangerequestresponses', views.RoleChangeRequestResponseViewSet, 'rolechangerequestresponses')
router.register(r'circles', views.CircleViewSet, 'circles')
router.register(r'organizations', views.OrganizationViewSet, 'organizations')
router.register(r'contacts', views.ContactViewSet, 'contacts')
router.register(r'contacttypes', views.ContactTypeViewSet, 'contacttypes')
router.register(r'searches', views.SearchViewSet, 'searches')

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    url(r'^login/$', auth_views.LoginView.as_view(template_name='rest_framework/login.html'), name='login'),
    url(r'^logout/$', auth_views.LogoutView.as_view(), name='logout'),
    path('openapi/', get_schema_view(title="WHISPersServices", description="API for WHISPers"), name='openapi-schema'),
    path('docs/', TemplateView.as_view(template_name='swagger-ui.html',
                                             extra_context={'schema_url': 'openapi-schema'}), name='swagger-ui'),
    path('redocs/', TemplateView.as_view(template_name='redoc.html',
                                        extra_context={'schema_url': 'openapi-schema'}), name='redoc'),
    url(r'^auth/$', views.AuthView.as_view(), name='authenticate'),
]
