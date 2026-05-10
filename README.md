# EcoSentinel - Human-Wildlife Conflict Management System

An integrated software system for human-wildlife conflict management with Business Intelligence support.
Built for India-wide forest-adjacent communities and forest officials.

## Tech Stack
| Layer     | Technology                    |
|-----------|-------------------------------|
| Frontend  | HTML5 / CSS3 dark theme       |
| Backend   | Python Flask REST API         |
| Database  | PostgreSQL-ready via SQLAlchemy |
| BI Module | Pandas, Matplotlib, Seaborn   |
| Map       | Leaflet.js, CartoDB dark tiles|

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure database
For local development, the app falls back to `sqlite:///ecosentinel.db` if `DATABASE_URL` is not set.

For PostgreSQL, set:
```bash
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/ecosentinel
```

### 3. Run the app
```bash
cd ecosentinel
python app.py
```

On first run, the app creates the tables and seeds the database from:
- `data/users.json`
- `data/tamil_nadu_full_districts_100.csv`

### 4. Open browser
```text
http://localhost:5050
```

### 5. Demo logins
| Role    | Username  | Password     |
|---------|-----------|--------------|
| Admin   | `admin`   | `admin123`   |
| Officer | `officer` | `officer123` |

## Proposed System Coverage
- Centralized incident storage with searchable historical records.
- Risk categorization: Low, Medium, and High.
- Interactive dashboards for trends, species analysis, hotspots, and response planning.
- Admin verification workflow for incident records.
- Admin user account and system access management.
- Officer incident reporting with location, species, date, damage, notes, and risk details.
- Continuous updates: new incidents are appended to the dataset and reflected in dashboards.

## Pages & Features
| Route                | Feature                                             |
|----------------------|-----------------------------------------------------|
| `/`                  | Home KPI summary and system overview                |
| `/login`             | Secure role-based login for Admin and Officer users |
| `/admin-dashboard`   | Admin dashboard with system KPIs, charts, hotspots  |
| `/officer-dashboard` | Officer dashboard with priority cases and actions   |
| `/dashboard`         | Redirects to the admin dashboard                    |
| `/incidents`         | Officer incident reporting and searchable history   |
| `/admin/incidents`   | Admin incident verification and review workflow     |
| `/admin/users`       | Admin user account and access management            |
| `/bi`                | BI module with Python-generated analytics charts    |
| `/map`               | Leaflet map with risk-colored incident markers      |

## API Endpoints
| Endpoint                            | Description                              |
|-------------------------------------|------------------------------------------|
| `GET /api/summary`                  | KPI totals and risk/verification counts  |
| `GET /api/incidents`                | Paginated incidents with filters/search  |
| `POST /api/incidents/add`           | Add a new incident                       |
| `POST /api/incidents/<id>/verify`   | Admin verification status update         |
| `GET /api/users`                    | Admin list of user accounts              |
| `POST /api/users/add`               | Admin create user account                |
| `POST /api/users/<username>/toggle` | Admin enable/disable account             |
| `GET /api/filters`                  | Available filter options                 |
| `GET /api/map_data`                 | Lat/lon incident records for map         |
| `GET /api/charts/species_donut`     | Species breakdown chart                  |
| `GET /api/charts/conflict_bar`      | Conflict type chart                      |
| `GET /api/charts/season_risk`       | Seasonal average risk chart              |
| `GET /api/charts/risk_histogram`    | Risk score histogram                     |
| `GET /api/charts/monthly_trend`     | Monthly trend line chart                 |
| `GET /api/charts/top_districts`     | Top 10 hotspot districts chart           |
| `GET /api/charts/response_pie`      | Response action pie chart                |
| `GET /api/charts/species_conflict_heatmap` | Seaborn heatmap                  |
| `GET /api/charts/damage_comparison` | Grouped damage bar chart                 |

## Dataset
- File: `data/tamil_nadu_full_districts_100.csv`
- Records: 100 synthetic HWC incidents in the current demo dataset
- Coverage: India-wide application design, with a Tamil Nadu sample dataset included for demonstration
- Species: Elephant, Wild Boar, Leopard, Monkey, Deer
- Fields: incident_id, report_date, state, district, forest_beat, latitude, longitude, animal_species, conflict_type, season, risk_score, response_action, officer_notes, human_casualties, livestock_loss, crop_damage_ha, verification_status, verified_by, verified_at
- Risk categorization: Low (`risk_score < 10`), Medium (`10 <= risk_score < 20`), High (`risk_score >= 20`)

## Project Structure
```text
ecosentinel/
|-- app.py
|-- data/
|   |-- tamil_nadu_full_districts_100.csv
|   |-- users.json
|-- templates/
|   |-- base.html
|   |-- index.html
|   |-- login.html
|   |-- admin_dashboard.html
|   |-- officer_dashboard.html
|   |-- admin_incidents.html
|   |-- users.html
|   |-- incidents.html
|   |-- bi.html
|   |-- map.html
|-- README.md
```

## Database Notes
- Current application data is stored in database tables through SQLAlchemy models.
- PostgreSQL is the recommended production database.
- SQLite is used only as a local fallback when `DATABASE_URL` is not configured.
- Existing CSV and JSON demo data are used only for one-time seeding when the database is empty.

## Authors
EcoSentinel - Academic Project, India-wide forest department use case
