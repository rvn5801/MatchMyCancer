"""Generate evaluation ground truth from cBioPortal clinical data.

Downloads curated clinical data from cBioPortal API (already annotated
by pathologists), reconstructs report text, and produces ground truth
JSON ready for the evaluator.

Supports: any cBioPortal study with clinical data (lung, melanoma, etc.)

Usage:
  cd backend && source .venv/bin/activate
  
  # From a cBioPortal study ID
  python -m app.evaluation.fetch_ground_truth --study luad_tcga_pan_can_atlas_2018 --genes EGFR,KRAS,BRAF --samples 10
  
  # Or point to a local clinical data file
  python -m app.evaluation.fetch_ground_truth --file clinical_data.tsv

Output: tcga_ground_truth.json — ready to feed into evaluator.
"""

import argparse
import csv
import json
import sys
import zlib
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


def resolve_entrez_ids(genes: List[str]) -> List[int]:
    """Map HUGO gene symbols to the Entrez IDs the mutations API requires."""
    base_url = "https://www.cbioportal.org/api"
    entrez_ids = []
    for symbol in genes:
        resp = httpx.get(f"{base_url}/genes/{symbol}", timeout=30)
        if resp.status_code != 200:
            print(f"  WARNING: unknown gene symbol {symbol!r} — skipping")
            continue
        entrez_ids.append(resp.json()["entrezGeneId"])
    if not entrez_ids:
        raise RuntimeError(f"No valid gene symbols in {genes}")
    return entrez_ids


def fetch_mutations_for_patients(
    study_id: str, patient_ids: List[str], genes: List[str]
) -> Dict[str, List[str]]:
    """Fetch mutation data for specific patients and genes from cBioPortal.

    Note the endpoint: mutations must be fetched from
    /molecular-profiles/{id}/mutations/fetch. The top-level /mutations/fetch
    takes a different filter shape and answers 200 with an EMPTY body, which
    silently yields zero mutations for every patient.

    Errors are raised, not swallowed — a ground truth file with no biomarkers
    still "passes" evaluation while testing nothing.
    """
    base_url = "https://www.cbioportal.org/api"

    print(f"Fetching mutations for {', '.join(genes)} across {len(patient_ids)} patients...")

    entrez_ids = resolve_entrez_ids(genes)

    # Step 1: Find the mutation molecular profile
    profiles_resp = httpx.get(
        f"{base_url}/studies/{study_id}/molecular-profiles",
        params={"projection": "SUMMARY"},
        timeout=30,
    )
    profiles_resp.raise_for_status()

    mutation_profile = next(
        (
            p["molecularProfileId"]
            for p in profiles_resp.json()
            if p.get("molecularAlterationType") == "MUTATION_EXTENDED"
        ),
        None,
    )
    if not mutation_profile:
        raise RuntimeError(f"No MUTATION_EXTENDED profile in study {study_id}")

    print(f"  Using mutation profile: {mutation_profile}")

    # Step 2: Get samples belonging to our patients
    samples_resp = httpx.get(
        f"{base_url}/studies/{study_id}/samples",
        params={"projection": "SUMMARY", "pageSize": 10000},
        timeout=30,
    )
    samples_resp.raise_for_status()
    sample_ids = [
        s["sampleId"] for s in samples_resp.json() if s.get("patientId") in patient_ids
    ]
    if not sample_ids:
        raise RuntimeError("No samples matched the requested patients")

    # Step 3: Fetch mutations from the per-profile endpoint
    mut_resp = httpx.post(
        f"{base_url}/molecular-profiles/{mutation_profile}/mutations/fetch",
        params={"projection": "DETAILED"},
        json={"entrezGeneIds": entrez_ids, "sampleIds": sample_ids[:500]},
        timeout=90,
    )
    mut_resp.raise_for_status()
    if not mut_resp.content:
        raise RuntimeError(
            "Mutations endpoint returned an empty body — check the filter shape"
        )

    mutations = mut_resp.json()
    print(f"  Got {len(mutations)} mutations total")

    by_patient: Dict[str, List[str]] = {pid: [] for pid in patient_ids}
    for m in mutations:
        pid = m.get("patientId", "")
        gene_symbol = m.get("gene", {}).get("hugoGeneSymbol", "")
        protein_change = m.get("proteinChange", "")
        if pid in by_patient and gene_symbol:
            label = f"{gene_symbol} {protein_change}" if protein_change else gene_symbol
            if label not in by_patient[pid]:
                by_patient[pid].append(label)

    found = sum(1 for v in by_patient.values() if v)
    print(f"  Found mutations in {found}/{len(patient_ids)} patients")
    if found == 0:
        raise RuntimeError(
            "Zero patients had mutations — ground truth would test nothing"
        )
    return by_patient


# Phrasings a real molecular pathology section uses. A labelled
# "Mutations detected: KRAS G12C" line makes extraction a copy job and
# inflates F1 to ~1.0; these force the model to actually parse prose.
_MUTATION_TEMPLATES = [
    "Molecular profiling identified a {alteration} alteration in the {gene} gene",
    "Next-generation sequencing detected {gene} {alteration}",
    "Sequencing revealed a {alteration} substitution in {gene}",
    "{gene} testing was positive for the {alteration} variant",
    "A pathogenic {gene} {alteration} mutation was identified on NGS panel testing",
]


