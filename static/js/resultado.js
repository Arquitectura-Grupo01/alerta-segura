/* Alerta Segura, página de resultado.
   Botón «Avisar a un familiar»: abre el menú de compartir del celular con un aviso corto.
   Donde no existe ese menú, copia el aviso. Sin ninguna de las dos cosas, el botón no aparece. */
(function () {
  "use strict";

  var bloque = document.querySelector("[data-avisar]");
  if (!bloque) return;

  var boton = bloque.querySelector("button");
  var estado = bloque.querySelector("[data-estado]");
  var texto = boton.getAttribute("data-texto");
  var puedeCompartir = typeof navigator.share === "function";
  var puedeCopiar = !!(navigator.clipboard && navigator.clipboard.writeText);
  if (!puedeCompartir && !puedeCopiar) return;

  bloque.hidden = false;

  function copiar() {
    navigator.clipboard.writeText(texto).then(function () {
      estado.textContent = "Copiamos el aviso. Pégalo en el chat de tu familia.";
    }, function () {
      estado.textContent = "No pudimos copiar el aviso. Cuéntaselo con tus palabras.";
    });
  }

  boton.addEventListener("click", function () {
    estado.textContent = "";
    if (!puedeCompartir) {
      copiar();
      return;
    }
    navigator.share({ text: texto }).catch(function (error) {
      // AbortError: la persona cerró el menú. No es un error.
      if (error && error.name !== "AbortError" && puedeCopiar) copiar();
    });
  });
})();
