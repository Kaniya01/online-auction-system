# AuctionHub

AuctionHub is a Django auction application using PostgreSQL, Django templates, and a shared responsive interface. It includes buyer and seller workflows, watchlists, bidding, seller auction management, staff administration, in-app notifications, reports, and Razorpay Standard Checkout.

## Local setup (Windows PowerShell)

1. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Install and start PostgreSQL. Copy `.env.example` to `.env` and set local database credentials. Local settings keep `DJANGO_DEBUG=True` and use the console email backend by default.

   ```powershell
   Copy-Item .env.example .env
   ```

3. Apply migrations and run Django:

   ```powershell
   python manage.py migrate
   python manage.py runserver
   ```

4. Check the project and run the app tests:

   ```powershell
   python manage.py check
   python manage.py test auction
   ```

## Selenium browser automation

Selenium is pinned in `requirements.txt`. Install project dependencies in the active virtual environment:

```powershell
python -m pip install -r requirements.txt
```

Install Google Chrome (stable channel) and keep it available to the current user. Selenium Manager, included with Selenium, discovers or downloads the matching ChromeDriver on first run, so a separate manual ChromeDriver installation is not required. The first browser run needs network access for driver management. Run the browser suite against a reachable PostgreSQL instance and a database user that can create the Django test database:

```powershell
python manage.py test auction.selenium_tests --verbosity=2
```

The separate suite covers login success/failure, buyer dashboard/browsing/auction detail, seller dashboard/product and auction pages, scheduled auction editing, and an eligible winner's payment page. The payment test only views the page; it never initiates Razorpay Checkout or contacts payment endpoints. The suite creates isolated test users and auction data.

Chrome runs headlessly by default. To watch the browser, set `$env:SELENIUM_HEADLESS="0"` before running the command. Failed browser tests save screenshots under `test-artifacts/selenium/`; this directory is ignored by Git. Django's test runner prints the test report to the console. To save a report in PowerShell, create the ignored folder and tee the output:

```powershell
New-Item -ItemType Directory -Force test-artifacts | Out-Null
python manage.py test auction.selenium_tests --verbosity=2 2>&1 | Tee-Object test-artifacts/selenium-test-report.txt
```

## Render deployment

Create a Render PostgreSQL database and a Python web service connected to this repository. Render exposes its database URL to the service as `DATABASE_URL` and its assigned hostname as `RENDER_EXTERNAL_HOSTNAME`.

Configure the service with these commands:

- **Build command:** `bash build.sh`
- **Start command:** `gunicorn auction_project.wsgi:application --bind 0.0.0.0:$PORT --access-logfile -`
- **Pre-deploy command:** `python manage.py migrate`

The build script installs `requirements.txt` and runs `collectstatic`. It deliberately does not run database migrations. Run migrations in Render's pre-deploy command where available; otherwise run `python manage.py migrate` as a separate, controlled step before serving traffic.

Set the following environment variables in the Render dashboard. Do not put production credentials in this repository or `.env.example`.

