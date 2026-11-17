# SPARC Ambassador Form & Email — Build Plan

> Source of truth: `docs/SPARC_Ambassador_Form_and_Email.pdf` (SPARC Ambassador Application 2026)
> Assigned to: Muhtasim Fuad Khan Zobaer, Abdul Basit · Deadline: 16 Nov 2026
> Constraint: the project uses **only two apps** — `registration` and `emails`.

---

## ⚠️ PENDING — OAuth setup (user action, required before any real mail sends)

The code side is done (Phase 4) but **Google Cloud credentials are not yet filled in `.env`**.
Until this checklist is done, every application saves fine and its `MailJob` fails with
`Google API needs re-authorisation` — expected, and recoverable later with `send_pending`.

- [ ] Google Cloud Console: new project → enable **Gmail API**
- [ ] OAuth consent screen: External, scope `gmail.send`, add the sending Gmail as **Test user**
- [ ] Credentials → OAuth client ID, type **Web application**; redirect URI (byte-exact, no trailing slash):
      `http://localhost:8000/init/oauth2callback` — plus the live address later
- [ ] Fill `DEV_GOOGLE_CLOUD_CLIENT_ID`, `DEV_GOOGLE_CLOUD_CLIENT_SECRET`, `DEV_GOOGLE_CLOUD_PROJECT_ID` in `.env`
- [ ] Run server as superuser → open `/init/authorise/` → sign in with the sending Gmail → Allow
- [ ] Verify `GOOGLE_CLOUD_TOKEN` / `GOOGLE_CLOUD_REFRESH_TOKEN` are filled in `.env`
- [ ] Resubmit (or run `python manage.py send_pending` in Phase 5) → expect `[OK] … MsgId=…` and the mail in the Gmail Sent folder

*Reminder promised at the end of Phase 5 and in the final wrap-up.*

---

## 1. Project Scan (current state)

| Item | Finding |
|---|---|
| Repo | Git, single commit `start`; working tree clean |
| Runtime | Python 3.14 venv, Django 6.1.3, pip 26.0.1, asgiref 3.13.0, sqlparse 0.6.1 |
| Project | `sparc/sparc/` — stock `startproject` skeleton (SQLite, DEBUG on, no env handling) |
| Apps | `registration/` and `emails/` exist but are 100% boilerplate (empty models/views, no urls/forms/admin) |
| `urls.py` | Only `admin/` mounted |
| `settings.py` | Already contains a custom `MAILERS` dict (console backend) — kept as the mail-configuration block; `SITE_URL`, `MAIL_SENDER`, `GOOGLE_*` not yet defined |
| `.gitignore` | Already anticipates `.env`, `db.sqlite3`, `media_files/ambassador_photos/` (root + app level) |

### Issues found during scan (must fix)

1. **Copy-paste bug:** `emails/apps.py` and `registration/apps.py` both define `class RegistrationConfig`. `emails` must become `EmailsConfig`, or app loading breaks once both are in `INSTALLED_APPS`.
2. Neither app is listed in `INSTALLED_APPS`.
3. No `requirements.txt`, no `.env.example`; `.env` handling not implemented.
4. `docs/` is gitignored — `phase.md` will exist on disk but won't be tracked unless that line is removed from `.gitignore`.
5. No media config yet, while the spec requires `/media_files/SPARC26LogoMin.png` (logo) and photo uploads under `ambassador_photos/`.

---

## 2. Requirements Digest (from the PDF)

### Form — SPARC Ambassador Application 2026

