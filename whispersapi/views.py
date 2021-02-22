import re
from datetime import date
from datetime import datetime as dt
from collections import OrderedDict
from django.core.mail import EmailMessage
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import Now
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
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
from whispersapi.tokens import email_verification_token
from whispersapi.serializers import *
from whispersapi.models import *
from whispersapi.filters import *
from whispersapi.permissions import *
from whispersapi.pagination import *
from whispersapi.authentication import *
from whispersapi.immediate_tasks import *
from dry_rest_permissions.generics import DRYPermissions
from django.shortcuts import get_object_or_404
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

def get_whispers_email_address():
    whispers_email_address = Configuration.objects.filter(name='whispers_email_address').first()
    if whispers_email_address:
        if whispers_email_address.value.count('@') == 1:
            EMAIL_WHISPERS = whispers_email_address.value
        else:
            EMAIL_WHISPERS = settings.EMAIL_WHISPERS
            encountered_type = type(whispers_email_address.value).__name__
            send_wrong_type_configuration_value_email('whispers_email_address', encountered_type, 'email_address')
    else:
        EMAIL_WHISPERS = settings.EMAIL_WHISPERS
        send_missing_configuration_value_email('whispers_email_address')

def get_nhwc_org_id():
    nwhc_org_record = Configuration.objects.filter(name='nwhc_organization').first()
    if nwhc_org_record:
        if nwhc_org_record.value.isdecimal():
            NWHC_ORG_ID = int(nwhc_org_record.value)
        else:
            NWHC_ORG_ID = settings.NWHC_ORG_ID
            encountered_type = type(nwhc_org_record.value).__name__
            send_wrong_type_configuration_value_email('nwhc_organization', encountered_type, 'int')
    else:
        NWHC_ORG_ID = settings.NWHC_ORG_ID
        send_missing_configuration_value_email('nwhc_organization')
    return NWHC_ORG_ID


