from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import logging

from app import models, schemas
from app.api import deps
from app.services.wordpress import WordPressClient

router = APIRouter()

logger = logging.getLogger(__name__)

@router.get("/{site_id}", response_model=dict)
def run_diagnostics(
    site_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Run diagnostic checks on a WordPress site.
    """
    logger.info(f"Running diagnostics for site {site_id}")
    site = db.query(models.Site).filter(models.Site.id == site_id).first()
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site not found",
        )
    
    results = {
        "wordpress": {"reachable": False, "error": None},
        "fluentforms": {"active": False, "version": None, "error": None},
        "plugin": {"installed": False, "active": False, "version": None, "error": None},
    }

    try:
        with WordPressClient(site.url, site.api_key, site.api_secret) as wp:
            # 1. Check Reachability
            reach_result = wp.check_wp_reachable()
            results["wordpress"]["reachable"] = reach_result["success"]
            results["wordpress"]["error"] = reach_result["error"]

            if reach_result["success"]:
                # 2. Check Fluent Forms API
                api_result = wp.check_fluentforms_api()
                results["fluentforms"]["active"] = api_result["success"]
                results["fluentforms"]["error"] = api_result["error"]
                
                # 3. Check Plugin Status
                plugin_result = wp.get_plugin_status()
                if plugin_result["success"]:
                    results["plugin"]["installed"] = True
                    results["plugin"]["active"] = plugin_result["data"].get("status") == "active"
                    results["plugin"]["version"] = plugin_result["data"].get("version")
                else:
                    results["plugin"]["error"] = plugin_result["error"]

    except Exception as e:
        # Catch instantiation errors or other unexpected failures
        results["wordpress"]["error"] = str(e)


    logger.info(f"Diagnostics for site {site_id} completed, fluentforms plugin is {results['fluentforms']['active']}, plugin version is {results['plugin']['version']}, wp reachability is {results['wordpress']['reachable']}")

    return results