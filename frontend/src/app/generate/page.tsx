"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";

interface CityOption {
  id: string | number;
  name: string;
  state?: string;
  lat: number;
  lon: number;
  total_businesses: number | null;
}

interface SelectedCity {
  id: string | number;
  name: string;
  lat: number;
  lon: number;
  total_businesses: number | null;
}

interface GeneratedStop {
  cnpj: string;
  nome_fantasia: string;
  cnae_label: string;
  bairro: string;
  logradouro: string;
  lat: number;
  lon: number;
  days_since_visit: number;
  priority: string;
}

interface GenerateResult {
  city: string;
  total_candidates: number;
  selected: number;
  stops: GeneratedStop[];
}

type MessageType = { text: string; type: "success" | "error" };

export default function GeneratePage() {
  const [cities, setCities] = useState<CityOption[]>([]);
  const [selectedCity, setSelectedCity] = useState<SelectedCity | null>(null);
  const [maxLojas, setMaxLojas] = useState(80);
  const [minDays, setMinDays] = useState(30);
  const [isGenerating, setIsGenerating] = useState(false);
  const [result, setResult] = useState<GenerateResult | null>(null);
  const [message, setMessage] = useState<MessageType | null>(null);
  const [fetchError, setFetchError] = useState<string | undefined>();

  useEffect(() => {
    let isMounted = true;

    const load = async () => {
      try {
        const res = await fetch("/api/cities");
        if (!res.ok) throw new Error("fail");
        const data = await res.json();
        if (!isMounted) return;

        const baseCities: CityOption[] = (data as Array<{ id: string | number; name: string; state?: string; lat: number; lon: number }>).map(c => ({
          id: c.id,
          name: c.name,
          state: c.state,
          lat: c.lat,
          lon: c.lon,
          total_businesses: null,
        }));
        setCities(baseCities);

        const statsResults = await Promise.allSettled(
          baseCities.map(async (city) => {
            const statRes = await fetch(`/api/cities/${city.id}/stats`);
            if (!statRes.ok) throw new Error(`stats ${city.id}`);
            const stat = await statRes.json();
            return stat.total_businesses ?? null;
          })
        );

        if (!isMounted) return;

        setCities(prev =>
          prev.map((city, i) => {
            const r = statsResults[i];
            if (!r || r.status === "rejected") return city;
            return { ...city, total_businesses: r.value };
          })
        );
      } catch {
        if (isMounted) setFetchError("No se pudieron cargar las ciudades.");
      }
    };

    load();

    return () => {
      isMounted = false;
    };
  }, []);

  const handleSelectCity = useCallback((city: CityOption) => {
    setSelectedCity({
      id: city.id,
      name: city.name,
      lat: city.lat,
      lon: city.lon,
      total_businesses: city.total_businesses,
    });
    setResult(null);
    setMessage(null);
  }, []);

  const handleGenerate = useCallback(async () => {
    if (!selectedCity) return;
    setIsGenerating(true);
    setResult(null);
    setMessage(null);

    try {
      const res = await fetch("/api/routes/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          city_id: Number(selectedCity.id),
          max_lojas: maxLojas,
          min_days_without_visit: minDays,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage({ text: data.error || data.detail || "Erro ao gerar rota", type: "error" });
        setIsGenerating(false);
        return;
      }
      setResult(data as GenerateResult);
    } catch {
      setMessage({ text: "Não foi possível conectar ao servidor.", type: "error" });
    } finally {
      setIsGenerating(false);
    }
  }, [selectedCity, maxLojas, minDays]);

  const handleSave = useCallback(async () => {
    if (!result || !selectedCity) return;

    const now = new Date();
    const dd = String(now.getDate()).padStart(2, "0");
    const mm = String(now.getMonth() + 1).padStart(2, "0");
    const routeName = `Rota ${dd}/${mm}`;

    try {
      const res = await fetch(`/api/cities/${selectedCity.id}/routes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: routeName,
          city_id: Number(selectedCity.id),
          stops: result.stops.map((s, i) => ({
            stop_order: i + 1,
            address: s.logradouro,
            lat: s.lat,
            lon: s.lon,
            display_name: `${s.logradouro}, ${s.bairro}`,
            cnpj: s.cnpj,
          })),
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        setMessage({ text: "Erro ao salvar rota", type: "error" });
        console.error("Save route error:", errData);
        return;
      }

      setMessage({ text: "Rota salva com sucesso!", type: "success" });
    } catch {
      setMessage({ text: "Erro ao salvar rota", type: "error" });
    }
  }, [result, selectedCity]);

  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(null), 3000);
    return () => clearTimeout(timer);
  }, [message]);

  const daysColor = (days: number) => {
    if (days > 90) return "var(--error)";
    if (days > 60) return "#f59e0b";
    return "var(--accent)";
  };

  return (
    <main className="flex flex-col min-h-dvh" style={{ padding: "24px 20px", maxWidth: "900px", margin: "0 auto", width: "100%" }}>
      <header className="mb-6">
        <Link
          href="/cities"
          className="inline-flex items-center gap-1 text-xs font-medium mb-3 transition-colors"
          style={{ color: "var(--muted)", textDecoration: "none" }}
          onMouseEnter={(e) => { e.currentTarget.style.color = "var(--accent)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = "var(--muted)"; }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></svg>
          Cidades
        </Link>
        <h1 className="text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>Gerar Rota do Dia</h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>Seleciona lojas por visitar priorizando as que faz mais tempo sem visita</p>
      </header>

      {fetchError && (
        <p className="text-xs mb-4" style={{ color: "var(--error)" }}>{fetchError}</p>
      )}

      <section>
        <p className="text-xs font-medium mb-3" style={{ color: "var(--muted)" }}>Selecione a cidade</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {cities.length === 0 && !fetchError && (
            <p className="text-xs" style={{ color: "var(--muted)" }}>Carregando cidades...</p>
          )}
          {cities.map((city) => {
            const isSelected = selectedCity?.id === city.id;
            return (
              <button
                key={city.id}
                onClick={() => handleSelectCity(city)}
                className="text-left transition-all"
                style={{
                  padding: "16px",
                  background: isSelected ? "color-mix(in srgb, var(--accent) 8%, transparent)" : "var(--card)",
                  border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
                  borderRadius: "var(--radius)",
                  cursor: "pointer",
                  display: "flex",
                  flexDirection: "column",
                  gap: "4px",
                }}
                onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.borderColor = "var(--muted)"; }}
                onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.borderColor = "var(--border)"; }}
              >
                <span className="text-sm font-medium" style={{ color: "var(--fg)" }}>{city.name}</span>
                {city.total_businesses !== null && (
                  <span className="text-xs" style={{ color: "var(--accent)" }}>{city.total_businesses} lojas</span>
                )}
              </button>
            );
          })}
        </div>
      </section>

      {selectedCity && (
        <>
          <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "24px 0" }} />

          <section>
            <p className="text-sm font-medium mb-4" style={{ color: "var(--fg-secondary)" }}>Configuração</p>

            <div className="mb-5">
              <div className="flex items-center justify-between mb-2">
                <label htmlFor="max-lojas" className="text-xs" style={{ color: "var(--muted)" }}>Quantidade de lojas</label>
                <span className="text-xs font-bold" style={{ color: "var(--accent)" }}>{maxLojas}</span>
              </div>
              <input
                id="max-lojas"
                type="range"
                min={30}
                max={150}
                step={10}
                value={maxLojas}
                onChange={(e) => setMaxLojas(Number(e.target.value))}
                style={{ width: "100%", accentColor: "var(--accent)", height: "6px" }}
              />
            </div>

            <div className="mb-5">
              <div className="flex items-center justify-between mb-2">
                <label htmlFor="min-days" className="text-xs" style={{ color: "var(--muted)" }}>Dias sem visita (mínimo)</label>
                <span className="text-xs font-bold" style={{ color: "var(--accent)" }}>{minDays}</span>
              </div>
              <input
                id="min-days"
                type="range"
                min={7}
                max={120}
                step={7}
                value={minDays}
                onChange={(e) => setMinDays(Number(e.target.value))}
                style={{ width: "100%", accentColor: "var(--accent)", height: "6px" }}
              />
            </div>

            <button
              onClick={handleGenerate}
              disabled={isGenerating}
              className="inline-flex items-center justify-center gap-2 transition-opacity"
              style={{
                marginTop: "24px",
                padding: "12px 24px",
                background: "var(--accent)",
                color: "#0f0f0f",
                fontWeight: 500,
                fontSize: "14px",
                borderRadius: "var(--radius)",
                width: "100%",
                cursor: isGenerating ? "not-allowed" : "pointer",
                opacity: isGenerating ? 0.5 : 1,
                border: "none",
              }}
            >
              {isGenerating ? (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" style={{ animation: "spin 0.8s linear infinite", border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%" }} />
                  Gerando...
                </>
              ) : "Gerar Rota"}
            </button>
          </section>
        </>
      )}

      {result && (
        <>
          <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "24px 0" }} />

          <section>
            <p className="text-sm mb-4" style={{ color: "var(--fg-secondary)" }}>
              {result.selected} de {result.total_candidates} lojas candidatas selecionadas para {result.city}
            </p>

            <div style={{ maxHeight: "400px", overflowY: "auto", borderRadius: "var(--radius)", border: "1px solid var(--border)" }}>
              <div style={{ display: "grid", gridTemplateColumns: "40px 1fr 1fr 1fr 80px", borderBottom: "1px solid var(--border)", position: "sticky", top: 0, background: "var(--card)", zIndex: 1 }}>
                {["#", "Nome Fantasia", "Bairro", "Rua", "Dias"].map((h, i) => (
                  <div key={h} style={{ padding: "8px", fontSize: "12px", fontWeight: 600, color: "var(--muted)", textAlign: i === 4 ? "right" : "left" }}>{h}</div>
                ))}
              </div>

              {result.stops.map((stop, i) => (
                <div
                  key={stop.cnpj}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "40px 1fr 1fr 1fr 80px",
                    background: i % 2 === 1 ? "var(--bg-elevated)" : "transparent",
                  }}
                >
                  <div style={{ padding: "8px", fontSize: "12px", color: "var(--muted)" }}>{i + 1}</div>
                  <div style={{ padding: "8px", fontSize: "12px", color: "var(--fg)" }}>{stop.nome_fantasia}</div>
                  <div style={{ padding: "8px", fontSize: "12px", color: "var(--fg-secondary)" }}>{stop.bairro}</div>
                  <div style={{ padding: "8px", fontSize: "12px", color: "var(--fg-secondary)" }}>{stop.logradouro}</div>
                  <div style={{ padding: "8px", fontSize: "12px", color: daysColor(stop.days_since_visit), textAlign: "right", fontWeight: 600 }}>{stop.days_since_visit}</div>
                </div>
              ))}
            </div>

            <button
              onClick={handleSave}
              className="inline-flex items-center justify-center gap-2 transition-opacity"
              style={{
                marginTop: "16px",
                padding: "12px 24px",
                background: "var(--accent)",
                color: "#0f0f0f",
                fontWeight: 500,
                fontSize: "14px",
                borderRadius: "var(--radius)",
                width: "100%",
                cursor: "pointer",
                border: "none",
              }}
            >
              Salvar como Rota
            </button>
          </section>
        </>
      )}

      {message && (
        <div style={{
          marginTop: "16px",
          padding: "12px 16px",
          borderRadius: "var(--radius)",
          background: message.type === "success" ? "var(--accent-dim)" : "var(--error-dim)",
          color: message.type === "success" ? "var(--accent)" : "var(--error)",
          fontSize: "14px",
          fontWeight: 500,
          textAlign: "center",
          transition: "opacity 0.3s",
        }}>
          {message.text}
        </div>
      )}

      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </main>
  );
}
