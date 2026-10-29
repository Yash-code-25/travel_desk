from django.conf import settings
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'Travel Desk administration'

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),  # not at the guessable /admin/
    path('api/', include('desk.urls')),
]
