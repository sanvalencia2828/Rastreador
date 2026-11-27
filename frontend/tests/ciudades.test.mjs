// node --test tests/   (Node >= 22.18 ejecuta el .ts quitando los tipos)
import { test } from "node:test";
import assert from "node:assert/strict";
import { mismaCiudad, reparar } from "../src/app/lib/ciudades.ts";

test("reparar deshace el mojibake de cities.name y deja el resto igual", () => {
  assert.equal(reparar("MaringÃ¡"), "Maringá");
  assert.equal(reparar("CambÃ©"), "Cambé");
  assert.equal(reparar("Maringá"), "Maringá");
  assert.equal(reparar("Londrina"), "Londrina");
});

test("mismaCiudad ignora mayúsculas y mojibake", () => {
  assert.equal(mismaCiudad("Maringá", "MaringÃ¡"), true);
  assert.equal(mismaCiudad("MARINGÁ", "maringá"), true);
  assert.equal(mismaCiudad(null, "Maringá"), false);
  assert.equal(mismaCiudad("Arapongas", "Maringá"), false);
});
