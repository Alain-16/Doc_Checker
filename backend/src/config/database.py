from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Not dead: importing trail.py registers the Session listeners that write the
# Part 11 audit trail. ruff would delete an unused import, hence the noqa.
import src.audit.trail  # noqa: F401

from .settings import get_settings

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