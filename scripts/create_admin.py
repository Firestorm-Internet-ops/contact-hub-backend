import logging
import sys
import os

# Ensure backend directory is in python path
sys.path.append(os.getcwd())
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import models
from app.core import security
from app.core.database import SessionLocal
from app.core.config import settings

logging.basicConfig(level=logging.INFO)

def init_db():
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(
            models.User.email == settings.ADMIN_EMAIL
        ).first()

        if user:
            print("Admin user already exists. Skipping...")
        else:
            print("Creating admin user...")
            new_user = models.User(
                email=settings.ADMIN_EMAIL,
                hashed_password=security.get_password_hash(settings.ADMIN_PASSWORD),
                role="admin",
                is_active=True,
            )
            db.add(new_user)
            db.commit()
            print("Admin user created successfully.")
    
    except Exception as e:
        db.rollback()
        print(f"Error initializing DB: {e}")
        raise e
        
    finally:
        db.close()

if __name__ == "__main__":
    init_db()