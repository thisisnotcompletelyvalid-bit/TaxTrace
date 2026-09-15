"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type DatasetReadiness = {
  dataset_key: string;
  release_key?: string | null;
  status: string;
  coverage_type?: string | null;
  row_count: number;
  government_count: number;
  parquet_objects: number;
  ready: boolean;
};

type ProductReadiness = {
  mode: string;
  national_state_local_ready: boolean;
  federal_core_ready: boolean;
  government_registry: DatasetReadiness;
  census_finance_2022: DatasetReadiness;
  census_finance_2024: DatasetReadiness;
  real_omb_account_rows: number;
  real_treasury_rows: number;
  fixture_snapshot_count: number;
  warnings: string[];
};

type Identifier = { scheme: string; value: string };
type GovernmentResult = {
  id: number;
  code: string;
  name: string;
  level: string;
  parent_id?: number | null;
  identifiers: Identifier[];
};

type CoverageRow = {
  dataset_key: string;
  dataset_name: string;
  release: string;
  fiscal_year?: number | null;
  grain: string;
  completeness: string;
  record_count?: number | null;
  classification_count?: number | null;
  quality_grade?: string | null;
  notes?: string | null;
};

type CoverageResponse = {
  government: { id: number; code: string; name: string; level: string };
  coverage: CoverageRow[];
};

type PartitionNode = {
  key: string;
  label: string;
  amount: string;
  item_codes: string[];
  additive: boolean;
};

type PartitionResponse = {
  government: { id: number; code: string; name: string; level: string };
  fiscal_year: number;
  dataset_key: string;
  release: string;
  coverage_type: string;
  taxonomy_version: string;
  formula_key: string;
  additive: boolean;
  parent: { key: string; label: string; amount: string };
  nodes: PartitionNode[];
  residual: PartitionNode;
  excluded_native_expenditure_codes: string[];
  imputed_codes: string[];
  source_row_count: number;
  conservation_difference: string;
  source_urls: string[];
  formula_notes: string[];
  warnings: string[];
};

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function money(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  }).format(parsed);
}

function integer(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US").format(value);
}

function statusClass(ready: boolean) {
  return ready ? "status good" : "status";
}