| Variable | Required value |
| --- | --- |
| `DJANGO_DEBUG` | `False` |
| `DJANGO_SECRET_KEY` | A unique random secret of at least 50 characters |
| `RENDER_EXTERNAL_HOSTNAME` | Set by Render; automatically added to allowed hosts and HTTPS CSRF origins |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated custom domains, if any; the Render hostname is added automatically |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated HTTPS origins for additional custom domains when needed |
| `DATABASE_URL` | Render PostgreSQL internal connection URL |
| `DB_CONN_MAX_AGE` | Optional; defaults to `60` seconds |
| `SITE_BASE_URL` | Public HTTPS site URL; defaults to the Render hostname when available |
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST` | SMTP server hostname |
| `EMAIL_PORT` | SMTP port, commonly `587` for TLS or `465` for SSL |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | SMTP credentials; set both or neither when the relay does not require authentication |
| `EMAIL_USE_TLS` / `EMAIL_USE_SSL` | Select the SMTP transport; do not enable both |
| `DEFAULT_FROM_EMAIL` | Sender address verified/configured with the email provider |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | Cloudinary API key |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret; keep private |
| `RAZORPAY_KEY_ID` | Use a `rzp_test_` key for staging |
| `RAZORPAY_KEY_SECRET` | Razorpay Test Mode secret for staging |
| `RAZORPAY_WEBHOOK_SECRET` | Secret configured for the deployed webhook endpoint |
| `RAZORPAY_CURRENCY` | `INR` |

The Django app rejects production configuration that omits the secret key, allowed hosts, PostgreSQL settings, sender address, SMTP host, Cloudinary credentials, or public site URL. It keeps HTTPS redirects and secure session/CSRF cookies enabled when `DJANGO_DEBUG=False`. On Render, the app trusts Render's `X-Forwarded-Proto` header by default so HTTPS redirects recognize the original browser connection. Set `DJANGO_USE_HTTPS_PROXY_HEADER=False` only if deploying outside Render without a trusted proxy that supplies that header. Enable forwarded-host support only when the trusted proxy strips user-supplied forwarding headers.

HSTS is set to one year when debug is disabled. HSTS subdomain and preload options remain off; enable them only after confirming that all relevant subdomains are HTTPS-only and the domain is ready for browser preload lists. Run `python manage.py check --deploy` with the actual Render environment before launch.

### Static and uploaded media

WhiteNoise serves collected static files from the web service. `build.sh` runs `python manage.py collectstatic --noinput` into `staticfiles/`.

Product and profile images use Django's local filesystem storage under `MEDIA_ROOT` (default `media/`) while `DJANGO_DEBUG=True`. In production (`DJANGO_DEBUG=False`), the default media storage switches to Cloudinary; static files remain on WhiteNoise. No model or database migration is required because the existing image fields use Django's storage API.

#### Cloudinary setup for Render

1. Create a Cloudinary account and open the account's API credentials page to obtain its cloud name, API key, and API secret. The Cloudinary Python SDK reads configuration server-side; do not put credentials in templates or commit them.
2. Add `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET` as secret environment variables in the Render web service. Production startup fails clearly if any are missing. Local development continues to use filesystem storage even when these values are absent.
3. Before deploying existing uploads, run `python manage.py sync_media_to_cloudinary` on the machine that has the current `MEDIA_ROOT` files, with the Cloudinary variables available in that process. The command uploads missing files using stable IDs derived from their existing relative names, skips assets already present, and does not change the database or local files. Run it again after backup or if any files were added; existing database field names keep resolving to their Cloudinary URLs.
4. Confirm uploaded assets and image URLs in Cloudinary before switching the production service to `DJANGO_DEBUG=False`.

The project pins Cloudinary's maintained Python SDK. It supports Python 3.13 and Django 5.2 according to its current compatibility matrix. [Cloudinary Python SDK](https://pypi.org/project/cloudinary/), [Cloudinary Django integration docs](https://cloudinary.com/documentation/django_integration).

### Auction status scheduler

Auction pages refresh status on visits. To close auctions and send winner/ending notifications on schedule, run `python manage.py refresh_auctions` regularly (the project recommends once per minute). Configure this as a separate scheduled job/service in Render; it is not run by the web process or build script.

### Razorpay staging

The application uses Razorpay Standard Checkout. Payment orders are created server-side from the recorded winning bid; callback signatures and provider payment state are verified server-side, while webhooks are HMAC-verified and deduplicated. Keep `rzp_test_` credentials for staging. Test Mode exercises the integration but does not transfer real funds. Configure the webhook URL as `https://<your-domain>/payments/razorpay/webhook/` and select the payment events supported by the application. Do not use live credentials until the business owner approves a live-payment launch and the account/webhook setup has been verified.

## Production verification commands

Run these commands in the configured Render environment before launch:

```bash
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py collectstatic --noinput
```

Create the initial staff account from the Render Shell with `python manage.py createsuperuser`.
