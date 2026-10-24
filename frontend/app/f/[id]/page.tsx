import Link from "next/link";
import { getFinding, mediaUrl } from "@/lib/api";
import { PATTERN_LABEL } from "@/lib/types";
import { bigNumber } from "@/lib/measure";
import StatusBadge from "@/components/StatusBadge";
import PriceLadder from "@/components/PriceLadder";

export const dynamic = "force-dynamic";

const back = (
  <Link href="/" className="text-sm text-neutral-400 hover:text-neutral-200">← All findings</Link>
);

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let data;
  try {
    data = await getFinding(id);
  } catch (e) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-10">
        {back}
        <p className="mt-6 rounded-lg border border-amber-700/40 bg-amber-950/30 p-4 text-sm text-amber-200">
          Could not load finding {id} ({(e as Error).message}). Check the backend on port 8000 and the finding ID.
        </p>
      </main>
    );
  }
  const { finding, journey_states } = data;
  const js = journey_states?.[0];
  const big = bigNumber(finding);
  const video = finding.evidence.video_ref ?? js?.artifacts?.video_ref ?? null;
  const h2 = "text-xs font-semibold uppercase tracking-wider text-neutral-500";

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      {back}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{PATTERN_LABEL[finding.pattern] ?? finding.pattern}</h1>
        <StatusBadge status={finding.status} />
        <span className="text-sm text-neutral-400">{finding.platform}</span>
        <span className="text-sm text-neutral-500">{finding.severity} severity</span>
      </div>

      {big && (
        <section className="mt-6 rounded-xl border-2 border-blue-700 bg-blue-950/30 p-6">
          <p className="text-4xl font-bold tracking-tight">{big.value}</p>
          <p className="mt-1 text-sm text-blue-200">{big.caption}</p>
        </section>
      )}

      {js && <PriceLadder steps={js.steps} />}

      {js?.steps.some((s) => s.timers.length > 0 || s.stock_claims.length > 0) && (
        <section className="mt-8 rounded-xl border border-neutral-800 p-5">
          <h2 className={h2}>Urgency claims shown</h2>
          <ul className="mt-2 space-y-1 text-sm text-neutral-300">
            {js.steps.flatMap((s) => [
              ...s.timers.map((t, i) => <li key={`t${s.index}${i}`}>{s.name}: {t.label}{t.seconds_left != null ? `, ${t.seconds_left}s left` : ""}</li>),
              ...s.stock_claims.map((c, i) => <li key={`c${s.index}${i}`}>{s.name}: {c.text}</li>),
            ])}
          </ul>
        </section>
      )}

      <section className="mt-8 grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-neutral-800 p-5">
          <h2 className={h2}>Legal basis</h2>
          <p className="mt-2 text-sm leading-relaxed">{finding.clause}</p>
        </div>
        <div className="rounded-xl border border-neutral-800 p-5">
          <h2 className={h2}>Evidence</h2>
          <ul className="mt-2 space-y-1 text-sm text-neutral-300">
            {finding.evidence.reproduced_in && <li>Reproduced in {finding.evidence.reproduced_in}</li>}
            <li>{finding.evidence.observation_ids?.length ?? 0} observation(s)</li>
            <li>Detected {new Date(finding.detected_at).toLocaleString("en-IN")}</li>
          </ul>
        </div>
      </section>

      <section className="mt-8">
        <h2 className={h2}>Run recording</h2>
        {video ? (
          <video controls src={mediaUrl(video)} className="mt-3 w-full rounded-xl border border-neutral-800" />
        ) : (
          <p className="mt-3 rounded-xl border border-dashed border-neutral-800 p-8 text-center text-sm text-neutral-500">
            Recording not attached for this observation
          </p>
        )}
      </section>

      <p className="mt-8 text-xs leading-relaxed text-neutral-500">
        DARKROOM reports measurements, not verdicts. Figures describe what the interface displayed during an automated
        session that never completed a payment. Platforms are offered a right of reply before publication.
      </p>
    </main>
  );
}
