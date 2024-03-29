from django.db.models import Count
from django.db.models.functions import Now
from django_filters.rest_framework import FilterSet, BaseInFilter, NumberFilter, CharFilter, BooleanFilter, MultipleChoiceFilter, DateFilter
from django_filters.widgets import BooleanWidget
from rest_framework.exceptions import NotFound
from whispersapi.models import *
from whispersapi.field_descriptions import *


PK_REQUESTS = ['retrieve', 'update', 'partial_update', 'destroy']
LIST_DELIMITER = ','


class NumberInFilter(BaseInFilter, NumberFilter):
    pass


class CharInFilter(BaseInFilter, CharFilter):
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
    contains = CharFilter(field_name='text', lookup_expr='icontains', label='Filter by string contained in event abstract text, not case-sensitive')

    class Meta:
        model = EventAbstract
        fields = ['contains', ]


class AdministrativeLevelOneFilter(FilterSet):
    country = NumberInFilter(field_name='country', lookup_expr='in', label='Filter by country ID (or a list of country IDs)')

    class Meta:
        model = AdministrativeLevelOne
        fields = ['country', ]


class AdministrativeLevelTwoFilter(FilterSet):
    administrativelevelone = NumberInFilter(field_name='administrative_level_one', lookup_expr='in', label='Filter by administrative level one (e.g., state or province) ID (or a list of administrative level one IDs)')

    class Meta:
        model = AdministrativeLevelTwo
        fields = ['administrativelevelone', ]


class DiagnosisFilter(FilterSet):
    diagnosis_type = NumberInFilter(field_name='diagnosis_type', lookup_expr='in', label='Filter by diagnosis type ID (or a list of diagnosis type IDs)')

    class Meta:
        model = Diagnosis
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
        model = Notification
        fields = ['all', 'recipient', ]


class CommentFilter(FilterSet):
    contains = CharFilter(field_name='comment', lookup_expr='icontains', label='Filter by string contained in comment text, not case-sensitive')

    class Meta:
        model = Comment
        fields = ['contains', ]


class UserFilter(FilterSet):
    username = CharFilter(field_name='username', lookup_expr='exact', label='Filter by username, exact match')
    email = CharFilter(field_name='email', lookup_expr='iexact', label='Filter by email, exact match')
    role = NumberInFilter(field_name='role', lookup_expr='in', label='Filter by role ID (or a list of role IDs)')
    organization = NumberInFilter(field_name='organization', lookup_expr='in', label='Filter by organization ID (or a list of organization IDs)')

    class Meta:
        model = User
        fields = ['username', 'email', 'role', 'organization', ]


class OrganizationFilter(FilterSet):
    users = NumberInFilter(field_name='users', lookup_expr='in', label='Filter by user ID (or a list of user IDs)')
    contacts = NumberInFilter(field_name='contacts', lookup_expr='in', label='Filter by contact ID (or a list of contact IDs)')
    laboratory = BooleanFilter(label='Filter by whether organization is a laboratory or not')
    active = BooleanFilter(label='Filter by whether organization is active or not')

    class Meta:
        model = Organization
        fields = ['users', 'contacts', 'laboratory', 'active',]


class ContactFilter(FilterSet):
    org = NumberInFilter(field_name='organization', lookup_expr='in', label='Filter by organization ID (or a list of organization IDs)')
    ownerorg = NumberInFilter(field_name='owner_organization', lookup_expr='in', label='Filter by owner organization ID (or a list of owner organization IDs)')
    active = BooleanFilter(label='Filter by whether contact is active or not')

    class Meta:
        model = Contact
        fields = ['org', 'ownerorg', 'active', ]


class SearchFilter(FilterSet):
    org = NumberInFilter(field_name='organization', lookup_expr='in', label='Filter by organization ID (or a list of organization IDs)')

    class Meta:
        model = Search
        fields = ['org', ]


