from django.urls import path

from . import views

app_name = 'bakery'

urlpatterns = [
    path('setup/', views.bakery_setup, name='setup'),
    path('edit/', views.bakery_edit, name='edit'),
    path('activity/', views.activity_log, name='activity_log'),
    path('', views.bakery_detail, name='detail'),
]
