from django.urls import path
from rest_framework.routers import SimpleRouter

from . import profiles, security_views, views

# SimpleRouter: no public "API root" page listing every endpoint.
router = SimpleRouter()
router.register('requests', views.TravelRequestViewSet, basename='request')
router.register('security/events', security_views.EventViewSet, basename='security-event')
router.register('security/users', security_views.EmployeeViewSet, basename='security-user')

urlpatterns = [
    path('auth/csrf/', views.csrf),
    path('auth/me/', views.me),
    path('auth/login/', views.login_view),
    path('auth/demo-login/', views.demo_login),
    path('auth/logout/', views.logout_view),
    path('auth/change-password/', views.change_password),
    path('auth/activity/', views.my_activity),
    path('profile/', profiles.my_profile),
    path('profiles/<int:user_id>/', profiles.profile_detail),
    path('profiles/<int:user_id>/files/<str:doc>/', profiles.profile_file),
    path('security/overview/', security_views.overview),
    path('dashboard/', views.dashboard),
    path('desk/agents/', views.desk_agents),
    path('desk/analytics/', views.desk_analytics),
    path('notifications/', views.notifications),
    path('notifications/read/', views.notifications_read),
] + router.urls
