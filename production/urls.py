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
        'products/',
        views.product_list,
        name='product_list',
    ),
    path(
        'products/<uuid:product_id>/edit/',
        views.product_edit,
        name='product_edit',
    ),
    path(
        '',
        views.production_list,
        name='list',
    ),
    path(
        'sales/register/',
        views.daily_sales_registration,
        name='sales_register',
    ),
    path(
        'sales/',
        views.sales_list,
        name='sales_list',
    ),
]