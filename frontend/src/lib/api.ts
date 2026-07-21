const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

export interface Biomarker {
  gene: string;
  alteration: string | null;
  alteration_type: string | null;
  significance: string | null;
  test_method: string | null;
  raw_text: string;
}

export interface BiomarkerResult {
  biomarkers: Biomarker[];
  msi_status: string | null;
  tmb: number | null;
  pd_l1_score: string | null;
}

export interface CancerDiagnosis {
  primary_site: string | null;
  histology: string | null;
  stage: string | null;
  grade: string | null;
  laterality: string | null;
  raw_text: string;
}

export interface Explanation {
  gene: string;
  alteration: string;
  explanation: string;
  biomarker: Biomarker;
}

export interface ReasoningStep {
  step_number: number;
  description: string;
  confidence: number;
}

export interface SourceAttribution {
  source_name: string;
  source_url: string | null;
  relevance: string;
}

export interface ReasoningTrace {
  recommendation_text: string;
  recommendation_type: string;
  reasoning_steps: ReasoningStep[];
  sources: SourceAttribution[];
  disclaimer: string;
}

export interface Therapy {
  drug: string;
  brand: string;
  biomarker: string;
  alteration: string;
  cancer_type: string;
  fda_approval_year: number;
  source: string;
  matched_biomarker: string;
  patient_alteration: string | null;
  match_quality: "exact" | "partial";
  trace?: ReasoningTrace | null;
}

export interface Trial {
  nct_id: string;
  title: string;
  status: string;
  phases: string[];
  description: string;
  eligibility: string;
  locations: { facility: string; city: string; state: string; country: string }[];
  conditions: string[];
  interventions: string[];
  // Freshness (backend enrichment)
  verified_on?: string | null;
  tier?: "HIGHEST" | "MEDIUM" | "LOW";
  is_stale?: boolean;
  // AI eligibility (top-5 trials only)
  eligibility_summary?: string[] | null;
  eligibility_assessment?: string | null;
  eligibility_reasoning?: string | null;
}

export interface Guardrails {
  source_verification: {
    verified: number;
    total: number;
    rate: number;
    details: unknown[];
  };
  confidence_score: number;
  warnings: string[];
}

export interface AnalyzeResponse {
  status: string;
  extraction: {
    biomarkers: BiomarkerResult;
    diagnosis: CancerDiagnosis | null;
    treatment_history: unknown | null;
    raw_report_text: string | null;
  };
  explanations: Explanation[];
  clinical_summary: string;
  therapies: Therapy[];
  trials: Trial[];
  guardrails: Guardrails;
  meta: {
    biomarkers_found: number;
    therapies_matched: number;
    trials_found: number;
    pipeline_version: string;
  };
}

// ── API Functions ──────────────────────────────────────────────────────────

export interface StreamEvent {
  stage: string;
  message: string;
  extraction?: any;
  explanations?: any;
  summary?: any;
  clinical_summary?: any;
  therapies?: any;
  trials?: any;
  guardrails?: any;
  meta?: any;
  error?: string;
}

export async function healthCheck(): Promise<{
  status: string;
  version: string;
}> {
  const res = await fetch(`${API_URL}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

export async function uploadDocument(formData: FormData) {
  const res = await fetch(`${API_URL}/api/v1/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Upload failed: ${res.status}`);
  }
  return res.json();
}

export async function analyzeReport(
  documentText: string
): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_URL}/api/v1/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_text: documentText }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Analysis failed: ${res.status}`);
  }
  return res.json();
}

export async function* analyzeStream(
  documentText: string
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${API_URL}/api/v1/analyze/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: documentText }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Stream failed: ${res.status}`);
  }

  const reader = res.body?.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  if (!reader) return;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            yield JSON.parse(line.slice(6));
          } catch {
            // ignore malformed
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
