# LoadFlow — Freight Brokerage Operations Suite

A working ops platform for a freight brokerage: post loads, assign carriers,
confirm rates, and track shipments pickup-to-delivery — with real, API-enforced
RBAC and automatic compliance flagging so the broker never dispatches to a
carrier with lapsed insurance or authority.

## Stack (and why)

| Piece | Choice | Reason |
|---|---|---|
| Backend | **FastAPI** | Async, typed, auto-generates OpenAPI docs (`/docs`) for free — fast to build and easy to demo/verify endpoints during a hackathon. |
| DB | **SQLite + SQLAlchemy** | Zero setup, single file, plenty for a demo dataset; SQLAlchemy models port to Postgres later with no code changes. |
| Auth | **JWT (python-jose) + bcrypt** | Stateless, works cleanly with a JS frontend without needing server-side sessions. |
| Frontend | **Vanilla HTML/JS single page** | No build step, no npm — one `index.html` served as a static file, keeps the whole thing runnable with just `pip install`. |

Deliberately **not** used: LangChain/LangGraph (no LLM reasoning in this domain —
compliance rules are deterministic business logic, not something to hand to an
LLM), Celery/Redis (no background jobs or task queue needed at this scale — all
operations are synchronous request/response).

## Project layout

```
loadflow/
├── app/
│   ├── main.py                 # FastAPI app + static file serving
│   ├── database.py             # SQLAlchemy engine/session
│   ├── models.py                # ORM models + PERMISSION_CATALOG + LOAD_STATES
│   ├── schemas.py               # Pydantic request/response models
│   ├── auth.py                  # password hashing, JWT issue/verify
│   ├── permissions.py           # RBAC dependencies, org/object scoping, denial logging
│   └── routers/
│       ├── auth.py              # register-org (bootstrap), register-shipper, login
│       ├── orgs.py              # roles, staff invite/list, carrier/shipper lookups
│       ├── compliance.py        # carrier compliance record CRUD
│       ├── loads.py             # load CRUD, state machine, rate confirmation, POD
│       └── audit.py             # permission-denied log + full audit trail viewer
├── static/index.html            # single-page frontend (all 3 dashboards)
├── seed.py                       # demo data: 2 broker users, 3 carrier orgs, shipper, 1 load
├── requirements.txt
└── loadflow.db                   # created on first run (SQLite)
```

## Run it

