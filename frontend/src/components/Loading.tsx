/** Shown while a page waits for data, so a slow response doesn't look like a broken page. */
export function Loading({ label = "Loading…", className = "" }: { label?: string; className?: string }) {
  return (
    <div className={`loading-state ${className}`.trim()} role="status" aria-live="polite">
      <span className="loading-spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

/** A placeholder bar where a number will appear. */
export function Skeleton({ width = "6rem" }: { width?: string }) {
  return <span className="skeleton" style={{ width }} aria-hidden="true" />;
}
