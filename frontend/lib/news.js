// Server-side helpers for /live-news (kept out of route.js because Next only allows HTTP handlers there).
// Pulls Google News India (hl=en-IN, gl=IN) for dark patterns / hidden charges / consumer pricing,
// keeps only Indian publishers, removes duplicates and returns plain JSON for the What's on page.

const FEED = "https://news.google.com/rss/search";
const WINDOW = "when:30d";
const QUERIES = [
  `("dark patterns" OR "dark pattern") ${WINDOW}`,
  `("hidden charges" OR "convenience fee" OR "platform fee" OR "handling fee" OR "drip pricing" OR "surge pricing") (app OR booking OR delivery OR ecommerce OR cab OR flight) ${WINDOW}`,
  `(CCPA OR "Central Consumer Protection Authority") (penalty OR notice OR order OR guidelines OR advisory) ${WINDOW}`,
  `("e-commerce rules" OR "consumer protection") ("dark patterns" OR refund OR "hidden charges" OR subscription) India ${WINDOW}`,
];

// Indian publishers whose domain does not end in .in. Anything ending in .in is accepted automatically.
// The list is deliberately conservative: an unknown .com outlet is dropped rather than risk a non-Indian story.
const INDIAN_HOSTS = [
  "indiatimes.com", "timesofindia.com", "hindustantimes.com", "thehindu.com", "thehindubusinessline.com",
  "indianexpress.com", "financialexpress.com", "livemint.com", "ndtv.com", "ndtvprofit.com", "moneycontrol.com",
  "news18.com", "firstpost.com", "business-standard.com", "deccanherald.com", "deccanchronicle.com",
  "newindianexpress.com", "tribuneindia.com", "telegraphindia.com", "mid-day.com", "outlookindia.com",
  "dnaindia.com", "cnbctv18.com", "timesnownews.com", "republicworld.com", "abplive.com", "thequint.com",
  "medianama.com", "inc42.com", "yourstory.com", "entrackr.com", "barandbench.com", "etretail.com",
  "siasat.com", "devdiscourse.com", "ptinews.com", "uniindia.com", "zeebiz.com", "india.com", "newslaundry.com",
  "indiaspend.com", "livelaw.in", "thehansindia.com", "telanganatoday.com", "orissapost.com", "assamtribune.com",
  "jagran.com", "bhaskar.com", "amarujala.com", "livehindustan.com", "lokmat.com", "news9live.com",
  "tv9hindi.com", "asianetnews.com", "mathrubhumi.com", "onmanorama.com", "manoramaonline.com", "etvbharat.com",
  "greaterkashmir.com", "kashmirobserver.net", "theweek.in", "businesstoday.in", "aninews.in", "ianslive.in",
];

export function isIndian(host) {
  const h = String(host || "").toLowerCase().replace(/^www\./, "");
  if (!h) return false;
  if (h.endsWith(".in")) return true;
  return INDIAN_HOSTS.some((d) => h === d || h.endsWith("." + d));
}

export function decode(s) {
  return String(s || "")
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(+n))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&amp;/g, "&");
}

function tag(block, name) {
  const m = new RegExp("<" + name + "(?:\\s[^>]*)?>([\\s\\S]*?)</" + name + ">", "i").exec(block);
  return m ? decode(m[1]).trim() : "";
}

export function parseFeed(xml) {
  const out = [];
  const re = /<item>([\s\S]*?)<\/item>/g;
  let m;
  while ((m = re.exec(xml))) {
    const b = m[1];
    const src = /<source[^>]*url="([^"]+)"[^>]*>([\s\S]*?)<\/source>/i.exec(b);
    const srcName = src ? decode(src[2]).trim() : "";
    const srcUrl = src ? decode(src[1]).trim() : "";
    let title = tag(b, "title");
    if (srcName && title.endsWith(" - " + srcName)) title = title.slice(0, -(srcName.length + 3)).trim();
    const link = tag(b, "link");
    const when = Date.parse(tag(b, "pubDate"));
    let host = "";
    try { host = new URL(srcUrl).hostname; } catch { /* no usable source url */ }
    if (!title || !/^https?:\/\//.test(link) || Number.isNaN(when) || !srcName) continue;
    out.push({ title, link, src: srcName, host, t: when });
  }
  return out;
}

export async function fetchQuery(q) {
  const url = `${FEED}?q=${encodeURIComponent(q)}&hl=en-IN&gl=IN&ceid=IN:en`;
  const r = await fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0 (compatible; DarkroomNews/1.0)", Accept: "application/rss+xml, text/xml" },
    signal: AbortSignal.timeout(9000),
    cache: "no-store",
  });
  if (!r.ok) throw new Error("Google News answered " + r.status);
  return parseFeed(await r.text());
}

export const NEWS_QUERIES = QUERIES;
