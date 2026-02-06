import logging

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app import models
from app.api.v1.sync import sync_site_submissions
from app.tasks.celery_app import celery_app
from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

@celery_app.task(bind=True)
def sync_all_sites_task(self):
    """Fan out individual sync tasks for each active site."""
    db: Session = SessionLocal()
    try:
        site_ids = [
            s.id for s in
            db.query(models.Site.id).filter(models.Site.is_active.is_(True)).all()
        ]
        logger.info("Dispatching sync for %d active sites", len(site_ids))
        for site_id in site_ids:
            sync_single_site_task.delay(site_id)
    finally:
        db.close()


@celery_app.task(
    bind=True,
    autoretry_for=(Exception, SoftTimeLimitExceeded),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
    retry_jitter=True,
)
def sync_single_site_task(self, site_id: int):
    logger.info("Starting sync for site %d (attempt %s)", site_id, self.request.retries + 1)
    db: Session = SessionLocal()
    redis_client = get_redis_client()
    try:
        site = db.query(models.Site).filter(models.Site.id == site_id).first()
        if not site:
            logger.warning("Site %d not found, skipping sync", site_id)
            return
        sync_site_submissions(db, site, redis_client)
        logger.info("Successfully synced site %d (%s)", site.id, site.name)
    except Exception as e:
        logger.exception("Error syncing site %d (%s)", site_id, site.name)
        raise
    finally:
        redis_client.close()
        db.close()
