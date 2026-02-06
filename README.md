# Fluent Forms Hub - Backend

FastAPI backend for centralized management of Fluent Forms data across multiple WordPress sites.

## Tech Stack

- **Framework:** FastAPI
- **Database:** MySQL with SQLAlchemy ORM
- **Authentication:** JWT tokens (python-jose)
- **Task Queue:** Celery with Redis
- **Email:** Gmail API integration + SMTP

## Project Structure

```
backend/
├── app/
│   ├── api/v1/           # API endpoints
│   │   ├── auth.py       # Authentication (login, register, password)
│   │   ├── submission.py # Form submissions CRUD
│   │   ├── site.py       # WordPress site management
│   │   ├── sync.py       # WordPress sync operations
│   │   ├── email.py      # Email sending
│   │   ├── gmail_oauth.py# Gmail OAuth flow
│   │   ├── contact.py    # Contact management
│   │   └── diagnostics.py# System diagnostics
│   ├── core/
│   │   ├── config.py     # Settings from environment
│   │   ├── database.py   # Database connection
│   │   └── security.py   # JWT & password hashing
│   ├── models/           # SQLAlchemy models
│   │   ├── user.py
│   │   ├── site.py
│   │   ├── submission.py
│   │   ├── email_thread.py
│   │   └── gmail_credentials.py
│   ├── schemas/          # Pydantic schemas
│   ├── services/         # Business logic
│   └── tasks/            # Celery tasks
│       ├── celery_app.py # Celery configuration
│       ├── sync_tasks.py # WordPress sync tasks
│       └── gmail_tasks.py# Gmail polling tasks
├── alembic/              # Database migrations
├── logs/                 # Application logs
├── start.sh              # Start all services
└── requirements.txt
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/auth/login` | User login |
| `POST /api/v1/auth/register` | User registration |
| `GET /api/v1/submissions` | List submissions |
| `GET /api/v1/submissions/{id}` | Get submission details |
| `PUT /api/v1/submissions/{id}` | Update submission |
| `GET /api/v1/sites` | List WordPress sites |
| `POST /api/v1/sites` | Add WordPress site |
| `POST /api/v1/sync/all` | Sync all sites |
| `POST /api/v1/email/send` | Send email |
| `GET /api/v1/gmail/oauth/init` | Start Gmail OAuth |
| `GET /health` | Health check |

## Environment Variables

Create a `.env` file in the backend directory:

```env
# App
PROJECT_NAME="Fluent Forms Hub"
PROJECT_DESCRIPTION="Centralized hub for managing Fluent Forms data"
PROJECT_VERSION="0.1.0"
API_V1_STR="/api/v1"

# Admin
ADMIN_EMAIL="admin@example.com"
ADMIN_PASSWORD="your_password"

# Security
SECRET_KEY="your_secret_key"  # openssl rand -hex 32
ACCESS_TOKEN_EXPIRE_MINUTES=1440  # 1 day
ENCRYPTION_KEY="your_fernet_key"
CRYPT_ALGORITHM="HS256"

# Database
DB_USER=root
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=3306
DB_NAME=hubdb

# Redis
REDIS_URL="redis://localhost:6379/0"

# SMTP
SMTP_TLS=True
SMTP_PORT=587
SMTP_HOST="smtp.gmail.com"
SMTP_EMAIL="your_email@gmail.com"
SMTP_PASSWORD="your_app_password"
EMAILS_FROM_EMAIL="your_email@gmail.com"
EMAILS_FROM_NAME="Your Name"

# Gmail API
GMAIL_CLIENT_ID="your_client_id"
GMAIL_CLIENT_SECRET="your_client_secret"
GMAIL_REDIRECT_URI="http://localhost:8000/api/v1/gmail/oauth/callback"
GMAIL_POLL_INTERVAL_HOURS=3

# CORS
CORS_ORIGINS="http://localhost:5173"
```

## Setup

1. **Create virtual environment:**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Setup database:**
   ```bash
   # Create MySQL database
   mysql -u root -p -e "CREATE DATABASE hubdb;"

   # Run migrations
   alembic upgrade head
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

## Running

### Start All Services (Recommended)

```bash
./start.sh
```

This starts:
- Redis (port 6379)
- FastAPI (port 8000)
- Celery Worker
- Celery Beat (scheduler)

### Manual Start

```bash
# Terminal 1: Redis
redis-server

# Terminal 2: FastAPI
uvicorn app.main:app --reload --port 8000

# Terminal 3: Celery Worker
celery -A app.tasks.celery_app worker --loglevel=info

# Terminal 4: Celery Beat
celery -A app.tasks.celery_app beat --loglevel=info
```

## Scheduled Tasks

Configured in `app/tasks/celery_app.py`:

| Task | Schedule |
|------|----------|
| `sync_all_sites_task` | Every 3 hours |
| `poll_gmail_replies_task` | Every 3 hours |

## Logs

Logs are stored in `backend/logs/`:
- `api_*.log` - API server logs
- `celery-worker.log` - Celery worker logs
- `celery-beat.log` - Celery scheduler logs
- `redis.log` - Redis logs

## API Documentation

When running, access:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
