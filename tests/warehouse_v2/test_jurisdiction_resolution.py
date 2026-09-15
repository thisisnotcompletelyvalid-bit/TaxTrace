from taxtrace.db_models import Jurisdiction
from taxtrace.enums import JurisdictionLevel
from taxtrace.warehouse_v2.db_models import GovernmentIdentifier, JurisdictionRelation
from taxtrace.warehouse_v2.jurisdiction_resolution import (
    GeographyIdentifierMatch,
    resolve_jurisdiction_matches,
)
from apps.api.app.routers.jurisdiction_v2 import (
    GeographyIdentifierInput,
    JurisdictionResolutionRequest,
    resolve_jurisdictions,
)


def _seed_resolution_graph(db_session):
    state = Jurisdiction(code="WA", name="Washington", level=JurisdictionLevel.STATE)
    county = Jurisdiction(code="TEST-KING", name="King County", level=JurisdictionLevel.COUNTY)
    city = Jurisdiction(code="TEST-SEATTLE", name="Seattle", level=JurisdictionLevel.MUNICIPAL)
    school = Jurisdiction(
        code="TEST-SEATTLE-SCHOOL",
        name="Seattle School District",
        level=JurisdictionLevel.SCHOOL,
    )
    special = Jurisdiction(
        code="TEST-TRANSIT",
        name="Regional Transit District",
        level=JurisdictionLevel.SPECIAL_DISTRICT,
    )
    db_session.add_all([state, county, city, school, special])
    db_session.flush()

    identifiers = [
        GovernmentIdentifier(
            jurisdiction_id=state.id,
            scheme="CENSUS_STATE_GEOID",
            value="53",
            valid_from_year=2020,
        ),
        GovernmentIdentifier(
            jurisdiction_id=county.id,
            scheme="CENSUS_COUNTY_GEOID",
            value="53033",
            valid_from_year=2020,
        ),
        GovernmentIdentifier(
            jurisdiction_id=city.id,
            scheme="CENSUS_PLACE_GEOID",
            value="5363000",
            valid_from_year=2020,
        ),
        GovernmentIdentifier(
            jurisdiction_id=city.id,
            scheme="CENSUS_PLACE_FIPS",
            value="63000",
            valid_from_year=2020,
        ),
        GovernmentIdentifier(
            jurisdiction_id=school.id,
            scheme="CENSUS_UNIFIED_SCHOOL_GEOID",
            value="5307710",
            valid_from_year=2022,
        ),
        GovernmentIdentifier(
            jurisdiction_id=special.id,
            scheme="STATE_SPECIAL_DISTRICT_ID",
            value="TRANSIT-1",
            valid_from_year=2022,
        ),
        GovernmentIdentifier(
            jurisdiction_id=city.id,
            scheme="HISTORIC_PLACE_ID",
            value="OLD-SEATTLE",
            valid_to_year=2021,
        ),
    ]
    db_session.add_all(identifiers)
    db_session.flush()

    db_session.add_all(
        [
            JurisdictionRelation(
                subject_jurisdiction_id=county.id,
                object_jurisdiction_id=state.id,
                relation_type="GEOGRAPHICALLY_WITHIN",
                valid_from_year=2020,
            ),
            JurisdictionRelation(
                subject_jurisdiction_id=city.id,
                object_jurisdiction_id=county.id,
                relation_type="GEOGRAPHICALLY_WITHIN",
                valid_from_year=2020,
            ),
            JurisdictionRelation(
                subject_jurisdiction_id=school.id,
                object_jurisdiction_id=county.id,
                relation_type="OVERLAPS",
                valid_from_year=2022,
            ),
            JurisdictionRelation(
                subject_jurisdiction_id=special.id,
                object_jurisdiction_id=city.id,
                relation_type="OVERLAPS",
                valid_from_year=2022,
            ),
        ]
    )
    db_session.commit()
    return state, county, city, school, special


