"use client";

import { FormEvent, useState } from "react";

type Coverage = {
  dataset_key: string;
  release_key?: string | null;
  fiscal_year: number;
  status: string;
  full_fiscal_year: boolean;
  row_count?: number | null;
  object_count: number;
  notes: string[];
};

type SearchResult = {
  entity_type: string;
  key: string;
  title: string;
  subtitle?: string | null;
  score: string;
  award_identity?: string | null;
  award_family?: string | null;
  recipient_name?: string | null;
  recipient_uei?: string | null;
  description?: string | null;
  personalized_amount?: string | null;
  prime_personalized_amount?: string | null;
  additive: boolean;
  target_award_identity?: string | null;
  metadata: Record<string, unknown>;
  warning: string;
};

type SearchResponse = {
  query: string;
  normalized_query: string;
  fiscal_year: number;
  results: SearchResult[];
  prime_coverage: Coverage;
  subaward_coverage: Coverage;
  receipt_context: boolean;
  personalization_status: string;
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
};

type Subaward = {
  key: string;
  prime_award_identity: string;
  award_family: string;
  subaward_number?: string | null;
  subawardee_name?: string | null;
  subawardee_uei?: string | null;
  subaward_amount?: string | null;
  description?: string | null;
  action_date?: string | null;
};

type AwardDetail = {
  award_identity: string;
  fiscal_year: number;
  prime_coverage: Coverage;
  subaward_coverage: Coverage;
  prime?: PrimeAwardSummary | null;
  subawards: Subaward[];
  warnings: string[];
};

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function money(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(parsed);
}

