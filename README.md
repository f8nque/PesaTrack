# Tally: budgeting app (Django Templates + Django REST)

## Running the App (Django Templates UI + API)
    cd backend
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py runserver        # http://localhost:8000/ (UI) and http://localhost:8000/api/

Change the currency in `backend/config/settings.py` (`CURRENCY = 'KES'`).

## Legacy Vue Frontend (optional)
    cd frontend
    npm install
    npm run dev                       # http://localhost:5173 (proxies /api to Django)

## Working in versions
Each roadmap step is a branch (`v2-recurring`), merged to `main` and tagged (`v2.0.0`), with a CHANGELOG entry.
Upgrading from v0.1: delete `backend/db.sqlite3` and run `python manage.py migrate`.
