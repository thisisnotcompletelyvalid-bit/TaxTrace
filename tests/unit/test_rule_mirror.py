from pathlib import Path


def test_packaged_tax_rules_match_repository_mirror():
    packaged = Path("src/taxtrace/data/tax_rules/federal/2026.json").read_bytes()
    mirror = Path("data/tax_rules/federal/2026.json").read_bytes()
    assert packaged == mirror
