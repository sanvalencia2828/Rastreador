"use client";

import React from "react";

interface StatusMessageProps {
  type: "empty" | "loading" | "error" | "success";
  message?: string;
}

export default function StatusMessage({ type, message }: StatusMessageProps) {
  if (type === "loading") {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-8">
        <div
          className="h-8 w-8 rounded-full border-2 border-t-transparent"
          style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
        >
          <style>{`
            @keyframes spin {
              to { transform: rotate(360deg); }
            }
          `}</style>
          <div
            className="h-full w-full"
            style={{ animation: "spin 0.6s linear infinite" }}
          />
        </div>
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          Buscando...
        </p>
      </div>
    );
  }

  if (type === "error") {
    return (
      <div
        className="flex flex-col items-center gap-2 py-6 px-4 text-center"
        style={{
          background: "var(--bg-elevated)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
        }}
      >
        <svg
          width="32"
          height="32"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ color: "var(--error)" }}
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <p className="text-sm" style={{ color: "var(--fg-secondary)" }}>
          {message ?? "Ocurrió un error al buscar la dirección."}
        </p>
      </div>
    );
  }

  if (type === "success") {
    return (
      <div className="flex flex-col items-center gap-2 py-4 px-4 text-center">
        <div
          className="h-10 w-10 flex items-center justify-center rounded-full"
          style={{ background: "var(--accent)" }}
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#0f0f0f"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </div>
        <p className="text-sm font-medium" style={{ color: "var(--fg)" }}>
          ¡Listo!
        </p>
      </div>
    );
  }

  // type = "empty"
  return (
    <div
      className="flex flex-col items-center gap-3 py-10 px-4 text-center"
      style={{
        background: "var(--bg-elevated)",
        border: "1px dashed var(--border)",
        borderRadius: "var(--radius)",
      }}
    >
      <svg
        width="40"
        height="40"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ color: "var(--muted)" }}
      >
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
      <p className="text-sm" style={{ color: "var(--muted)" }}>
        Ingresá una dirección para ver el mapa y los comercios cercanos.
      </p>
    </div>
  );
}
