import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.config.database import get_session
from src.models import Component, Vendor

router = APIRouter(tags=["vendors"])

NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


# --- Request and response shapes (Pydantic checks incoming JSON against these) ---


class VendorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class VendorOut(BaseModel):
    # from_attributes lets Pydantic read a SQLAlchemy object (vendor.name)
    # as well as a dict (vendor["name"]).
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class ComponentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    vendor_part_number: str | None = None
    internal_part_number: str | None = None
    description: str | None = None


class ComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vendor_id: uuid.UUID
    name: str
    vendor_part_number: str | None
    internal_part_number: str | None
    description: str | None


def normalize_vendor_name(name: str) -> str:
    """"West Pharmaceutical Services, Inc." -> "west pharmaceutical services inc".

    Two spellings of the same vendor collide on normalized_name's UNIQUE
    constraint, so the same vendor can't be created twice by accident.
    """
    return NON_ALPHANUMERIC.sub(" ", name.casefold()).strip()


