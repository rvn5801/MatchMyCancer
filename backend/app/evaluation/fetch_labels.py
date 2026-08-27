"""Fetch cBioPortal clinical labels for every patient in the corpus.

This is the ground truth side of the evaluation: for each barcode whose
pathology PDF we hold, pull what TCGA's abstractors recorded about the same
patient. The join key is the TCGA barcode; nothing is fuzzy.

The attribute set includes deliberate controls:
  positive (PATH_T_STAGE, GRADE)      — stated verbatim on reports; a low
                                        match rate later means a broken
                                        matcher, not a finding
  negative (OS_MONTHS, TMB, MSI, ...) — cannot appear in a pathology report;
                                        a high match rate means over-matching

Usage:
  cd backend && source .venv/bin/activate
  python -m app.evaluation.fetch_labels
"""

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

import httpx

from app.evaluation import corpus_db

CBIO = "https://www.cbioportal.org/api"
STUDY_SUFFIX = "_tcga_pan_can_atlas_2018"

PATIENT_ATTRS = [
    # fields of interest
    "ICD_O_3_HISTOLOGY", "ICD_O_3_SITE", "AJCC_PATHOLOGIC_TUMOR_STAGE",
    "PATH_N_STAGE", "PATH_M_STAGE",
    # positive control
    "PATH_T_STAGE",
    # negative controls
    "OS_MONTHS", "BUFFA_HYPOXIA_SCORE",
    # staging criteria changed between editions; needed to interpret stage
    "AJCC_STAGING_EDITION",
]
SAMPLE_ATTRS = [
    "GRADE",                                  # positive control
    "TMB_NONSYNONYMOUS", "MSI_SENSOR_SCORE",  # negative controls
]


def resolve_studies(projects: Set[str]) -> Dict[str, str]:
    """Map GDC project ids to cBioPortal pan-can study ids, by discovery.

    COAD and READ are merged by cBioPortal into a single 'coadread' study —
    the one hardcoded special case. Anything unresolvable is a loud warning,
    never a silent skip.
    """
    resp = httpx.get(f"{CBIO}/studies", params={"projection": "SUMMARY"}, timeout=90)
    resp.raise_for_status()
    by_acronym = {
        s["studyId"].removesuffix(STUDY_SUFFIX).upper(): s["studyId"]
        for s in resp.json()
        if s["studyId"].endswith(STUDY_SUFFIX)
    }

    mapping: Dict[str, str] = {}
    for project in sorted(projects):
        acronym = project.removeprefix("TCGA-")
        study = by_acronym.get(acronym)
        if study is None and acronym in ("COAD", "READ"):
            study = by_acronym.get("COADREAD")
        if study is None:
            print(f"  WARNING: no pan-can study for {project} — its reports get no labels")
            continue
        mapping[project] = study
    return mapping


def fetch_attribute(
    study: str, attr: str, level: str
) -> List[dict]:
    """One attribute's values for every patient/sample in a study."""
    resp = httpx.get(
        f"{CBIO}/studies/{study}/clinical-data",
        params={
            "clinicalDataType": level,
            "attributeId": attr,
            "pageSize": 100000,
            "projection": "DETAILED",
        },
        timeout=120,
    )
    if resp.status_code != 200:
        print(f"  WARNING: {study}/{attr} ({level}) -> HTTP {resp.status_code}")
        return []
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch cBioPortal labels for the corpus")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()

    conn = corpus_db.connect(args.db)

    rows = conn.execute("SELECT DISTINCT barcode, project FROM report").fetchall()
    barcodes_by_project: Dict[str, Set[str]] = defaultdict(set)
    for r in rows:
        barcodes_by_project[r["project"]].add(r["barcode"])
    all_barcodes = {b for s in barcodes_by_project.values() for b in s}
    print(f"corpus: {len(all_barcodes)} patients across {len(barcodes_by_project)} projects")

    studies = resolve_studies(set(barcodes_by_project))
    inserted = 0

    for project, study in studies.items():
        wanted = barcodes_by_project[project]
        print(f"\n{project} -> {study} ({len(wanted)} patients)")

        for attr in PATIENT_ATTRS:
            data = fetch_attribute(study, attr, "PATIENT")
            n = 0
            for item in data:
                pid = item.get("patientId", "")
                value = (item.get("value") or "").strip()
                if pid in wanted and value:
                    conn.execute(
                        "INSERT OR REPLACE INTO label (barcode, attribute, value) "
                        "VALUES (?, ?, ?)",
                        (pid, attr, value),
                    )
                    n += 1
            inserted += n
            print(f"  {attr:32} {n:5} patients")

        for attr in SAMPLE_ATTRS:
            data = fetch_attribute(study, attr, "SAMPLE")
            n = 0
            for item in data:
                pid = item.get("patientId", "")
                sample = item.get("sampleId", "")
                value = (item.get("value") or "").strip()
                # Primary solid tumour samples only (TCGA sample code 01).
                # The report describes the primary specimen; collapsing in
                # metastatic or normal samples would label it with values
                # from a different piece of tissue.
                if pid in wanted and value and sample.startswith(f"{pid}-01"):
                    conn.execute(
                        "INSERT OR REPLACE INTO label (barcode, attribute, value) "
                        "VALUES (?, ?, ?)",
                        (pid, attr, value),
                    )
                    n += 1
            inserted += n
            print(f"  {attr:32} {n:5} primary samples")

        conn.commit()

    corpus_db.set_meta(conn, "labels_fetched_from", ", ".join(sorted(studies.values())))
    conn.commit()

    labeled = conn.execute("SELECT COUNT(DISTINCT barcode) AS n FROM label").fetchone()["n"]
    print(f"\ndone: {inserted} labels for {labeled}/{len(all_barcodes)} corpus patients")
    unlabeled = len(all_barcodes) - labeled
    if unlabeled:
        print(f"{unlabeled} patients have no labels (dropped from the pan-can freeze) — "
              f"they are excluded from evaluation denominators, not errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
