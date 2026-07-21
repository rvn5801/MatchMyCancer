"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { healthCheck } from "@/lib/api";
import FileUpload from "@/components/FileUpload";
import { StreamingResults } from "@/components/ResultsDisplay";
import Icon from "@/components/Icon";

type AppState =
  | { phase: "loading" }
  | { phase: "ready" }
  | { phase: "analyzing"; text: string }
  | { phase: "error"; message: string };

export default function Home() {
  const [state, setState] = useState<AppState>({ phase: "loading" });
  const [version, setVersion] = useState<string>("?");
  const [connected, setConnected] = useState(false);
  const [hasConsent, setHasConsent] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  // Consent hydration + redirect
  useEffect(() => {
    const stored = sessionStorage.getItem("matchmycancer_consent_v1");
    setHasConsent(stored === "true");
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated && !hasConsent && pathname !== "/consent") {
      router.replace("/consent");
    }
  }, [hydrated, hasConsent, pathname, router]);

  // Check backend on mount
  useEffect(() => {
    healthCheck()
      .then((data) => {
        setVersion(data.version);
        setConnected(true);
        setState({ phase: "ready" });
      })
      .catch(() => {
        setConnected(false);
        setState({
          phase: "error",
          message:
            "Cannot connect to the backend. Make sure the server is running on port 8000.",
        });
      });
  }, []);

  const handleAnalyze = useCallback((text: string) => {
    setState({ phase: "analyzing", text });
  }, []);

  const handleReset = useCallback(() => setState({ phase: "ready" }), []);

  return (
    <main className="min-h-screen bg-slate-50 text-slate-800 flex flex-col">
      {/* ── Header ──────────────────────────────────────────────── */}
      <header className="border-b border-slate-200 bg-white/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-6 py-3.5 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="grid place-items-center w-9 h-9 rounded-lg bg-teal-600 text-white">
              <Icon name="activity" size={20} />
            </span>
            <div>
              <h1 className="text-lg font-semibold tracking-tight text-slate-800 leading-none">
                MatchMyCancer<span className="text-teal-600">.ai</span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                AI oncology report analysis
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                connected ? "bg-teal-500" : "bg-rose-500"
              }`}
            />
            <span className="text-xs text-slate-400">
              {connected ? `API v${version}` : "Disconnected"}
            </span>
          </div>
        </div>
      </header>

      {/* ── Body ────────────────────────────────────────────────── */}
      <div className="flex-1 w-full max-w-5xl mx-auto px-6 py-12">
        {state.phase === "loading" && <LoadingSkeleton />}

        {state.phase === "ready" && (
          <>
            <div className="text-center mb-10 max-w-xl mx-auto">
              <h2 className="text-3xl font-semibold tracking-tight text-slate-800 mb-3">
                Understand your oncology report
              </h2>
              <p className="text-slate-500 leading-relaxed">
                Upload a pathology or genomics report. We extract biomarkers,
                explain them in plain language, and match FDA-approved therapies
                and clinical trials.
              </p>
            </div>
            <FileUpload onTextReady={handleAnalyze} isAnalyzing={false} />
          </>
        )}

        {state.phase === "analyzing" && (
          <StreamingResults documentText={state.text} onReset={handleReset} />
        )}

        {state.phase === "error" && (
          <div className="text-center max-w-md mx-auto">
            <div className="inline-flex items-start gap-3 bg-rose-50 border border-rose-200 rounded-xl px-5 py-4 text-rose-700 text-left">
              <Icon name="alert" size={22} className="shrink-0 mt-0.5" />
              <span>{state.message}</span>
            </div>
            <button
              onClick={handleReset}
              className="block mx-auto mt-4 text-sm font-medium text-teal-600 hover:text-teal-700"
            >
              Try again
            </button>
          </div>
        )}
      </div>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <footer className="border-t border-slate-200 py-5">
        <p className="text-center text-xs text-slate-400">
          For educational purposes only. Always discuss results with your
          oncology team.
        </p>
      </footer>
    </main>
  );
}

function LoadingSkeleton() {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4">
      <div className="w-8 h-8 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
      <p className="text-slate-400 text-sm">Connecting to backend…</p>
    </div>
  );
}
