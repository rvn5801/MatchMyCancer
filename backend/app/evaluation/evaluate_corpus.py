"""Evaluate the extraction pipeline against real GDC reports + cBioPortal labels.

Scoring follows a three-way taxonomy, because registry labels are not document
labels (measured on TCGA-B1-A656: report says pNX/MX and no stage group; the
registry says N0/M0/Stage I):

  registry-scored   site, histology, T stage — stated on reports, scored as
                    accuracy against the (code-translated) registry value
  stratified        N, M, stage group — scored against the registry ONLY when
                    the registry value is actually stated in the document
                    text; otherwise the pipeline declining (X / null) is
                    counted as document-faithful, not as error
  specimen-site     C77/C49 registry sites (nodal/soft-tissue specimens,
                    mostly metastatic melanoma) — the registry coded where
                    the sample came FROM, the pipeline reports the origin;
                    bucketed separately, never scored as site error

Predictions are cached per (report, model) in corpus.db, so re-scoring after
a rubric change costs zero LLM calls, and OpenAI vs NVIDIA runs coexist.

Usage:
  python -m app.evaluation.evaluate_corpus --per-project 50
  nvidia_llm python -m app.evaluation.evaluate_corpus --per-project 50
"""

import argparse
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import settings
from app.evaluation import corpus_db

RESULTS_DIR = Path(__file__).parent / "results"

# ── Code → term maps, grounded in the codes actually present in the corpus ──

# Topography prefix → organ. C77/C49 are specimen sites (nodes, soft tissue),
# not origins — bucketed, not scored.
SITE_BY_PREFIX = {
    "C50": "breast", "C34": "lung", "C44": "skin", "C64": "kidney",
    "C17": "small intestine", "C16": "stomach", "C18": "colon",
}
SPECIMEN_SITE_PREFIXES = ("C77", "C49")

# Morphology code → keywords accepted in the extracted histology string.
HISTOLOGY_KEYWORDS: Dict[str, List[str]] = {
    "8500/3": ["ductal carcinoma", "duct carcinoma"],
    "8520/3": ["lobular carcinoma"],
    "8522/3": ["ductal and lobular", "duct and lobular", "mixed ductal"],
    "8523/3": ["ductal carcinoma", "duct carcinoma"],
    "8524/3": ["lobular carcinoma"],
    "8507/3": ["micropapillary"],
    "8503/3": ["papillary"],
    "8502/3": ["secretory"],
    "8510/3": ["medullary"],
    "8480/3": ["mucinous"],
    "8490/3": ["signet ring"],
    "8541/3": ["paget"],
    "8575/3": ["metaplastic"],
    "8401/3": ["apocrine"],
    "8200/3": ["adenoid cystic"],
    "8201/3": ["cribriform"],
    "8211/3": ["tubular"],
    "8230/3": ["solid"],
    "8140/3": ["adenocarcinoma"],
    "8255/3": ["adenocarcinoma"],
    "8252/3": ["adenocarcinoma", "bronchioloalveolar", "lepidic"],
    "8253/3": ["mucinous adenocarcinoma", "adenocarcinoma"],
    "8250/3": ["adenocarcinoma", "bronchioloalveolar", "lepidic"],
    "8260/3": ["papillary"],
    "8310/3": ["clear cell"],
    "8550/3": ["acinar"],
    "8050/3": ["papillary"],
    "8022/3": ["pleomorphic"],
    "8013/3": ["large cell neuroendocrine"],
    "8010/3": ["carcinoma"],
    "8090/3": ["basal cell"],
    "8720/3": ["melanoma"],
    "8721/3": ["melanoma"],
    "8730/3": ["melanoma"],
    "8742/3": ["melanoma"],
    "8743/3": ["melanoma"],
    "8744/3": ["melanoma"],
    "8771/3": ["melanoma"],
    "8772/3": ["melanoma"],
    "9020/3": ["phyllodes"],
}

# ── Pure scoring helpers (unit-tested, no I/O) ─────────────────────────────

def t_component(tnm: Optional[str]) -> Optional[str]:
    """Normalised T from a TNM string: 'pT1a pNX' -> 'T1A'."""
    if not tnm:
        return None
    m = re.search(r"\b(?:y?p)?(T(?:[0-4][A-Da-d]?|IS|is|X|x))\b", tnm)
    return f"T{m.group(1)[1:].upper()}" if m else None


def n_component(tnm: Optional[str]) -> Optional[str]:
    if not tnm:
        return None
    m = re.search(r"\b(?:y?p)?(N(?:[0-3][A-Ca-c]?|X|x)(?:MI|mi)?)\b", tnm)
    return m.group(1).upper() if m else None


