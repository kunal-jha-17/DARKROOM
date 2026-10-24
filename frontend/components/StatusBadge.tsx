export default function StatusBadge({ status }: { status: string }) {
  const confirmed = status === "confirmed";
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
        confirmed
          ? "bg-emerald-950 text-emerald-300 ring-1 ring-emerald-800"
          : "bg-neutral-800 text-neutral-400 ring-1 ring-neutral-700"
      }`}
    >
      {confirmed ? "Confirmed" : "Candidate"}
    </span>
  );
}
