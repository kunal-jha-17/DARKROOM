"use client";
import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { startProbe, getRun } from "@/lib/api";

const MAX_MS = 4 * 60 * 1000; // stop polling after 4 minutes

export default function RunBar() {
  const [url, setUrl] = useState(process.env.NEXT_PUBLIC_DEMO_URL ?? "");
  const [platform, setPlatform] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [progress, setProgress] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const router = useRouter();

  const stop = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  };
  useEffect(() => stop, []);

  async function run() {
    if (!url || timer.current) return;
    setStatus("PENDING");
    setProgress("queued");
    try {
      const { run_id } = await startProbe(platform || "Platform", url);
      const started = Date.now();
      timer.current = setInterval(async () => {
        if (Date.now() - started > MAX_MS) {
          stop();
          setStatus("FAILED");
          setProgress("timed out waiting for the probe");
          return;
        }
        try {
          const r = await getRun(run_id);
          setStatus(r.status);
          setProgress(r.progress ?? "");
          if (["COMPLETED", "FAILED"].includes(r.status)) {
            stop();
            router.refresh();
            if (r.finding_id) router.push(`/f/${r.finding_id}`);
          }
        } catch {
          /* keep polling; one dropped request must not end the demo */
        }
      }, 2000);
    } catch (e) {
      stop();
      setStatus("FAILED");
      setProgress((e as Error).message);
    }
  }

  const busy = status === "PENDING" || status === "RUNNING";
  const field = "rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm";
  return (
    <section className="mb-6 rounded-xl border border-neutral-800 bg-neutral-900/40 p-4">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input value={platform} onChange={(e) => setPlatform(e.target.value)} placeholder="Platform name" className={`${field} w-full sm:w-48`} />
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://… entry URL" className={`${field} flex-1`} />
        <button onClick={run} disabled={busy || !url} className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white disabled:opacity-40">
          {busy ? "Shopping…" : "Run probe"}
        </button>
      </div>
      {status && (
        <p className="mt-3 flex items-center gap-2 text-sm text-neutral-400">
          {busy && <span className="h-2 w-2 animate-pulse rounded-full bg-blue-400" />}
          <span className="font-medium text-neutral-300">{status}</span>
          {progress && <span>{progress}</span>}
        </p>
      )}
    </section>
  );
}
