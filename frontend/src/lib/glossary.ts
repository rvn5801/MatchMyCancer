// Plain-language definitions for terms that appear in oncology reports.
//
// Static dict, no LLM: definitions are written once, reviewed once, and
// identical for every patient - generated definitions would reintroduce the
// hallucination surface everywhere else in the app is built to remove.
// Longest term wins when terms overlap ("ductal carcinoma in situ" before
// "ductal carcinoma" before "carcinoma").

export const GLOSSARY: Record<string, string> = {
  "ductal carcinoma in situ":
    "Abnormal cells contained inside the milk ducts that have not spread into nearby tissue. Often called DCIS, and considered the earliest, non-invasive form.",
  "invasive ductal carcinoma":
    "Cancer that started in a milk duct and has grown into the surrounding breast tissue. It is the most common type of breast cancer.",
  "squamous cell carcinoma":
    "Cancer that starts in squamous cells - the flat cells that line many surfaces of the body, such as the skin, lungs and throat.",
  "renal cell carcinoma":
    "The most common type of kidney cancer, starting in the lining of the kidney's small tubes.",
  adenocarcinoma:
    "Cancer that starts in gland cells - cells that make mucus or other fluids. Common sites include the lung, colon, breast, prostate and pancreas.",
  carcinoma:
    "Cancer that starts in the cells lining an organ or the skin. Most cancers are carcinomas.",
  melanoma:
    "A cancer that starts in melanocytes, the cells that give skin its colour. It can appear on skin anywhere, and occasionally in other tissues.",
  dcis:
    "Short for ductal carcinoma in situ - abnormal cells contained inside the milk ducts that have not spread into nearby tissue.",
  metastatic:
    "Cancer that has spread from where it started to another part of the body. A tumour found in a lymph node or organ may have travelled there from elsewhere.",
  metastasis:
    "The spread of cancer from where it started to another part of the body.",
  biomarker:
    "A measurable feature of your tumour - such as a gene change or a protein level - that can help predict which treatments are likely to work.",
  histology:
    "What the tumour cells look like under a microscope, which tells doctors the exact type of cancer.",
  "nottingham grade":
    "A 1-to-3 score for breast cancer describing how abnormal the cells look. Grade 1 grows slowest; grade 3 grows fastest.",
  grade:
    "How abnormal the tumour cells look compared to healthy cells. Higher grade usually means faster-growing.",
  stage:
    "How far the cancer has spread, usually written as Stage I (early) to Stage IV (spread to distant parts of the body).",
  tnm: "A three-part code doctors use: T describes the tumour's size, N whether lymph nodes are involved, and M whether it has spread to distant sites.",
  "sentinel lymph node":
    "The first lymph node that fluid from the tumour area drains to - checked first because if cancer spreads, it usually appears there before anywhere else.",
  "lymph node":
    "Small bean-shaped glands that filter fluid from the body. Doctors check them because cancer cells that spread often reach them first.",
  "lymphovascular invasion":
    "Cancer cells found inside small blood or lymph vessels near the tumour - a sign the cancer may have a route to spread.",
  margins:
    "The edge of the tissue removed in surgery. 'Negative' or 'clear' margins mean no cancer cells were found at the edge - a good sign the tumour was fully removed.",
  invasive:
    "Cancer that has grown beyond where it started into surrounding tissue.",
  "in situ":
    "Latin for 'in place' - abnormal cells that are still contained where they started and have not spread into nearby tissue.",
  laterality: "Which side of the body - left, right, or both.",
  multifocal:
    "More than one separate area of tumour in the same organ or region.",
  her2: "A protein that can make some cancers grow faster. HER2-positive cancers can be treated with drugs that target this protein; HER2-negative cancers need different treatments.",
  "estrogen receptor":
    "A protein on some cancer cells that responds to the hormone estrogen. If positive, hormone-blocking therapy may be a treatment option.",
  "progesterone receptor":
    "A protein on some cancer cells that responds to the hormone progesterone. Usually tested together with the estrogen receptor.",
  "pd-l1":
    "A protein some tumours use to hide from the immune system. Higher levels can mean immunotherapy is more likely to help.",
  msi: "Microsatellite instability - a pattern of DNA errors in some tumours. Tumours with high MSI often respond well to immunotherapy.",
  tmb: "Tumour mutational burden - how many DNA changes the tumour carries. A high count can make immunotherapy more likely to work.",
  mutation:
    "A change in a gene's DNA. Some mutations drive cancer growth - and some of those can be targeted by specific drugs.",
  amplification:
    "Too many copies of a gene, which can make cells produce too much of a growth-promoting protein.",
  fusion:
    "Two genes joined together abnormally, which can create a protein that drives cancer growth. Several fusions have targeted drugs.",
  "variant of unknown significance":
    "A gene change whose effect is not yet understood. It is recorded, but it does not guide treatment decisions.",
  immunotherapy:
    "Treatment that helps your own immune system recognise and attack cancer cells.",
  "targeted therapy":
    "Drugs designed to attack a specific feature of cancer cells - usually a particular protein or gene change - while sparing most healthy cells.",
  chemotherapy:
    "Drugs that kill fast-dividing cells, including cancer cells. Works throughout the whole body.",
  ngs: "Next-generation sequencing - a lab method that reads many genes from a tumour sample at once to find changes that might guide treatment.",
  ihc: "Immunohistochemistry - a lab stain that shows whether specific proteins (like HER2 or hormone receptors) are present on tumour cells.",
  fish: "A lab test that counts copies of a gene inside cells - often used to confirm HER2 results.",
  pathology:
    "The study of tissue under a microscope. A pathology report describes what was found in tissue removed during a biopsy or surgery.",
  oncologist: "A doctor who specialises in treating cancer.",
  malignant: "Cancerous - able to grow into nearby tissue and spread.",
  benign: "Not cancerous. Benign growths do not spread to other parts of the body.",
  eligibility:
    "The rules deciding who can join a clinical trial - based on cancer type, stage, previous treatments and general health.",
};

// Longest-first so multi-word terms match before their substrings.
const TERMS = Object.keys(GLOSSARY).sort((a, b) => b.length - a.length);

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export const GLOSSARY_REGEX = new RegExp(
  `\\b(${TERMS.map(escape).join("|")})\\b`,
  "gi"
);

export function lookup(term: string): string | undefined {
  return GLOSSARY[term.toLowerCase()];
}
