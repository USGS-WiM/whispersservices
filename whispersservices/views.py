import re
from datetime import datetime as dt
from collections import OrderedDict
from django.core.mail import EmailMessage
from django.utils import timezone
from django.db.models import Count, Q
from django.db.models.functions import Now
from django.contrib.auth import get_user_model
from rest_framework import views, viewsets, authentication, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import BaseParser
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.settings import api_settings
from rest_framework.schemas.openapi import AutoSchema
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework_csv import renderers as csv_renderers
from whispersservices.serializers import *
from whispersservices.models import *
from whispersservices.filters import *
from whispersservices.permissions import *
from whispersservices.pagination import *
from whispersservices.authentication import *
from dry_rest_permissions.generics import DRYPermissions
User = get_user_model()

# TODO: implement type checking on custom actions to prevent internal server error (HTTP 500)

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


class PlainTextParser(BaseParser):
    media_type = 'text/plain'

    def parse(self, stream, media_type=None, parser_context=None):
        text = stream.read().decode("utf-8")
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            text = text[1:-1]
        return text


PK_REQUESTS = ['retrieve', 'update', 'partial_update', 'destroy']
LIST_DELIMITER = ','
EMAIL_WHISPERS = settings.EMAIL_WHISPERS
whispers_email_address = Configuration.objects.filter(name='whispers_email_address').first()
if whispers_email_address and whispers_email_address.value.count('@') == 1:
    EMAIL_WHISPERS = whispers_email_address.value


def get_request_user(request):
    if request:
        return request.user
    else:
        return None


def construct_email(request_data, requester_email, message):
    # construct and send the request email
    subject = "Assistance Request"
    body = "A person (" + requester_email + ") has requested assistance:\r\n\r\n"
    body += message + "\r\n\r\n"
    body += request_data
    from_address = EMAIL_WHISPERS
    to_list = [EMAIL_WHISPERS, ]
    bcc_list = []
    reply_list = [requester_email, ]
    headers = None  # {'Message-ID': 'foo'}
    email = EmailMessage(subject, body, from_address, to_list, bcc_list, reply_to=reply_list, headers=headers)
    if settings.ENVIRONMENT in ['production', 'test']:
        try:
            email.send(fail_silently=False)
            return Response({"status": 'email sent'}, status=200)
        except TypeError:
            return Response({"status": "send email failed, please contact the administrator."}, status=500)
    else:
        return Response(email.__dict__, status=200)


def generate_notification_request_new(lookup_table, request):
    user = get_request_user(request)
    user = user if user else User.objects.filter(id=1).first()
    # source: User requesting a new option.
    source = user.username
    # recipients: WHISPers admin team
    recipients = list(User.objects.filter(role__in=[1, 2]).values_list('id', flat=True))
    # email forwarding: Automatic, to whispers@usgs.gov
    email_to = [User.objects.filter(id=1).values('email').first()['email'], ]
    msg_tmp = NotificationMessageTemplate.objects.filter(name='New Lookup Item Request').first()
    subject = msg_tmp.subject_template.format(lookup_table=lookup_table, lookup_item=request.data)
    body = msg_tmp.body_template.format(first_name=user.first_name, last_name=user.last_name, email=user.email,
                                  organization=user.organization.name, lookup_table=lookup_table,
                                  lookup_item=request.data)
    event = None
    from whispersservices.immediate_tasks import generate_notification
    generate_notification.delay(recipients, source, event, 'userdashboard', subject, body, True, email_to)
    return Response({"status": 'email sent'}, status=200)


######
#
#  Abstract Base Classes
#
######


class AuthLastLoginMixin(object):
    """
    This class will update the user's last_login field each time a request is received
    """

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

    permission_classes = (DRYPermissions,)
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend]  # (DjangoFilterBackend, filters.OrderingFilter,)

    def perform_create(self, serializer):
        if self.basename != 'users':
            serializer.save(created_by=self.request.user, modified_by=self.request.user)
        else:
            serializer.save()

    def perform_update(self, serializer):
        if self.basename != 'users':
            serializer.save(modified_by=self.request.user)
        else:
            serializer.save()

    # override the default pagination to allow disabling of pagination
    def paginate_queryset(self, *args, **kwargs):
        if not self.request:
            return super().paginate_queryset(*args, **kwargs)
        elif 'no_page' in self.request.query_params:
            return None
        return super().paginate_queryset(*args, **kwargs)


class ReadOnlyHistoryViewSet(AuthLastLoginMixin, viewsets.ReadOnlyModelViewSet):
    """
    This class will only allow GET requests (list and retrieve)
    """

    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend]  # (DjangoFilterBackend, filters.OrderingFilter,)

    # override the default pagination to allow disabling of pagination
    def paginate_queryset(self, *args, **kwargs):
        if not self.request:
            return super().paginate_queryset(*args, **kwargs)
        elif 'no_page' in self.request.query_params:
            return None
        return super().paginate_queryset(*args, **kwargs)


######
#
#  Events
#
######


class EventViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all events.

    create:
    Creates a new event.
    
    read:
    Returns an event by id.
    
    update:
    Updates an event.
    
    partial_update:
    Updates parts of an event.
    
    delete:
    Deletes an event.
    """

    serializer_class = EventSerializer

    @action(detail=True, methods=['post'])
    def alert_collaborator(self, request, pk=None):
        # expected JSON fields: "recipients" (list of integers, required), "comment" (string, optional)
        if request is None or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            raise PermissionDenied

        event = Event.objects.filter(id=pk).first()
        if not event:
            raise NotFound

        user = get_request_user(self.request)

        # only 'qualified users' may send alerts (someone with edit permissions on event)
        # (admins or the creator or a manager/admin member of the creator's org or a write_collaborator)
        qualified_event_user_ids = set(list(User.objects.filter(
            Q(eventwriteusers__event_id=event.id) |
            Q(organization=event.created_by.organization.id, role__in=[3, 4]) |
            Q(organization__in=event.created_by.parent_organizations, role__in=[3, 4]) |
            Q(id=event.created_by.id) |
            Q(role__in=[1, 2])).values_list('id', flat=True)))
        if user.id not in qualified_event_user_ids:
            raise PermissionDenied

        # validate that the POST body contains a required recipients list and possibly an optional comment
        recipients_message = "A field named \"recipients\" containing a list/array of collaborator User IDs"
        recipients_message += " is required to create collaborator alerts."
        if 'recipients' in request.data:
            recipient_ids = request.data['recipients']
            if not isinstance(recipient_ids, list) or not all(isinstance(x, int) for x in recipient_ids):
                raise serializers.ValidationError(recipients_message)
            else:
                event_user_ids = set(list(User.objects.filter(
                    Q(eventreadusers__event_id=event.id) |
                    Q(eventwriteusers__event_id=event.id) |
                    Q(organization=event.created_by.organization.id, role__in=[3, 4]) |
                    Q(organization__in=event.created_by.parent_organizations, role__in=[3, 4]) |
                    Q(id=event.created_by.id) |
                    Q(role__in=[1, 2])).values_list('id', flat=True)))
                # validate that the recipients are all collaborators of the event (or have access to the event)
                if not all(r_id in event_user_ids for r_id in recipient_ids):
                    message = "One or more submitted recipient IDs are not eligible to receive alerts about this event."
                    message += " Eligible recipients are collaborators of this event or"
                    message += " users in the same organization as the creator of this event, or system administrators."
                    raise serializers.ValidationError(message)
        else:
            raise serializers.ValidationError(recipients_message)
        comment_message = "A field named \"comment\" may only contain a string value."
        if 'comment' in request.data:
            comment = request.data['comment']
            if not isinstance(comment, str):
                raise serializers.ValidationError(comment_message)
        else:
            comment = ''

        # source: A qualified user (someone with edit permissions on event) who creates a collaborator alert.
        source = user.username
        # recipients: user(s) chosen from among the collaborator list
        recipients = User.objects.filter(id__in=recipient_ids)
        recipient_ids = [user.id for user in recipients]
        recipient_names = ''
        for user in recipients:
            recipient_names += ", " + user.first_name + " " + user.last_name
        recipient_names = recipient_names.replace(", ", "", 1)
        # email forwarding: Automatic, to all users included in the notification request.
        email_to = list(User.objects.filter(id__in=recipient_ids).values_list('email', flat=True))
        msg_tmp = NotificationMessageTemplate.objects.filter(name='Alert Collaborator').first()
        subject = msg_tmp.subject_template.format(event_id=event.id)
        body = msg_tmp.body_template.format(
            first_name=user.first_name, last_name=user.last_name, organization=user.organization.name,
            event_id=event.id, comment=comment, recipients=recipient_names)
        from whispersservices.immediate_tasks import generate_notification
        generate_notification.delay(recipient_ids, source, event.id, 'event', subject, body, True, email_to)

        # Collaborator alert is also logged as an event-level comment.
        comment += "\r\nAlert send to : " + recipient_names
        comment_type = CommentType.objects.filter(name='Collaborator Alert').first()
        if comment_type is not None:
            Comment.objects.create(content_object=event, comment=comment, comment_type=comment_type,
                                   created_by=user, modified_by=user)

        return Response({"status": 'email sent'}, status=200)

    @action(detail=True, methods=['post'], parser_classes=(PlainTextParser,))
    def request_collaboration(self, request, pk=None):
        if request is None or not request.user.is_authenticated:
            raise PermissionDenied

        user = get_request_user(self.request)
        # source: User requesting that they be a collaborator on an event.
        source = user.username
        event = Event.objects.filter(id=pk).first()
        if not event:
            raise NotFound

        event_owner = event.created_by
        # recipients: event owner, org manager, org admin
        recipients = list(User.objects.filter(
            Q(id=event_owner.id) | Q(role__in=[3, 4], organization=event_owner.organization.id) | Q(
                role__in=[3, 4], organization__in=event_owner.parent_organizations)
        ).values_list('id', flat=True))
        # email forwarding: Automatic, to event owner, organization manager, and organization admin
        email_to = list(User.objects.filter(
            Q(id=event_owner.id) | Q(role__in=[3, 4], organization=event_owner.organization.id) | Q(
                role__in=[3, 4], organization__in=event_owner.parent_organizations)
        ).values_list('email', flat=True))
        msg_tmp = NotificationMessageTemplate.objects.filter(name='Collaboration Request').first()
        subject = msg_tmp.subject_template.format(event_id=event.id)
        # {first_name,last_name,organization,event_id,comment,email}
        body = msg_tmp.body_template.format(first_name=user.first_name, last_name=user.last_name, email=user.email,
                                            organization=user.organization, event_id=event.id, comment=request.data)
        from whispersservices.immediate_tasks import generate_notification
        generate_notification.delay(recipients, source, event.id, 'event', subject, body, True, email_to)
        return Response({"status": 'email sent'}, status=200)

    def destroy(self, request, *args, **kwargs):
        # if the event is complete, it cannot be deleted
        if self.get_object().complete:
            message = "A complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        elif self.get_object().eventgroups:
            eventgroups_min_events = []
            eventgroups = EventGroup.objects.filter(events=self.get_object().id)
            for eg in eventgroups:
                eventgroup = EventGroup.objects.filter(id=eg.id).annotate(num_events=Count('events'))
                if eventgroup[0].num_events == 2:
                    eventgroups_min_events.append(eventgroup[0].id)
            if len(eventgroups_min_events) > 0:
                message = "An event may not be deleted if any event group " + str(eventgroups_min_events)
                message += " to which it belongs would have fewer than two events following this delete."
                raise serializers.ValidationError(message)

        return super(EventViewSet, self).destroy(request, *args, **kwargs)

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = get_request_user(self.request)
        queryset = Event.objects.all()

        # all requests from anonymous or public users must only return public data
        if not user or not user.is_authenticated or user.role.is_public:
            return queryset.filter(public=True)
        # admins have full access to all fields
        elif user.role.is_superadmin or user.role.is_admin:
            return queryset
        # for all non-admins, pk requests can only return non-public data to the owner or their org or collaborators
        elif self.action in PK_REQUESTS:
            pk = self.request.parser_context['kwargs'].get('pk', None)
            if pk is not None and pk.isdigit():
                queryset = Event.objects.filter(id=pk)
                if queryset:
                    obj = queryset[0]
                    if obj:
                        read_collaborators = []
                        write_collaborators = []
                        if obj.read_collaborators:
                            read_collaborators = list(
                                User.objects.filter(readevents=obj.id).values_list('id', flat=True))
                        if obj.write_collaborators:
                            write_collaborators = list(
                                User.objects.filter(writeevents=obj.id).values_list('id', flat=True))
                        if (user.id == obj.created_by.id
                                or user.organization.id == obj.created_by.organization.id
                                or user.organization.id in obj.created_by.parent_organizations
                                or user.id in read_collaborators or user.id in write_collaborators):
                            return queryset
                        else:
                            return queryset.filter(public=True)
            raise NotFound
        # all create requests imply that the requester is the owner, so use allow non-public data
        elif self.action == 'create':
            return queryset
        # all other requests must only return public data
        else:
            return queryset.filter(public=True)


class EventEventGroupViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event event groups.

    create:
    Creates a new event event group.

    read:
    Returns an event event group by id.

    update:
    Updates an event event group.

    partial_update:
    Updates parts of an event event group.

    delete:
    Deletes an event event group.
    """

    serializer_class = EventEventGroupSerializer

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to eventgroups can be deleted
        if self.get_object().event.complete:
            message = "EventGroup for a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(EventEventGroupViewSet, self).destroy(request, *args, **kwargs)

    # override the default queryset to allow filtering by user type
    def get_queryset(self):
        user = get_request_user(self.request)
        # "Biologically Equivalent (Public)" category only type visible to users not on WHISPers staff
        if not user or not user.is_authenticated:
            return EventEventGroup.objects.filter(eventgroup__category__name='Biologically Equivalent (Public)')
        # admins have access to all records
        if (user.role.is_superadmin or user.role.is_admin
                or user.organization.id == int(
                    Configuration.objects.filter(name='nwhc_organization').first().value)):
            return EventEventGroup.objects.all()
        else:
            return EventEventGroup.objects.filter(eventgroup__category__name='Biologically Equivalent (Public)')


class EventGroupViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event groups.

    create:
    Creates a new event group.

    read:
    Returns an event group by id.

    update:
    Updates an event group.

    partial_update:
    Updates parts of an event group.

    delete:
    Deletes an event group.
    """

    serializer_class = EventGroupSerializer

    # override the default queryset to allow filtering by user type
    def get_queryset(self):
        user = get_request_user(self.request)
        # "Biologically Equivalent (Public)" category only type visible to users not on WHISPers staff
        if not user or not user.is_authenticated:
            return EventGroup.objects.filter(category__name='Biologically Equivalent (Public)')
        # admins have access to all records
        if user.role.is_superadmin or user.role.is_admin:
            return EventGroup.objects.all()
        else:
            return EventGroup.objects.filter(category__name='Biologically Equivalent (Public)')


class EventGroupCategoryViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event group categories.

    create:
    Creates a new event group category.

    read:
    Returns an event group category by id.

    update:
    Updates an event group category.

    partial_update:
    Updates parts of an event group category.

    delete:
    Deletes an event group category.
    """

    serializer_class = EventGroupCategorySerializer

    # override the default queryset to allow filtering by user type
    def get_queryset(self):
        user = get_request_user(self.request)
        # "Biologically Equivalent (Public)" category only type visible to users not on WHISPers staff
        if not user or not user.is_authenticated:
            return EventGroupCategory.objects.filter(name='Biologically Equivalent (Public)')
        # admins have access to all records
        if (user.role.is_superadmin or user.role.is_admin
                or user.organization.id == int(Configuration.objects.filter(name='nwhc_organization').first().value)):
            return EventGroupCategory.objects.all()
        else:
            return EventGroupCategory.objects.filter(name='Biologically Equivalent (Public)')


class EventTypeViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event types.

    create:
    Creates a new event type.
    
    read:
    Returns an event type by id.
    
    update:
    Updates an event type.
    
    partial_update:
    Updates parts of an event type.
    
    delete:
    Deletes an event type.
    """

    queryset = EventType.objects.all()
    serializer_class = EventTypeSerializer


class StaffViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all staff.

    create:
    Creates a new staff member.
    
    read:
    Returns a staff member by id.
    
    update:
    Updates a staff member.
    
    partial_update:
    Updates parts of a staff member.
    
    delete:
    Deletes a staff member.
    """

    serializer_class = StaffSerializer

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = get_request_user(self.request)

        # all requests from anonymous users return nothing
        if not user or not user.is_authenticated:
            return Staff.objects.none()
        # admins and superadmins can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = Staff.objects.all()
        # otherwise return nothing
        else:
            return Staff.objects.none()

        return queryset


class LegalStatusViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all legal statuses.

    create:
    Creates a new legal status.
    
    read:
    Returns a legal status by id.
    
    update:
    Updates a legal status.
    
    partial_update:
    Updates parts of a legal status.
    
    delete:
    Deletes a legal status.
    """

    queryset = LegalStatus.objects.all()
    serializer_class = LegalStatusSerializer


class EventStatusViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event statuses.

    create:
    Creates a new event status.
    
    read:
    Returns an event status by id.
    
    update:
    Updates an event status.
    
    partial_update:
    Updates parts of an event status.
    
    delete:
    Deletes an event status.
    """

    queryset = EventStatus.objects.all()
    serializer_class = EventStatusSerializer


class EventAbstractViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event abstracts.

    create:
    Creates a new event abstract.
    
    read:
    Returns an event abstract by id.
    
    update:
    Updates an event abstract.
    
    partial_update:
    Updates parts of an event abstract.
    
    delete:
    Deletes an event abstract.
    """
    # not visible in api

    serializer_class = EventAbstractSerializer
    queryset = EventAbstract.objects.all()
    filter_backends = (DjangoFilterBackend,)
    filterset_class = EventAbstractFilter

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to abstracts can be deleted
        if self.get_object().event.complete:
            message = "Abstracts from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(EventAbstractViewSet, self).destroy(request, *args, **kwargs)


class EventCaseViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event cases.

    create:
    Creates a new event case.
    
    read:
    Returns an event case by id.
    
    update:
    Updates an event case.
    
    partial_update:
    Updates parts of an event case.
    
    delete:
    Deletes an event case.
    """

    queryset = EventCase.objects.all()
    serializer_class = EventCaseSerializer

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to cases can be deleted
        if self.get_object().event.complete:
            message = "Cases from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(EventCaseViewSet, self).destroy(request, *args, **kwargs)


class EventLabsiteViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event lab sites.

    create:
    Creates a new event lab site.
    
    read:
    Returns an event lab site by id.
    
    update:
    Updates an event lab site.
    
    partial_update:
    Updates parts of an event lab site.
    
    delete:
    Deletes an event lab site.
    """

    queryset = EventLabsite.objects.all()
    serializer_class = EventLabsiteSerializer

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to labsites can be deleted
        if self.get_object().event.complete:
            message = "Labsites from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(EventLabsiteViewSet, self).destroy(request, *args, **kwargs)


class EventOrganizationViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event organizations.

    create:
    Creates a new event organization.
    
    read:
    Returns an event organization by id.
    
    update:
    Updates an event organization.
    
    partial_update:
    Updates parts of an event organization.
    
    delete:
    Deletes an event organization.
    """

    queryset = EventOrganization.objects.all()
    serializer_class = EventOrganizationSerializer

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to organizations can be deleted
        if self.get_object().event.complete:
            message = "Organizations from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(EventOrganizationViewSet, self).destroy(request, *args, **kwargs)


class EventContactViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event contacts.

    create:
    Creates a new event contact.
    
    read:
    Returns an event contact by id.
    
    update:
    Updates an event contact.
    
    partial_update:
    Updates parts of an event contact.
    
    delete:
    Deletes an event contact.
    """

    serializer_class = EventContactSerializer

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to contacts can be deleted
        if self.get_object().event.complete:
            message = "Contacts from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(EventContactViewSet, self).destroy(request, *args, **kwargs)

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = get_request_user(self.request)

        # all requests from anonymous users return nothing
        if not user or not user.is_authenticated:
            return EventContact.objects.none()
        # admins and superadmins can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = EventContact.objects.all()
        # otherwise return nothing
        else:
            return EventContact.objects.none()

        return queryset


######
#
#  Locations
#
######


class EventLocationViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event locations.

    create:
    Creates a new event location.
    
    read:
    Returns an event location by id.
    
    update:
    Updates an event location.
    
    partial_update:
    Updates parts of an event location.
    
    delete:
    Deletes an event location.
    """

    queryset = EventLocation.objects.all()
    serializer_class = EventLocationSerializer

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to locations can be deleted
        if self.get_object().event.complete:
            message = "Locations from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(EventLocationViewSet, self).destroy(request, *args, **kwargs)


class EventLocationContactViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event location contacts.

    create:
    Creates a new event location contact.
    
    read:
    Returns an event contact by id.
    
    update:
    Updates an event location contact.
    
    partial_update:
    Updates parts of an event location contact.
    
    delete:
    Deletes an event location contact.
    """

    serializer_class = EventLocationContactSerializer

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to location contacts can be deleted
        if self.get_object().event_location.event.complete:
            message = "Contacts from a location from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(EventLocationContactViewSet, self).destroy(request, *args, **kwargs)

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = get_request_user(self.request)

        # all requests from anonymous or public users return nothing
        if not user or not user.is_authenticated or user.role.is_public:
            return EventLocationContact.objects.none()
        # admins and superadmins can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = EventLocationContact.objects.all()
        # partners can see location contacts owned by the user or user's org
        elif user.role.is_affiliate or user.role.is_partner or user.role.is_partnermanager or user.role.is_partneradmin:
            # they can also see location contacts for events on which they are collaborators:
            collab_evt_ids = list(Event.objects.filter(
                Q(eventwriteusers__user__in=[user.id, ]) | Q(eventreadusers__user__in=[user.id, ])
            ).values_list('id', flat=True))
            queryset = EventLocationContact.objects.filter(
                Q(created_by__exact=user.id) |
                Q(created_by__organization__exact=user.organization) |
                Q(created_by__organization__in=user.child_organizations) |
                Q(event_location__event__in=collab_evt_ids)
            )
        # otherwise return nothing
        else:
            return EventLocationContact.objects.none()

        return queryset


class CountryViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all countries.

    create:
    Creates a new country.
    
    read:
    Returns a country by id.
    
    update:
    Updates a country.
    
    partial_update:
    Updates parts of a country.
    
    delete:
    Deletes a country.
    """

    queryset = Country.objects.all()
    serializer_class = CountrySerializer


class AdministrativeLevelOneViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all administrative level ones.

    create:
    Creates an new administrative level one.
    
    read:
    Returns an administrative level one by id.
    
    update:
    Updates an administrative level one.
    
    partial_update:
    Updates parts of an administrative level one.
    
    delete:
    Deletes an administrative level one.
    """

    queryset = AdministrativeLevelOne.objects.all()
    filter_backends = (DjangoFilterBackend,)
    filterset_class = AdministrativeLevelOneFilter

    def get_serializer_class(self):
        if self.request and 'slim' in self.request.query_params:
            return AdministrativeLevelOneSlimSerializer
        else:
            return AdministrativeLevelOneSerializer


class AdministrativeLevelTwoViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all administrative level twos.

    create:
    Creates a new administrative level two.
    
    request_new:
    Request to have a new administrative level two added.
    
    read:
    Returns a administrative level two by id.
    
    update:
    Updates an administrative level two.
    
    partial_update:
    Updates parts of an administrative level two.
    
    delete:
    Deletes an administrative level two.
    """

    queryset = AdministrativeLevelTwo.objects.all()
    filter_backends = (DjangoFilterBackend,)
    filterset_class = AdministrativeLevelTwoFilter

    @action(detail=False, methods=['post'], parser_classes=(PlainTextParser,))
    def request_new(self, request):
        # A request for a new lookup item is made. Partner or above.
        if request is None or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            raise PermissionDenied

        # message = "Please add a new administrative level two:"
        # return construct_email(request.data, request.user.email, message)
        return generate_notification_request_new("administrativeleveltwos", request)

    def get_serializer_class(self):
        if self.request and 'slim' in self.request.query_params:
            return AdministrativeLevelTwoSlimSerializer
        else:
            return AdministrativeLevelTwoSerializer


class AdministrativeLevelLocalityViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all administrative level localities.

    create:
    Creates a new administrative level locality.
    
    read:
    Returns an administrative level locality by id.
    
    update:
    Updates an administrative level locality.
    
    partial_update:
    Updates parts of an administrative level locality.
    
    delete:
    Deletes an administrative level locality.
    """

    queryset = AdministrativeLevelLocality.objects.all()
    serializer_class = AdministrativeLevelLocalitySerializer


class LandOwnershipViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all landownerships.

    create:
    Creates a new landownership.
    
    read:
    Returns a landownership by id.
    
    update:
    Updates a landownership.
    
    partial_update:
    Updates parts of a landownership.
    
    delete:
    Deletes a landownership.
    """

    queryset = LandOwnership.objects.all()
    serializer_class = LandOwnershipSerializer


class EventLocationFlywayViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event location flyways.

    create:
    Creates an event location flyway.
    
    read:
    Returns an event location flyway by id.
    
    update:
    Updates an event location flyway.
    
    partial_update:
    Updates parts of an event location flyway.
    
    delete:
    Deletes an event location flyway.
    """

    queryset = EventLocationFlyway.objects.all()
    serializer_class = EventLocationFlywaySerializer

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to location flyways can be deleted
        if self.get_object().event_location.event.complete:
            message = "Flyways from a location from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(EventLocationFlywayViewSet, self).destroy(request, *args, **kwargs)


class FlywayViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all flyways.

    create:
    Creates a flyway.
    
    read:
    Returns a flyway by id.
    
    update:
    Updates a flyway.
    
    partial_update:
    Updates parts of a flyway.
    
    delete:
    Deletes a flyway.
    """

    queryset = Flyway.objects.all()
    serializer_class = FlywaySerializer


######
#
#  Species
#
######


class LocationSpeciesViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all location species.

    create:
    Creates a location species.
    
    read:
    Returns a location species by id.
    
    update:
    Updates a location species.
    
    partial_update:
    Updates parts of a location species.
    
    delete:
    Deletes a location species.
    """

    queryset = LocationSpecies.objects.all()
    serializer_class = LocationSpeciesSerializer

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to location species can be deleted
        if self.get_object().event_location.event.complete:
            message = "Species from a location from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(LocationSpeciesViewSet, self).destroy(request, *args, **kwargs)


class SpeciesViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all species.

    create:
    Creates a species.
    
    request_new:
    Request to have a new species added.
    
    read:
    Returns a species by id.
    
    update:
    Updates a species.
    
    partial_update:
    Updates parts of a species.
    
    delete:
    Deletes a species.
    """

    queryset = Species.objects.all()

    @action(detail=False, methods=['post'], parser_classes=(PlainTextParser,))
    def request_new(self, request):
        # A request for a new lookup item is made. Partner or above.
        if request is None or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            raise PermissionDenied

        # message = "Please add a new species:"
        # return construct_email(request.data, request.user.email, message)
        return generate_notification_request_new("species", request)

    def get_serializer_class(self):
        if self.request and 'slim' in self.request.query_params:
            return SpeciesSlimSerializer
        else:
            return SpeciesSerializer


class AgeBiasViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all age biasses.

    create:
    Creates an age bias.
    
    read:
    Returns an age bias by id.
    
    update:
    Updates an age bias.
    
    partial_update:
    Updates parts of an age bias.
    
    delete:
    Deletes an age bias.
    """

    queryset = AgeBias.objects.all()
    serializer_class = AgeBiasSerializer


class SexBiasViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all sex biasses.

    create:
    Creates a sex bias.
    
    read:
    Returns a sex bias by id.
    
    update:
    Updates a sex bias.
    
    partial_update:
    Updates parts of a sex bias.
    
    delete:
    Deletes a sex bias.
    """

    queryset = SexBias.objects.all()
    serializer_class = SexBiasSerializer


######
#
#  Diagnoses
#
######


class DiagnosisViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all diagnoses.

    create:
    Creates a diagnosis.

    request_new:
    Request to have a new diagnosis added.
    
    read:
    Returns a diagnosis by id.
    
    update:
    Updates a diagnosis.
    
    partial_update:
    Updates parts of a diagnosis.
    
    delete:
    Deletes a diagnosis.
    """

    serializer_class = DiagnosisSerializer
    queryset = Diagnosis.objects.all()
    filter_backends = (DjangoFilterBackend,)
    filterset_class = DiagnosisFilter

    @action(detail=False, methods=['post'], parser_classes=(PlainTextParser,))
    def request_new(self, request):
        # A request for a new lookup item is made. Partner or above.
        if request is None or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            raise PermissionDenied

        # message = "Please add a new diagnosis:"
        # return construct_email(request.data, request.user.email, message)
        return generate_notification_request_new("diagnoses", request)


class DiagnosisTypeViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all diagnosis types.

    create:
    Creates a diagnosis type.
    
    read:
    Returns a diagnosis type by id.
    
    update:
    Updates a diagnosis type.
    
    partial_update:
    Updates parts of a diagnosis type.
    
    delete:
    Deletes a diagnosis type.
    """

    queryset = DiagnosisType.objects.all()
    serializer_class = DiagnosisTypeSerializer


class EventDiagnosisViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all event diagnoses.

    create:
    Creates an event diagnosis.
    
    read:
    Returns an event diagnosis by id.
    
    update:
    Updates an event diagnosis.
    
    partial_update:
    Updates parts of an event diagnosis.
    
    delete:
    Deletes an event diagnosis.
    """

    queryset = EventDiagnosis.objects.all()
    serializer_class = EventDiagnosisSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        # if the related event is complete, no relates to diagnoses can be deleted
        if instance.event.complete:
            message = "Diagnoses from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)

        destroyed_event_diagnosis = super(EventDiagnosisViewSet, self).destroy(request, *args, **kwargs)

        # Ensure at least one other EventDiagnosis exists for the parent Event after the EventDiagnosis deletion above,
        # and if there are no EventDiagnoses left, create a new Pending or Undetermined EventDiagnosis,
        # depending on the parent Event's complete status
        evt_diags = EventDiagnosis.objects.filter(event=instance.event.id)
        if not len(evt_diags) > 0:
            new_diagnosis_name = 'Pending' if not instance.event.complete else 'Undetermined'
            new_diagnosis = Diagnosis.objects.filter(name=new_diagnosis_name).first()
            # All "Pending" and "Undetermined" must be confirmed OR some other way of coding this
            # such that we never see "Pending suspect" or "Undetermined suspect" on front end.
            EventDiagnosis.objects.create(
                event=instance.event, diagnosis=new_diagnosis, suspect=False, priority=1,
                created_by=instance.created_by, modified_by=instance.modified_by)

        return destroyed_event_diagnosis


class SpeciesDiagnosisViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all species diagnoses.

    create:
    Creates a species diagnosis.
    
    read:
    Returns a species diagnosis by id.
    
    update:
    Updates a species diagnosis.
    
    partial_update:
    Updates parts of a species diagnosis.
    
    delete:
    Deletes a species diagnosis.
    """

    queryset = SpeciesDiagnosis.objects.all()
    serializer_class = SpeciesDiagnosisSerializer

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to location species diagnoses can be deleted
        if self.get_object().location_species.event_location.event.complete:
            message = "Diagnoses from a species from a location from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(SpeciesDiagnosisViewSet, self).destroy(request, *args, **kwargs)


class SpeciesDiagnosisOrganizationViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all species diagnosis organization.

    create:
    Creates a species diagnosis organization.
    
    read:
    Returns a species diagnosis organization by id.
    
    update:
    Updates a species diagnosis organization.
    
    partial_update:
    Updates parts of a species diagnosis organization.
    
    delete:
    Deletes a species diagnosis organization.
    """

    queryset = SpeciesDiagnosisOrganization.objects.all()
    serializer_class = SpeciesDiagnosisOrganizationSerializer

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to location species diagnosis organizations can be deleted
        if self.get_object().species_diagnosis.location_species.event_location.event.complete:
            message = "Diagnoses from a species from a location from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        return super(SpeciesDiagnosisOrganizationViewSet, self).destroy(request, *args, **kwargs)


class DiagnosisBasisViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all diagnosis bases.

    create:
    Creates a diagnosis basis.
    
    read:
    Returns a diagnosis basis by id.
    
    update:
    Updates a diagnosis basis.
    
    partial_update:
    Updates parts of a diagnosis basis.
    
    delete:
    Deletes a diagnosis basis.
    """

    queryset = DiagnosisBasis.objects.all()
    serializer_class = DiagnosisBasisSerializer


class DiagnosisCauseViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all diagnosis causes.

    create:
    Creates a diagnosis cause.
    
    read:
    Returns a diagnosis cause by id.
    
    update:
    Updates a diagnosis cause.
    
    partial_update:
    Updates parts of a diagnosis cause.
    
    delete:
    Deletes a diagnosis cause.
    """

    queryset = DiagnosisCause.objects.all()
    serializer_class = DiagnosisCauseSerializer


######
#
#  Service Requests
#
######


class ServiceRequestViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all service requests.

    create:
    Creates a service request.
    
    read:
    Returns a service request by id.
    
    update:
    Updates a service request.
    
    partial_update:
    Updates parts of a service request.
    
    delete:
    Deletes a service request.
    """

    serializer_class = ServiceRequestSerializer

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = get_request_user(self.request)

        # all requests from anonymous or public users return nothing
        if not user or not user.is_authenticated or user.role.is_public:
            return ServiceRequest.objects.none()
        # admins and superadmins can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = ServiceRequest.objects.all()
        # partners can see service requests owned by the user or user's org
        elif user.role.is_affiliate or user.role.is_partner or user.role.is_partnermanager or user.role.is_partneradmin:
            # they can also see service requests for events on which they are collaborators:
            collab_evt_ids = list(Event.objects.filter(
                Q(eventwriteusers__user__in=[user.id, ]) | Q(eventreadusers__user__in=[user.id, ])
            ).values_list('id', flat=True))
            queryset = ServiceRequest.objects.filter(
                Q(created_by__exact=user.id) |
                Q(created_by__organization__exact=user.organization) |
                Q(created_by__organization__in=user.child_organizations) |
                Q(event__in=collab_evt_ids)
            )
        # otherwise return nothing
        else:
            return ServiceRequest.objects.none()

        return queryset


class ServiceRequestTypeViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all service request types.

    create:
    Creates a service request type.
    
    read:
    Returns a service request type by id.
    
    update:
    Updates a service request type.
    
    partial_update:
    Updates parts of a service request type.
    
    delete:
    Deletes a service request type.
    """

    queryset = ServiceRequestType.objects.all()
    serializer_class = ServiceRequestTypeSerializer


class ServiceRequestResponseViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all service request responses.

    create:
    Creates a service request response.
    
    read:
    Returns a service request response by id.
    
    update:
    Updates a service request response.
    
    partial_update:
    Updates parts of a service request response.
    
    delete:
    Deletes a service request response.
    """

    queryset = ServiceRequestResponse.objects.all().exclude(name="Pending")
    serializer_class = ServiceRequestResponseSerializer


######
#
#  Notifications
#
######


class NotificationViewSet(HistoryViewSet):
    serializer_class = NotificationSerializer

    @action(methods=['post'], detail=False)
    def bulk_update(self, request):
        user = get_request_user(self.request)

        is_valid = True
        response_errors = []
        item = request.data
        if 'action' not in item or item['action'] not in ['delete', 'set_read', 'set_unread']:
            message = 'action is a required field (accepted values are "delete", "set_read", "set_unread")'
            response_errors.append(message)
        if 'ids' not in item or not isinstance(item['ids'], list) or not (
                all(isinstance(x, int) for x in item['ids']) or all(x.isdigit() for x in item['ids'])):
            # recipients_message = "A field named \"ids\" containing a list/array of notification IDs"
            # recipients_message += " is required to bulk update notifications."
            # raise serializers.ValidationError(recipients_message)
            response_errors.append("ids is a required field")
        else:
            if user.role.id not in [1,2]:
                user_notifications = list(
                    Notification.objects.filter(recipient__id=user.id).values_list('id', flat=True))
                if not all(x in user_notifications for x in item['ids']):
                    message = "the requesting user must be the recipient of all notifications for all submitted ids"
                    response_errors.append(message)
        if len(response_errors) > 0:
            is_valid = False

        if is_valid:
            if item['action'] == 'delete':
                Notification.objects.filter(id__in=(item['ids'])).delete()
            elif item['action'] == 'set_read':
                Notification.objects.filter(id__in=(item['ids'])).update(read=True)
            elif item['action'] == 'set_unread':
                Notification.objects.filter(id__in=(item['ids'])).update(read=False)
            return Response({"status": 'update completed'}, status=200)
        else:
            return Response({"non-field errors": response_errors}, status=400)

    def get_queryset(self):
        queryset = Notification.objects.all()
        user = get_request_user(self.request)

        # anonymous users cannot see anything
        if not user or not user.is_authenticated:
            return Notification.objects.none()
        # public users cannot see anything
        elif user.role.is_public:
            return Notification.objects.none()
        # admins and superadmins can see notifications that belong to anyone (if they use the 'recipient' query param)
        # or everyone (if they use the 'all' query param, or get a single one), but default to just getting their own
        elif user.role.is_superadmin or user.role.is_admin:
            if self.action in PK_REQUESTS:
                pk = self.request.parser_context['kwargs'].get('pk', None)
                if pk is not None and pk.isdigit():
                    queryset = Notification.objects.filter(id=pk)
                    return queryset
                raise NotFound
            get_all = True if self.request is not None and 'all' in self.request.query_params else False
            if get_all:
                return Notification.objects.all()
            else:
                recipient = self.request.query_params.get('recipient', None) if self.request else None
                if recipient is not None and recipient != '':
                    if LIST_DELIMITER in recipient:
                        recipient_list = recipient.split(',')
                        queryset = queryset.filter(recipient__in=recipient_list)
                    else:
                        queryset = queryset.filter(recipient__exact=recipient)
                else:
                    queryset = Notification.objects.all().filter(recipient__exact=user.id)
        # otherwise return only what belongs to the user
        else:
            queryset = Notification.objects.filter(recipient__exact=user.id)

        return queryset.order_by('-id')


