import os

import logging
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

load_dotenv()



SQLALCHEMY_DATABASE_URL = str(os.getenv('DATABASE_URL'))


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