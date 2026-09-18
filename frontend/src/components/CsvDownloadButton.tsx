import { useState } from "react";
import { downloadApi } from "../api/client";

type CsvDownloadButtonProps = {
  path: string;
  label?: string;
  disabled?: boolean;
};

export function CsvDownloadButton({
  path,
  label = "Export CSV",
  disabled = false,
}: CsvDownloadButtonProps) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");

  async function download() {
    setDownloading(true);
    setError("");
    try {
      await downloadApi(path);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create the export");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <span className="csv-export-control">
      <button
        className="secondary csv-export-button"
        type="button"
        disabled={disabled || downloading}
        onClick={download}
      >
        {downloading ? "Preparing…" : label}
      </button>
      {error && <small className="csv-export-error" role="alert">{error}</small>}
    </span>
  );
}