class NotificationCuePreferenceViewSet(HistoryViewSet):
    serializer_class = NotificationCuePreferenceSerializer

    def get_queryset(self):
        user = get_request_user(self.request)

        # anonymous users cannot see anything
        if not user or not user.is_authenticated:
            return NotificationCuePreference.objects.none()
        # public users cannot see anything
        elif user.role.is_public:
            return NotificationCuePreference.objects.none()
        # otherwise return only what belongs to the user
        else:
            queryset = NotificationCuePreference.objects.all().filter(created_by__exact=user.id)

        return queryset


class NotificationCueCustomViewSet(HistoryViewSet):
    serializer_class = NotificationCueCustomSerializer

    def get_queryset(self):
        user = get_request_user(self.request)

        # anonymous users cannot see anything
        if not user or not user.is_authenticated:
            return NotificationCueCustom.objects.none()
        # public users cannot see anything
        elif user.role.is_public:
            return NotificationCueCustom.objects.none()
        # otherwise return only what belongs to the user
        else:
            queryset = NotificationCueCustom.objects.all().filter(created_by__exact=user.id)

        return queryset


class NotificationCueStandardViewSet(HistoryViewSet):
    serializer_class = NotificationCueStandardSerializer

    def get_queryset(self):
        user = get_request_user(self.request)

        # anonymous users cannot see anything
        if not user or not user.is_authenticated:
            return NotificationCueStandard.objects.none()
        # public users cannot see anything
        elif user.role.is_public:
            return NotificationCueStandard.objects.none()
        # otherwise return only what belongs to the user
        else:
            queryset = NotificationCueStandard.objects.all().filter(created_by__exact=user.id)

        return queryset


class NotificationCueStandardTypeViewSet(HistoryViewSet):
    queryset = NotificationCueStandardType.objects.all()
    serializer_class = NotificationCueStandardTypeSerializer


######
#
#  Misc
#
######


class CommentViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all comments.

    create:
    Creates a comment.
    
    read:
    Returns a comment by id.
    
    update:
    Updates a comment.
    
    partial_update:
    Updates parts of a comment.
    
    delete:
    Deletes a comment.
    """

    serializer_class = CommentSerializer

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = get_request_user(self.request)

        # all requests from anonymous or public users return nothing
        if not user or not user.is_authenticated or user.role.is_public:
            return Comment.objects.none()
        # admins and superadmins can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = Comment.objects.all()
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
            queryset = Comment.objects.filter(
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
            return Comment.objects.none()

        contains = self.request.query_params.get('contains', None) if self.request else None
        if contains is not None:
            queryset = queryset.filter(comment__contains=contains)
        return queryset


class CommentTypeViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all comment types.

    create:
    Creates a comment type.
    
    read:
    Returns a comment type by id.
    
    update:
    Updates a comment type.
    
    partial_update:
    Updates parts of a comment type.
    
    delete:
    Deletes a comment type.
    """

    queryset = CommentType.objects.all()
    serializer_class = CommentTypeSerializer


class ArtifactViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all artifacts.

    create:
    Creates an artifact.
    
    read:
    Returns an artifact by id.
    
    update:
    Updates an artifact.
    
    partial_update:
    Updates parts of an artifact.
    
    delete:
    Deletes an artifact.
    """

    queryset = Artifact.objects.all()
    serializer_class = ArtifactSerializer


######
#
#  Users
#
######


class UserViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all artifacts.

    create:
    Creates an artifact.

    request_new:
    Request to have a new user added.
    
    read:
    Returns an artifact by id.
    
    update:
    Updates an artifact.
    
    partial_update:
    Updates parts of an artifact.
    
    delete:
    Deletes an artifact.
    """

    serializer_class = UserSerializer

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def verify_email(self, request):
        if isinstance(request.data, list):
            found = []
            not_found = []
            for item in request.data:
                # check if this item is a string
                if isinstance(item, str):
                    # check if this item is a well-formed email address
                    if '@' in item and re.match(r"[^@]+@[^@]+\.[^@]+", item):
                        # check if there is a matching user (email addresses are unique across all users)
                        user = User.objects.filter(email=item).first()
                        if user:
                            found.append(user)
                        else:
                            not_found.append(item)
                    else:
                        not_found.append(item)
                else:
                    not_found.append(item)
            if found:
                serializer = self.serializer_class(found, many=True, context={'request': request})
                resp = {**{"matching_users": serializer.data}, **{"no_matching_users": not_found}}
                return Response(resp, status=200)
            else:
                resp = {**{"matching_users": found}, **{"no_matching_users": not_found}}
                return Response(resp, status=200)
        else:
            raise serializers.ValidationError("You may only submit a list (array)")

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = get_request_user(self.request)

        # anonymous users cannot see anything
        if not user or not user.is_authenticated:
            return User.objects.none()
        # admins and superadmins can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = User.objects.all()
        # public and partner users can only see themselves
        elif user.role.is_public or user.role.is_affiliate or user.role.is_partner or user.role.is_partnermanager:
            return User.objects.filter(pk=user.id)
        # partneradmin can see data owned by the user or user's org
        elif user.role.is_partneradmin:
            queryset = User.objects.all().filter(Q(id__exact=user.id) | Q(organization__exact=user.organization) | Q(
                organization__in=user.organization.child_organizations))
        # otherwise return nothing
        else:
            return User.objects.none()

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
    """
    create:
    Determines if the submitted username and password match a user and whether the user is active
    """

    authentication_classes = (CustomBasicAuthentication,)
    serializer_class = UserSerializer

    def post(self, request):
        user = request.user if request is not None else None
        if user and user.is_authenticated:
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])
        return Response(self.serializer_class(user, context={'request': request}).data)


class RoleViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all roles.

    create:
    Creates a role.
    
    read:
    Returns a role by id.
    
    update:
    Updates a role.
    
    partial_update:
    Updates parts of a role.
    
    delete:
    Deletes a role.
    """

    queryset = Role.objects.all()
    serializer_class = RoleSerializer


class UserChangeRequestViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all role change requests.

    create:
    Creates a role change request.

    read:
    Returns a role change request by id.

    update:
    Updates a role change request.

    partial_update:
    Updates parts of a role change request.

    delete:
    Deletes a role change request.
    """

    serializer_class = UserChangeRequestSerializer

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = get_request_user(self.request)

        # anonymous users cannot see anything
        if not user or not user.is_authenticated:
            return UserChangeRequest.objects.none()
        # admins and superadmins can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = UserChangeRequest.objects.all()
        # partneradmins can see requests for their own org
        elif user.role.is_partneradmin:
            queryset = UserChangeRequest.objects.filter(Q(created_by__organization__exact=user.organization) | Q(
                created_by__organization__in=user.organization.child_organizations))
        # otherwise return nothing
        else:
            return UserChangeRequest.objects.none()

        return queryset


class UserChangeRequestResponseViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all role change request responses.

    create:
    Creates a role change request response.

    read:
    Returns a role change request response by id.

    update:
    Updates a role change request response.

    partial_update:
    Updates parts of a role change request response.

    delete:
    Deletes a role change request response.
    """

    queryset = UserChangeRequestResponse.objects.all().exclude(name="Pending")
    serializer_class = UserChangeRequestResponseSerializer


class CircleViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all circles.

    create:
    Creates a circle.
    
    read:
    Returns a circle by id.
    
    update:
    Updates a circle.
    
    partial_update:
    Updates parts of a circle.
    
    delete:
    Deletes a circle.
    """

    serializer_class = CircleSerializer

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = get_request_user(self.request)

        # anonymous users cannot see anything
        if not user or not user.is_authenticated:
            return Circle.objects.none()
        # admins and superadmins can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = Circle.objects.all()
        # otherwise return data owned by the user or user's org
        else:
            queryset = Circle.objects.all().filter(
                Q(created_by__exact=user.id) | Q(created_by__organization__exact=user.organization) | Q(
                    created_by__organization__in=user.organization.child_organizations))

        return queryset


class OrganizationViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all organizations.

    create:
    Creates a organization.

    request_new:
    Request to have a new organization added.
    
    read:
    Returns a organization by id.
    
    update:
    Updates a organization.
    
    partial_update:
    Updates parts of a organization.
    
    delete:
    Deletes a organization.
    """

    @action(detail=False, methods=['post'], parser_classes=(PlainTextParser,))
    def request_new(self, request):
        # A request for a new lookup item is made. Partner or above.
        if request is None or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            raise PermissionDenied

        # message = "Please add a new organization:"
        # return construct_email(request.data, request.user.email, message)
        return generate_notification_request_new("organizations", request)

    # override the default serializer_class to ensure the requester sees only permitted data
    def get_serializer_class(self):
        slim = True if self.request is not None and 'slim' in self.request.query_params else False
        return OrganizationSerializer if not slim else OrganizationSlimSerializer

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = get_request_user(self.request)
        queryset = Organization.objects.all()

        if self.request:
            users = self.request.query_params.get('users', None)
            if users is not None and users != '':
                users_list = users.split(',')
                queryset = queryset.filter(users__in=users_list)
            contacts = self.request.query_params.get('contacts', None)
            if contacts is not None and contacts != '':
                contacts_list = contacts.split(',')
                queryset = queryset.filter(contacts__in=contacts_list)
            laboratory = self.request.query_params.get('laboratory', None)
            if laboratory is not None and laboratory.capitalize() in ['True', 'False']:
                queryset = queryset.filter(laboratory__exact=laboratory.capitalize())

        # all requests from anonymous users must only return published data
        if not user or not user.is_authenticated:
            return queryset.filter(do_not_publish=False)
        # for pk requests, unpublished data can only be returned to the owner or their org or admins
        elif self.action in PK_REQUESTS:
            pk = self.request.parser_context['kwargs'].get('pk', None)
            if pk is not None and pk.isdigit():
                queryset = Organization.objects.filter(id=pk)
                if queryset:
                    obj = queryset[0]
                    if obj and (user.id == obj.created_by.id or user.organization.id == obj.created_by.organization.id
                                or user.organization.id in obj.created_by.organization.parent_organizations
                                or user.role.is_superadmin or user.role.is_admin):
                        return queryset
            raise NotFound
        # all list requests, and all requests from public users, must only return published data
        elif self.action == 'list' or user.role.is_public:
            return queryset.filter(do_not_publish=False)
        # that leaves the create request, implying that the requester is the owner
        else:
            return queryset


class ContactViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all contacts.

    create:
    Creates a contact.

    user_contacts:
    Returns contacts owned by a user.
    
    read:
    Returns a contact by id.
    
    update:
    Updates a contact.
    
    partial_update:
    Updates parts of a contact.
    
    delete:
    Deletes a contact.
    """

    @action(detail=False)
    def user_contacts(self, request):
        # limit data to what the user owns and what the user's org owns
        query_params = self.request.query_params if request is not None else None
        queryset = self.build_queryset(query_params, get_user_contacts=True)
        ordering_param = query_params.get('ordering', None) if query_params is not None else None
        if ordering_param is not None:
            fields = [field.strip() for field in ordering_param.split(',')]
            ordering = filters.OrderingFilter.remove_invalid_fields(
                filters.OrderingFilter(), queryset, fields, self, request)
            if ordering:
                queryset = queryset.order_by(*ordering)
            else:
                queryset = queryset.order_by('id')
        else:
            queryset = queryset.order_by('id')

        if not request:
            serializer = ContactSerializer(queryset, many=True, context={'request': request})
            return Response(serializer.data, status=200)

        else:
            slim = True if 'slim' in self.request.query_params else False

            if 'no_page' in self.request.query_params:
                if slim:
                    serializer = ContactSlimSerializer(queryset, many=True, context={'request': request})
                else:
                    serializer = ContactSerializer(queryset, many=True, context={'request': request})
                return Response(serializer.data, status=200)
            else:
                page = self.paginate_queryset(queryset)
                if page is not None:
                    if slim:
                        serializer = ContactSlimSerializer(page, many=True, context={'request': request})
                    else:
                        serializer = ContactSerializer(page, many=True, context={'request': request})
                    return self.get_paginated_response(serializer.data)
                if slim:
                    serializer = ContactSlimSerializer(queryset, many=True, context={'request': request})
                else:
                    serializer = ContactSerializer(queryset, many=True, context={'request': request})
                return Response(serializer.data, status=200)

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        query_params = self.request.query_params if self.request else None
        return self.build_queryset(query_params, get_user_contacts=False)

    # build a queryset using query_params
    # NOTE: this is being done in its own method to adhere to the DRY Principle
    def build_queryset(self, query_params, get_user_contacts):
        user = get_request_user(self.request)

        # anonymous users cannot see anything
        if not user or not user.is_authenticated:
            return Contact.objects.none()
        # public users cannot see anything
        elif user.role.is_public:
            return Contact.objects.none()
        # user-specific requests and requests from a partner user can only return data owned by the user or user's org
        elif (get_user_contacts or user.role.is_affiliate
              or user.role.is_partner or user.role.is_partnermanager or user.role.is_partneradmin):
            queryset = Contact.objects.all().filter(
                Q(created_by__exact=user.id) | Q(created_by__organization__exact=user.organization) | Q(
                    created_by__organization__in=user.organization.child_organizations))
        # admins, superadmins, and superusers can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = Contact.objects.all()
        # otherwise return nothing
        else:
            return Contact.objects.none()

        org = query_params.get('org', None)
        if org is not None and org != '':
            if LIST_DELIMITER in org:
                org_list = org.split(',')
                queryset = queryset.filter(organization__in=org_list)
            else:
                queryset = queryset.filter(organization__exact=org)
        owner_org = query_params.get('ownerorg', None)
        if owner_org is not None and owner_org != '':
            if LIST_DELIMITER in owner_org:
                owner_org_list = owner_org.split(',')
                queryset = queryset.filter(owner_organization__in=owner_org_list)
            else:
                queryset = queryset.filter(owner_organization__exact=owner_org)
        return queryset

    def get_serializer_class(self):
        if self.request and 'slim' in self.request.query_params:
            return ContactSlimSerializer
        else:
            return ContactSerializer


class ContactTypeViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all contact types.

    create:
    Creates a contact type.
    
    read:
    Returns a contact type by id.
    
    update:
    Updates a contact type.
    
    partial_update:
    Updates parts of a contact type.
    
    delete:
    Deletes a contact type.
    """

    queryset = ContactType.objects.all()
    serializer_class = ContactTypeSerializer


class SearchViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all searches.

    create:
    Creates a search.

    top_ten:
    Returns a list of the top 10 searches.

    user_searches:
    Returns a count of searches created by users.
    
    read:
    Returns a search by id.
    
    update:
    Updates a search.
    
    partial_update:
    Updates parts of a search.
    
    delete:
    Deletes a search.
    """

    serializer_class = SearchSerializer

    @action(detail=False)
    def user_searches(self, request):
        # limit data to what the user owns and what the user's org owns
        query_params = self.request.query_params if self.request else None
        queryset = self.build_queryset(query_params, get_user_searches=True)
        ordering_param = query_params.get('ordering', None) if query_params else None
        if ordering_param is not None:
            fields = [field.strip() for field in ordering_param.split(',')]
            ordering = filters.OrderingFilter.remove_invalid_fields(
                filters.OrderingFilter(), queryset, fields, self, request)
            if ordering:
                queryset = queryset.order_by(*ordering)
            else:
                queryset = queryset.order_by('id')
        else:
            queryset = queryset.order_by('id')

        if not self.request:
            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.serializer_class(page, many=True, context={'request': request})
                return self.get_paginated_response(serializer.data)
            serializer = self.serializer_class(queryset, many=True, context={'request': request})
            return Response(serializer.data, status=200)
        elif 'no_page' in self.request.query_params:
            serializer = self.serializer_class(queryset, many=True, context={'request': request})
            return Response(serializer.data, status=200)
        else:
            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.serializer_class(page, many=True, context={'request': request})
                return self.get_paginated_response(serializer.data)
            serializer = self.serializer_class(queryset, many=True, context={'request': request})
            return Response(serializer.data, status=200)

    @action(detail=False)
    def top_ten(self, request):
        # return top ten most popular searches
        queryset = Search.objects.all().values('data').annotate(use_count=Sum('count')).order_by('-use_count')[:10]
        serializer = self.serializer_class(queryset, many=True, context={'request': request})

        return Response(serializer.data, status=200)

    # override the default pagination to allow disabling of pagination
    def paginate_queryset(self, *args, **kwargs):
        if self.request and 'no_page' in self.request.query_params:
            return None
        return super().paginate_queryset(*args, **kwargs)

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        query_params = self.request.query_params if self.request else None
        return self.build_queryset(query_params, get_user_searches=False)

    # build a queryset using query_params
    # NOTE: this is being done in its own method to adhere to the DRY Principle
    def build_queryset(self, query_params, get_user_searches):
        user = get_request_user(self.request)

        # anonymous users cannot see anything
        if not user or not user.is_authenticated:
            return Search.objects.none()
        # user-specific requests and requests from non-admin user can only return data owned by the user
        elif get_user_searches or not (user.role.is_superadmin or user.role.is_admin):
            queryset = Search.objects.all().filter(created_by__exact=user)
        # admins, superadmins, and superusers can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = Search.objects.all()
        # otherwise return nothing
        else:
            return Search.objects.none()

        owner = query_params.get('owner', None)
        if owner is not None and owner != '':
            if LIST_DELIMITER not in owner:
                owner_list = owner.split(',')
                queryset = queryset.filter(created_by__in=owner_list)
            else:
                queryset = queryset.filter(created_by__exact=owner)
        return queryset


######
#
#  Special
#
######


class CSVEventSummaryPublicRenderer(csv_renderers.PaginatedCSVRenderer):
    header = ['id', 'type', 'affected', 'start_date', 'end_date', 'countries', 'states', 'counties',  'species',
              'eventdiagnoses']
    labels = {'id': 'Event ID', 'type': 'Event Type', 'affected': 'Number Affected', 'start_date': 'Event Start Date',
              'end_date': 'Event End Date', 'countries': "Countries", 'states': 'States (or equivalent)',
              'counties': 'Counties (or equivalent)', 'species': 'Species', 'eventdiagnoses': 'Event Diagnosis'}


class CSVEventSummaryRenderer(csv_renderers.PaginatedCSVRenderer):
    header = ['id', 'type', 'public', 'affected', 'start_date', 'end_date', 'countries', 'states', 'counties',
              'species', 'eventdiagnoses']
    labels = {'id': 'Event ID', 'type': 'Event Type', 'affected': 'Number Affected', 'public': 'Public',
              'start_date': 'Event Start Date', 'end_date': 'Event End Date', 'countries': 'Countries',
              'states': 'States (or equivalent)', 'counties': 'Counties (or equivalent)', 'species': 'Species',
              'eventdiagnoses': 'Event Diagnosis'}


