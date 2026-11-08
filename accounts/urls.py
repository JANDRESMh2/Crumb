from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('register/', views.user_registration_view, name='register'),
    path('login/', views.user_login_view, name='login'),
    path('recovery/', views.recovery_request_view, name='recovery_request'),
    path('recovery/verify/', views.recovery_verify_view, name='recovery_verify'),
    path('recovery/resend/', views.recovery_resend_view, name='recovery_resend'),
    path('recovery/password/', views.recovery_password_view, name='recovery_password'),
    path('recovery/complete/', views.recovery_complete_view, name='recovery_complete'),
]
