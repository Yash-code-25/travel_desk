from django.contrib import admin

from .models import Notification, Profile, RequestEvent, SecurityEvent, TravelRequest


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'manager', 'department']
    list_filter = ['role']


class EventInline(admin.TabularInline):
    model = RequestEvent
    extra = 0
    readonly_fields = ['actor', 'action', 'from_status', 'to_status', 'comment', 'created_at']


@admin.register(TravelRequest)
class TravelRequestAdmin(admin.ModelAdmin):
    list_display = ['request_code', 'employee', 'service', 'destination', 'start_date', 'status']
    list_filter = ['status', 'service']
    search_fields = ['request_code', 'destination', 'employee__username']
    inlines = [EventInline]


admin.site.register(Notification)


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    """Read-only: the audit log must not be edited or deleted from the admin."""
    list_display = ['created_at', 'type', 'username', 'ip', 'actor', 'detail']
    list_filter = ['type']
    search_fields = ['username', 'ip', 'detail']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
