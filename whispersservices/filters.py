from django.db.models import Count, Q
from django_filters.rest_framework import DjangoFilterBackend, FilterSet, BaseInFilter, NumberFilter, CharFilter, BooleanFilter, ChoiceFilter, DateRangeFilter
from django_filters.widgets import BooleanWidget
from rest_framework.exceptions import PermissionDenied, NotFound
from whispersservices.models import *
from whispersservices.field_descriptions import *


PK_REQUESTS = ['retrieve', 'update', 'partial_update', 'destroy']
LIST_DELIMITER = ','


class NumberInFilter(BaseInFilter, NumberFilter):
    pass


class EmptyBooleanWidget(BooleanWidget):
    def value_from_datadict(self, data, files, name):
        value = data.get(name, None)
        if isinstance(value, str):
            value = value.lower()

        return {
            '1': True,
            '0': False,
            'true': True,
            'false': False,
            True: True,
            False: False,
            None: True
        }.get(value, None)


class EventAbstractFilter(FilterSet):
    contains = CharFilter(field_name='text', lookup_expr='contains', label='Filter by string contained in event abstract text')

    class Meta:
        model: EventAbstract
        fields = ['contains', ]


class AdministrativeLevelOneFilter(FilterSet):
    country = NumberInFilter(field_name='country', lookup_expr='in', label='Filter by country ID (or a list of country IDs)')

    class Meta:
        model: AdministrativeLevelOne
        fields = ['country', ]


class AdministrativeLevelTwoFilter(FilterSet):
    administrativelevelone = NumberInFilter(field_name='administrative_level_one', lookup_expr='in', label='Filter by administrative level one (e.g., state or province) ID (or a list of administrative level one IDs)')

    class Meta:
        model: AdministrativeLevelOne
        fields = ['administrativelevelone', ]


class DiagnosisFilter(FilterSet):
    diagnosis_type = NumberInFilter(field_name='diagnosis_type', lookup_expr='in', label='Filter by diagnosis type ID (or a list of diagnosis type IDs)')

    class Meta:
        model: Diagnosis
        fields = ['diagnosis_type', ]


class NotificationFilter(FilterSet):
    all = BooleanFilter(field_name='recipient', widget=EmptyBooleanWidget(), label='Return all notifications (mutually exclusive with "recipient" query parameter)')
    recipient = NumberInFilter(field_name='recipient', lookup_expr='in', label='Filter by recipient user ID (or a list of recipient user IDs) (mutually exclusive with "all" query parameter)')

    @property
    def qs(self):
        parent = super().qs
        user = getattr(self.request, 'user', None)

        # anonymous users cannot see anything
        if not user or not user.is_authenticated:
            return parent.none()
        # public users cannot see anything
        elif user.role.is_public:
            return parent.none()
        # admins and superadmins can see notifications that belong to anyone (if they use the 'recipient' query param)
        # or everyone (if they use the 'all' query param, or get a single one), but default to just getting their own

        elif user.role.is_superadmin or user.role.is_admin:
            parser_context = getattr(self.request, 'parser_context', None)
            if parser_context:
                action = parser_context['kwargs'].get('action', None)
                if action in PK_REQUESTS:
                    pk = self.request.parser_context['kwargs'].get('pk', None)
                    if pk is not None and pk.isdigit():
                        return Notification.objects.filter(id=pk).order_by('-id')
                    raise NotFound
                pass
            get_all = True if self.request is not None and 'all' in self.request.query_params else False
            if get_all:
                return parent.all().order_by('-id')
            else:
                recipient = self.request.query_params.get('recipient', None) if self.request else None
                if recipient is not None and recipient != '':
                    if LIST_DELIMITER in recipient:
                        recipient_list = recipient.split(',')
                        return Notification.objects.filter(recipient__in=recipient_list).order_by('-id')
                    else:
                        return Notification.objects.filter(recipient__exact=recipient).order_by('-id')
                else:
                    return Notification.objects.filter(recipient__exact=user.id).order_by('-id')
        # otherwise return only what belongs to the user
        else:
            return Notification.objects.filter(recipient__exact=user.id).order_by('-id')

    class Meta:
        model: Notification
        fields = ['all', 'recipient', ]


