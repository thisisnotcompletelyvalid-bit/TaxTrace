# ADR-002: Preserve immutable raw source snapshots

Status: accepted

Government datasets are revised. Reproducibility requires knowing exactly which bytes produced a published result.

Decision: archive raw bytes by SHA-256 and create a new `SourceSnapshot` for every retrieval. Never replace an existing snapshot's bytes in place. Parser versions are recorded separately from source versions.
