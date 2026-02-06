import json
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.api import deps
from app.services.wordpress import WordPressClient

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/{site_id}/contact-form/entries", response_model=schemas.ContactFormEntriesListResponse)
def get_contact_form_entries(
    site_id: int,
    page: int = 1,
    per_page: int = 15,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Fetch submissions specifically from the 'Contact Form' on the site.
    Returns a cleaned list of entries with parsed response data, wrapped in pagination info.
    """
    logger.info(f"Fetching contact form entries for site {site_id}")
    site = db.query(models.Site).filter(models.Site.id == site_id).first()
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site not found",
        )

    processed_entries = []
    form_title = "Unknown"
    found_form_id = None
    pagination_meta = {}

    try:
        with WordPressClient(site.url, site.api_key, site.api_secret) as wp:
            # 1. Check Reachability
            if not wp.check_wp_reachable()["success"]:
                raise HTTPException(status_code=502, detail="Valid WordPress site not reachable")

            # 2. Get All Forms to find the Contact Form
            forms_result = wp.get_forms()
            if not forms_result["success"]:
                raise HTTPException(status_code=502, detail=f"Failed to fetch forms: {forms_result['error']}")
            
            # 3. Find form with title "Contact Form" (case insensitive)
            if site.contact_form_id:
                found_form_id = site.contact_form_id
                # Try to find title
                for form in forms_result["data"]:
                    if form["id"] == found_form_id:
                        form_title = form.get("title", "Contact Form")
                        break
            else:
                for form in forms_result["data"]:
                    title = form.get("title", "").lower()
                    if "contact form" in title or title == "contact":
                        found_form_id = form["id"]
                        form_title = form.get("title", "Contact Form")
                        break
            
            if not found_form_id:
                raise HTTPException(status_code=404, detail="No 'Contact Form' found on this site")

            # 4. Fetch Entries (Paginated)
            entries_result = wp.get_form_entries(found_form_id, page=page, per_page=per_page)
            if not entries_result["success"]:
                 raise HTTPException(status_code=502, detail=f"Failed to fetch entries: {entries_result['error']}")
            
            # 5. Process Entries (Parse JSON and remove junk)
            # WP API for Fluent Forms might return just list, or dict with 'data' and 'meta'.
            # Based on typical Fluent Forms API, it usually returns { "data": [...], "meta": {...} } or similar for pagination.
            # But get_form_entries wraps response.json() into 'data'.
            # If standard response is list, we assume list. If dict with 'data', we extract it.
            
            raw_response = entries_result["data"]
            
            # Heuristic to handle if raw_response is list or dict with 'data' key inside
            entry_list = []
            if isinstance(raw_response, dict) and "data" in raw_response:
                entry_list = raw_response["data"]
                pagination_meta = raw_response.get("meta", {})
                # Also sometimes paginated result has 'total', 'per_page' at top level
                if "total" in raw_response:
                     pagination_meta["total"] = raw_response["total"]
                if "current_page" in raw_response:
                     pagination_meta["current_page"] = raw_response["current_page"]
                if "last_page" in raw_response:
                     pagination_meta["last_page"] = raw_response["last_page"]

            elif isinstance(raw_response, list):
                entry_list = raw_response
            
            for entry in entry_list:
                try:
                    # Parse the stringified JSON in 'response'
                    response_str = entry.get("response", "{}")
                    content = json.loads(response_str)
                    
                    # Remove junk keys (starting with _)
                    clean_content = {k: v for k, v in content.items() if not k.startswith("_")}
                    
                    # Prepare final object
                    processed_entries.append({
                        "id": entry.get("id"),
                        "status": entry.get("status"),
                        "created_at": entry.get("created_at"),
                        "data": clean_content
                    })
                except (json.JSONDecodeError, TypeError):
                    continue 

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    logger.info(f"Fetched {len(processed_entries)} contact form entries for site {site_id}")
        
    return {
        "form_id": found_form_id,
        "form_title": form_title,
        "entries": processed_entries,
        "total": pagination_meta.get("total"),
        "per_page": int(pagination_meta.get("per_page", per_page)) if pagination_meta.get("per_page") else per_page,
        "current_page": int(pagination_meta.get("current_page", page)) if pagination_meta.get("current_page") else page,
        "last_page": int(pagination_meta.get("last_page", 1)) if pagination_meta.get("last_page") else None
    }