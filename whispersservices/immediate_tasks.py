from celery import shared_task, current_task
import re
from datetime import datetime
from rest_framework.settings import api_settings
from django.core.mail import EmailMultiAlternatives
from whispersservices.models import *


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


def send_notification_template_message_keyerror_email(template_name, encountered_key, expected_keys):
    recip = EMAIL_WHISPERS
    subject = "WHISPERS ADMIN: Notification Message Template KeyError"
    body = "The \"" + template_name + "\" Notification Message Template encountered a KeyError"
    body += " at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S") + ". Encountered " + str(encountered_key.args[0])
    body += ", which is not in the list of expected keys:"
    str_keys = ""
    for key in expected_keys:
        str_keys += ", " + str(key)
    str_keys = str_keys.replace(", ", "", 1)
    body += " [" + str_keys + "]."
    notif_email = construct_notification_email(recip, subject, body, False)
    print(notif_email.__dict__)


def send_missing_notification_template_message_email(task_name, template_name):
    recip = EMAIL_WHISPERS
    subject = "WHISPERS ADMIN: Notification Message Template Not Found During " + task_name + " task"
    body = "The \"" + template_name + "\" Notification Message Template was not found"
    body += " at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    notif_email = construct_notification_email(recip, subject, body, False)
    print(notif_email.__dict__)


def send_missing_notification_cue_standard_email(user, template_name):
    recip = EMAIL_WHISPERS
    subject = "WHISPERS ADMIN: Standard Notification Cue Not Found During standard_notifications task"
    body = "The \"" + template_name + "\" Standard Notification Cue was not found for user "
    body += user.first_name + " " + user.last_name + " (username " + user.username + ", ID " + str(user.id) + ")"
    body += " at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    notif_email = construct_notification_email(recip, subject, body, False)
    print(notif_email.__dict__)


def send_missing_configuration_value_email(record_name, message="A default value was used instead."):
    recip = EMAIL_WHISPERS
    subject = "WHISPERS ADMIN: Configuration Value Not Found"
    body = "A configuration value ('" + record_name + "') was not found in the Configuration table."
    body += " Problem encountered at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S") + ". " + message
    notif_email = construct_notification_email(recip, subject, body, False)
    print(notif_email.__dict__)


def send_wrong_type_configuration_value_email(record_name, encountered_type, expected_type,
                                              message="A default value was used instead."):
    recip = EMAIL_WHISPERS
    subject = "WHISPERS ADMIN: Configuration Value Wrong Type"
    body = "A configuration value ('" + record_name + "') in the Configuration table contained the wrong data type."
    body += "Encountered " + encountered_type + " when " + expected_type + " was expected."
    body += " Problem encountered at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S") + ". " + message
    notif_email = construct_notification_email(recip, subject, body, False)
    print(notif_email.__dict__)


whispers_admin_user_record = Configuration.objects.filter(name='whispers_admin_user').first()
if whispers_admin_user_record:
    if whispers_admin_user_record.value.isdecimal():
        WHISPERS_ADMIN_USER_ID = int(whispers_admin_user_record.value)
    else:
        WHISPERS_ADMIN_USER_ID = settings.WHISPERS_ADMIN_USER_ID
        encountered_type = type(whispers_admin_user_record.value).__name__
        send_wrong_type_configuration_value_email('whispers_admin_user', encountered_type, 'int')
else:
    WHISPERS_ADMIN_USER_ID = settings.WHISPERS_ADMIN_USER_ID
    send_missing_configuration_value_email('whispers_admin_user')

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

email_boilerplate_record = Configuration.objects.filter(name='email_boilerplate').first()
if email_boilerplate_record:
    EMAIL_BOILERPLATE = email_boilerplate_record.value
else:
    EMAIL_BOILERPLATE = settings.EMAIL_BOILERPLATE
    send_missing_configuration_value_email('email_boilerplate')


