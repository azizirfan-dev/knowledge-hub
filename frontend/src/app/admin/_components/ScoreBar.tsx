export function ScoreBar({ value, label }: { value: number; label?: string }) {
  const clamped = Math.max(0, Math.min(1, value));
  const pct = Math.round(clamped * 100);
  const color =
    clamped >= 0.5 ? "bg-green-400" : clamped >= 0.3 ? "bg-yellow-300" : "bg-red-400";
  return (
    <div className="flex items-center gap-2 text-xs font-mono">
      {label && <span className="text-gray-600 shrink-0">{label}</span>}
      <div className="h-3 w-24 border-2 border-black bg-white relative">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-bold shrink-0">{value.toFixed(3)}</span>
    </div>
  );
}