| Section | Field | Type | Rules |
|---|---|---|---|
| 1 Personal | Full name (as on ID) | short | required |
| 1 | Email (all updates go here) | short | required, valid, **unique** |
| 1 | WhatsApp number | short | required |
| 1 | Date of birth | date | required |
| 1 | Gender | choice | Male / Female |
| 2 University | University name | short | required |
| 2 | Department | short | required |
| 2 | Current year of study | dropdown | 1st / 2nd / 3rd / 4th / Postgraduate |
| 2 | Student ID number | short | required |
| 3 IEEE | Are you an IEEE member? | choice | Yes / No |
| 3 | IEEE membership number | short | shown/validated **only if Yes** |
| 3 | IEEE membership grade | dropdown | Student Member / Graduate Student Member / Member / Other (only if Yes) |
| 3 | IEEE Student Branch name | short | only if Yes |
| 3 | Position in the branch | short | e.g. Member, Volunteer, Officer, Chairperson (only if Yes) |
| 4 Photo | Formal photo | file | JPG/PNG, 1 file, **max 10 MB**, required; photo guide shown above upload |
| 4 | Short bio for website | paragraph | **max 50 words**, required |
| 6 About | Why do you want to become a SPARC Ambassador? | paragraph | required |
| 6 | Comfortable activities | checkboxes | social posts & stories / short videos / hanging posters / talking to students & societies / quotes & captions / organizing campus sessions |
| 6 | How did you hear about SPARC? | choice | Social media / Friend / IEEE branch / University / Other |
| 7 Agreement | 4 checkboxes | checkbox | all required (accuracy; name-photo-bio usage; points & ranking; contact by email & WhatsApp) |

Extras: photo guide text above upload; confirmation message after submit (thank-you text incl. "check your email … unique Ambassador Code … follow us on social media").

### Email flow (as specified in the PDF)

1. Form submits → **application saved first**, then "thank you" returned at once (`JsonResponse`).
2. Django creates a **`MailJob` (Pending)** row and starts a **background thread** via `transaction.on_commit`.
3. Thread builds mail (HTML + plain text) and calls **Gmail API `users.messages.send`**; mail is sent from the club Gmail account.
4. Job becomes **Sent** (with Gmail message ID) or **Failed** (with error). A failed mail never loses the application and is re-sent with `python manage.py send_pending`.

OAuth one-time setup: Google Cloud project + Gmail API + Web-application OAuth client with redirect `http://localhost:8000/init/oauth2callback/`; superuser opens `/init/authorise/`; tokens land in `.env` as `GOOGLE_CLOUD_TOKEN` / `GOOGLE_CLOUD_REFRESH_TOKEN`. Testing-mode consent expires after 7 days → re-authorise.

---

## 3. Architectural Plan

### 3.1 Layering

```
Browser (fetch/AJAX)
        │  POST / (multipart form)
        ▼
registration.views  ── form validation (ModelForm + clean_*) ──► registration.models.Ambassador
        │  save first, then JsonResponse (fire-and-forget mail)
        ▼
transaction.on_commit ──► threading.Thread(daemon)
                                 │
                                 ▼
                    emails.sender.process_job_in_thread(job_id)
                                 │  get_credentials() from emails.views
                                 ▼
                    Gmail API users.messages.send (HTML + txt, base64 raw)
                                 │
                                 ▼
                    emails.models.MailJob  (pending → sent / failed)
```

- **Data layer** — `registration.Ambassador` (the application) and `emails.MailJob` (mail ledger). Decoupled by FK; a mail failure never rolls back an application.
- **Form/service layer** — `registration/forms.py` holds all validation; `emails/sender.py` is the mail service (build_service / send_mail / process_job / process_job_in_thread) exactly as the PDF specifies.
- **Presentation layer** — sectioned form template + CSS + small JS (conditional IEEE fields, bio word counter, file pre-checks), success screen.
- **Auth/config layer** — OAuth endpoints in `emails` under `/init/…` (superuser-only); secrets live in `.env`, loaded by `python-dotenv`.

### 3.2 Concurrency model (per spec)

- No Celery/Redis — the PDF mandates a **daemon `Thread`** started **only after DB commit** (`transaction.on_commit`), so the thread never reads a row that isn't persisted.
- `process_job` is **idempotent**: if `status == sent`, it returns immediately (never sends twice). `get_or_create` + `UniqueConstraint(campaign, ambassador)` guarantee one mail per campaign per ambassador.
- `process_job_in_thread` closes the DB connection in `finally` (thread safety).
- `send_pending` retries Pending/Failed jobs with one shared service instance and `sleep(3)` between sends; `--from-id` resumes after failures (Gmail ~500 recipients/day, `rateLimitExceeded`).

### 3.3 Configuration contract (`.env`)

