"use client";

import { useEffect, useState } from "react";

type DueStatus = "never" | "overdue" | "due_soon" | "ok";

interface Business {
  id: string | number;
  name: string;
  last_visit_date: string | null;
  visits_count: number;
  avg_visit_interval_days: number | null;
  days_since_last_visit: number | null;
  due_in_days: number | null;
  status_due: DueStatus;
}

type LoadState = "loading" | "ready" | "error";

const STATUS_LABELS: Record<DueStatus, string> = {
  never: "Nunca visitado",
  overdue: "Vencido",
  due_soon: "Próximo",
  ok: "Al día",
};

const STATUS_COLORS: Record<DueStatus, string> = {
  never: "#60a5fa",
  overdue: "#f87171",
  due_soon: "#facc15",
  ok: "#9ca3af",
};

function formatDate(value: string | null): string {
  if (!value) return "Nunca";
  const [year, month, day] = value.split("-");
  if (!year || !month || !day) return value;
  return `${day}/${month}/${year}`;
}

function formatNumber(value: number | null): string {
  return value === null ? "—" : String(value);
}

export default function RoutesPage() {
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [state, setState] = useState<LoadState>("loading");

  useEffect(() => {
    const controller = new AbortController();

    async function loadBusinesses() {
      try {
        const response = await fetch("/api/businesses", {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("businesses request failed");

        const data: unknown = await response.json();
        if (!Array.isArray(data)) throw new Error("invalid businesses response");

        setBusinesses(data as Business[]);
        setState("ready");
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState("error");
      }
    }

    loadBusinesses();
    return () => controller.abort();
  }, []);

  return (
    <main
      className="flex min-h-dvh flex-col px-4 py-5 lg:px-8 lg:py-8"
      style={{ maxWidth: "1280px", margin: "0 auto", width: "100%" }}
    >
      <header className="mb-6">
        <p
          className="text-[11px] font-semibold uppercase tracking-[0.18em]"
          style={{ color: "var(--accent)" }}
        >
          Inteligencia comercial
        </p>
        <h1
          className="mt-2 text-2xl font-semibold tracking-tight lg:text-3xl"
          style={{ color: "var(--fg)" }}
        >
          Planificador de Rutas Inteligente
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>
          Priorizá los negocios según su frecuencia y urgencia de visita.
        </p>
      </header>

      {state === "loading" && (
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          Cargando negocios...
        </p>
      )}

      {state === "error" && (
        <div
          className="px-4 py-3 text-sm"
          style={{
            color: "var(--error)",
            background: "var(--error-dim)",
            border: "1px solid var(--error)",
            borderRadius: "var(--radius)",
          }}
        >
          No se pudieron cargar los negocios. Intentá nuevamente más tarde.
        </div>
      )}

      {state === "ready" && businesses.length === 0 && (
        <div
          className="px-4 py-8 text-center text-sm"
          style={{
            color: "var(--muted)",
            background: "var(--bg-elevated)",
            border: "1px dashed var(--border)",
            borderRadius: "var(--radius)",
          }}
        >
          No hay negocios disponibles para planificar rutas.
        </div>
      )}

      {state === "ready" && businesses.length > 0 && (
        <div
          className="overflow-x-auto"
          style={{
            background: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
          }}
        >
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {[
                  "Nombre",
                  "Última visita",
                  "Frecuencia",
                  "Días",
                  "Vence en",
                  "Estado",
                ].map((heading) => (
                  <th
                    key={heading}
                    className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider"
                    style={{ color: "var(--muted)" }}
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {businesses.map((business) => (
                <tr
                  key={business.id}
                  style={{ borderBottom: "1px solid var(--border)" }}
                >
                  <td
                    className="max-w-[280px] truncate px-4 py-3 font-medium"
                    style={{ color: "var(--fg)" }}
                  >
                    {business.name || "Sin nombre"}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--fg-secondary)" }}>
                    {formatDate(business.last_visit_date)}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--fg-secondary)" }}>
                    {business.avg_visit_interval_days === null
                      ? "—"
                      : `${business.avg_visit_interval_days} días`}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--fg-secondary)" }}>
                    {formatNumber(business.days_since_last_visit)}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--fg-secondary)" }}>
                    {formatNumber(business.due_in_days)}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className="inline-flex rounded-full px-2.5 py-1 text-xs font-semibold"
                      style={{
                        color: STATUS_COLORS[business.status_due],
                        background: `${STATUS_COLORS[business.status_due]}1c`,
                      }}
                    >
                      {STATUS_LABELS[business.status_due]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
