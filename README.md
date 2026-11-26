# ClientDesk: Client Relationship Management

ClientDesk is a Django web app for a small team that looks after clients. Staff keep every company and contact in one place, check in seconds whether an email really comes from a client, and (in later phases) work deals, follow-ups and support tickets together.

## What works today (Phase 1)

- **Companies**: client code (`CL-0001`), status (Prospect / Client / Former), services, needs, account manager
- **Sender verification**: each company stores its email domains and "how to verify" notes. Paste any address into the **Today** page and ClientDesk says whether it is a verified client contact, a known contact who is not cleared, an unknown person at a client domain, or a stranger
- **Contacts**: linked to a company, with job title and "authorized to make requests"; one email address belongs to one contact
- **Notes timeline** on every contact; live search, filters and sorting; CSV export (protected against formula injection)
- **Team**: all staff see all data; administrators create staff accounts, disable them, and are the only ones who delete
- **Accounts**: sign in, change password, forgot password, brute-force lockout. There is no public sign-up
- **REST API** with token authentication, throttling and sender verification
- **UI**: dark mode, mobile menu, toasts, accessible forms

Planned: **Phase 2** pipeline board with deals, **Phase 3** tasks and the Today queue, **Phase 4** tickets with claim/assign and email intake, **Phase 5** reports and demo polish.

## Roles

| Role                       | Can do                                                                            |
| -------------------------- | --------------------------------------------------------------------------------- |
| Staff                      | See everything, create and edit companies and contacts, add notes, verify senders |
| Admin (a Django superuser) | Everything staff can, plus create and disable staff accounts, and delete records  |

## Quick start (SQLite, no database setup)

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # Windows: copy .env.example .env
python manage.py migrate
python manage.py createsuperuser    # your admin account
python manage.py seed_demo          # optional: fictional companies, contacts and staff
python manage.py runserver
```

Open http://127.0.0.1:8000/. With the demo data, sign in as `demo_admin` or `ana` (password `demo-pass-123`), then try verifying `maria.santos@everbest.com.ph`, `someone@everbest.com.ph` and `stranger@gmail.com` on the Today page.

## REST API

Base URL `/api/v1/`. Get a token, then send `Authorization: Token <token>`.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/token/ -H "Content-Type: application/json" \
     -d '{"username": "ana", "password": "..."}'

curl "http://127.0.0.1:8000/api/v1/verify/?email=maria.santos@everbest.com.ph" -H "Authorization: Token <token>"
```

| Method               | Endpoint                   | Purpose                                            |
| -------------------- | -------------------------- | -------------------------------------------------- |
| POST                 | `/auth/token/`             | Username and password for a token (5 per minute)   |
| POST                 | `/auth/token/revoke/`      | Invalidate your token                              |
| GET                  | `/me/`                     | Who you are and your role                          |
| GET                  | `/verify/?email=`          | Is this sender one of our clients?                 |
| GET/POST             | `/companies/`              | List (search, status, ordering) or create          |
| GET/PUT/PATCH/DELETE | `/companies/{id}/`         | One company (delete: admins only)                  |
| GET                  | `/companies/stats/`        | Dashboard totals                                   |
| GET/POST             | `/contacts/`               | List (search, status, company, ordering) or create |
| GET/PUT/PATCH/DELETE | `/contacts/{id}/`          | One contact (delete: admins only)                  |
| GET/POST             | `/contacts/{id}/timeline/` | Read or add notes                                  |

With `DJANGO_DEBUG=True` the browsable API at `/api/v1/` lets you try everything in the browser.

## Tests

```bash
python manage.py test
```

## Going to production

1. `DJANGO_DEBUG=False`, a real `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`
2. `DJANGO_FORCE_HTTPS=True` (and `DJANGO_BEHIND_PROXY=True` only behind a trusted proxy)
3. `python manage.py collectstatic`, then serve `staticfiles/` with your web server (or add WhiteNoise)
4. Use a shared cache (Redis/Memcached) so login throttling works across workers
5. Never run `seed_demo` with real data you care about, and change the demo passwords
6. `python manage.py check --deploy`

## Project layout

```
dcrm/                project settings and root URLs
website/
  models.py          Company, Contact, Note
  verification.py    verify_sender(): is this email from one of our clients?
  permissions.py     Staff and Admin
  views.py           class-based views, throttled login, CSV export, team management
  forms.py           Bootstrap-styled forms
  security.py        cache-based rate limiting
  queries.py         search / filter / sort / dashboard numbers
  api/               serializers, viewsets, routes
  management/        seed_demo command
  templates/         layouts, pages and partials
  static/website/    css, js, icons
```