class CommentFilter(FilterSet):
    contains = CharFilter(field_name='comment', lookup_expr='icontains')

    @property
    def qs(self):
        parent = super().qs
        user = getattr(self.request, 'user', None)

        # all requests from anonymous or public users return nothing
        if not user or not user.is_authenticated or user.role.is_public:
            return parent.none()
        # admins and superadmins can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = parent.all()
        # partners can see comments owned by the user or user's org
        elif user.role.is_affiliate or user.role.is_partner or user.role.is_partnermanager or user.role.is_partneradmin:
            # they can also see comments for events on which they are collaborators:
            collab_evt_ids = list(Event.objects.filter(
                Q(eventwriteusers__user__in=[user.id, ]) | Q(eventreadusers__user__in=[user.id, ])
            ).values_list('id', flat=True))
            collab_evtloc_ids = list(EventLocation.objects.filter(
                event__in=collab_evt_ids).values_list('id', flat=True))
            collab_evtgrp_ids = list(set(list(EventEventGroup.objects.filter(
                event__in=collab_evt_ids).values_list('eventgroup', flat=True))))
            collab_srvreq_ids = list(ServiceRequest.objects.filter(
                event__in=collab_evt_ids).values_list('id', flat=True))
            return Comment.objects.filter(
                Q(created_by__exact=user.id) |
                Q(created_by__organization__exact=user.organization) |
                Q(created_by__organization__in=user.child_organizations) |
                Q(content_type__model='event', object_id__in=collab_evt_ids) |
                Q(content_type__model='eventlocation', object_id__in=collab_evtloc_ids) |
                Q(content_type__model='eventgroup', object_id__in=collab_evtgrp_ids) |
                Q(content_type__model='servicerequest', object_id__in=collab_srvreq_ids)
            )
        # otherwise return nothing
        else:
            return parent.none()

    class Meta:
        model: Comment
        fields = ['contains', ]


class UserFilter(FilterSet):
    username = CharFilter(field_name='username', lookup_expr='exact')
    email = CharFilter(field_name='email', lookup_expr='exact')
    role = CharFilter(field_name='role', lookup_expr='exact')
    organization = CharFilter(field_name='organization', lookup_expr='exact')

    @property
    def qs(self):
        parent = super().qs
        user = getattr(self.request, 'user', None)

        # anonymous users cannot see anything
        if not user or not user.is_authenticated:
            return parent.none()
        # admins and superadmins can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = parent.all()
        # public and partner users can only see themselves
        elif user.role.is_public or user.role.is_affiliate or user.role.is_partner or user.role.is_partnermanager:
            return User.objects.filter(pk=user.id)
        # partneradmin can see data owned by the user or user's org
        elif user.role.is_partneradmin:
            return User.objects.all().filter(Q(id__exact=user.id) | Q(organization__exact=user.organization) | Q(
                organization__in=user.organization.child_organizations))
        # otherwise return nothing
        else:
            return parent.none()

    class Meta:
        model: User
        fields = ['username', 'email', 'role', 'organization', ]


class OrganizationFilter(FilterSet):
    users = CharFilter(field_name='users', lookup_expr='exact')
    contacts = CharFilter(field_name='contacts', lookup_expr='exact')
    laboratory = CharFilter(field_name='laboratory', lookup_expr='exact')

    class Meta:
        model: User
        fields = ['user', 'contacts', 'laboratory', ]


class ContactFilter(FilterSet):
    org = NumberInFilter(field_name='organization', lookup_expr='in')
    ownerorg = NumberInFilter(field_name='owner_organization', lookup_expr='in')

    class Meta:
        model: User
        fields = ['org', 'ownerorg', ]


class SearchFilter(FilterSet):
    org = NumberInFilter(field_name='organization', lookup_expr='in')

    class Meta:
        model: Search
        fields = ['org', ]