# # TODO: improve labels such that only unique fields (like affected_count__gte) have string literal values,
#     while all other labels (like diagnosis) are assigned to variables
#       e.g., complete = BooleanFilter(field_name='complete', lookup_expr='exact', label=event.complete)
class EventSummaryFilter(FilterSet):
    AND_PARAMS_ENUM = (('diagnosis', 'diagnosis'), ('diagnosis_type', 'diagnosis_type'), ('species', 'species'),
                       ('administrative_level_one', 'administrative_level_one'),
                       ('administrative_level_two', 'administrative_level_two'),
                       )
    PERMISSION_SOURCES_ENUM = (('own', 'own'), ('organization', 'organization'), ('collaboration', 'collaboration'), )

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
            if isinstance(value, list):
                value = ','.join([str(x) for x in value if x is not None])
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
            if isinstance(value, list):
                value = ','.join([str(x) for x in value if x is not None])
            if LIST_DELIMITER in value:
                diagnosis_list = value.split(',')
                queryset = queryset.prefetch_related('eventdiagnoses').filter(
                    eventdiagnoses__diagnosis__in=diagnosis_list).distinct()
                parser_context = getattr(self.request, 'parser_context', None)
                and_params = parser_context['request'].query_params.get('and_params', None) if parser_context else None
                if and_params is not None and 'diagnosis' in and_params:
                    # first, count the species for each returned event
                    # and only allow those with the same or greater count as the length of the query_param list
                    # use the 'only' operator to avoid PostgreSQL GROUP BY errors in annotation aggregation
                    queryset = queryset.annotate(count_diagnoses=Count(
                        'eventdiagnoses__diagnosis', distinct=True)).filter(
                        count_diagnoses__gte=len(diagnosis_list)).only('id')
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
            if isinstance(value, list):
                value = ','.join([str(x) for x in value if x is not None])
            if LIST_DELIMITER in value:
                diagnosis_type_list = value.split(',')
                queryset = queryset.prefetch_related('eventdiagnoses__diagnosis__diagnosis_type').filter(
                    eventdiagnoses__diagnosis__diagnosis_type__in=diagnosis_type_list).distinct()
                parser_context = getattr(self.request, 'parser_context', None)
                and_params = parser_context['request'].query_params.get('and_params', None) if parser_context else None
                if and_params is not None and 'diagnosis_type' in and_params:
                    # first, count the species for each returned event
                    # and only allow those with the same or greater count as the length of the query_param list
                    # use the 'only' operator to avoid PostgreSQL GROUP BY errors in annotation aggregation
                    queryset = queryset.annotate(count_diagnosis_types=Count(
                        'eventdiagnoses__diagnosis__diagnosis_type', distinct=True)).filter(
                        count_diagnosis_types__gte=len(diagnosis_type_list)).only('id')
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
            if isinstance(value, list):
                value = ','.join([str(x) for x in value if x is not None])
            if LIST_DELIMITER in value:
                species_list = value.split(',')
                queryset = queryset.prefetch_related('eventlocations__locationspecies__species').filter(
                    eventlocations__locationspecies__species__in=species_list).distinct()
                parser_context = getattr(self.request, 'parser_context', None)
                and_params = parser_context['request'].query_params.get('and_params', None) if parser_context else None
                if and_params is not None and 'species' in and_params:
                    # first, count the species for each returned event
                    # and only allow those with the same or greater count as the length of the query_param list
                    # use the 'only' operator to avoid PostgreSQL GROUP BY errors in annotation aggregation
                    queryset = queryset.annotate(count_species=Count(
                        'eventlocations__locationspecies__species')).filter(
                        count_species__gte=len(species_list)).only('id')
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
            if isinstance(value, list):
                value = ','.join([str(x) for x in value if x is not None])
            if LIST_DELIMITER in value:
                admin_level_one_list = value.split(',')
                queryset = queryset.prefetch_related('eventlocations__administrative_level_two').filter(
                    eventlocations__administrative_level_one__in=admin_level_one_list).distinct()
                parser_context = getattr(self.request, 'parser_context', None)
                and_params = parser_context['request'].query_params.get('and_params', None) if parser_context else None
                if and_params is not None and 'administrative_level_one' in and_params:
                    # this _should_ be fairly straight forward with the postgresql ArrayAgg function,
                    # (which would offload the hard work to postgresql and make this whole operation faster)
                    # but that function is just throwing an error about a Serial data type,
                    # so the following is a work-around

                    # first, count the eventlocations for each returned event
                    # and only allow those with the same or greater count as the length of the query_param list
                    # use the 'only' operator to avoid PostgreSQL GROUP BY errors in annotation aggregation
                    queryset = queryset.annotate(
                        count_evtlocs=Count('eventlocations')).filter(
                        count_evtlocs__gte=len(admin_level_one_list)).only('id')
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
            if isinstance(value, list):
                value = ','.join([str(x) for x in value if x is not None])
            if LIST_DELIMITER in value:
                admin_level_two_list = value.split(',')
                queryset = queryset.prefetch_related('eventlocations__administrative_level_two').filter(
                    eventlocations__administrative_level_two__in=admin_level_two_list).distinct()
                parser_context = getattr(self.request, 'parser_context', None)
                and_params = parser_context['request'].query_params.get('and_params', None) if parser_context else None
                if and_params is not None and 'administrative_level_two' in and_params:
                    # first, count the eventlocations for each returned event
                    # and only allow those with the same or greater count as the length of the query_param list
                    # use the 'only' operator to avoid PostgreSQL GROUP BY errors in annotation aggregation
                    queryset = queryset.annotate(
                        count_evtlocs=Count('eventlocations')).filter(
                        count_evtlocs__gte=len(admin_level_two_list)).only('id')
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

    # label arguments were added to filters to prevent [invalid_name] displaying in filter form
    # https://github.com/carltongibson/django-filter/issues/1009
    and_params = CharInFilter(method='filter_and_params', label='Set the fields that will be combined with an "AND" operator instead of the default "OR"')
    complete = BooleanFilter(label='Filter by whether event is complete or not')
    public = BooleanFilter(label='Filter by whether event is public or not')
    permission_source = MultipleChoiceFilter(choices=PERMISSION_SOURCES_ENUM, method='filter_permission_sources', label='Filter by how the user has permission to view events')
    event_type = NumberInFilter(lookup_expr='in', label='Filter by event type ID (or a list of event type IDs)')
    diagnosis = NumberInFilter(method='filter_diagnosis', label='Filter by diagnosis ID (or a list of diagnosis IDs)')
    diagnosis_type = NumberInFilter(method='filter_diagnosis_type', label='Filter by diagnosis type ID (or a list of diagnosis type IDs)')
    species = NumberInFilter(method='filter_species', label='Filter by species ID (or a list of species IDs)')
    administrative_level_one = NumberInFilter(method='filter_administrative_level_one', label='Filter by administrative level one (e.g., state) ID (or a list of administrative level one (e.g., state) IDs)')
    administrative_level_two = NumberInFilter(method='filter_administrative_level_two', label='Filter by administrative level two (e.g., county) ID (or a list of administrative level two (e.g., county) IDs)')
    flyway = NumberInFilter(field_name='eventlocations__flyway', lookup_expr='in', label='Filter by flyway ID (or a list of flyway IDs)')
    country = NumberInFilter(field_name='eventlocations__country', lookup_expr='in', label='Filter by country ID (or a list of country IDs)')
    gnis_id = NumberInFilter(field_name='eventlocations__gnis_id', lookup_expr='in', label='Filter by GNIS ID (or a list of GNIS IDs)')
    affected_count__gte = NumberFilter(field_name='affected_count', lookup_expr='gte', label='Filter by affected count (greater than or equal to)')
    affected_count__lte = NumberFilter(field_name='affected_count', lookup_expr='lte', label='Filter by affected count (less than or equal to)')
    start_date = DateFilter(method='filter_start_end_date', label='Filter by start date', help_text='YYYY-MM-DD format')
    end_date = DateFilter(method='filter_start_end_date', label='Filter by end date', help_text='YYYY-MM-DD format')
    id = NumberInFilter(lookup_expr='in', label='Filter by event ID (or a list of event IDs)')

    class Meta:
        model = Event
        fields = ['and_params', 'complete', 'public', 'permission_source', 'event_type', 'diagnosis', 'diagnosis_type',
                  'species', 'administrative_level_one', 'administrative_level_two', 'flyway', 'country', 'gnis_id',
                  'affected_count__gte', 'affected_count__lte', 'start_date', 'end_date', ]
