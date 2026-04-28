"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

const ROLES = ["Developer", "HR Staff", "Employee", "Admin"] as const;
type Role = (typeof ROLES)[number];

const ROLE_DESCRIPTIONS: Record<Role, string> = {
  Developer: "Technical documentation & API queries",
  "HR Staff": "HR policies, onboarding & leave procedures",
  Employee: "General questions & internal knowledge",
  Admin: "Developer dashboard — monitor RAG performance",
};

export default function LandingPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role | "">("");
  const [error, setError] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Please enter your name.");
      return;
    }
    if (!role) {
      setError("Please select your role.");
      return;
    }
    sessionStorage.setItem("kb_name", name.trim());
    sessionStorage.setItem("kb_role", role);
    router.push(role === "Admin" ? "/admin" : "/loading");
  }

  return (
    <main className="min-h-screen bg-white flex flex-col items-center justify-center p-6">
      {/* Header stripe */}
      <div className="w-full max-w-md mb-8">
        <div className="neo-box bg-[#FFD700] p-4 mb-1">
          <h1 className="text-3xl font-black uppercase tracking-tight leading-none">
            KnowledgeHub
          </h1>
          <p className="text-sm font-bold mt-1 uppercase tracking-widest">
            Assistant
          </p>
        </div>
        <div className="h-2 bg-black w-full" />
      </div>

      {/* Form card */}
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md neo-box bg-white p-8 flex flex-col gap-6"
      >
        <div>
          <label className="block text-xs font-black uppercase tracking-widest mb-2">
            Your Name
          </label>
          <input
            className="neo-input"
            type="text"
            placeholder="e.g. Aziz Irfan"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setError("");
            }}
            maxLength={60}
          />
        </div>

        <div>
          <label className="block text-xs font-black uppercase tracking-widest mb-3">
            Select Your Role
          </label>
          <div className="flex flex-col gap-3">
            {ROLES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => {
                  setRole(r);
                  setError("");
                }}
                className={`neo-box-sm p-4 text-left transition-all cursor-pointer ${
                  role === r
                    ? "bg-[#FFD700] border-black"
                    : "bg-white hover:bg-gray-50"
                }`}
              >
                <div className="font-black text-base">{r}</div>
                <div className="text-xs font-medium text-gray-600 mt-0.5">
                  {ROLE_DESCRIPTIONS[r]}
                </div>
              </button>
            ))}
          </div>
        </div>

        {error && (
          <p className="text-sm font-bold text-red-600 neo-box-sm bg-red-50 p-2">
            {error}
          </p>
        )}

        <button type="submit" className="neo-btn w-full text-base font-black uppercase tracking-wider py-4">
          Enter KnowledgeHub →
        </button>
      </form>

      <p className="mt-6 text-xs font-medium text-gray-400 uppercase tracking-widest">
        Multi-Agent RAG · Internal Documents
      </p>
    </main>
  );
}
