"use client";

import { FormEvent, useMemo, useState } from "react";

type SourceReference = {
  id: number;
  name: string;
  url: string;
  reference_period?: string | null;
  retrieved_at?: string | null;
  parser_version: string;
};

type NodeProvenance = {
  formula: string;
  pool_code: string;
  pool_name: string;
  rule_description: string;
  metric: string;
  status: string;
  source_snapshots: SourceReference[];
  notes: string[];
};

type ReceiptNode = {
  key: string;
  label: string;
  node_type: string;
  allocated_amount: string;
  government_spending_amount?: string | null;
  relation: string;
  confidence: string;
  allocation_status: string;
  provenance: NodeProvenance[];
};

type PoolReceipt = {
  code: string;
  name: string;
  contribution: string;
  eligible_government_spending: string;
  relation: string;
  confidence: string;
  allocation_status: string;
};

type Receipt = {
  methodology_version: string;
  spending_fiscal_year: number;
  total_allocable_taxes: string;
  conservation_difference: string;
  purpose: ReceiptNode[];
  pools: PoolReceipt[];
  warnings: string[];
  tax_result: {
    taxable_income: string;
    federal_income_tax_liability: string;
    social_security_tax: string;
    medicare_tax: string;
    additional_medicare_tax: string;
    total_personal_tax_liability: string;
  };
};

type ExplorerNode = {
  key: string;
  label: string;
  node_type: string;
  allocated_amount: string;
  government_amount?: string | null;
  relation: string;
  confidence: string;
  additive: boolean;
  method: string;
  drilldown_views: string[];
  notes: string[];
  sources?: SourceReference[];
};

type ExplorerResult = {
  view: string;
  parent_type?: string | null;
  parent_key?: string | null;
  scope_amount: string;
  nodes: ExplorerNode[];
  conservation_difference: string;
  warnings: string[];
};

type SearchResult = {
  entity_type: string;
  entity_key: string;
  title: string;
  subtitle?: string | null;
  score: string;
  matched_aliases: string[];
  metadata: Record<string, unknown>;
  additive: boolean;
  warning: string;
  attributable_amount?: string | null;
  government_amount?: string | null;
  relation?: string | null;
  confidence?: string | null;
  attribution_note?: string | null;
  suggested_view?: string | null;
  parent_type?: string | null;
  parent_key?: string | null;
};

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const VIEWS = ["purpose", "agency", "account", "program_activity", "object_class", "award"] as const;

type View = (typeof VIEWS)[number];

function money(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(parsed);
}

