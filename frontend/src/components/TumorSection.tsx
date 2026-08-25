// Per-tumour rendering for reports describing more than one cancer.
//
// Measured on TCGA-BH-A18H: two breast primaries, Nottingham grade 2 vs 3,
// pT1b pN0 vs pT1c pN1a, 0/1 vs 2/24 nodes. A flat biomarker list showed six
// identical-looking rows with no way to tell which breast each belonged to.
//
// Also home to the shared biomarker card and badge, imported by ResultsDisplay.

import type { Biomarker, Explanation, TumorInstance } from "@/lib/api";
import Icon from "@/components/Icon";

// ── Shared presentational primitives ──────────────────────────────

export const TONES: Record<string, string> = {
  teal: "bg-teal-50 text-teal-700",
  amber: "bg-amber-50 text-amber-700",
  emerald: "bg-emerald-50 text-emerald-700",
  rose: "bg-rose-50 text-rose-700",
  slate: "bg-slate-100 text-slate-600",
};

export function Badge({
  tone,
  children,
}: {
  tone: keyof typeof TONES;
  children: React.ReactNode;
}) {
  return (
    <span className={`shrink-0 px-2 py-0.5 text-xs rounded-full ${TONES[tone]}`}>
      {children}
    </span>
  );
}

// A negative result rules a therapy OUT — that's a finding, so it gets a
// neutral tone rather than the red used for errors.
const CALL_TONES: Record<Biomarker["result"], keyof typeof TONES> = {
  positive: "teal",
  negative: "slate",
  equivocal: "amber",
  not_tested: "amber", // a gap, not a result — worth the patient noticing
  unknown: "slate",
};

const CALL_LABELS: Record<Biomarker["result"], string> = {
  positive: "positive",
  negative: "negative",
  equivocal: "equivocal",
  not_tested: "not tested",
  unknown: "not stated",
};

/** The extractor puts polarity in `result` and often leaves `alteration` null,
 *  so falling back to "Alteration detected" would label a negative result as a
 *  positive finding. */
function describeBiomarker(bm: Biomarker): string {
  if (bm.alteration) return bm.alteration;
  switch (bm.result) {
    case "positive":
      return "Detected";
    case "negative":
      return "Not detected — this result rules out therapies targeting it";
    case "equivocal":
      return "Equivocal — confirmatory testing needed";
    case "not_tested":
      return "Not assessed in this report — worth asking whether it applies to you";
    default:
      return "Result not stated in this report";
  }
}

export function BiomarkerCard({
  bm,
  explanation,
}: {
  bm: Biomarker;
  explanation?: Explanation;
}) {
  return (
    <div className="bg-white rounded-xl p-5 border border-slate-200">
      <div className="flex items-start justify-between mb-2">
        {/* Negative findings are informative, not alarming — muted, not red. */}
        <span
          className={`text-xl font-bold ${
            bm.result === "positive" ? "text-teal-700" : "text-slate-500"
          }`}
        >
          {bm.gene}
        </span>
        <div className="flex items-center gap-1.5">
          <span className="text-xs px-2 py-0.5 bg-slate-100 text-slate-600 rounded-full">
            {bm.alteration_type || "alteration"}
          </span>
          <Badge tone={CALL_TONES[bm.result] ?? "slate"}>
            {CALL_LABELS[bm.result] ?? bm.result}
          </Badge>
        </div>
      </div>
      <p className="text-slate-600 text-sm mb-2">
        {describeBiomarker(bm)}
        {bm.significance && ` — ${bm.significance}`}
      </p>
      {bm.test_method && (
        <p className="text-xs text-slate-400 mb-2">Method: {bm.test_method}</p>
      )}
      {explanation && (
        <details className="text-sm">
          <summary className="text-teal-600 cursor-pointer">Explanation</summary>
          <p className="text-slate-600 mt-1.5 leading-relaxed">
            {explanation.explanation}
          </p>
        </details>
      )}
    </div>
  );
}

// ── Per-tumour view ───────────────────────────────────────────────

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-50 rounded-lg px-3 py-2">
      <div className="text-[11px] text-slate-400 uppercase tracking-wide">
        {label}
      </div>
      <div className="text-sm font-medium text-slate-800">{value}</div>
    </div>
  );
}

