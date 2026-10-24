// Every fetch in the app goes through this file.
import type { Finding, JourneyState } from "./types";
import { SAMPLE_FINDINGS, SAMPLE_JOURNEY } from "./sample";

export const BASE = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000";
const FALLBACK = process.env.NEXT_PUBLIC_SAMPLE_FALLBACK === "1";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { cache: "no-store" }); // required, see Next.js caching
  if (!r.ok) throw new Error(`API ${r.status} on ${path}`);
  return r.json();
}

export async function getFindings(): Promise<{ findings: Finding[]; sample: boolean }> {
  try {
    const d = await get<{ findings: Finding[] }>("/api/findings");
    return { findings: d.findings, sample: false };
  } catch (e) {
    if (FALLBACK) return { findings: SAMPLE_FINDINGS, sample: true };
    throw e;
  }
}

export async function getFinding(id: string) {
  try {
    return await get<{ finding: Finding; journey_states: JourneyState[] }>(`/api/findings/${id}`);
  } catch (e) {
    const f = SAMPLE_FINDINGS.find((x) => x.finding_id === id);
    if (FALLBACK && f) {
      return { finding: f, journey_states: f.finding_id === "f_1184" ? [SAMPLE_JOURNEY] : [] };
    }
    throw e;
  }
}

export const getRun = (id: string) =>
  get<{ status: string; progress: string; finding_id?: string }>(`/api/runs/${id}`);

export async function startProbe(platform: string, entry_url: string) {
  const r = await fetch(`${BASE}/api/probes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ platform, entry_url }),
  });
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json() as Promise<{ run_id: string; status: string }>;
}

export const inr = (n: number) =>
  `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

// video_ref may be absolute or a path on the backend
export const mediaUrl = (ref: string) => (/^https?:/.test(ref) ? ref : `${BASE}${ref.startsWith("/") ? "" : "/"}${ref}`);
