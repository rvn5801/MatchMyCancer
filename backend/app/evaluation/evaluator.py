#!/usr/bin/env python
"""Evaluation v2 — per-biomarker precision/recall against TCGA ground truth.

Usage:
    python -m backend.app.evaluation.evaluator --set tcga
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.pipelines.clinical_extraction import extract_clinical_data


def load_ground_truth(path: Path) -> list[dict[str, Any]]:
    with open(path) as f:
        data = json.load(f)
    return data.get("reports", [])


def run_extraction(report_text: str) -> dict[str, Any]:
    try:
        result = extract_clinical_data(report_text)
        return result.model_dump()
    except Exception as e:
        return {"error": str(e), "biomarkers": {"biomarkers": []}}


def eval_biomarkers(ground_truth: list[dict], predictions: list[dict]) -> dict:
    """Compute per-biomarker precision/recall."""
    all_genes = set()
    for gt in ground_truth:
        for b in gt.get("ground_truth", {}).get("biomarkers", []):
            if b.get("gene"):
                all_genes.add(b["gene"].upper())
    for pred in predictions:
        for b in pred.get("biomarkers", {}).get("biomarkers", []):
            if b.get("gene"):
                all_genes.add(b["gene"].upper())

    results = {}
    for gene in sorted(all_genes):
        tp = fp = fn = 0
        for gt, pred in zip(ground_truth, predictions):
            gt_genes = [b["gene"].upper() for b in gt.get("ground_truth", {}).get("biomarkers", []) if b.get("gene")]
            pred_genes = [b["gene"].upper() for b in pred.get("biomarkers", {}).get("biomarkers", []) if b.get("gene")]
            
            in_gt = gene in gt_genes
            in_pred = gene in pred_genes
            
            if in_gt and in_pred:
                tp += 1
            elif in_pred and not in_gt:
                fp += 1
            elif in_gt and not in_pred:
                fn += 1
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        
        results[gene] = {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}
    
    return results


def _norm_alteration(alt: str | None) -> str:
    """Normalize an alteration for comparison (case/whitespace only).

    Deliberately conservative: no synonym folding. 'exon 19 deletion' and
    'E746_A750del' are the same event clinically, so a miss here may be a
    naming difference rather than an error — check the mismatch list before
    treating the number as accuracy.
    """
    return " ".join((alt or "").lower().split())


def eval_alterations(ground_truth: list[dict], predictions: list[dict]) -> dict:
    """Score gene+alteration pairs, not just gene symbols.

    Gene-level scoring calls 'EGFR T790M' a perfect match for
    'EGFR exon 19 deletion' — but those select different drugs. Therapy
    matching keys off the alteration, so this is the metric that reflects
    whether the recommendation would be right.
    """
    tp = fp = fn = 0
    mismatches = []

    for gt, pred in zip(ground_truth, predictions):
        gt_pairs = {
            (b["gene"].upper(), _norm_alteration(b.get("alteration")))
            for b in gt.get("ground_truth", {}).get("biomarkers", [])
            if b.get("gene")
        }
        pred_pairs = {
            (b["gene"].upper(), _norm_alteration(b.get("alteration")))
            for b in pred.get("biomarkers", {}).get("biomarkers", [])
            if b.get("gene")
        }

        tp += len(gt_pairs & pred_pairs)
        fp += len(pred_pairs - gt_pairs)
        fn += len(gt_pairs - pred_pairs)

        for gene, alt in sorted(gt_pairs - pred_pairs):
            got = sorted(a for g, a in pred_pairs if g == gene)
            mismatches.append({
                "report_id": gt.get("report_id"),
                "gene": gene,
                "expected": alt,
                "predicted": got or None,
            })

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "mismatches": mismatches,
    }


def eval_diagnosis(ground_truth: list[dict], predictions: list[dict]) -> dict:
    """Compute diagnosis accuracy (primary_site, histology, stage).

    Scoring stays exact-match, but near-misses are counted separately as
    `partial`. TCGA histology labels carry ICD-O-3 specificity the report
    prose does not ("adenocarcinoma with mixed subtypes" vs the model's
    "adenocarcinoma") — scoring those as a flat miss reads as a 0.10 F1 and
    hides that the extraction was substantively right. Partial is reported,
    never folded into TP.
    """
    fields = ["primary_site", "histology", "stage"]
    results = {}

    for field in fields:
        tp = fp = fn = partial = 0
        for gt, pred in zip(ground_truth, predictions):
            gt_val = gt.get("ground_truth", {}).get("diagnosis", {}).get(field)
            pred_val = pred.get("diagnosis", {}).get(field)

            if gt_val and pred_val:
                g, p = gt_val.lower().strip(), pred_val.lower().strip()
                if g == p:
                    tp += 1
                else:
                    if g in p or p in g:
                        partial += 1
                    fp += 1
                    fn += 1
            elif pred_val and not gt_val:
                fp += 1
            elif gt_val and not pred_val:
                fn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        results[field] = {
            "tp": tp, "fp": fp, "fn": fn, "partial": partial,
            "precision": precision, "recall": recall, "f1": f1,
        }

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "ground_truth",
        nargs="?",
        default="tcga_ground_truth.json",
        help="Ground truth JSON (relative to backend/ or an absolute path)",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--reuse-predictions",
        action="store_true",
        help="Score the cached predictions instead of re-running extraction. "
             "Iterating on metrics costs nothing this way.",
    )
    args = parser.parse_args()

    gt_path = Path(args.ground_truth)
    if not gt_path.is_absolute():
        gt_path = Path(__file__).parent.parent.parent / gt_path
    if not gt_path.exists():
        print(f"Ground truth not found: {gt_path}")
        sys.exit(1)

    reports = load_ground_truth(gt_path)
    if args.limit:
        reports = reports[:args.limit]

    # A file with no annotated biomarkers scores a vacuous 0.0 — say so loudly.
    annotated = sum(1 for r in reports if r.get("ground_truth", {}).get("biomarkers"))
    if annotated == 0:
        print(f"WARNING: no reports in {gt_path.name} have ground-truth biomarkers.")
        print("         Biomarker metrics below are meaningless. Regenerate with:")
        print("         python -m app.evaluation.fetch_ground_truth --genes EGFR,KRAS,...")

    print(f"Evaluating {len(reports)} reports from {gt_path.name} "
          f"({annotated} with biomarker annotations)...\n")

    ground_truth = list(reports)
    pred_cache = gt_path.with_suffix(".predictions.json")

    if args.reuse_predictions:
        if not pred_cache.exists():
            print(f"No cached predictions at {pred_cache} — run once without "
                  f"--reuse-predictions first.")
            sys.exit(1)
        predictions = json.loads(pred_cache.read_text())[: len(ground_truth)]
        if len(predictions) != len(ground_truth):
            print(f"Cache has {len(predictions)} predictions for "
                  f"{len(ground_truth)} reports — regenerate it.")
            sys.exit(1)
        print(f"Scoring cached predictions from {pred_cache.name} (no LLM calls).\n")
    else:
        predictions = []
        for i, report in enumerate(reports):
            print(f"  [{i+1}/{len(reports)}] {report['report_id']}...")
            predictions.append(run_extraction(report["report_text"]))
        pred_cache.write_text(json.dumps(predictions, indent=2))
        print(f"\nCached predictions -> {pred_cache.name}")

    # Evaluate biomarkers
    results = eval_biomarkers(ground_truth, predictions)

    # Print biomarker markdown table
    print("\n| Gene | TP | FP | FN | Precision | Recall | F1 |")
    print("|------|----|----|----|-----------|--------|----|")
    for gene, m in sorted(results.items()):
        print(f"| {gene} | {m['tp']} | {m['fp']} | {m['fn']} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} |")

    # Macro averages
    if results:
        macro_p = sum(m["precision"] for m in results.values()) / len(results)
        macro_r = sum(m["recall"] for m in results.values()) / len(results)
        macro_f1 = sum(m["f1"] for m in results.values()) / len(results)
        print(f"\n**Biomarker Macro Avg:** Precision={macro_p:.3f} Recall={macro_r:.3f} F1={macro_f1:.3f}")

        # Micro averages
        total_tp = sum(m["tp"] for m in results.values())
        total_fp = sum(m["fp"] for m in results.values())
        total_fn = sum(m["fn"] for m in results.values())
        micro_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
        micro_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
        micro_f1 = 2 * micro_p * micro_r / (micro_p + micro_r) if (micro_p + micro_r) > 0 else 0
        print(f"**Biomarker Micro Avg:** Precision={micro_p:.3f} Recall={micro_r:.3f} F1={micro_f1:.3f}")

    # Gene+alteration — the pairing therapy matching actually keys off
    alt = eval_alterations(ground_truth, predictions)
    print(f"\n**Gene+Alteration (exact):** Precision={alt['precision']:.3f} "
          f"Recall={alt['recall']:.3f} F1={alt['f1']:.3f} "
          f"(TP={alt['tp']} FP={alt['fp']} FN={alt['fn']})")
    if alt["mismatches"]:
        print(f"\nAlteration mismatches ({len(alt['mismatches'])}) — first 10:")
        for m in alt["mismatches"][:10]:
            print(f"  {m['report_id']}  {m['gene']}: expected {m['expected']!r}, "
                  f"got {m['predicted']}")

    # Evaluate diagnosis
    diag_results = eval_diagnosis(ground_truth, predictions)
    print("\n| Field | TP | Partial | FP | FN | Precision | Recall | F1 |")
    print("|-------|----|---------|----|----|-----------|--------|----|")
    for field, m in diag_results.items():
        print(f"| {field} | {m['tp']} | {m['partial']} | {m['fp']} | {m['fn']} "
              f"| {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} |")
    print("\nPartial = prediction is a more/less specific form of the truth "
          "(scored as a miss, shown for triage).")


if __name__ == "__main__":
    main()