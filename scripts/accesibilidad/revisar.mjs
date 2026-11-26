// Revisión de accesibilidad de las páginas de Alerta Segura (tarea 30).
//
// Uso: node revisar.mjs <carpeta con las páginas .html> <static/js/accesibilidad.js>
//
// 1. Pasa axe-core con las reglas WCAG 2.0 y 2.1 de nivel A y AA sobre cada página.
//    axe corre sobre jsdom, que no calcula estilos ni posiciones, así que la regla
//    "color-contrast" no se puede ejecutar aquí. El contraste de la paleta lo mide
//    tests/test_accesibilidad.py, que sí corre en el CI.
// 2. Ejecuta static/js/accesibilidad.js contra cada página y comprueba que el panel de ajustes
//    guarda y aplica las preferencias, ignora valores inválidos y se cierra con Escape.
//
// Termina con código 1 si hay una sola violación o un solo fallo.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { createRequire } from "node:module";
import { JSDOM } from "jsdom";

const require = createRequire(import.meta.url);
const axeFuente = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

const [carpeta, rutaScript] = process.argv.slice(2);
if (!carpeta || !rutaScript) {
  console.error("Uso: node revisar.mjs <carpeta con páginas> <accesibilidad.js>");
  process.exit(2);
}
const scriptPropio = readFileSync(rutaScript, "utf8");
const archivos = readdirSync(carpeta).filter((nombre) => nombre.endsWith(".html")).sort();
if (archivos.length === 0) {
  console.error(`No hay páginas .html en ${carpeta}`);
  process.exit(2);
}

const ETIQUETAS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
let fallos = 0;

function fallar(pagina, mensaje) {
  fallos += 1;
  console.error(`FALLA ${pagina}: ${mensaje}`);
}

async function abrir(html, preferencias = {}) {
  const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  for (const [clave, valor] of Object.entries(preferencias)) window.localStorage.setItem(clave, valor);
  // Si la página ya terminó de cargar, el evento "load" no volvería a llegar.
  if (window.document.readyState !== "complete") {
    await new Promise((listo) => window.addEventListener("load", listo));
  }
  return window;
}

async function revisarAxe(pagina, html) {
  const window = await abrir(html);
  window.eval(axeFuente);
  const resultado = await window.axe.run(window.document, {
    runOnly: { type: "tag", values: ETIQUETAS },
    rules: { "color-contrast": { enabled: false } },
  });
  for (const violacion of resultado.violations) {
    const nodos = violacion.nodes.map((nodo) => nodo.target.join(" ")).join(" | ");
    fallar(pagina, `${violacion.id} (${violacion.impact}): ${violacion.help}. Elementos: ${nodos}`);
  }
  console.log(`${pagina}: ${resultado.violations.length} violaciones, ${resultado.passes.length} reglas cumplidas`);
  window.close();
}

function comprobar(pagina, condicion, mensaje) {
  if (!condicion) fallar(pagina, mensaje);
}

async function revisarPreferencias(pagina, html) {
  const tieneAjustes = html.includes("data-ajustes");

  // Las preferencias guardadas se aplican al cargar; un valor inválido se ignora.
  let window = await abrir(html, { "alerta.texto": "muy-grande", "alerta.contraste": "alto" });
  window.eval(scriptPropio);
  const raiz = window.document.documentElement;
  comprobar(pagina, raiz.getAttribute("data-texto") === "muy-grande", "no aplicó el texto guardado");
  comprobar(pagina, raiz.getAttribute("data-contraste") === "alto", "no aplicó el contraste guardado");
  window.close();

  window = await abrir(html, { "alerta.texto": "gigante", "alerta.contraste": "<script>" });
  window.eval(scriptPropio);
  const limpia = window.document.documentElement;
  comprobar(pagina, !limpia.hasAttribute("data-texto"), "aceptó un tamaño inválido");
  comprobar(pagina, !limpia.hasAttribute("data-contraste"), "aceptó un contraste inválido");
  window.close();

  if (!tieneAjustes) return; // La 500 solo aplica las preferencias; no tiene panel.

  window = await abrir(html);
  const documento = window.document;
  const ajustes = documento.querySelector("[data-ajustes]");
  const abrirPanel = documento.querySelector("[data-ajustes-abrir]");
  const panel = documento.querySelector("[data-ajustes-panel]");
  comprobar(pagina, ajustes.hidden, "el panel debe estar oculto antes de que corra el JavaScript");
  window.eval(scriptPropio);
  comprobar(pagina, !ajustes.hidden, "el panel no apareció al correr el JavaScript");

  abrirPanel.click();
  comprobar(pagina, !panel.hidden && abrirPanel.getAttribute("aria-expanded") === "true", "no abrió el panel");

  documento.querySelector('[data-texto-opcion="grande"]').click();
  comprobar(pagina, documento.documentElement.getAttribute("data-texto") === "grande", "no aplicó texto grande");
  comprobar(pagina, window.localStorage.getItem("alerta.texto") === "grande", "no guardó el texto");
  comprobar(
    pagina,
    documento.querySelector('[data-texto-opcion="grande"]').getAttribute("aria-pressed") === "true",
    "no marcó la opción activa",
  );

  documento.querySelector("[data-contraste-opcion]").click();
  comprobar(pagina, documento.documentElement.getAttribute("data-contraste") === "alto", "no activó el alto contraste");
  comprobar(pagina, window.localStorage.getItem("alerta.contraste") === "alto", "no guardó el contraste");

  documento.querySelector("[data-contraste-opcion]").click();
  comprobar(pagina, !documento.documentElement.hasAttribute("data-contraste"), "no desactivó el alto contraste");

  documento.querySelector('[data-texto-opcion="normal"]').click();
  comprobar(pagina, !documento.documentElement.hasAttribute("data-texto"), "no volvió al texto normal");

  panel.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  comprobar(pagina, panel.hidden, "Escape no cerró el panel");
  comprobar(pagina, documento.activeElement === abrirPanel, "Escape no devolvió el foco al botón");
  window.close();
}

for (const archivo of archivos) {
  const html = readFileSync(join(carpeta, archivo), "utf8");
  await revisarAxe(archivo, html);
  await revisarPreferencias(archivo, html);
}

// La 500 es independiente de base.html y no la renderiza una vista: se revisa aparte.
if (fallos > 0) {
  console.error(`\n${fallos} problema(s) de accesibilidad.`);
  process.exit(1);
}
console.log(`\n${archivos.length} páginas sin violaciones de WCAG 2.1 AA revisables sin navegador.`);
