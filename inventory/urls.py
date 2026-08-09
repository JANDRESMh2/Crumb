from django.urls import path

from . import views

app_name = 'inventory'

urlpatterns = [
    path('ingredients/new/', views.ingredient_create, name='create'),
    path('ingredients/', views.ingredient_list, name='list'),
]
