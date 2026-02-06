import logging
import re
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=30,
    pool_recycle=3600,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


_SAFE_DB_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def init_db():
    db_name = settings.DB_NAME

    # C5 fix: Validate db_name to prevent SQL injection via environment variable
    if not _SAFE_DB_NAME.match(db_name):
        raise ValueError(
            f"Invalid database name: '{db_name}'. "
            "Must start with a letter or underscore and contain only alphanumeric characters."
        )

    parsed = urlparse(settings.DATABASE_URL)
    server_url = urlunparse(parsed._replace(path=""))
    temp_engine = create_engine(server_url)
    try:
        with temp_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE IF NOT EXISTS {db_name}"))
            logger.info("Database '%s' created or already exists.", db_name)
    finally:
        temp_engine.dispose()
    
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    logger.info("Tables created or verified.")
    
    # Manual migration for new columns (Task 6.7 response)
    # We do this to ensure existing installs get the new columns without Alembic
    _ensure_columns_exist()

def _ensure_columns_exist():
    """
    Ensure all columns defined in models exist in existing tables.
    This handles schema evolution without requiring Alembic migrations.
    """
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    # Define column specifications for each table
    # Format: table_name -> list of (column_name, sql_type, extra_sql)
    table_columns = {
        "form_submissions": [
            ("submitter_name", "VARCHAR(255)", None),
            ("submitter_email", "VARCHAR(255)", "CREATE INDEX IF NOT EXISTS ix_form_submissions_submitter_email ON form_submissions (submitter_email)"),
            ("subject", "VARCHAR(255)", None),
            ("message", "TEXT", None),
            ("gmail_thread_id", "VARCHAR(255)", "CREATE INDEX IF NOT EXISTS ix_form_submissions_gmail_thread_id ON form_submissions (gmail_thread_id)"),
            ("updated_at", "DATETIME", None),
            ("is_active", "BOOLEAN DEFAULT TRUE", None),
            ("locked_by", "INTEGER", None),
            ("locked_at", "DATETIME", None),
        ],
        "email_threads": [
            ("to_email", "VARCHAR(255)", None),
            ("from_email", "VARCHAR(255)", None),
            ("status", "VARCHAR(20)", None),
            ("gmail_message_id", "VARCHAR(255)", "CREATE UNIQUE INDEX IF NOT EXISTS ix_email_threads_gmail_message_id ON email_threads (gmail_message_id)"),
            ("gmail_thread_id", "VARCHAR(255)", "CREATE INDEX IF NOT EXISTS ix_email_threads_gmail_thread_id ON email_threads (gmail_thread_id)"),
        ],
        "sites": [
            ("contact_form_id", "INTEGER", None),
            ("last_synced_at", "DATETIME", None),
            ("created_at", "DATETIME", None),
            ("updated_at", "DATETIME", None),
        ],
        "site_assignments": [
            ("role", "VARCHAR(255) DEFAULT 'editor'", None),
            ("is_active", "BOOLEAN DEFAULT TRUE", None),
            ("created_at", "DATETIME", None),
        ],
        "users": [
            ("role", "VARCHAR(255) DEFAULT 'user'", None),
            ("created_at", "DATETIME", None),
            ("updated_at", "DATETIME", None),
        ],
        "gmail_credentials": [
            ("user_email", "VARCHAR(255)", "CREATE UNIQUE INDEX IF NOT EXISTS ix_gmail_credentials_user_email ON gmail_credentials (user_email)"),
            ("access_token", "TEXT", None),
            ("refresh_token", "TEXT", None),
            ("client_secret", "TEXT", None),
            ("token_uri", "VARCHAR(255)", None),
            ("client_id", "VARCHAR(255)", None),
            ("scopes", "VARCHAR(255)", None),
            ("expiry", "DATETIME", None),
            ("created_at", "DATETIME", None),
            ("updated_at", "DATETIME", None),
        ],
        "audit_logs": [
            ("user_id", "INTEGER", None),
            ("action", "VARCHAR(255)", None),
            ("entity_type", "VARCHAR(255)", None),
            ("entity_id", "INTEGER", None),
            ("data", "JSON", None),
            ("created_at", "DATETIME", None),
        ],
        "task_executions": [
            ("task_name", "VARCHAR(255)", "CREATE INDEX IF NOT EXISTS ix_task_executions_task_name ON task_executions (task_name)"),
            ("status", "VARCHAR(255)", "CREATE INDEX IF NOT EXISTS ix_task_executions_status ON task_executions (status)"),
            ("result", "JSON", None),
            ("created_at", "DATETIME", None),
        ],
    }

    with engine.connect() as conn:
        for table_name, columns_spec in table_columns.items():
            if table_name not in existing_tables:
                continue

            existing_columns = [c["name"] for c in inspector.get_columns(table_name)]

            for col_name, col_type, extra_sql in columns_spec:
                if col_name not in existing_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
                        logger.info(f"Added column {col_name} to {table_name}")

                        if extra_sql:
                            conn.execute(text(extra_sql))
                            logger.info(f"Executed: {extra_sql}")
                    except Exception as e:
                        # Column might already exist or other issue
                        logger.warning(f"Could not add column {col_name} to {table_name}: {e}")

        # Handle column renames (for backward compatibility)
        if "form_submissions" in existing_tables:
            fs_columns = [c["name"] for c in inspector.get_columns("form_submissions")]
            if "api_key" in fs_columns:
                try:
                    conn.execute(text("ALTER TABLE form_submissions RENAME COLUMN api_key TO username"))
                    logger.info("Renamed api_key to username in form_submissions")
                except Exception as e:
                    logger.warning(f"Could not rename api_key: {e}")
            if "api_secret" in fs_columns:
                try:
                    conn.execute(text("ALTER TABLE form_submissions RENAME COLUMN api_secret TO application_password"))
                    logger.info("Renamed api_secret to application_password in form_submissions")
                except Exception as e:
                    logger.warning(f"Could not rename api_secret: {e}")

        # Update status from 'pending' to 'new' for consistency
        if "form_submissions" in existing_tables:
            try:
                result = conn.execute(text("UPDATE form_submissions SET status = 'new' WHERE status = 'pending'"))
                if result.rowcount > 0:
                    logger.info(f"Updated {result.rowcount} submissions from 'pending' to 'new' status")
            except Exception as e:
                logger.warning(f"Could not update pending status: {e}")

        conn.commit()

    logger.info("Column verification complete.")