def test_resolver_returns_overlapping_applicable_governments_without_deduping_by_level(db_session) -> None:
    state, county, city, school, special = _seed_resolution_graph(db_session)

    result = resolve_jurisdiction_matches(
        db_session,
        fiscal_year=2022,
        matches=[
            GeographyIdentifierMatch("census_state_geoid", "53", "state"),
            GeographyIdentifierMatch("CENSUS_COUNTY_GEOID", "53033", "county"),
            GeographyIdentifierMatch("CENSUS_PLACE_GEOID", "5363000", "place"),
            GeographyIdentifierMatch("CENSUS_PLACE_FIPS", "63000", "place"),
            GeographyIdentifierMatch(
                "CENSUS_UNIFIED_SCHOOL_GEOID", "5307710", "unified_school_district"
            ),
            GeographyIdentifierMatch(
                "STATE_SPECIAL_DISTRICT_ID", "TRANSIT-1", "special_district"
            ),
        ],
    )

    assert result.complete is True
    assert result.additive is False
    assert [item.id for item in result.jurisdictions] == [
        state.id,
        county.id,
        city.id,
        school.id,
        special.id,
    ]
    assert len(result.jurisdictions[2].matched_identifiers) == 2
    assert {relation.relation_type for relation in result.relations} == {
        "GEOGRAPHICALLY_WITHIN",
        "OVERLAPS",
    }
    assert len(result.relations) == 4
    assert result.unmatched == ()
    assert any("not additive" in warning for warning in result.warnings)


def test_resolver_honors_identifier_validity_and_required_matches(db_session) -> None:
    _seed_resolution_graph(db_session)

    result = resolve_jurisdiction_matches(
        db_session,
        fiscal_year=2022,
        matches=[
            GeographyIdentifierMatch("HISTORIC_PLACE_ID", "OLD-SEATTLE", "place"),
            GeographyIdentifierMatch(
                "UNMAPPED_OPTIONAL", "OPTIONAL", "special_district", required=False
            ),
        ],
    )

    assert result.complete is False
    assert result.jurisdictions == ()
    assert len(result.unmatched) == 2
    assert result.unmatched[0].required is True
    assert result.unmatched[1].required is False


def test_optional_unmatched_geography_does_not_make_resolution_incomplete(db_session) -> None:
    _seed_resolution_graph(db_session)

    result = resolve_jurisdiction_matches(
        db_session,
        fiscal_year=2022,
        matches=[
            GeographyIdentifierMatch("CENSUS_STATE_GEOID", "53", "state"),
            GeographyIdentifierMatch(
                "UNKNOWN_SPECIAL", "NONE", "special_district", required=False
            ),
        ],
    )

    assert result.complete is True
    assert len(result.jurisdictions) == 1
    assert len(result.unmatched) == 1


def test_resolution_api_preserves_non_additive_semantics(db_session) -> None:
    state, county, *_ = _seed_resolution_graph(db_session)

    response = resolve_jurisdictions(
        JurisdictionResolutionRequest(
            fiscal_year=2022,
            matches=[
                GeographyIdentifierInput(
                    scheme="CENSUS_STATE_GEOID",
                    value="53",
                    geography_type="state",
                ),
                GeographyIdentifierInput(
                    scheme="CENSUS_COUNTY_GEOID",
                    value="53033",
                    geography_type="county",
                ),
            ],
        ),
        session=db_session,
    )

    assert response["complete"] is True
    assert response["additive"] is False
    assert [item["id"] for item in response["jurisdictions"]] == [state.id, county.id]
    assert response["relations"] == [
        {
            "subject_jurisdiction_id": county.id,
            "object_jurisdiction_id": state.id,
            "relation_type": "GEOGRAPHICALLY_WITHIN",
            "dataset_release_id": None,
            "valid_from_year": 2020,
            "valid_to_year": None,
        }
    ]
