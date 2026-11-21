import type { FormEvent } from "react";
import type { Broker, Connection, ConnectionGuide } from "../../api/types";
import { brokerLogo, brokerShortMark } from "../../domain/brokers";

export function SourceMark({
  broker,
  shortMark,
}: {
  broker: Broker;
  shortMark?: string;
}) {
  const logo = brokerLogo(broker);
  return (
    <span className={`compact-source-mark ${broker}`} aria-hidden="true">
      {logo ? <img src={logo} alt="" /> : (shortMark ?? brokerShortMark(broker))}
    </span>
  );
}

function SetupSteps({ guide, title, label }: { guide: ConnectionGuide; title: string; label?: string }) {
  return (
    <section className={`setup-guide${label ? " replacement-key-help" : ""}`} aria-label={label}>
      <h3>{title}</h3>
      <ol>
        {guide.setup_steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <a className="official-guide-link" href={guide.tutorial_url} target="_blank" rel="noreferrer">
        View the official guide <span>↗</span>
      </a>
    </section>
  );
}

/** Connect an API source, replace its credentials, or upload a statement file. */
export function SourceDialog({
  guide,
  reconnecting,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  guide: ConnectionGuide;
  reconnecting: Connection | null;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const isFile = guide.connection_type === "csv";
  const fileImport = guide.file_import;
  const submitLabel = busy
    ? isFile ? "Importing…" : reconnecting ? "Replacing…" : "Connecting…"
    : isFile ? "Import" : reconnecting ? "Save new key" : "Connect";

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form
        key={reconnecting ? `replace:${reconnecting.id}` : `connect:${guide.broker}`}
        className={`modal connection-modal${reconnecting ? " reconnect-modal" : ""}`}
        onSubmit={onSubmit}
        onMouseDown={(event) => event.stopPropagation()}
        noValidate={!isFile}
      >
        <div className="modal-source-heading">
          <SourceMark broker={guide.broker} shortMark={guide.short_mark} />
          <div>
            <p className="eyebrow">
              {isFile ? "Import a file" : reconnecting ? "Fix connection" : "Connect"}
            </p>
            <h2>{guide.display_name}</h2>
          </div>
        </div>
        {reconnecting ? (
          <p className="reconnect-note">
            Your current key stays active until the replacement is verified.
          </p>
        ) : (
          <div className="security-callout">{guide.security_notice}</div>
        )}
        {reconnecting ? (
          <SetupSteps
            guide={guide}
            title="How to create a new key"
            label="Replacement key instructions"
          />
        ) : (
          <SetupSteps guide={guide} title={isFile ? "How to get the file" : "How to get your key"} />
        )}

        {isFile && fileImport ? (
          <label className="csv-dropzone">
            <span className="upload-mark">↑</span>
            <strong>{fileImport.prompt}</strong>
            <small>{fileImport.help_text}</small>
            <input
              name="file"
              type="file"
              accept={fileImport.accept}
              multiple={fileImport.multiple}
              required
            />
          </label>
        ) : (
          <div className="credential-fields">
            <h3>{reconnecting ? "Paste the new key" : "Paste your key"}</h3>
            {guide.credential_fields.map((field) => (
              <label key={field}>
                {guide.credential_labels[field] ?? `${field.charAt(0).toUpperCase()}${field.slice(1).replaceAll("_", " ")}`}
                <input name={field} type="password" autoComplete="new-password" required />
              </label>
            ))}
          </div>
        )}

        {error && <p className="connection-error modal-error" role="alert">{error}</p>}

        <div className="button-row">
          <button type="button" className="text-button" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={busy}>
            {submitLabel}
          </button>
        </div>
      </form>
    </div>
  );
}
