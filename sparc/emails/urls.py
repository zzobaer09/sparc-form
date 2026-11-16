from django.urls import path

app_name = 'emails'

# Phase 4 mounts the OAuth endpoints here:
#   /init/authorise/         - superuser-only consent start
#   /init/oauth2callback/    - token exchange, writes tokens back to .env
urlpatterns = []
