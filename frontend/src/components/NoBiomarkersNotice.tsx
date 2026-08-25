// Shown when the pipeline finds no biomarkers.
//
// Measured on 8/8 real de-identified TCGA pathology reports: surgical
// pathology reports contain zero molecular content. The extraction is
// correct — the document simply doesn't hold that data, because genomic
// testing is reported separately.
//
// So this is a RESULT, not an error state. Deliberately styled calm (slate,
// not rose): a patient reading "no biomarkers" should not think something
// went wrong with their tumour or with the upload.

import Icon from "@/components/Icon";
import type { CancerDiagnosis } from "@/lib/api";

interface Props {
  diagnosis: CancerDiagnosis | null;
}

/** True when we extracted nothing at all — a different problem to explain. */
function isEmptyDiagnosis(d: CancerDiagnosis | null): boolean {
  if (!d) return true;
  return !(d.primary_site || d.histology || d.stage || d.tnm || d.grade);
}

export default function NoBiomarkersNotice({ diagnosis }: Props) {
  if (isEmptyDiagnosis(diagnosis)) return <UnreadableNotice />;

  return (
    <section className="bg-white rounded-xl border border-slate-200 p-6">
      <div className="flex items-start gap-3">
        <span className="shrink-0 grid place-items-center w-9 h-9 rounded-lg bg-slate-100 text-slate-500">
          <Icon name="file" size={19} />
        </span>
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-slate-800">
            No biomarker results in this document
          </h2>
          <p className="text-sm text-slate-500 mt-0.5">
            This reads like a pathology report, which describes the tumour
            itself — its type, size, grade and margins.
          </p>
        </div>
      </div>

      <div className="mt-5 space-y-4 text-sm text-slate-600 leading-relaxed">
        <p>
          Biomarker and genomic testing is normally reported{" "}
          <strong className="text-slate-800">separately</strong>. It is a
          different test run on the same tissue, and the results come back as
          their own document — often titled{" "}
          <em>Molecular Pathology</em>, <em>Next-Generation Sequencing</em>, or{" "}
          <em>Comprehensive Genomic Profiling</em>, or named after the
          laboratory that performed it.
        </p>

        <div className="rounded-lg bg-teal-50 border border-teal-100 p-4">
          <p className="font-medium text-teal-900">
            If you have that second report, upload it here.
          </p>
          <p className="text-teal-800 mt-1">
            That is the document biomarkers, targeted therapy options and
            biomarker-matched trials are drawn from.
          </p>
        </div>

        <div>
          <p className="font-medium text-slate-800">
            If you don&apos;t have one, this is worth raising at your next
            appointment:
          </p>
          <blockquote className="mt-2 border-l-2 border-slate-300 pl-4 italic text-slate-700">
            &ldquo;Has my tumour had biomarker or genomic testing? Would the
            results change my treatment options?&rdquo;
          </blockquote>
          <p className="mt-2 text-slate-500">
            Genomic testing is not appropriate for every cancer type or stage.
            Your oncology team can say whether it applies in your situation.
          </p>
        </div>
      </div>
    </section>
  );
}

/** Nothing extracted at all — likely a scan quality or wrong-file problem. */
function UnreadableNotice() {
  return (
    <section className="bg-white rounded-xl border border-slate-200 p-6">
      <div className="flex items-start gap-3">
        <span className="shrink-0 grid place-items-center w-9 h-9 rounded-lg bg-amber-50 text-amber-600">
          <Icon name="alert" size={19} />
        </span>
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-slate-800">
            We couldn&apos;t read much from this document
          </h2>
          <p className="text-sm text-slate-500 mt-0.5">
            No diagnosis or biomarker details were found.
          </p>
        </div>
      </div>

      <ul className="mt-5 space-y-2 text-sm text-slate-600 leading-relaxed">
        <li>
          <strong className="text-slate-800">Scan quality</strong> — faint or
          skewed scans are hard to read. A clearer photo or a straighter scan
          often works.
        </li>
        <li>
          <strong className="text-slate-800">Document type</strong> — billing
          statements, appointment letters and imaging orders don&apos;t contain
          the clinical detail this looks for.
        </li>
        <li>
          <strong className="text-slate-800">Try pasting the text</strong> — if
          you can select and copy text from the PDF, pasting it directly avoids
          the scanning step entirely.
        </li>
      </ul>
    </section>
  );
}
