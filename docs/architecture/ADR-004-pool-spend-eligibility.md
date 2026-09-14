# ADR-004 — Funding pools require explicit expenditure eligibility rules

Status: accepted

Tax-to-pool mapping alone is not enough to construct a receipt. Each funding pool must also have an effective-dated rule specifying which actual expenditure facts form its allocation denominator.

TaxTrace therefore stores `PoolSpendRule` records. General revenue uses a documented proportional allocation domain; the OASI/DI pools are excluded from that domain at the Social Security spending base, while Medicare remains in the general domain because Medicare is mixed-funded. Dedicated OASI/DI/Medicare HI contributions are still restricted before subdivision. A displayed purpose funded by more than one pool is marked `MIXED_FUNDING`, with confidence reflecting the separability of the public data. If no eligible facts are available, the engine emits `UNALLOCATED_DETAIL` rather than silently broadening the domain.
