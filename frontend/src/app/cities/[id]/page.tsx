import { Suspense } from "react";
import CityPlanner from "./CityPlanner";

export function generateStaticParams() {
  return Array.from({ length: 24 }, (_, index) => ({ id: String(index + 1) }));
}

export default async function CityPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Suspense
      fallback={
        <main className="px-4 py-6 text-xs" style={{ color: "var(--muted)" }}>
          Cargando ciudad...
        </main>
      }
    >
      <CityPlanner id={id} />
    </Suspense>
  );
}
