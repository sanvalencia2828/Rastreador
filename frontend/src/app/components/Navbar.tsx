"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/", label: "Mapa" },
  { href: "/cities", label: "Cidades" },
  { href: "/generate", label: "Gerar Rota" },
  { href: "/visits", label: "Visitas" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/reports", label: "Relatórios" },
  { href: "/search", label: "Buscar" },
];

export default function Navbar() {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(href + "/");
  };

  return (
    <nav
      className="flex items-center gap-1 overflow-x-auto"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        height: "48px",
        background: "var(--bg)",
        borderBottom: "1px solid var(--border)",
        padding: "0 20px",
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        gap: "16px",
      }}
    >
      <Link
        href="/"
        className="text-sm font-semibold flex-shrink-0"
        style={{ color: "var(--fg)", textDecoration: "none" }}
      >
        Rastreador
      </Link>
      <div className="flex items-center" style={{ gap: "4px", flex: 1, minWidth: 0 }}>
        {NAV_LINKS.map((link) => {
          const active = isActive(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className="text-xs font-medium flex-shrink-0 transition-colors"
              style={{
                color: active ? "var(--accent)" : "var(--muted)",
                textDecoration: "none",
                padding: "6px 10px",
                borderRadius: "6px",
                whiteSpace: "nowrap",
              }}
              onMouseEnter={(e) => {
                if (!active) e.currentTarget.style.color = "var(--accent)";
              }}
              onMouseLeave={(e) => {
                if (!active) e.currentTarget.style.color = "var(--muted)";
              }}
            >
              {link.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}