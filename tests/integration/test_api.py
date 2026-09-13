from fastapi.testclient import TestClient

from apps.api.app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_federal_tax_api():
    response = client.post(
        "/v1/tax/federal",
        json={
            "tax_year": 2026,
            "filing_status": "single",
            "wage_income": "50000",
            "spouse_wage_income": "0",
            "qualifying_children_under_17": 0,
            "other_dependents": 0,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["federal_income_tax_liability"] == "3820.00"
    assert body["total_personal_tax_liability"] == "7645.00"
