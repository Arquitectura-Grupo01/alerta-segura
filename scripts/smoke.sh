#!/usr/bin/env bash
# Uso: smoke.sh <URL_BASE> <COMMIT_ESPERADO>
#
# Espera a que el servidor sirva EXACTAMENTE el commit que se acaba de desplegar.
# Si solo se comprobara "responde 200", el test pasaría contra la versión vieja,
# que Render mantiene viva mientras construye la nueva.
set -euo pipefail

URL="${1%/}"
ESPERADO="$2"
INTENTOS="${SMOKE_INTENTOS:-60}"   # 60 x 10 s = 10 min: build de Docker + cold start del plan Free
PAUSA="${SMOKE_PAUSA:-10}"

for i in $(seq 1 "$INTENTOS"); do
  CUERPO="$(curl -fsS --max-time 15 "$URL/health/" 2>/dev/null || true)"
  COMMIT="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("commit",""))' <<<"$CUERPO" 2>/dev/null || true)"

  if [[ "$COMMIT" == "$ESPERADO" ]]; then
    echo "Versión correcta en línea ($COMMIT) tras $i intento(s)."

    CODIGO="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$URL/ready/")"
    if [[ "$CODIGO" != "200" ]]; then
      echo "FALLA: /ready/ devolvió $CODIGO. La app no alcanza la base de datos."
      exit 1
    fi
    echo "Base de datos accesible."

    CABECERAS="$(curl -sSI --max-time 15 "$URL/health/")"
    for h in "strict-transport-security" "x-content-type-options" "x-frame-options"; do
      if ! grep -qi "^$h:" <<<"$CABECERAS"; then
        echo "FALLA: falta la cabecera de seguridad '$h'."
        exit 1
      fi
    done
    echo "Cabeceras de seguridad presentes. Smoke test OK."
    exit 0
  fi

  echo "Intento $i/$INTENTOS: sirviendo '${COMMIT:-sin respuesta}', se espera '$ESPERADO'."
  sleep "$PAUSA"
done

echo "FALLA: la versión $ESPERADO no apareció en $URL en el tiempo límite."
exit 1