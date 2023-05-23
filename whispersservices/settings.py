"""
Django settings for whispersservices project.

Generated by 'django-admin startproject' using Django 2.0.

For more information on this file, see
https://docs.djangoproject.com/en/2.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.0/ref/settings/
"""

import os
import json
from django.utils.six import moves

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
SETTINGS_DIR = os.path.dirname(__file__)
PROJECT_PATH = os.path.join(SETTINGS_DIR, os.pardir)
PROJECT_PATH = os.path.abspath(PROJECT_PATH)
TEMPLATE_PATH = os.path.join(PROJECT_PATH, 'templates')

CONFIG = moves.configparser.RawConfigParser(allow_no_value=True)
CONFIG.read(os.path.join(SETTINGS_DIR, 'settings.cfg'))

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.11/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = CONFIG.get('general', 'SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = CONFIG.get('general', 'DEBUG')
ADMIN_ENABLED = False

# ALLOWED_HOSTS = CONFIG.get('general', 'ALLOWED_HOSTS')
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

# CORS_ORIGIN_ALLOW_ALL = CONFIG.get('general', 'CORS_ORIGIN_ALLOW_ALL')
CORS_ORIGIN_ALLOW_ALL = True

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'simple_history',
    'rest_framework',
    'corsheaders',
    'dry_rest_permissions',
    'django_celery_beat',
    'drf_recaptcha',
    'django_filters',
    'whispersapi',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
]

ROOT_URLCONF = 'whispersservices.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [TEMPLATE_PATH],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.BasicAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
}

SESSION_EXPIRE_AT_BROWSER_CLOSE = True

WSGI_APPLICATION = 'whispersservices.wsgi.application'

EMAIL_BACKEND = CONFIG.get('email', 'EMAIL_BACKEND')
EMAIL_HOST = CONFIG.get('email', 'EMAIL_HOST')
EMAIL_HOST_PASSWORD = CONFIG.get('email', 'EMAIL_HOST_PASSWORD')
EMAIL_HOST_USER = CONFIG.get('email', 'EMAIL_HOST_USER')
EMAIL_PORT = CONFIG.get('email', 'EMAIL_PORT')
EMAIL_USE_SSL = CONFIG.get('email', 'EMAIL_USE_SSL')
# Note that EMAIL_USE_SSL does implicit TLS, typically for port 465
#  the alternative is EMAIL_USE_TLS which does explicit TLS, typically for port 587
#  the USGS SMTP Relay documentation says to use prefer port 465 over 25 or 587, so I went with EMAIL_USE_SSL here
EMAIL_TIMEOUT = CONFIG.get('email', 'EMAIL_TIMEOUT')
DEFAULT_FROM_EMAIL = CONFIG.get('email', 'DEFAULT_FROM_EMAIL')

# Database
# https://docs.djangoproject.com/en/2.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': CONFIG.get('databases', 'ENGINE'),
        'NAME': CONFIG.get('databases', 'NAME'),
        'USER': CONFIG.get('databases', 'USER'),
        'PASSWORD': CONFIG.get('databases', 'PASSWORD'),
        'HOST': CONFIG.get('databases', 'HOST'),
        'PORT': CONFIG.get('databases', 'PORT'),
        'CONN_MAX_AGE': 60,
    }
}

AUTH_USER_MODEL = 'whispersapi.User'

# Password validation
# https://docs.djangoproject.com/en/2.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/2.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = CONFIG.get('general', 'TIME_ZONE')

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.0/howto/static-files/

STATIC_ROOT = os.path.join(PROJECT_PATH, 'static')
STATIC_PATH = os.path.join(PROJECT_PATH, 'static/staticfiles')
STATIC_URL = '/static/'

STATICFILES_DIRS = (
    STATIC_PATH,
)

MEDIA_ROOT = os.path.join(PROJECT_PATH, 'media')
MEDIA_URL = '/media/'

CELERY_IMPORTS = ['whispersapi.immediate_tasks', 'whispersapi.scheduled_tasks']
CELERY_BROKER_URL = 'amqp://localhost'
CELERY_RESULT_BACKEND = 'rpc://'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# WHISPers-specific settings (here as backup in case these variables are not in the Configuration database table)
ENVIRONMENT = CONFIG.get('whispers', 'ENVIRONMENT')
SSL_CERT = SETTINGS_DIR + CONFIG.get('whispers', 'SSL_CERT')
STALE_EVENT_PERIODS = CONFIG.get('whispers', 'STALE_EVENT_PERIODS')
APP_WHISPERS_URL = CONFIG.get('whispers', 'APP_WHISPERS_URL')
EMAIL_WHISPERS = CONFIG.get('whispers', 'EMAIL_WHISPERS')
EMAIL_NWHC_EPI = CONFIG.get('whispers', 'EMAIL_NWHC_EPI')
EMAIL_BOILERPLATE = CONFIG.get('whispers', 'EMAIL_BOILERPLATE')
WHISPERS_ADMIN_USER_ID = CONFIG.get('whispers', 'WHISPERS_ADMIN_USER_ID')
NWHC_ORG_ID = CONFIG.get('whispers', 'NWHC_ORG_ID')
HFS_LOCATIONS = CONFIG.get('whispers', 'HFS_LOCATIONS')
GEONAMES_USERNAME = CONFIG.get('whispers', 'GEONAMES_USERNAME')
GEONAMES_API = CONFIG.get('whispers', 'GEONAMES_API')
FLYWAYS_API = CONFIG.get('whispers', 'FLYWAYS_API')

# How to generate a reCAPTCHA secret key for local development:
# 1. Register for an API key pair: http://www.google.com/recaptcha/admin
# 2. When you register for the API key pair:
#    - select the reCAPTCHA type as v2, "I am not a robot" checkbox
#    - add the domains "localhost" and "127.0.0.1"
#    - for the rest of the form the defaults are fine
# 3. Put the secret key portion into settings.cfg as the value of
#    DRF_RECAPTCHA_SECRET_KEY under section [security]
# 4. Use the site id in the environment.ts file on the client as the value of
#    "recaptcha_site_key"
DRF_RECAPTCHA_SECRET_KEY = CONFIG.get('security', 'DRF_RECAPTCHA_SECRET_KEY')


def get_api_version():
    version = ""
    try:
        file_path = os.path.join(PROJECT_PATH, 'code.json')
        f = open(file_path, 'r')
        data = json.load(f)
        if 'version' in data[0]:
            version = data[0]['version']
    except OSError:
        pass
    return version


WHISPERS_API_VERSION = get_api_version()
