import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.dependencies import current_user
from src.config.database import get_session
from src.models import Component, Vendor

router = APIRouter(tags=["vendors"], dependencies=[Depends(current_user)])


# --- Request and response shapes (Pydantic checks incoming JSON against these) ---


class VendorOut(BaseModel):
    # from_attributes lets Pydantic read a SQLAlchemy object (vendor.name)
    # as well as a dict (vendor["name"]).
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    aliases: list[str]



class ComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vendor_id: uuid.UUID
    name: str
    vendor_part_number: str | None
    internal_part_number: str | None
    description: str | None
    aliases: list[str]


@router.get("/vendors", response_model=list[VendorOut])
def list_vendors(session: Session = Depends(get_session)) -> list[Vendor]:

    return list(session.scalars(select(Vendor).order_by(Vendor.name)))

@router.get("/components", response_model=list[ComponentOut])
def list_components(vendor_id: uuid.UUID | None = None, session: Session = Depends(get_session)) -> list[Component]:
    query = select(Component).order_by(Component.name)
    if vendor_id is not None:
        query = query.where(Component.vendor_id == vendor_id)
    return list(session.scalars(query))


