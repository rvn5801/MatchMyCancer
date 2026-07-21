"""Generate evaluation ground truth from cBioPortal clinical data.

Downloads curated clinical data from cBioPortal API (already annotated
by pathologists), reconstructs report text, and produces ground truth
JSON ready for the evaluator.

Supports: any cBioPortal study with clinical data (lung, melanoma, etc.)

Usage:
  cd backend && source .venv/bin/activate
  
  # From a cBioPortal study ID
  python -m app.evaluation.fetch_ground_truth --study luad_tcga_pan_can_atlas_2018 --gene EGFR --samples 10
  
  # Or point to a local clinical data file
  python -m app.evaluation.fetch_ground_truth --file clinical_data.tsv

Output: tcga_ground_truth.json — ready to feed into evaluator.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx


def fetch_cbioportal_clinical_data(
    study_id: str, sample_count: int = 10
) -> List[Dict[str, str]]:
    """Fetch clinical data from cBioPortal API.

    Returns list of dicts — one per patient — with clinical attributes.
    """
    base_url = "https://www.cbioportal.org/api"

    # Step 1: Get all clinical attributes for the study
    print(f"Fetching clinical attributes for {study_id}...")
    attrs_resp = httpx.get(
        f"{base_url}/studies/{study_id}/clinical-attributes",
        params={"projection": "SUMMARY"},
        timeout=30,
    )
    attrs_resp.raise_for_status()
    attrs = attrs_resp.json()

    # Filter to useful attributes
    useful_attrs = [
        "CANCER_TYPE_ACRONYM", "AJCC_PATHOLOGIC_TUMOR_STAGE",
        "PATH_T_STAGE", "PATH_N_STAGE", "PATH_M_STAGE",
        "AGE", "SEX", "OS_STATUS", "ICD_O_3_HISTOLOGY",
        "ICD_O_3_SITE", "ICD_10",
    ]
    attr_ids = [
        a["clinicalAttributeId"]
        for a in attrs
        if a["clinicalAttributeId"] in useful_attrs
    ]
    print(f"  Found {len(attr_ids)} relevant clinical attributes")

    # Step 2: Get sample list
    print(f"Fetching sample list...")
    samples_resp = httpx.get(
        f"{base_url}/studies/{study_id}/samples",
        params={"projection": "SUMMARY"},
        timeout=30,
    )
    samples_resp.raise_for_status()
    all_samples = samples_resp.json()

    # Get unique patient IDs (take first sample per patient)
    seen_patients = set()
    patient_ids = []
    for s in all_samples:
        pid = s.get("patientId")
        if pid and pid not in seen_patients:
            seen_patients.add(pid)
            patient_ids.append(pid)
            if len(patient_ids) >= sample_count * 2:  # oversample for filtering
                break

    patient_ids = patient_ids[:sample_count * 2]

    # Step 3: Fetch clinical data for patients using the working endpoint
    print(f"Fetching clinical data for {len(patient_ids)} patients...")

    all_data = []
    for attr_id in attr_ids:
        resp = httpx.get(
            f"{base_url}/studies/{study_id}/clinical-data",
            params={
                "clinicalDataType": "PATIENT",
                "attributeId": attr_id,
                "pageSize": 10000,
                "projection": "DETAILED",
            },
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            # Filter to our patients
            matching = [d for d in data if d.get("patientId") in patient_ids]
            all_data.extend(matching)

    clinical_data = all_data
    print(f"  Got {len(clinical_data)} clinical data points")

    # Organize by patient
    patients: Dict[str, Dict] = {}
    for item in clinical_data:
        pid = item["patientId"]
        attr = item["clinicalAttributeId"]
        val = item.get("value", "")
        if pid not in patients:
            patients[pid] = {"patient_id": pid}
        patients[pid][attr] = val

    # Filter to patients with at least CANCER_TYPE_ACRONYM
    filtered = []
    for pid, data in patients.items():
        if data.get("CANCER_TYPE_ACRONYM"):
            filtered.append(data)
            if len(filtered) >= sample_count:
                break

    print(f"  Kept {len(filtered)} patients with sufficient clinical data")
    return filtered


def fetch_mutations_for_patients(
    study_id: str, patient_ids: List[str], gene: str
) -> Dict[str, List[str]]:
    """Fetch mutation data for specific patients and gene from cBioPortal."""
    base_url = "https://www.cbioportal.org/api"

    print(f"Fetching mutations for {gene} across {len(patient_ids)} patients...")

    # Step 1: Find the mutation molecular profile
    try:
        profiles_resp = httpx.get(
            f"{base_url}/studies/{study_id}/molecular-profiles",
            params={"projection": "SUMMARY"},
            timeout=30,
        )
        profiles_resp.raise_for_status()
        profiles = profiles_resp.json()

        mutation_profile = None
        for p in profiles:
            if p.get("molecularAlterationType") == "MUTATION_EXTENDED":
                mutation_profile = p["molecularProfileId"]
                break

        if not mutation_profile:
            print(f"  No MUTATION_EXTENDED profile found")
            return {pid: [] for pid in patient_ids}

        print(f"  Using mutation profile: {mutation_profile}")

        # Step 2: Get samples for these patients
        samples_resp = httpx.get(
            f"{base_url}/studies/{study_id}/samples",
            params={"projection": "SUMMARY", "pageSize": 10000},
            timeout=30,
        )
        samples = samples_resp.json() if samples_resp.status_code == 200 else []
        sample_ids = [s["sampleId"] for s in samples if s.get("patientId") in patient_ids]
        sample_ids = sample_ids[:500]  # limit for API call

        # Step 3: Fetch mutations
        mut_resp = httpx.post(
            f"{base_url}/mutations/fetch",
            params={
                "molecularProfileId": mutation_profile,
                "projection": "DETAILED",
            },
            json={
                "sampleIds": sample_ids,
                "entrezGeneIds": [],
            },
            timeout=60,
        )

        if mut_resp.status_code == 200:
            mutations = mut_resp.json()
            print(f"  Got {len(mutations)} mutations total")

            by_patient: Dict[str, List[str]] = {pid: [] for pid in patient_ids}
            for m in mutations:
                pid = m.get("patientId", "")
                gene_symbol = m.get("gene", {}).get("hugoGeneSymbol", "")
                protein_change = m.get("proteinChange", "")

                if pid in by_patient and gene_symbol.upper() == gene.upper():
                    label = f"{gene_symbol} {protein_change}" if protein_change else gene_symbol
                    by_patient[pid].append(label)

            found = sum(1 for v in by_patient.values() if v)
            print(f"  Found {gene} mutations in {found} patients")
            return by_patient

    except Exception as e:
        print(f"  Mutation fetch error: {e}")

    return {pid: [] for pid in patient_ids}


def build_ground_truth_json(
    clinical_data: List[Dict],
    gene: str,
    mutations_by_patient: Dict[str, List[str]],
) -> Dict[str, Any]:
    """Convert clinical data + mutations into evaluator ground truth format."""
    reports = []

    for patient in clinical_data:
        pid = patient.get("patient_id", "unknown")

        # Reconstruct report text from clinical fields
        cancer_type = patient.get("CANCER_TYPE_ACRONYM", "Unknown")
        stage = patient.get("AJCC_PATHOLOGIC_TUMOR_STAGE", "")
        t_stage = patient.get("PATH_T_STAGE", "")
        n_stage = patient.get("PATH_N_STAGE", "")
        m_stage = patient.get("PATH_M_STAGE", "")
        age = patient.get("AGE", "")
        sex = patient.get("SEX", "")
        histology = patient.get("ICD_O_3_HISTOLOGY", "")
        icd10 = patient.get("ICD_10", "")

        mutations = mutations_by_patient.get(pid, [])

        # Map TCGA codes to human-readable text
        cancer_map = {"LUAD": "Lung Adenocarcinoma", "LUSC": "Lung Squamous Cell Carcinoma",
                       "BRCA": "Breast Cancer", "COAD": "Colon Adenocarcinoma",
                       "READ": "Rectal Adenocarcinoma", "SKCM": "Cutaneous Melanoma",
                       "PRAD": "Prostate Adenocarcinoma", "STAD": "Stomach Adenocarcinoma"}
        cancer_name = cancer_map.get(cancer_type, cancer_type)

        # ICD-O-3 histology codes → human readable
        hist_map = {"8140/3": "Adenocarcinoma", "8250/3": "Bronchioloalveolar Adenocarcinoma",
                     "8255/3": "Adenocarcinoma with mixed subtypes", "8260/3": "Papillary Adenocarcinoma",
                     "8480/3": "Mucinous Adenocarcinoma", "8070/3": "Squamous Cell Carcinoma"}
        hist_name = hist_map.get(histology, histology)

        # Build realistic report text
        text_parts = [f"Diagnosis: {cancer_name}"]
        if hist_name:
            text_parts.append(f"Histology: {hist_name}")
        if stage:
            stage_clean = stage.replace("STAGE ", "Stage ")
            text_parts.append(f"Stage: {stage_clean}")
        if age:
            text_parts.append(f"Age: {age}")
        if sex:
            text_parts.append(f"Sex: {sex}")
        if mutations:
            text_parts.append(f"Mutations detected: {'; '.join(mutations)}")
        text_parts.append("This is a de-identified clinical record from TCGA.")

        report_text = ". ".join(text_parts)

        # Ground truth biomarkers
        gt_biomarkers = []
        for mut in mutations:
            if gene.upper() in mut.upper():
                # Parse protein change if available
                parts = mut.split(" ", 1)
                alteration = parts[1] if len(parts) > 1 else "mutation"
                gt_biomarkers.append({"gene": gene, "alteration": alteration})

        # Ground truth diagnosis
        # Extract just the organ site (first word before "Adenocarcinoma" etc.)
        site_words = cancer_name.lower().split()
        site = site_words[0] if site_words else None  # "lung" from "Lung Adenocarcinoma"
        hist = hist_name.lower() if hist_name else None
        stg = stage.replace("STAGE ", "Stage ") if stage else None

        reports.append({
            "report_id": pid,
            "report_text": report_text,
            "ground_truth": {
                "biomarkers": gt_biomarkers,
                "diagnosis": {
                    "primary_site": site,
                    "histology": hist,
                    "stage": stg,
                },
                "expected_therapies": [],  # Fill manually or use OncoKB mapping
            },
            "_meta": {
                "cancer_type": cancer_type,
                "mutations_raw": mutations,
                "age": age,
            },
        })

    return {"reports": reports, "_source": "cBioPortal TCGA clinical data"}


def main():
    parser = argparse.ArgumentParser(
        description="Generate ground truth from TCGA/cBioPortal clinical data"
    )
    parser.add_argument(
        "--study",
        default="luad_tcga_pan_can_atlas_2018",
        help="cBioPortal study ID (default: luad_tcga_pan_can_atlas_2018)",
    )
    parser.add_argument(
        "--gene", default="EGFR", help="Gene to fetch mutations for"
    )
    parser.add_argument(
        "--samples", type=int, default=10, help="Number of patients"
    )
    parser.add_argument(
        "--output", default="tcga_ground_truth.json", help="Output file"
    )
    args = parser.parse_args()

    print(f"Generating ground truth from: {args.study}")
    print(f"Gene: {args.gene}, Samples: {args.samples}")

    # Fetch clinical data
    clinical = fetch_cbioportal_clinical_data(args.study, args.samples)
    patient_ids = [p["patient_id"] for p in clinical]

    # Fetch mutations
    mutations = fetch_mutations_for_patients(args.study, patient_ids, args.gene)

    # Build ground truth
    ground_truth = build_ground_truth_json(clinical, args.gene, mutations)

    # Save
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(ground_truth, f, indent=2)

    print(f"\nSaved {len(ground_truth['reports'])} annotated reports to: {output_path}")
    print(f"\nRun evaluation:")
    print(f"  python -m app.evaluation.evaluator {output_path}")


if __name__ == "__main__":
    main()