```bash
cd loadflow
pip install -r requirements.txt --break-system-packages   # drop the flag outside a managed env
python seed.py                   # optional but recommended — populates demo data
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000**. API docs (Swagger) are at **http://localhost:8000/docs**.

### Demo logins (seeded, password for all: `password123`)

| Role | Email | Notes |
|---|---|---|
| Broker Admin | admin@summitfreight.com | Full permissions, can manage staff/roles |
| Broker Dispatcher | dispatcher@summitfreight.com | `load.create`, `load.assign_carrier`, `rate.confirm`, `load.update_status` — no override |
| Carrier Admin (compliant) | admin@ironhidetrucking.com | Ironhide Trucking Co — active authority, valid insurance |
| Carrier Driver | driver@ironhidetrucking.com | `load.update_status`, `pod.upload` only |
| Carrier Admin (non-compliant) | admin@flybynight.com | Fly-By-Night Logistics — expired insurance, inactive authority, on purpose |
| Shipper | shipper@acmegoods.com | Sees only their own loads |

**Suggested demo path:** log in as the broker admin → assign "Fly-By-Night
Logistics" to the seeded Chicago→Dallas load → watch it get auto-flagged and
rate confirmation blocked → either fix their compliance record (as the
Fly-By-Night carrier admin) or override the flag (broker admin has
`load.override_compliance_flag`) → progress the load through to Invoiced/Closed.

To start from a clean slate instead: delete `loadflow.db`, then register a new
Broker org, Carrier org, and Shipper via the signup tabs on the login screen.

## RBAC design

- **Permission catalog** is a fixed list (`app/models.py::PERMISSION_CATALOG`):
  `load.create`, `load.assign_carrier`, `load.override_compliance_flag`,
  `rate.confirm`, `load.update_status`, `staff.manage`, `pod.upload`,
  `load.accept_decline`.
- **Roles** are DB rows (`Role.permissions` = JSON list of catalog strings),
  created by an org Admin through `POST /orgs/roles` — nothing is hardcoded to
  a role *name*. Every check in the code (`permissions.require_permission(...)`)
  tests for a permission string, never a role name.
- **Org Admins** implicitly hold every permission within their own org (so the
  bootstrap Admin can operate immediately without also assigning themselves a
  role), everyone else needs the permission explicitly on their role.
- **Bootstrap vs. invite:** the *first* user of a Broker or Carrier org is
  created via `POST /auth/register-org`, which creates the org and its Admin
  in one step. Every subsequent staff member must be invited by that Admin via
  `POST /orgs/staff` (requires `is_admin=True` on the caller) — there is no
  other way to join an existing org.
- **Org scoping**: every load/compliance query is filtered by the caller's
  `org_id` (broker or carrier) before anything else runs.
- **Object-level scoping**: `permissions.enforce_load_scope()` additionally
  checks that a shipper owns the specific load, or a carrier org is the one
  assigned to it, on every single-load endpoint (`GET/POST /loads/{id}/...`).
- **API-layer enforcement**: all of the above are FastAPI dependencies
  (`require_permission`, `require_account_type`, `enforce_load_scope`) that run
  before the endpoint body executes — hitting a restricted endpoint directly
  (e.g. via curl/Postman with a lower-privileged token) is blocked with a 403,
  independent of what the frontend shows. Verified in testing: a Dispatcher
  role (no override permission) gets a 403 hitting `override-compliance`
  directly, and a shipper token gets a 403 hitting `POST /loads`.
- **Permission-denied logging**: every 403 from the dependencies above writes a
  row to `permission_denied_log` (email, endpoint, permission required,
  reason, timestamp) and prints to stdout. Viewable by org Admins at
  `GET /audit/denied-log` or the "Audit Log" tab in the UI.

## Compliance auto-flagging

Whenever a carrier is assigned to a load (`POST /loads/{id}/assign-carrier`),
`_check_compliance()` in `routers/loads.py` re-evaluates the carrier's
`ComplianceRecord` against the load's equipment/commodity type:

- Authority status must be `active`
- Insurance must not be expired (or missing)
- Equipment type must be in the carrier's `approved_equipment`
- Commodity type must be in the carrier's `approved_commodities`

Any failure sets `Load.compliance_flag = True` with a human-readable reason.
While flagged, `POST /loads/{id}/rate-confirm` and `POST /loads/{id}/status`
both hard-block progression past "Carrier Assigned" with a 400 explaining why.
A user holding `load.override_compliance_flag` (e.g. an "Ops Lead" role) can
clear the flag via `POST /loads/{id}/override-compliance`, which is itself
recorded in the load's audit trail.

## State machine

`Posted → Carrier Assigned → Rate Confirmed → Dispatched → In Transit →
Delivered → POD Verified → Invoiced/Closed`

Enforced as strictly sequential, one step forward at a time
(`routers/loads.py::update_status`); every transition — plus carrier
assignment, rate confirmations, and compliance overrides — writes a row to
`LoadStatusHistory` with who/when/what, viewable via `GET /loads/{id}/history`
or `GET /audit/loads/{id}/full-trail`.

## Rate confirmation versioning

`POST /loads/{id}/rate-confirm` always creates a **new** `RateConfirmation` row
with an incremented `version`, flips the previous version's `is_current` to
`false`, and points `Load.current_rate_confirmation_id` at the new one. Old
loads that were dispatched under an earlier version keep that version's data
untouched — nothing is edited in place. Full history via
`GET /loads/{id}/rate-confirmations`.

## What's implemented vs. stretch

**Done:** Auth for all 3 account types; full custom-role RBAC with org +
object scoping enforced server-side; load CRUD + full state machine + audit
trail; carrier compliance CRUD; versioned rate confirmation; compliance
auto-flagging that blocks progression; all 3 dashboards; search/filter on the
broker load board; POD upload/viewer; permission-denied + full audit log
viewer.

**Not done:** automated compliance-expiry renewal *alert emails* (the data —
expiry dates flagged as "expires soon"/"expired" — is surfaced in the broker's
Compliance tab, but no notification/email job runs on a schedule, consistent
with the decision not to add a task queue for this scope).
