"use client";

import { FormEvent, KeyboardEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import { AdvancedPanel } from "@/components/checker/AdvancedPanel";
import { AccountGate } from "@/components/checker/AccountGate";
import { ResultCard } from "@/components/checker/ResultCard";
import {
  CheckIcon,
  ChevronIcon,
  MoonIcon,
  OpenRouterMark,
  SendIcon,
  SunIcon,
} from "@/components/ui/Icons";
import { api } from "@/lib/api";
import type { Health, Mode, ModelOption, SimpleResponse, Usage } from "@/types/api";


const FALLBACK_MODELS: ModelOption[] = [
  { id: "openai/gpt-6-luna", label: "GPT-6 Luna", note: "Fastest — best for batches" },
  { id: "openai/gpt-5.6-terra", label: "GPT-5.6 Terra", note: "Balanced research" },
  { id: "anthropic/claude-haiku-5.5", label: "Claude Haiku 5.5", note: "Fast and cheap Claude" },
  { id: "anthropic/claude-sonnet-5.5", label: "Claude Sonnet 5.5", note: "Strong web synthesis" },
  { id: "anthropic/claude-opus-5.5", label: "Claude Opus 5.5", note: "Highest quality, slower" },
];

const credits = (value: number) =>
  value.toLocaleString(undefined, { maximumFractionDigits: value < 10 ? 2 : 0 });
const money = (value: number) => `$${value.toFixed(2)}`;

export default function Home() {
  return <AccountGate><Checker /></AccountGate>;
}

function Checker() {
  const [mode, setMode] = useState<Mode>("simple");
  const [dark, setDark] = useState(true);
  const [query, setQuery] = useState("");
  const [context, setContext] = useState("");
  const [showContext, setShowContext] = useState(false);
  const [model, setModel] = useState(FALLBACK_MODELS[0].id);
  const [models, setModels] = useState(FALLBACK_MODELS);
  const [quality, setQuality] = useState("Standard");
  const [modelOpen, setModelOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [response, setResponse] = useState<SimpleResponse | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);

  const refreshUsage = useCallback(() => {
    api.usage().then(setUsage).catch(() => setUsage(null));
  }, []);

  useEffect(() => {
    const savedTheme = window.localStorage.getItem("email-checker-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    setDark(savedTheme ? savedTheme === "dark" : prefersDark);
    const refresh = () => {
      refreshUsage();
      return Promise.all([api.health(), api.models()])
        .then(([healthResult, modelResult]) => {
          setHealth(healthResult);
          setModels(modelResult);
        })
        .catch(() => setHealth(null));
    };
    void refresh();
    window.addEventListener("credentials-changed", refresh);
    return () => window.removeEventListener("credentials-changed", refresh);
  }, [refreshUsage]);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    window.localStorage.setItem("email-checker-theme", dark ? "dark" : "light");
  }, [dark]);

  const activeModel = useMemo(
    () => models.find((option) => option.id === model) ?? models[0],
    [model, models],
  );

  const runCheck = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!query.trim() || loading) return;
    setLoading(true);
    setError("");
    setResponse(null);
    try {
      const result = await api.check({ query: query.trim(), context, model, quality });
      setResponse(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The check could not be completed.");
    } finally {
      setLoading(false);
      refreshUsage();
    }
  };

  const handleComposerKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void runCheck();
    }
  };

  const changeMode = (nextMode: Mode) => {
    setMode(nextMode);
    setError("");
    setModelOpen(false);
  };

  return (
    <div className="app-shell">
      <main className="main-panel">
        <header className="topbar">
          <div className="mode-tabs" role="tablist" aria-label="Check mode">
            <button role="tab" aria-selected={mode === "simple"} className={mode === "simple" ? "active" : ""} onClick={() => changeMode("simple")}>Simple</button>
            <button role="tab" aria-selected={mode === "advanced"} className={mode === "advanced" ? "active" : ""} onClick={() => changeMode("advanced")}>Advanced</button>
          </div>

          <UsagePanel usage={usage} health={health} />

          <div className="topbar-right">
            <button className="icon-button" onClick={() => setDark((value) => !value)} aria-label={`Use ${dark ? "light" : "dark"} theme`}>
              {dark ? <SunIcon /> : <MoonIcon />}
            </button>
          </div>
        </header>

        {mode === "simple" ? (
          <div className={`work-view ${response || error || loading ? "with-results" : ""}`}>
            <section className="hero">
              <h1>Email checker</h1>
            </section>

            {(response || error || loading) && (
              <section className="conversation" aria-live="polite">
                <div className="query-bubble">{response?.query || query}</div>
                <div className="answer-block">
                  <div className="answer-content">
                    {loading && (
                      <div className="thinking">
                        <span className="spinner" />
                        <div><strong>Job submitted…</strong><small>You can follow its progress in Jobs, including after a refresh.</small></div>
                      </div>
                    )}
                    {error && <div className="error-banner" role="alert">{error}</div>}
                    {response && response.results.length === 0 && (
                      <div className="empty-answer"><strong>No supported email candidates found.</strong><span>Add an institution, company, country, or domain in search context and try again.</span></div>
                    )}
                    {response && response.results.length > 0 && (
                      <>
                        <div className="answer-summary">
                          <strong>{response.results.length} {response.results.length === 1 ? "address" : "addresses"} checked</strong>
                          <span>{response.lookup_used ? "Each candidate was checked separately." : "The supplied address was checked directly."}</span>
                        </div>
                        <div className="result-list">
                          {response.results.map((result) => <ResultCard key={result.email} result={result} />)}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </section>
            )}

            <form className="composer" onSubmit={runCheck}>
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={handleComposerKey}
                placeholder="Enter a person, role, or email address…"
                rows={1}
                maxLength={300}
                aria-label="Person or email to verify"
              />
              {showContext && (
                <div className="inline-context">
                  <label htmlFor="context">Context</label>
                  <input
                    id="context"
                    value={context}
                    onChange={(event) => setContext(event.target.value)}
                    placeholder="Institution, company, country, or domain"
                    maxLength={500}
                  />
                </div>
              )}
              <div className="composer-footer">
                <button type="button" className={`context-button ${showContext ? "active" : ""}`} onClick={() => setShowContext((value) => !value)}>
                  ＋ <span>Context</span>
                </button>
                <div className="composer-actions">
                  <label className="field-pill depth-select">
                    <span className="pill-label">Depth</span>
                    <select value={quality} onChange={(event) => setQuality(event.target.value)} aria-label="Verification depth">
                      <option value="Standard">Standard</option>
                      <option value="High">High</option>
                      <option value="Extreme">Extreme</option>
                    </select>
                  </label>
                  <div className="model-picker">
                    <button type="button" className="field-pill" onClick={() => setModelOpen((value) => !value)} aria-expanded={modelOpen}>
                      <span className="pill-label">Model</span>
                      <span className="pill-value">{activeModel?.label ?? "Choose model"}</span>
                      <ChevronIcon size={14} />
                    </button>
                    {modelOpen && (
                      <div className="model-menu">
                        <span className="menu-label">Email discovery model</span>
                        {models.map((option) => (
                          <button key={option.id} type="button" className={model === option.id ? "selected" : ""} onClick={() => { setModel(option.id); setModelOpen(false); }}>
                            <span><strong>{option.label}</strong><small>{option.note}</small></span>
                            {model === option.id && <CheckIcon />}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <button className="send-button" type="submit" disabled={!query.trim() || loading} aria-label="Run check">
                    <SendIcon />
                  </button>
                </div>
              </div>
            </form>
          </div>
        ) : (
          <AdvancedPanel
            model={model}
            quality={quality}
            models={models}
            onModelChange={setModel}
            onQualityChange={setQuality}
            onComplete={refreshUsage}
          />
        )}
      </main>
      <span className="app-version">v{process.env.NEXT_PUBLIC_APP_VERSION}</span>
    </div>
  );
}

function UsagePanel({ usage, health }: { usage: Usage | null; health: Health | null }) {
  const verifalia = usage?.verifalia;
  const openrouter = usage?.openrouter;
  const verifaliaStart = verifalia ? verifalia.available + verifalia.used_today : 0;
  return (
    <div className="usage-panel" aria-label="Provider budget">
      <Meter
        name="Verifalia"
        mark={<img src="/verifalia-mark.png" alt="" width={14} height={14} />}
        value={verifalia ? `${credits(verifalia.available)} left` : undefined}
        note={verifalia ? `${credits(verifalia.used_today)} of ${credits(verifaliaStart)} credits used today` : undefined}
        ratio={verifalia && verifaliaStart > 0 ? verifalia.used_today / verifaliaStart : 0}
        configured={health?.verifalia_configured}
      />
      <Meter
        name="OpenRouter"
        mark={<OpenRouterMark />}
        value={openrouter ? `${money(openrouter.remaining)} left` : undefined}
        note={openrouter ? `${money(openrouter.used)} of ${money(openrouter.total)} used` : undefined}
        ratio={openrouter && openrouter.total > 0 ? openrouter.used / openrouter.total : 0}
        configured={health?.openrouter_configured}
      />
    </div>
  );
}

function Meter({
  name,
  mark,
  value,
  note,
  ratio,
  configured,
}: {
  name: string;
  mark: ReactNode;
  value?: string;
  note?: string;
  ratio: number;
  configured?: boolean;
}) {
  const percent = Math.min(100, Math.max(0, ratio * 100));
  const fallback = configured ? "Balance unavailable" : "No key saved";
  return (
    <div className={`meter ${percent >= 90 ? "critical" : percent >= 70 ? "warn" : ""}`}>
      <div className="meter-head">
        <span className={`provider-mark ${name.toLowerCase()}`}>{mark}</span>
        <span className="provider-name">{name}</span>
        <strong>{value ?? "—"}</strong>
      </div>
      <div className="meter-track" role="presentation">
        <span style={{ width: `${value ? percent : 0}%` }} />
      </div>
      <small>{note ?? fallback}</small>
    </div>
  );
}
