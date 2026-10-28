from fastapi import FastAPI
from .api import compliance_rules, vendor_files, vendors,alert, users, auth
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .auth.accounts import ensure_default_admin
from .config.database import SessionLocal


logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    with SessionLocal() as session:
        done = ensure_default_admin(session)
        session.commit()
    if done:
        logger.warning(done)
    yield

app = FastAPI(title="Document intelligence", lifespan=lifespan)

app.include_router(vendors.router)
app.include_router(vendor_files.router)
app.include_router(compliance_rules.router)
app.include_router(alert.router)
app.include_router(users.router)
app.include_router(auth.router)

