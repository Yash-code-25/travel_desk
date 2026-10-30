"""
Django settings for the Travel Desk project.

Everything security-sensitive is read from environment variables, so the same code
runs safely in development and production:

    DJANGO_DEBUG=false
    DJANGO_SECRET_KEY=<long random string>
    DJANGO_ALLOWED_HOSTS=travel.example.com
    DJANGO_CSRF_TRUSTED_ORIGINS=https://travel.example.com
    DJANGO_ADMIN_URL=<hard-to-guess-path>/
    DJANGO_DEMO_MODE=false
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default):
    return [v.strip() for v in os.environ.get(name, default).split(',') if v.strip()]


# ------------------------------------------------------------------ core
DEBUG = env_bool('DJANGO_DEBUG', True)

def _dev_secret_key():
    """Development only: a random key created once and kept in backend/.dev_secret_key
    (git-ignored), so no secret key is ever written in the source code."""
    path = BASE_DIR / '.dev_secret_key'
    if not path.exists():
        from django.core.management.utils import get_random_secret_key
        path.write_text(get_random_secret_key())
    return path.read_text().strip()


SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or (_dev_secret_key() if DEBUG else '')
if not SECRET_KEY:
    raise ImproperlyConfigured('Set a strong DJANGO_SECRET_KEY environment variable in production.')

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')

# React dev server (Vite) runs on this address and proxies /api to Django.
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS', 'http://localhost:5174,http://127.0.0.1:5174')

# Django admin lives on a configurable, non-obvious path (bots scan /admin/).
ADMIN_URL = os.environ.get('DJANGO_ADMIN_URL', 'secure-admin/')

# One-click demo logins on the sign-in page. Never enable in production.
DEMO_MODE = env_bool('DJANGO_DEMO_MODE', DEBUG)


# ------------------------------------------------------------------ apps
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'desk',
]

REST_FRAMEWORK = {
    # Login with a Django session cookie (React sends the CSRF token on every POST).
    # Our subclass returns 401 (not 403) when the session is missing/expired.
    'DEFAULT_AUTHENTICATION_CLASSES': ['desk.security.SessionAuth'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_PAGINATION_CLASS': 'desk.pagination.Pagination',
    # JSON only: no browsable-API HTML page (faster, and less exposed surface).
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    # Rate limits: stop scripted abuse and password guessing.
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',
        'user': '600/min',
        'login': '10/min',  # sign-in, demo sign-in and change-password
    },
    'EXCEPTION_HANDLER': 'desk.security.exception_handler',  # logs "permission denied" attempts
}

AUTHENTICATION_BACKENDS = ['desk.security.LockoutModelBackend']

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # serves the React build + admin static files
    'desk.middleware.SecurityHeadersMiddleware',
    'django.middleware.gzip.GZipMiddleware',  # smaller JSON responses
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'desk.middleware.PasswordChangeRequiredMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

import dj_database_url

# DATABASE_URL set -> Supabase Postgres. Not set -> local SQLite (dev and tests).
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
        conn_health_checks=True,
    )
}
# Shared cache for lockouts, rate limits and throttles. Stored in the database so it
# survives restarts and is shared by every server process (an in-memory cache isn't).
# For heavy traffic switch to Redis: django.core.cache.backends.redis.RedisCache.
# One-time setup: python manage.py createcachetable
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'desk_cache',
    }
}


# ------------------------------------------------------------------ passwords
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ------------------------------------------------------------------ sessions, cookies, headers
SESSION_COOKIE_AGE = 2 * 60 * 60        # signed out after 2 hours without activity...
SESSION_SAVE_EVERY_REQUEST = True       # ...because every request extends the session
SESSION_COOKIE_HTTPONLY = True          # JavaScript can't read the session cookie
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = False            # React must read it to send the X-CSRFToken header
X_FRAME_OPTIONS = 'DENY'                # no clickjacking via iframes
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'

if not DEBUG:
    # HTTPS only in production.
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SSL_REDIRECT', True)
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # only behind a trusted reverse proxy
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Request size limits (ticket uploads are capped separately at MAX_TICKET_SIZE_MB).
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 200


# ------------------------------------------------------------------ security rules
LOGIN_MAX_FAILURES = 5          # failed sign-ins per username before lockout
LOGIN_MAX_FAILURES_PER_IP = 20  # failed sign-ins per IP address before lockout
LOGIN_LOCKOUT_MINUTES = 15


# ------------------------------------------------------------------ app data & rules
# Uploaded tickets. They are NOT served publicly; only via the permission-checked API.
MEDIA_ROOT = BASE_DIR / 'media'

APPROVAL_SLA_HOURS = 48        # pending longer than this -> shown as "Overdue"
MAX_TRIP_DAYS = 60             # longer trips are refused
MAX_BOOKING_AHEAD_DAYS = 365   # can't request travel more than a year ahead
MAX_TICKET_SIZE_MB = 5
ALLOWED_TICKET_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg']
COST_OVERRUN_ALERT_PERCENT = 20  # warn approver if actual cost exceeds estimate by this much
AUTO_CLOSE_INTERVAL_SECONDS = 60  # expire/complete past trips at most once a minute, not on every request


# ------------------------------------------------------------------ misc
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'  # `python manage.py collectstatic` copies Django admin files here
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

# The built React app (`npm run build` in frontend/) is served from the site root:
# https://yoursite/ -> index.html, /assets/... -> JS/CSS. Only used once it has been built.
FRONTEND_BUILD = BASE_DIR / 'frontend_build'
if FRONTEND_BUILD.exists():
    WHITENOISE_ROOT = FRONTEND_BUILD
    WHITENOISE_INDEX_FILE = True

# ------------------------------------------------------------------ email
# Without DJANGO_EMAIL_HOST, emails are printed in the Django terminal (development).
# Production (e.g. Office 365): DJANGO_EMAIL_HOST=smtp.office365.com, DJANGO_EMAIL_PORT=587,
#   DJANGO_EMAIL_USER=traveldesk@yourcompany.in, DJANGO_EMAIL_PASSWORD=..., DJANGO_FROM_EMAIL=same address
if os.environ.get('DJANGO_EMAIL_HOST'):
    MAILERS = {
        'default': {
            'BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
            'OPTIONS': {
                'host': os.environ['DJANGO_EMAIL_HOST'],
                'port': int(os.environ.get('DJANGO_EMAIL_PORT', '587')),
                'username': os.environ.get('DJANGO_EMAIL_USER', ''),
                'password': os.environ.get('DJANGO_EMAIL_PASSWORD', ''),
                'use_tls': env_bool('DJANGO_EMAIL_USE_TLS', True),
                'timeout': 15,
            },
        },
    }
else:
    MAILERS = {'default': {'BACKEND': 'django.core.mail.backends.console.EmailBackend'}}

DEFAULT_FROM_EMAIL = os.environ.get('DJANGO_FROM_EMAIL', 'Travel Desk <no-reply@localhost>')
# Link put in welcome / password-reset emails.
PORTAL_URL = os.environ.get('DJANGO_PORTAL_URL', 'http://localhost:5174')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {
        'django.security': {'handlers': ['console'], 'level': 'WARNING'},
        'desk.security': {'handlers': ['console'], 'level': 'INFO'},
    },
}
