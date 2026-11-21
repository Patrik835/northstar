import { useState, type ChangeEvent } from "react";
import { api } from "../../api/client";
import type { ConnectionGuide, StatementDetection } from "../../api/types";
import { Loading } from "../../components/Loading";

/**
 * "Not sure which broker?" — read the chosen file, suggest its broker and import only after
 * the user confirms. Brokers with similar files are offered as alternatives, never guessed.
 */
export function StatementDetector({
  guides,
  onImport,
}: {
  guides: ConnectionGuide[];
  onImport: (guide: ConnectionGuide, form: FormData) => Promise<void>;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [detection, setDetection] = useState<StatementDetection | null>(null);
  const [status, setStatus] = useState<"idle" | "reading" | "importing">("idle");
  const [error, setError] = useState("");
  const [inputKey, setInputKey] = useState(0);

  const accept = [...new Set(guides.flatMap((guide) =>
    (guide.file_import?.accept ?? "").split(",").filter((item) => item.startsWith("."))))].join(",");

  function formFor(selected: File[]) {
    const form = new FormData();
    selected.forEach((file) => form.append("file", file));
    return form;
  }

  function reset() {
    setFiles([]);
    setDetection(null);
    setError("");
    setInputKey((key) => key + 1);
  }

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files ?? []).filter((file) => file.size > 0);
    setDetection(null);
    setError("");
    setFiles(selected);
    if (!selected.length) return;
    setStatus("reading");
    try {
      setDetection(await api<StatementDetection>("/connections/imports/detect", {
        method: "POST",
        body: formFor(selected),
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not read the file");
    } finally {
      setStatus("idle");
    }
  }

  async function importAs(guide: ConnectionGuide) {
    setStatus("importing");
    setError("");
    try {
      await onImport(guide, formFor(files));
      reset();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not import the file");
    } finally {
      setStatus("idle");
    }
  }

  const guideFor = (broker: string) => guides.find((guide) => guide.broker === broker);
  const suggested = detection?.suggested ? guideFor(detection.suggested) : undefined;
  const alternatives = (detection?.matches ?? [])
    .map((match) => guideFor(match.broker))
    .filter((guide): guide is ConnectionGuide => Boolean(guide) && guide !== suggested);
  const busy = status !== "idle";

  return (
    <div className="statement-detector">
      <label className="csv-dropzone statement-detector-drop">
        <span className="upload-mark">↑</span>
        <strong>{files.length ? files.map((file) => file.name).join(", ") : "Not sure which broker? Choose your statement file"}</strong>
        <small>We recognise the broker for you. Nothing is imported until you confirm.</small>
        <input key={inputKey} type="file" multiple accept={accept} onChange={(event) => void choose(event)} disabled={busy} />
      </label>

      {status === "reading" && <Loading label="Reading your file…" />}
      {status === "importing" && <Loading label="Importing…" />}

      {!busy && detection && (
        <div className="statement-detector-result" role="status">
          {suggested ? (
            <>
              <p>This looks like a <strong>{suggested.display_name}</strong> export.</p>
              <div className="button-row">
                <button type="button" className="primary" onClick={() => void importAs(suggested)}>
                  Import as {suggested.display_name}
                </button>
                <button type="button" className="text-button" onClick={reset}>Cancel</button>
              </div>
              {alternatives.length > 0 && (
                <p className="muted statement-detector-alternatives">
                  Not right? Import as{" "}
                  {alternatives.map((guide, index) => (
                    <span key={guide.broker}>
                      {index > 0 && " or "}
                      <button type="button" className="text-button" onClick={() => void importAs(guide)}>
                        {guide.display_name}
                      </button>
                    </span>
                  ))}
                </p>
              )}
            </>
          ) : alternatives.length ? (
            <>
              <p>Which broker is this file from?</p>
              <div className="button-row statement-detector-choices">
                {alternatives.map((guide) => (
                  <button type="button" className="secondary" key={guide.broker} onClick={() => void importAs(guide)}>
                    {guide.display_name}
                  </button>
                ))}
                <button type="button" className="text-button" onClick={reset}>Cancel</button>
              </div>
            </>
          ) : (
            <p>
              We couldn't recognise this file. Pick your broker below and follow its steps to
              download the right export.{" "}
              <button type="button" className="text-button" onClick={reset}>Choose another file</button>
            </p>
          )}
        </div>
      )}
      {error && <p className="connection-error" role="alert">{error}</p>}
    </div>
  );
}