```
DEV_GOOGLE_CLOUD_CLIENT_ID=...
DEV_GOOGLE_CLOUD_CLIENT_SECRET=...
DEV_GOOGLE_CLOUD_PROJECT_ID=...
DEV_SCOPES=https://www.googleapis.com/auth/gmail.send
GOOGLE_MAIL_API_NAME=gmail
GOOGLE_MAIL_API_VERSION=v1
SITE_URL=http://localhost:8000
MAIL_SENDER=IEEE NSU SB Portal <club@gmail.com>
# written back by the OAuth callback:
GOOGLE_CLOUD_TOKEN=
GOOGLE_CLOUD_REFRESH_TOKEN=
# Django:
DJANGO_SECRET_KEY=...
```

`settings.py` additions: both apps in `INSTALLED_APPS`; `SITE_URL`, `MAIL_SENDER`, `GOOGLE_*` read from env; `MEDIA_URL='media_files/'`, `MEDIA_ROOT=BASE_DIR/'media_files'`; project-level `TEMPLATES[0]['DIRS']=[BASE_DIR/'templates']`; keep the existing `MAILERS` block (dev uses console backend as an offline fallback; production mail goes through the Gmail API client).

### 3.4 Data model

**`registration.Ambassador`** (one row per application)

| Field | Type | Notes |
|---|---|---|
| `name` | CharField(120) | as on ID |
| `email` | EmailField, **unique**, db_index | all updates go here |
| `whatsapp` | CharField(20) | light E.164-ish regex check |
| `date_of_birth` | DateField | |
| `gender` | CharField choices | male / female |
| `university`, `department` | CharField(120)/(120) | |
| `year_of_study` | CharField choices | 1st/2nd/3rd/4th/postgraduate |
| `student_id` | CharField(40) | |
| `is_ieee_member` | BooleanField | gates the 4 IEEE fields |
| `ieee_number` | CharField(40), blank | required iff member |
| `ieee_grade` | CharField choices, blank | student/graduate_student/member/other |
| `ieee_branch` | CharField(120), blank | required iff member |
| `ieee_position` | CharField(80), blank | required iff member |
| `photo` | ImageField, upload_to `ambassador_photos/` | JPG/PNG ≤ 10 MB |
| `bio` | TextField | ≤ 50 words |
| `why_ambassador` | TextField | required |
| `activities` | JSONField (list) | 6 checkbox values |
| `heard_from` | CharField choices | social_media/friend/ieee_branch/university/other |
| `agree_*` ×4 | BooleanField | must all be True |
| `created_at` | auto_now_add | audit |

**`emails.MailJob`** — exactly as the PDF: `campaign` (Char 40), `ambassador` FK→`registration.Ambassador` CASCADE, `to_email`, `status` (pending/sent/failed, default pending), `error` (text, blank), `gmail_message_id` (Char 64, blank), `created_at` (auto), `sent_at` (null), `UniqueConstraint(campaign, ambassador, name="one_mail_per_campaign")`.

### 3.5 URL map

| URL | App | Purpose |
|---|---|---|
| `/` | registration | the application form (photo guide, sections) |
| `/` POST | registration | validate → save → create MailJob → respond `JsonResponse({"success": true, "message": ...})` |
| `/thanks/` | registration | static success page (fallback for non-JS) |
| `/init/authorise/` | emails | superuser-only OAuth consent start |
| `/init/oauth2callback/` | emails | token exchange; writes `GOOGLE_CLOUD_TOKEN`(+refresh) back to `.env` |
| `/admin/` | django | Ambassador + MailJob admin (status counts, resend hooks) |
| `/media_files/…` | static serve | `SPARC26LogoMin.png`, uploaded photos (dev: `static()` helper) |

---

## 4. Essential Python Packages

### Required (runtime)

