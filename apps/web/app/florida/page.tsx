"use client";

import { FormEvent, useState } from "react";

type Node = {
  key: string;
  label: string;
  allocated_amount: string;
  government_spending_amount?: string | null;
  relation: string;
  confidence: string;
  notes: string[];
  children: Node[];
};

type Result = {
  methodology_version: string;
  state_individual_income_tax: string;
  total_supported_calculated_and_modeled_tax: string;
  federal: { total_allocable_taxes: string };
  sales_tax_model: {
    model_version: string;
    calculation_basis: string;
    confidence: string;
    cex_quintile: string;
    income_proxy: string;
    annual_expenditure_estimate: string;
    state_taxable_base: string;
    county_taxable_base: string;
    florida_state_sales_tax: string;
    alachua_county_surtax: string;
    combined_sales_tax: string;
    assumptions: string[];
    sources: Array<{ name: string; url: string }>;
  };
  florida_state: {
    tax_amount: string;
    conservation_difference: string;
    nodes: Node[];
    warnings: string[];
    sources: Array<{ name: string; url: string }>;
  };
  alachua_local: {
    tax_amount: string;
    conservation_difference: string;
    nodes: Node[];
    warnings: string[];
    sources: Array<{ name: string; url: string }>;
  };
  gainesville_spending_reference: {
    total_actual_expenditure: string;
    explanation: string;
    nodes: Array<{ key: string; label: string; actual_expenditure: string }>;
    sources: Array<{ name: string; url: string }>;
  };
  warnings: string[];
};

function money(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(parsed);
}

