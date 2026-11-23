export type Mode = "simple" | "advanced";

export type ModelOption = {
  id: string;
  label: string;
  note: string;
};

export type Health = {
  status: string;
  openrouter_configured: boolean;
  verifalia_configured: boolean;
};

export type VerificationResult = {
  email: string;
  result: string;
  classification: string;
  status: string;
  normalized_email: string | null;
  is_disposable: boolean | null;
  is_role_account: boolean | null;
  is_free_address: boolean | null;
  suggestions: string[];
  candidate_confidence: string | null;
  candidate_source_url: string | null;
  candidate_rationale: string | null;
  verdict?: string | null;
  verdict_reason?: string | null;
};

export type SimpleResponse = {
  query: string;
  lookup_used: boolean;
  model: string | null;
  results: VerificationResult[];
};

export type BatchResponse = {
  batch_id: string;
  filename: string;
  preview: Array<Record<string, unknown>>;
  columns: string[];
  summary: {
    total_rows: number;
    output_rows: number;
    emails_checked: number;
    generated_candidates: number;
    counts: Record<string, number>;
  };
  outcome?: "complete" | "partial";
  message?: string;
  unprocessed_rows?: number[];
};

export type Usage = {
  verifalia: {
    credit_packs: number;
    free_credits: number;
    available: number;
    used_today: number;
  } | null;
  openrouter: { total: number; used: number; remaining: number } | null;
};
