"use client";

import { useRef, useState } from "react";
import { apiFetch, friendlyError } from "../../lib/auth";

type Coords = { lat: number; lon: number };

// font-size 16px: iOS Safari zooms the page on focus for smaller inputs.
const FIELD: React.CSSProperties = {
  width: "100%", minHeight: "48px", padding: "10px 12px", fontSize: "16px",
  background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius)",
};
const BUTTON: React.CSSProperties = {
  width: "100%", minHeight: "52px", padding: "12px 24px", fontSize: "16px", fontWeight: 500,
  borderRadius: "var(--radius)", border: "none",
};

export default function NewClientePage() {
  const [nombre, setNombre] = useState("");
  const [direccion, setDireccion] = useState("");
  const [coords, setCoords] = useState<Coords | null>(null);
  const [locating, setLocating] = useState(false);
  const [locError, setLocError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  const locate = () => {
    setLocError(null);
    if (!navigator.geolocation) {
      setLocError("Este aparelho não oferece localização.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({ lat: pos.coords.latitude, lon: pos.coords.longitude });
        setLocating(false);
      },
      (err) => {
        setCoords(null);
        setLocating(false);
        setLocError(
          err.code === err.PERMISSION_DENIED
            ? "Sem permissão de localização. Ative-a nas configurações do navegador ou salve só com o endereço."
            : "Não foi possível obter a localização. Tente de novo ao ar livre ou salve só com o endereço.",
        );
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (saving) return;
    setSaving(true);
    setError(null);
    setSaved(null);
    try {
      const res = await apiFetch("/api/clientes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          nombre_negocio: nombre.trim(),
          direccion: direccion.trim() || null,
          ...(coords ?? {}),
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(friendlyError(res.status) ?? (typeof data.detail === "string" ? data.detail : "Erro ao salvar o cliente"));
        return;
      }
      setSaved(`${nombre.trim()} salvo${coords ? " com localização" : " (localização pendente)"}.`);
      setNombre("");
      setDireccion("");
      setCoords(null);
      nameRef.current?.focus();
    } catch {
      setError("Não foi possível conectar ao servidor.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="flex flex-col min-h-dvh px-4 py-4" style={{ maxWidth: "480px", margin: "0 auto", width: "100%" }}>
      <header className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>Novo cliente</h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>Maringá. Use sua localização para marcar o ponto onde você está.</p>
      </header>

      <form onSubmit={save} className="flex flex-col" style={{ gap: "16px" }}>
        <div>
          <label htmlFor="nombre" className="text-xs block mb-2" style={{ color: "var(--muted)" }}>Nome do negócio</label>
          <input
            id="nombre" ref={nameRef} value={nombre} onChange={(e) => setNombre(e.target.value)}
            required maxLength={300} autoComplete="off" style={FIELD}
          />
        </div>
        <div>
          <label htmlFor="direccion" className="text-xs block mb-2" style={{ color: "var(--muted)" }}>Endereço ou nota (opcional)</label>
          <input
            id="direccion" value={direccion} onChange={(e) => setDireccion(e.target.value)}
            maxLength={300} autoComplete="off" style={FIELD}
          />
        </div>

        <div>
          <button
            type="button" onClick={locate} disabled={locating}
            style={{
              ...BUTTON, background: "var(--card)", border: "1px solid var(--accent)", color: "var(--accent)",
              opacity: locating ? 0.5 : 1,
            }}
          >
            {locating ? "Obtendo localização..." : coords ? "Atualizar minha localização" : "Usar minha localização"}
          </button>
          {coords && <p className="text-xs mt-2" style={{ color: "var(--success)" }}>✓ Localização capturada</p>}
          {locError && <p className="text-xs mt-2" style={{ color: "var(--error)" }}>{locError}</p>}
        </div>

        <button
          type="submit" disabled={saving || !nombre.trim()}
          style={{
            ...BUTTON, background: "var(--accent)", color: "#0f0f0f",
            opacity: saving || !nombre.trim() ? 0.5 : 1, cursor: saving ? "not-allowed" : "pointer",
          }}
        >
          {saving ? "Salvando..." : "Salvar"}
        </button>

        <div aria-live="polite">
          {saved && <p className="text-sm" style={{ color: "var(--success)" }}>✓ {saved} Pode cadastrar o próximo.</p>}
          {error && <p className="text-sm" style={{ color: "var(--error)" }}>{error}</p>}
        </div>
      </form>
    </main>
  );
}
