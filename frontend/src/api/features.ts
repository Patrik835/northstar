import { useEffect, useState } from "react";
import { api } from "./client";
import type { FeatureStatus } from "./types";

// Feature availability only changes when the server restarts, so fetch it once per page load.
let cached: Promise<FeatureStatus> | null = null;

export function loadFeatures(): Promise<FeatureStatus> {
  cached ??= api<FeatureStatus>("/dashboard/features").catch((reason: unknown) => {
    cached = null;
    throw reason;
  });
  return cached;
}

/** Optional features (AI, news, benchmarks); null while loading. */
export function useFeatures(): FeatureStatus | null {
  const [features, setFeatures] = useState<FeatureStatus | null>(null);
  useEffect(() => {
    let cancelled = false;
    loadFeatures()
      .then((value) => { if (!cancelled) setFeatures(value); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);
  return features;
}
