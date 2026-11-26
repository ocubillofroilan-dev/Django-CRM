# ClientDesk: Client Relationship Management

ClientDesk is a Django web app for a small team that looks after clients. Staff keep every company and contact in one place, check in seconds whether an email really comes from a client, and (in later phases) work deals, follow-ups and support tickets together.

## What works today

**Phase 1: clients**

- **Companies** with a client code (`CL-0001`), status, services, needs and an account manager
- **Sender verification**: each company stores its email domains and "how to verify" notes. Paste any address into the **Today** page and ClientDesk says whether it is a verified client contact, a known contact who is not cleared, an unknown person at a client domain, or a stranger
- **Contacts** linked to a company, with job title and "authorized to make requests"; one email address belongs to one contact
- Notes timeline, live search, filters and CSV export

**Phase 2: tickets and reports**

- **Tickets** are entered by hand (`TCK-0001`). If the requester's email matches a contact, the client is linked automatically and the sender is verified
- **Nobody working? Say so.** The first column of the ticket list shows who is working on each ticket, or a clickable **Unassigned** button. Click it, find your name in the list, and the ticket is yours
- Staff can take a ticket nobody has, release their own, and mark it **Done** with a note of what was done. Only admins assign tickets to other people
- **Completed** page: every finished ticket with who finished it, when and what was done. Open one to add a follow-up note or reopen it
- **Reports**: open and unassigned tickets, finished this week, average time to finish, a 14-day chart, tickets per team member, and the clients that ask the most
- Every ticket has a history of who did what and when

**Accounts and security**

- All staff see all data. Admins create staff accounts and are the only ones who delete. No public sign-up
- Sign in, change password, forgot password, brute-force lockout
- REST API for companies, contacts and sender verification

## Roles

| Role                       | Can do                                                                                                                        |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Staff                      | See everything, create and edit, add notes, take unassigned tickets, release their own, finish their own tickets, see reports |
| Admin (a Django superuser) | Everything staff can, plus assign tickets to anyone, create and disable staff accounts, and delete records                    |

## Live demo

The demo runs on Render's free plan: **[add your link here](https://your-name.onrender.com)**. The first visit after a quiet period takes about a minute to wake up. Sign in with `demo_admin` or `ana` (the password is shown on the login page). The data is fictional and resets whenever the site sleeps, and password changes, new staff and the Django admin site are switched off in demo mode.

## Putting the demo on Render (free)

1. Push the project to GitHub (`.env` and `db.sqlite3` are ignored, so they are not uploaded).
2. On Render: **New > Web Service**, connect the repository, language **Python 3**, instance type **Free**.
3. Build command: `pip install -r requirements.txt && python manage.py collectstatic --noinput`
4. Start command: `python manage.py migrate --noinput && python manage.py seed_demo && gunicorn dcrm.wsgi:application`
5. Environment variables: `DJANGO_DEBUG=False`, `DJANGO_SECRET_KEY` (any long random value), `DJANGO_FORCE_HTTPS=True`, `DJANGO_BEHIND_PROXY=True`, `DEMO_MODE=True`, `WEB_CONCURRENCY=1`, `PYTHON_VERSION=3.13.5`.

Render's free web services have a temporary disk, so SQLite starts empty on every wake-up. The start command rebuilds the demo data each time, which is exactly what a demo needs.

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

Open http://127.0.0.1:8000/. With the demo data, sign in as `demo_admin` or `ana` (password `demo-pass-123`). Try verifying `maria.santos@everbest.com.ph`, `someone@everbest.com.ph` and `stranger@gmail.com` on the Today page, then open **Tickets** and take one that says Unassigned.

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
  models.py          Company, Contact, Note, Ticket, TicketEvent
  tickets.py         the ticket rules: claim, assign, release, done, reopen
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
