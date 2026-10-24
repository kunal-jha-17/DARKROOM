// GET /live-news  (served by the frontend server on :3000, no backend involved)
// Pulls Google News India (hl=en-IN, gl=IN) for dark patterns / hidden charges / consumer pricing,
// keeps only Indian publishers, removes duplicates and returns plain JSON for the What's on page.
import { NEWS_QUERIES, fetchQuery, isIndian } from "../../lib/news.js";

export const dynamic = "force-dynamic";
export const revalidate = 0;

let cache = { at: 0, body: null };

export async function GET(request) {
  const fresh = new URL(request.url).searchParams.get("fresh") === "1";
  if (!fresh && cache.body && Date.now() - cache.at < 120000) {
    return Response.json(cache.body, { headers: { "Cache-Control": "no-store" } });
  }
  const results = await Promise.allSettled(NEWS_QUERIES.map(fetchQuery));
  const errors = results.filter((r) => r.status === "rejected").map((r) => String(r.reason && r.reason.message || r.reason));
  const seen = new Set();
  const items = [];
  for (const r of results) {
    if (r.status !== "fulfilled") continue;
    for (const it of r.value) {
      if (!isIndian(it.host)) continue;
      const key = it.link || it.title;
      if (seen.has(key)) continue;
      seen.add(key);
      items.push(it);
    }
  }
  if (!items.length && errors.length === NEWS_QUERIES.length) {
    return Response.json({ error: errors[0], errors }, { status: 502, headers: { "Cache-Control": "no-store" } });
  }
  items.sort((a, b) => b.t - a.t);
  const body = { fetched_at: new Date().toISOString(), edition: "Google News India (en-IN)", count: items.length, items, errors };
  cache = { at: Date.now(), body };
  return Response.json(body, { headers: { "Cache-Control": "no-store" } });
}
