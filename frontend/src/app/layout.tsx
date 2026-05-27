import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Londrina Radar Comercial | Dashboard de Inteligencia Geográfica",
  description:
    "Plataforma analítica geoespacial para el rastreo y análisis de comercios y polos emergentes en Londrina, PR. Panel 100% de código abierto sin APIs comerciales.",
  keywords: [
    "Londrina",
    "comercio",
    "radar comercial",
    "inteligencia geográfica",
    "GIS",
    "heatmap",
    "CNPJ",
    "ETL",
  ],
  authors: [{ name: "Rastreador Comercial" }],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="es"
      className={`${inter.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col font-[family-name:var(--font-inter)]">
        {children}
      </body>
    </html>
  );
}
