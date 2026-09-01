# Crumb

**Inventory management for small bakeries — built so the person kneading the dough can actually keep it up to date.**

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-6.0.7-092E20?logo=django&logoColor=white)
![Status](https://img.shields.io/badge/status-in%20development-orange)

Small bakeries track their inventory on paper, on a phone note, or in someone's
head. Flour runs out mid-batch, milk expires unnoticed, and nobody can say what
last month actually cost. Generic inventory software assumes an office, a
barcode gun, and someone free to type — a bakery has none of those at 5 a.m.

Crumb centralizes ingredients, stock movements, production, sales, losses and
alerts in one web application, with short workflows designed for someone
standing at a workbench with flour on their hands. On top of the day-to-day
records, it turns the accumulated history into analytics the owner can act on,
rather than stopping at data entry.

Developed for **Proyecto Integrador 1 (ST0251)**, Universidad EAFIT.

---

## Table of contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [Running the tests](#running-the-tests)
- [Project structure](#project-structure)
- [Architecture](#architecture)
- [Requirements traceability](#requirements-traceability)
- [Conventions](#conventions)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Team](#team)
- [Documentation](#documentation)

---

## Features

| ID | Functionality | Status |
|---|---|---|
| FR01 | Ingredient registration (name, quantity, unit, expiration date) | Available |
| FR02 | Unit of measure management (kg, g, units, liters) | Available |
| FR03 | Ingredient editing | Available |
| FR04 | Ingredient deletion | Available |
| FR05 | Current inventory viewing | Available |
| FR06 | Configurable ingredient expiration alerts | Available |
| FR07 | Stock in (purchase registration) | Available |
| FR08 | Stock consumption registration | Available |
| FR09 | Business profile setup (bakery information) | Available |
| FR10 | Low-stock threshold configuration | Available |
| FR11 | Low-stock alerts | Available |
| FR17 | Barcode scanning for ingredient registration | Available |
| FR22 | Search functionality | Available |

The complete prioritized backlog (FR01–FR38, MoSCoW) lives in the
[project wiki](https://github.com/JANDRESMh2/Crumb/wiki).

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12+ (developed on 3.14.3) | Required by the course |
| Framework | Django 6.0.7 | MVT organization with a layered separation of concerns |
| Database | SQLite | Zero setup for a single-bakery deployment; the ORM keeps the engine swappable |
| Frontend | Django templates over a hand-written CSS design system | No build step and no framework to install — the project stays runnable with `pip install` alone |

---

## Getting started

### 1. Clone the repository

```bash
git clone https://github.com/JANDRESMh2/Crumb.git
cd Crumb
```

### 2. Create and activate a virtual environment

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install the dependencies

```bash
pip install -r requirements.txt
```

### 4. Create the database

```bash
python manage.py migrate
```

Besides creating the tables, this seeds the four units of measure that FR02
restricts the system to: kilograms, grams, units and liters.

### 5. Run the development server

```bash
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

### 6. Set up the bakery profile

**Crumb needs a bakery profile before any ingredient can be registered.** Open
**Set up bakery** (`/bakery/setup/`) and fill in at least the name and the
address. The inventory screens stay empty until that exists — this is FR09, not
a bug.

To inspect the raw data through the Django admin, create a superuser and log in
at `/admin/`:

```bash
python manage.py createsuperuser
```

---

## Running the tests

```bash
python manage.py test
```

The suite covers every implemented requirement at each layer: database
constraints, form validation, the business rules inside the service functions,
and the HTTP behaviour of each view. It must finish with `OK`.

Tests are named after the behaviour they protect rather than the file they live
in, so a failure says what broke — `test_search_does_not_expose_ingredients_from_another_bakery`
tells you more than `test_view_2`.

---

## Project structure

```
Crumb/
├── Crumb/              # Project settings, root URLs and the home view
├── bakery/             # Bakery business profile (FR09)
├── inventory/          # Ingredients, units of measure, stock movements, barcodes
│   ├── models.py       # Data model and database-level constraints
│   ├── forms.py        # Input validation
│   ├── services.py     # Business rules, wrapped in atomic transactions
│   ├── views.py        # HTTP layer only
│   ├── migrations/     # Schema plus the FR02 unit-seeding data migration
│   └── templates/
├── templates/          # base.html design system and shared partials
├── manage.py
└── requirements.txt
```

---

## Architecture

Every feature travels the same path, and each layer has exactly one job:

| Layer | Responsibility | Never does |
|---|---|---|
| `models.py` | Data, and the constraints the **database itself** guarantees | Business decisions |
| `forms.py` | Validating user input and producing readable field errors | Touching unrelated records |
| `services.py` | The business rules, inside `@transaction.atomic` | Knowing about HTTP |
| `views.py` | Read the request, call a service, choose a response | Business logic |
| `templates/` | Presentation | Queries |

### A request, end to end

Registering an ingredient (FR01) shows why the split earns its keep:

```
POST /inventory/ingredients/new/
  │
  ├─ views.py       reads the POST, confirms a bakery exists, delegates
  ├─ forms.py       rejects a duplicate name and any unit outside the four allowed
  ├─ services.py    register_ingredient() — applies the rule that re-registering a
  │                 previously deleted ingredient reactivates it instead of failing
  ├─ models.py      the database refuses a negative quantity even if every layer
  │                 above it were bypassed
  └─ templates/     renders the catalog with a success message
```

The payoff runs in the other direction too: because the rules live in
`services.py` instead of the view, they can be called from a management command,
a future API endpoint, or a test, without going through HTTP.

---

## Requirements traceability

Each requirement maps to a known place in the code, so a reviewer can go from
the backlog in the wiki to the implementation without searching:

| ID | Where it lives |
|---|---|
| FR01 | `inventory/models.py`, `inventory/forms.py`, `inventory/services.py`, `inventory/views.py` |
| FR02 | `inventory/models.py` (`UnitOfMeasure` and its check constraint), `inventory/migrations/0002_seed_units_of_measure.py` |
| FR03 | `inventory/services.py`, `inventory/views.py` |
| FR04 | `inventory/services.py` (soft delete through `is_active`), `inventory/views.py` |
| FR05 | `inventory/views.py`, `inventory/templates/inventory/ingredient_list.html` |
| FR06 | `inventory/models.py` (`AlertConfiguration`), `inventory/forms.py`, `inventory/services.py`, `inventory/views.py`, `inventory/templates/inventory/ingredient_list.html` |
| FR07 | `inventory/models.py` (`StockMovement`), `inventory/views.py` |
| FR08 | `inventory/forms.py` (`Stock_consumption_registration_form`), `inventory/services.py`, `inventory/views.py`, `inventory/templates/inventory/stock_consumption_form.html` |
| FR09 | `bakery/models.py`, `bakery/services.py`, `bakery/views.py` |
| FR10 | `inventory/models.py` (`AlertConfiguration`), `inventory/forms.py` (`LowStockThresholdConfigurationForm`), `inventory/services.py`, `inventory/views.py`, `inventory/templates/inventory/low_stock_threshold_configuration.html` |
| FR11 | `inventory/models.py` (`AlertConfiguration`), `inventory/services.py`, `inventory/views.py`, `inventory/templates/inventory/ingredient_list.html` |
| FR17 | `inventory/models.py` (`BarcodeIdentifier`), `inventory/forms.py`, `inventory/services.py`, `inventory/views.py` |
| FR22 | `inventory/views.py` (the `q` query parameter on the catalog) |

---

## Conventions

**Naming.** Forms and views are named after the functionality they implement,
using the name given to it in the Requirements Prioritisation table of the wiki,
so the backlog and the code speak the same vocabulary.

**Branching.**

```
main  ←  develop  ←  feature/*
```

Feature branches open a pull request against `develop`; `develop` is promoted to
`main` through its own pull request once a sprint's work is stable. Branch names
carry the requirement they implement, for example
`feature/fr08-fr17-consumption-barcode`.

**New code** follows the layered order above instead of putting business logic in
a view, and arrives with tests for the requirement it covers.

---

## Troubleshooting

**`Activate.ps1 cannot be loaded because running scripts is disabled`** (Windows).
PowerShell blocks scripts by default. Allow it for the current terminal only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**The inventory page is empty and I cannot register anything.** The bakery
profile has not been created yet. Go to `/bakery/setup/` first.

**Setting up the bakery a second time fails.** By design: Crumb currently serves
one bakery per deployment, because user accounts (FR31) are not implemented yet.
Editing the existing profile is FR30.

**`no such table` after pulling changes.** New migrations arrived with the code.
Run `python manage.py migrate` again.

---

## Roadmap

| Sprint | Scope |
|---|---|
| Sprint 1 | Ingredient CRUD, units of measure, inventory viewing, search, stock-in, bakery profile |
| Sprint 2 | Stock consumption, barcode scanning and auto-fill, expiration alerts, low-stock thresholds and alerts |
| Later | Spreadsheet import, expiration date filter, production and sales records, reports and exports, history and loss reporting, user accounts, dashboard and sales analytics |

---

## Team

| Name | GitHub |
|---|---|
| Isabella Hernández Posada | [@IsaHernandezPosada](https://github.com/IsaHernandezPosada) |
| Isabela Ruiz de la Ossa | [@SailBliss](https://github.com/SailBliss) |
| Jose Andres Mendoza | [@JANDRESMh2](https://github.com/JANDRESMh2) |
| Juan Manuel Ramirez Wilches | [@Juanrw7](https://github.com/Juanrw7) |

---

## Documentation

- **Wiki** — requirements specification, deliverables, weekly reports and
  retrospectives: <https://github.com/JANDRESMh2/Crumb/wiki>
- **Project board** — sprint backlog and issue tracking:
  <https://github.com/users/JANDRESMh2/projects/15>
