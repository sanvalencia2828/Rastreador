"use client";

import { useState, type FormEvent } from "react";

interface SearchBarProps {
  onSearch: (address: string) => void;
  isLoading: boolean;
}

export default function SearchBar({ onSearch, isLoading }: SearchBarProps) {
  const [value, setValue] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();

    if (trimmed.length < 5) {
      setValidationError("Ingresá al menos 5 caracteres.");
      return;
    }

    setValidationError(null);
    onSearch(trimmed);
  }

  function handleChange(text: string) {
    setValue(text);
    if (validationError && text.trim().length >= 5) {
      setValidationError(null);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="w-full">
      <div
        className="flex gap-3"
        style={{
          background: "var(--card)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          padding: "6px 6px 6px 16px",
          transition: "border-color 0.2s",
        }}
        onFocus={(e) => {
          e.currentTarget.style.borderColor = "var(--accent)";
        }}
        onBlur={(e) => {
          e.currentTarget.style.borderColor = "var(--border)";
        }}
      >
        <input
          type="text"
          value={value}
          onChange={(e) => handleChange(e.target.value)}
          placeholder="Rua, número, bairro — Londrina/PR"
          aria-label="Dirección a buscar"
          disabled={isLoading}
          className="flex-1 bg-transparent py-2.5 text-sm placeholder:text-[var(--muted)] disabled:opacity-50"
          autoComplete="off"
          spellCheck={false}
        />

        <button
          type="submit"
          disabled={isLoading}
          aria-busy={isLoading}
          className="flex items-center justify-center gap-2 px-5 text-sm font-medium transition-colors disabled:opacity-50"
          style={{
            background: isLoading ? "var(--accent-dim)" : "var(--accent)",
            color: "#0f0f0f",
            borderRadius: "calc(var(--radius) - 3px)",
            minWidth: "110px",
          }}
        >
          {isLoading ? (
            <>
              <span
                className="inline-block h-4 w-4 rounded-full border-2 border-current border-t-transparent"
                style={{ animation: "spin 0.6s linear infinite" }}
              />
              Buscando
            </>
          ) : (
            <>
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              Buscar
            </>
          )}
        </button>
      </div>

      {validationError && (
        <p
          className="mt-2 text-xs"
          style={{ color: "var(--error)" }}
          role="alert"
        >
          {validationError}
        </p>
      )}

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </form>
  );
}
