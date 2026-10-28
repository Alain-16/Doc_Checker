from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker,Session

from .settings import get_settings
import src.audit.trail


engine = create_engine(
    str(get_settings().database_url),

    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,

    expire_on_commit=False,
)

def get_session() ->  Iterator[Session]:

    with SessionLocal() as session:
        yield session