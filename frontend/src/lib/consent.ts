"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";

const CONSENT_KEY = "matchmycancer_consent_v1";

export function useConsent() {
  const [hasConsent, setHasConsent] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const stored = sessionStorage.getItem(CONSENT_KEY);
    setHasConsent(stored === "true");
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated && !hasConsent && pathname !== "/consent") {
      router.replace("/consent");
    }
  }, [hydrated, hasConsent, pathname, router]);

  const giveConsent = () => {
    sessionStorage.setItem(CONSENT_KEY, "true");
    setHasConsent(true);
    router.push("/");
  };

  return { hasConsent: hydrated && hasConsent, giveConsent, hydrated };
}