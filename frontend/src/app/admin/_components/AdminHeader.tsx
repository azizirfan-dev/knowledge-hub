"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export function AdminHeader({ title, subtitle }: { title: string; subtitle: string }) {
  const router = useRouter();
  const [name, setName] = useState("");

  useEffect(() => {
    setName(sessionStorage.getItem("kb_name") ?? "");
  }, []);

  function handleLogout() {
    sessionStorage.removeItem("kb_name");
    sessionStorage.removeItem("kb_role");
    router.push("/");
  }

  return (
    <>
      <div className="neo-box bg-[#FFD700] p-4 mb-1 flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-black uppercase tracking-tight">{title}</h1>
          <p className="text-sm font-bold mt-1">{subtitle}</p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {name && (
            <span className="text-xs font-black uppercase tracking-widest">
              {name} · Admin
            </span>
          )}
          <button
            onClick={handleLogout}
            className="neo-btn bg-white text-xs font-black uppercase px-3 py-2"
          >
            Log Out
          </button>
        </div>
      </div>
      <div className="h-2 bg-black w-full mb-6" />
    </>
  );
}
