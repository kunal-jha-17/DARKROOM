import { getFindings } from "@/lib/api";
import type { Finding } from "@/lib/types";
import FindingCard from "@/components/FindingCard";
import RunBar from "@/components/RunBar";

export const dynamic = "force-dynamic";

export default async function Page() {
  let findings: Finding[] = [];
  let sample = false;
  let error = "";
  try {
    ({ findings, sample } = await getFindings());
  } catch (e) {
    error = (e as Error).message;
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">DARKROOM</h1>
        <p className="mt-1 text-sm text-neutral-400">Dark patterns caught on live Indian checkouts, with evidence</p>
      </header>
      <RunBar />
      {sample && (
        <p className="mb-4 rounded-lg border border-neutral-800 p-3 text-xs text-neutral-400">
          Showing sample data. The backend is not reachable.
        </p>
      )}
      {error && (
        <p className="rounded-lg border border-amber-700/40 bg-amber-950/30 p-4 text-sm text-amber-200">
          Backend unreachable ({error}). Start it on port 8000, then reload.
        </p>
      )}
      {!error && findings.length === 0 && (
        <p className="rounded-lg border border-neutral-800 p-8 text-center text-sm text-neutral-400">
          No findings yet. Enter an entry URL above and run a probe.
        </p>
      )}
      <ul className="mt-6 space-y-3">
        {findings.map((f) => (
          <li key={f.finding_id}><FindingCard f={f} /></li>
        ))}
      </ul>
    </main>
  );
}
