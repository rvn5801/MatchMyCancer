"""Generate synthetic oncology reports as PDFs for testing.

Creates realistic-looking pathology and genomics reports so you can
test the full pipeline: upload → extract → analyze.
"""

import fitz  # PyMuPDF
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "test_reports"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Report templates ────────────────────────────────────────────────────────

REPORTS = {
    "lung_egfr": {
        "filename": "lung_adenocarcinoma_egfr_report.pdf",
        "title": "MOLECULAR PATHOLOGY REPORT",
        "subtitle": "Next-Generation Sequencing (NGS) — Solid Tumor Panel",
        "body": """
PATIENT: [De-identified] 67F, Specimen: Lung, Left Upper Lobe, Core Biopsy

CLINICAL HISTORY:
Never smoker. CT chest showed 3.2 cm spiculated mass in left upper lobe.
No prior cancer history.

DIAGNOSIS:
Invasive adenocarcinoma of the lung, acinar predominant pattern.
Moderately differentiated (Grade 2).
Stage: cT2a N1 M0 — AJCC 8th Edition Stage IIB.

MOLECULAR FINDINGS:
Pathogenic Alterations Detected:
  • EGFR — Exon 19 deletion (p.Glu746_Ala750del)
    Variant Allele Frequency: 42%
    Clinical Significance: PATHOGENIC — FDA-approved therapies available
    
  • TP53 — p.Arg175His (R175H)
    Variant Allele Frequency: 38%
    Clinical Significance: PATHOGENIC — prognostic marker

Additional Genes Tested — No Alterations Detected:
  KRAS, ALK, ROS1, BRAF, MET, RET, NTRK1, NTRK2, NTRK3, ERBB2 (HER2)

IMMUNOHISTOCHEMISTRY:
  PD-L1 (22C3 assay): Tumor Proportion Score (TPS) = 80% — HIGH POSITIVE

GENOMIC SIGNATURES:
  Microsatellite Instability (MSI): Stable (MSS)
  Tumor Mutational Burden (TMB): 8.4 mutations/Mb

PRIOR TREATMENT:
  Carboplatin + Pemetrexed × 4 cycles (completed April 2023)
  Best Response: Partial Response (40% tumor reduction)

INTERPRETATION:
EGFR exon 19 deletion is a well-established sensitizing mutation predictive
of response to EGFR tyrosine kinase inhibitors (TKIs). Multiple FDA-approved
therapies target this alteration. High PD-L1 expression (TPS 80%) suggests
potential benefit from immune checkpoint inhibitor therapy.

Electronically signed: J. Chen, MD, PhD — Molecular Pathology
Report Date: 2024-01-15
"""
    },
    "melanoma_braf": {
        "filename": "melanoma_braf_report.pdf",
        "title": "PATHOLOGY & MOLECULAR REPORT",
        "subtitle": "Dermatopathology — Molecular Diagnostics",
        "body": """
PATIENT: [De-identified] 54M, Specimen: Skin, Right Shoulder, Excisional Biopsy

CLINICAL HISTORY:
Changing mole on right shoulder over 6 months. Family history of melanoma
(mother). No prior systemic therapy.

DIAGNOSIS:
Malignant melanoma, superficial spreading type.
Breslow thickness: 2.4 mm
Clark level: IV
Ulceration: Present
Mitotic rate: 4/mm²
Stage: pT3b N0 M0 — AJCC 8th Edition Stage IIB

MOLECULAR FINDINGS:
BRAF Mutation Analysis (PCR):
  • BRAF V600E (c.1799T>A) — DETECTED
    Clinical Significance: PATHOGENIC — FDA-approved targeted therapies available

NRAS Mutation Analysis:
  • NRAS — Wild-type (no mutation detected)

KIT Mutation Analysis:
  • KIT — Wild-type (no mutation detected)

IMMUNOHISTOCHEMISTRY:
  PD-L1 (28-8 assay): Tumor cell staining <1% — NEGATIVE

PRIOR TREATMENT:
  Wide local excision with 2 cm margins (completed).
  Sentinel lymph node biopsy: Negative (0/3 nodes).
  No prior systemic therapy.

INTERPRETATION:
BRAF V600E mutation is present in approximately 40-50% of cutaneous melanomas
and is predictive of response to BRAF + MEK inhibitor combination therapy.
Multiple FDA-approved targeted therapy regimens are available. PD-L1 expression
is low, but immunotherapy may still be considered.

Electronically signed: M. Rodriguez, MD — Dermatopathology
Report Date: 2024-02-20
"""
    },
    "colorectal_msi": {
        "filename": "colorectal_msi_report.pdf",
        "title": "SURGICAL PATHOLOGY & MOLECULAR REPORT",
        "subtitle": "Gastrointestinal Pathology — Molecular Diagnostics",
        "body": """
PATIENT: [De-identified] 58M, Specimen: Colon, Sigmoid, Endoscopic Biopsy

CLINICAL HISTORY:
Rectal bleeding and change in bowel habits × 3 months. Colonoscopy revealed
4.5 cm ulcerated mass in sigmoid colon. No family history of colorectal cancer.

DIAGNOSIS:
Invasive adenocarcinoma of the sigmoid colon, moderately differentiated.
Stage: cT3 N1 M0 — AJCC 8th Edition Stage IIIB

MOLECULAR FINDINGS:
RAS Mutation Analysis:
  • KRAS — p.Gly12Asp (G12D) — DETECTED
    Variant Allele Frequency: 35%
    Clinical Significance: PATHOGENIC — Negative predictor for anti-EGFR therapy

  • NRAS — Wild-type

BRAF Mutation Analysis:
  • BRAF V600E — Not detected (Wild-type)

MICROSATELLITE INSTABILITY (MSI) TESTING:
  MSI Status: MSI-H (High) — 4 of 5 markers unstable
  Mismatch Repair (MMR) IHC:
    MLH1: Lost (absent nuclear staining)
    PMS2: Lost (absent nuclear staining)
    MSH2: Intact
    MSH6: Intact
  Interpretation: Deficient MMR (dMMR) — likely sporadic MLH1 promoter hypermethylation

TUMOR MUTATIONAL BURDEN:
  TMB: 25.3 mutations/Mb — HIGH

IMMUNOHISTOCHEMISTRY:
  PD-L1 (22C3): Combined Positive Score (CPS) = 5

PRIOR TREATMENT:
  No prior systemic therapy.
  Planned: Surgical resection followed by adjuvant chemotherapy.

INTERPRETATION:
MSI-H/dMMR status is a strong predictive biomarker for immune checkpoint
inhibitor therapy. High TMB (25.3 mut/Mb) further supports potential benefit
from immunotherapy. KRAS G12D mutation predicts lack of response to anti-EGFR
monoclonal antibodies (cetuximab, panitumumab). FDA-approved immunotherapy
options are available for MSI-H colorectal cancer.

Electronically signed: S. Park, MD, PhD — GI Pathology
Report Date: 2024-03-10
"""
    },
}


