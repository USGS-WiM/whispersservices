from django_filters.rest_framework import DjangoFilterBackend, FilterSet, NumberFilter, CharFilter, BooleanFilter
from whispersservices.models import *
from whispersservices.field_descriptions import *


# TODO: improve labels such that only unique fields (like affected_count__gte) have string literal values, while all other labels (like diagnosis) are assigned to variables
class EventSummaryFilter(FilterSet):
    complete = BooleanFilter(field_name='complete', lookup_expr='exact', label=event.complete)
    event_type = BooleanFilter(field_name='event_type', lookup_expr='exact', label=event.event_type)
    diagnosis = BooleanFilter(field_name='diagnosis', lookup_expr='exact', label='diagnosis ID')
    diagnosis_type = BooleanFilter(field_name='diagnosis_type', lookup_expr='exact', label='diagnosis type ID')
    species = BooleanFilter(field_name='species', lookup_expr='exact', label='species ID')
    administrative_level_one = BooleanFilter(
        field_name='administrative_level_one', lookup_expr='exact', label='administrative_level_one ID')
    administrative_level_two = BooleanFilter(
        field_name='administrative_level_two', lookup_expr='exact', label='administrative_level_two ID')
    flyway = BooleanFilter(field_name='flyway', lookup_expr='exact', label='flyway ID')
    country = BooleanFilter(field_name='country', lookup_expr='exact', label='country ID')
    gnis_id = BooleanFilter(field_name='gnis_id', lookup_expr='exact', label='gnis_ID')
    affected_count__gte = BooleanFilter(field_name='affected_count__gte', lookup_expr='gte', label='affected_count__gte')
    affected_count__lte = BooleanFilter(field_name='affected_count__lte', lookup_expr='lte', label='affected_count__lte')
    start_date = BooleanFilter(field_name='start_date', lookup_expr='exact', label=event.start_date)
    end_date = BooleanFilter(field_name='end_date', lookup_expr='exact', label=event.end_date)

    class Meta:
        model = Event
        fields = ['complete', 'event_type', 'diagnosis', 'diagnosis_type', 'species', 'administrative_level_one',
                  'administrative_level_two', 'flyway', 'country', 'gnis_id', 'affected_count__gte',
                  'affected_count__lte', 'start_date', 'end_date']