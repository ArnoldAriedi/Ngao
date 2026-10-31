from sqlalchemy import create_engine

from app import models  # noqa: F401
from app.config import settings
from app.db import Base

if __name__ == "__main__":
    Base.metadata.create_all(bind=create_engine(settings.migration_database_url or settings.database_url))
    print("Tables created.")
