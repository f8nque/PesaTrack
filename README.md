# Tally: budgeting app (Django)

## Running the App
    python -m venv env && source env/bin/activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py runserver        # http://localhost:8000/

Change the currency in `config/settings.py` (`CURRENCY = 'KES'`).

## Working in versions
Each roadmap step is a branch (`v2-recurring`), merged to `main` and tagged (`v2.0.0`), with a CHANGELOG entry.
Upgrading from v0.1: delete `db.sqlite3` and run `python manage.py migrate`.
