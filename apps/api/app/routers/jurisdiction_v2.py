from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from taxtrace.database import get_db
from taxtrace.warehouse_v2.jurisdiction_resolution import (
    GeographyIdentifierMatch,
    resolve_jurisdiction_matches,
)

router = APIRouter(prefix="/jurisdictions", tags=["jurisdiction-resolution-v2"])


class GeographyIdentifierInput(BaseModel):
    scheme: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=255)
    geography_type: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=512)
    required: bool = True


class JurisdictionResolutionRequest(BaseModel):
    fiscal_year: int = Field(ge=1900, le=2200)
    matches: list[GeographyIdentifierInput] = Field(min_length=1, max_length=100)


@router.post("/resolve")
def resolve_jurisdictions(
    request: JurisdictionResolutionRequest,
    session: Session = Depends(get_db),
) -> dict:
    result = resolve_jurisdiction_matches(
        session,
        fiscal_year=request.fiscal_year,
        matches=[
            GeographyIdentifierMatch(
                scheme=item.scheme,
                value=item.value,
                geography_type=item.geography_type,
                name=item.name,
                required=item.required,
            )
            for item in request.matches
        ],
    )
    return {
        "fiscal_year": result.fiscal_year,
        "complete": result.complete,
        "additive": result.additive,
        "warning": (
            "Jurisdiction resolution identifies overlapping governments applicable to one "
            "location. Their spending is not one additive hierarchy."
        ),
        "jurisdictions": [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "level": item.level,
                "matched_identifiers": [
                    {
                        "scheme": match.scheme,
                        "value": match.value,
                        "geography_type": match.geography_type,
                        "name": match.name,
                        "required": match.required,
                    }
                    for match in item.matched_identifiers
                ],
            }
            for item in result.jurisdictions
        ],
        "relations": [
            {
                "subject_jurisdiction_id": relation.subject_jurisdiction_id,
                "object_jurisdiction_id": relation.object_jurisdiction_id,
                "relation_type": relation.relation_type,
                "dataset_release_id": relation.dataset_release_id,
                "valid_from_year": relation.valid_from_year,
                "valid_to_year": relation.valid_to_year,
            }
            for relation in result.relations
        ],
        "unmatched": [
            {
                "scheme": item.scheme,
                "value": item.value,
                "geography_type": item.geography_type,
                "name": item.name,
                "required": item.required,
            }
            for item in result.unmatched
        ],
        "warnings": list(result.warnings),
    }
