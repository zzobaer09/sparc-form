from django.urls import path

from . import views

app_name = 'registration'

urlpatterns = [
    # Phase 0 stub so the root URL responds while the server is verified.
    # Replaced by the real application form in Phase 2/3.
    path('', views.home, name='home'),
]