function ReceiptNodes({ nodes }: { nodes: Node[] }) {
  return (
    <div className="explorer-list">
      {nodes.map((node) => (
        <div className="explorer-row" key={node.key}>
          <div className="row-main">
            <span className="row-title">{node.label}</span>
            <span className="meta">{node.relation} · confidence {node.confidence}</span>
          </div>
          <div className="row-amount"><strong>{money(node.allocated_amount)}</strong></div>
          {node.notes.length > 0 && (
            <details className="calc-details">
              <summary>Method and limits</summary>
              {node.notes.map((note) => <p key={note}>{note}</p>)}
            </details>
          )}
          {node.children.length > 0 && (
            <div style={{ gridColumn: "1 / -1", paddingLeft: "1rem" }}>
              {node.children.map((child) => (
                <div className="pool-row" key={child.key}>
                  <div><strong>{child.label}</strong><small>{child.relation} · confidence {child.confidence}</small></div>
                  <strong>{money(child.allocated_amount)}</strong>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function FloridaPage() {
  const [income, setIncome] = useState("50000");
  const [filingStatus, setFilingStatus] = useState("single");
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function calculate(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/v1/receipt/florida-gainesville", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          tax_year: 2026,
          spending_fiscal_year: 2025,
          filing_status: filingStatus,
          wage_income: income,
          spouse_wage_income: "0",
          qualifying_children_under_17: 0,
          other_dependents: 0,
          household_size: 1
        })
      });
      if (!response.ok) throw new Error(await response.text());
      setResult(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <section className="hero">
        <p className="eyebrow">TaxTrace · Phases 7, 8 & 9A</p>
        <h1>Florida and Gainesville, without pretending modeled taxes are exact.</h1>
        <p>
          This view keeps the federal receipt, adds a BLS-based estimate of Florida and Alachua sales taxes,
          allocates the state share across audited Florida spending, follows dedicated Alachua surtax pools,
          and shows Gainesville&apos;s audited spending separately where quick mode cannot defend a personal attribution.
        </p>
      </section>

      <section className="panel">
        <div className="section-head"><div><p className="eyebrow">Quick mode</p><h2>Build Florida + Gainesville receipt</h2></div></div>
        <form className="tax-form" onSubmit={calculate}>
          <label>W-2 wages<input value={income} onChange={(e) => setIncome(e.target.value)} inputMode="decimal" /></label>
          <label>Filing status
            <select value={filingStatus} onChange={(e) => setFilingStatus(e.target.value)}>
              <option value="single">Single</option>
              <option value="married_filing_jointly">Married filing jointly</option>
              <option value="married_filing_separately">Married filing separately</option>
              <option value="head_of_household">Head of household</option>
            </select>
          </label>
          <button disabled={loading} type="submit">{loading ? "Working…" : "Build Florida receipt"}</button>
        </form>
        {error && <pre className="error">{error}</pre>}
      </section>

      {result && (
        <>
          <section className="panel">
            <div className="section-head"><div><p className="eyebrow">Tax layers</p><h2>Calculated + modeled liability</h2></div><span className="status good">methodology {result.methodology_version}</span></div>
            <div className="headline-number"><span>Supported federal + modeled sales taxes</span><strong>{money(result.total_supported_calculated_and_modeled_tax)}</strong></div>
            <div className="results compact">
              <div><span>Federal · CALCULATED</span><strong>{money(result.federal.total_allocable_taxes)}</strong></div>
              <div><span>Florida individual income tax</span><strong>{money(result.state_individual_income_tax)}</strong></div>
              <div><span>Florida sales tax · MODELED</span><strong>{money(result.sales_tax_model.florida_state_sales_tax)}</strong></div>
              <div><span>Alachua surtax · MODELED</span><strong>{money(result.sales_tax_model.alachua_county_surtax)}</strong></div>
            </div>
            {result.warnings.map((warning) => <p className="notice" key={warning}>{warning}</p>)}
          </section>

          <section className="panel">
            <div className="section-head"><div><p className="eyebrow">Phase 9A</p><h2>How the sales-tax estimate works</h2></div><span className="status">{result.sales_tax_model.calculation_basis} · confidence {result.sales_tax_model.confidence}</span></div>
            <p>Income proxy {money(result.sales_tax_model.income_proxy)} maps to the <strong>{result.sales_tax_model.cex_quintile}</strong> BLS 2024 income quintile, with average annual expenditures of {money(result.sales_tax_model.annual_expenditure_estimate)}.</p>
            <div className="results compact">
              <div><span>Modeled Florida-taxable base</span><strong>{money(result.sales_tax_model.state_taxable_base)}</strong></div>
              <div><span>Modeled Alachua-taxable base</span><strong>{money(result.sales_tax_model.county_taxable_base)}</strong></div>
              <div><span>Combined modeled sales tax</span><strong>{money(result.sales_tax_model.combined_sales_tax)}</strong></div>
            </div>
            <details className="calc-details"><summary>Assumptions and uncertainty</summary>{result.sales_tax_model.assumptions.map((x) => <p key={x}>{x}</p>)}</details>
            {result.sales_tax_model.sources.map((source) => <p key={source.url}>Source: <a href={source.url} target="_blank" rel="noreferrer">{source.name}</a></p>)}
          </section>

          <section className="panel">
            <div className="section-head"><div><p className="eyebrow">Phase 7</p><h2>Your modeled Florida sales tax → actual state spending</h2></div><span className="status good">Conservation Δ {money(result.florida_state.conservation_difference)}</span></div>
            {result.florida_state.warnings.map((x) => <p className="notice" key={x}>{x}</p>)}
            <ReceiptNodes nodes={result.florida_state.nodes} />
            {result.florida_state.sources.map((source) => <p key={source.url}>Source: <a href={source.url} target="_blank" rel="noreferrer">{source.name}</a></p>)}
          </section>

          <section className="panel">
            <div className="section-head"><div><p className="eyebrow">Phase 8</p><h2>Your modeled Alachua surtax → dedicated purposes</h2></div><span className="status good">Conservation Δ {money(result.alachua_local.conservation_difference)}</span></div>
            {result.alachua_local.warnings.map((x) => <p className="notice" key={x}>{x}</p>)}
            <ReceiptNodes nodes={result.alachua_local.nodes} />
            {result.alachua_local.sources.map((source) => <p key={source.url}>Source: <a href={source.url} target="_blank" rel="noreferrer">{source.name}</a></p>)}
          </section>

          <section className="panel">
            <div className="section-head"><div><p className="eyebrow">Gainesville FY2025</p><h2>Actual city spending reference</h2></div><span className="status">ACTUAL · not additive to your quick receipt</span></div>
            <p className="notice">{result.gainesville_spending_reference.explanation}</p>
            <div className="headline-number"><span>Audited governmental-activity expenses</span><strong>{money(result.gainesville_spending_reference.total_actual_expenditure)}</strong></div>
            <div className="explorer-list">
              {result.gainesville_spending_reference.nodes.map((node) => (
                <div className="pool-row" key={node.key}><strong>{node.label}</strong><strong>{money(node.actual_expenditure)}</strong></div>
              ))}
            </div>
            {result.gainesville_spending_reference.sources.map((source) => <p key={source.url}>Source: <a href={source.url} target="_blank" rel="noreferrer">{source.name}</a></p>)}
          </section>
        </>
      )}
    </main>
  );
}
