import logging
import json
from datetime import datetime, timezone
from typing import List
from redis import Redis
from dateutil.parser import parse as parse_datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.api import deps
from app.core.cache import cache_delete_pattern
from app.services.wordpress import WordPressClient
from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

SYNC_BATCH_SIZE = 500

router = APIRouter()


def _parse_wp_datetime(value: str | None) -> datetime | None:
    """Parse a WordPress datetime string, returning None on failure."""
    if not value:
        return None
    try:
        return parse_datetime(value)
    except (ValueError, OverflowError):
        logger.warning("Failed to parse datetime: %s", value)
        return None


def sync_site_submissions(db: Session, site: models.Site, redis_client: Redis) -> schemas.SiteSyncResponse:
    """
    Shared sync logic: fetch forms and entries from WordPress,
    upsert submissions into the local database.
    Scopes to 'Contact Form' only and parses fields.
    """
    logger.info("Syncing site %s", site.id)
    with WordPressClient(site.url, site.username, site.application_password) as wp_client:
        # 1. Check Connection
        connection_result = wp_client.test_connection()
        if not connection_result["success"]:
            return schemas.SiteSyncResponse(
                site_id=site.id,
                forms_found=0,
                submissions_synced=0,
                status="error",
                message=connection_result["error"] or "Connection failed",
            )
        target_form_id = None
        # 2. Forms Cache Lookup
        if site.contact_form_id:
            target_form_id = site.contact_form_id
        
        # 1. Forms Cache Lookup (if we don't have ID from DB yet)
        if not target_form_id:
            forms_cache_key = f"site:{site.id}:contact_form_id"
            try:
                cached_id = redis_client.get(forms_cache_key)
                if cached_id:
                    target_form_id = int(cached_id)
            except Exception as e:
                logger.warning("Redis error reading form cache for site %s: %s", site.id, e)

        target_form = None # We might not have the full object, but we have the ID

        # 2. Get Forms (Only if we still don't have an ID)
        if not target_form_id:
            forms_result = wp_client.get_forms()
            if not forms_result["success"]:
                return schemas.SiteSyncResponse(
                    site_id=site.id,
                    forms_found=0,
                    submissions_synced=0,
                    status="error",
                    message=forms_result["error"] or "Failed to fetch forms",
                )
            
            raw_forms = forms_result["data"]
            # Handle paginated response: {"data": [...], "total": N, ...}
            if isinstance(raw_forms, dict) and "data" in raw_forms:
                forms = raw_forms["data"]
            elif isinstance(raw_forms, list):
                forms = raw_forms
            else:
                forms = []
            forms_found = len(forms)

            # Locate Contact Form
            # Heuristic: Find first form with "contact" in title
            for form in forms:
                title = form.get("title", "").lower()
                if "contact" in title:
                    logger.info("Found candidate form: %s (ID: %s)", title, form["id"])
                    target_form = form
                    target_form_id = form["id"]
                    
                    # Update site and cache
                    site.contact_form_id = target_form_id
                    db.add(site) 
                    
                    try:
                        redis_client.setex(f"site:{site.id}:contact_form_id", 3600, target_form_id)
                    except Exception as e:
                         logger.warning("Redis error setting form cache for site %s: %s", site.id, e)
                    break
            
            if not target_form and not target_form_id:
                 # Update last_synced_at even if no form found, to indicate check was performed
                 try:
                     site.last_synced_at = datetime.now(timezone.utc)
                     db.add(site)
                     db.commit()
                 except Exception:
                     db.rollback()
                     logger.warning("Failed to update last_synced_at for site %s", site.id)

                 # Log available forms to help debugging
                 available_titles = [f.get("title", "Unknown") for f in forms]
                 logger.warning("No 'Contact' form found for site %s. Available: %s", site.id, available_titles)

                 return schemas.SiteSyncResponse(
                    site_id=site.id,
                    forms_found=forms_found,
                    submissions_synced=0,
                    status="success", # Success but 0 synced
                    message=f"No 'Contact' form found. Available: {', '.join(available_titles[:3])}...",
                )
        else:
             forms_found = 1 # We skipped fetching list, so we assume 1 found

        # We have target_form_id now.
        # Note: If we got ID from cache/DB, we might not have `target_form` object (title etc). 
        # But we only need ID for `get_form_entries`.
        
        forms_to_sync_ids = [target_form_id]
        submissions_synced = 0

        # Batch-fetch existing
        existing_submissions = db.query(models.Submission).filter(
            models.Submission.site_id == site.id,
            models.Submission.form_id == target_form_id
        ).all()
        lookup = {(s.form_id, s.fluent_form_id): s for s in existing_submissions}

        for form_id in forms_to_sync_ids:
            # Fetch ALL entries

            # Default GET /entries returns latest 20 (or default limit). We should ideally fetch all.
            # For now, adhering to existing pattern (default fetch).
            entries_result = wp_client.get_form_entries(form_id, per_page=50) # Increased batch

            if not entries_result["success"]:
                logger.warning("Failed to fetch entries for form %s: %s", form_id, entries_result["error"])
                continue

            entries = entries_result["data"]
            # Handle potential pagination wrapper
            if isinstance(entries, dict) and "data" in entries:
                entries = entries["data"]

            for entry in entries:
                fluent_form_entry_id = entry.get("id")
                
                # --- Parsing Logic ---
                raw_response_str = entry.get("response", "{}")
                parsed_content = {}
                try:
                    parsed_content = json.loads(raw_response_str)
                except (json.JSONDecodeError, TypeError):
                    parsed_content = {}

                # Cleaning: remove junk keys
                clean_data = {k: v for k, v in parsed_content.items() if not k.startswith("_")}
                
                # Extraction
                # Fluent Forms often nests names in 'names': {'first_name':.., 'last_name':..}
                submitter_name = None
                if "names" in parsed_content and isinstance(parsed_content["names"], dict):
                    first = parsed_content["names"].get("first_name", "")
                    last = parsed_content["names"].get("last_name", "")
                    submitter_name = f"{first} {last}".strip()
                elif "name" in parsed_content:
                    submitter_name = parsed_content["name"]
                
                submitter_email = parsed_content.get("email")
                subject = parsed_content.get("subject")
                message = parsed_content.get("message")
                # ---------------------

                existing = lookup.get((form_id, fluent_form_entry_id))
                
                if existing:
                    # Update (preserve existing status - don't overwrite with WordPress status)
                    existing.data = clean_data
                    existing.submitter_name = submitter_name
                    existing.submitter_email = submitter_email
                    existing.subject = subject
                    existing.message = message
                else:
                    # Create
                    new_submission = models.Submission(
                        site_id=site.id,
                        fluent_form_id=fluent_form_entry_id,
                        form_id=form_id,
                        status="new",
                        data=clean_data,
                        submitter_name=submitter_name,
                        submitter_email=submitter_email,
                        subject=subject,
                        message=message,
                        submitted_at=_parse_wp_datetime(entry.get("created_at")),
                        is_active=True,
                    )
                    db.add(new_submission)
                    lookup[(form_id, fluent_form_entry_id)] = new_submission

                submissions_synced += 1

                if submissions_synced % SYNC_BATCH_SIZE == 0:
                    db.flush()

    try:
        site.last_synced_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Database error during sync for site %s", site.id)
        return schemas.SiteSyncResponse(
            site_id=site.id,
            forms_found=forms_found,
            submissions_synced=0,
            status="error",
            message="Database error during sync",
        )

    logger.info("Sync completed for site %s, synced %s submissions", site.id, submissions_synced)

    return schemas.SiteSyncResponse(
        site_id=site.id,
        forms_found=forms_found,
        submissions_synced=submissions_synced,
        status="success",
        message="Sync completed successfully",
    )


@router.post("/{site_id}", response_model=schemas.SiteSyncResponse)
def sync_single_site(
    site_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    redis_client: Redis = Depends(deps.get_redis),
):
    """
    Manual sync for a single site.
    """
    site = db.query(models.Site).filter(
        models.Site.id == site_id,
        models.Site.is_active.is_(True),
    ).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    logger.info("Manual sync started for site %s", site.id)
    try:
        result = sync_site_submissions(db, site, redis_client)
        cache_delete_pattern(redis_client, "api:submissions:*")
        cache_delete_pattern(redis_client, "api:submission:*")
        return result
    except Exception:
        logger.exception("Unhandled error during sync for site %s", site.id)
        raise HTTPException(status_code=500, detail="Sync failed due to an internal error")


@router.post("/", response_model=List[schemas.SiteSyncResponse])
def sync_all_sites(
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    redis_client: Redis = Depends(deps.get_redis),
):
    """
    Manual sync for all active sites.
    """
    sites = db.query(models.Site).filter(models.Site.is_active.is_(True)).all()
    if not sites:
        raise HTTPException(status_code=404, detail="No active sites found")

    results = []
    for site in sites:
        result = sync_site_submissions(db, site, redis_client)
        results.append(result)

    cache_delete_pattern(redis_client, "api:submissions:*")
    cache_delete_pattern(redis_client, "api:submission:*")

    logger.info("Manual sync completed for %s sites", len(sites))
    return results