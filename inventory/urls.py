from django.urls import path

from . import views

app_name = 'inventory'

urlpatterns = [
    path('ingredients/new/', views.ingredient_create, name='create'),
    path('stock-in/', views.stock_in_create, name='stock_in'),
    path('ingredients/', views.ingredient_list, name='list'),
]
