from rest_framework import permissions
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist


class IsStaff(permissions.BasePermission):
    """
    Custom permission to only allow staff users access to objects.
    """

    def has_permission(self, request, view):
        try:
            # returns True if user is staff, False if user is not staff
            return User.objects.get(username=request.user).is_staff
        except ObjectDoesNotExist:
            # always return False if the user does not exist or is not staff
            return False


class IsActive(permissions.BasePermission):
    """
    Custom permission to only allow active users access to objects.
    """

    def has_permission(self, request, view):
        try:
            # returns True if user is active, False if user is not active
            return User.objects.get(username=request.user).is_active
        except ObjectDoesNotExist:
            # always return False if the user does not exist or is not active
            return False


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the owner of the snippet.
        return obj.created_by == request.user