def _render_mutations(mutations: List[str], seed_key: str, prose: bool = True) -> str:
    """Render mutations as report text.

    prose=True varies the phrasing per patient (deterministic on patient ID,
    so regenerating gives a stable file). prose=False keeps the old labelled
    form, which is easier to eyeball but trivial to extract from.
    """
    if not prose:
        return f"Mutations detected: {'; '.join(mutations)}"

    rendered = []
    for i, mut in enumerate(mutations):
        parts = mut.split(" ", 1)
        gene = parts[0]
        alteration = parts[1] if len(parts) > 1 else "mutation"
        # crc32, not hash() — builtin hash is salted per process (PYTHONHASHSEED)
        # and would reshuffle phrasing on every regeneration.
        template = _MUTATION_TEMPLATES[
            (zlib.crc32(seed_key.encode()) + i) % len(_MUTATION_TEMPLATES)
        ]
        rendered.append(template.format(gene=gene, alteration=alteration))
    return ". ".join(rendered)


# Anatomic primary site per TCGA cancer-type acronym.
SITE_BY_CANCER_TYPE = {
    "LUAD": "lung", "LUSC": "lung", "BRCA": "breast", "COAD": "colon",
    "READ": "rectum", "SKCM": "skin", "PRAD": "prostate", "STAD": "stomach",
}


def build_ground_truth_json(
    clinical_data: List[Dict],
    mutations_by_patient: Dict[str, List[str]],
    prose: bool = True,
) -> Dict[str, Any]:
    """Convert clinical data + mutations into evaluator ground truth format."""
    reports = []
    unmapped_cancer_types: set = set()
    unmapped_histology: set = set()

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

        # ICD-O-3 histology codes → human readable.
        # An unmapped code must NOT fall through: "Histology: 8720/3" is not
        # something a report says, and annotating ground truth with a raw code
        # scores a correct extraction ("cutaneous melanoma") as wrong.
        hist_map = {"8140/3": "Adenocarcinoma", "8250/3": "Bronchioloalveolar Adenocarcinoma",
                     "8255/3": "Adenocarcinoma with mixed subtypes", "8260/3": "Papillary Adenocarcinoma",
                     "8480/3": "Mucinous Adenocarcinoma", "8070/3": "Squamous Cell Carcinoma",
                     "8720/3": "Malignant Melanoma", "8721/3": "Nodular Melanoma",
                     "8742/3": "Lentigo Maligna Melanoma", "8743/3": "Superficial Spreading Melanoma",
                     "8500/3": "Infiltrating Duct Carcinoma", "8520/3": "Lobular Carcinoma"}
        hist_name = hist_map.get(histology, "")
        if histology and not hist_name:
            unmapped_histology.add(histology)

        # Build report text
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
            text_parts.append(_render_mutations(mutations, pid, prose=prose))
        text_parts.append("This is a de-identified clinical record from TCGA.")

        report_text = ". ".join(text_parts)

        # Ground truth biomarkers — every gene we fetched, not just one
        gt_biomarkers = []
        for mut in mutations:
            parts = mut.split(" ", 1)
            gt_biomarkers.append({
                "gene": parts[0],
                "alteration": parts[1] if len(parts) > 1 else "mutation",
            })

        # Ground truth diagnosis.
        # Primary site comes from an explicit map, NOT the first word of the
        # cancer name — that trick gives "lung" for "Lung Adenocarcinoma" but
        # "cutaneous" for "Cutaneous Melanoma", where the site is skin.
        site = SITE_BY_CANCER_TYPE.get(cancer_type)
        if site is None:
            unmapped_cancer_types.add(cancer_type)
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

    # Silent gaps here become fake evaluation failures, so say them out loud.
    if unmapped_cancer_types:
        print(f"  WARNING: no primary-site mapping for {sorted(unmapped_cancer_types)} "
              f"— primary_site left unannotated. Add them to SITE_BY_CANCER_TYPE.")
    if unmapped_histology:
        print(f"  WARNING: unmapped ICD-O-3 histology codes {sorted(unmapped_histology)} "
              f"— histology left unannotated. Add them to hist_map.")

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
        "--genes",
        default="EGFR,KRAS,BRAF,ALK,ROS1,ERBB2,MET,TP53",
        help="Comma-separated HUGO gene symbols to fetch mutations for",
    )
    parser.add_argument(
        "--samples", type=int, default=10, help="Number of patients"
    )
    parser.add_argument(
        "--output", default="tcga_ground_truth.json", help="Output file"
    )
    parser.add_argument(
        "--no-prose",
        action="store_true",
        help="Emit 'Mutations detected: GENE ALT' instead of varied pathology "
             "prose. Easier to read, but makes extraction a copy job.",
    )
    args = parser.parse_args()

    genes = [g.strip().upper() for g in args.genes.split(",") if g.strip()]

    print(f"Generating ground truth from: {args.study}")
    print(f"Genes: {', '.join(genes)}, Samples: {args.samples}")

    # Fetch clinical data
    clinical = fetch_cbioportal_clinical_data(args.study, args.samples)
    patient_ids = [p["patient_id"] for p in clinical]

    # Fetch mutations
    mutations = fetch_mutations_for_patients(args.study, patient_ids, genes)

    # Build ground truth
    ground_truth = build_ground_truth_json(clinical, mutations, prose=not args.no_prose)

    # Save
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(ground_truth, f, indent=2)

    print(f"\nSaved {len(ground_truth['reports'])} annotated reports to: {output_path}")
    print(f"\nRun evaluation:")
    print(f"  python -m app.evaluation.evaluator {output_path}")


if __name__ == "__main__":
    main()
