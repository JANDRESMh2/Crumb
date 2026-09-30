from django.urls import path

from . import views

app_name = 'production'

urlpatterns = [
    path(
        'products/new/',
        views.product_create,
        name='product_create',
    ),
    path(
        'register/',
        views.daily_production_registration,
        name='register',
    ),
    path(
        '',
        views.production_list,
        name='list',
    ),
]