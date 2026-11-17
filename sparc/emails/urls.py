from django.urls import path

from . import views

app_name = 'emails'

urlpatterns = [
    # OAuth endpoints (PDF one-time setup, step 4).
    path('authorise/', views.authorise, name='authorise'),

    # NOTE: no trailing slash on purpose - the redirect URI registered in
    # Google Cloud (http://localhost:8000/init/oauth2callback) must match
    # the incoming URL byte-for-byte, so Django must route the bare path.
    path('oauth2callback', views.oauth2callback, name='oauth2callback'),
]
