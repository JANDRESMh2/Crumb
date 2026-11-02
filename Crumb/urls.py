"""URL configuration for Crumb project."""
from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    # Gives the header switcher the set_language view it posts to.
    path('i18n/', include('django.conf.urls.i18n')),
    path('', views.home, name='home'),
    path('bakery/', include('bakery.urls', namespace='bakery')),
    path('inventory/', include('inventory.urls', namespace='inventory')),
    path('production/', include('production.urls', namespace='production')),
    path('accounts/', include('accounts.urls')),
]