class EventSummaryViewSet(ReadOnlyHistoryViewSet):
    """
    list:
    Returns a list of all event summaries.

    get_count:
    Returns a count of all event summaries.
    
    get_user_events_count:
    Returns a count of events created by (or otherwise visible to) a user.
    
    user_events:
    Returns events create by a user.
    
    read:
    Returns an event summary by id.
    """

    queryset = Event.objects.all()
    schema = AutoSchema(operation_id_base="EventSummary")
    # filterset_class = EventSummaryFilter
    # filterset_fields = ['complete', 'event_type']

    @action(detail=False)
    def get_count(self, request):
        query_params = self.request.query_params if self.request else None
        return Response({"count": self.build_queryset(query_params, get_user_events=False).count()})

    @action(detail=False)
    def get_user_events_count(self, request):
        query_params = self.request.query_params if self.request else None
        return Response({"count": self.build_queryset(query_params, get_user_events=True).count()})

    @action(detail=False)
    def user_events(self, request):
        # limit data to what the user owns, what the user's org owns, and what has been shared with the user
        query_params = self.request.query_params if self.request else None
        queryset = self.build_queryset(query_params, get_user_events=True)
        ordering_param = query_params.get('ordering', None) if query_params else None
        if ordering_param is not None:
            fields = [field.strip() for field in ordering_param.split(',')]
            ordering = filters.OrderingFilter.remove_invalid_fields(
                filters.OrderingFilter(), queryset, fields, self, request)
            if ordering:
                queryset = queryset.order_by(*ordering)
            else:
                queryset = queryset.order_by('-id')
        else:
            queryset = queryset.order_by('-id')

        frmt = self.request.query_params.get('format', '') if self.request else ''
        if self.request and 'no_page' in self.request.query_params:
            page = self.paginate_queryset(queryset)
            if page is not None:
                if frmt == 'csv':
                    serializer = FlatEventSummarySerializer(page, many=True, context={'request': request})
                else:
                    serializer = EventSummarySerializer(page, many=True, context={'request': request})
                return self.get_paginated_response(serializer.data)
        if frmt == 'csv':
            serializer = FlatEventSummarySerializer(queryset, many=True, context={'request': request})
        else:
            serializer = EventSummarySerializer(queryset, many=True, context={'request': request})

        return Response(serializer.data, status=200)

    # override the default renderers to use a csv renderer when requested
    def get_renderers(self):
        frmt = self.request.query_params.get('format', None) if self.request else None

        if frmt is not None and frmt == 'csv':
            renderer_classes = (CSVEventSummaryRenderer,) + tuple(api_settings.DEFAULT_RENDERER_CLASSES)
        else:
            renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES)
        return [renderer_class() for renderer_class in renderer_classes]

    # override the default finalize_response to assign a filename to CSV files
    # see https://github.com/mjumbewu/django-rest-framework-csv/issues/15
    def finalize_response(self, request, *args, **kwargs):
        response = super(viewsets.ReadOnlyModelViewSet, self).finalize_response(request, *args, **kwargs)
        renderer_format = self.request.accepted_renderer.format if self.request else ''
        if renderer_format == 'csv':
            fileextension = '.csv'
            filename = 'event_summary_'
            filename += dt.now().strftime("%Y") + '-' + dt.now().strftime("%m") + '-' + dt.now().strftime("%d")
            filename += fileextension
            response['Content-Disposition'] = "attachment; filename=%s" % filename
            response['Access-Control-Expose-Headers'] = 'Content-Disposition'
        return response

    # override the default serializer_class to ensure csv requests get the proper serializer
    def get_serializer_class(self):
        frmt = self.request.query_params.get('format', '') if self.request else ''
        return FlatEventSummarySerializer if frmt == 'csv' else EventSummarySerializer

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        query_params = self.request.query_params if self.request else None
        return self.build_queryset(query_params, get_user_events=False)

    # build a queryset using query_params
    # NOTE: this is being done in its own method to adhere to the DRY Principle
    def build_queryset(self, query_params, get_user_events):
        user = get_request_user(self.request)

        # first get or create the search and increment its count
        if query_params:
            ordered_query_params = OrderedDict(sorted(query_params.items()))
            ordered_query_params_static_keys = ordered_query_params.copy().keys()
            not_search_params = ['no_page', 'page', 'page_size', 'format', 'slim', 'ordering']
            for param in ordered_query_params_static_keys:
                if param in not_search_params:
                    del ordered_query_params[param]
            if len(ordered_query_params) > 0:
                admin_user = User.objects.get(pk=1)
                if not user or not user.is_authenticated:
                    search = Search.objects.filter(data=ordered_query_params, created_by=admin_user).first()
                else:
                    search = Search.objects.filter(data=ordered_query_params, created_by=user).first()
                # user-owned searches should be deliberately created through the searches endpoint
                # all other searches are 'anonymous' and should be owned by the admin user
                if not search:
                    search = Search.objects.create(data=ordered_query_params, created_by=admin_user)
                search.count += 1
                search.modified_by = admin_user if not user or not user.is_authenticated else user
                search.save()

        # then proceed to build the queryset
        queryset = self.queryset

        # anonymous users can only see public data
        if not user or not user.is_authenticated or user.role.is_public:
            if get_user_events:
                return queryset.none()
            else:
                queryset = queryset.filter(public=True)
        # user-specific event requests can only return data owned by the user or the user's org, or shared with the user
        elif get_user_events:
            queryset = queryset.filter(
                Q(created_by__exact=user.id) | Q(created_by__organization__exact=user.organization.id)
                | Q(created_by__organization__in=user.organization.child_organizations)
                | Q(read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])).distinct()
        # admins, superadmins, and superusers can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = queryset
        # for non-user-specific event requests, try to return the (old default) public data
        #  AND any private data the user should be able to see
        else:
            # queryset = queryset.filter(public=True)
            public_queryset = queryset.filter(public=True).distinct()
            personal_queryset = queryset.filter(
                Q(created_by__exact=user.id) | Q(created_by__organization__exact=user.organization.id)
                | Q(read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])).distinct()
            queryset = public_queryset | personal_queryset

        # check for params that should use the 'and' operator
        and_params = query_params.get('and_params', None)

        # filter by complete, exact
        complete = query_params.get('complete', None)
        if complete is not None and complete.capitalize() in ['True', 'False']:
            queryset = queryset.filter(complete__exact=complete.capitalize())
        # filter by public, exact
        public = query_params.get('public', None)
        if public is not None and public.capitalize() in ['True', 'False']:
            queryset = queryset.filter(public__exact=public.capitalize())
        # filter by permission_source, exact list
        permission_source = query_params.get('permission_source', None)
        if permission_source is not None and permission_source != '':
            if LIST_DELIMITER in permission_source:
                permission_source_list = permission_source.split(',')
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
                        Q(created_by=user.id) | Q(read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])).distinct()
                elif 'organization' in permission_source_list and 'collaboration' in permission_source_list:
                    queryset = queryset.filter(Q(created_by__organization=user.organization.id) | Q(
                        created_by__organization__in=user.organization.child_organizations) | Q(
                        read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])).exclude(created_by=user.id).distinct()
                elif 'own' in permission_source_list:
                    queryset = queryset.filter(created_by=user.id)
                elif 'organization' in permission_source_list:
                    queryset = queryset.filter(Q(created_by__organization=user.organization.id) | Q(
                        created_by__organization__in=user.organization.child_organizations)).exclude(created_by=user.id).distinct()
                elif 'collaboration' in permission_source_list:
                    queryset = queryset.filter(Q(read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])).distinct()
            else:
                if 'own' == permission_source:
                    queryset = queryset.filter(created_by=user.id)
                elif 'organization' == permission_source:
                    queryset = queryset.filter(Q(created_by__organization=user.organization.id) | Q(
                        created_by__organization__in=user.organization.child_organizations)).exclude(created_by=user.id).distinct()
                elif 'collaboration' == permission_source:
                    queryset = queryset.filter(Q(read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])).distinct()
        # filter by event_type ID, exact list
        event_type = query_params.get('event_type', None)
        if event_type is not None and event_type != '':
            if LIST_DELIMITER in event_type:
                event_type_list = event_type.split(',')
                queryset = queryset.filter(event_type__in=event_type_list)
            else:
                queryset = queryset.filter(event_type__exact=event_type)
        # filter by diagnosis ID, exact list
        diagnosis = query_params.get('diagnosis', None)
        if diagnosis is not None and diagnosis != '':
            if LIST_DELIMITER in diagnosis:
                diagnosis_list = diagnosis.split(',')
                queryset = queryset.prefetch_related('eventdiagnoses').filter(
                    eventdiagnoses__diagnosis__in=diagnosis_list).distinct()
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
                queryset = queryset.filter(eventdiagnoses__diagnosis__exact=diagnosis).distinct()
        # filter by diagnosistype ID, exact list
        diagnosis_type = query_params.get('diagnosis_type', None)
        if diagnosis_type is not None and diagnosis_type != '':
            if LIST_DELIMITER in diagnosis_type:
                diagnosis_type_list = diagnosis_type.split(',')
                queryset = queryset.prefetch_related('eventdiagnoses__diagnosis__diagnosis_type').filter(
                    eventdiagnoses__diagnosis__diagnosis_type__in=diagnosis_type_list).distinct()
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
                queryset = queryset.filter(eventdiagnoses__diagnosis__diagnosis_type__exact=diagnosis_type).distinct()
        # filter by species ID, exact list
        species = query_params.get('species', None)
        if species is not None and species != '':
            if LIST_DELIMITER in species:
                species_list = species.split(',')
                queryset = queryset.prefetch_related('eventlocations__locationspecies__species').filter(
                    eventlocations__locationspecies__species__in=species_list).distinct()
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
                queryset = queryset.filter(eventlocations__locationspecies__species__exact=species).distinct()
        # filter by administrative_level_one, exact list
        administrative_level_one = query_params.get('administrative_level_one', None)
        if administrative_level_one is not None and administrative_level_one != '':
            if LIST_DELIMITER in administrative_level_one:
                admin_level_one_list = administrative_level_one.split(',')
                queryset = queryset.prefetch_related('eventlocations__administrative_level_two').filter(
                    eventlocations__administrative_level_one__in=admin_level_one_list).distinct()
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
                    eventlocations__administrative_level_one__exact=administrative_level_one).distinct()
        # filter by administrative_level_two, exact list
        administrative_level_two = query_params.get('administrative_level_two', None)
        if administrative_level_two is not None and administrative_level_two != '':
            if LIST_DELIMITER in administrative_level_two:
                admin_level_two_list = administrative_level_two.split(',')
                queryset = queryset.prefetch_related('eventlocations__administrative_level_two').filter(
                    eventlocations__administrative_level_two__in=admin_level_two_list).distinct()
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
                    eventlocations__administrative_level_two__exact=administrative_level_two).distinct()
        # filter by flyway, exact list
        flyway = query_params.get('flyway', None)
        if flyway is not None and flyway != '':
            queryset = queryset.prefetch_related('eventlocations__flyway')
            if LIST_DELIMITER in flyway:
                flyway_list = flyway.split(',')
                queryset = queryset.filter(eventlocations__flyway__in=flyway_list).distinct()
            else:
                queryset = queryset.filter(eventlocations__flyway__exact=flyway).distinct()
        # filter by country, exact list
        country = query_params.get('country', None)
        if country is not None and country != '':
            queryset = queryset.prefetch_related('eventlocations__country')
            if LIST_DELIMITER in country:
                country_list = country.split(',')
                queryset = queryset.filter(eventlocations__country__in=country_list).distinct()
            else:
                queryset = queryset.filter(eventlocations__country__exact=country).distinct()
        # filter by gnis_id, exact list
        gnis_id = query_params.get('gnis_id', None)
        if gnis_id is not None and gnis_id != '':
            queryset = queryset.prefetch_related('eventlocations__gnis_id')
            if LIST_DELIMITER in gnis_id:
                gnis_id_list = country.split(',')
                queryset = queryset.filter(eventlocations__gnis_id__in=gnis_id_list).distinct()
            else:
                queryset = queryset.filter(eventlocations__gnis_id__exact=gnis_id).distinct()
        # filter by affected, (greater than or equal to only, less than or equal to only,
        # or between both, depending on which URL params appear)
        affected_count__gte = query_params.get('affected_count__gte', None)
        affected_count__lte = query_params.get('affected_count__lte', None)
        if affected_count__gte is not None and affected_count__lte is not None:
            queryset = queryset.filter(affected_count__gte=affected_count__gte, affected_count__lte=affected_count__lte)
        elif affected_count__gte is not None:
            queryset = queryset.filter(affected_count__gte=affected_count__gte)
        elif affected_count__lte is not None:
            queryset = queryset.filter(affected_count__lte=affected_count__lte)

        # # filter by start and end date (after only, before only, or between both, depending on which URL params appear)
        # # the date filters below are date-exclusive
        # start_date = query_params.get('start_date', None)
        # end_date = query_params.get('end_date', None)
        # if start_date is not None and end_date is not None:
        #     queryset = queryset.filter(start_date__gt=start_date, end_date__lt=end_date)
        # elif start_date is not None:
        #     queryset = queryset.filter(start_date__gt=start_date)
        # elif end_date is not None:
        #     queryset = queryset.filter(end_date__lt=end_date)

        # filter by start and end date (after only, before only, or between both, depending on which URL params appear)
        # the date filters below are date-inclusive
        start_date = query_params.get('start_date', None)
        end_date = query_params.get('end_date', None)
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