export default function GovernmentsPage() {
  const [readiness, setReadiness] = useState<ProductReadiness | null>(null);
  const [query, setQuery] = useState("Gainesville");
  const [results, setResults] = useState<GovernmentResult[]>([]);
  const [selected, setSelected] = useState<GovernmentResult | null>(null);
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null);
  const [partition, setPartition] = useState<PartitionResponse | null>(null);
  const [fiscalYear, setFiscalYear] = useState(2022);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/v2/data/product-readiness`)
      .then(async (response) => {
        if (!response.ok) throw new Error(await response.text());
        return response.json();
      })
      .then((data: ProductReadiness) => setReadiness(data))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  async function search(event?: FormEvent) {
    event?.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(
        `${API}/v2/data/governments/search?q=${encodeURIComponent(query.trim())}&limit=50`
      );
      if (!response.ok) throw new Error(await response.text());
      const body = await response.json();
      setResults(body.results || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function openGovernment(government: GovernmentResult, year = fiscalYear) {
    setSelected(government);
    setCoverage(null);
    setPartition(null);
    setLoading(true);
    setError("");
    try {
      const coverageResponse = await fetch(`${API}/v2/data/governments/${government.id}/coverage`);
      if (!coverageResponse.ok) throw new Error(await coverageResponse.text());
      setCoverage(await coverageResponse.json());

      const partitionResponse = await fetch(
        `${API}/v2/data/governments/${government.id}/finance-partition?fiscal_year=${year}`
      );
      if (partitionResponse.ok) {
        setPartition(await partitionResponse.json());
      } else if (partitionResponse.status === 404) {
        setPartition(null);
      } else {
        throw new Error(await partitionResponse.text());
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function changeYear(year: number) {
    setFiscalYear(year);
    if (selected) await openGovernment(selected, year);
  }

  const sortedNodes = useMemo(
    () =>
      partition
        ? [...partition.nodes].sort((a, b) => Number(b.amount) - Number(a.amount))
        : [],
    [partition]
  );

  return (
    <main>
      <section className="hero">
        <p className="eyebrow">TaxTrace · National public finance</p>
        <h1>Explore actual state and local government spending.</h1>
        <p>
          Search the Census government universe, inspect which public-finance datasets TaxTrace has for
          a government, and view the conserved Direct General Expenditure partition established in
          methodology 1.4.0. Raw Census rows remain available as source detail but are not naively summed.
        </p>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">Running data warehouse</p>
            <h2>Is this deployment actually populated?</h2>
          </div>
          {readiness && (
            <span className={statusClass(readiness.national_state_local_ready)}>
              {readiness.mode.replaceAll("_", " ")}
            </span>
          )}
        </div>

        {!readiness && <p>Checking data coverage…</p>}
        {readiness && (
          <>
            <div className="results compact">
              <div>
                <span>Government registry</span>
                <strong>{integer(readiness.government_registry.government_count)}</strong>
                <small>{readiness.government_registry.ready ? "national registry ready" : "not nationally populated"}</small>
              </div>
              <div>
                <span>2022 Census finance rows</span>
                <strong>{integer(readiness.census_finance_2022.row_count)}</strong>
                <small>{integer(readiness.census_finance_2022.government_count)} governments with finance data</small>
              </div>
              <div>
                <span>Real federal account rows</span>
                <strong>{integer(readiness.real_omb_account_rows)}</strong>
                <small>{readiness.real_treasury_rows} real Treasury summary rows</small>
              </div>
            </div>
            {readiness.warnings.map((warning) => (
              <p className="notice" key={warning}>{warning}</p>
            ))}
            {!readiness.national_state_local_ready && (
              <details className="calc-details">
                <summary>How to activate the national dataset</summary>
                <p>
                  Run <code>python -m taxtrace.warehouse_v2.product_activation</code> against the persistent
                  application database, or use the default Docker Compose stack, which now runs the same
                  one-shot activation job before starting the API.
                </p>
              </details>
            )}
          </>
        )}
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">Government registry</p>
            <h2>Search governments</h2>
          </div>
          <span className="status">Census government IDs</span>
        </div>
        <form className="search-form" onSubmit={search}>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Gainesville, Orange County, New York City…"
          />
          <button type="submit" disabled={loading}>{loading ? "Loading…" : "Search"}</button>
        </form>
        {error && <pre className="error">{error}</pre>}

        <div className="search-results">
          {results.map((government) => (
            <div className="search-row" key={government.id}>
              <div>
                <strong>{government.name}</strong>
                <span className="meta">
                  {government.level} · {government.code}
                  {government.identifiers.length
                    ? ` · ${government.identifiers.map((item) => `${item.scheme}:${item.value}`).join(" · ")}`
                    : ""}
                </span>
              </div>
              <button type="button" className="mini" onClick={() => openGovernment(government)}>
                Open
              </button>
            </div>
          ))}
        </div>
        {!loading && results.length === 0 && readiness?.national_state_local_ready && (
          <p className="notice">Search by a government or place name. The national registry contains roughly 92,000 government units.</p>
        )}
      </section>

      {selected && (
        <section className="panel">
          <div className="section-head">
            <div>
              <p className="eyebrow">Selected government</p>
              <h2>{selected.name}</h2>
              <p className="meta">{selected.level} · {selected.code}</p>
            </div>
            <label>
              Finance year
              <select value={fiscalYear} onChange={(event) => changeYear(Number(event.target.value))}>
                <option value={2022}>2022 Census baseline</option>
                <option value={2024}>2024 annual sample</option>
              </select>
            </label>
          </div>

          {coverage && (
            <>
              <h3>Available coverage</h3>
              <div className="explorer-list">
                {coverage.coverage.map((row, index) => (
                  <div className="explorer-row" key={`${row.dataset_key}-${row.release}-${index}`}>
                    <div className="row-main">
                      <span className="row-title">{row.dataset_name}</span>
                      <span className="meta">
                        {row.fiscal_year || "—"} · {row.completeness} · {row.grain} · quality {row.quality_grade || "—"}
                      </span>
                    </div>
                    <div className="row-amount">
                      <strong>{integer(row.record_count)}</strong>
                      <small>{integer(row.classification_count)} classifications</small>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          {!partition && !loading && (
            <p className="notice">
              No READY additive Census finance partition is available for {fiscalYear}. Try the 2022 census baseline;
              2024 is an annual survey sample and does not cover every local government.
            </p>
          )}

          {partition && (
            <>
              <div className="headline-number">
                <span>{partition.parent.label}</span>
                <strong>{money(partition.parent.amount)}</strong>
                <small>
                  FY{partition.fiscal_year} · {partition.coverage_type} · taxonomy {partition.taxonomy_version} · {partition.source_row_count} source rows
                </small>
              </div>

              {partition.warnings.map((warning) => (
                <p className="notice" key={warning}>{warning}</p>
              ))}

              <div className="explorer-list">
                {sortedNodes.map((node) => (
                  <div className="explorer-row" key={node.key}>
                    <div className="row-main">
                      <span className="row-title">{node.label}</span>
                      <span className="meta">Census item codes {node.item_codes.join(", ") || "—"}</span>
                    </div>
                    <div className="row-amount">
                      <strong>{money(node.amount)}</strong>
                      <small>additive within parent</small>
                    </div>
                  </div>
                ))}
              </div>

              <div className="results compact" style={{ marginTop: "1rem" }}>
                <div>
                  <span>Conservation difference</span>
                  <strong>{money(partition.conservation_difference)}</strong>
                </div>
                <div>
                  <span>Excluded native expenditure codes</span>
                  <strong>{partition.excluded_native_expenditure_codes.length}</strong>
                </div>
                <div>
                  <span>Imputed/non-reported codes</span>
                  <strong>{partition.imputed_codes.length}</strong>
                </div>
              </div>

              <details className="calc-details">
                <summary>Formula, exclusions, and sources</summary>
                <p><strong>Formula:</strong> <code>{partition.formula_key}</code></p>
                <p>
                  <strong>Excluded native expenditure codes:</strong>{" "}
                  {partition.excluded_native_expenditure_codes.join(", ") || "none in this government"}
                </p>
                <p>
                  <strong>Imputed/non-reported codes:</strong>{" "}
                  {partition.imputed_codes.join(", ") || "none"}
                </p>
                {partition.formula_notes.map((note) => <p key={note}>{note}</p>)}
                {partition.source_urls.map((url) => (
                  <p key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></p>
                ))}
              </details>
            </>
          )}
        </section>
      )}
    </main>
  );
}
