import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from redis import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import deps
from app import models, schemas
from app.core.cache import cache_get, cache_set, cache_delete_pattern, cache_delete

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[schemas.SubmissionResponse])
def get_submissions(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    status: Optional[str] = None,
    site_id: Optional[int] = None,
    is_active: bool = Query(default=True),
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    redis: Redis = Depends(deps.get_redis),
):
    cache_key = f"api:submissions:site:{site_id}:active:{is_active}:status:{status}:skip:{skip}:limit:{limit}"
    cached = cache_get(redis, cache_key)
    if cached is not None:
        return cached

    query = db.query(models.Submission).filter(models.Submission.is_active == is_active)
    if status is not None:
        query = query.filter(models.Submission.status == status)
    if site_id is not None:
        query = query.filter(models.Submission.site_id == site_id)
    if skip:
        query = query.offset(skip)

    query = query.order_by(models.Submission.submitted_at.desc()).limit(limit)
    submissions = query.all()

    response_data = [schemas.SubmissionResponse.model_validate(s).model_dump(mode="json") for s in submissions]
    cache_set(redis, cache_key, response_data, 120)

    logger.info(f"Fetched {len(submissions)} submissions")
    return submissions


@router.get("/{submission_id}", response_model=schemas.SubmissionResponse)
def get_submission(
    submission_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    redis: Redis = Depends(deps.get_redis),
):
    submission = db.query(models.Submission).filter(models.Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Clear customer reply flag when viewing (mark as read)
    if submission.has_customer_reply:
        submission.has_customer_reply = False
        db.commit()
        # Invalidate caches since state changed
        cache_delete(redis, f"api:submission:{submission_id}")
        cache_delete_pattern(redis, "api:submissions:*")

    # Check cache only after mutation logic
    cache_key = f"api:submission:{submission_id}"
    cached = cache_get(redis, cache_key)
    if cached is not None:
        return cached

    response_data = schemas.SubmissionResponse.model_validate(submission).model_dump(mode="json")
    cache_set(redis, cache_key, response_data, 120)

    logger.info(f"Fetched submission {submission_id}")
    return submission


@router.post("/", response_model=schemas.SubmissionResponse, status_code=201)
def create_submission(
    submission_in: schemas.SubmissionCreate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    redis: Redis = Depends(deps.get_redis),
):
    try:
        submission = models.Submission(**submission_in.model_dump())
        db.add(submission)
        db.commit()
        db.refresh(submission)
        cache_delete_pattern(redis, "api:submissions:*")
        return submission
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate submission")
    except Exception:
        db.rollback()
        logger.exception("Failed to create submission")
        raise HTTPException(status_code=500, detail="Failed to create submission")


@router.put("/{submission_id}", response_model=schemas.SubmissionResponse)
def update_submission(
    submission_id: int,
    submission_in: schemas.SubmissionUpdate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    redis: Redis = Depends(deps.get_redis),
):
    submission = db.query(models.Submission).filter(models.Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    update_data = submission_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(submission, field, value)
    try:
        db.commit()
        db.refresh(submission)
        cache_delete(redis, f"api:submission:{submission_id}")
        cache_delete_pattern(redis, "api:submissions:*")
        return submission
    except Exception:
        db.rollback()
        logger.exception("Failed to update submission %s", submission_id)
        raise HTTPException(status_code=500, detail="Failed to update submission")
