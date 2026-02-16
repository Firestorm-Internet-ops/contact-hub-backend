import logging

from sqlalchemy.exc import IntegrityError
from fastapi import APIRouter, Depends, HTTPException
from redis import Redis
from sqlalchemy.orm import Session

from app import models, schemas
from app.api import deps
from app.core.cache import cache_get, cache_set, cache_delete_pattern
from app.services.wordpress import WordPressClient

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/", response_model=list[schemas.SiteResponse])
def get_sites(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    redis: Redis = Depends(deps.get_redis),
):
    """
    Get all active sites with pagination.
    """
    cache_key = f"api:sites:user:{current_user.id}"
    cached = cache_get(redis, cache_key)
    if cached is not None:
        return cached

    logger.info(f"Listing sites with skip={skip} and limit={limit}")
    sites = (
        db.query(models.Site)
        .filter(models.Site.is_active.is_(True))
        .offset(skip)
        .limit(limit)
        .all()
    )

    response_data = [schemas.SiteResponse.model_validate(s).model_dump(mode="json") for s in sites]
    cache_set(redis, cache_key, response_data, 300)

    return response_data


@router.get("/all", response_model=list[schemas.SiteAdminResponse])
def get_all_sites(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin_user),
    redis: Redis = Depends(deps.get_redis),
):
    """
    Get ALL sites including soft-deleted ones. Admin-only.
    """
    cache_key = "api:sites:all"
    cached = cache_get(redis, cache_key)
    if cached is not None:
        return cached

    logger.info(f"Admin listing all sites with skip={skip} and limit={limit}")
    sites = (
        db.query(models.Site)
        .offset(skip)
        .limit(limit)
        .all()
    )

    response_data = [schemas.SiteAdminResponse.model_validate(s).model_dump(mode="json") for s in sites]
    cache_set(redis, cache_key, response_data, 300)

    return response_data


@router.get("/{site_id}", response_model=schemas.SiteResponse)
def get_site(
    site_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Get a specific site by site_id.
    """
    logger.info(f"Fetching site with id={site_id}")
    site = db.query(models.Site).filter(
        models.Site.is_active.is_(True),
        models.Site.id == site_id,
    ).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.post("/", response_model=schemas.SiteResponse, status_code=201)
def create_site(
    site: schemas.SiteCreate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin_user),
    redis: Redis = Depends(deps.get_redis),
):
    """
    Create a new site. Admin-only.
    """
    logger.info(f"Creating new site with name={site.name}, url={site.url}, username={site.username}")
    db_site = models.Site(
        name=site.name,
        url=site.url,
        username=site.username,
        application_password=site.application_password,
        is_active=True,
    )
    try:
        db.add(db_site)
        db.commit()
        db.refresh(db_site)
        cache_delete_pattern(redis, "api:sites:*")
        return db_site
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Site already exists")
    except Exception:
        db.rollback()
        logger.exception("Failed to create site")
        raise HTTPException(status_code=500, detail="Failed to create site")


@router.put("/{site_id}", response_model=schemas.SiteResponse)
def update_site(
    site_id: int,
    site: schemas.SiteUpdate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    redis: Redis = Depends(deps.get_redis),
):
    """
    Update a specific site by site_id.
    """
    logger.info(f"Updating site with id={site_id}")
    db_site = db.query(models.Site).filter(
        models.Site.is_active.is_(True),
        models.Site.id == site_id,
    ).first()
    if not db_site:
        raise HTTPException(status_code=404, detail="Site not found")

    if site.name is not None:
        db_site.name = site.name
    if site.url is not None:
        db_site.url = site.url
    if site.username is not None:
        db_site.username = site.username
    if site.application_password is not None:
        db_site.application_password = site.application_password

    try:
        db.commit()
        db.refresh(db_site)
        cache_delete_pattern(redis, "api:sites:*")
        return db_site
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Site name already taken")
    except Exception:
        db.rollback()
        logger.exception("Failed to update site %s", site_id)
        raise HTTPException(status_code=500, detail="Failed to update site")


@router.delete("/{site_id}", response_model=schemas.SiteResponse)
def delete_site(
    site_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin_user),
    redis: Redis = Depends(deps.get_redis),
):
    """
    Soft-delete a specific site by site_id. Admin-only.
    """
    logger.info(f"Soft-deleting site with id={site_id}")
    db_site = db.query(models.Site).filter(
        models.Site.is_active.is_(True),
        models.Site.id == site_id,
    ).first()
    if not db_site:
        raise HTTPException(status_code=404, detail="Site not found")

    try:
        db_site.is_active = False
        db.commit()
        db.refresh(db_site)
        cache_delete_pattern(redis, "api:sites:*")
        return db_site
    except Exception:
        db.rollback()
        logger.exception("Failed to delete site %s", site_id)
        raise HTTPException(status_code=500, detail="Failed to delete site")


@router.post("/{site_id}/restore", response_model=schemas.SiteResponse)
def restore_site(
    site_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin_user),
    redis: Redis = Depends(deps.get_redis),
):
    """
    Restore a soft-deleted site. Admin-only.
    """
    logger.info(f"Restoring site with id={site_id}")
    db_site = db.query(models.Site).filter(
        models.Site.is_active.is_(False),
        models.Site.id == site_id,
    ).first()
    if not db_site:
        raise HTTPException(status_code=404, detail="Inactive site not found")

    try:
        db_site.is_active = True
        db.commit()
        db.refresh(db_site)
        cache_delete_pattern(redis, "api:sites:*")
        return db_site
    except Exception:
        db.rollback()
        logger.exception("Failed to restore site %s", site_id)
        raise HTTPException(status_code=500, detail="Failed to restore site")


@router.post("/{site_id}/test-connection", response_model=schemas.SiteSyncResponse)
def test_connection(
    site_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Test connection to a specific site.
    """
    logger.info(f"Testing connection to site with id={site_id}")
    db_site = db.query(models.Site).filter(
        models.Site.is_active.is_(True),
        models.Site.id == site_id,
    ).first()
    if not db_site:
        raise HTTPException(status_code=404, detail="Site not found")

    with WordPressClient(db_site.url, db_site.username, db_site.application_password) as wp_client:
        connection_result = wp_client.test_connection()
        if not connection_result["success"]:
            return schemas.SiteSyncResponse(
                site_id=db_site.id,
                forms_found=0,
                submissions_synced=0,
                status="error",
                message=connection_result["error"] or "Connection failed",
            )

        forms_result = wp_client.get_forms()
        if forms_result["success"]:
            return schemas.SiteSyncResponse(
                site_id=db_site.id,
                forms_found=len(forms_result["data"]),
                submissions_synced=0,
                status="success",
                message="Connection successful",
            )
        else:
            return schemas.SiteSyncResponse(
                site_id=db_site.id,
                forms_found=0,
                submissions_synced=0,
                status="error",
                message=forms_result["error"] or "Failed to fetch forms",
            )