function entityLabel(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function FederalSearchPage() {
  const [query, setQuery] = useState("");
  const [fiscalYear, setFiscalYear] = useState("2025");
  const [receiptContext, setReceiptContext] = useState(false);
  const [income, setIncome] = useState("50000");
  const [filingStatus, setFilingStatus] = useState("single");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [detail, setDetail] = useState<AwardDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    setDetail(null);
    try {
      const result = receiptContext
        ? await fetch(`${API}/v2/search/federal`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
              tax_year: 2026,
              spending_fiscal_year: Number(fiscalYear),
              filing_status: filingStatus,
              wage_income: income,
              spouse_wage_income: "0",
              qualifying_children_under_17: 0,
              other_dependents: 0,
              q: query,
              limit: 30,
              entity_types: []
            })
          })
        : await fetch(
            `${API}/v2/search/federal?q=${encodeURIComponent(query)}&fiscal_year=${encodeURIComponent(fiscalYear)}&limit=30`
          );
      if (!result.ok) throw new Error(await result.text());
      setResponse(await result.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function openAward(identity: string) {
    setDetailLoading(true);
    setError("");
    try {
      const result = await fetch(`${API}/v2/explorer/federal/award-detail`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ fiscal_year: Number(fiscalYear), award_identity: identity })
      });
      if (!result.ok) throw new Error(await result.text());
      setDetail(await result.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <main>
      <section className="hero">
        <p className="eyebrow">TaxTrace · Federal Search V2</p>
        <h1>Search federal awards, recipients, and subawards.</h1>
        <p>
          Search runs directly over full-year Warehouse V2 D1/D2 prime-transaction and File F
          Parquet data. Repeated prime transactions collapse to canonical award identity before they
          become results. Search results overlap and are never an additive spending partition.
        </p>
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">Search controls</p>
            <h2>Federal award data</h2>
          </div>
          {response && <span className="status">FY{response.fiscal_year}</span>}
        </div>
        <form className="search-form" onSubmit={search}>
          <input
            aria-label="Search federal awards, recipients, or subawards"
            placeholder="Try a recipient, UEI, PIID, FAIN, award description, or subawardee…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button type="submit" disabled={loading}>{loading ? "Searching…" : "Search"}</button>
        </form>
        <div className="tax-form">
          <label>
            Spending fiscal year
            <input value={fiscalYear} onChange={(event) => setFiscalYear(event.target.value)} inputMode="numeric" />
          </label>
          <label>
            Receipt context
            <select
              value={receiptContext ? "yes" : "no"}
              onChange={(event) => setReceiptContext(event.target.value === "yes")}
            >
              <option value="no">Public-data search only</option>
              <option value="yes">Annotate with my receipt</option>
            </select>
          </label>
          {receiptContext && (
            <>
              <label>
                W-2 wages
                <input value={income} onChange={(event) => setIncome(event.target.value)} inputMode="decimal" />
              </label>
              <label>
                Filing status
                <select value={filingStatus} onChange={(event) => setFilingStatus(event.target.value)}>
                  <option value="single">Single</option>
                  <option value="married_filing_jointly">Married filing jointly</option>
                  <option value="married_filing_separately">Married filing separately</option>
                  <option value="head_of_household">Head of household</option>
                </select>
              </label>
            </>
          )}
        </div>
        {error && <pre className="error">{error}</pre>}
      </section>

      {response && (
        <section className="panel">
          <div className="section-head">
            <div>
              <p className="eyebrow">Warehouse coverage</p>
              <h2>{response.results.length} result{response.results.length === 1 ? "" : "s"}</h2>
            </div>
            <span className={response.personalization_status === "READY" ? "status good" : "status"}>
              {response.receipt_context ? `Receipt ${response.personalization_status}` : "Public data"}
            </span>
          </div>
          <div className="results compact">
            <div><span>D1/D2 prime data</span><strong>{response.prime_coverage.status}</strong></div>
            <div><span>File F subawards</span><strong>{response.subaward_coverage.status}</strong></div>
          </div>
          {response.warnings.map((warning) => <p className="notice" key={warning}>{warning}</p>)}

          <div className="search-results">
            {response.results.map((result) => (
              <div className="search-row" key={result.key}>
                <div>
                  <strong>{result.title}</strong>
                  <small>
                    {entityLabel(result.entity_type)}
                    {result.subtitle ? ` · ${result.subtitle}` : ""}
                    {result.award_family ? ` · ${result.award_family}` : ""}
                  </small>
                  {result.description && <small>{result.description}</small>}
                  {result.personalized_amount !== null && result.personalized_amount !== undefined && (
                    <small>Current receipt attribution: <strong>{money(result.personalized_amount)}</strong></small>
                  )}
                  {result.prime_personalized_amount !== null && result.prime_personalized_amount !== undefined && (
                    <small>
                      Prime-award receipt context: <strong>{money(result.prime_personalized_amount)}</strong> · not allocated to this subaward
                    </small>
                  )}
                  <small>{result.warning}</small>
                </div>
                <div className="search-actions">
                  <span className="score">{Number(result.score).toFixed(0)}</span>
                  {result.target_award_identity && (
                    <button
                      type="button"
                      className="mini"
                      onClick={() => openAward(result.target_award_identity as string)}
                      disabled={detailLoading}
                    >
                      {result.entity_type === "recipient" ? "Open sample award →" : "Open award →"}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {detail && (
        <section className="panel">
          <div className="section-head">
            <div>
              <p className="eyebrow">Canonical award identity</p>
              <h2>{detail.award_identity}</h2>
            </div>
            <span className="status">D1/D2 {detail.prime_coverage.status} · File F {detail.subaward_coverage.status}</span>
          </div>
          {detail.prime && (
            <>
              <div className="results compact">
                <div><span>Recipient</span><strong>{detail.prime.recipient_name || "Unknown"}</strong></div>
                <div><span>Prime transactions</span><strong>{detail.prime.transaction_count}</strong></div>
                <div><span>Award family</span><strong>{detail.prime.award_family}</strong></div>
              </div>
              {detail.prime.description && <p>{detail.prime.description}</p>}
            </>
          )}
          {detail.subawards.length > 0 && (
            <div className="explorer-list">
              {detail.subawards.map((subaward) => (
                <div className="explorer-row" key={subaward.key}>
                  <div className="row-main">
                    <span className="row-title">{subaward.subawardee_name || subaward.subaward_number || "Unnamed subaward"}</span>
                    <span className="meta">
                      {subaward.subaward_number || "no subaward number"} · non-additive File F detail
                    </span>
                  </div>
                  <div className="row-amount">
                    <strong>{money(subaward.subaward_amount)}</strong>
                    <small>government-reported subaward amount</small>
                  </div>
                </div>
              ))}
            </div>
          )}
          {detail.warnings.map((warning) => <p className="notice" key={warning}>{warning}</p>)}
        </section>
      )}

      <section className="panel quiet">
        <h2>Search semantics</h2>
        <p>
          D1/D2 rows are transaction records, so TaxTrace collapses them to canonical prime-award
          identity before displaying a prime award. Recipient results group those same identities.
          File F is downstream subaward context. None of these result sets may be added together.
        </p>
        <p><a href="/">Return to the federal receipt →</a></p>
      </section>
    </main>
  );
}
