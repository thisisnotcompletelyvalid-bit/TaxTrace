from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from taxtrace.db_models import Jurisdiction
from taxtrace.enums import JurisdictionLevel
from taxtrace.warehouse_v2.db_models import GovernmentIdentifier, JurisdictionRelation


@dataclass(frozen=True)
class GeographyIdentifierMatch:
    """One authoritative geography identifier returned by a boundary/geocoder source."""

    scheme: str
    value: str
    geography_type: str
    name: str | None = None
    required: bool = True


@dataclass(frozen=True)
class ResolvedJurisdiction:
    id: int
    code: str
    name: str
    level: str
    matched_identifiers: tuple[GeographyIdentifierMatch, ...]


@dataclass(frozen=True)
class ResolvedRelation:
    subject_jurisdiction_id: int
    object_jurisdiction_id: int
    relation_type: str
    dataset_release_id: int | None
    valid_from_year: int | None
    valid_to_year: int | None


@dataclass(frozen=True)
class JurisdictionResolution:
    fiscal_year: int
    complete: bool
    additive: bool
    jurisdictions: tuple[ResolvedJurisdiction, ...]
    relations: tuple[ResolvedRelation, ...]
    unmatched: tuple[GeographyIdentifierMatch, ...]
    warnings: tuple[str, ...]


_LEVEL_ORDER = {
    JurisdictionLevel.STATE: 10,
    JurisdictionLevel.COUNTY: 20,
    JurisdictionLevel.MUNICIPAL: 30,
    JurisdictionLevel.SCHOOL: 40,
    JurisdictionLevel.SPECIAL_DISTRICT: 50,
    JurisdictionLevel.FEDERAL: 60,
}


def _active_identifier_query(match: GeographyIdentifierMatch, fiscal_year: int):
    return (
        select(GovernmentIdentifier, Jurisdiction)
        .join(Jurisdiction, Jurisdiction.id == GovernmentIdentifier.jurisdiction_id)
        .where(
            GovernmentIdentifier.scheme == match.scheme.strip().upper(),
            GovernmentIdentifier.value == match.value.strip(),
            or_(
                GovernmentIdentifier.valid_from_year.is_(None),
                GovernmentIdentifier.valid_from_year <= fiscal_year,
            ),
            or_(
                GovernmentIdentifier.valid_to_year.is_(None),
                GovernmentIdentifier.valid_to_year >= fiscal_year,
            ),
        )
    )


def _active_relation_query(jurisdiction_ids: set[int], fiscal_year: int):
    return (
        select(JurisdictionRelation)
        .where(
            JurisdictionRelation.subject_jurisdiction_id.in_(jurisdiction_ids),
            JurisdictionRelation.object_jurisdiction_id.in_(jurisdiction_ids),
            or_(
                JurisdictionRelation.valid_from_year.is_(None),
                JurisdictionRelation.valid_from_year <= fiscal_year,
            ),
            or_(
                JurisdictionRelation.valid_to_year.is_(None),
                JurisdictionRelation.valid_to_year >= fiscal_year,
            ),
        )
        .order_by(
            JurisdictionRelation.relation_type,
            JurisdictionRelation.subject_jurisdiction_id,
            JurisdictionRelation.object_jurisdiction_id,
        )
    )


def resolve_jurisdiction_matches(
    session: Session,
    *,
    fiscal_year: int,
    matches: list[GeographyIdentifierMatch] | tuple[GeographyIdentifierMatch, ...],
) -> JurisdictionResolution:
    """Resolve authoritative geography IDs to applicable TaxTrace governments.

    This function deliberately does not geocode an address itself. Adapters for Census
    Geocoder/TIGER or state-specific boundary services should normalize their results to
    ``GeographyIdentifierMatch`` first. That keeps external API response shapes out of the
    accounting model and makes the resolution step deterministic and testable.
    """

    by_jurisdiction: dict[int, tuple[Jurisdiction, list[GeographyIdentifierMatch]]] = {}
    unmatched: list[GeographyIdentifierMatch] = []

    for raw_match in matches:
        match = GeographyIdentifierMatch(
            scheme=raw_match.scheme.strip().upper(),
            value=raw_match.value.strip(),
            geography_type=raw_match.geography_type.strip().upper(),
            name=raw_match.name.strip() if raw_match.name else None,
            required=raw_match.required,
        )
        if not match.scheme or not match.value or not match.geography_type:
            unmatched.append(match)
            continue

        row = session.execute(_active_identifier_query(match, fiscal_year)).first()
        if row is None:
            unmatched.append(match)
            continue
        _, jurisdiction = row
        existing = by_jurisdiction.get(jurisdiction.id)
        if existing is None:
            by_jurisdiction[jurisdiction.id] = (jurisdiction, [match])
        else:
            existing[1].append(match)

    resolved = [
        ResolvedJurisdiction(
            id=jurisdiction.id,
            code=jurisdiction.code,
            name=jurisdiction.name,
            level=jurisdiction.level.value,
            matched_identifiers=tuple(
                sorted(identifier_matches, key=lambda item: (item.scheme, item.value))
            ),
        )
        for jurisdiction, identifier_matches in by_jurisdiction.values()
    ]
    resolved.sort(
        key=lambda item: (
            _LEVEL_ORDER.get(JurisdictionLevel(item.level), 999),
            item.name.casefold(),
            item.id,
        )
    )

    resolved_ids = {item.id for item in resolved}
    relations: tuple[ResolvedRelation, ...] = ()
    if resolved_ids:
        relation_rows = session.scalars(
            _active_relation_query(resolved_ids, fiscal_year)
        ).all()
        relations = tuple(
            ResolvedRelation(
                subject_jurisdiction_id=row.subject_jurisdiction_id,
                object_jurisdiction_id=row.object_jurisdiction_id,
                relation_type=row.relation_type,
                dataset_release_id=row.dataset_release_id,
                valid_from_year=row.valid_from_year,
                valid_to_year=row.valid_to_year,
            )
            for row in relation_rows
        )

    required_unmatched = [item for item in unmatched if item.required]
    warnings: list[str] = []
    if required_unmatched:
        warnings.append(
            "One or more required geography identifiers did not map to a TaxTrace government "
            "for the requested fiscal year."
        )
    if resolved:
        warnings.append(
            "Resolved governments are overlapping taxing/spending authorities, not additive "
            "children of one budget. Do not sum their spending totals across jurisdictions."
        )

    return JurisdictionResolution(
        fiscal_year=fiscal_year,
        complete=not required_unmatched,
        additive=False,
        jurisdictions=tuple(resolved),
        relations=relations,
        unmatched=tuple(unmatched),
        warnings=tuple(warnings),
    )
