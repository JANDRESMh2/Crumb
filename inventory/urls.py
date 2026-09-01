from django.urls import path

from . import views

app_name = 'inventory'

urlpatterns = [
    path('ingredients/new/', views.ingredient_create, name='create'),
    path('stock-in/', views.stock_in_create, name='stock_in'),
    path('stock-consumption/', views.Stock_consumption_registration, name='stock_consumption'),
    path('ingredients/', views.ingredient_list, name='list'),

    path('ingredients/<uuid:ingredient_id>/edit/',
    views.ingredient_edit,
    name='edit',
    ),
    path('ingredients/<uuid:ingredient_id>/delete/',
    views.ingredient_delete,
    name='delete',
    ),
]
