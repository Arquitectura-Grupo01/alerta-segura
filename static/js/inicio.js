/* Alerta Segura, página de inicio.
   Botón Pegar, extracción del enlace cuando se pega un mensaje entero
   y esqueleto del resultado mientras el servidor analiza. */
(function () {
  "use strict";

  // La escala de niveles se llena una vez cuando entra en pantalla. La transición está en el CSS.
  var escala = document.querySelector(".escala");
  if (escala && "IntersectionObserver" in window) {
    document.documentElement.classList.add("escala-animada");
    var observador = new IntersectionObserver(function (entradas) {
      if (entradas[0].isIntersecting) {
        escala.classList.add("visible");
        observador.disconnect();
      }
    }, { rootMargin: "0px 0px -12% 0px" });
    observador.observe(escala);
  }

  var form = document.getElementById("form-analisis");
  if (!form) return;

  var campo = form.querySelector("#enlace");
  var botonPegar = form.querySelector("[data-pegar]");
  var botonAnalizar = form.querySelector("[data-analizar]");
  var mensaje = document.getElementById("enlace-mensaje");
  var seccionCarga = document.getElementById("analizando");
  var dominioCarga = seccionCarga.querySelector("[data-dominio]");
  var rotuloBoton = botonAnalizar.querySelector("[data-texto]") || botonAnalizar;
  var textoBoton = rotuloBoton.textContent;
  var reducirMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)");

  // Un enlace con esquema o www, un dominio con extensión o una IPv4.
  var PATRON_ENLACE = new RegExp(
    "(?:https?://|www\\.)[^\\s<>\"'«»]+" +
    "|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,24}(?::\\d{2,5})?(?:[/?#][^\\s<>\"'«»]*)?" +
    "|\\b\\d{1,3}(?:\\.\\d{1,3}){3}(?::\\d{2,5})?(?:[/?#][^\\s<>\"'«»]*)?",
    "i"
  );

  function extraerEnlace(texto) {
    var encontrado = (texto || "").trim().match(PATRON_ENLACE);
    return encontrado ? encontrado[0].replace(/[.,;:!?)\]}»"']+$/, "") : "";
  }

  function dominioDe(enlace) {
    var conEsquema = /^[a-z][a-z0-9+.-]*:\/\//i.test(enlace) ? enlace : "https://" + enlace;
    try {
      return new URL(conEsquema).hostname;
    } catch (e) {
      return "";
    }
  }

  function avisar(texto, esError) {
    mensaje.textContent = texto;
    if (esError) {
      mensaje.setAttribute("data-tipo", "error");
      campo.setAttribute("aria-invalid", "true");
    } else {
      mensaje.removeAttribute("data-tipo");
      campo.removeAttribute("aria-invalid");
    }
  }

  function limpiarAviso() {
    mensaje.textContent = "";
    mensaje.removeAttribute("data-tipo");
    campo.removeAttribute("aria-invalid");
  }

  function usarTexto(texto) {
    var limpio = (texto || "").trim();
    if (!limpio) {
      avisar("No hay nada copiado. Copia el enlace del mensaje y vuelve a intentar.", true);
      return;
    }
    var enlace = extraerEnlace(limpio);
    if (!enlace) {
      avisar("Lo que copiaste no trae un enlace. Copia solo el enlace del mensaje.", true);
      return;
    }
    campo.value = enlace;
    if (enlace !== limpio) {
      avisar("Copiaste un mensaje entero. Tomamos solo el primer enlace que traía.", false);
    } else {
      limpiarAviso();
    }
    campo.focus();
  }

  // El botón Pegar solo aparece si el navegador permite leer el portapapeles.
  if (botonPegar && navigator.clipboard && typeof navigator.clipboard.readText === "function") {
    botonPegar.hidden = false;
    form.classList.add("con-pegar");
    botonPegar.addEventListener("click", function () {
      navigator.clipboard.readText().then(usarTexto, function () {
        avisar("No pudimos leer lo que copiaste. Mantén presionado el campo y elige Pegar.", true);
        campo.focus();
      });
    });
  }

  // Si pegan un mensaje con texto alrededor, el campo se queda solo con el enlace.
  campo.addEventListener("paste", function (evento) {
    var datos = evento.clipboardData || window.clipboardData;
    var texto = datos ? datos.getData("text") : "";
    if (texto && /\s/.test(texto.trim())) {
      evento.preventDefault();
      usarTexto(texto);
    }
  });

  campo.addEventListener("input", function () {
    if (campo.getAttribute("aria-invalid") === "true") limpiarAviso();
  });

  function mostrarCarga(dominio) {
    document.body.classList.add("cargando");
    seccionCarga.hidden = false;
    dominioCarga.textContent = dominio || "el enlace";
    campo.readOnly = true;
    if (botonPegar) botonPegar.disabled = true;
    botonAnalizar.disabled = true;
    rotuloBoton.textContent = "Analizando";
    form.setAttribute("aria-busy", "true");

    var arriba = seccionCarga.getBoundingClientRect().top;
    if (arriba > window.innerHeight * 0.55) {
      seccionCarga.scrollIntoView({
        behavior: reducirMovimiento.matches ? "auto" : "smooth",
        block: "start"
      });
    }
  }

  function ocultarCarga() {
    document.body.classList.remove("cargando");
    seccionCarga.hidden = true;
    campo.readOnly = false;
    if (botonPegar) botonPegar.disabled = false;
    botonAnalizar.disabled = false;
    rotuloBoton.textContent = textoBoton;
    form.removeAttribute("aria-busy");
  }

  form.addEventListener("submit", function (evento) {
    if (form.getAttribute("aria-busy") === "true") {
      evento.preventDefault();
      return;
    }
    var enlace = extraerEnlace(campo.value);
    if (!enlace) {
      evento.preventDefault();
      avisar(
        campo.value.trim()
          ? "Eso no parece un enlace. Cópialo completo desde el mensaje."
          : "Pega un enlace para revisarlo.",
        true
      );
      campo.focus();
      return;
    }
    campo.value = enlace;
    limpiarAviso();
    mostrarCarga(dominioDe(enlace));

    // En el prototipo no hay servidor: el esqueleto queda a la vista.
    if (form.hasAttribute("data-prototipo")) evento.preventDefault();
  });

  // Al volver con el botón Atrás, el navegador puede restaurar la página en estado de carga.
  window.addEventListener("pageshow", function (evento) {
    if (evento.persisted) ocultarCarga();
  });

  document.addEventListener("keydown", function (evento) {
    if (evento.key === "Escape" && form.hasAttribute("data-prototipo")) ocultarCarga();
  });
})();