def create_pdf_report(filename: str, title: str, subtitle: str, body: str) -> Path:
    """Generate a realistic-looking PDF medical report."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # US Letter

    # Header bar
    page.draw_rect(fitz.Rect(50, 40, 562, 80), color=(0.1, 0.3, 0.6), fill=(0.1, 0.3, 0.6))
    page.insert_text(
        fitz.Point(60, 65),
        "UNIVERSITY MEDICAL CENTER — DEPARTMENT OF PATHOLOGY",
        fontsize=10,
        color=(1, 1, 1),
    )

    # Title
    page.insert_text(fitz.Point(60, 110), title, fontsize=14, color=(0, 0, 0))
    page.insert_text(fitz.Point(60, 128), subtitle, fontsize=10, color=(0.4, 0.4, 0.4))

    # Divider line
    page.draw_line(fitz.Point(60, 140), fitz.Point(552, 140), color=(0.7, 0.7, 0.7))

    # Body text
    y = 160
    for line in body.strip().split("\n"):
        if not line.strip():
            y += 8
            continue
        page.insert_text(fitz.Point(60, y), line, fontsize=9, color=(0.15, 0.15, 0.15))
        y += 13

        # New page if needed
        if y > 730:
            page = doc.new_page(width=612, height=792)
            y = 60

    # Footer
    page.insert_text(
        fitz.Point(60, 760),
        "CONFIDENTIAL — For medical use only. De-identified for research.",
        fontsize=7,
        color=(0.6, 0.6, 0.6),
    )

    output_path = OUTPUT_DIR / filename
    doc.save(str(output_path))
    doc.close()
    return output_path


if __name__ == "__main__":
    for key, report in REPORTS.items():
        path = create_pdf_report(**report)
        print(f"Created: {path}")
    print(f"\nAll reports saved to: {OUTPUT_DIR}")
