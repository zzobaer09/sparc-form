from django.urls import path

from . import views

app_name = 'registration'

urlpatterns = [
    # The ambassador application form at the site root.
    path('', views.ambassador_apply, name='ambassador_apply'),
]
