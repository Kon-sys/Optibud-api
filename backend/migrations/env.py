from logging.config import fileConfig
from alembic import context
from dotenv import load_dotenv

# Импортируем наш файл Base и модели, чтобы Alembic мог генерировать миграции
from app.models.base import Base

config = context.config

load_dotenv()

# Читаем параметры из переменных окружения и собираем строку подключения динамически
db_user = os.getenv("POSTGRES_USER", "optibud_user")
db_password = os.getenv("POSTGRES_PASSWORD", "optibud_password")
db_host = os.getenv("POSTGRES_HOST", "localhost")
db_port = os.getenv("POSTGRES_PORT", "5433")
db_name = os.getenv("POSTGRES_DB", "optibud_db")

# Динамически переопределяем sqlalchemy.url в конфиге Alembic
database_url = f"postgresql+psycopg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Получаем URL напрямую из конфигурации alembic.ini
    url = config.get_main_option("sqlalchemy.url")

    # Создаем движок напрямую через create_engine (это проще и надежнее)
    from sqlalchemy import create_engine
    connectable = create_engine(url)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_online() # или offline
else:
    run_migrations_online()

