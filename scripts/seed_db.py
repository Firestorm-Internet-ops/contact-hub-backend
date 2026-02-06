import logging
import sys
import os
from datetime import datetime, timezone

# Setup Path
sys.path.append(os.getcwd())
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import models
from app.core.database import SessionLocal

logging.basicConfig(level=logging.INFO)

def seed():
    db = SessionLocal()
    try:
        # 1. Create Site
        site = db.query(models.Site).filter_by(url="https://example.com").first()
        if not site:
            print("Creating Demo Site...")
            site = models.Site(
                name="Demo Site",
                url="https://example.com",
                api_key="demo_key",
                api_secret="demo_secret"
            )
            db.add(site)
            db.commit()
            db.refresh(site)
        
        # 2. Create Submission
        if not db.query(models.Submission).first():
            print("Creating Test Submission...")
            sub = models.Submission(
                site_id=site.id,
                fluent_form_id=101,
                form_id=1,
                status="pending",
                data={"name": "John Doe", "message": "I want to buy!"},
                submitted_at=datetime.now(timezone.utc)
            )
            db.add(sub)
            db.commit()
            print("Seeding Complete! 🌱")
        else:
            print("Data already exists. Skipping.")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed()