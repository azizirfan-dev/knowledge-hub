"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const STEPS = [
  "Verifying identity...",
  "Loading knowledge base...",
  "Preparing agents...",
  "Welcome aboard.",
];

export default function LoadingPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [step, setStep] = useState(0);

  useEffect(() => {
    const n = sessionStorage.getItem("kb_name");
    const r = sessionStorage.getItem("kb_role");
    if (!n || !r) {
      router.replace("/");
      return;
    }
    setName(n);
    setRole(r);

    const timers: ReturnType<typeof setTimeout>[] = [];
    STEPS.forEach((_, i) => {
      timers.push(setTimeout(() => setStep(i), i * 450));
    });
    timers.push(setTimeout(() => router.replace("/chat"), STEPS.length * 450 + 300));

    return () => timers.forEach(clearTimeout);
  }, [router]);

  return (
    <main className="min-h-screen bg-white flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-sm neo-box bg-white p-8 flex flex-col gap-6">
        {/* Identity card */}
        <div className="neo-box-sm bg-[#FFD700] p-4">
          <p className="text-xs font-black uppercase tracking-widest text-black/50">
            Authenticated as
          </p>
          <p className="text-2xl font-black mt-1 truncate">{name || "..."}</p>
          <span className="neo-tag neo-tag-technical mt-2 inline-block">
            {role || "..."}
          </span>
        </div>

        {/* Spinner + status */}
        <div className="flex flex-col items-center gap-4 py-4">
          <div className="neo-spinner" />
          <div className="h-8 flex items-center">
            <p className="text-sm font-bold tracking-wide transition-all duration-300">
              {STEPS[step]}
            </p>
          </div>
        </div>

        {/* Progress bar */}
        <div className="neo-box-sm h-4 bg-gray-100 overflow-hidden">
          <div
            className="h-full bg-black transition-all duration-500"
            style={{ width: `${((step + 1) / STEPS.length) * 100}%` }}
          />
        </div>
      </div>
    </main>
  );
}