def m_component(tnm: Optional[str]) -> Optional[str]:
    if not tnm:
        return None
    m = re.search(r"\b(?:y?p)?(M(?:[01][A-Ba-b]?|X|x))\b", tnm)
    return m.group(1).upper() if m else None


def norm_registry_tnm(value: Optional[str]) -> Optional[str]:
    """Registry 'N0 (I-)' / 'T1A' -> base component 'N0' / 'T1A'."""
    if not value:
        return None
    m = re.match(r"([TNM](?:[0-4X][A-D]?|IS)(?:MI)?)", value.strip().upper())
    return m.group(1) if m else value.strip().upper()


def norm_stage(value: Optional[str]) -> Optional[str]:
    """'STAGE IIA' / 'Stage IIa' -> 'IIA'; unusable forms -> None."""
    if not value:
        return None
    s = value.strip().upper().removeprefix("STAGE").strip()
    return s if re.fullmatch(r"(0|IV|III|II|I)[A-C]?", s) else None


_ROMAN_TO_ARABIC = {"IV": "4", "III": "3", "II": "2", "I": "1"}


def stated_in_text(kind: str, registry_value: str, text: str) -> bool:
    """Is the registry's value literally stated in the document?

    Lenient on surface form (pN0/N0, Stage IIA/stage 2a, OCR 1<->l) but
    word-boundary anchored so Stage I never matches inside Stage III.
    """
    lower = text.lower()

    def present(variant: str) -> bool:
        v = re.escape(variant.lower())
        # OCR digit confusion: 1 <-> l
        v = v.replace("1", "[1l]")
        return re.search(rf"(?<![a-z0-9]){v}(?![a-z0-9])", lower) is not None

    if kind in ("N", "M", "T"):
        base = norm_registry_tnm(registry_value)
        if not base:
            return False
        return any(present(p + base) for p in ("", "p", "yp"))

    if kind == "stage":
        stage = norm_stage(registry_value)
        if not stage:
            return False
        variants = [f"stage {stage}"]
        m = re.match(r"(IV|III|II|I)([A-C]?)", stage)
        if m:
            variants.append(f"stage {_ROMAN_TO_ARABIC[m.group(1)]}{m.group(2)}")
        return any(present(v) for v in variants)

    return False


def score_stratified(
    kind: str, registry_value: Optional[str], extracted: Optional[str], text: str
) -> str:
    """The three-way call for N / M / stage group."""
    if not registry_value:
        return "no_label"
    reg = norm_stage(registry_value) if kind == "stage" else norm_registry_tnm(registry_value)
    if not reg:
        return "no_label"
    ext = extracted.upper().removeprefix("STAGE").strip() if extracted else None

    if stated_in_text(kind, registry_value, text):
        return "stated_correct" if ext == reg else "stated_wrong"
    # Registry value is NOT in the document. Declining is faithfulness.
    if ext is None or ext.endswith("X"):
        return "unstated_declined"
    return "unstated_agrees" if ext == reg else "unstated_differs"


def score_site(registry_code: Optional[str], extracted: Optional[str]) -> str:
    if not registry_code:
        return "no_label"
    prefix = registry_code.split(".")[0].upper()
    if prefix in SPECIMEN_SITE_PREFIXES:
        # Registry coded the specimen (node/soft tissue); the pipeline answers
        # the ORIGIN. For melanoma that origin is skin.
        return "specimen_site_origin_given" if extracted else "specimen_site_no_origin"
    organ = SITE_BY_PREFIX.get(prefix)
    if organ is None:
        return "unmapped_code"
    if not extracted:
        return "missed"
    return "correct" if organ in extracted.lower() else "wrong"


def score_histology(registry_code: Optional[str], extracted: Optional[str]) -> str:
    if not registry_code:
        return "no_label"
    keywords = HISTOLOGY_KEYWORDS.get(registry_code.strip())
    if keywords is None:
        return "unmapped_code"
    if not extracted:
        return "missed"
    low = extracted.lower()
    return "correct" if any(k in low for k in keywords) else "wrong"


# ── Runner ─────────────────────────────────────────────────────────────────

def _ensure_prediction_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS prediction ("
        " file_id TEXT NOT NULL, model TEXT NOT NULL,"
        " payload TEXT NOT NULL, created TEXT NOT NULL,"
        " PRIMARY KEY (file_id, model))"
    )


