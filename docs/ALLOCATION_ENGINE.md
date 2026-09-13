# Allocation-engine contract (phase 4 prerequisite)

The allocation engine itself is intentionally not implemented in phases 0–3, but its contract is fixed here so the warehouse is built for it.

Inputs:

- versioned user liabilities by `RevenueType`;
- effective `RevenuePoolMapping` rows;
- funding-pool eligible expenditure facts;
- a selected mutually exclusive spending partition;
- methodology/data versions.

Required outputs:

- attributed amount for every selected expenditure node;
- DIRECT/ALLOCATED/TRACED relation label;
- source/fiscal-year provenance;
- formula inputs;
- confidence metadata;
- an explicit unallocated/residual category if evidence prevents full partitioning.

Hard invariant:

`sum(attributed children) == allocable user contribution to the parent pool`, subject only to internal precision tolerance. Display rounding must be reconciled separately.

This contract is why phases 0–3 model revenue pools and overlapping finance dimensions now instead of retrofitting them after a UI exists.
