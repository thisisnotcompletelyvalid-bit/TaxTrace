# ADR-006 — Search is discovery, not an additive accounting view

Status: accepted

Search may return a program, account, award, recipient, agency, and canonical category for the same underlying spending. Search results are therefore always non-additive. Receipt-aware search may attach a taxpayer-specific attributable amount when a result can be defensibly mapped to a receipt/explorer node, but those amounts remain non-additive and must not be summed across hits. Official names remain unchanged; abbreviations, automatic aliases, and curated synonyms are stored as separate search metadata.