def get_prediction(conn, file_id: str, model: str, text: str) -> Optional[dict]:
    """Cached extraction, or one live LLM call."""
    row = conn.execute(
        "SELECT payload FROM prediction WHERE file_id = ? AND model = ?",
        (file_id, model),
    ).fetchone()
    if row:
        return json.loads(row["payload"])

    from app.pipelines.diagnosis_extractor import dominant_tumor, extract_tumors

    try:
        tumors = extract_tumors(text)
    except Exception as e:  # noqa: BLE001 — recorded; one failure must not kill the run
        payload = {"error": f"{type(e).__name__}: {e}", "tumors": []}
    else:
        dom = dominant_tumor(tumors)
        payload = {
            "tumors": [t.model_dump(mode="json") for t in tumors],
            "dominant": dom.model_dump(mode="json") if dom else None,
        }
    conn.execute(
        "INSERT OR REPLACE INTO prediction (file_id, model, payload, created) "
        "VALUES (?, ?, ?, ?)",
        (file_id, model, json.dumps(payload),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate extraction on the real corpus")
    parser.add_argument("--per-project", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--method", default="embedded_sorted")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()

    model = settings.openai_model
    endpoint = settings.openai_base_url or "api.openai.com"
    conn = corpus_db.connect(args.db)
    _ensure_prediction_table(conn)

    # Eligible: has text and at least one label.
    rows = conn.execute(
        "SELECT r.file_id, r.barcode, r.project, t.text "
        "FROM report r "
        "JOIN report_text t ON t.file_id = r.file_id AND t.method = ? "
        "  AND t.status = 'ok' "
        "WHERE EXISTS (SELECT 1 FROM label l WHERE l.barcode = r.barcode) "
        "ORDER BY r.file_id",
        (args.method,),
    ).fetchall()

    by_project: Dict[str, list] = {}
    for r in rows:
        by_project.setdefault(r["project"], []).append(r)

    rng = random.Random(args.seed)
    sample = []
    for project in sorted(by_project):
        pool = by_project[project]
        take = min(args.per_project, len(pool))
        sample.extend(rng.sample(pool, take))
        print(f"{project}: sampled {take}/{len(pool)}")

    print(f"\nmodel={model} endpoint={endpoint} n={len(sample)}\n")

    labels: Dict[str, Dict[str, str]] = {}
    for l in conn.execute("SELECT barcode, attribute, value FROM label"):
        labels.setdefault(l["barcode"], {})[l["attribute"]] = l["value"]

    counts: Dict[str, Dict[str, int]] = {
        f: {} for f in ("site", "histology", "T", "N", "M", "stage")
    }
    errors = 0

    for i, r in enumerate(sample, 1):
        pred = get_prediction(conn, r["file_id"], model, r["text"])
        if pred.get("error") or not pred.get("dominant"):
            errors += 1
            continue
        dom = pred["dominant"]
        lab = labels.get(r["barcode"], {})
        text = r["text"]

        def bump(field: str, outcome: str) -> None:
            counts[field][outcome] = counts[field].get(outcome, 0) + 1

        bump("site", score_site(lab.get("ICD_O_3_SITE"), dom.get("primary_site")))
        bump("histology", score_histology(lab.get("ICD_O_3_HISTOLOGY"), dom.get("histology")))

        reg_t = norm_registry_tnm(lab.get("PATH_T_STAGE"))
        ext_t = t_component(dom.get("tnm"))
        if reg_t:
            bump("T", "correct" if ext_t == reg_t else ("missed" if ext_t is None else "wrong"))

        bump("N", score_stratified("N", lab.get("PATH_N_STAGE"), n_component(dom.get("tnm")), text))
        bump("M", score_stratified("M", lab.get("PATH_M_STAGE"), m_component(dom.get("tnm")), text))
        bump("stage", score_stratified("stage", lab.get("AJCC_PATHOLOGIC_TUMOR_STAGE"),
                                       dom.get("stage"), text))

        if i % 10 == 0:
            print(f"  {i}/{len(sample)}")

    # ── Report ─────────────────────────────────────────────────────────────
    results = {
        "model": model,
        "endpoint": endpoint,
        "method": args.method,
        "n_sampled": len(sample),
        "n_extraction_errors": errors,
        "seed": args.seed,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "fields": counts,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"corpus_eval_{re.sub(r'[^A-Za-z0-9._-]', '_', model)}.json"
    out.write_text(json.dumps(results, indent=2))

    print(f"\n{'field':10} outcomes")
    for field, c in counts.items():
        total = sum(c.values())
        parts = "  ".join(f"{k}={v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1]))
        print(f"{field:10} n={total:4}  {parts}")
    if errors:
        print(f"\nextraction errors: {errors} (cached; inspect prediction table)")
    print(f"\nresults -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
