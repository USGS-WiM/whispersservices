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
            try:
                # fetch user by username and manually check password
                user = get_user_model().objects.get(**{
                    get_user_model().USERNAME_FIELD: userid
                })
                if user.check_password(password):
                    if not user.email_verified:
                        raise AuthenticationFailed({
                            'type': 'unverified_email',
                            'detail': _('User email address has not been verified.')
                        })
                    if not user.is_active:
                        raise AuthenticationFailed({'type': 'user_inactive', 'detail': _('User inactive or deleted.')})
                else:
                    raise AuthenticationFailed({'type': 'invalid_password', 'detail': _('Invalid username/password.')})
            except get_user_model().DoesNotExist:
                raise AuthenticationFailed({'type': 'invalid_password', 'detail': _('Invalid username/password.')})

        return (user, None)


class AuthenticationFailed(exceptions.APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = {'type': 'invalid_password', 'detail': _('Incorrect authentication credentials.')}
    default_code = 'authentication_failed'
