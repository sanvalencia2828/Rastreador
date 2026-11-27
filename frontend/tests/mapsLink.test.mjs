// node --test tests/   (Node >= 22.18 ejecuta el .ts quitando los tipos). Enlaces sintéticos.
import { test } from "node:test";
import assert from "node:assert/strict";
import { coordsDeEnlace, enParana } from "../src/app/lib/mapsLink.ts";

test("formatos de Google Maps", () => {
  assert.deepEqual(coordsDeEnlace("https://maps.google.com/?q=-23.4205,-51.9333"), { lat: -23.4205, lon: -51.9333 });
  assert.deepEqual(coordsDeEnlace("https://www.google.com/maps?q=-23.4205%2C-51.9333&z=17"), { lat: -23.4205, lon: -51.9333 });
  assert.deepEqual(coordsDeEnlace("https://www.google.com/maps/@-23.41,-51.92,17z"), { lat: -23.41, lon: -51.92 });
  assert.deepEqual(coordsDeEnlace("-23.4, -51.9"), { lat: -23.4, lon: -51.9 });
});

test("!3d!4d (el lugar) gana sobre @ (el centro de la vista)", () => {
  const url = "https://www.google.com/maps/place/X/@-23.40,-51.90,17z/data=!3m1!4b1!4m6!3m5!8m2!3d-23.4123!4d-51.9234";
  assert.deepEqual(coordsDeEnlace(url), { lat: -23.4123, lon: -51.9234 });
});

test("sin coordenadas o enlace corto: null", () => {
  assert.equal(coordsDeEnlace("https://maps.app.goo.gl/abc123"), null);
  assert.equal(coordsDeEnlace("Rua X, 100"), null);
  assert.equal(coordsDeEnlace(""), null);
});

test("enParana", () => {
  assert.equal(enParana({ lat: -23.42, lon: -51.93 }), true);
  assert.equal(enParana({ lat: -51.93, lon: -23.42 }), false); // al revés
  assert.equal(enParana({ lat: -25.43, lon: -49.27 }), false); // Curitiba: fuera del rango aproximado
});
