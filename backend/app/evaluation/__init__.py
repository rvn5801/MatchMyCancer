"""Evaluation framework for MatchMyCancer pipeline.

Compares pipeline output against ground truth annotations to measure:
  1. Biomarker extraction accuracy (precision, recall, F1)
  2. Diagnosis extraction accuracy (field-level match)
  3. Therapy matching accuracy (correct therapies found vs ground truth)
  4. End-to-end report-level metrics

Usage:
  python3 -m app.evaluation.evaluator --ground-truth path/to/ground_truth.json

Ground truth format:
{
  "reports": [
    {
      "report_id": "lung_001",
      "report_text": "Full text of the oncology report...",
      "ground_truth": {
        "biomarkers": [
          {"gene": "EGFR", "alteration": "exon 19 deletion"}
        ],
        "diagnosis": {
          "primary_site": "lung",
          "histology": "adenocarcinoma",
          "stage": "Stage IV"
        },
        "expected_therapies": ["Osimertinib", "Erlotinib"]
      }
    }
  ]
}
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def load_ground_truth(path: str) -> Dict[str, Any]:
    """Load ground truth annotations from JSON file."""
    with open(path) as f:
        return json.load(f)


def evaluate_biomarkers(
    predicted: List[Dict], ground_truth: List[Dict]
) -> Dict[str, Any]:
    """Calculate precision, recall, F1 for biomarker extraction.

    Matches on gene name (case-insensitive). A predicted biomarker is
    correct if its gene appears in ground truth.
    """
    pred_genes = {b["gene"].upper() for b in predicted}
    gt_genes = {b["gene"].upper() for b in ground_truth}

    true_positives = pred_genes & gt_genes
    false_positives = pred_genes - gt_genes
    false_negatives = gt_genes - pred_genes

    tp = len(true_positives)
    fp = len(false_positives)
    fn = len(false_negatives)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "true_positives": sorted(true_positives),
        "false_positives": sorted(false_positives),
        "false_negatives": sorted(false_negatives),
    }


def evaluate_diagnosis(
    predicted: Dict, ground_truth: Dict
) -> Dict[str, Any]:
    """Compare diagnosis fields (site, histology, stage)."""
    results = {}
    for field in ("primary_site", "histology", "stage"):
        pred_val = (predicted.get(field) or "").lower().strip()
        gt_val = (ground_truth.get(field) or "").lower().strip()
        results[field] = {
            "predicted": pred_val or None,
            "ground_truth": gt_val or None,
            "match": pred_val == gt_val if gt_val else None,
        }
    return results


def evaluate_therapies(
    predicted_therapies: List[Dict], expected_drugs: List[str]
) -> Dict[str, Any]:
    """Check which expected therapies were found."""
    pred_drugs = {t["drug"].lower() for t in predicted_therapies}
    expected = {d.lower() for d in expected_drugs}

    found = expected & pred_drugs
    missed = expected - pred_drugs
    extra = pred_drugs - expected

    return {
        "found": sorted(found),
        "missed": sorted(missed),
        "extra": sorted(extra),
        "recall": round(len(found) / len(expected), 3) if expected else 0.0,
    }


def run_evaluation(ground_truth_path: str, pipeline_fn) -> Dict[str, Any]:
    """Run full evaluation on a set of annotated reports.

    Args:
        ground_truth_path: Path to ground truth JSON file.
        pipeline_fn: Function that takes report_text and returns
            the full pipeline output (AnalyzeResponse dict).

    Returns:
        Aggregated evaluation results.
    """
    data = load_ground_truth(ground_truth_path)
    reports = data.get("reports", [])

    if not reports:
        print("No reports found in ground truth file.")
        return {}

    all_biomarker_results = []
    all_diagnosis_results = []
    all_therapy_results = []
    report_summaries = []

    for i, report in enumerate(reports):
        rid = report.get("report_id", f"report_{i}")
        text = report.get("report_text", "")
        gt = report.get("ground_truth", {})

        print(f"\n{'='*50}")
        print(f"Evaluating: {rid}")
        print(f"{'='*50}")

        # Run pipeline
        try:
            result = pipeline_fn(text)
        except Exception as e:
            print(f"  ERROR: {e}")
            report_summaries.append({"report_id": rid, "error": str(e)})
            continue

        extraction = result.get("extraction", {})
        biomarkers_data = extraction.get("biomarkers", {})
        pred_biomarkers = biomarkers_data.get("biomarkers", [])
        gt_biomarkers = gt.get("biomarkers", [])

        pred_diagnosis = extraction.get("diagnosis") or {}
        gt_diagnosis = gt.get("diagnosis", {})

        pred_therapies = result.get("therapies", [])
        gt_therapies = gt.get("expected_therapies", [])

        # Evaluate biomarkers
        bm_result = evaluate_biomarkers(pred_biomarkers, gt_biomarkers)
        all_biomarker_results.append(bm_result)
        print(f"  Biomarkers: P={bm_result['precision']} R={bm_result['recall']} F1={bm_result['f1']}")
        if bm_result["false_positives"]:
            print(f"    False positives: {bm_result['false_positives']}")
        if bm_result["false_negatives"]:
            print(f"    False negatives: {bm_result['false_negatives']}")

        # Evaluate diagnosis
        diag_result = evaluate_diagnosis(pred_diagnosis, gt_diagnosis)
        all_diagnosis_results.append(diag_result)
        matches = sum(1 for f in diag_result.values() if f["match"])
        total = sum(1 for f in diag_result.values() if f["ground_truth"] is not None)
        print(f"  Diagnosis: {matches}/{total} fields correct")

        # Evaluate therapies
        therapy_result = evaluate_therapies(pred_therapies, gt_therapies)
        all_therapy_results.append(therapy_result)
        print(f"  Therapies: {len(therapy_result['found'])}/{len(gt_therapies)} found")
        if therapy_result["missed"]:
            print(f"    Missed: {therapy_result['missed']}")

        report_summaries.append({
            "report_id": rid,
            "biomarker_f1": bm_result["f1"],
            "diagnosis_accuracy": matches / total if total > 0 else None,
            "therapy_recall": therapy_result["recall"],
        })

    # Aggregate
    bm_precisions = [r["precision"] for r in all_biomarker_results]
    bm_recalls = [r["recall"] for r in all_biomarker_results]
    bm_f1s = [r["f1"] for r in all_biomarker_results]

    summary = {
        "total_reports": len(reports),
        "evaluated": len(report_summaries),
        "biomarkers": {
            "avg_precision": round(sum(bm_precisions) / len(bm_precisions), 3) if bm_precisions else 0,
            "avg_recall": round(sum(bm_recalls) / len(bm_recalls), 3) if bm_recalls else 0,
            "avg_f1": round(sum(bm_f1s) / len(bm_f1s), 3) if bm_f1s else 0,
        },
        "report_details": report_summaries,
    }

    print(f"\n{'='*50}")
    print("FINAL SUMMARY")
    print(f"{'='*50}")
    print(f"Reports evaluated: {summary['evaluated']}/{summary['total_reports']}")
    print(f"Avg Biomarker F1: {summary['biomarkers']['avg_f1']}")
    print(f"Avg Biomarker Precision: {summary['biomarkers']['avg_precision']}")
    print(f"Avg Biomarker Recall: {summary['biomarkers']['avg_recall']}")

    return summary


if __name__ == "__main__":
    # CLI entry point: python -m app.evaluation.evaluator ground_truth.json
    if len(sys.argv) < 2:
        print("Usage: python -m app.evaluation.evaluator <ground_truth.json>")
        sys.exit(1)

    from app.pipelines.clinical_extraction import extract_clinical_data
    from app.pipelines.explanation_engine import explain_biomarkers, generate_clinical_summary
    from app.pipelines.therapy_matcher import match_therapies
    from app.pipelines.guardrails import validate_biomarker_against_source, calculate_confidence

    def run_pipeline(text: str) -> Dict:
        """Full pipeline matching the /analyze endpoint."""
        extraction = extract_clinical_data(text)
        explanations = explain_biomarkers(extraction.biomarkers)
        summary = generate_clinical_summary(extraction.model_dump())
        therapies = match_therapies(extraction.biomarkers)

        bm_dicts = extraction.model_dump()["biomarkers"]["biomarkers"]
        validated = validate_biomarker_against_source(bm_dicts, text)
        verified = sum(1 for v in validated if v["source_verified"])
        rate = verified / len(validated) if validated else 1.0
        confidence = calculate_confidence(rate, True, len(therapies))

        return {
            "extraction": extraction.model_dump(),
            "explanations": explanations,
            "clinical_summary": summary,
            "therapies": therapies,
            "guardrails": {"confidence_score": confidence, "source_verification": {"verified": verified, "total": len(validated)}},
        }

    summary = run_evaluation(sys.argv[1], run_pipeline)
    # Save detailed results
    out_path = Path(sys.argv[1]).with_suffix(".results.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nDetailed results saved to: {out_path}")
