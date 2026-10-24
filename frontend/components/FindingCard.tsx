import Link from "next/link";
import { headline } from "@/lib/measure";
import { PATTERN_LABEL, type Finding } from "@/lib/types";
import StatusBadge from "./StatusBadge";

export default function FindingCard({ f }: { f: Finding }) {
  return (
    <Link
      href={`/f/${f.finding_id}`}
      className="block rounded-xl border border-neutral-800 bg-neutral-900/40 p-5 transition hover:border-neutral-600"
    >
      <div className="flex items-center justify-between gap-4">
        <span className="text-sm font-medium text-neutral-300">{f.platform}</span>
        <StatusBadge status={f.status} />
      </div>
      <p className="mt-2 text-lg font-semibold">{headline(f)}</p>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-500">
        <span className="rounded bg-neutral-800 px-2 py-0.5 text-neutral-300">
          {PATTERN_LABEL[f.pattern] ?? f.pattern}
        </span>
        <span>{f.severity} severity</span>
        {f.evidence.reproduced_in && <span>{f.evidence.reproduced_in}</span>}
        <span>{new Date(f.detected_at).toLocaleString("en-IN")}</span>
      </div>
    </Link>
  );
}
