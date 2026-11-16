"""
URL configuration for sparc project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),

    # The ambassador application form (Phase 2/3) lives at the site root.
    path('', include('registration.urls')),

    # OAuth authorisation endpoints for the Gmail API (Phase 4).
    path('init/', include('emails.urls')),
]

# Serve uploaded media (logo, ambassador photos) with the dev server.
# In production a real web server (nginx/Apache) takes over this job -
# see the Phase 6 deployment checklist.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
