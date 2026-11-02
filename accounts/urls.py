from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('register/', views.user_registration_view, name='register'),
    path('login/', views.user_login_view, name='login'),
]