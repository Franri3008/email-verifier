"use client";

import { useState } from "react";

import { AlertIcon, CheckIcon, CloseIcon, CopyIcon, QuestionIcon } from "@/components/ui/Icons";
import type { VerificationResult } from "@/types/api";


const TONES = {
  deliverable: CheckIcon,
  undeliverable: CloseIcon,
  risky: AlertIcon,
} as const;

const toneOf = (classification: string) => {
  const key = classification.toLowerCase();
  return key in TONES ? (key as keyof typeof TONES) : "unknown";
};

export function ResultCard({ result }: { result: VerificationResult }) {
  const tone = toneOf(result.classification);
  const Icon = tone === "unknown" ? QuestionIcon : TONES[tone];
  const [copied, setCopied] = useState(false);
  const verdict = result.verdict?.toLowerCase();

  const copy = () => {
    // ponytail: clipboard needs a secure context, so tell the user when it is unavailable.
    navigator.clipboard.writeText(result.email).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => setCopied(false),
    );
  };

  return (
    <article className={`result-card ${verdict === "rejected" ? "rejected" : ""}`}>
      <span className={`status-tab ${tone}`}>{result.result}</span>
      <div className={`result-mark ${tone}`}>
        <Icon size={19} />
      </div>
      <div className="result-main">
        <p className="result-email">
          {result.email}
          <button type="button" className="copy-button" onClick={copy}
            title={copied ? "Copied" : "Copy address"} aria-label={copied ? "Copied" : "Copy address"}>
            {copied ? <CheckIcon size={15} /> : <CopyIcon size={15} />}
          </button>
        </p>
        {result.verdict && (
          <p className="verdict-line">
            <span className={`verdict-label ${verdict}`}>{result.verdict}</span>
            {result.verdict_reason && <span className="verdict-reason">{result.verdict_reason}</span>}
          </p>
        )}
        <p className="result-detail">{result.status.replace(/([a-z])([A-Z])/g, "$1 $2")}</p>

        <div className="result-meta">
          <span>{result.classification}</span>
          {result.candidate_confidence && <span>{result.candidate_confidence} confidence</span>}
          {result.is_role_account && <span>Role account</span>}
          {result.is_disposable && <span>Disposable</span>}
          {result.is_free_address && <span>Free provider</span>}
        </div>

        {result.candidate_rationale && <p className="result-rationale">{result.candidate_rationale}</p>}
        {result.candidate_source_url && (
          <a
            className="source-link"
            href={result.candidate_source_url}
            target="_blank"
            rel="noreferrer"
          >
            View public source <span aria-hidden="true">↗</span>
          </a>
        )}
        {result.suggestions.length > 0 && (
          <p className="suggestions">Suggested: {result.suggestions.join(", ")}</p>
        )}
      </div>
    </article>
  );
}