/** Staging facts, omitting anything the report didn't state. */
function tumorFacts(t: TumorInstance): { label: string; value: string }[] {
  const facts: { label: string; value: string }[] = [];
  if (t.histology) facts.push({ label: "Type", value: t.histology });
  if (t.tumor_size) facts.push({ label: "Size", value: t.tumor_size });
  if (t.grade) facts.push({ label: "Grade", value: t.grade });
  if (t.stage) facts.push({ label: "Stage", value: t.stage });
  if (t.tnm) facts.push({ label: "TNM", value: t.tnm });
  if (t.nodes_examined !== null && t.nodes_examined !== undefined) {
    facts.push({
      label: "Lymph nodes",
      value: `${t.nodes_positive ?? "?"} of ${t.nodes_examined} involved`,
    });
  }
  if (t.lymphovascular_invasion !== null) {
    facts.push({
      label: "Vascular invasion",
      value: t.lymphovascular_invasion ? "Present" : "Not seen",
    });
  }
  if (t.margins) facts.push({ label: "Margins", value: t.margins });
  return facts;
}

interface Props {
  tumors: TumorInstance[];
  biomarkers: Biomarker[];
  explanations: Explanation[];
  /** Label of the tumour driving therapy and trial matching. */
  dominantLabel?: string | null;
}

export default function TumorSection({
  tumors,
  biomarkers,
  explanations,
  dominantLabel,
}: Props) {
  // Anything the extractor couldn't attribute is shown separately rather than
  // dropped — a biomarker with no tumour is still a finding.
  const unattributed = biomarkers.filter(
    (b) => !b.tumor_label || !tumors.some((t) => t.label === b.tumor_label)
  );

  return (
    <section>
      <h2 className="flex items-center gap-2 font-semibold text-slate-800 text-lg mb-4">
        <span className="text-teal-600">
          <Icon name="cross" size={20} />
        </span>
        {tumors.length} separate tumours found
      </h2>

      <p className="text-sm text-slate-500 -mt-2 mb-4">
        This report describes more than one tumour. They are shown separately
        because they can differ in grade, stage and treatment implications.
      </p>

      <div className="space-y-5">
        {tumors.map((tumor) => {
          const mine = biomarkers.filter((b) => b.tumor_label === tumor.label);
          const isDominant = dominantLabel === tumor.label;

          return (
            <div
              key={tumor.label}
              className="rounded-xl border border-slate-200 bg-white p-5"
            >
              <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
                <div>
                  <h3 className="font-semibold text-slate-800 capitalize">
                    {tumor.label}
                  </h3>
                  {tumor.primary_site && (
                    <p className="text-sm text-slate-500 capitalize">
                      {tumor.primary_site}
                      {tumor.laterality && ` · ${tumor.laterality}`}
                    </p>
                  )}
                </div>
                {isDominant && tumors.length > 1 && (
                  <Badge tone="teal">used for trial matching</Badge>
                )}
              </div>

              <div className="grid gap-2 sm:grid-cols-3">
                {tumorFacts(tumor).map((f) => (
                  <Fact key={f.label} label={f.label} value={f.value} />
                ))}
              </div>

              {mine.length > 0 && (
                <div className="mt-4 pt-4 border-t border-slate-100">
                  <p className="text-xs uppercase tracking-wide text-slate-400 mb-2">
                    Biomarkers for this tumour
                  </p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {mine.map((bm, i) => (
                      <BiomarkerCard
                        key={`${bm.gene}-${i}`}
                        bm={bm}
                        explanation={explanations.find((e) => e.gene === bm.gene)}
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {unattributed.length > 0 && (
        <div className="mt-5">
          <p className="text-xs uppercase tracking-wide text-slate-400 mb-2">
            Not linked to a specific tumour
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {unattributed.map((bm, i) => (
              <BiomarkerCard
                key={`${bm.gene}-un-${i}`}
                bm={bm}
                explanation={explanations.find((e) => e.gene === bm.gene)}
              />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
