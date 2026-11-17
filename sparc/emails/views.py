"""Gmail authorisation (OAuth) for the emails app.

Implements the PDF's one-time setup flow:

    /init/authorise/        superuser opens this -> Google consent screen
    /init/oauth2callback    Google returns here -> tokens written to .env

get_credentials() is the piece emails/sender.py reuses on every send.
Tokens live in .env (GOOGLE_CLOUD_TOKEN, GOOGLE_CLOUD_REFRESH_TOKEN) -
never committed, exactly as the PDF requires.
"""
import logging
import os
import threading
import time

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect, render
from django.utils.crypto import constant_time_compare
from dotenv import set_key
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

logger = logging.getLogger(__name__)

# State expiration window for OAuth CSRF protection (10 minutes)
OAUTH_STATE_TIMEOUT_SECONDS = 600

# Same .env file that settings.py loads at startup.
ENV_FILE = str(settings.BASE_DIR / '.env')

AUTH_URI = 'https://accounts.google.com/o/oauth2/auth'
TOKEN_URI = 'https://oauth2.googleapis.com/token'

# One valid credentials object per process; refreshed when it expires.
# The RLock serialises every token refresh and every .env rewrite so two
# sender threads can never race a read-modify-write of the token file.
# It is reentrant because get_credentials() holds it while calling
# _persist_token(), which acquires it again.
_cached_credentials = None
_token_lock = threading.RLock()


def _redirect_uri():
    # Byte-exact match with the URI registered in Google Cloud (PDF step 2).
    # NOTE: no trailing slash - Google compares the redirect URI literally.
    return f'{settings.SITE_URL}/init/oauth2callback'


def _client_config():
    return {
        'web': {
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'project_id': settings.GOOGLE_PROJECT_ID,
            'auth_uri': AUTH_URI,
            'token_uri': TOKEN_URI,
            'auth_provider_x509_cert_url': 'https://www.googleapis.com/oauth2/v1/certs',
            'redirect_uris': [_redirect_uri()],
        }
    }


def _build_flow():
    return Flow.from_client_config(
        _client_config(),
        scopes=settings.GOOGLE_SCOPES,
        redirect_uri=_redirect_uri(),
    )


def _configured():
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def _persist_token(key, value, env_file=ENV_FILE):
    """Write a token back into .env AND the running process environment.

    The process-environment write is what lets get_credentials() pick up
    tokens immediately after the callback - no server restart needed.
    chmod 600: the file holds a long-lived refresh token, so other local
    users must not be able to read it (set_key honours the umask, which
    is usually 644).
    """
    with _token_lock:
        os.environ[key] = value or ''
        set_key(env_file, key, value or '')
        try:
            os.chmod(env_file, 0o600)
        except OSError:
            logger.warning('Could not tighten permissions on %s', env_file)


def get_credentials():
    """Credentials for the Gmail API, or None when (re-)authorisation is needed.

    Tokens are read dynamically from the environment (they are written by
    the callback while the server runs; settings captured at import time
    would be stale). Returns None on invalid_grant etc. - per the PDF the
    fix is to repeat the /init/authorise/ step.
    """
    global _cached_credentials
    if _cached_credentials is not None and _cached_credentials.valid:
        return _cached_credentials

    with _token_lock:
        # Re-read inside the lock: another thread may have refreshed and
        # persisted a new token while we were waiting.
        refresh_token = os.environ.get('GOOGLE_CLOUD_REFRESH_TOKEN')
        if not refresh_token:
            logger.info('get_credentials: no refresh token in .env - '
                        'open /init/authorise/ as a superuser')
            return None  # never authorised (or .env was recreated)

        creds = Credentials(
            token=os.environ.get('GOOGLE_CLOUD_TOKEN') or None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URI,
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=settings.GOOGLE_SCOPES,
        )
        try:
            # Refresh when the token is missing/expired, or when we cannot
            # know (expiry is unknown after a server restart - refresh to
            # be safe).
            if not creds.valid or creds.expiry is None:
                creds.refresh(Request())
        except Exception as exc:
            logger.warning('get_credentials: token refresh failed (%s) - '
                           're-authorisation needed', type(exc).__name__)
            return None

        if creds.token != os.environ.get('GOOGLE_CLOUD_TOKEN'):
            _persist_token('GOOGLE_CLOUD_TOKEN', creds.token)
        _cached_credentials = creds
        return creds


