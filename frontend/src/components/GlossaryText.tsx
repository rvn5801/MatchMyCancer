"use client";

// Renders prose with known medical terms tappable. Tapping a term shows its
// plain-language definition in a box directly below the paragraph, so the
// reader never loses their place (no modal, no tooltip — tooltips don't
// exist on touch screens, and patients are mostly on phones).

import { useState } from "react";
import { GLOSSARY_REGEX, lookup } from "@/lib/glossary";

export default function GlossaryText({
  text,
  className = "",
}: {
  text: string;
  className?: string;
}) {
  const [open, setOpen] = useState<string | null>(null);

  const parts = text.split(GLOSSARY_REGEX);
  // split with a capture group alternates [plain, term, plain, term, ...] —
  // odd indices are matched terms.
  const hasTerms = parts.length > 1;
  if (!hasTerms) return <p className={className}>{text}</p>;

  const definition = open ? lookup(open) : undefined;

  return (
    <div>
      <p className={className}>
        {parts.map((part, i) =>
          i % 2 === 1 ? (
            <button
              key={i}
              type="button"
              onClick={() =>
                setOpen(open === part.toLowerCase() ? null : part.toLowerCase())
              }
              className={`underline decoration-dotted underline-offset-2 rounded-sm ${
                open === part.toLowerCase()
                  ? "text-teal-700 decoration-teal-500 bg-teal-50"
                  : "text-inherit decoration-slate-400 hover:decoration-teal-500"
              }`}
              aria-expanded={open === part.toLowerCase()}
            >
              {part}
            </button>
          ) : (
            <span key={i}>{part}</span>
          )
        )}
      </p>
      {definition && (
        <div className="mt-2 rounded-lg bg-teal-50 border border-teal-100 px-3 py-2 text-sm text-teal-900">
          <span className="font-semibold capitalize">{open}</span>
          {" — "}
          {definition}
        </div>
      )}
    </div>
  );
}
