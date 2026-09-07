import type {
  BatchResponse,
  Health,
  ModelOption,
  SimpleResponse,
  Usage,
} from "@/types/api";


const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

async function parseError(response: Response): Promise<never> {
  let message = `Request failed (${response.status})`;
  try {
    const body = (await response.json()) as { detail?: string | Array<{ msg: string }> };
    if (typeof body.detail === "string") message = body.detail;
    if (Array.isArray(body.detail)) message = body.detail.map((item) => item.msg).join(" · ");
  } catch {
    // Preserve the status-based fallback when the server does not return JSON.
  }
  throw new Error(message);
}

export async function jsonFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    cache: "no-store",
    credentials: "include",
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "email-checker",
      ...options?.headers,
    },
  });
  if (!response.ok) return parseError(response);
  return response.json() as Promise<T>;
}

export const api = {
  health: () => jsonFetch<Health>("/api/configuration"),
  models: () => jsonFetch<ModelOption[]>("/api/models"),
  usage: () => jsonFetch<Usage>("/api/usage"),
  check: (body: { query: string; context: string; model: string; quality: string }) =>
    jsonFetch<Job>("/api/check", {
      method: "POST",
      body: JSON.stringify(body),
    }).then((job) => waitForJob<SimpleResponse>(job.id)),
  batch: async (form: FormData) => {
    const response = await fetch(`${BASE_URL}/api/batch`, {
      method: "POST",
      body: form,
      credentials: "include",
      headers: { "X-Requested-With": "email-checker" },
    });
    if (!response.ok) return parseError(response);
    const job = await response.json() as Job;
    return waitForJob<BatchResponse>(job.id);
  },
  downloadUrl: (batchId: string) => `${BASE_URL}/api/batch/${batchId}/download`,
};

export type Account = { id: string; email: string; admin: boolean; active: boolean };
export type Job = { id: string; kind: string; status: string; filename: string; created: number; expires: number; error: string | null; result: SimpleResponse | BatchResponse | null };

async function waitForJob<T>(id: string): Promise<T> {
  window.dispatchEvent(new Event("jobs-changed"));
  for (let attempt = 0; attempt < 1000; attempt++) {
    const job = await jsonFetch<Job>(`/api/jobs/${id}`);
    if (job.status === "completed") return job.result as T;
    if (!["queued", "running"].includes(job.status)) throw new Error(job.error || `Job ${job.status}.`);
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("The job is still processing. Open Jobs to follow its progress.");
}