# # TODO: improve labels such that only unique fields (like affected_count__gte) have string literal values,
#     while all other labels (like diagnosis) are assigned to variables
#       e.g., complete = BooleanFilter(field_name='complete', lookup_expr='exact', label=event.complete)
class EventSummaryFilter(FilterSet):
    # TODO: properly set these choices (need to be tuples)
    AND_PARAMS = (('diagnosis', 'diagnosis'), ('diagnosis_type', 'diagnosis_type'), ('species', 'species'), ('administrative_level_one', 'administrative_level_one'), ('administrative_level_two', 'administrative_level_two'), )
    PERMISSION_SOURCES = (('own', 'own'), ('organization', 'organization'), ('collaboration', 'collaboration'), )

    # do nothing, as this query param is not an independent filter on any fields,
    #  but a 'meta' filter for changing how other filters are used in combination
    #  (the default is always 'filter by field x where value is y OR z',
    #   but we want to allow for 'filter by field x where value is y AND z')
    def filter_and_params(self, queryset, name, value):
        return queryset

    # filter by permission_source, exact list
    def filter_permission_sources(self, queryset, name, value):
        user = getattr(self.request, 'user', None)
        if value is not None and value != '':
            permission_source_list = value.split(',')
            if ('own' in permission_source_list and 'organization' in permission_source_list
                    and 'collaboration' in permission_source_list):
                queryset = queryset.filter(
                    Q(created_by=user.id) | Q(created_by__organization=user.organization.id) | Q(
                        created_by__organization__in=user.organization.child_organizations) | Q(
                        read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])).distinct()
            elif 'own' in permission_source_list and 'organization' in permission_source_list:
                queryset = queryset.filter(
                    Q(created_by=user.id) | Q(created_by__organization=user.organization.id) | Q(
                        created_by__organization__in=user.organization.child_organizations)).distinct()
            elif 'own' in permission_source_list and 'collaboration' in permission_source_list:
                queryset = queryset.filter(
                    Q(created_by=user.id) | Q(read_collaborators__in=[user.id]) | Q(
                        write_collaborators__in=[user.id])).distinct()
            elif 'organization' in permission_source_list and 'collaboration' in permission_source_list:
                queryset = queryset.filter(Q(created_by__organization=user.organization.id) | Q(
                    created_by__organization__in=user.organization.child_organizations) | Q(
                    read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])).exclude(
                    created_by=user.id).distinct()
            elif 'own' in permission_source_list:
                queryset = queryset.filter(created_by=user.id)
            elif 'organization' in permission_source_list:
                queryset = queryset.filter(Q(created_by__organization=user.organization.id) | Q(
                    created_by__organization__in=user.organization.child_organizations)).exclude(
                    created_by=user.id).distinct()
            elif 'collaboration' in permission_source_list:
                queryset = queryset.filter(
                    Q(read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])).distinct()
        return queryset

    # filter by diagnosis ID, exact list
    def filter_diagnosis(self, queryset, name, value):
        if value is not None and value != '':
            if LIST_DELIMITER in value:
                diagnosis_list = value.split(',')
                queryset = queryset.prefetch_related('eventdiagnoses').filter(
                    eventdiagnoses__diagnosis__in=diagnosis_list).distinct()
                parser_context = getattr(self.request, 'parser_context', None)
                and_params = parser_context['kwargs'].get('and_params', None) if parser_context else None
                if and_params is not None and 'diagnosis' in and_params:
                    # first, count the species for each returned event
                    # and only allow those with the same or greater count as the length of the query_param list
                    queryset = queryset.annotate(count_diagnoses=Count(
                        'eventdiagnoses__diagnosis', distinct=True)).filter(
                        count_diagnoses__gte=len(diagnosis_list))
                    diagnosis_list_ints = [int(i) for i in diagnosis_list]
                    # next, find only the events that have _all_ the requested values, not just any of them
                    for item in queryset:
                        evtdiags = EventDiagnosis.objects.filter(event_id=item.id)
                        all_diagnoses = [evtdiag.diagnosis.id for evtdiag in evtdiags]
                        if not set(diagnosis_list_ints).issubset(set(all_diagnoses)):
                            queryset = queryset.exclude(pk=item.id)
            else:
                queryset = queryset.filter(eventdiagnoses__diagnosis__exact=value).distinct()
        return queryset

    # filter by filter_diagnosis_type ID, exact list
    def filter_diagnosis_type(self, queryset, name, value):
        if value is not None and value != '':
            if LIST_DELIMITER in value:
                diagnosis_type_list = value.split(',')
                queryset = queryset.prefetch_related('eventdiagnoses__diagnosis__diagnosis_type').filter(
                    eventdiagnoses__diagnosis__diagnosis_type__in=diagnosis_type_list).distinct()
                parser_context = getattr(self.request, 'parser_context', None)
                and_params = parser_context['kwargs'].get('and_params', None) if parser_context else None
                if and_params is not None and 'diagnosis_type' in and_params:
                    # first, count the species for each returned event
                    # and only allow those with the same or greater count as the length of the query_param list
                    queryset = queryset.annotate(count_diagnosis_types=Count(
                        'eventdiagnoses__diagnosis__diagnosis_type', distinct=True)).filter(
                        count_diagnosis_types__gte=len(diagnosis_type_list))
                    diagnosis_type_list_ints = [int(i) for i in diagnosis_type_list]
                    # next, find only the events that have _all_ the requested values, not just any of them
                    for item in queryset:
                        evtdiags = EventDiagnosis.objects.filter(event_id=item.id)
                        all_diagnosis_types = [evtdiag.diagnosis.diagnosis_type.id for evtdiag in evtdiags]
                        if not set(diagnosis_type_list_ints).issubset(set(all_diagnosis_types)):
                            queryset = queryset.exclude(pk=item.id)
            else:
                queryset = queryset.filter(eventdiagnoses__diagnosis__diagnosis_type__exact=value).distinct()
        return queryset

    # filter by species ID, exact list
    def filter_species(self, queryset, name, value):
        if value is not None and value != '':
            if LIST_DELIMITER in value:
                species_list = value.split(',')
                queryset = queryset.prefetch_related('eventlocations__locationspecies__species').filter(
                    eventlocations__locationspecies__species__in=species_list).distinct()
                parser_context = getattr(self.request, 'parser_context', None)
                and_params = parser_context['kwargs'].get('and_params', None) if parser_context else None
                if and_params is not None and 'species' in and_params:
                    # first, count the species for each returned event
                    # and only allow those with the same or greater count as the length of the query_param list
                    queryset = queryset.annotate(count_species=Count(
                        'eventlocations__locationspecies__species')).filter(count_species__gte=len(species_list))
                    species_list_ints = [int(i) for i in species_list]
                    # next, find only the events that have _all_ the requested values, not just any of them
                    for item in queryset:
                        evtlocs = EventLocation.objects.filter(event_id=item.id)
                        locspecs = LocationSpecies.objects.filter(event_location__in=evtlocs)
                        all_species = [locspec.species.id for locspec in locspecs]
                        if not set(species_list_ints).issubset(set(all_species)):
                            queryset = queryset.exclude(pk=item.id)
            else:
                queryset = queryset.filter(eventlocations__locationspecies__species__exact=value).distinct()
        return queryset

    # filter by administrative_level_one, exact list
    def filter_administrative_level_one(self, queryset, name, value):
        if value is not None and value != '':
            if LIST_DELIMITER in value:
                admin_level_one_list = value.split(',')
                queryset = queryset.prefetch_related('eventlocations__administrative_level_two').filter(
                    eventlocations__administrative_level_one__in=admin_level_one_list).distinct()
                parser_context = getattr(self.request, 'parser_context', None)
                and_params = parser_context['kwargs'].get('and_params', None) if parser_context else None
                if and_params is not None and 'administrative_level_one' in and_params:
                    # this _should_ be fairly straight forward with the postgresql ArrayAgg function,
                    # (which would offload the hard work to postgresql and make this whole operation faster)
                    # but that function is just throwing an error about a Serial data type,
                    # so the following is a work-around

                    # first, count the eventlocations for each returned event
                    # and only allow those with the same or greater count as the length of the query_param list
                    queryset = queryset.annotate(
                        count_evtlocs=Count('eventlocations')).filter(count_evtlocs__gte=len(admin_level_one_list))
                    admin_level_one_list_ints = [int(i) for i in admin_level_one_list]
                    # next, find only the events that have _all_ the requested values, not just any of them
                    for item in queryset:
                        evtlocs = EventLocation.objects.filter(event_id=item.id)
                        all_a1s = [evtloc.administrative_level_one.id for evtloc in evtlocs]
                        if not set(admin_level_one_list_ints).issubset(set(all_a1s)):
                            queryset = queryset.exclude(pk=item.id)
            else:
                queryset = queryset.filter(
                    eventlocations__administrative_level_one__exact=value).distinct()
        return queryset

    # filter by administrative_level_two, exact list
    def filter_administrative_level_two(self, queryset, name, value):
        if value is not None and value != '':
            if LIST_DELIMITER in value:
                admin_level_two_list = value.split(',')
                queryset = queryset.prefetch_related('eventlocations__administrative_level_two').filter(
                    eventlocations__administrative_level_two__in=admin_level_two_list).distinct()
                parser_context = getattr(self.request, 'parser_context', None)
                and_params = parser_context['kwargs'].get('and_params', None) if parser_context else None
                if and_params is not None and 'administrative_level_two' in and_params:
                    # first, count the eventlocations for each returned event
                    # and only allow those with the same or greater count as the length of the query_param list
                    queryset = queryset.annotate(
                        count_evtlocs=Count('eventlocations')).filter(count_evtlocs__gte=len(admin_level_two_list))
                    admin_level_two_list_ints = [int(i) for i in admin_level_two_list]
                    # next, find only the events that have _all_ the requested values, not just any of them
                    for item in queryset:
                        evtlocs = EventLocation.objects.filter(event_id=item.id)
                        all_a2s = [evtloc.administrative_level_two.id for evtloc in evtlocs]
                        if not set(admin_level_two_list_ints).issubset(set(all_a2s)):
                            queryset = queryset.exclude(pk=item.id)
            else:
                queryset = queryset.filter(
                    eventlocations__administrative_level_two__exact=value).distinct()
        return queryset

    # filter by start and end date (after only, before only, or between both, depending on which URL params appear)
    # the date filters below are date-inclusive, per cooperator instructions
    def filter_start_end_date(self, queryset, name, value):
        query_params = getattr(self.request, 'query_params', None)
        if name == 'start_date':
            start_date = value
            end_date = query_params.get('end_date', None)
        else:
            end_date = value
            start_date = query_params.get('start_date', None)
        if start_date is not None and end_date is not None:
            queryset = queryset.filter(
                Q(start_date__lte=start_date, end_date__gte=start_date)
                | Q(start_date__gte=start_date, start_date__lte=end_date)
            )
        elif start_date is not None and end_date is None:
            queryset = queryset.filter(
                Q(start_date__lte=start_date, end_date__gte=start_date)
                | Q(start_date__lte=start_date, end_date__isnull=True)
                | Q(start_date__gte=start_date, start_date__lte=Now())
            )
        elif start_date is None and end_date is not None:
            queryset = queryset.filter(start_date__lte=end_date)
        return queryset

    and_params = ChoiceFilter(choices=AND_PARAMS, method=filter_and_params)
    complete = BooleanFilter()
    public = BooleanFilter()
    permission_source = ChoiceFilter(choices=PERMISSION_SOURCES, method=filter_permission_sources)
    event_type = NumberInFilter(lookup_expr='in')
    diagnosis = NumberInFilter(method=filter_diagnosis)
    diagnosis_type = NumberInFilter(method=filter_diagnosis_type)
    species = NumberInFilter(method=filter_species)
    administrative_level_one = NumberInFilter(method=filter_administrative_level_one)
    administrative_level_two = NumberInFilter(method=filter_administrative_level_two)
    flyway = NumberInFilter(field_name='eventlocations__flyway', lookup_expr='in')
    country = NumberInFilter(field_name='eventlocations__country', lookup_expr='in')
    gnis_id = NumberInFilter(field_name='eventlocations__gnis_id', lookup_expr='in')
    affected_count__gte = NumberFilter(field_name='affected_count', lookup_expr='gte')
    affected_count__lte = NumberFilter(field_name='affected_count', lookup_expr='lte')
    start_date = DateRangeFilter(method='filter_start_date')
    end_date = DateRangeFilter(method='filter_end_date')

    class Meta:
        model = Event
        fields = ['and_params', 'complete', 'public', 'permission_source', 'event_type', 'diagnosis', 'diagnosis_type',
                  'species', 'administrative_level_one', 'administrative_level_two', 'flyway', 'country', 'gnis_id',
                  'affected_count__gte', 'affected_count__lte', 'start_date', 'end_date', ]
