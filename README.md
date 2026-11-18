# Tally: budgeting app (Django REST + Vue 3)

## Backend
    cd backend
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py runserver        # http://localhost:8000/api/

## Frontend
    cd frontend
    npm install
    npm run dev                       # http://localhost:5173 (proxies /api to Django)

Change the currency in `frontend/src/api.js`.

## Working in versions
Each roadmap step is a branch (`v2-recurring`), merged to `main` and tagged (`v2.0.0`), with a CHANGELOG entry.
Upgrading from v0.1: delete `backend/db.sqlite3` and run `python manage.py migrate`.
