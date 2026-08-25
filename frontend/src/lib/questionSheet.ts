// Printable question sheet for the patient's next appointment.
//
// The questions are derived from what the analysis found AND what it didn't —
// the absence of genomic testing, a missing stage, an equivocal result. All
// deterministic template text; no LLM writes anything a patient will hand to
// their doctor.

import type { AnalyzeResponse } from "@/lib/api";

export function buildQuestions(data: AnalyzeResponse): string[] {
  const { extraction, trials } = data;
  const biomarkers = extraction.biomarkers.biomarkers;
  const tumors = extraction.tumors ?? [];
  const dx = extraction.diagnosis;
  const questions: string[] = [];

  if (biomarkers.length === 0) {
    questions.push(
      "Has my tumour had biomarker or genomic testing? Would the results change my treatment options?"
    );
  }
  if (biomarkers.some((b) => b.result === "equivocal")) {
    questions.push(
      "One of my biomarker results was borderline. Is a follow-up test needed to confirm it?"
    );
  }
  if (biomarkers.some((b) => b.result === "not_tested")) {
    questions.push(
      "My report mentions a marker that wasn't assessed. Should it be tested?"
    );
  }
  if (dx && !dx.stage && dx.tnm) {
    questions.push(
      `My report shows "${dx.tnm}" but no overall stage. What stage is my cancer, and what does that mean for me?`
    );
  }
  if (dx?.tnm) {
    questions.push(
      `Can you explain what "${dx.tnm}" means in plain language?`
    );
  }
  if (tumors.length > 1) {
    questions.push(
      "My report describes more than one tumour. How does that affect my treatment plan?"
    );
  }
  if (trials.length > 0) {
    questions.push(
      "Are any clinical trials appropriate for my situation? What would joining one involve?"
    );
  }
  questions.push(
    "What are the treatment options for my diagnosis, and what do you recommend?",
    "What are the next steps, and how quickly do we need to decide?"
  );
  return questions;
}

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function openQuestionSheet(data: AnalyzeResponse): boolean {
  const { extraction } = data;
  const tumors = extraction.tumors ?? [];
  const dx = extraction.diagnosis;

  const summaryLines: string[] = [];
  if (tumors.length > 1) {
    for (const t of tumors) {
      const bits = [t.histology, t.laterality, t.tnm ?? t.stage, t.grade]
        .filter(Boolean)
        .join(" · ");
      summaryLines.push(`${t.label}: ${bits}`);
    }
  } else if (dx) {
    const bits = [dx.primary_site, dx.histology, dx.stage ?? dx.tnm, dx.grade]
      .filter(Boolean)
      .join(" · ");
    if (bits) summaryLines.push(bits);
  }

  const questions = buildQuestions(data);

  const html = `<!doctype html><html><head><title>Questions for my appointment</title>
<style>
  body { font-family: Georgia, serif; color: #1e293b; max-width: 44rem; margin: 2rem auto; padding: 0 1.5rem; line-height: 1.5; }
  h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
  .sub { color: #64748b; font-size: 0.85rem; margin-bottom: 1.5rem; }
  .dx { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.75rem 1rem; font-size: 0.9rem; margin-bottom: 1.5rem; }
  ol { padding-left: 1.25rem; }
  li { margin-bottom: 0.4rem; page-break-inside: avoid; }
  .lines { border-bottom: 1px solid #cbd5e1; height: 1.6rem; margin-top: 1.1rem; }
  .foot { margin-top: 2rem; font-size: 0.75rem; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 0.75rem; }
  @media print { .noprint { display: none; } body { margin: 0.5rem auto; } }
</style></head><body>
<h1>Questions for my appointment</h1>
<p class="sub">Prepared with MatchMyCancer.ai &middot; ${new Date().toLocaleDateString()}</p>
${summaryLines.length ? `<div class="dx"><strong>From my report:</strong><br>${summaryLines.map(esc).join("<br>")}</div>` : ""}
<ol>
${questions.map((q) => `<li>${esc(q)}<div class="lines"></div><div class="lines"></div></li>`).join("\n")}
</ol>
<div class="foot">This sheet was generated from an AI reading of a medical report, for discussion purposes only. It is not medical advice &mdash; your oncology team's guidance always comes first.</div>
<p class="noprint"><button onclick="window.print()">Print</button></p>
</body></html>`;

  // Blob URL instead of document.write: no script-injection surface, and the
  // page is a plain static document the browser owns.
  const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
  const w = window.open(url, "_blank", "width=820,height=640");
  if (!w) {
    URL.revokeObjectURL(url);
    return false;
  }
  w.focus();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
  return true;
}
