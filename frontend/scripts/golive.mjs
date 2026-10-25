// Packages your real findings + run videos into the frontend so it can be
// deployed on its own, with no backend.
//
// Run from frontend/ WITH THE BACKEND RUNNING:
//     node scripts/golive.mjs
//
// It writes:
//   public/data/snapshot.json   - findings + details + reports
//   public/media/*.webm         - the run recordings, copied locally
// and rewrites every video_ref to the local copy.

import { mkdir, writeFile } from "node:fs/promises";
import { createWriteStream } from "node:fs";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

const API = (process.env.API || "http://127.0.0.1:8000").replace(/\/$/, "");
const j = async (p) => {
  const r = await fetch(API + p);
  if (!r.ok) throw new Error(`${p} -> ${r.status}`);
  return r.json();
};

const findings = (await j("/api/findings")).findings || [];
if (!findings.length) {
  console.error("No findings in the backend. Run a probe first, then re-run this.");
  process.exit(1);
}

await mkdir("public/data", { recursive: true });
await mkdir("public/media", { recursive: true });

const details = {};
const reports = {};
let videos = 0;

for (const f of findings) {
  const id = f.finding_id;
  details[id] = await j("/api/findings/" + encodeURIComponent(id));

  // the enriched report: precedent, fix, harm at scale, benchmark
  try {
    reports[id] = await j("/api/findings/" + encodeURIComponent(id) + "/report");
  } catch {
    /* endpoint may not exist on an older backend - not fatal */
  }

  // pull the recording down so it survives without the backend
  const ref = f.evidence?.video_ref;
  if (ref && !/^https?:/.test(ref)) {
    const name = ref.split("/").pop();
    const local = `/media/${name}`;
    try {
      const res = await fetch(API + (ref.startsWith("/") ? "" : "/") + ref);
      if (res.ok && res.body) {
        await pipeline(Readable.fromWeb(res.body), createWriteStream(`public/media/${name}`));
        f.evidence.video_ref = local;
        if (details[id]?.finding?.evidence) details[id].finding.evidence.video_ref = local;
        if (reports[id]?.finding?.evidence) reports[id].finding.evidence.video_ref = local;
        videos++;
      }
    } catch (e) {
      console.warn(`  video for ${id} could not be copied: ${e.message}`);
    }
  }
}

await writeFile(
  "public/data/snapshot.json",
  JSON.stringify(
    {
      exported_at: new Date().toISOString(),
      source: API,
      count: findings.length,
      findings,
      details,
      reports,
    },
    null,
    2
  )
);

console.log(`Packaged ${findings.length} findings and ${videos} video(s).`);
console.log("Now commit public/data and public/media, then deploy.");
