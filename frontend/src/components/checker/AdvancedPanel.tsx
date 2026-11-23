"use client";

import { ChangeEvent, DragEvent, FormEvent, useRef, useState } from "react";

import { DownloadIcon, FileIcon, UploadIcon } from "@/components/ui/Icons";
import { api } from "@/lib/api";
import type { BatchResponse, ModelOption } from "@/types/api";


type Props = {
  model: string;
  quality: string;
  models: ModelOption[];
  onModelChange: (model: string) => void;
  onQualityChange: (quality: string) => void;
  onComplete: () => void;
};

export function AdvancedPanel({
  model,
  quality,
  models,
  onModelChange,
  onQualityChange,
  onComplete,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [generate, setGenerate] = useState(false);
  const [context, setContext] = useState("");
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [response, setResponse] = useState<BatchResponse | null>(null);

  const chooseFile = (candidate?: File) => {
    if (!candidate) return;
    if (!/\.(xlsx|xls|csv)$/i.test(candidate.name)) {
      setError("Choose an .xlsx, .xls, or .csv file.");
      return;
    }
    setError("");
    setResponse(null);
    setFile(candidate);
  };

  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files[0]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file || loading) return;
    setLoading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("model", model);
      form.append("quality", quality);
      form.append("generate_missing", String(generate));
      form.append("context", context);
      const result = await api.batch(form);
      setResponse(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The batch could not be processed.");
    } finally {
      setLoading(false);
      onComplete();
    }
  };

  const partial = response?.outcome === "partial";

  const previewColumns = response
    ? ["name", "email", "result", "verifalia_status", "verdict"].filter((column) =>
        response.columns.includes(column),
      )
    : [];

  return (
    <div className="work-view with-results">
      <section className="hero">
        <p>Upload a spreadsheet and download the results.</p>
      </section>

      <form className="batch-card" onSubmit={submit}>
        <div
          className={`dropzone ${dragging ? "dragging" : ""} ${file ? "has-file" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={drop}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => event.key === "Enter" && inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            hidden
            onChange={(event: ChangeEvent<HTMLInputElement>) => chooseFile(event.target.files?.[0])}
          />
          <div className="drop-icon">{file ? <FileIcon size={25} /> : <UploadIcon size={25} />}</div>
          {file ? (
            <>
              <strong>{file.name}</strong>
              <span>{(file.size / 1024).toFixed(1)} KB · Click to replace</span>
            </>
          ) : (
            <>
              <strong>Drop your spreadsheet here</strong>
              <span>or click to browse · XLSX, XLS, CSV</span>
            </>
          )}
        </div>

        <div className="batch-options">
          <label className="switch-row">
            <span>
              <strong>Find missing emails</strong>
              <small>Use the name column when email is empty</small>
            </span>
            <input type="checkbox" checked={generate} onChange={(event) => setGenerate(event.target.checked)} />
            <span className="switch" aria-hidden="true" />
          </label>

          {generate && (
            <label className="context-field full">
              <span>Shared context <em>optional</em></span>
              <input
                value={context}
                onChange={(event) => setContext(event.target.value)}
                placeholder="e.g. European universities, Acme Corp…"
                maxLength={500}
              />
            </label>
          )}

          <div className="select-row">
            <label>
              <span>Lookup model</span>
              <select value={model} onChange={(event) => onModelChange(event.target.value)} disabled={!generate}>
                {models.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
              </select>
            </label>
            <label>
              <span>Verification depth</span>
              <select value={quality} onChange={(event) => onQualityChange(event.target.value)}>
                <option value="Standard">Standard</option>
                <option value="High">High</option>
                <option value="Extreme">Extreme</option>
              </select>
            </label>
          </div>
        </div>

        {error && <div className="error-banner" role="alert">{error}</div>}

        <button className="primary-button" type="submit" disabled={!file || loading}>
          {loading ? <><span className="spinner" /> Processing list…</> : <>Run batch verification <span>→</span></>}
        </button>
        <p className="privacy-note">Jobs continue in the background. Private results expire after 24 hours.</p>
        <p className="privacy-note">Re-uploading a file you downloaded here? Rows that already have a result are kept as they are and not checked again. Rows marked No email found or Not processed are checked again.</p>
      </form>

      {response && (
        <section className="batch-result">
          <div className="batch-result-head">
            <div>
              <span className="eyebrow">{partial ? "Partial" : "Complete"}</span>
              <h2>{response.summary.emails_checked} unique emails checked</h2>
            </div>
            <a className="download-button" href={api.downloadUrl(response.batch_id)} download={response.filename}>
              <DownloadIcon /> {partial ? "Download finished rows" : "Download Excel"}
            </a>
          </div>
          {partial && <div className="error-banner" role="status">{response.message}</div>}
          <div className="stat-grid">
            {Object.entries(response.summary.counts).map(([label, count]) => (
              <div className="stat" key={label}><strong>{count}</strong><span>{label}</span></div>
            ))}
          </div>
          {previewColumns.length > 0 && (
            <div className="table-shell">
              <table>
                <thead><tr>{previewColumns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead>
                <tbody>
                  {response.preview.slice(0, 8).map((row, index) => (
                    <tr key={index} className={verdictOf(row) === "rejected" ? "rejected" : undefined}>
                      {previewColumns.map((column) => (
                        <td key={column}>
                          {column === "verdict" ? <VerdictCell row={row} /> : String(row[column] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {response.summary.output_rows > 8 && <p className="preview-note">Showing 8 of {response.summary.output_rows} output rows</p>}
        </section>
      )}
    </div>
  );
}

function verdictOf(row: Record<string, unknown>) {
  return String(row.verdict ?? "").toLowerCase();
}

function VerdictCell({ row }: { row: Record<string, unknown> }) {
  const verdict = String(row.verdict ?? "");
  if (!verdict) return null;
  const reason = String(row.verdict_reason ?? "");
  return (
    <span className="verdict-line">
      <span className={`verdict-label ${verdict.toLowerCase()}`}>{verdict}</span>
      {reason && <span className="verdict-reason">{reason}</span>}
    </span>
  );
}
