"use client";

import { useCallback, useRef, useState } from "react";
import Icon from "@/components/Icon";

interface FileUploadProps {
  onTextReady: (text: string) => void;
  isAnalyzing: boolean;
}

export default function FileUpload({ onTextReady, isAnalyzing }: FileUploadProps) {
  const [dragOver, setDragOver] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      setUploading(true);
      try {
        const formData = new FormData();
        formData.append("file", file);
        const { uploadDocument } = await import("@/lib/api");
        const result = await uploadDocument(formData);
        // Send the FULL extracted text to analyze (preview is display-only,
        // truncated to 3000 chars — never analyze on that).
        const text = result.extracted_text || result.extracted_preview || "";
        if (text) {
          onTextReady(text);
        } else {
          setError("No text could be extracted from this file.");
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setUploading(false);
      }
    },
    [onTextReady]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handlePasteSubmit = () => {
    const trimmed = pasteText.trim();
    if (!trimmed) return;
    setError(null);
    onTextReady(trimmed);
  };

  const isLoading = uploading || isAnalyzing;

  return (
    <div className="w-full max-w-2xl mx-auto">
      {/* ── Drag-and-drop zone ───────────────────────────────────── */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`
          rounded-2xl p-10 text-center cursor-pointer border-2 border-dashed
          transition-all duration-200
          ${
            dragOver
              ? "border-teal-500 bg-teal-50"
              : "border-slate-300 bg-white hover:border-teal-400 hover:bg-slate-50"
          }
          ${isLoading ? "pointer-events-none opacity-60" : ""}
        `}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.png,.tiff,.txt"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
        />
        {uploading ? (
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-slate-500">Extracting text from document…</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <span className="grid place-items-center w-14 h-14 rounded-xl bg-teal-50 text-teal-600">
              <Icon name="upload" size={28} />
            </span>
            <p className="text-lg font-medium text-slate-700">
              Drop your oncology report here
            </p>
            <p className="text-sm text-slate-400">
              PDF, JPEG, PNG, or TIFF — or click to browse
            </p>
          </div>
        )}
      </div>

      {/* ── Divider ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-4 my-6">
        <div className="flex-1 h-px bg-slate-200" />
        <span className="text-sm text-slate-400">or paste report text</span>
        <div className="flex-1 h-px bg-slate-200" />
      </div>

      {/* ── Paste text area ──────────────────────────────────────── */}
      <textarea
        value={pasteText}
        onChange={(e) => setPasteText(e.target.value)}
        placeholder="Paste your pathology or genomics report text here…&#10;&#10;Example: Lung adenocarcinoma Stage IV. EGFR exon 19 deletion detected by NGS. PD-L1 TPS 80%."
        rows={6}
        disabled={isLoading}
        className="w-full rounded-xl border border-slate-300 bg-white p-4 text-sm
                   focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent
                   disabled:opacity-50 resize-y placeholder:text-slate-400"
      />
      <button
        onClick={handlePasteSubmit}
        disabled={isLoading || !pasteText.trim()}
        className="mt-3 w-full inline-flex items-center justify-center gap-2 bg-teal-600 hover:bg-teal-700
                   disabled:bg-slate-300 text-white font-medium py-3 px-6 rounded-xl
                   transition-colors disabled:cursor-not-allowed"
      >
        Analyze report
        <Icon name="arrowRight" size={18} />
      </button>

      {/* ── Error display ────────────────────────────────────────── */}
      {error && (
        <div className="mt-4 flex items-start gap-2 p-3 bg-rose-50 border border-rose-200 rounded-lg text-sm text-rose-700">
          <Icon name="alert" size={18} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
