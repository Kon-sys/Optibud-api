import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

load_dotenv()


def _build_database_url() -> str:
    """Собираем URL так же, как это делает Alembic в migrations/env.py.

    DATABASE_URL (если задан явно) имеет приоритет — это удобно для
    локального запуска вне Docker. Внутри docker-compose контейнеры
    общаются по имени сервиса/контейнера, а не по localhost, поэтому
    компоненты (POSTGRES_HOST и т.д.) должны совпадать с тем, что
    передаёт docker-compose.yml.
    """
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    db_user = os.getenv("POSTGRES_USER", "optibud_user")
    db_password = os.getenv("POSTGRES_PASSWORD", "optibud_password")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "optibud_db")
    return f"postgresql+psycopg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"


SQLALCHEMY_DATABASE_URL = _build_database_url()

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

logger = logging.getLogger(__name__)


def get_db():
    db = SessionLocal()
    logger.debug("Открытие новой сессии базы данных.")
    try:
        yield db
    except SQLAlchemyError as e:
        logger.error(f"Ошибка базы данных (SQLAlchemyError): {e}", exc_info=True)
        db.rollback()  # Обязательно откатываем транзакцию при ошибке
        raise
    except Exception as e:
        logger.critical(f"Непредвиденная ошибка в сессии БД: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()
        logger.debug("Сессия базы данных закрыта.")
