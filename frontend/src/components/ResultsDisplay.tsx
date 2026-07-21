"use client";

import { useState, useEffect } from "react";
import type { AnalyzeResponse, StreamEvent } from "@/lib/api";
import { analyzeStream } from "@/lib/api";
import Icon from "@/components/Icon";

// ── Streaming progress + results orchestrator ─────────────────────

interface StreamingResultsProps {
  documentText: string;
  onReset: () => void;
}

export function StreamingResults({ documentText, onReset }: StreamingResultsProps) {
  const [stage, setStage] = useState<string>("connecting");
  const [finalData, setFinalData] = useState<AnalyzeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function runStream() {
      try {
        setStage("connecting");
        for await (const event of analyzeStream(documentText)) {
          if (cancelled) break;
          setStage(event.stage);

          if (event.stage === "complete") {
            setFinalData({
              status: "success",
              extraction: event.extraction,
              explanations: event.explanations || [],
              clinical_summary: event.clinical_summary || event.summary || "",
              therapies: event.therapies || [],
              trials: event.trials || [],
              guardrails: event.guardrails,
              meta: event.meta,
            });
          }
          if (event.stage === "error") {
            setError(event.message || "Analysis failed");
          }
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Stream failed");
        }
      }
    }

    runStream();
    return () => {
      cancelled = true;
    };
  }, [documentText]);

  if (error) {
    return (
      <div className="text-center max-w-md mx-auto">
        <div className="inline-flex items-start gap-3 bg-rose-50 border border-rose-200 rounded-xl px-5 py-4 text-rose-700 text-left">
          <Icon name="alert" size={22} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
        <button
          onClick={onReset}
          className="block mx-auto mt-4 text-sm font-medium text-teal-600 hover:text-teal-700"
        >
          Try again
        </button>
      </div>
    );
  }

  if (finalData) {
    return <ResultsDisplay data={finalData} onReset={onReset} />;
  }

  return (
    <div className="w-full max-w-lg mx-auto">
      <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-11 h-11 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
          <div>
            <h2 className="text-lg font-semibold text-slate-800">
              Analyzing your report…
            </h2>
            <p className="text-teal-700 text-sm mt-0.5">
              {stageMessages[stage] || stage}
            </p>
          </div>
        </div>
        <ol className="space-y-3">
          {progressSteps.map((step, i) => {
            const done = stageOrder[stage] > stageOrder[step.id];
            const active = stageOrder[stage] === stageOrder[step.id];
            return (
              <li
                key={step.id}
                className={`flex items-center gap-3 ${
                  done || active ? "text-slate-700" : "text-slate-400"
                }`}
              >
                <span
                  className={`grid place-items-center w-6 h-6 rounded-full border text-xs font-semibold ${
                    done
                      ? "bg-teal-600 border-teal-600 text-white"
                      : active
                      ? "bg-teal-600 border-teal-600 text-white animate-pulse"
                      : "border-slate-300 text-slate-400"
                  }`}
                >
                  {done ? <Icon name="check" size={14} /> : i + 1}
                </span>
                <span className="text-sm font-medium">{step.label}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

const stageMessages: Record<string, string> = {
  connecting: "Establishing connection…",
  extract: "Extracting biomarkers from your report…",
  explain: "Generating plain-language explanations…",
  therapy: "Matching FDA-approved therapies…",
  trial: "Searching clinical trials…",
  guardrails: "Running quality checks…",
  complete: "Analysis complete!",
  error: "Analysis failed",
};

const progressSteps = [
  { id: "extract", label: "Extract biomarkers" },
  { id: "explain", label: "Generate explanations" },
  { id: "therapy", label: "Match therapies" },
  { id: "trial", label: "Search clinical trials" },
  { id: "guardrails", label: "Run quality checks" },
];

const stageOrder: Record<string, number> = {
  connecting: 0,
  extract: 1,
  explain: 2,
  therapy: 3,
  trial: 4,
  guardrails: 5,
  complete: 6,
  error: -1,
};

// ── Results ───────────────────────────────────────────────────────

interface ResultsDisplayProps {
  data: AnalyzeResponse;
  onReset: () => void;
}

export function ResultsDisplay({ data, onReset }: ResultsDisplayProps) {
  const { extraction, explanations, clinical_summary, therapies, trials, guardrails, meta } = data;
  const biomarkers = extraction.biomarkers.biomarkers;
  const [showAllTrials, setShowAllTrials] = useState(false);

  const handleDownload = () => {
    const lines: string[] = [];
    const rule = (c: string, n = 60) => c.repeat(n);
    lines.push(rule("="), "MatchMyCancer.ai — Oncology Report Analysis", rule("="), "");
    lines.push(clinical_summary, "");

    if (biomarkers.length > 0) {
      lines.push(rule("-", 40), "BIOMARKERS FOUND", rule("-", 40));
      biomarkers.forEach((bm) => {
        lines.push(`  ${bm.gene}: ${bm.alteration || "detected"} (${bm.alteration_type || "unknown type"})`);
        const exp = explanations.find((e) => e.gene === bm.gene);
        if (exp) lines.push(`  Explanation: ${exp.explanation}`);
        lines.push("");
      });
    }

    if (extraction.diagnosis) {
      const d = extraction.diagnosis;
      lines.push(rule("-", 40), "DIAGNOSIS", rule("-", 40));
      if (d.primary_site) lines.push(`  Site: ${d.primary_site}`);
      if (d.histology) lines.push(`  Histology: ${d.histology}`);
      if (d.stage) lines.push(`  Stage: ${d.stage}`);
      if (d.grade) lines.push(`  Grade: ${d.grade}`);
      lines.push("");
    }

    if (therapies.length > 0) {
      lines.push(rule("-", 40), "FDA-APPROVED THERAPIES", rule("-", 40));
      therapies.forEach((t) => {
        lines.push(`  ${t.drug} (${t.brand})`);
        lines.push(`  Targets: ${t.biomarker} — ${t.alteration}`);
        lines.push(`  Cancer type: ${t.cancer_type} | FDA approval: ${t.fda_approval_year} | Match: ${t.match_quality}`);
        lines.push("");
      });
    }

    if (trials.length > 0) {
      lines.push(rule("-", 40), "CLINICAL TRIALS", rule("-", 40));
      trials.forEach((trial) => {
        lines.push(`  ${trial.title}`);
        lines.push(`  NCT: ${trial.nct_id} | Status: ${trial.status}`);
        if (trial.eligibility_assessment) lines.push(`  Eligibility: ${trial.eligibility_assessment}`);
        (trial.eligibility_summary || []).forEach((b) => lines.push(`    - ${b}`));
        lines.push(`  More info: https://clinicaltrials.gov/study/${trial.nct_id}`, "");
      });
    }

    lines.push(rule("-", 40));
    lines.push(`ANALYSIS CONFIDENCE: ${Math.round(guardrails.confidence_score * 100)}%`);
    lines.push(`Biomarkers verified: ${guardrails.source_verification.verified}/${guardrails.source_verification.total}`, "");
    lines.push(rule("="), "DISCLAIMER: AI-generated analysis for educational purposes only.", "Discuss all findings with your oncology team.", rule("="));

    // Open a print-friendly page and let the browser save it as PDF —
    // native, no PDF dependency. Reuses the same report text as before.
    const esc = (s: string) =>
      s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const w = window.open("", "_blank", "width=820,height=640");
    if (!w) {
      alert("Please allow pop-ups to download the report.");
      return;
    }
    w.document.write(
      `<!doctype html><html><head><title>MatchMyCancer Report ${new Date()
        .toISOString()
        .slice(0, 10)}</title></head>` +
        `<body style="margin:0"><pre style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;` +
        `font-size:12px;line-height:1.5;white-space:pre-wrap;padding:32px;color:#1e293b">` +
        esc(lines.join("\n")) +
        `</pre></body></html>`
    );
    w.document.close();
    w.focus();
    w.print();
  };

  return (
    <div className="w-full">
      {/* ── Top bar ────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-800">
            Analysis complete
          </h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {meta.biomarkers_found} biomarkers · {meta.therapies_matched} therapies · {meta.trials_found} trials
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleDownload}
            className="inline-flex items-center gap-2 px-3.5 py-2 bg-white border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-50 text-sm font-medium transition-colors"
          >
            <Icon name="download" size={16} /> Save PDF
          </button>
          <button
            onClick={onReset}
            className="inline-flex items-center gap-2 px-3.5 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 text-sm font-medium transition-colors"
          >
            <Icon name="refresh" size={16} /> New analysis
          </button>
        </div>
      </div>

      {/* ── Two-column: main + sticky rail ─────────────────────── */}
      <div className="grid lg:grid-cols-[1fr_320px] gap-6 items-start">
        <div className="space-y-6 min-w-0">
          {/* Biomarkers */}
          {biomarkers.length > 0 && (
            <section>
              <SectionTitle icon="dna" title={`Biomarkers found (${biomarkers.length})`} />
              <div className="grid gap-4 sm:grid-cols-2">
                {biomarkers.map((bm, idx) => {
                  const exp = explanations.find((e) => e.gene === bm.gene);
                  return (
                    <div key={idx} className="bg-white rounded-xl p-5 border border-slate-200">
                      <div className="flex items-start justify-between mb-2">
                        <span className="text-xl font-bold text-teal-700">{bm.gene}</span>
                        <span className="text-xs px-2 py-0.5 bg-slate-100 text-slate-600 rounded-full">
                          {bm.alteration_type || "alteration"}
                        </span>
                      </div>
                      <p className="text-slate-600 text-sm mb-2">
                        {bm.alteration || "Alteration detected"}
                        {bm.significance && ` — ${bm.significance}`}
                      </p>
                      {bm.test_method && (
                        <p className="text-xs text-slate-400 mb-2">Method: {bm.test_method}</p>
                      )}
                      {exp && (
                        <details className="text-sm">
                          <summary className="text-teal-600 cursor-pointer">Explanation</summary>
                          <p className="text-slate-600 mt-1.5 leading-relaxed">{exp.explanation}</p>
                        </details>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Diagnosis */}
          {extraction.diagnosis && (
            <section>
              <SectionTitle icon="cross" title="Diagnosis" />
              <div className="bg-white rounded-xl p-5 border border-slate-200 grid gap-3 sm:grid-cols-2">
                {extraction.diagnosis.primary_site && <InfoTile label="Primary site" value={extraction.diagnosis.primary_site} />}
                {extraction.diagnosis.histology && <InfoTile label="Histology" value={extraction.diagnosis.histology} />}
                {extraction.diagnosis.stage && <InfoTile label="Stage" value={extraction.diagnosis.stage} />}
                {extraction.diagnosis.grade && <InfoTile label="Grade" value={extraction.diagnosis.grade} />}
                {extraction.diagnosis.laterality && <InfoTile label="Laterality" value={extraction.diagnosis.laterality} />}
              </div>
            </section>
          )}

          {/* Therapies */}
          {therapies.length > 0 && (
            <section>
              <SectionTitle icon="pill" title={`FDA-approved therapies (${therapies.length})`} />
              <div className="grid gap-4 sm:grid-cols-2">
                {therapies.map((t, idx) => (
                  <div key={idx} className="bg-white rounded-xl p-5 border border-slate-200">
                    <div className="flex items-start justify-between mb-2">
                      <div>
                        <h3 className="font-semibold text-slate-800">{t.drug}</h3>
                        <p className="text-sm text-slate-400">{t.brand}</p>
                      </div>
                      <Badge tone={t.match_quality === "exact" ? "teal" : "amber"}>{t.match_quality}</Badge>
                    </div>
                    <p className="text-sm text-slate-600 mb-1">Targets: <span className="font-medium">{t.biomarker}</span> — {t.alteration}</p>
                    <p className="text-sm text-slate-600 mb-1">Cancer: <span className="font-medium">{t.cancer_type}</span></p>
                    <p className="text-xs text-slate-400">FDA approved {t.fda_approval_year} · {t.source}</p>
                    {t.trace && (
                      <details className="mt-3 text-sm">
                        <summary className="text-teal-600 cursor-pointer">Why this therapy?</summary>
                        <ol className="mt-2 space-y-1 list-decimal list-inside text-slate-600">
                          {t.trace.reasoning_steps.map((s) => (
                            <li key={s.step_number}>{s.description}</li>
                          ))}
                        </ol>
                        {t.trace.sources.length > 0 && (
                          <p className="mt-2 text-xs text-slate-400">
                            Source: {t.trace.sources.map((s) => `${s.source_name} — ${s.relevance}`).join("; ")}
                          </p>
                        )}
                      </details>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Trials */}
          {trials.length > 0 && (
            <section>
              <SectionTitle icon="flask" title={`Clinical trials (${trials.length})`} />
              <div className="space-y-3">
                {(showAllTrials ? trials : trials.slice(0, 5)).map((trial, idx) => (
                  <div key={idx} className="bg-white rounded-xl p-5 border border-slate-200">
                    <div className="flex items-start justify-between gap-3 mb-1">
                      <h3 className="font-semibold text-slate-800">{trial.title}</h3>
                      {trial.eligibility_assessment && (
                        <Badge
                          tone={
                            trial.eligibility_assessment.startsWith("LIKELY") ? "emerald" :
                            trial.eligibility_assessment.startsWith("UNLIKELY") ? "rose" : "amber"
                          }
                        >
                          {trial.eligibility_assessment.replace(" ELIGIBLE", "")}
                        </Badge>
                      )}
                    </div>
                    <p className="text-sm text-slate-500 mb-2">
                      NCT:{" "}
                      <a href={`https://clinicaltrials.gov/study/${trial.nct_id}`} target="_blank" rel="noopener noreferrer" className="text-teal-600 hover:underline">
                        {trial.nct_id}
                      </a>{" "}
                      · Status: <span className="font-medium text-slate-600">{trial.status}</span>
                    </p>
                    {trial.eligibility_summary && trial.eligibility_summary.length > 0 ? (
                      <div className="text-sm text-slate-600">
                        <p className="font-medium text-slate-700 mb-1">Who qualifies:</p>
                        <ul className="space-y-0.5">
                          {trial.eligibility_summary.map((b, i) => <li key={i}>• {b}</li>)}
                        </ul>
                        {trial.eligibility_reasoning && (
                          <p className="mt-1.5 text-xs text-slate-400 italic">{trial.eligibility_reasoning}</p>
                        )}
                      </div>
                    ) : (
                      trial.eligibility && <p className="text-sm text-slate-400 line-clamp-2">{trial.eligibility}</p>
                    )}
                    {trial.conditions.length > 0 && (
                      <div className="flex flex-wrap gap-2 mt-2">
                        {trial.conditions.slice(0, 3).map((c, i) => (
                          <span key={i} className="px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded-full">{c}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                {trials.length > 5 && (
                  <div className="text-center">
                    <button
                      onClick={() => setShowAllTrials((v) => !v)}
                      className="text-sm font-medium text-teal-600 hover:text-teal-700"
                    >
                      {showAllTrials ? "Show fewer" : `View all ${trials.length} trials`}
                    </button>
                  </div>
                )}
              </div>
            </section>
          )}
        </div>

        {/* ── Sticky rail ──────────────────────────────────────── */}
        <aside className="space-y-4 lg:sticky lg:top-24 h-fit">
          <section className="bg-white rounded-xl p-5 border border-slate-200">
            <SectionTitle icon="file" title="Clinical summary" small />
            <p className="text-sm text-slate-600 leading-relaxed whitespace-pre-line">{clinical_summary}</p>
          </section>

          <section className="bg-white rounded-xl p-5 border border-slate-200">
            <SectionTitle icon="shield" title="Confidence" small />
            <ConfidenceMeter score={guardrails.confidence_score} />
            <div className="mt-3 text-sm text-slate-600">
              <div className="flex justify-between py-1 border-t border-slate-100">
                <span>Biomarkers verified</span>
                <span className="font-medium">{guardrails.source_verification.verified}/{guardrails.source_verification.total}</span>
              </div>
              <div className="flex justify-between py-1 border-t border-slate-100">
                <span>Verification rate</span>
                <span className="font-medium">{(guardrails.source_verification.rate * 100).toFixed(0)}%</span>
              </div>
            </div>
            {guardrails.warnings.length > 0 && (
              <div className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <p className="flex items-center gap-1.5 font-medium text-amber-800 text-sm mb-1">
                  <Icon name="alert" size={15} /> Warnings
                </p>
                <ul className="text-xs text-amber-700 space-y-1">
                  {guardrails.warnings.map((w, i) => <li key={i}>• {w}</li>)}
                </ul>
              </div>
            )}
          </section>
        </aside>
      </div>

      <footer className="border-t border-slate-200 mt-8 pt-5 text-center">
        <p className="text-xs text-slate-400">
          For educational purposes only. Always discuss findings with your oncologist.
        </p>
      </footer>
    </div>
  );
}

// ── Small presentational helpers ──────────────────────────────────

function SectionTitle({ icon, title, small }: { icon: Parameters<typeof Icon>[0]["name"]; title: string; small?: boolean }) {
  return (
    <h2 className={`flex items-center gap-2 font-semibold text-slate-800 ${small ? "text-sm mb-3" : "text-lg mb-4"}`}>
      <span className="text-teal-600"><Icon name={icon} size={small ? 16 : 20} /></span>
      {title}
    </h2>
  );
}

function InfoTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-50 rounded-lg p-3">
      <div className="text-xs text-slate-400 uppercase tracking-wide">{label}</div>
      <div className="font-medium text-slate-800 capitalize">{value}</div>
    </div>
  );
}

const TONES: Record<string, string> = {
  teal: "bg-teal-50 text-teal-700",
  amber: "bg-amber-50 text-amber-700",
  emerald: "bg-emerald-50 text-emerald-700",
  rose: "bg-rose-50 text-rose-700",
};

function Badge({ tone, children }: { tone: keyof typeof TONES; children: React.ReactNode }) {
  return <span className={`shrink-0 px-2 py-0.5 text-xs rounded-full ${TONES[tone]}`}>{children}</span>;
}

function ConfidenceMeter({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const tone = score >= 0.8 ? "text-teal-700" : score >= 0.5 ? "text-amber-700" : "text-rose-700";
  const bar = score >= 0.8 ? "bg-teal-500" : score >= 0.5 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className={`text-3xl font-bold ${tone}`}>{pct}%</span>
        <span className="text-sm text-slate-400">overall</span>
      </div>
      <div className="mt-2 h-2 rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full ${bar} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
