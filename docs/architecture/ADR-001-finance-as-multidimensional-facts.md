# ADR-001: Store federal finance as multidimensional facts, not one spending tree

Status: accepted

Federal expenditures can be classified simultaneously by agency, account, program activity, object class, function, award, and recipient. These classifications overlap. A single hierarchy would either duplicate money or discard useful dimensions.

Decision: store monetary `SpendFact` rows with explicit `record_scope` and dimension foreign keys. Treat scopes as separate views unless a documented transformation establishes a mutually exclusive partition.
