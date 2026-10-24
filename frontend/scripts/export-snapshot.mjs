// Saves the backend's real answers to public/data/snapshot.json so the page can show
// them when the backend is not running. Nothing is edited or added: records are stored as returned.
// Run with the backend up:  npm run snapshot      (other address: API=http://HOST:PORT npm run snapshot)
import { mkdir, writeFile } from "node:fs/promises";
const API = (process.env.API || "http://127.0.0.1:8000").replace(/\/$/, "");
const j = async (p) => { const r = await fetch(API + p); if (!r.ok) throw new Error(p + " -> " + r.status); return r.json(); };
const findings = (await j("/api/findings")).findings || [];
const details = {};
for (const f of findings) details[f.finding_id] = await j("/api/findings/" + encodeURIComponent(f.finding_id));
await mkdir("public/data", { recursive: true });
await writeFile("public/data/snapshot.json", JSON.stringify({ exported_at: new Date().toISOString(), source: API, count: findings.length, findings, details }, null, 2));
console.log("Saved " + findings.length + " findings from " + API + " to public/data/snapshot.json");
