from django.shortcuts import render

from .forms import AmbassadorForm


def ambassador_apply(request):
    """Show the SPARC Ambassador application form.

    Phase 2 scope: render the empty form on GET. Phase 3 adds the POST
    handling: validate with AmbassadorForm -> Ambassador.objects.create ->
    MailJob creation -> JsonResponse (AJAX) / thanks page (non-JS).
    """
    return render(request, 'registration/apply.html', {'form': AmbassadorForm()})
