# AuctionHub

A Django auction site with PostgreSQL storage, seller product and auction management, buyer bidding, and in-app notifications. Payment is a project placeholder and does not charge users.

## Local setup (Windows PowerShell)

1. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Install and start PostgreSQL. Copy `.env.example` to `.env` and set the database name, user, and password for your local PostgreSQL instance.

   ```powershell
   Copy-Item .env.example .env
   ```

3. Apply migrations and start Django:

   ```powershell
   python manage.py migrate
   python manage.py runserver
   ```

4. Run checks and tests:

   ```powershell
   python manage.py check
   python manage.py test auction
   ```

## Auction status scheduling

Auction pages refresh status when users visit them. To also update auctions and send winner notifications on schedule, run this command once per minute with Windows Task Scheduler or a system cron service:

```powershell
python manage.py refresh_auctions
```

Run it from the project directory using the same virtual environment and `.env` as the web app. It is safe to run repeatedly. It refreshes scheduled and active auctions, and sends a winner notification when an auction first closes with a winning bid. Auctions with no bids close without a winner notification.

## Production configuration

Set these environment variables in the deployment environment; do not commit `.env` or real credentials:

- `DJANGO_SECRET_KEY`: a unique, long random key.
- `DJANGO_DEBUG=False`.
- `DJANGO_ALLOWED_HOSTS`: comma-separated hostnames serving the app.
- `DJANGO_CSRF_TRUSTED_ORIGINS`: comma-separated full HTTPS origins when required.
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT`.

With debug disabled, HTTPS redirects, secure cookies, and HSTS are enabled by default. If TLS terminates at a reverse proxy, configure that trusted proxy and set `DJANGO_USE_HTTPS_PROXY_HEADER=True`; only enable forwarded-host handling when the proxy strips user-supplied forwarding headers. Run `python manage.py check --deploy` against the actual deployment environment and address any deployment-specific findings. Collect static files with `python manage.py collectstatic` and serve `staticfiles/` and uploaded `media/` through the deployment's web server or object storage.

## Current scope

The payment model and dashboard display are placeholders. There is no checkout, payment provider, or real payment processing. The notification inbox and read actions are implemented; scheduled status changes and winner notices require the recurring management command above for prompt delivery.
