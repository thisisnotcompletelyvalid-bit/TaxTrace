"use client";

import { FormEvent, useState } from "react";

type TaxResult = {
  gross_wages: string;
  taxable_income: string;
  federal_income_tax_liability: string;
  social_security_tax: string;
  medicare_tax: string;
  additional_medicare_tax: string;
  total_personal_tax_liability: string;
  refundable_credits_separately: string;
  assumptions: string[];
  limitations: string[];
};

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function money(value: string | undefined) {
  if (!value) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value));
}

export default function Home() {
  const [income, setIncome] = useState("50000");
  const [filingStatus, setFilingStatus] = useState("single");
  const [result, setResult] = useState<TaxResult | null>(null);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    const response = await fetch(`${API}/v1/tax/federal`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        tax_year: 2026,
        filing_status: filingStatus,
        wage_income: income,
        spouse_wage_income: "0",
        qualifying_children_under_17: 0,
        other_dependents: 0
      })
    });
    if (!response.ok) {
      setError(await response.text());
      return;
    }
    setResult(await response.json());
  }

  return (
    <main>
      <section className="hero">
        <p className="eyebrow">TaxTrace · Phases 0–3</p>
        <h1>Auditable federal tax and finance foundation</h1>
        <p>
          This shell demonstrates the versioned 2026 federal W-2 tax engine. The warehouse,
          source snapshots, methodology invariants, OMB/Treasury/USAspending ingestion and
          reconciliation live behind the API and CLI.
        </p>
      </section>

      <section className="panel">
        <h2>Federal tax-engine check</h2>
        <form onSubmit={submit}>
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
          <button type="submit">Calculate 2026 federal taxes</button>
        </form>
        {error && <pre className="error">{error}</pre>}
        {result && (
          <div className="results">
            <div><span>Taxable income</span><strong>{money(result.taxable_income)}</strong></div>
            <div><span>Federal income tax</span><strong>{money(result.federal_income_tax_liability)}</strong></div>
            <div><span>Social Security</span><strong>{money(result.social_security_tax)}</strong></div>
            <div><span>Medicare</span><strong>{money(result.medicare_tax)}</strong></div>
            <div><span>Additional Medicare</span><strong>{money(result.additional_medicare_tax)}</strong></div>
            <div className="total"><span>Total personal tax liability in supported scope</span><strong>{money(result.total_personal_tax_liability)}</strong></div>
          </div>
        )}
      </section>

      <section className="panel quiet">
        <h2>What this repository intentionally stops before</h2>
        <p>
          Phase 4, the actual user-specific spending receipt/allocation UI, is not implemented here.
          Phases 0–3 make that next step possible without inventing finance relationships.
        </p>
        <p>API documentation is available at <code>http://localhost:8000/docs</code>.</p>
      </section>
    </main>
  );
}
