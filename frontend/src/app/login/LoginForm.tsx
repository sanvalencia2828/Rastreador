"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { friendlyError, safeNext, setToken } from "../lib/auth";

export default function LoginForm({ expired, next }: { expired: boolean; next: string | null }) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      if (!res.ok) {
        setError(
          res.status === 400
            ? "Usuário ou senha incorretos."
            : friendlyError(res.status) ?? "Não foi possível entrar. Tente novamente.",
        );
        return;
      }
      const data = await res.json();
      if (!setToken(data.token)) {
        setError("O navegador bloqueou o armazenamento da sessão. Permita o armazenamento do site e tente de novo.");
        return;
      }
      router.replace(safeNext(next));
    } catch {
      setError("Não foi possível conectar ao servidor.");
    } finally {
      setLoading(false);
    }
  }

  const field = {
    width: "100%",
    padding: "10px 12px",
    background: "var(--bg-elevated)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    color: "var(--fg)",
  } as const;

  return (
    <main className="flex flex-col items-center px-4 py-10">
      <form
        onSubmit={handleSubmit}
        style={{ width: "100%", maxWidth: "360px", background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "24px" }}
      >
        <h1 className="text-lg font-semibold mb-4" style={{ color: "var(--fg)" }}>Entrar</h1>
        {expired && !error && (
          <p role="status" className="text-xs mb-3" style={{ color: "var(--muted)" }}>
            Sua sessão expirou. Entre novamente.
          </p>
        )}
        <label className="text-xs" style={{ color: "var(--fg-secondary)" }} htmlFor="username">Usuário</label>
        <input id="username" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} style={{ ...field, marginBottom: "12px" }} />
        <label className="text-xs" style={{ color: "var(--fg-secondary)" }} htmlFor="password">Senha</label>
        <input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} style={{ ...field, marginBottom: "16px" }} />
        {error && (
          <p role="alert" className="text-xs mb-3" style={{ color: "var(--error)" }}>{error}</p>
        )}
        <button
          type="submit"
          disabled={loading}
          className="text-sm font-medium"
          style={{ width: "100%", padding: "10px", borderRadius: "var(--radius)", background: "var(--accent)", color: "#0f0f0f", opacity: loading ? 0.6 : 1 }}
        >
          {loading ? "Entrando..." : "Entrar"}
        </button>
      </form>
    </main>
  );
}
