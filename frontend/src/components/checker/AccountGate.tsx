"use client";

import { FormEvent, ReactNode, useEffect, useState } from "react";
import { Account, Job, api, jsonFetch } from "@/lib/api";
import { JobsIcon, PeopleIcon, SettingsIcon, SignOutIcon } from "@/components/ui/Icons";
import { ResultCard } from "./ResultCard";

const PANELS = [
  { id: "jobs", label: "Jobs", Icon: JobsIcon, admin: false },
  { id: "settings", label: "Settings", Icon: SettingsIcon, admin: false },
  { id: "people", label: "People", Icon: PeopleIcon, admin: true },
];

const GROUPS = [
  { name: "OpenRouter", fields: [["openrouter_api_key", "API key"]] },
  { name: "Verifalia", fields: [
    ["verifalia_username", "Username"],
    ["verifalia_password", "Password"],
    ["verifalia_bearer_token", "Bearer token — optional alternative"],
  ] },
] as const;

export function AccountGate({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [ready, setReady] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [kind, setKind] = useState("invite");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [panel, setPanel] = useState("");
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [users, setUsers] = useState<Account[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [link, setLink] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<Job | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    if (params.has("token")) {
      setToken(params.get("token") || ""); setEmail(params.get("email") || "");
      setKind(params.get("kind") || "invite");
      window.history.replaceState(null, "", window.location.pathname);
    }
    jsonFetch<Account>("/api/account").then(setAccount).catch(() => {}).finally(() => setReady(true));
  }, []);

  async function refreshPanel() {
    if (panel === "settings") setSaved(await jsonFetch("/api/credentials"));
    if (panel === "people") setUsers(await jsonFetch("/api/admin/users"));
    if (panel === "jobs") setJobs(await jsonFetch("/api/jobs"));
  }

  useEffect(() => {
    if (!account || !panel) return;
    let active = true;
    const refresh = () => refreshPanel().catch((e) => active && setError(e.message));
    void refresh();
    const timer = panel === "jobs" ? setInterval(refresh, 3000) : undefined;
    return () => { active = false; clearInterval(timer); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panel, account]);

  async function action(fn: () => Promise<void>) {
    setError(""); setBusy(true);
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "Request failed."); }
    finally { setBusy(false); }
  }

  function login(event: FormEvent) {
    event.preventDefault();
    void action(async () => {
      setAccount(await jsonFetch<Account>(token ? "/api/auth/accept" : "/api/auth/login", {
        method: "POST", body: JSON.stringify({ email, password, ...(token ? { token } : {}) }),
      }));
      setToken(""); setPassword("");
    });
  }

  if (!ready) return <div className="account-screen">Loading…</div>;
  if (!account) return <div className="account-screen"><form className="account-card" onSubmit={login}>
    <h1>{token ? kind === "reset" ? "Reset password" : "Create account" : "Sign in"}</h1>
    <label>Email<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
    <label>Password<input type="password" autoComplete={token ? "new-password" : "current-password"} minLength={token ? 12 : 1} maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
    {error && <p className="error-banner" role="alert">{error}</p>}
    <button className="primary-button" disabled={busy}>{busy ? "Please wait…" : token ? "Save and sign in" : "Sign in"}</button>
    <p>Access is by invitation.</p>
  </form></div>;

  return <>
    <div className="account-toolbar">
      <span className="account-who"><small>Logged in as</small><b title={account.email}>{account.email}</b></span>
      {PANELS.filter((entry) => account.admin || !entry.admin).map(({ id, label, Icon }) =>
        <button key={id} className="icon-button" title={label} aria-label={label}
          onClick={() => { setPanel(id); setError(""); setSelected(null); }}><Icon /></button>)}
      <button className="icon-button" title="Sign out" aria-label="Sign out"
        onClick={() => void action(async () => { await jsonFetch("/api/auth/logout", { method: "POST" }); window.location.reload(); })}><SignOutIcon /></button>
    </div>
    {children}
    {panel && <div className="account-overlay"><section className="account-card account-dialog" role="dialog" aria-modal="true" aria-label={panel}>
      <div className="dialog-heading"><h2>{panel === "settings" ? "Your credentials" : panel === "people" ? "Access" : "Your jobs"}</h2><button onClick={() => { setPanel(""); setCredentials({}); setLink(""); }}>Close</button></div>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {panel === "settings" && <form onSubmit={(e) => { e.preventDefault(); void action(async () => {
        const values = Object.fromEntries(Object.entries(credentials).filter(([, v]) => v.trim()));
        await jsonFetch("/api/credentials", { method: "PUT", body: JSON.stringify(values) });
        setCredentials({}); await refreshPanel(); window.dispatchEvent(new Event("credentials-changed"));
      }); }}>
        <p>Requests use your provider accounts and credits. Blank fields keep existing values.</p>
        {GROUPS.map((group) => <fieldset className="cred-group" key={group.name}>
          <legend>{group.name}</legend>
          {group.fields.map(([key, label]) => <label key={key}>{label}
            <span className="cred-input">
              <input type="password" autoComplete="off" placeholder={saved[key] ? "set" : ""} value={credentials[key] || ""} onChange={(e) => setCredentials({ ...credentials, [key]: e.target.value })} />
              {saved[key] && <button type="button" disabled={busy} onClick={() => void action(async () => { await jsonFetch("/api/credentials", { method: "PUT", body: JSON.stringify({ [key]: null }) }); await refreshPanel(); window.dispatchEvent(new Event("credentials-changed")); })}>Remove</button>}
            </span>
          </label>)}
        </fieldset>)}
        <button className="primary-button" disabled={busy}>Save credentials</button>
      </form>}
      {panel === "people" && <>
        <label>Email<input type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} /></label>
        <div className="account-actions">{["invite", "reset"].map((type) => <button key={type} disabled={busy} onClick={() => void action(async () => {
          const result = await jsonFetch<{url: string}>("/api/admin/invites", { method: "POST", body: JSON.stringify({ email: inviteEmail, kind: type }) }); setLink(result.url);
        })}>{type === "invite" ? "Create invitation" : "Create password reset"}</button>)}
        <button disabled={busy} onClick={() => void action(async () => { await jsonFetch("/api/admin/invites", { method: "DELETE", body: JSON.stringify({ email: inviteEmail }) }); setLink(""); })}>Revoke link</button></div>
        {link && <label>Share this single-use link privately. Expires in 48 hours.<input readOnly value={link} onFocus={(e) => e.target.select()} /></label>}
        {users.map((user) => <div className="account-row" key={user.id}><span>{user.email} {user.admin ? "(admin)" : user.active ? "" : "(disabled)"}</span>
          {!user.admin && <button disabled={busy} onClick={() => void action(async () => { await jsonFetch(`/api/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify({ active: !user.active }) }); await refreshPanel(); })}>{user.active ? "Disable" : "Enable"}</button>}
        </div>)}
      </>}
      {panel === "jobs" && <>
        <p>Jobs continue when you close this page. Results expire after 24 hours.</p>
        {jobs.length === 0 && <p>No jobs yet.</p>}
        {jobs.map((job) => <div className="account-row" key={job.id}><span>{job.filename || "Single check"}<small>{new Date(job.created * 1000).toLocaleString()} · {job.status}</small></span>
          <button onClick={() => void action(async () => setSelected(await jsonFetch<Job>(`/api/jobs/${job.id}`)))}>View</button>
          {job.status !== "running" && <button disabled={busy} onClick={() => void action(async () => { await jsonFetch(`/api/jobs/${job.id}`, { method: "DELETE" }); if (selected?.id === job.id) setSelected(null); await refreshPanel(); })}>Delete</button>}
        </div>)}
        {selected && <div className="job-detail"><h3>{selected.status}</h3>{selected.error && <p>{selected.error}</p>}
          {selected.result && "results" in selected.result && <><p>{selected.result.query}</p>{selected.result.results.map((r) => <ResultCard key={r.email} result={r} />)}{selected.result.results.length === 0 && <p>No supported email found.</p>}</>}
          {selected.result && "summary" in selected.result && <><p>{selected.result.summary.emails_checked} emails checked</p><a className="download-button" href={api.downloadUrl(selected.id)}>Download Excel</a></>}
        </div>}
      </>}
    </section></div>}
  </>;
}
