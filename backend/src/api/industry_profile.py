from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit.trail import set_audit_reason
from src.auth.dependencies import ADMINS, current_user, require_role
from src.config.database import get_session
from src.industry.profile import PRESETS, current_profile
from src.models import IndustryProfile

# Anyone signed in can read it (the frontend needs the labels); only admins change it.
router = APIRouter(prefix="/industry-profile", tags=["industry profile"], dependencies=[Depends(current_user)])


class ProfileOut(BaseModel):
    preset: str | None
    industry: str
    description: str
    vendor_label: str
    vendor_label_plural: str
    component_label: str
    component_label_plural: str


class ProfileChange(BaseModel):
    """Either a preset name, or the fields; given fields override the preset's."""

    preset: str | None = Field(default=None, description=f"One of: {', '.join(PRESETS)}.")
    industry: str | None = Field(default=None, min_length=2)
    description: str | None = Field(default=None, min_length=10)
    vendor_label: str | None = Field(default=None, min_length=2)
    vendor_label_plural: str | None = Field(default=None, min_length=2)
    component_label: str | None = Field(default=None, min_length=2)
    component_label_plural: str | None = Field(default=None, min_length=2)
    reason: str = Field(min_length=10, description="Why the profile changes (audit trail).")


@router.get("", response_model=ProfileOut)
def read_profile(session: Session = Depends(get_session)) -> ProfileOut:
    return ProfileOut(**current_profile(session).as_dict())


@router.get("/presets", response_model=dict[str, ProfileOut])
def list_presets() -> dict[str, ProfileOut]:
    return {name: ProfileOut(**preset.as_dict()) for name, preset in PRESETS.items()}


@router.put("", response_model=ProfileOut, dependencies=[Depends(require_role(*ADMINS))])
def change_profile(body: ProfileChange, session: Session = Depends(get_session)) -> ProfileOut:
    """Set the installation's industry. Applies to documents processed and questions asked
    from now on; documents already processed keep the types and names they were given."""
    if body.preset is not None and body.preset not in PRESETS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown preset. Choose one of: {', '.join(PRESETS)}.")
    start = PRESETS[body.preset] if body.preset else current_profile(session)
    fields = {**start.as_dict(), **body.model_dump(exclude={"reason"}, exclude_none=True)}
    if body.industry is not None or body.description is not None:
        fields["preset"] = None  # customised: no longer the preset as shipped

    set_audit_reason(session, body.reason)
    row = session.scalars(select(IndustryProfile)).one_or_none()
    if row is None:
        row = IndustryProfile()
        session.add(row)
    for name, value in fields.items():
        setattr(row, name, value)
    session.commit()
    return ProfileOut(**current_profile(session).as_dict())