def construct_notification_email(recipient_email, subject, html_body, include_boilerplate=True):

    # append the boilerplate text to the end of the email body
    if include_boilerplate:
        html_body += EMAIL_BOILERPLATE

    # create a plain text body by remove HTML tags from the html_body
    body = html_body
    body = body.replace('<h1>', '').replace('</h1>', '\r\n').replace('<h2>', '').replace('</h2>', '\r\n')
    body = body.replace('<h3>', '').replace('</h3>', '\r\n').replace('<h4>', '').replace('</h4>', '\r\n')
    body = body.replace('<h5>', '').replace('</h5>', '\r\n').replace('<p>', '').replace('</p>', '\r\n')
    body = body.replace('<span>', '').replace('</span>', ' ').replace('<strong>', '').replace('</strong>', '')
    body = body.replace('<br>', '').replace('<br />', '\r\n').replace('<br/>', '\r\n').replace('&nbsp;', ' ')
    body = body.replace('<div>', '').replace('</div>', '\r\n').replace('<table>', '').replace('</table>', '\r\n')
    body = body.replace('<thead>', '').replace('</thead>', '\r\n').replace('<tbody>', '').replace('</tbody>', '\r\n')
    body = body.replace('<tr>', '').replace('</tr>', '\r\n').replace('<td>', '').replace('</td>', ' ')
    body = re.sub('<a.*?>|</a>', '', body)
    body = body.replace('</a>', '')
    # body += url
    from_address = EMAIL_WHISPERS
    to_list = [recipient_email, ]
    bcc_list = []
    reply_list = [EMAIL_WHISPERS, ]
    headers = None
    email = EmailMultiAlternatives(subject, body, from_address, to_list, bcc_list, reply_to=reply_list, headers=headers)
    email.attach_alternative(html_body, "text/html")
    if settings.ENVIRONMENT in ['production', 'test']:
        try:
            email.send(fail_silently=False)
        except TypeError:
            message = "Send email failed, please contact the administrator."
            print(jsonify_errors(message))
    else:
        print(email.__dict__)
    return email


@shared_task(name='generate_notification_task')
def generate_notification(recipients, source, event_id, client_page, subject, body,
                          send_email=False, email_to=None):
    if not recipients or not subject or not body:
        # notify admins of error
        new_recip = EMAIL_WHISPERS
        new_subject = "WHISPERS ADMIN: Problem Encountered During generate_notification_task"
        new_body = "A problem was encountered while generating a notification. No notification was created."
        new_body += " The cause of the problem was"
        if not recipients and not subject and not body:
            new_body += " a null recipient list and a null subject and a null body."
        elif not recipients and not subject:
            new_body += " a null recipient list and a null subject."
        elif not recipients and not body:
            new_body += " a null recipient list and a null body."
        elif not subject and not body:
            new_body += " a null subject and a null body."
        elif not recipients:
            new_body += " a null recipient list."
        elif not subject:
            new_body += " a null subject."
        elif not body:
            new_body += " a null body."
        elif len(subject) > Notification._meta.get_field('subject').max_length:
            new_body += " the subject length was greater than the maximum allowed length of the subject field."
        new_body += " Problem encountered at " + datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        new_body += " during task " + str(current_task.request.id)
        new_body += "<br /><br />The intended settings of the notification were:"
        new_body += "<br />recipients: " + str(recipients)
        new_body += "<br />source: " + source
        new_body += "<br />event_id: " + str(event_id)
        new_body += "<br />client_page: " + client_page
        new_body += "<br />subject: " + subject
        new_body += "<br />body: " + body
        new_body += "<br />send_email: " + str(send_email)
        new_body += "<br />email_to: " + str(email_to)
        notif_email = construct_notification_email(new_recip, new_subject, new_body, False)
        print(notif_email.__dict__)
    else:
        admin = User.objects.filter(id=WHISPERS_ADMIN_USER_ID).first()
        event = Event.objects.filter(id=event_id).first()
        # ensure no duplicate notification recipients
        recipients = list(set(recipients))
        for recip in recipients:
            user = User.objects.filter(id=recip).first()
            Notification.objects.create(
                recipient=user, source=source, event=event, read=False, client_page=client_page,
                subject=subject, body=body, created_by=admin, modified_by=admin)
        if send_email and email_to is not None:
            # ensure no duplicate email recipients
            email_to = list(set(email_to))
            for recip in email_to:
                construct_notification_email(recip, subject, body, True)
    return True
