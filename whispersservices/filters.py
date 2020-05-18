from django_filters.rest_framework import DjangoFilterBackend, FilterSet, BaseInFilter, NumberFilter, CharFilter, BooleanFilter
from django_filters.widgets import BooleanWidget
from rest_framework.exceptions import PermissionDenied, NotFound
from whispersservices.models import *
from whispersservices.field_descriptions import *


PK_REQUESTS = ['retrieve', 'update', 'partial_update', 'destroy']
LIST_DELIMITER = ','


class NumberInFilter(BaseInFilter, NumberFilter):
    pass


# # TODO: improve labels such that only unique fields (like affected_count__gte) have string literal values, while all other labels (like diagnosis) are assigned to variables
# class EventSummaryFilter(FilterSet):
#     complete = BooleanFilter(field_name='complete', lookup_expr='exact', label=event.complete)
#     event_type = BooleanFilter(field_name='event_type', lookup_expr='exact', label=event.event_type)
#     diagnosis = BooleanFilter(field_name='diagnosis', lookup_expr='exact', label='diagnosis ID')
#     diagnosis_type = BooleanFilter(field_name='diagnosis_type', lookup_expr='exact', label='diagnosis type ID')
#     species = BooleanFilter(field_name='species', lookup_expr='exact', label='species ID')
#     administrative_level_one = BooleanFilter(
#         field_name='administrative_level_one', lookup_expr='exact', label='administrative_level_one ID')
#     administrative_level_two = BooleanFilter(
#         field_name='administrative_level_two', lookup_expr='exact', label='administrative_level_two ID')
#     flyway = BooleanFilter(field_name='flyway', lookup_expr='exact', label='flyway ID')
#     country = BooleanFilter(field_name='country', lookup_expr='exact', label='country ID')
#     gnis_id = BooleanFilter(field_name='gnis_id', lookup_expr='exact', label='gnis_ID')
#     affected_count__gte = BooleanFilter(field_name='affected_count__gte', lookup_expr='gte', label='affected_count__gte')
#     affected_count__lte = BooleanFilter(field_name='affected_count__lte', lookup_expr='lte', label='affected_count__lte')
#     start_date = BooleanFilter(field_name='start_date', lookup_expr='exact', label=event.start_date)
#     end_date = BooleanFilter(field_name='end_date', lookup_expr='exact', label=event.end_date)
#
#     class Meta:
#         model = Event
#         fields = ['complete', 'event_type', 'diagnosis', 'diagnosis_type', 'species', 'administrative_level_one',
#                   'administrative_level_two', 'flyway', 'country', 'gnis_id', 'affected_count__gte',
#                   'affected_count__lte', 'start_date', 'end_date']


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
    all = BooleanFilter(widget=BooleanWidget(), label='Return all notifications (mutually exclusive with "recipient" query parameter))')
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
                        return parent.filter(id=pk)
                raise NotFound
            get_all = True if self.request is not None and 'all' in self.request.query_params else False
            if get_all:
                return parent.all()
            else:
                recipient = self.request.query_params.get('recipient', None) if self.request else None
                if recipient is not None and recipient != '':
                    if LIST_DELIMITER in recipient:
                        recipient_list = recipient.split(',')
                        parent = parent.filter(recipient__in=recipient_list)
                    else:
                        parent = parent.filter(recipient__exact=recipient)
                else:
                    parent = parent.all().filter(recipient__exact=user.id)
        # otherwise return only what belongs to the user
        else:
            parent = parent.filter(recipient__exact=user.id)

        return parent.order_by('-id')

    class Meta:
        model: Notification
        fields = ['all', 'recipient', ]
