"""
URL configuration for auction_project project.
"""

from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [

    # Django Admin
    path(
        'admin/',
        admin.site.urls
    ),

    # Dashboard Preview
    # This temporarily displays dashboard.html directly.
    # Later this will be replaced with a proper dashboard view
    # that retrieves data from PostgreSQL.
    path(
        'dashboard-preview/',
        TemplateView.as_view(
            template_name='dashboard.html'
        ),
        name='dashboard_preview'
    ),
]

# Serve uploaded media files during development
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )