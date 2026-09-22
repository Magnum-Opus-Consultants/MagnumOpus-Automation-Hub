# Responsiveness checks

Playwright drives the running dev stack rather than starting its own: the app
needs Next on :3000 **and** Django on :8000, so a Playwright-managed web server
would only ever bring up half of it.

## Running

With both servers up:

    npx playwright test

The suite needs two fixtures — a session cookie for the authenticated page, and
a share token for the reviewer page. Without them every test skips rather than
fails, so the suite stays runnable on a machine with no database.

Write them from the repo root:

    ./venv/Scripts/python.exe automations/manage.py shell -c "
    import json
    from django.contrib.auth.models import User
    from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
    from django.contrib.sessions.backends.db import SessionStore
    from dashboard.models import TestProject, TestShareLink
    u = User.objects.get(username='admin')
    s = SessionStore()
    s[SESSION_KEY] = str(u.pk)
    s[BACKEND_SESSION_KEY] = 'django.contrib.auth.backends.ModelBackend'
    s[HASH_SESSION_KEY] = u.get_session_auth_hash()
    s.create()
    p = TestProject.objects.first()
    link = TestShareLink.objects.create(project=p, token=TestShareLink.new_token(),
                                        label='playwright')
    open(r'C:\Users\BERNAD~1\AppData\Local\Temp\claude\pw.json','w').write(
        json.dumps({'sessionid': s.session_key, 'token': link.token,
                    'projectId': p.id}))
    "

Delete the link afterwards — it is a live, unauthenticated way into that
project:

    ./venv/Scripts/python.exe automations/manage.py shell -c "
    from dashboard.models import TestShareLink
    TestShareLink.objects.filter(label='playwright').delete()"

## What is actually asserted

The sheet is **meant** to be wider than the screen, so "nothing exceeds the
viewport" would be the wrong check — it is true of the page and false of the
table by design. What the suite asserts is that the *document* never scrolls
sideways: overflow must be absorbed by a scroller, never pushed onto the page,
because that is the failure that shifts the whole layout on a phone. Any element
overhanging the viewport is reported with its tag and classes, unless one of its
ancestors is a scroll container.
