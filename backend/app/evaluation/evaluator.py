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


def eval_diagnosis(ground_truth: list[dict], predictions: list[dict]) -> dict:
    """Compute diagnosis accuracy (primary_site, histology, stage)."""
    fields = ["primary_site", "histology", "stage"]
    results = {}
    
    for field in fields:
        tp = fp = fn = 0
        for gt, pred in zip(ground_truth, predictions):
            gt_val = gt.get("ground_truth", {}).get("diagnosis", {}).get(field)
            pred_val = pred.get("diagnosis", {}).get(field)
            
            if gt_val and pred_val:
                # Case-insensitive comparison
                if gt_val.lower() == pred_val.lower():
                    tp += 1
                else:
                    fp += 1
                    fn += 1
            elif pred_val and not gt_val:
                fp += 1
            elif gt_val and not pred_val:
                fn += 1
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        
        results[field] = {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}
    
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["tcga"], default="tcga")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    data_dir = Path(__file__).parent.parent.parent / "tcga_ground_truth.json"
    if not data_dir.exists():
        print(f"Ground truth not found: {data_dir}")
        sys.exit(1)

    reports = load_ground_truth(data_dir)
    if args.limit:
        reports = reports[:args.limit]

    print(f"Evaluating {len(reports)} reports from {args.set}...\n")

    ground_truth = []
    predictions = []

    for i, report in enumerate(reports):
        print(f"  [{i+1}/{len(reports)}] {report['report_id']}...")
        ground_truth.append(report)
        pred = run_extraction(report["report_text"])
        predictions.append(pred)

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

    # Evaluate diagnosis
    diag_results = eval_diagnosis(ground_truth, predictions)
    print("\n| Field | TP | FP | FN | Precision | Recall | F1 |")
    print("|-------|----|----|----|-----------|--------|----|")
    for field, m in diag_results.items():
        print(f"| {field} | {m['tp']} | {m['fp']} | {m['fn']} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} |")


if __name__ == "__main__":
    main()