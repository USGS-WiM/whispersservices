import json
from time import sleep
from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives
from whispersservices.serializers import *
from whispersservices.models import *
from celery import shared_task, current_app
from celery.result import AsyncResult


def jsonify_errors(data):
    if isinstance(data, list) or isinstance(data, str):
        # Errors raised as a list are non-field errors.
        if hasattr(settings, 'NON_FIELD_ERRORS_KEY'):
            key = settings.NON_FIELD_ERRORS_KEY
        else:
            key = api_settings.NON_FIELD_ERRORS_KEY
        return {key: data}
    else:
        return data


# TODO: modify to suit the needs of notifications
def construct_notification_email(recipient_email, source, event, link, message):
    subject = "An action by " + source + " requires your attention"
    body = message
    if link == 'event':
        event_id_string = str(event)
        url = settings.APP_WHISPERS_URL + 'event/' + event_id_string
    elif link == 'userdashboard':
        url = settings.APP_WHISPERS_URL + 'usedashboard'
    else:
        url = settings.APP_WHISPERS_URL
    html_body = body + "<a href='" + url + "/'>" + url + "/</a>"
    body = body.replace('<strong>', '').replace('</strong>', '').replace('<br>', '    ').replace('&nbsp;', ' ')
    body += url + "/"
    from_address = settings.EMAIL_WHISPERS
    to_list = [recipient_email, ]
    bcc_list = []
    reply_list = [settings.EMAIL_WHISPERS, ]
    headers = None  # {'Message-ID': 'foo'}
    email = EmailMultiAlternatives(subject, body, from_address, to_list, bcc_list, reply_to=reply_list, headers=headers)
    email.attach_alternative(html_body, "text/html")
    if settings.ENVIRONMENT in ['production', 'test']:
        try:
            email.send(fail_silently=False)
        except TypeError:
            message = "Notification saved but send email failed, please contact the administrator."
            # raise serializers.ValidationError(jsonify_errors(message))
            print(jsonify_errors(message))
    return email


@shared_task(name='generate_notification_task')
def generate_notification(recipients, source, event_id, client_page, message, send_email=False, email_to=None):
    admin = User.objects.filter(id=1).first()
    event = Event.objects.filter(id=event_id).first()
    for recip in recipients:
        user = User.objects.filter(id=recip).first()
        Notification.objects.create(
            recipient=user, source=source, event=event, read=False, client_page=client_page, message=message,
            created_by=admin, modified_by=admin)
        # email: settings.EMAIL_WHISPERS, settings.EMAIL_NWHC_EPI
    if send_email and email_to is not None:
        for recip in email_to:
            notif_email = construct_notification_email(recip, source, event, client_page, message)
            print(notif_email.__dict__)
    return True
