import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";
import "./globals.css";
import Navbar from "./components/Navbar";

const geistSans = Geist({
  subsets: ["latin"],
  variable: "--font-geist-sans",
});

export const metadata: Metadata = {
  title: "Geolocalizador — Busca direcciones en el mapa",
  description:
    "Ingresa una dirección y obtené las coordenadas exactas con un radio de 500m en el mapa.",
  robots: "noindex, nofollow",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  themeColor: "#0f0f0f",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className={geistSans.variable}>
      <body>
        <Navbar />
        <div style={{ paddingTop: "48px" }}>{children}</div>
      </body>
    </html>
  );
}
