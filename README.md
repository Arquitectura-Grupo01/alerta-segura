# Alerta Segura

Alerta Segura es una plataforma web para que cualquier persona en el Perú verifique, antes de actuar, si un enlace, una captura de pantalla, un código QR o el texto de un mensaje que recibió puede ser una estafa. Devuelve un nivel de riesgo, los motivos en lenguaje cotidiano y una acción recomendada. El ciudadano no crea cuenta ni inicia sesión; solo el equipo interno entra a una consola con doble factor. Es el trabajo final del curso Arquitectura de Aplicaciones de la UPC.

Las reglas de contribución, para personas y agentes de IA, están en [AGENTS.md](AGENTS.md). Lo que la plataforma debe hacer, sus riesgos y pruebas de seguridad, el plan de tareas numeradas y las decisiones del equipo están en [docs/](docs/).

## Estado actual

El repositorio contiene la base del sistema, el pipeline y un primer análisis de enlaces, todavía sin catálogo de marcas ni consola interna.

Implementado:

- Orquestador, registro y caché de resultados. `/analizar` busca primero un resultado vigente; si no hay, analiza, lo guarda y redirige a `/resultado/<uuid>/`, que tiene un identificador aleatorio. Cada consulta deja una fila en `Analisis` con el dominio, el nivel, el puntaje, las señales y el estado de cada fuente. La URL completa se guarda solo con Peligroso o Peligro alto. La caché (`core/resultados.py` lee y `motor/cache.py` escribe) usa como clave el SHA-256 de la URL normalizada más la versión de reglas y dura 72 h, 24 h o 6 h según el nivel. Invalidar un dominio sube un contador en una tabla y deja sin efecto todos sus resultados. Una entrada que no coincide con sus señales se descarta. `manage.py cargar_datos_demo` crea análisis ficticios.
- Análisis de enlaces (`analisis/` y `motor/`). `/analizar` lee el enlace como lo lee el navegador y lo sigue desde el servidor con `pedir_url`, hasta 3 redirecciones en total contando las de `<meta http-equiv="refresh">` y la cabecera `Refresh`. Revisa con heurísticas locales la dirección pegada y la de destino, y busca por RDAP la edad de las dos webs. Manda la más nueva; un dominio sin RDAP, como los `.pe`, un acortador o un alojamiento compartido como netlify.app no dan edad. `motor` calcula el nivel y lo explica con 3 a 5 motivos. Sin fuentes externas la cobertura no llega a 70 % y el resultado nunca es Seguro.
- Interfaz común de las fuentes externas (`inteligencia/fuentes.py`). Cada proveedor es una subclase de `Fuente` que responde detección, sin detecciones, desconocido o falló. Sin detecciones exige un análisis vigente del proveedor, con un plazo que depende de la edad de la web; si es más viejo, cuenta como desconocido. La clase base pone el circuit breaker, que se abre al tercer fallo seguido y reintenta a los 5 minutos, la cuota diaria y por minuto y el presupuesto global por hora. `consultar_fuentes` las llama en paralelo con un plazo total, y el análisis sigue aunque fallen todas. Las respuestas crudas van a una caché técnica aparte, 24 h como máximo, y `inteligencia/claves.py` quita las claves de API de los logs. El detalle técnico del resultado dice el estado de cada fuente consultada.
- Seis fuentes externas, una por archivo en `inteligencia/`. Cada una se activa al definir su clave y sin ella se omite. Ver [Fuentes externas](#fuentes-externas).
- Botón «Avisar a un familiar» en el resultado, desde Ten cuidado (`static/js/resultado.js`). Abre el menú de compartir del celular, o copia el texto donde no existe, con el nivel, el dominio desactivado (`ejemplo[.]com`) y la primera acción. Nunca comparte el enlace.
- Guía «Ya hice clic, di mis datos o pagué» en `/guia/` (`templates/guia.html`). Pasos numerados para cinco situaciones, qué pruebas guardar y dónde denunciar. No tiene formularios ni pide datos. Enlaza solo a sitios oficiales verificados, con la fecha en un comentario de la plantilla, y no trae teléfonos de entidades porque no se pudieron verificar. El inicio y todo resultado desde Ten cuidado llevan a ella.
- `/health/` responde si el proceso está vivo y devuelve el ambiente y el commit desplegado. `/ready/` confirma que la aplicación alcanza la base de datos.
- `templates/400.html`, `403.html`, `403_csrf.html`, `404.html`, `429.html` y `500.html` son las páginas de error, en español sencillo, con el diseño del sitio y un enlace al inicio. Ninguna muestra trazas, rutas ni el mensaje de la excepción. Las cuatro primeras extienden `error_base.html`; la 500 es independiente porque Django la renderiza sin contexto y la causa del error puede ser la base de datos.
- `core/entrada.py` es la capa de entrada. `limitar` pone un tope por IP a `/analizar` (30 análisis cada 10 minutos) y responde 429 con `Retry-After` antes de resolver DNS o abrir conexiones. La IP sale de `X-Forwarded-For` según `ENTRADA_PROXIES_CONFIABLES` (2 en producción, 0 en los demás ambientes), se agrupa por /64 en IPv6 y solo se guarda como HMAC con expiración. `consumir_presupuesto_externo` limita las consultas a servicios externos por hora. `LimiteDeTamanoMiddleware` rechaza con 413 las solicitudes de más de 5 MB y con 400 un `Content-Length` inválido, y Django corta con 400 los formularios de más de 128 KB.
- `core/net.py` contiene la política de salida a internet. `validar_url` exige `http` o `https` y puerto 80 o 443, y rechaza el host si alguna de sus IP no es pública: redes privadas, loopback, link-local, metadatos de nube, CGNAT, multicast o IPv4 dentro de IPv6. `pedir_url` es la única función que sale a internet y el único lugar donde se importa `httpx`: valida cada destino, se conecta a la IP ya validada con el `Host` y el SNI originales, sigue hasta 3 redirecciones validando cada salto, corta la conexión a los 2 s, la solicitud completa a los 10 s aunque el servidor mande las cabeceras de a un byte, y la respuesta a los 2 MB ya descomprimidos. Quien la llama puede bajar el máximo de redirecciones y el plazo, nunca subirlos. Solo acepta gzip y lo descomprime con tope. GET, HEAD y POST, sin cookies, sin credenciales de la URL y sin leer proxies del entorno. Cada destino bloqueado deja un evento de auditoría sin host ni IP, y `httpx` no escribe las URLs pedidas en el log. Las fuentes externas pueden mandar cabeceras propias y un formulario por POST; en ese caso no se sigue ninguna redirección, para que su clave nunca llegue a otro servidor.
- Cabecera Content-Security-Policy en todas las respuestas (`core/middleware.py`), sin scripts ni estilos en línea.
- Cabeceras de seguridad fijas en todas las respuestas (`core/middleware.py`): Permissions-Policy, que solo deja la cámara del propio sitio, Cross-Origin-Opener-Policy, Cross-Origin-Embedder-Policy y Cross-Origin-Resource-Policy. Toda respuesta sin política de caché propia sale con `Cache-Control: no-store`, y los estáticos no llevan `Access-Control-Allow-Origin`.
- La cookie de CSRF es HttpOnly. El JavaScript propio no la lee: si hace un POST, toma el token del formulario.
- Settings por ambiente (`dev`, `test`, `prod`) leídos de variables de entorno. `prod` activa la redirección a HTTPS, cookies `Secure`, HSTS, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy` y TLS obligatorio hacia PostgreSQL.
- Admin de Django en una ruta configurable.
- Celery configurado con Redis como broker, sin tareas definidas.
- Caché compartida entre procesos (`config/settings/cache.py`): Redis en local y una tabla de PostgreSQL con tope de 5000 filas en Render. La caché técnica de las fuentes externas y la de resultados van en otras dos tablas, para que no desplacen a los contadores del rate limit. `scripts/entrypoint.sh` crea la tabla con `createcachetable` al arrancar. Los tests usan `LocMemCache`.
- Imagen Docker multi-stage que se ejecuta con un usuario sin privilegios. En local y en el CI la aplicación entra a PostgreSQL con un rol sin superusuario.
- Auditoría de solo agregar (`core/models.py`, `core/auditoria.py`): el modelo `EventoAuditoria` rechaza editar y borrar, también en bloque, y el admin lo muestra solo de lectura. Las demás apps registran con `registrar_evento(tipo, usuario=..., objeto=..., motivo=..., detalle=...)`, que enmascara los textos y rechaza IP y URLs. Todavía no hay trigger en PostgreSQL ni cadena de hashes.
- Enmascarado de datos personales (`core/enmascarado.py`): `enmascarar(texto)` reemplaza de forma irreversible tarjetas, CCI, cuentas, teléfonos, DNI, correos y montos por marcadores como `[DNI]`. Normaliza con NFKC y quita caracteres invisibles para que no se esquive, corta el texto a 20 000 caracteres y usa expresiones sin cuantificadores anidados. `FiltroEnmascarado` lo aplica a todo mensaje de log, a sus argumentos y a las trazas, y `registrar_evento` lo aplica a lo que guarda.
- Pipeline de GitHub Actions con tests, cobertura, análisis estático, auditoría de dependencias, detección de secretos, escaneo de la imagen, despliegue a Dev y Prod, smoke test y DAST.
- 969 tests en `tests/` sobre los endpoints de salud, la página de inicio, la CSP y las demás cabeceras de seguridad, la política de salida, la capa de entrada, las páginas de error, la caché, la auditoría, el enmascarado, las conexiones salientes, el análisis de enlaces, las fuentes externas, la guía, el orquestador con su caché y los settings.

Planificado según el informe del Hito 1, sin código todavía:

| Fase | Alcance |
|---|---|
| v1 | Análisis de enlaces con fuentes de Threat Intelligence, análisis del dominio, comparación con el catálogo de marcas peruanas, motor de riesgo y de explicación, caché de resultados, detalle técnico opcional, guía para quien ya interactuó, reporte de desacuerdo, consola interna con MFA y roles, curación, invalidación de resultados y auditoría |
| v2 | Análisis de capturas de pantalla (OCR) y de códigos QR |
| v3 | Análisis del texto del mensaje con reglas propias, agrupación en campañas y reglas con versiones |
| Al final | Registro estadístico anonimizado y panel de estadísticas. Consulta de números telefónicos, cuyo diseño el equipo todavía no decide |

El informe ubicaba el registro estadístico, el panel y la consulta de números dentro de v1 a v3; el equipo los movió al final. El modelo de lenguaje es opcional, queda desactivado por defecto y su habilitación se evaluará después del MVP.

## Arquitectura

Monolito modular en Django 5.2: una sola aplicación, una sola imagen Docker y seis apps con responsabilidades separadas. Un análisis entra por `core`; `analisis` consulta primero la caché y luego los analizadores y las fuentes externas; `motor` decide el nivel. Ninguna fuente externa decide el veredicto por sí sola.

| App | Responsabilidad | Estado |
|---|---|---|
| `core` | Capa de entrada (validación, rate limit, CSRF, CSP), caché de resultados, auditoría, salud y validación de destinos de red | `/health/`, `/ready/`, `net.py` y la CSP |
| `analisis` | Orquesta cada análisis y contiene los analizadores de URL, imagen y texto | Analizador de enlaces: normalización, heurísticas, redirecciones y edad del dominio |
| `inteligencia` | Un adaptador por proveedor de Threat Intelligence, con timeout por fuente y circuit breaker | Interfaz común y seis fuentes externas |
| `motor` | Motor de riesgo, motor de explicación y base de reputación propia | Motor de riesgo y motor de explicación |
| `catalogo` | Marcas peruanas, dominios oficiales y variantes de suplantación, con versiones | Sin implementar |
| `curacion` | Cola de reportes, campañas e invalidación de resultados | Sin implementar |

`catalogo` y `curacion` tienen solo su estructura. Ellas, `inteligencia` y `motor`, que no tienen modelos, no están en `INSTALLED_APPS`.

En la nube la aplicación corre en Render, con dos servicios (Dev y Prod) que usan la misma imagen, y PostgreSQL en Neon. El plan gratuito de Render no tiene workers, por eso allí Celery corre en modo eager (`CELERY_EAGER`). En local, `docker-compose.yml` levanta PostgreSQL, Redis, la aplicación y un worker de Celery.

## Fuentes externas

Cada fuente se activa al definir su variable de entorno, en `.env` en local y en el panel de Render en Dev y Prod. Sin la variable, la fuente se omite y el análisis sigue con las demás. Las claves nunca van al repo.

Una lista de bloqueo solo aporta detecciones: si la dirección no figura, queda como «desconocido» y nunca como limpia. Solo VirusTotal y urlscan.io pueden decir «sin detecciones», y solo con un análisis vigente: de las últimas 24 h si la web tiene menos de 30 días o no se conoce su edad, de 7 días si tiene menos de un año y de 30 días si tiene más. Si nadie analizó la dirección exacta, vale el análisis de la web completa en VirusTotal cuando ningún antivirus la marca, tiene más de un año y figura en un ranking de webs visitadas. Una sospecha cuenta desde dos fuentes; una confirmación cuenta sola. Ninguna fuente recibe una dirección para escanearla: se consultan análisis que ya existen. Las respuestas crudas viven en la caché técnica, 24 h como máximo, y nunca pasan a la reputación ni a las estadísticas.

| Fuente | Variable | Qué recibe | Qué aporta | Licencia y uso comercial | Cuota que aplica el código |
|---|---|---|---|---|---|
| Google Safe Browsing v5 | `SAFE_BROWSING_API_KEY` | 4 bytes del SHA-256 de cada forma de la dirección, nunca la URL | Página falsa o programa dañino (100) | Gratis solo para uso no comercial; para uso comercial, Web Risk API | 10 000 al día |
| URLhaus (abuse.ch) | `ABUSE_CH_AUTH_KEY` | La dirección, sin parámetros de rastreo | Distribución de programas dañinos (100) | Gratis con uso justo; un uso comercial puede requerir el plan pagado; no se redistribuye | Sin tope fijo |
| PhishTank | `PHISHTANK_APP_KEY` | La dirección, sin parámetros de rastreo | Página falsa verificada y activa (100) | Requiere registro; términos de Cisco | Sin tope publicado; un 509 cuenta como cuota agotada |
| VirusTotal | `VIRUSTOTAL_API_KEY` | El identificador de la dirección y, si hace falta, el nombre de la web | 3 motores o más que coinciden en el tipo de amenaza (100); 3 o más sin tipo, o 1 o 2 (50, una sospecha); 0 con análisis vigente de la dirección o de la web completa (sin detecciones) | API pública: prohíbe el uso comercial y solo sirve para enriquecer | 500 al día y 4 por minuto; la reputación de una web se guarda un día para no repetir la consulta |
| urlscan.io | `URLSCAN_API_KEY` | La dirección, como búsqueda de escaneos existentes, y el identificador del escaneo más reciente para leer su veredicto | Escaneo malicioso (100) o limpio y vigente (sin detecciones) | Plan gratuito limitado | 500 al día y 30 por minuto, los cupos sin cuenta |
| AbuseIPDB | `ABUSEIPDB_API_KEY` | Solo la IP del destino | IP reportada con confianza de 90 o más (50, una sospecha) | Plan gratuito limitado | 1000 al día |

Probado con claves reales el 2026-11-13, salvo PhishTank, que no tiene clave. De ahí salieron dos correcciones. Safe Browsing v5 solo responde en protobuf y contesta 400 a `alt=json`, así que el adaptador lee el mensaje sin sumar una dependencia. La búsqueda de urlscan.io no trae el veredicto: se pide el resultado del escaneo más reciente, dos consultas como máximo por análisis. Hay que revisar estos términos cada cierto tiempo: cambian sin aviso.

El detalle técnico del resultado muestra lo que contó cada fuente, en tres grupos: con evidencia, sin reportes y las que no respondieron. Según la fuente son los antivirus que la marcan, el tipo de amenaza, la marca imitada, las fechas, los reportes de abuso del servidor y dónde está alojado. Un dato que la fuente no trae no deja una línea vacía. Ese detalle es de terceros: se guarda solo en la caché técnica durante 24 h y nunca en `Analisis` ni en la caché de resultados. Pasado ese plazo, el resultado muestra solo el estado de cada fuente.

## Requisitos previos

- Python 3.12, la versión de la imagen (`python:3.12-slim`), del CI y del `target-version` de ruff en `pyproject.toml`.
- Docker con Docker Compose. Los servicios usan `postgres:16-alpine` y `redis:7-alpine`.
- Git.

Los comandos de este README están escritos para bash. En Windows funcionan en Git Bash o WSL.

## Puesta en marcha

1. Crea el archivo de variables a partir de la plantilla. `docker-compose.yml` lo exige y `.gitignore` lo deja fuera del repo.

   ```bash
   cp .env.example .env
   ```

2. Levanta los servicios. Con ellos arriba, aplica las migraciones desde otra terminal.

   ```bash
   docker compose up --build
   docker compose exec web python manage.py migrate
   ```

3. Comprueba que la aplicación responde y alcanza la base de datos.

   ```bash
   curl http://localhost:8000/health/
   curl http://localhost:8000/ready/
   ```

La primera vez que se crea el volumen `pgdata`, `scripts/init_postgres.sql` crea el rol `alerta` sin superusuario, igual que el de producción. Si tu volumen es anterior a ese script, el rol sigue siendo superusuario. Para recrearlo, borrando los datos locales:

```bash
docker compose down -v
docker compose up -d db
```

## Pruebas

Los tests corren en tu máquina contra el PostgreSQL de `docker-compose.yml`, igual que en el CI. pytest usa `config.settings.test`, recolecta solo `tests/` y toma `DJANGO_SECRET_KEY` y `DATABASE_URL` del archivo `.env`. Con `--cov` falla si la cobertura de `core`, `motor` e `inteligencia` baja del 70 % (`pyproject.toml`).

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
docker compose up -d db
pytest --cov
```

## Variables de entorno

`.env.example` es la plantilla. En Render los mismos nombres se cargan desde el panel de cada servicio. Nunca subas `.env` ni pegues valores reales en el repo.

| Variable | Uso |
|---|---|
| `DJANGO_SETTINGS_MODULE` | Módulo de `config/settings/` que se carga. `manage.py` usa `dev` si falta; Gunicorn, Celery y `scripts/entrypoint.sh` usan `prod` |
| `DJANGO_SECRET_KEY` | `SECRET_KEY` de Django. Obligatoria |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos. Solo tiene efecto en `prod`, porque `dev` y `test` los fijan |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Orígenes confiables para CSRF. Solo la lee `prod` |
| `DJANGO_ADMIN_PATH` | Ruta del admin de Django. Es configurable porque `/admin/` recibe escaneo automatizado |
| `DATABASE_URL` | Conexión a PostgreSQL. Obligatoria. Dentro de Docker Compose la reemplaza la del servicio `db` |
| `REDIS_URL` | Broker de Celery |
| `CACHE_BACKEND` | Almacén de la caché compartida: `redis` en local o `db` (tabla de PostgreSQL). Sin la variable se usa `db`, que es lo que corre en Render |
| `REDIS_CACHE_URL` | Redis de la caché cuando `CACHE_BACKEND=redis`. Usa la base 1 para que `cache.clear()` no vacíe la cola de Celery |
| `CELERY_EAGER` | Si está activa, las tareas corren dentro del proceso web y no en el worker |
| `APP_ENV` | Nombre del ambiente que devuelve `/health/` |
| `LOG_LEVEL` | Nivel del logger raíz |
| `DJANGO_HSTS_SECONDS` | Duración de HSTS en `prod` |

El código también lee `DB_CONN_MAX_AGE` (`config/settings/base.py`), `PORT` y `WEB_CONCURRENCY` (`scripts/entrypoint.sh`), que no están en la plantilla, y `RENDER_GIT_COMMIT`, que Render define en cada despliegue y `/health/` devuelve como commit.

`DEBUG`, la CSP, el TLS hacia PostgreSQL y la política de salida a internet no se configuran por variables. Son controles de seguridad fijos en `config/settings/` y `core/net.py`, iguales en todos los ambientes, para que una variable mal cargada no pueda desactivarlos.

## CI/CD

`.github/workflows/pipeline.yml` corre en cada push y pull request a `main`. Cinco jobs corren en paralelo, y según el informe del Hito 1 el ruleset de `main` los exige para integrar:

| Job | Qué valida |
|---|---|
| `calidad` | ruff, migraciones completas, pytest contra PostgreSQL con un rol sin superusuario, cobertura mínima de 70 % y `check --deploy` con los settings de producción |
| `sast` | Bandit y Semgrep con las reglas `p/python` y `p/django` |
| `dependencias` | pip-audit sobre `requirements.txt` |
| `secretos` | gitleaks sobre todo el historial |
| `imagen` | Build de la imagen y Trivy, que falla ante vulnerabilidades HIGH o CRITICAL con parche disponible |

Las herramientas de los jobs se instalan desde `requirements-dev.txt`, así que el CI y tu máquina usan las mismas versiones.

En un push a `main`, si los cinco pasan, el pipeline despliega a Dev y corre `scripts/smoke.sh`, que espera a que `/health/` devuelva el commit nuevo y revisa `/ready/` y las cabeceras de seguridad, incluida la CSP. Después corre un escaneo pasivo de OWASP ZAP con las reglas de `.github/zap-rules.tsv`; una alerta marcada como FAIL detiene el pipeline. Si todo pasa, despliega a producción sin aprobación manual y repite el smoke test. La revisión humana es la aprobación del PR antes del merge.

`.github/dependabot.yml` abre un PR mensual con las actualizaciones menores de dependencias de Python y de las acciones de GitHub. Los saltos de versión mayor quedan para decisión del equipo.

Para reproducir los jobs en local, con `.env` creado, el entorno virtual activo y el servicio `db` arriba:

```bash
# calidad
ruff check .
python manage.py makemigrations --check --dry-run
pytest --cov
DJANGO_SETTINGS_MODULE=config.settings.prod DJANGO_ALLOWED_HOSTS=ci.example \
DJANGO_SECRET_KEY="$(python -c 'from django.core.management.utils import get_random_secret_key as g; print(g())')" \
python manage.py check --deploy --fail-level WARNING

# sast
bandit -r . -x ./tests,./.venv -ll -ii
semgrep scan --config p/python --config p/django --error --metrics=off

# dependencias
pip-audit -r requirements.txt

# imagen
docker build -t alerta-segura:ci .
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:0.58.0 image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 \
  alerta-segura:ci
```

El job `secretos` descarga el binario de gitleaks 8.21.2 y ejecuta `gitleaks detect --source . --redact --verbose` sobre un clon con todo el historial.

## Estructura del repo

```text
.
├── config/                 # settings por ambiente, urls, wsgi y Celery
│   └── settings/           # base, dev, test y prod
├── core/                   # salud (views.py), política de salida (net.py) y CSP (middleware.py)
├── analisis/               # analizador de enlaces con normalización, heurísticas, redirecciones y edad
├── catalogo/               # sin implementar
├── curacion/               # sin implementar
├── inteligencia/           # interfaz común y un archivo por fuente externa
├── motor/                  # motor de riesgo y motor de explicación
├── tests/                  # pruebas de pytest
├── docs/
│   ├── requisitos.md       # qué hace la plataforma, con todos sus valores
│   ├── seguridad.md        # riesgos, controles y pruebas obligatorias
│   ├── plan.md             # tareas numeradas en orden de implementación
│   ├── decisiones.md       # decisiones del equipo y pendientes
│   └── incidentes.md       # respuesta a incidentes y restauración de la base
├── scripts/
│   ├── entrypoint.sh       # migraciones y Gunicorn al arrancar en Render
│   ├── init_postgres.sql   # rol de la app sin superusuario (local y CI)
│   └── smoke.sh            # smoke test posterior a cada despliegue
├── .github/
│   ├── dependabot.yml      # actualizaciones mensuales de dependencias
│   ├── zap-rules.tsv       # alertas de ZAP que detienen el despliegue
│   └── workflows/
│       └── pipeline.yml    # CI/CD
├── Dockerfile
├── docker-compose.yml      # solo para desarrollo local
├── .env.example            # plantilla de variables de entorno
├── pyproject.toml          # configuración de pytest, cobertura y ruff
├── requirements.txt        # dependencias de ejecución
├── requirements-dev.txt    # pruebas, lint y escáneres
├── SECURITY.md             # cómo reportar una vulnerabilidad
├── AGENTS.md               # reglas de contribución
└── CLAUDE.md               # carga AGENTS.md en Claude Code
```
