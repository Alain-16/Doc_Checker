# Connects Alembic to our settings (database URL) and our models (the target schema).
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from src.config.settings import get_settings

# Importing the models package registers every table on Base.metadata,
# which is what autogenerate compares the database against.
from src.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    # Read from .env / environment variables through our settings, never from
    # alembic.ini, so no database password ends up in a committed file.
    return str(get_settings().database_url)


def run_migrations_offline() -> None:
    """Write the migration SQL to the screen instead of running it (alembic ... --sql)."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply the migrations."""
    # NullPool: open one connection, use it, close it. A migration run is short
    # and shouldn't keep idle connections around.
    engine = create_engine(get_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
