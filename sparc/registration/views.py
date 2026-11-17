from threading import Thread

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render

from emails.models import MailJob
from emails.sender import process_job_in_thread

from .forms import AmbassadorForm


def _is_ajax(request):
    """form.js marks its fetch() calls with X-Requested-With: XMLHttpRequest."""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _errors_for_json(form):
    """Shape the errors for form.js renderErrors(): {field: ['msg', ...]}."""
    return {
        field: [err['message'] for err in messages]
        for field, messages in form.errors.get_json_data().items()
    }


def ambassador_apply(request):
    """Show and process the SPARC Ambassador application form.

    GET  -> render the empty form.
    POST -> validate with AmbassadorForm; on success save the application
            FIRST (PDF step 1: "saves the application, then returns thank
            you at once") and answer immediately. The background mail job
            is created in Phase 4 at the marked hook. AJAX callers get
            JSON; plain browser posts get the /thanks/ page or the form
            re-rendered with field errors.
    """
    if request.method == 'POST':
        form = AmbassadorForm(request.POST, request.FILES)

        if form.is_valid():
            with transaction.atomic():
                ambassador = form.save()

                # PDF step 3: create the mail job (pending) first, then a
                # background thread sends it only AFTER the DB commit, so
                # the thread never reads an unpersisted row and the form
                # answers at once either way.
                job, _ = MailJob.objects.get_or_create(
                    campaign='ambassador_received',
                    ambassador=ambassador,
                    defaults={'to_email': ambassador.email})
                transaction.on_commit(lambda: Thread(
                    target=process_job_in_thread, args=(job.id,),
                    daemon=True).start())

            if _is_ajax(request):
                return JsonResponse({
                    'success': True,
                    'message': 'Application received. Thank you!',
                })
            return redirect('registration:thanks')

        if _is_ajax(request):
            return JsonResponse({'success': False,
                                 'errors': _errors_for_json(form)}, status=400)

        # Non-JavaScript path: re-render with the submitted values and the
        # server-rendered error lists (the template shows {{ form.x.errors }}).
        return render(request, 'registration/apply.html', {'form': form})

    return render(request, 'registration/apply.html', {'form': AmbassadorForm()})


def thanks(request):
    """Confirmation page for non-JavaScript submissions (Phase 2 template)."""
    return render(request, 'registration/thanks.html')