| Package | Why | Status |
|---|---|---|
| `django==6.1.3` | framework | ✅ already in venv |
| `google-api-python-client` | Gmail API `users.messages.send` (`googleapiclient.discovery.build` — required by the PDF's code) | ➕ to install |
| `google-auth` | `Credentials` objects from stored/refresh tokens | ➕ |
| `google-auth-oauthlib` | OAuth consent `Flow` for `/init/authorise/` + callback | ➕ |
| `google-auth-httplib2` | auth transport used by the API client | ➕ (comes with the above, pin it anyway) |
| `Pillow` | `ImageField` needs it: image verification, re-encode, dimension/size checks | ➕ |
| `python-dotenv` | read `.env` for secrets; `set_key()` to write refreshed tokens back to `.env` | ➕ |

`pip install google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2 Pillow python-dotenv`

### Optional (quality of life)

| Package | Why |
|---|---|
| `pytest` + `pytest-django` | nicer test runner than `manage.py test` |
| `ruff` or `black` | lint/format consistency |
| `whitenoise` | static serving in production without a web-server tweak |

Deliberately **not** used: Celery/Redis (PDF mandates plain threads), anymail (PDF mandates the raw Gmail API), crispy-forms (custom sectioned HTML).

---

## 5. Target File Structure

```
sparc-form/
├── .env                          # secrets — never commit (already gitignored)
├── .env.example                  # template of the contract in §3.3
├── requirements.txt              # pinned deps
├── docs/
│   ├── SPARC_Ambassador_Form_and_Email.pdf
│   └── phase.md                  # this plan
└── sparc/
    ├── manage.py
    ├── db.sqlite3                # gitignored
    ├── media_files/
    │   ├── SPARC26LogoMin.png    # email logo asset (committed)
    │   └── ambassador_photos/    # uploads — gitignored
    ├── templates/                # project-level templates
    │   └── base.html
    ├── static/
    │   ├── css/form.css
    │   └── js/form.js
    ├── sparc/                    # project package
    │   ├── __init__.py
    │   ├── settings.py           # + env loading, MEDIA, TEMPLATES DIRS, apps
    │   ├── urls.py               # include registration at root, emails at init/
    │   ├── wsgi.py
    │   └── asgi.py
    ├── registration/             # APP 1 — the form & applicants
    │   ├── __init__.py
    │   ├── apps.py               # RegistrationConfig  (fix duplicated class name)
    │   ├── models.py             # Ambassador
    │   ├── forms.py              # AmbassadorForm + all clean_* validation
    │   ├── views.py              # form GET/POST, thanks, JsonResponse
    │   ├── urls.py
    │   ├── admin.py              # AmbassadorAdmin (search, filters, photo thumb)
    │   ├── tests.py              # model/form/view tests
    │   ├── migrations/
    │   │   └── __init__.py
    │   └── templates/registration/
    │       ├── apply.html        # sectioned form + photo guide
    │       └── thanks.html       # confirmation message page
    └── emails/                   # APP 2 — mail pipeline & OAuth
        ├── __init__.py
        ├── apps.py               # EmailsConfig  (fix duplicated class name)
        ├── models.py             # MailJob
        ├── sender.py             # build_service / send_mail / process_job / process_job_in_thread
        ├── views.py              # get_credentials() + /init/authorise/ + /init/oauth2callback/
        ├── urls.py
        ├── admin.py              # MailJobAdmin (status, msg id, actions)
        ├── tests.py              # mocked sender tests
        ├── migrations/
        │   └── __init__.py
        ├── management/
        │   ├── __init__.py
        │   └── commands/
        │       ├── __init__.py
        │       └── send_pending.py   # retry Pending/Failed, --from-id
        └── templates/
            ├── ambassador_received.html  # 600px table layout, inline styles, logo top
            └── ambassador_received.txt
```

Naming follows the PDF exactly: `get_credentials()` stays in `emails/views.py` (sender imports it), `sender.py` at app level, `send_pending` command, templates named `ambassador_received.*`.

---

## 6. Build Phases

### Request lifecycle → phase map

| Lifecycle step | Phase |
|---|---|
| Database tables (ORM models + migrations + admin) | **Phase 1** |
| User hits `/` → URL → view renders the HTML form (template, CSS, JS) | **Phase 2** |
| User submits → `forms.py` validation → `Ambassador.objects.create()` → `JsonResponse` | **Phase 3** |
| Mail job created + sent in background thread | **Phase 4** |
| Retry command for failed jobs | **Phase 5** |
| Tests + deployment hardening | **Phase 6** |

One view function (`ambassador_apply`) handles both directions and is written in Phase 3:
`GET /` renders the Phase 2 template; `POST /` runs Phase 3 validation and saves.
The URL wiring (`registration` at `''`) already exists from Phase 0 — only the stub view is swapped.

### Phase 0 — Foundation & hygiene *(~0.5 day)* ✅ done
- [ ] `requirements.txt` (pin current versions) + install the ➕ packages into `venv`.
- [ ] `.env.example` matching §3.3; `.env` created locally (gitignored).
- [ ] `settings.py`: load env via `python-dotenv`; add `registration`, `emails` to `INSTALLED_APPS`; add `SITE_URL`, `MAIL_SENDER`, `GOOGLE_*` settings; `MEDIA_URL='media_files/'` + `MEDIA_ROOT`; project-level `TEMPLATES` `DIRS`; move the hardcoded `SECRET_KEY` to env.
- [ ] Fix `emails/apps.py` → `EmailsConfig`; wire `urls.py` (`registration` at `''`, `emails` at `init/`, media static-serve).
- [ ] Drop `SPARC26LogoMin.png` into `sparc/media_files/`.
- [ ] `makemigrations` + `migrate`, create superuser.
- **Exit:** `manage.py check` clean; `runserver` boots; admin reachable; logo served at `/media_files/SPARC26LogoMin.png`.

### Phase 1 — Data layer *(~1 day)* ✅ done
- [ ] `Ambassador` model per §3.4 (unique email, choices, JSON activities).
- [ ] `MailJob` model verbatim from the PDF incl. `one_mail_per_campaign` constraint.
- [ ] Migrations for both apps.
- [ ] Admin: `AmbassadorAdmin` (search by name/email/university, filters year/gender/IEEE/year-joined, photo thumbnail, sectioned fieldsets), `MailJobAdmin` (list status/gmail_message_id/sent_at, read-only error box, filters by status/campaign, action "retry selected").
- **Exit:** `migrate` clean; both models editable in admin; unique constraint enforced; duplicate `(campaign, ambassador)` rejected.

### Phase 2 — Form UI *(~1–2 days)* ✅ done

> Note: `forms.py` was started here (fields/widgets/labels only — no validation
> logic) so the template renders straight from a real Django form. Phase 3 adds
> only the `clean_*` validators and the POST save logic. The Phase 0 stub view
> was swapped for the real `ambassador_apply` GET renderer in this phase.
- [ ] `base.html` + `static/css/form.css` (SPARC-branded, responsive, mobile-friendly).
- [ ] `apply.html`: intro text, 4 sections (Personal / University / IEEE / Photo+Bio) + About + Agreement, numbered like the spec; photo guide banner above the upload; required markers.
- [ ] `static/js/form.js`: show/hide IEEE block on Yes/No; live 50-word bio counter (block submit over limit); client-side file type/size pre-check (JPG/PNG ≤ 10 MB); `fetch()` submit with loading state; render the exact confirmation message from the spec on success.
- [ ] `thanks.html` fallback (non-JS POST still gets the confirmation message).
- **Exit:** form renders per spec; IEEE fields toggle; counter stops at 50 words; oversized file rejected client-side.

### Phase 3 — Submission backend *(~1–2 days)* ✅ done
- [ ] `AmbassadorForm(ModelForm)`: unique-email friendly error; `clean_photo` (content-type/extension JPG|PNG, size ≤ 10 MB, Pillow `verify()`); `clean_bio` ≤ 50 words; conditional IEEE validation (required iff `is_ieee_member`); all 4 agreement checkboxes enforced; WhatsApp regex; `clean_activities` from the allowed list.
- [ ] `views.ambassador_apply`: GET renders form, POST validates → `Ambassador.objects.create(...)` inside `transaction.atomic` → return `JsonResponse({"success": True, "message": "Application received. Thank you!"})`; AJAX error path returns field errors as JSON (200-with-error contract or 400).
- [ ] Slot the **Phase 4** mail hook location (comment) right after create.
- **Exit:** valid submit creates Ambassador + stores photo under `media_files/ambassador_photos/`; duplicate email rejected; invalid payloads return per-field errors; CSRF enforced.

### Phase 4 — Email pipeline *(~2 days)* ✅ done (code + local verification)

> Remaining for the user (needs a real Google account, cannot be automated):
> Google Cloud project + Gmail API + OAuth consent (Test user) + Web client
> credentials → fill `DEV_GOOGLE_CLOUD_*` in `.env` → log in as superuser →
> open `/init/authorise/` → submit a real application → check Gmail Sent
> folder. The redirect URI to register (byte-exact, no trailing slash):
> `http://localhost:8000/init/oauth2callback` plus the live address.
> During testing: one bug was found and fixed during verification
> (`_render_result` was missing its `request` argument).
- [ ] `emails/views.py`: `get_credentials()` (reads env client config + `GOOGLE_CLOUD_TOKEN`/`REFRESH_TOKEN`, auto-refresh, refresh-token write-back to `.env` via `python-dotenv`), `/init/authorise/` (superuser-only, builds Flow with `/init/oauth2callback/` redirect), `/init/oauth2callback/` (exchange + persist tokens, report success).
- [ ] `emails/sender.py` verbatim-faithful: `build_service()`, `send_mail()` (validate recipient, `render_to_string` txt+html, `EmailMessage`, base64 `urlsafe_b64encode`, `users().messages().send`), `process_job()` (idempotent, `[OK]`/`[FAIL]` console lines, error ≤ 500 chars), `process_job_in_thread()` (closes `connection` in `finally`).
- [ ] Templates `ambassador_received.html` (600 px, table layout, inline styles, logo `{SITE_URL}/media_files/SPARC26LogoMin.png`, body *"Dear {{ name }}, thank you for applying… Best regards, IEEE NSU Student Branch."* — **no** DOB/student-ID/WhatsApp in the mail) + `.txt` alternative.
- [ ] Hook in `registration.views`: `MailJob.objects.get_or_create(campaign="ambassador_received", …)` → `transaction.on_commit` → daemon `Thread(process_job_in_thread)`.
- **Exit:** OAuth round-trip fills tokens in `.env`; a real submit prints `[OK] … MsgId=…`; `MailJob` status `sent`; Gmail Sent folder shows the mail; logo + text render on phone and desktop.

### Phase 5 — Retry & operations *(~0.5–1 day)* ✅ done (local verification, mocked Gmail)

> Note: the forced-failure test ran against a mocked Gmail service (no Google
> credentials yet). The **real**-Gmail forced-failure test (bad client secret,
> exactly as the PDF prescribes) belongs to the PENDING OAuth checklist above —
> do it immediately after authorising. Two small, deliberate deviations from
> the PDF's code: `print()` became `logging` calls with the identical
> `[OK]`/`[FAIL]` line format (routed to the console by a `LOGGING` config),
> and `send_pending` exits cleanly with readable messages ("Nothing to send",
> or a re-authorisation hint on stderr) instead of crashing when there are no
> jobs or no tokens.
- [x] `emails/management/commands/send_pending.py` per the PDF: `--from-id`, processes pending+failed ordered by ambassador_id, shared service, `sleep(3)`, prints summary + restart hint on failures.
- [x] Logging (`loggers` for sender/OAuth), docstring/help text for the command.
- [x] Admin MailJob action delegating to `process_job` (single-job manual retry).
- **Exit:** forced-failure test (mocked Gmail) → job `failed` with readable reason; "fixing the secret" + `send_pending` sends only the failed one; second run reports nothing to send. Unauthorised run: friendly stderr, jobs untouched. `[OK]`/`[FAIL]` captured via the `emails` logger. Admin "Send now" action verified (POST → job sent).

### Phase 6 — QA, tests & hardening *(~1 day)* ✅ done (local rows; Gmail rows pending OAuth — see the checklist at the top)

> QA catch: `_confirmation.html` used a three-line `{# … #}` comment — Django
> does **not** strip multi-line `{# #}` comments (only `{% comment %}` works),
> so the raw comment leaked into every rendered page since Phase 2. Fixed and
> guarded by the rendering test.
> Second QA catch (first real-Gmail round): the mail's logo referenced
> `{SITE_URL}/media_files/SPARC26LogoMin.png`, which webmail clients can
> never load (Gmail fetches remote images through its own servers — a
> `localhost` URL is unreachable there), and the mail template's leading
> three-line `{# … #}` comment leaked into the mail body. Fixed the comment
> with `{% comment %}`. For the header, the placeholder logo was first
> embedded via CID, then **replaced at the user's request** with a large
> white **"IEEE NSU SB"** text banner on the blue header — the
> email-client-safest option, since the mail now carries no remote image
> at all. This supersedes the PDF's "logo on top": if the club later
> supplies the real logo asset, restore an `<img>` in the header (with a
> public SITE_URL a plain URL works; in dev embed via CID — the recipe is
> in the git history of `emails/sender.py`).
- [x] Automated tests — **58 tests, all green** (`venv/bin/python manage.py test`):
      - `registration/tests.py` (25): model constraints (unique email,
        `one_mail_per_campaign`, CASCADE delete, MailJob defaults); every form
        rule (conditional IEEE ×4, 50-word bio, photo required/PNG/JPG/
        wrong-extension/corrupt/>10 MB, WhatsApp formats, all 4 agreements,
        activity whitelist, case-insensitive unique email + lowercasing);
        view flow (GET render with viewport/CSS/photo-guide, AJAX success
        JSON with the exact message, photo saved under a temp MEDIA_ROOT,
        non-AJAX 302→`/thanks/`, duplicate + invalid 400 paths,
        non-AJAX re-render), `on_commit` mail hook queued exactly once,
        admin registration + changelists.
      - `emails/tests.py` (33): sender with FakeService (pending→sent,
        never-send-twice idempotency, failure recording, error truncated to
        500 chars, exact MIME — subject/from/multipart text+html/absolute
        logo URL, **no PII**, invalid recipient rejected), `[OK]`/`[FAIL]`
        captured via the `emails` logger, `send_pending` (`--from-id`
        skipping, second-run pickup, forced failure + restart hint,
        nothing-to-send, unauthorised friendly stderr, help text), OAuth
        (`/init/oauth2callback` byte-exact with a trailing-slash 404 guard,
        staff-only authorise, unconfigured guidance, real Flow consent
        redirect with `access_type=offline`+`prompt=consent`, state
        missing/mismatch 400s, Google-error page, fake-Flow token success
        persisting both keys, `get_credentials` no-token/refresh-fail/
        refresh-success/cached branches), admin Send-now (send / cannot-send
        / sent-only selection), LOGGING config shape.
      - Django's test runner runs with `DEBUG=False`, so the suite doubles
        as a no-debug smoke test of the whole site.
- [x] Production checklist — code side done; server-side rows go on the
      deploy day:
      - `settings.py`: `DJANGO_ALLOWED_HOSTS` env-driven (empty = localhost
        while `DEBUG=True`), `STATIC_ROOT` added (`collectstatic` verified —
        132 files), `MAILERS` made dev-only so the Gmail-API pipeline is the
        only mail path and Django's `mail.E001` deploy check stays clean.
      - `.env.example` documents `DJANGO_ALLOWED_HOSTS`; `.gitignore` adds
        `staticfiles/`.
      - Still open **at deploy time** (need a real HTTPS domain):
        `SECURE_HSTS_SECONDS`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`,
        `CSRF_COOKIE_SECURE` — clear each, then
        `DJANGO_DEBUG=False DJANGO_ALLOWED_HOSTS=<real> manage.py check --deploy`.
      - Live redirect URI in Google Cloud and the Gmail SPF/DKIM/DMARC rows
        are part of the PENDING OAuth checklist at the top of this file.
- [ ] Full PDF verification matrix — locally verifiable rows are covered by
      the suite ([OK] line, MailJob counts, phone/desktop rendering).
      Gmail-server rows (Sent folder, inbox + Spam with SPF/DKIM/DMARC
      `PASS`, 3 test addresses all `sent`) require completed OAuth setup.
- **Exit:** suite 58/58 green; `manage.py check` clean; `check --deploy`
  reduced to the four HTTPS warnings; doc updated (this section).

**Total estimate: ~6–8 working days.** Phases 1–3 are safely parallelizable in pairs (models → form/backend vs. UI).

---

## 7. Risks & Notes

| Risk | Mitigation |
|---|---|
| Google OAuth app in *Testing* → consent expires after 7 days | `/init/authorise/` re-run; sender raises a clear "re-authorise" RuntimeError; `send_pending` retries later |
| `redirect_uri_mismatch` | Constant in code must byte-match Google Cloud config; document both dev and live URIs |
| Gmail `rateLimitExceeded` (~500/day) | `send_pending --from-id` resume; 3 s spacing between sends |
| Thread started before commit → missing row | `transaction.on_commit` only (per PDF) |
| Mail failure must never lose an application | Application saved first; job row keeps error; retry command |
| PII discipline | Email template excludes DOB, student ID, WhatsApp (per PDF) |
| `docs/` gitignored | Remove the `docs/` line from `.gitignore` if `phase.md` should be tracked |
| Duplicate `RegistrationConfig` class in `emails/apps.py` | Fixed in Phase 0 — `EmailsConfig` |