def update_modified_fields(obj, request):
    # update the modified fields so that the model is aware of who performed this delete,
    #  which will bubble up to the event modified fields
    obj.modified_by = request.user
    obj.modified_date = date.today()
    obj.save(update_fields=['modified_by', 'modified_date'])


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
    EMAIL_WHISPERS = get_whispers_email_address()
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
    msg_tmp = NotificationMessageTemplate.objects.filter(name='New Lookup Item Request').first()
    if not msg_tmp:
        send_missing_notification_template_message_email('generate_notification_request_new', 'New Lookup Item Request')
    else:
        try:
            subject = msg_tmp.subject_template.format(lookup_table=lookup_table, lookup_item=request.data)
        except KeyError as e:
            send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
            subject = ""
        try:
            body = msg_tmp.body_template.format(first_name=user.first_name, last_name=user.last_name, email=user.email,
                                                organization=user.organization.name, lookup_table=lookup_table,
                                                lookup_item=request.data)
        except KeyError as e:
            send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
            body = ""
        event = None
        # source: User requesting a new option.
        source = user.username
        # recipients: WHISPers admin team
        recipients = list(User.objects.filter(role__in=[1, 2]).values_list('id', flat=True))
        # email forwarding: Automatic, to whispers@usgs.gov
        email_to = [User.objects.filter(id=1).values('email').first()['email'], ]
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
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, ]

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
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter,]

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

    alert_collaborator:
    Sends an alert notification to a collaborator (or list of collaborators) of this event.

    request_collaboration:
    Sends a notification to the event owner and their superiors asking for the requester to become a collaborator on this event
    """

    queryset = Event.objects.all()
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
            if (not isinstance(recipient_ids, list) or len(recipient_ids) == 0
                    or not all(isinstance(x, int) for x in recipient_ids)):
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
        recipient_ids = []
        recipient_names = ''
        for recipient in recipients:
            recipient_ids.append(recipient.id)
            recipient_names += ", " + recipient.first_name + " " + recipient.last_name
        recipient_names = recipient_names.replace(", ", "", 1)
        # email forwarding: Automatic, to all users included in the notification request.
        email_to = list(User.objects.filter(id__in=recipient_ids).values_list('email', flat=True))
        msg_tmp = NotificationMessageTemplate.objects.filter(name='Alert Collaborator').first()
        if not msg_tmp:
            send_missing_notification_template_message_email('eventviewset_alert_collaborator', 'Alert Collaborator')
        else:
            try:
                subject = msg_tmp.subject_template.format(event_id=event.id)
            except KeyError as e:
                send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                subject = ""
            try:
                body = msg_tmp.body_template.format(first_name=user.first_name, last_name=user.last_name,
                                                    organization=user.organization.name, event_id=event.id,
                                                    comment=comment, recipients=recipient_names)
            except KeyError as e:
                send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                body = ""
            generate_notification.delay(recipient_ids, source, event.id, 'event', subject, body, True, email_to)

        # Collaborator alert is also logged as an event-level comment.
        comment += "\r\nAlert sent to: " + recipient_names
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

        msg_tmp = NotificationMessageTemplate.objects.filter(name='Collaboration Request').first()
        if not msg_tmp:
            send_missing_notification_template_message_email('eventviewset_request_collaboration',
                                                             'Collaboration Request')
        else:
            try:
                subject = msg_tmp.subject_template.format(event_id=event.id)
            except KeyError as e:
                send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                subject = ""
            # {first_name,last_name,organization,event_id,comment,email}
            try:
                body = msg_tmp.body_template.format(first_name=user.first_name, last_name=user.last_name,
                                                    email=user.email, organization=user.organization, event_id=event.id,
                                                    comment=request.data)
            except KeyError as e:
                send_notification_template_message_keyerror_email(msg_tmp.name, e, msg_tmp.message_variables)
                body = ""
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
        if not self.request:
            return Event.objects.none()
        else:
            queryset = self.queryset

        user = get_request_user(self.request)

        # all requests from anonymous or public users must only return public data
        if not user or not user.is_authenticated or user.role.is_public:
            return queryset.filter(public=True)
        # admins have full access to all fields
        elif user.role.is_superadmin or user.role.is_admin:
            return queryset
        # for all non-admins, pk requests can only return non-public data to the owner or their org or collaborators
        elif self.action in PK_REQUESTS:
            pk = self.request.parser_context['kwargs'].get('pk', None)
            if pk is not None and pk.isdecimal():
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
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
        return super(EventEventGroupViewSet, self).destroy(request, *args, **kwargs)

    # override the default queryset to allow filtering by user type
    def get_queryset(self):
        user = get_request_user(self.request)
        # "Biologically Equivalent (Public)" category only type visible to users not on WHISPers staff
        if not user or not user.is_authenticated:
            return EventEventGroup.objects.filter(eventgroup__category__name='Biologically Equivalent (Public)')
        # admins have access to all records
        NWHC_ORG_ID = get_nhwc_org_id()
        if user.role.is_superadmin or user.role.is_admin or user.organization.id == NWHC_ORG_ID:
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
        NWHC_ORG_ID = get_nhwc_org_id()
        if user.role.is_superadmin or user.role.is_admin or user.organization.id == NWHC_ORG_ID:
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
        NWHC_ORG_ID = get_nhwc_org_id()
        if user.role.is_superadmin or user.role.is_admin or user.organization.id == NWHC_ORG_ID:
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
    # not visible in whispersapi

    serializer_class = EventAbstractSerializer
    queryset = EventAbstract.objects.all()
    filterset_class = EventAbstractFilter

    def destroy(self, request, *args, **kwargs):
        # if the related event is complete, no relates to abstracts can be deleted
        if self.get_object().event.complete:
            message = "Abstracts from a complete event may not be changed"
            message += " unless the event is first re-opened by the event owner or an administrator."
            raise serializers.ValidationError(message)
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
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
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
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
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
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
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
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
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
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
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
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
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
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
    filterset_class = AdministrativeLevelTwoFilter

    @action(detail=False, methods=['post'], parser_classes=(PlainTextParser,))
    def request_new(self, request):
        # A request for a new lookup item is made. Partner or above.
        if request is None or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            raise PermissionDenied

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
    Returns a list of all land ownerships.

    create:
    Creates a new land ownership.
    
    read:
    Returns a land ownership by id.
    
    update:
    Updates a land ownership.
    
    partial_update:
    Updates parts of a land ownership.
    
    delete:
    Deletes a land ownership.
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
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
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
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
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
    Returns a list of all age biases.

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
    Returns a list of all sex biases.

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
    filterset_class = DiagnosisFilter

    @action(detail=False, methods=['post'], parser_classes=(PlainTextParser,))
    def request_new(self, request):
        # A request for a new lookup item is made. Partner or above.
        if request is None or not request.user or not request.user.is_authenticated or request.user.role.is_public:
            raise PermissionDenied

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

        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)

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
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
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
        # update the modified fields so that the model is aware of who performed this delete,
        #  which will bubble up to the event modified fields
        update_modified_fields(self.get_object(), request)
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
    """
    list:
    Returns a list of all notifications.

    create:
    Creates a notification.

    read:
    Returns a notification by id.

    update:
    Updates a notification.

    partial_update:
    Updates parts of a notification.

    delete:
    Deletes a notification.

    bulk_update:
    Updates multiple notifications.
    """
    serializer_class = NotificationSerializer
    filterset_class = NotificationFilter

    def get_queryset(self):
        self.kwargs['action'] = getattr(self, 'action', None)
        return self.filter_queryset(Notification.objects.all())

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
                all(isinstance(x, int) for x in item['ids']) or all(x.isdecimal() for x in item['ids'])):
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


class NotificationCuePreferenceViewSet(HistoryViewSet):
    """
    list:
    Returns a list of all notification cue ('trigger') preferences.

    create:
    Creates a notification cue ('trigger') preference.

    read:
    Returns a notification cue ('trigger') preference by id.

    update:
    Updates a notification cue ('trigger') preference.

    partial_update:
    Updates parts of a notification cue ('trigger') preference.

    delete:
    Deletes a notification cue ('trigger') preference.
    """
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
    """
    list:
    Returns a list of all custom notification cues ('triggers').

    create:
    Creates a custom notification cue ('trigger').

    read:
    Returns a custom notification cue ('trigger') by id.

    update:
    Updates a custom notification cue ('trigger').

    partial_update:
    Updates parts of a custom notification cue ('trigger').

    delete:
    Deletes a custom notification cue ('trigger').
    """
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
    """
    list:
    Returns a list of all standard notification cues ('triggers').

    create:
    Creates a standard notification cue ('trigger').

    read:
    Returns a standard notification cue ('trigger') by id.

    update:
    Updates a standard notification cue ('trigger').

    partial_update:
    Updates parts of a standard notification cue ('trigger').

    delete:
    Deletes a standard notification cue ('trigger').
    """
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
    """
    list:
    Returns a list of all standard notification cue ('trigger') types.

    create:
    Creates a standard notification cue ('trigger') type.

    read:
    Returns a standard notification cue ('trigger') type by id.

    update:
    Updates a standard notification cue ('trigger') type.

    partial_update:
    Updates parts of a standard notification cue ('trigger') type.

    delete:
    Deletes a standard notification cue ('trigger') type.
    """
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
    filterset_class = CommentFilter

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

        return self.filter_queryset(queryset)


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
    Returns a list of all users.

    create:
    Creates a user.
    
    read:
    Returns a user by id.
    
    update:
    Updates a user.
    
    partial_update:
    Updates parts of a user.
    
    delete:
    Deletes a user.

    verify_email:
    Returns two lists: one of users whose email addresses match the submitted email addresses, and one of email addresses that had no matches.
    """

    serializer_class = UserSerializer
    filterset_class = UserFilter

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
                        # and that user is affiliate or above (no public users can be collaborators)
                        user = User.objects.filter(email__iexact=item).first()
                        if user and (user.role.is_superadmin or user.role.is_admin or user.role.is_partneradmin
                                     or user.role.is_partnermanager or user.role.is_partner or user.role.is_affiliate):
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

    @transaction.atomic
    @action(detail=True, methods=['get'], permission_classes=[])
    def confirm_email(self, request, pk=None):
        # Bypass overridden get_queryset since user isn't authenticated but
        # needs to be able to confirm email address
        user = get_object_or_404(User, id=pk)
        token = request.GET['token']
        if user and user.email_verified:
            # don't check token if user email is already verified - let user
            # know email is already verified
            return Response({"status": "Email address has already been verified."}, status=200)
        elif user and email_verification_token.check_token(user, token):
            user.is_active = True
            user.email_verified = True
            user.save()
            # If the user requested a role/organization when registering, send
            # those notification emails now
            ucr = UserChangeRequest.objects.filter(created_by=user).first()
            if ucr:
                UserChangeRequestSerializer.send_user_change_request_email(ucr)
            self._send_user_created_email(user)
            serializer_class = self.get_serializer_class()
            serializer = serializer_class(user, context={'request': request})
            return Response(serializer.data)
        elif user:
            # Checking token failed, possibly because it expired. Send to user again.
            UserSerializer.send_email_verification_message(user)
            return Response({"status": "Email verification failed, resending verification email. Please check your inbox and try again."}, status=400)
        else:
            return Response({"status": "Failed to confirm email address."}, status=400)
    
    @action(detail=False, methods=['post'], permission_classes=[])
    def request_password_reset(self, request):
        if 'username' in request.data:
            username = request.data['username']
            user = get_object_or_404(User, username=username)
            # If user is inactive, don't send email but do return the same
            # successful response to prevent leaking who has accounts.
            if user.is_active:
                token = PasswordResetTokenGenerator().make_token(user)
                password_reset_link = (settings.APP_WHISPERS_URL + "?" + urlencode(
                    {'user-id': user.id, 'password-reset-token': token}))
                # create a 'Password Reset' notification
                # source: User that requests a public account
                source = user.username
                # recipients: user
                recipients = [user.id]
                # email forwarding: Automatic, to user's email
                email_to = [user.email]
                # TODO: add protection here for when the msg_tmp is not found (see scheduled_tasks.py for examples)
                msg_tmp = NotificationMessageTemplate.objects.filter(name='Password Reset').first()
                subject = msg_tmp.subject_template
                body = msg_tmp.body_template.format(
                    first_name=user.first_name,
                    last_name=user.last_name,
                    password_reset_link=password_reset_link)
                event = None
                generate_notification.delay(recipients, source, event, 'homepage', subject, body, True, email_to)
            return Response({"status": "Password reset request processed."})
        else:
            raise serializers.ValidationError("Request must include an username.")

    @action(detail=False, methods=['post'], permission_classes=[], serializer_class=None)
    def reset_password(self, request):
        user_id = request.data['id']
        token = request.data['token']
        user = get_object_or_404(User, id=user_id)
        # verify that password follows business rules by using UserSerializer
        data = dict(password=request.data['password'])
        serializer = self.get_serializer_class()(user, data=data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        token_generator = PasswordResetTokenGenerator()
        if token_generator.check_token(user, token):
            # update the password
            user.set_password(serializer.validated_data['password'])
            user.save()
            return Response(serializer.data)
        else:
            return Response({"status": "Password change failed. Please try again with a new password reset request."}, status=400)

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

        return self.filter_queryset(queryset)
    
    def _send_user_created_email(self, user):
        # create a 'User Created' notification
        msg_tmp = NotificationMessageTemplate.objects.filter(name='User Created').first()
        if not msg_tmp:
            send_missing_notification_template_message_email('userserializer_create', 'User Created')
        else:
            subject = msg_tmp.subject_template
            body = msg_tmp.body_template
            event = None
            # source: User that requests a public account
            source = user.username
            # recipients: user, WHISPers admin team
            recipients = list(User.objects.filter(role__in=[1, 2]).values_list('id', flat=True)) + [user.id, ]
            # email forwarding: Automatic, to user's email and to whispers@usgs.gov
            email_to = [User.objects.filter(id=1).values('email').first()['email'], user.email, ]
            generate_notification.delay(recipients, source, event, 'homepage', subject, body, True, email_to)


class AuthView(views.APIView):
    """
    create:
    Determines if the submitted username and password match a user and whether the user is active.
    """

    authentication_classes = (CustomBasicAuthentication,)
    serializer_class = UserSerializer

    def post(self, request):
        user = request.user if request is not None else None
        if user and user.is_authenticated:
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])
        return Response(self.serializer_class(user, context={'request': request, 'view_name': 'auth'}).data)


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
    Returns a list of all user change requests.

    create:
    Creates a user change request.

    read:
    Returns a user change request by id.

    update:
    Updates a user change request.

    partial_update:
    Updates parts of a user change request.

    delete:
    Deletes a user change request.
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
    Returns a list of all user change request responses.

    create:
    Creates a user change request response.

    read:
    Returns a user change request response by id.

    update:
    Updates a user change request response.

    partial_update:
    Updates parts of a user change request response.

    delete:
    Deletes a user change request response.
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

    queryset = Organization.objects.all()
    filterset_class = OrganizationFilter

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
        if not self.request:
            return Organization.objects.none()

        queryset = self.filter_queryset(self.queryset) if self.request.query_params else self.queryset

        user = get_request_user(self.request)

        # all requests from anonymous users must only return published data
        if not user or not user.is_authenticated:
            return queryset.filter(do_not_publish=False)
        # for pk requests, unpublished data can only be returned to the owner or their org or admins
        elif self.action in PK_REQUESTS:
            pk = self.request.parser_context['kwargs'].get('pk', None)
            if pk is not None and pk.isdecimal():
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

    filterset_class = ContactFilter

    @action(detail=False)
    def user_contacts(self, request):
        # limit data to what the user owns and what the user's org owns
        query_params = self.request.query_params if request is not None else None
        queryset = self.build_queryset(query_params, get_user_contacts=True)
        ordering_param = query_params.get('ordering', None) if query_params is not None else None
        if ordering_param is None:
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

        queryset = self.filter_queryset(queryset)

        # ensure that only active contacts are returned unless the user requests inactive
        active = query_params.get('active', None)
        if active is None or active not in ['False', 'false']:
            queryset = queryset.filter(active=True)

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
    filterset_class = SearchFilter

    @action(detail=False)
    def user_searches(self, request):
        # limit data to what the user owns and what the user's org owns
        query_params = self.request.query_params if self.request else None
        queryset = self.build_queryset(query_params, get_user_searches=True)
        ordering_param = query_params.get('ordering', None) if query_params else None
        if ordering_param is None:
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
        resp = []
        for item in queryset:
            resp.append({"data": item['data'], "use_count": item['use_count']})
        return Response(resp, status=200)

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
            queryset = Search.objects.filter(created_by__exact=user)
        # admins, superadmins, and superusers can see everything
        elif user.role.is_superadmin or user.role.is_admin:
            queryset = Search.objects.all()
        # otherwise return nothing
        else:
            return Search.objects.none()

        return self.filter_queryset(queryset)


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
    filterset_class = EventSummaryFilter

    @action(detail=False)
    def get_count(self, request):
        query_params = self.request.query_params if self.request else None
        events = self.build_queryset(query_params, get_user_events=False)
        cnt = events.count() if events else 0
        return Response({"count": cnt})

    @action(detail=False)
    def get_user_events_count(self, request):
        query_params = self.request.query_params if self.request else None
        events = self.build_queryset(query_params, get_user_events=True)
        cnt = events.count() if events else 0
        return Response({"count": cnt})

    @action(detail=False)
    def user_events(self, request):
        # limit data to what the user owns, what the user's org owns, and what has been shared with the user
        query_params = self.request.query_params if self.request else None
        queryset = self.build_queryset(query_params, get_user_events=True)
        ordering_param = query_params.get('ordering', None) if query_params else None
        if ordering_param is None:
            queryset = queryset.order_by('-id')

        frmt = self.request.query_params.get('format', '') if self.request else ''
        if self.request and 'no_page' not in self.request.query_params:
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
        queryset = self.filter_queryset(self.queryset)

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
                | Q(created_by__organization__in=user.organization.child_organizations)
                | Q(read_collaborators__in=[user.id]) | Q(write_collaborators__in=[user.id])).distinct()
            queryset = public_queryset | personal_queryset

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
    Returns a flattened (not nested) response for an event detail by id.
    """

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
            if pk is not None and pk.isdecimal():
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