function viewLabel(view: string) {
  return view.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function Home() {
  const [income, setIncome] = useState("50000");
  const [filingStatus, setFilingStatus] = useState("single");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [explorer, setExplorer] = useState<ExplorerResult | null>(null);
  const [activeView, setActiveView] = useState<View>("purpose");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [trail, setTrail] = useState<Array<{ label: string; view: View; parentType?: string; parentKey?: string }>>([]);

  const payload = useMemo(
    () => ({
      tax_year: 2026,
      spending_fiscal_year: 2025,
      filing_status: filingStatus,
      wage_income: income,
      spouse_wage_income: "0",
      qualifying_children_under_17: 0,
      other_dependents: 0
    }),
    [filingStatus, income]
  );

  async function calculate(event: FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const response = await fetch(`${API}/v1/receipt/federal`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error(await response.text());
      const data: Receipt = await response.json();
      setReceipt(data);
      setExplorer(null);
      setActiveView("purpose");
      setTrail([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadExplorer(view: View, parentType?: string, parentKey?: string, label?: string) {
    if (!receipt) return;
    setError("");
    setLoading(true);
    try {
      const response = await fetch(`${API}/v1/explorer/federal`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...payload, view, parent_type: parentType || null, parent_key: parentKey || null })
      });
      if (!response.ok) throw new Error(await response.text());
      const data: ExplorerResult = await response.json();
      setExplorer(data);
      setActiveView(view);
      if (label) setTrail((old) => [...old, { label, view, parentType, parentKey }]);
      else setTrail([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  function drill(node: ExplorerNode | ReceiptNode) {
    if (node.node_type === "budget_function") {
      loadExplorer("agency", "budget_function", node.key, node.label);
    } else if (node.node_type === "budget_subfunction") {
      loadExplorer("agency", "budget_subfunction", node.key, node.label);
    } else if (node.node_type === "agency") {
      loadExplorer("account", "agency", node.key, node.label);
    } else if (node.node_type === "federal_account") {
      loadExplorer("program_activity", "federal_account", node.key, node.label);
    }
  }

  async function runSearch(event: FormEvent) {
    event.preventDefault();
    if (!searchText.trim()) return;
    setSearching(true);
    setError("");
    try {
      const response = receipt
        ? await fetch(`${API}/v1/search/federal`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ ...payload, q: searchText, limit: 20 })
          })
        : await fetch(`${API}/v1/search?q=${encodeURIComponent(searchText)}&limit=20`);
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      setSearchResults(data.results || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  }

  function openSearchResult(result: SearchResult) {
    if (!receipt || !result.suggested_view || !result.parent_type || !result.parent_key) return;
    if (!VIEWS.includes(result.suggested_view as View)) return;
    loadExplorer(
      result.suggested_view as View,
      result.parent_type,
      result.parent_key,
      result.title
    );
  }

  function downloadReceipt() {
    if (!receipt) return;
    const blob = new Blob([JSON.stringify(receipt, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `taxtrace-federal-receipt-2026-fy${receipt.spending_fiscal_year}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const displayedNodes: Array<ExplorerNode | ReceiptNode> = explorer
    ? explorer.nodes
    : receipt?.purpose || [];

  return (
    <main>
      <section className="hero">
        <p className="eyebrow">TaxTrace · Phases 0–6</p>
        <h1>See the public-finance path behind your federal taxes.</h1>
        <p>
          TaxTrace calculates supported federal tax liability, routes each tax through its financing
          pool, and attributes it to actual FY2025 outlays. General revenue is proportional allocation,
          not literal dollar tracing. Every drill-down stays within an explicitly labeled accounting view.
        </p>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">Step 1</p>
            <h2>Calculate the receipt</h2>
          </div>
          {receipt && <span className="status good">Conservation Δ {money(receipt.conservation_difference)}</span>}
        </div>
        <form className="tax-form" onSubmit={calculate}>
          <label>
            W-2 wages
            <input value={income} onChange={(e) => setIncome(e.target.value)} inputMode="decimal" />
          </label>
          <label>
            Filing status
            <select value={filingStatus} onChange={(e) => setFilingStatus(e.target.value)}>
              <option value="single">Single</option>
              <option value="married_filing_jointly">Married filing jointly</option>
              <option value="married_filing_separately">Married filing separately</option>
              <option value="head_of_household">Head of household</option>
            </select>
          </label>
          <button type="submit" disabled={loading}>{loading ? "Working…" : "Build federal receipt"}</button>
        </form>
        {error && <pre className="error">{error}</pre>}

        {receipt && (
          <>
            <div className="headline-number">
              <span>Supported federal taxes</span>
              <strong>{money(receipt.total_allocable_taxes)}</strong>
              <small>2026 tax rules · FY{receipt.spending_fiscal_year} actual spending profile</small>
            </div>
            <div className="results compact">
              <div><span>Federal income tax</span><strong>{money(receipt.tax_result.federal_income_tax_liability)}</strong></div>
              <div><span>Social Security</span><strong>{money(receipt.tax_result.social_security_tax)}</strong></div>
              <div><span>Medicare</span><strong>{money(receipt.tax_result.medicare_tax)}</strong></div>
            </div>
            <details className="pool-details">
              <summary>Financing-pool routing</summary>
              {receipt.pools.map((pool) => (
                <div className="pool-row" key={pool.code}>
                  <div><strong>{pool.name}</strong><small>{pool.relation} · confidence {pool.confidence}</small></div>
                  <strong>{money(pool.contribution)}</strong>
                </div>
              ))}
            </details>
            <button className="secondary" type="button" onClick={downloadReceipt}>Download auditable receipt JSON</button>
          </>
        )}
      </section>

      {receipt && (
        <section className="panel">
          <div className="section-head">
            <div>
              <p className="eyebrow">Steps 2–3</p>
              <h2>Explore the receipt</h2>
            </div>
            <span className="status">{explorer ? money(explorer.scope_amount) : money(receipt.total_allocable_taxes)} in scope</span>
          </div>

          <div className="tabs" role="tablist">
            {VIEWS.map((view) => (
              <button
                className={activeView === view ? "tab active" : "tab"}
                key={view}
                onClick={() => loadExplorer(view)}
                type="button"
              >
                {viewLabel(view)}
              </button>
            ))}
          </div>

          {trail.length > 0 && (
            <div className="breadcrumbs">
              <button type="button" onClick={() => loadExplorer(activeView)}>All</button>
              {trail.map((item, i) => <span key={`${item.label}-${i}`}>/ {item.label}</span>)}
            </div>
          )}

          {(explorer?.warnings || receipt.warnings).map((warning) => (
            <p className="notice" key={warning}>{warning}</p>
          ))}

          <div className="explorer-list">
            {displayedNodes.map((node) => {
              const canDrill = ["budget_function", "budget_subfunction", "agency", "federal_account"].includes(node.node_type);
              return (
                <div className="explorer-row" key={node.key}>
                  <button className="row-main" disabled={!canDrill} onClick={() => canDrill && drill(node)} type="button">
                    <span className="row-title">{node.label}</span>
                    <span className="meta">{node.node_type.replaceAll("_", " ")} · {node.relation} · confidence {node.confidence}{"allocation_status" in node && node.allocation_status !== "ALLOCATED" ? ` · ${node.allocation_status}` : ""}</span>
                  </button>
                  <div className="row-amount">
                    <strong>{money(node.allocated_amount)}</strong>
                    {canDrill && <small>open →</small>}
                  </div>
                  {"provenance" in node && node.provenance.length > 0 && (
                    <details className="calc-details">
                      <summary>How calculated</summary>
                      {node.provenance.map((item, index) => (
                        <div className="calc-block" key={`${node.key}-prov-${index}`}>
                          <p><strong>{item.pool_name}</strong> · {item.metric} · {item.status}</p>
                          <p>{item.formula}</p>
                          <p>{item.rule_description}</p>
                          {item.source_snapshots.map((source) => (
                            <p key={source.id}>
                              Source: <a href={source.url} target="_blank" rel="noreferrer">{source.name}</a>
                              {source.reference_period ? ` · ${source.reference_period}` : ""}
                            </p>
                          ))}
                        </div>
                      ))}
                    </details>
                  )}
                  {"sources" in node && node.sources && node.sources.length > 0 && (
                    <details className="calc-details">
                      <summary>Sources</summary>
                      {node.sources.map((source) => (
                        <p key={source.id}>
                          <a href={source.url} target="_blank" rel="noreferrer">{source.name}</a>
                          {source.reference_period ? ` · ${source.reference_period}` : ""}
                          {source.parser_version ? ` · parser ${source.parser_version}` : ""}
                        </p>
                      ))}
                    </details>
                  )}
                </div>
              );
            })}
          </div>

          {explorer && Number(explorer.conservation_difference) !== 0 && (
            <p className="error">Explorer conservation difference: {money(explorer.conservation_difference)}</p>
          )}
        </section>
      )}

      <section className="panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">Phase 6</p>
            <h2>Search federal finance</h2>
          </div>
        </div>
        <form className="search-form" onSubmit={runSearch}>
          <input
            aria-label="Search programs, accounts, awards, agencies, or recipients"
            placeholder="Try food stamps, DOD, Florida, debt interest…"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
          <button type="submit" disabled={searching}>{searching ? "Searching…" : "Search"}</button>
        </form>
        {searchResults.length > 0 && (
          <>
            <p className="notice">Search results can overlap. Do not add them together unless an explorer view explicitly says it is additive.</p>
            <div className="search-results">
              {searchResults.map((result) => (
                <div className="search-row" key={`${result.entity_type}:${result.entity_key}`}>
                  <div>
                    <strong>{result.title}</strong>
                    <small>{result.entity_type.replaceAll("_", " ")}{result.subtitle ? ` · ${result.subtitle}` : ""}</small>
                    {result.matched_aliases.length > 0 && <small>Matched alias: {result.matched_aliases.join(", ")}</small>}
                    {result.attributable_amount !== null && result.attributable_amount !== undefined && (
                      <small>Current receipt: <strong>{money(result.attributable_amount)}</strong>{result.relation ? ` · ${result.relation}` : ""}{result.confidence ? ` · confidence ${result.confidence}` : ""}</small>
                    )}
                    {result.attribution_note && <small>{result.attribution_note}</small>}
                  </div>
                  <div className="search-actions">
                    <span className="score">{Number(result.score).toFixed(0)}</span>
                    {receipt && result.suggested_view && result.parent_type && result.parent_key && (
                      <button type="button" className="mini" onClick={() => openSearchResult(result)}>Open →</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="panel quiet">
        <h2>What the numbers mean</h2>
        <p>
          <strong>DIRECT</strong> means the tax is restricted to a financing pool before allocation.
          <strong> ALLOCATED</strong> means fungible revenue is attributed proportionally to eligible actual outlays.
          Search and alternate explorer dimensions describe the same underlying government spending in different ways and are not additive across views.
        </p>
        <p>Methodology and machine-readable API documentation: <code>http://localhost:8000/docs</code>.</p>
      </section>
    </main>
  );
}
