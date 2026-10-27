# InvoiceFlow: rules for AI coding agents

Invoicing for Australian consultancies. Django 6.1, Django REST Framework,
HTMX, Tailwind CSS, PostgreSQL. Read this before changing anything.

## Commands

- Local database: `docker compose up -d` (Postgres on port 5433), then `cp .env.example .env`
- Install: `uv sync`
- Run: `uv run python manage.py migrate && uv run python manage.py runserver`
- Checks before reporting done, all must pass:
  `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run python manage.py makemigrations --check --dry-run`, `uv run pytest`
- Tailwind (after changing classes in templates or `assets/app.css`): `npm ci && npm run css`.
  The built `static/css/app.css` is committed; CI fails if it's out of date.

## How to work

- Plan first. For anything beyond a one-line fix, list the files to change,
  model or migration changes, security risks, and the tests you will add.
  Raise gaps or ambiguities in the spec before building.
- One feature or fix per branch and pull request. Keep diffs small and focused;
  no drive-by refactors.
- Every behaviour change ships with tests. A feature is not done until the
  checks above pass.
- PR descriptions: what changed and why, then a test plan listing the checks
  actually run.
- Never commit, push, merge, deploy, or run migrations against a shared
  database without explicit approval.

## Rules of this codebase

- **Tenancy is the most important rule.** Every business record belongs to an
  organisation. Always start queries from `Model.objects.for_org(org)` and
  look up single records with `get_object_or_404` on that scoped queryset, so
  another organisation's record is a 404, never a 403 that confirms it exists.
  Never trust an organisation or foreign-key id from the request body without
  checking it belongs to the user's organisation.
- **Money is `Decimal`, never float.** Store cents-precision `DecimalField`s;
  round with `ROUND_HALF_UP` to 2 places at line level. GST is 10% on taxable
  lines.
- **Business rules live in `services.py`**, not in views, serializers, or
  templates, so the HTML views and the API share one implementation. Writes that
  must not race (invoice numbers, payments) lock rows with `select_for_update`
  inside `transaction.atomic`.
- Enforce invariants in the database too (`CheckConstraint`,
  `UniqueConstraint`), not only in forms.
- HTMX: full pages extend `base.html`; partials live in
  `templates/<app>/partials/` and are returned when `request.htmx` is true.
  Keep JavaScript to HTMX attributes; no custom JS frameworks.
- Settings come from environment variables only. No secrets, keys, or real
  client data in code, fixtures, tests, or commit messages.
- Prefer Django and DRF built-ins over new dependencies; ask before adding one.
