import json
import os
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = os.environ['SECRET_KEY']
DEBUG = False

def aws_fargate_private_ip():
    with urllib.request.urlopen('http://169.254.170.2/v2/metadata') as response:
        return json.loads(response.read().decode('utf-8'))['Containers'][0]['Networks'][0]['IPv4Addresses'][0]

ALLOWED_HOSTS = \
    [os.environ['ALLOWED_HOST']] if os.environ['ALLOWED_HOST'] == 'localhost' else \
    [os.environ['ALLOWED_HOST'], aws_fargate_private_ip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'authbroker_client',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

AUTHENTICATION_BACKENDS = [
    'app.backends.AuthbrokerBackendAllSuperuser',
]
AUTHBROKER_URL = os.environ['AUTHBROKER_URL']
AUTHBROKER_CLIENT_ID = os.environ['AUTHBROKER_CLIENT_ID']
AUTHBROKER_CLIENT_SECRET = os.environ['AUTHBROKER_CLIENT_SECRET']
LOGIN_REDIRECT_URL = '/admin'

ROOT_URLCONF = 'app.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'app.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': os.environ['DB_NAME'],
        'USER': os.environ['DB_USER'],
        'PASSWORD': os.environ['DB_PASSWORD'],
        'HOST': os.environ['DB_HOST'],
        'PORT': os.environ['DB_PORT'],
    }
}

AUTH_PASSWORD_VALIDATORS = [
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    },
}

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Only used when collectstatic is run
STATIC_ROOT = '/home/django/static/'

# Used when generating URLs for static files
STATIC_URL = '/static/'
