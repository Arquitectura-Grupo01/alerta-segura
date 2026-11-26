/* Alerta Segura: preferencias de lectura (tamaño del texto y alto contraste).

   Se guardan en localStorage y no en una cookie: la única cookie del sitio es la de CSRF y
   no queremos agregar otra. Este archivo se carga en el <head> sin defer, a propósito: aplica
   las preferencias antes de que el navegador pinte la página y así no hay un destello con el
   tamaño o los colores por defecto. Las preferencias son atributos de <html>
   (data-texto y data-contraste) que sitio.css lee. Aquí no se usan cookies.

   El panel de ajustes (base.html, [data-ajustes]) empieza oculto y solo se muestra si este
   script corre: sin JavaScript no podría guardar nada. */
(function () {
  "use strict";

  var raiz = document.documentElement;
  var TAMANOS = ["normal", "grande", "muy-grande"];
  var CONTRASTES = ["normal", "alto"];
  var CLAVE_TEXTO = "alerta.texto";
  var CLAVE_CONTRASTE = "alerta.contraste";
  var NOMBRES_TAMANO = { "normal": "normal", "grande": "grande", "muy-grande": "muy grande" };

  // localStorage puede lanzar error (navegación privada, almacenamiento bloqueado).
  // En ese caso las preferencias valen solo para esta página.
  function leer(clave) {
    try { return window.localStorage.getItem(clave); } catch (error) { return null; }
  }

  function guardar(clave, valor) {
    try { window.localStorage.setItem(clave, valor); } catch (error) { /* sin almacenamiento */ }
  }

  function valido(valor, lista) {
    return lista.indexOf(valor) !== -1 ? valor : "normal";
  }

  function aplicar(atributo, valor) {
    if (valor === "normal") raiz.removeAttribute(atributo);
    else raiz.setAttribute(atributo, valor);
  }

  var texto = valido(leer(CLAVE_TEXTO), TAMANOS);
  var contraste = valido(leer(CLAVE_CONTRASTE), CONTRASTES);
  aplicar("data-texto", texto);
  aplicar("data-contraste", contraste);

  function montarPanel() {
    var ajustes = document.querySelector("[data-ajustes]");
    if (!ajustes) return;

    var abrir = ajustes.querySelector("[data-ajustes-abrir]");
    var panel = ajustes.querySelector("[data-ajustes-panel]");
    var estado = ajustes.querySelector("[data-ajustes-estado]");
    var opcionesTexto = ajustes.querySelectorAll("[data-texto-opcion]");
    var opcionContraste = ajustes.querySelector("[data-contraste-opcion]");

    function marcar() {
      for (var i = 0; i < opcionesTexto.length; i++) {
        var activa = opcionesTexto[i].getAttribute("data-texto-opcion") === texto;
        opcionesTexto[i].setAttribute("aria-pressed", activa ? "true" : "false");
      }
      opcionContraste.setAttribute("aria-pressed", contraste === "alto" ? "true" : "false");
    }

    function cerrar(devolverFoco) {
      panel.hidden = true;
      abrir.setAttribute("aria-expanded", "false");
      if (devolverFoco) abrir.focus();
    }

    ajustes.hidden = false;
    marcar();

    abrir.addEventListener("click", function () {
      var abierto = panel.hidden;
      panel.hidden = !abierto;
      abrir.setAttribute("aria-expanded", abierto ? "true" : "false");
    });

    for (var i = 0; i < opcionesTexto.length; i++) {
      opcionesTexto[i].addEventListener("click", function (evento) {
        texto = valido(evento.currentTarget.getAttribute("data-texto-opcion"), TAMANOS);
        aplicar("data-texto", texto);
        guardar(CLAVE_TEXTO, texto);
        marcar();
        estado.textContent = "Tamaño del texto: " + NOMBRES_TAMANO[texto] + ".";
      });
    }

    opcionContraste.addEventListener("click", function () {
      contraste = contraste === "alto" ? "normal" : "alto";
      aplicar("data-contraste", contraste);
      guardar(CLAVE_CONTRASTE, contraste);
      marcar();
      estado.textContent = contraste === "alto" ? "Alto contraste activado." : "Alto contraste desactivado.";
    });

    // Escape cierra el panel y devuelve el foco al botón que lo abrió.
    ajustes.addEventListener("keydown", function (evento) {
      if (evento.key === "Escape" && !panel.hidden) {
        evento.stopPropagation();
        cerrar(true);
      }
    });

    // Un clic fuera del panel lo cierra.
    document.addEventListener("click", function (evento) {
      if (!panel.hidden && !ajustes.contains(evento.target)) cerrar(false);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", montarPanel);
  else montarPanel();
})();
