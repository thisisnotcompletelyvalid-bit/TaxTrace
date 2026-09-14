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

type WarehouseCoverage = {
  dataset_key: string;
  release_key?: string | null;
  fiscal_year: number;
  status: string;
  full_fiscal_year: boolean;
  row_count?: number | null;
  object_count: number;
  notes: string[];
};

type WarehouseChild = {
  key: string;
  label: string;
  node_type: string;
  allocated_amount: string;
  government_outlay?: string | null;
  program_activity_code?: string | null;
  program_activity_name?: string | null;
  object_class_code?: string | null;
  object_class_name?: string | null;
  additive: boolean;
  residual: boolean;
  method: string;
  notes: string[];
};

type WarehouseAccount = {
  key: string;
  account_code: string;
  account_name: string;
  allocated_amount: string;
  omb_government_outlay: string;
  file_b_government_outlay?: string | null;
  children: WarehouseChild[];
  conservation_difference: string;
  warehouse_matched: boolean;
  notes: string[];
};

type ReceiptV2 = {
  base_receipt: Receipt;
  warehouse: WarehouseCoverage;
  accounts: WarehouseAccount[];
  residual_amount: string;
  additive_partition_total: string;
  conservation_difference: string;
  warnings: string[];
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

type AwardCoverage = {
  dataset_key: string;
  release_key?: string | null;
  fiscal_year: number;
  status: string;
  full_fiscal_year: boolean;
  row_count?: number | null;
  object_count: number;
  notes: string[];
};

type AwardNode = {
  key: string;
  label: string;
  node_type: string;
  allocated_amount: string;
  file_c_government_outlay?: string | null;
  award_identity?: string | null;
  award_family?: string | null;
  recipient_name?: string | null;
  recipient_uei?: string | null;
  description?: string | null;
  source_row_count: number;
  linked: boolean;
  residual: boolean;
  additive_within_account: boolean;
  method: string;
  notes: string[];
};

type AccountAwardProjection = {
  key: string;
  account_code: string;
  account_name: string;
  allocated_amount: string;
  file_b_government_outlay?: string | null;
  file_c_government_outlay?: string | null;
  file_c_share_of_file_b?: string | null;
  children: AwardNode[];
  conservation_difference: string;
  projection_available: boolean;
  notes: string[];
};

type AwardProjectionResult = {
  receipt: ReceiptV2;
  file_c: AwardCoverage;
  accounts: AccountAwardProjection[];
  warnings: string[];
};

type PrimeAwardSummary = {
  award_identity: string;
  award_family: string;
  transaction_count: number;
  award_id_piid?: string | null;
  award_id_fain?: string | null;
  award_id_uri?: string | null;
  recipient_name?: string | null;
  recipient_uei?: string | null;
  description?: string | null;
  awarding_agency_name?: string | null;
  funding_agency_name?: string | null;
  award_type?: string | null;
  first_action_date?: string | null;
  last_action_date?: string | null;
  additive: boolean;
  personalized_amount: null;
  notes: string[];
};

type SubawardDetailNode = {
  key: string;
  prime_award_identity: string;
  award_family: string;
  subaward_number?: string | null;
  subawardee_name?: string | null;
  subawardee_uei?: string | null;
  subaward_amount?: string | null;
  description?: string | null;
  action_date?: string | null;
  additive: boolean;
  personalized_amount: null;
  notes: string[];
};

type AwardDetailResult = {
  award_identity: string;
  fiscal_year: number;
  prime_coverage: AwardCoverage;
  subaward_coverage: AwardCoverage;
  prime?: PrimeAwardSummary | null;
  subawards: SubawardDetailNode[];
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
const VIEWS = ["purpose", "agency", "account", "program_activity", "object_class"] as const;

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

function percentage(value: string | null | undefined) {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return `${(parsed * 100).toFixed(1)}%`;
}

export default function Home() {
  const [income, setIncome] = useState("50000");
  const [filingStatus, setFilingStatus] = useState("single");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [receiptV2, setReceiptV2] = useState<ReceiptV2 | null>(null);
  const [explorer, setExplorer] = useState<ExplorerResult | null>(null);
  const [activeView, setActiveView] = useState<View>("purpose");
  const [selectedWarehouseAccount, setSelectedWarehouseAccount] = useState<string | null>(null);
  const [awardProjection, setAwardProjection] = useState<AwardProjectionResult | null>(null);
  const [selectedAwardAccount, setSelectedAwardAccount] = useState<string | null>(null);
  const [awardDetail, setAwardDetail] = useState<AwardDetailResult | null>(null);
  const [awardLoading, setAwardLoading] = useState(false);
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
      const response = await fetch(`${API}/v2/receipt/federal`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error(await response.text());
      const data: ReceiptV2 = await response.json();
      setReceiptV2(data);
      setReceipt(data.base_receipt);
      setExplorer(null);
      setActiveView("purpose");
      setTrail([]);
      setSelectedWarehouseAccount(null);
      setAwardProjection(null);
      setSelectedAwardAccount(null);
      setAwardDetail(null);
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

  async function loadAwards() {
    if (!receipt || awardProjection) return;
    setAwardLoading(true);
    setError("");
    try {
      const response = await fetch(`${API}/v2/explorer/federal/awards`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error(await response.text());
      const data: AwardProjectionResult = await response.json();
      setAwardProjection(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAwardLoading(false);
    }
  }

  async function loadAwardDetail(identity: string) {
    setAwardLoading(true);
    setError("");
    try {
      const response = await fetch(`${API}/v2/explorer/federal/award-detail`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ fiscal_year: payload.spending_fiscal_year, award_identity: identity })
      });
      if (!response.ok) throw new Error(await response.text());
      const data: AwardDetailResult = await response.json();
      setAwardDetail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAwardLoading(false);
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
    loadExplorer(result.suggested_view as View, result.parent_type, result.parent_key, result.title);
  }

  function downloadReceipt() {
    if (!receiptV2 || !receipt) return;
    const blob = new Blob([JSON.stringify(receiptV2, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `taxtrace-federal-receipt-v2-2026-fy${receipt.spending_fiscal_year}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const displayedNodes: Array<ExplorerNode | ReceiptNode> = explorer
    ? explorer.nodes
    : receipt?.purpose || [];
  const warehouseAccount = receiptV2?.accounts.find(
    (account) => account.account_code === selectedWarehouseAccount
  );
  const awardAccount = awardProjection?.accounts.find(
    (account) => account.account_code === selectedAwardAccount
  );

  return (
    <main>
      <section className="hero">
        <p className="eyebrow">TaxTrace · Federal Product V2</p>
        <h1>See the public-finance path behind your federal taxes.</h1>
        <p>
          TaxTrace calculates supported federal tax liability, routes each tax through its financing
          pool, and attributes it to actual federal outlays. OMB controls the additive account receipt;
          USAspending adds program, object, award, recipient, and subaward detail without double counting.
        </p>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">Step 1</p>
            <h2>Calculate the receipt</h2>
          </div>
          {receiptV2 && <span className="status good">Conservation Δ {money(receiptV2.conservation_difference)}</span>}
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
            <button className="secondary" type="button" onClick={downloadReceipt}>Download auditable V2 receipt JSON</button>
          </>
        )}
      </section>

      {receipt && (
        <section className="panel">
          <div className="section-head">
            <div>
              <p className="eyebrow">Core classifications</p>
              <h2>Explore the conserved receipt</h2>
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

      {receiptV2 && (
        <section className="panel">
          <div className="section-head">
            <div>
              <p className="eyebrow">Warehouse V2 · File B</p>
              <h2>Federal accounts → program activity × object class</h2>
            </div>
            <span className={receiptV2.warehouse.status === "READY" ? "status good" : "status"}>
              {receiptV2.warehouse.status}
            </span>
          </div>
          <p className="notice">
            OMB controls each account&apos;s personalized amount. File B only partitions that existing
            amount into program/activity/object-class detail, so the OMB and USAspending government
            totals shown here must not be added together.
          </p>
          {receiptV2.warnings.map((warning) => <p className="notice" key={warning}>{warning}</p>)}
          <div className="explorer-list">
            {receiptV2.accounts.map((account) => (
              <div className="explorer-row" key={account.key}>
                <button
                  className="row-main"
                  type="button"
                  onClick={() => setSelectedWarehouseAccount(
                    selectedWarehouseAccount === account.account_code ? null : account.account_code
                  )}
                >
                  <span className="row-title">{account.account_name}</span>
                  <span className="meta">
                    {account.account_code} · OMB actual {money(account.omb_government_outlay)} · File B {money(account.file_b_government_outlay)}
                  </span>
                </button>
                <div className="row-amount">
                  <strong>{money(account.allocated_amount)}</strong>
                  <small>{account.warehouse_matched ? "open →" : "detail unavailable"}</small>
                </div>
              </div>
            ))}
          </div>

          {warehouseAccount && (
            <div className="calc-block">
              <h3>{warehouseAccount.account_name}</h3>
              <p className="notice">Account conservation Δ {money(warehouseAccount.conservation_difference)}</p>
              <div className="explorer-list">
                {warehouseAccount.children.map((child) => (
                  <div className="explorer-row" key={child.key}>
                    <div className="row-main">
                      <span className="row-title">{child.label}</span>
                      <span className="meta">
                        {child.residual ? "explicit residual" : "File B additive child"}
                        {child.government_outlay !== null && child.government_outlay !== undefined ? ` · government outlay ${money(child.government_outlay)}` : ""}
                      </span>
                    </div>
                    <div className="row-amount"><strong>{money(child.allocated_amount)}</strong></div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {receiptV2 && (
        <section className="panel">
          <div className="section-head">
            <div>
              <p className="eyebrow">Warehouse V2 · Files C / D1 / D2 / F</p>
              <h2>Award, recipient, and subaward drilldown</h2>
            </div>
            {awardProjection && (
              <span className={awardProjection.file_c.status === "READY" ? "status good" : "status"}>
                File C {awardProjection.file_c.status}
              </span>
            )}
          </div>
          <p className="notice">
            File C can receive personalized award attribution only after reconciliation against the
            full-year File B account denominator. D1/D2 and File F are descriptive relationship grains,
            not extra spending.
          </p>
          {!awardProjection && (
            <button type="button" onClick={loadAwards} disabled={awardLoading}>
              {awardLoading ? "Loading award view…" : "Load conserved award view"}
            </button>
          )}
          {awardProjection && (
            <>
              {awardProjection.warnings.map((warning) => <p className="notice" key={warning}>{warning}</p>)}
              <div className="explorer-list">
                {awardProjection.accounts.map((account) => (
                  <div className="explorer-row" key={account.key}>
                    <button
                      className="row-main"
                      type="button"
                      onClick={() => {
                        setSelectedAwardAccount(
                          selectedAwardAccount === account.account_code ? null : account.account_code
                        );
                        setAwardDetail(null);
                      }}
                    >
                      <span className="row-title">{account.account_name}</span>
                      <span className="meta">
                        {account.account_code} · File C / File B {percentage(account.file_c_share_of_file_b)} · {account.projection_available ? "projected" : "residual only"}
                      </span>
                    </button>
                    <div className="row-amount"><strong>{money(account.allocated_amount)}</strong><small>open →</small></div>
                  </div>
                ))}
              </div>

              {awardAccount && (
                <div className="calc-block">
                  <h3>{awardAccount.account_name}</h3>
                  <p className="notice">Award-view conservation Δ {money(awardAccount.conservation_difference)}</p>
                  <div className="explorer-list">
                    {awardAccount.children.map((child) => (
                      <div className="explorer-row" key={child.key}>
                        <button
                          className="row-main"
                          type="button"
                          disabled={!child.linked || !child.award_identity}
                          onClick={() => child.award_identity && loadAwardDetail(child.award_identity)}
                        >
                          <span className="row-title">{child.label}</span>
                          <span className="meta">
                            {child.residual ? "explicit residual" : child.linked ? `${child.award_family || "award"} · collapsed identity` : "unlinked File C activity"}
                            {child.file_c_government_outlay !== null && child.file_c_government_outlay !== undefined ? ` · File C outlay ${money(child.file_c_government_outlay)}` : ""}
                          </span>
                        </button>
                        <div className="row-amount">
                          <strong>{money(child.allocated_amount)}</strong>
                          {child.linked && <small>award detail →</small>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {awardDetail && (
                <div className="calc-block">
                  <h3>Prime award identity: {awardDetail.award_identity}</h3>
                  <p className="notice">
                    D1/D2: {awardDetail.prime_coverage.status} · File F: {awardDetail.subaward_coverage.status}. These rows are non-additive and have no personalized amount.
                  </p>
                  {awardDetail.prime && (
                    <div className="results compact">
                      <div><span>Recipient</span><strong>{awardDetail.prime.recipient_name || "Unknown"}</strong></div>
                      <div><span>Prime transactions</span><strong>{awardDetail.prime.transaction_count}</strong></div>
                      <div><span>Award family</span><strong>{awardDetail.prime.award_family}</strong></div>
                    </div>
                  )}
                  {awardDetail.prime?.description && <p>{awardDetail.prime.description}</p>}
                  {awardDetail.subawards.length > 0 && (
                    <>
                      <h3>Subawards</h3>
                      <div className="explorer-list">
                        {awardDetail.subawards.map((subaward) => (
                          <div className="explorer-row" key={subaward.key}>
                            <div className="row-main">
                              <span className="row-title">{subaward.subawardee_name || subaward.subaward_number || "Unnamed subaward"}</span>
                              <span className="meta">
                                {subaward.subaward_number || "no subaward number"} · non-additive downstream detail
                              </span>
                            </div>
                            <div className="row-amount">
                              <strong>{money(subaward.subaward_amount)}</strong>
                              <small>government-reported subaward amount</small>
                            </div>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                  {awardDetail.warnings.map((warning) => <p className="notice" key={warning}>{warning}</p>)}
                </div>
              )}
            </>
          )}
        </section>
      )}

      <section className="panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">Federal search · V1 index pending 0.6.5 migration</p>
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
                    {receipt && result.suggested_view && result.parent_type && result.parent_key && VIEWS.includes(result.suggested_view as View) && (
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
          File B and File C are alternate detail views of the same parent account attribution. D1/D2 and File F describe award relationships and are not additional personalized spending.
        </p>
        <p><a href="/florida">Open the Florida + Alachua + Gainesville receipt →</a></p>
        <p>Methodology and machine-readable API documentation: <a href={`${API}/docs`}>{API}/docs</a>.</p>
      </section>
    </main>
  );
}