def _superuser_required(view):
    """PDF: the one-time Gmail setup belongs to a superuser, not any staff."""
    return user_passes_test(
        lambda u: u.is_active and u.is_superuser,
        login_url='admin:login')(view)


@_superuser_required
def authorise(request):
    """Start the OAuth consent flow (PDF one-time setup, step 4)."""
    if not _configured():
        return _render_result(
            request,
            'error',
            'DEV_GOOGLE_CLOUD_CLIENT_ID / DEV_GOOGLE_CLOUD_CLIENT_SECRET are '
            'not set in .env - complete the Google Cloud setup first.',
            '')

    flow = _build_flow()
    url, state = flow.authorization_url(
        access_type='offline',   # we need a refresh token for background sends
        prompt='consent',        # always return a refresh token, even on re-auth
    )
    request.session['oauth_state'] = state
    # PKCE: building the consent URL generates a code_verifier (Google's
    # library does this by default) and Google requires the SAME verifier
    # back at token exchange. The Flow object is discarded between the two
    # requests, so the verifier must survive in the session, next to state.
    verifier = getattr(flow, 'code_verifier', None)
    if verifier:
        request.session['oauth_verifier'] = verifier
    logger.info('OAuth authorisation flow started (user %s)', request.user)
    return redirect(url)


@_superuser_required
def oauth2callback(request):
    """Exchange the auth code for tokens and persist them to .env."""
    state_data = request.session.pop('oauth_state', None)
    if isinstance(state_data, dict):
        expected_state = state_data.get('state')
        created_at = state_data.get('created_at', 0)
        is_expired = (time.time() - created_at) > OAUTH_STATE_TIMEOUT_SECONDS
    else:
        expected_state = state_data
        is_expired = False

    incoming_state = request.GET.get('state', '')

    if not expected_state or is_expired or not constant_time_compare(expected_state, incoming_state):
        error_msg = 'Authorisation session expired.' if is_expired else 'State mismatch.'
        return _render_result(
            request,
            'error',
            error_msg,
            'Open /init/authorise/ again to start a new authorisation session.',
            http_status=400,
        )

    if request.GET.get('error'):
        logger.warning('OAuth authorisation failed: %s', request.GET['error'])
        return _render_result(
            request,
            'error',
            f'Google returned: {request.GET["error"]}',
            'access_denied usually means the sending Gmail is not added as a '
            'Test user on the OAuth consent screen.')

    if not _configured():
        return _render_result(request, 'error', 'Client credentials missing in .env.', '')

    flow = _build_flow()
    # Restore the PKCE verifier created during /init/authorise/ - without it
    # Google rejects the token exchange with "invalid_grant: Missing code
    # verifier" (see the comment there).
    verifier = request.session.pop('oauth_verifier', None)
    if verifier:
        flow.code_verifier = verifier
    try:
        flow.fetch_token(code=request.GET.get('code'))
    except Exception as exc:
        # Full detail goes to the log only - raw exception text must not
        # leak internal URLs/identifiers into the browser page.
        logger.warning('OAuth token exchange failed: %s', exc)
        return _render_result(
            request,
            'error', 'Token exchange failed.',
            'Full details are in the server log. redirect_uri_mismatch '
            'means the redirect URI registered in Google Cloud must be '
            'exactly ' + _redirect_uri())

    creds = flow.credentials
    if not creds.refresh_token:
        return _render_result(
            request,
            'error', 'Google did not return a refresh token.',
            'Open /init/authorise/ again - it requests prompt=consent, which '
            'always issues one.')

    _persist_token('GOOGLE_CLOUD_TOKEN', creds.token)
    _persist_token('GOOGLE_CLOUD_REFRESH_TOKEN', creds.refresh_token)
    return _render_result(
        request,
        'ok',
        'GOOGLE_CLOUD_TOKEN and GOOGLE_CLOUD_REFRESH_TOKEN are now filled in .env.',
        'Mail will be sent from MAIL_SENDER. While the Google app is in '
        'Testing status the login ends after 7 days - if a mail says '
        '"re-authorise", simply open /init/authorise/ again.')


def _render_result(request, status, message, detail, http_status=200):
    return render(request, 'emails/authorise_result.html', {
        'status': status,
        'message': message,
        'detail': detail,
        'site_url': settings.SITE_URL,
    }, status=http_status)
