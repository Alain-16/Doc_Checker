"""Adding what rules need: key attributes and document types QA names before any document shows them."""

import re
from dataclasses import dataclass, field

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.classification.classifier import MERGE_SIMILARITY, most_similar_type, type_name_from
from src.compliance.rules import RuleError
from src.models import DocumentType, KeyAttribute
from src.models.compliance import AttributeGroup, AttributeValueType
from src.models.document import DocumentTypeOrigin

# Also the field name in the schema GPT fills in, so it must work as one.
ATTRIBUTE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


@dataclass(frozen=True)
class AttributeSpec:
    name: str
    display_name: str
    description: str  # the extraction instruction, including the unit for a number
    value_type: AttributeValueType
    search_query: str
    document_type: str | None = None
    record_fields: list[str] = field(default_factory=list)
    required: bool = False


def check_field_name(name: str) -> None:
    if not ATTRIBUTE_NAME.match(name) or hasattr(BaseModel, name):
        raise RuleError(f"'{name}' can't be used as a name: use lower case letters, digits and underscores.")


def add_key_attribute(session: Session, spec: AttributeSpec) -> KeyAttribute:
    """A priority attribute: QA's own, found by searching each document's index."""
    check_field_name(spec.name)
    for record_field in spec.record_fields:
        check_field_name(record_field)
    if (spec.value_type == AttributeValueType.RECORDS) != bool(spec.record_fields):
        raise RuleError(f"'{spec.name}': record fields go with value type records, and only with it.")
    if not spec.search_query.strip():
        raise RuleError(f"'{spec.name}' needs a search query: it says where to look in each document.")
    if session.scalar(select(KeyAttribute.id).where(KeyAttribute.name == spec.name)):
        raise RuleError(f"A key attribute named {spec.name} already exists.")
    document_type_id = None
    if spec.document_type is not None:
        document_type_id = session.scalar(select(DocumentType.id).where(DocumentType.name == spec.document_type))
        if document_type_id is None:
            raise RuleError(f"Unknown document type: {spec.document_type}.")
    attribute = KeyAttribute(
        name=spec.name,
        display_name=spec.display_name,
        description=spec.description,
        attribute_group=AttributeGroup.PRIORITY,
        value_type=spec.value_type,
        document_type_id=document_type_id,
        record_fields=spec.record_fields,
        search_query=spec.search_query,
        required=spec.required,
        active=True,
    )
    session.add(attribute)
    session.flush()
    return attribute


def add_document_type(session: Session, display_name: str, description: str) -> DocumentType:
    """A type QA's rule names. Practically the same name reuses the existing type,
    bringing it back if it was retired: the classifier then offers it again."""
    types = list(session.scalars(select(DocumentType)))
    similar, similarity = most_similar_type(display_name, types)
    if similar is not None and similarity >= MERGE_SIMILARITY:
        similar.active = True
        return similar
    document_type = DocumentType(
        name=type_name_from(display_name),
        display_name=display_name,
        description=description,
        origin=DocumentTypeOrigin.CONFIGURED,
        aliases=[],
        active=True,
    )
    session.add(document_type)
    session.flush()
    return document_type
