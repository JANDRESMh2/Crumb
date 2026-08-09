"""URL configuration for Crumb project."""
from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('bakery/', include('bakery.urls', namespace='bakery')),
    path('inventory/', include('inventory.urls', namespace='inventory')),
]
