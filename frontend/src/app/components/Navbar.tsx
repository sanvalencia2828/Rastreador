"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Inicio" },
  { href: "/cities", label: "Cidades" },
  { href: "/generate", label: "Generar" },
  { href: "/routes", label: "Rutas" },
];

export default function Navbar() {
  const pathname = usePathname() || "/";

  return (
    <header
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 20,
        height: 48,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        padding: "0 16px",
        background: "rgba(15,15,15,0.92)",
        borderBottom: "1px solid var(--border)",
        backdropFilter: "blur(10px)",
      }}
    >
      <Link href="/" style={{ color: "var(--fg)", textDecoration: "none", fontSize: 13, fontWeight: 650, letterSpacing: "-0.02em" }}>
        Rastreador
      </Link>
      <nav style={{ display: "flex", gap: 6 }}>
        {LINKS.map((link) => {
          const active = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              style={{
                textDecoration: "none",
                fontSize: 12,
                fontWeight: 600,
                padding: "6px 10px",
                borderRadius: 6,
                color: active ? "var(--bg)" : "var(--fg-secondary)",
                background: active ? "var(--accent)" : "transparent",
              }}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