class CSVEventDetailRenderer(csv_renderers.CSVRenderer):
    # header = ['event_id', 'event_reference', 'event_type', 'complete', 'organization', 'start_date', 'end_date',
    header = ['event_id', 'event_type', 'complete', 'organization', 'start_date', 'end_date',
              'affected_count', 'event_diagnosis', 'location_id', 'location_priority', 'county', 'state', 'country',
              'location_start', 'location_end', 'location_species_id', 'species_priority', 'species_name', 'population',
              'sick', 'dead', 'estimated_sick', 'estimated_dead', 'captive', 'age_bias', 'sex_bias',
              # 'species_diagnosis_id', 'species_diagnosis_priority', 'speciesdx', 'causal', 'suspect', 'number_tested',
              'species_diagnosis_id', 'species_diagnosis_priority', 'speciesdx', 'suspect', 'number_tested',
              'number_positive', 'lab']
    # labels = {'event_id': 'Event ID', 'event_reference': 'User Event Reference', 'event_type': 'Event Type',
    labels = {'event_id': 'Event ID', 'event_type': 'Event Type',
              'complete': 'WHISPers Record Status', 'organization': 'Organization', 'start_date': 'Event Start Date',
              'end_date': 'Event End Date', 'affected_count': 'Number Affected', 'event_diagnosis': 'Event Diagnosis',
              'location_id': 'Location ID', 'location_priority': 'Location Priority',
              'county': 'County (or equivalent)', 'state': 'State (or equivalent)', 'country': 'Country',
              'location_start': 'Location Start Date', 'location_end': 'Location End Date',
              'location_species_id': 'Location Species ID', 'species_priority': 'Species Priority',
              'species_name': 'Species', 'population': 'Population', 'sick': 'Known Sick', 'dead': 'Known Dead',
              'estimated_sick': 'Estimated Sick', 'estimated_dead': 'Estimated Dead', 'captive': 'Captive',
              'age_bias': 'Age Bias', 'sex_bias': 'Sex Bias', 'species_diagnosis_id': 'Species Diagnosis ID',
              'species_diagnosis_priority': 'Species Diagnosis Priority', 'speciesdx': 'Species Diagnosis',
              # 'causal': 'Significance of Diagnosis for Species', 'suspect': 'Species Diagnosis Suspect',
              'suspect': 'Species Diagnosis Suspect',
              'number_tested': 'Number Assessed', 'number_positive': 'Number with this Diagnosis', 'lab': 'Lab'}


class EventDetailViewSet(ReadOnlyHistoryViewSet):
    """
    list:
    Returns a list of all event details.
    
    read:
    Returns an event detail.
    
    flat:
    Returns a flattened response for an event detail by id.
    """

    schema = AutoSchema(operation_id_base="EventDetail")
    serializer_class = EventDetailSerializer

    @action(detail=True)
    def flat(self, request, pk):
        # pk = self.request.parser_context['kwargs'].get('pk', None)
        queryset = FlatEventDetails.objects.filter(event_id=pk)
        serializer = FlatEventDetailSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data, status=200)

    # override the default renderers to use a csv renderer when requested
    def get_renderers(self):
        frmt = self.request.query_params.get('format', None) if self.request else None
        if frmt is not None and frmt == 'csv':
            renderer_classes = (CSVEventDetailRenderer,) + tuple(api_settings.DEFAULT_RENDERER_CLASSES)
        else:
            renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES)
        return [renderer_class() for renderer_class in renderer_classes]

    # override the default finalize_response to assign a filename to CSV files
    # see https://github.com/mjumbewu/django-rest-framework-csv/issues/15
    def finalize_response(self, request, *args, **kwargs):
        response = super(viewsets.ReadOnlyModelViewSet, self).finalize_response(request, *args, **kwargs)
        renderer_format = self.request.accepted_renderer.format if self.request else ''
        if renderer_format == 'csv':
            fileextension = '.csv'
            filename = 'event_details_'
            filename += dt.now().strftime("%Y") + '-' + dt.now().strftime("%m") + '-' + dt.now().strftime("%d")
            filename += fileextension
            response['Content-Disposition'] = "attachment; filename=%s" % filename
            response['Access-Control-Expose-Headers'] = 'Content-Disposition'
        return response

    # override the default queryset to allow filtering by URL arguments
    def get_queryset(self):
        user = get_request_user(self.request)
        queryset = Event.objects.all()

        if not user or not user.is_authenticated:
            return queryset.filter(public=True)

        # for pk requests, non-public data can only be returned to the owner or their org or collaborators or admins
        elif self.action == 'retrieve':
            pk = self.request.parser_context['kwargs'].get('pk', None)
            if pk is not None and pk.isdigit():
                queryset = Event.objects.filter(id=pk)
                if queryset:
                    obj = queryset[0]
                    if not obj:
                        raise NotFound
                    else:
                        read_collaborators = []
                        write_collaborators = []
                        if obj.read_collaborators:
                            read_collaborators = list(
                                User.objects.filter(readevents=obj.id).values_list('id', flat=True))
                        if obj.write_collaborators:
                            write_collaborators = list(
                                User.objects.filter(writeevents=obj.id).values_list('id', flat=True))
                        if (user.id == obj.created_by.id or user.organization.id == obj.created_by.organization.id
                                or user.organization.id in obj.created_by.organization.parent_organizations
                                or user.id in read_collaborators or user.id in write_collaborators
                                or user.role.is_superadmin or user.role.is_admin):
                            return queryset
                        else:
                            return queryset.filter(public=True)
            raise NotFound
        # for non-user-specific event requests, try to return the (old default) public data
        #  AND any private data the user should be able to see
        else:
            # queryset = queryset.filter(public=True)
            public_queryset = queryset.filter(public=True).distinct()
            personal_queryset = queryset.filter(
                Q(created_by__exact=user.id) | Q(created_by__organization__exact=user.organization.id)
                | Q(read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])).distinct()
            queryset = public_queryset | personal_queryset
            return queryset
