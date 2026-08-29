"use client";

import { useState, useCallback } from "react";
import Link from "next/link";

type ExportType = "visits" | "clients" | "coverage" | null;

function downloadCSV(filename: string, rows: string[][]) {
  const csv = rows.map(r =>
    r.map(cell => {
      const escaped = String(cell ?? "").replace(/"/g, '""');
      return `"${escaped}"`;
    }).join(",")
  ).join("\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return iso;
  }
}

function todayStamp(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function ReportsPage() {
  const [exporting, setExporting] = useState<ExportType>(null);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

  const showMessage = useCallback((text: string, type: "success" | "error") => {
    setMessage({ text, type });
    setTimeout(() => setMessage(null), 3000);
  }, []);

  const handleExportVisits = useCallback(async () => {
    setExporting("visits");
    try {
      const res = await fetch("/api/visits");
      if (!res.ok) throw new Error("fail");
      const data = await res.json();
      const rows: string[][] = [["data_hora", "nome_fantasia", "cnpj", "logradouro", "bairro", "municipio"]];
      for (const v of data) {
        rows.push([
          formatDate(v.visited_at),
          v.logradouro || v.cnpj,
          v.cnpj,
          v.logradouro || "",
          v.bairro || "",
          "",
        ]);
      }
      if (data.length === 0) {
        showMessage("Sin visitas para exportar.", "error");
        return;
      }
      downloadCSV(`visitas_${todayStamp()}.csv`, rows);
      showMessage(`Exportadas ${data.length} visitas.`, "success");
    } catch {
      showMessage("Error al exportar visitas.", "error");
    } finally {
      setExporting(null);
    }
  }, [showMessage]);

  const handleExportClients = useCallback(async () => {
    setExporting("clients");
    try {
      const res = await fetch("/api/businesses/clients?limit=500");
      if (!res.ok) throw new Error("fail");
      const data = await res.json();
      const rows: string[][] = [["nome_fantasia", "cnpj", "cnae_label", "bairro", "logradouro", "municipio"]];
      for (const c of data) {
        rows.push([
          c.nome_fantasia || "",
          c.cnpj,
          c.cnae_label || "",
          c.bairro || "",
          c.logradouro || "",
          c.municipio || "",
        ]);
      }
      if (data.length === 0) {
        showMessage("Sin clientes para exportar.", "error");
        return;
      }
      downloadCSV(`clientes_${todayStamp()}.csv`, rows);
      showMessage(`Exportados ${data.length} clientes.`, "success");
    } catch {
      showMessage("Error al exportar clientes.", "error");
    } finally {
      setExporting(null);
    }
  }, [showMessage]);

  const handleExportCoverage = useCallback(async () => {
    setExporting("coverage");
    try {
      const res = await fetch("/api/stats/summary");
      if (!res.ok) throw new Error("fail");
      const data = await res.json();
      const rows: string[][] = [["cidade", "total_lojas", "visitadas", "cobertura_%"]];
      for (const c of data.cities || []) {
        const pct = c.total > 0 ? Math.round((c.visited / c.total) * 100) : 0;
        rows.push([c.name, String(c.total), String(c.visited), String(pct)]);
      }
      if ((data.cities || []).length === 0) {
        showMessage("Sin datos de cobertura.", "error");
        return;
      }
      downloadCSV(`cobertura_${todayStamp()}.csv`, rows);
      showMessage(`Exportadas ${data.cities.length} ciudades.`, "success");
    } catch {
      showMessage("Error al exportar cobertura.", "error");
    } finally {
      setExporting(null);
    }
  }, [showMessage]);

  const cards = [
    {
      title: "Lojas visitadas",
      description: "Exportar lista de lojas visitadas con fecha y dirección",
      icon: (
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
          <circle cx="12" cy="10" r="3" />
        </svg>
      ),
      color: "#22c55e",
      action: handleExportVisits,
      key: "visits" as ExportType,
    },
    {
      title: "Clientes",
      description: "Exportar lista de clientes registrados",
      icon: (
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
          <circle cx="8.5" cy="7" r="4" />
          <line x1="20" y1="8" x2="20" y2="14" />
          <line x1="23" y1="11" x2="17" y2="11" />
        </svg>
      ),
      color: "#8b5cf6",
      action: handleExportClients,
      key: "clients" as ExportType,
    },
    {
      title: "Cobertura por ciudad",
      description: "Exportar resumo de cobertura por ciudad",
      icon: (
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <line x1="3" y1="9" x2="21" y2="9" />
          <line x1="9" y1="21" x2="9" y2="9" />
        </svg>
      ),
      color: "var(--accent)",
      action: handleExportCoverage,
      key: "coverage" as ExportType,
    },
  ];

  return (
    <main className="flex flex-col min-h-dvh px-4 py-4 lg:px-6 lg:py-6" style={{ maxWidth: "900px", margin: "0 auto", width: "100%" }}>
      <header className="mb-6">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1 text-xs font-medium mb-3 transition-colors"
          style={{ color: "var(--muted)", textDecoration: "none" }}
          onMouseEnter={(e) => { e.currentTarget.style.color = "var(--accent)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = "var(--muted)"; }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></svg>
          Dashboard
        </Link>
        <h1 className="text-lg lg:text-xl font-semibold tracking-tight" style={{ color: "var(--fg)" }}>Relatórios</h1>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>Exportá datos en formato CSV</p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {cards.map((card) => {
          const isExporting = exporting === card.key;
          return (
            <div
              key={card.key}
              className="flex flex-col gap-4"
              style={{
                padding: "20px",
                background: "var(--card)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
              }}
            >
              <div className="flex items-center gap-3">
                <span style={{ color: card.color }}>{card.icon}</span>
                <h2 className="text-sm font-medium" style={{ color: "var(--fg)" }}>{card.title}</h2>
              </div>
              <p className="text-xs" style={{ color: "var(--muted)", flex: 1 }}>{card.description}</p>
              <button
                onClick={card.action}
                disabled={isExporting}
                className="inline-flex items-center justify-center gap-2 transition-opacity"
                style={{
                  padding: "10px 16px",
                  background: isExporting ? "var(--accent-dim)" : "var(--bg-elevated)",
                  color: "var(--fg-secondary)",
                  fontWeight: 500,
                  fontSize: "13px",
                  borderRadius: "8px",
                  border: "1px solid var(--border)",
                  cursor: isExporting ? "not-allowed" : "pointer",
                  opacity: isExporting ? 0.6 : 1,
                }}
              >
                {isExporting ? (
                  <>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" style={{ animation: "spin 0.8s linear infinite", border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%" }} />
                    Exportando...
                  </>
                ) : (
                  <>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
                    Exportar CSV
                  </>
                )}
              </button>
            </div>
          );
        })}
      </div>

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
        }}>
          {message.text}
        </div>
      )}

      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </main>
  );
}