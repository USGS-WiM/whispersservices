from django.contrib.auth import authenticate, get_user_model
from rest_framework import authentication
from rest_framework import exceptions
from rest_framework import status
from django.utils.translation import ugettext_lazy as _


class CustomBasicAuthentication(authentication.BasicAuthentication):

    def authenticate_credentials(self, userid, password, request=None):
        """
        Authenticate the userid and password against username and password
        with optional request for context.
        """
        credentials = {
            get_user_model().USERNAME_FIELD: userid,
            'password': password
        }
        user = authenticate(request=request, **credentials)

        if user is None:
            raise AuthenticationFailed(_('Invalid username/password.'))

        if not user.is_active:
            raise AuthenticationFailed(_('User inactive or deleted.'))

        return (user, None)


class AuthenticationFailed(exceptions.APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = _('Incorrect authentication credentials.')
    default_code = 'authentication_failed'
