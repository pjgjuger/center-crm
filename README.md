# 센터 고객 CRM

Owner-only mobile Streamlit CRM. Customer cards, consultations, survey mappings,
deleted cards, collected reviews, reports and prompts are persisted in Google
Firestore. The app never uses its local filesystem as customer storage.

## Deploy

Use Python 3.12, `app.py`, and `requirements.txt` on Streamlit Community Cloud.
Keep the existing sales-helper app unchanged. This repository contains source
code only; customer data and credentials must never be committed.

Configure Streamlit Secrets with `owner_email`, `[auth]` (Google OIDC client,
callback URI and random cookie secret), `[google_service_account]` and `[survey]`
(`url`, `tab`, `auto_register = true`). Google server metadata URL:
`https://accounts.google.com/.well-known/openid-configuration`.

Verified Google email must exactly match the configured owner before any
database or survey access. Use restrictive Firestore client rules and grant the
server account `roles/datastore.user` limited to the CRM database with IAM.

## Behavior

Surveys refresh every ten seconds while a signed-in browser session is active.
Sleeping Community Cloud apps catch up on the next visit; this is not an
always-running background worker. Existing responses and deleted-card mappings
are durable, preventing duplicate creation across restarts.

Concurrent edits use Firestore transactions and revision checks. A stale edit is
rejected instead of overwriting a newer PC/phone edit. Deletion is recoverable
through the trash page. Use the web app on both devices to share changes; the
old desktop markdown files are retained as a migration source, not synchronized
back from the cloud.

Review crawling depends on Naver availability and Chromium support. Collected
customer files go to Firestore; downloaded browser executables are replaceable
runtime dependencies. Report AI output can be pasted into the report form.

Firestore free quotas apply; overages, storage and network usage can incur
charges. No paid backup/PITR plan is enabled by this app.

## Maintenance

Run `python -m unittest test_web -v`. `migrate.py --dry-run --config PATH`
inventories the desktop vault without changing it. Actual migration requires
explicit credential, owner and private manifest paths, is idempotent, and
verifies newly created cards and all uploaded assets.
