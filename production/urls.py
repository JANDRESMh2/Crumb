from django.urls import path

from . import views

app_name = 'production'

urlpatterns = [
    path('scheduled-orders/', views.scheduled_order_list, name='scheduled_orders'),
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
        'history-tracking/',
        views.history_tracking,
        name='history_tracking',
    ),
    path(
        'sales/',
        views.sales_list,
        name='sales_list',
    ),
    path(
        'sales/analytics/',
        views.sales_analytics,
        name='sales_analytics',
    ),
    path(
        'losses/',
        views.loss_report,
        name='loss_report',
    ),
    path(
        'daily-closing/',
        views.daily_closing,
        name='daily_closing',
    ),
    path(
        'daily-closing/<uuid:closing_id>/',
        views.daily_closing_detail,
        name='daily_closing_detail',
    ),
    path(
        'daily-closing/<uuid:closing_id>/export/',
        views.daily_closing_export,
        name='daily_closing_export',
    ),
]
