// node --test tests/   (Node >= 22.18 ejecuta el .ts quitando los tipos)
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

class FakeStorage {
  constructor() { this.m = new Map(); }
  get length() { return this.m.size; }
  key(i) { return [...this.m.keys()][i] ?? null; }
  getItem(k) { return this.m.has(k) ? this.m.get(k) : null; }
  setItem(k, v) { this.m.set(k, String(v)); }
  removeItem(k) { this.m.delete(k); }
}

let n = 0;
// cada import con otra query es un módulo nuevo: simula recargar la página con el mismo localStorage
const recargar = () => import(`../src/app/lib/visitados.ts?r=${n++}`);
const RUTA = { stops: [{ id: "c1" }, { id: "c2" }] };

beforeEach(() => { globalThis.localStorage = new FakeStorage(); });

test("ruta y visitados persisten al recargar", async () => {
  let v = await recargar();
  v.guardarRuta("2026-11-25", RUTA);
  v.alternarVisitado("2026-11-25", "c2");
  v = await recargar();
  assert.deepEqual(v.parsear(v.leerCrudo("2026-11-25")), { ruta: RUTA, visitados: ["c2"] });
});

test("desmarcar, y regenerar la ruta no borra los visitados", async () => {
  const v = await recargar();
  v.alternarVisitado("2026-11-25", "c1");
  v.alternarVisitado("2026-11-25", "c2");
  v.alternarVisitado("2026-11-25", "c1");
  v.guardarRuta("2026-11-25", RUTA);
  assert.deepEqual(v.parsear(v.leerCrudo("2026-11-25")).visitados, ["c2"]);
});

test("guardar un día nuevo borra los anteriores y no toca otras claves", async () => {
  const v = await recargar();
  localStorage.setItem("otra-cosa", "x");
  v.alternarVisitado("2026-11-24", "c1");
  v.alternarVisitado("2026-11-25", "c2");
  assert.equal(v.leerCrudo("2026-11-24"), "");
  assert.equal(localStorage.getItem("otra-cosa"), "x");
});

test("sin localStorage no revienta y recuerda en memoria", async () => {
  const v = await recargar();
  globalThis.localStorage = { get length() { throw new Error("denegado"); }, getItem() { throw new Error("denegado"); } };
  v.guardarRuta("2026-11-25", RUTA);
  v.alternarVisitado("2026-11-25", "c1");
  assert.deepEqual(v.parsear(v.leerCrudo("2026-11-25")), { ruta: RUTA, visitados: ["c1"] });
});

test("datos corruptos = día vacío; fecha local", async () => {
  const v = await recargar();
  localStorage.setItem(v.PREFIJO + "2026-11-25", "{no es json");
  assert.deepEqual(v.parsear(v.leerCrudo("2026-11-25")), { ruta: null, visitados: [] });
  assert.equal(v.hoy(new Date(2026, 0, 5, 23, 59)), "2026-01-05");
});

test("si setItem falla (lleno), marcar igual se ve en esta carga", async () => {
  const v = await recargar();
  localStorage.setItem = () => { throw new Error("QuotaExceededError"); };
  v.alternarVisitado("2026-11-25", "c1");
  assert.deepEqual(v.parsear(v.leerCrudo("2026-11-25")).visitados, ["c1"]);
});
