from django.http import HttpResponse


def home(request):
    """Phase 0 stub view so the root URL responds while runserver is checked.

    Replaced by the real ambassador application form in Phase 2/3.
    """
    return HttpResponse("SPARC 2026 - Ambassador Application. The form arrives in Phase 2/3.")
