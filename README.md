# Alerta Segura

Alerta Segura es una plataforma web para que cualquier persona en el Perú verifique, antes de actuar, si un enlace, una captura de pantalla, un código QR o el texto de un mensaje que recibió puede ser una estafa. Devuelve un nivel de riesgo, los motivos en lenguaje cotidiano y una acción recomendada. El ciudadano no crea cuenta ni inicia sesión; solo el equipo interno entra a una consola con doble factor. Es el trabajo final del curso Arquitectura de Aplicaciones de la UPC.

Las reglas de contribución, para personas y agentes de IA, están en [AGENTS.md](AGENTS.md). Lo que la plataforma debe hacer, sus riesgos y pruebas de seguridad, el plan de tareas numeradas y las decisiones del equipo están en [docs/](docs/).

## Estado actual

El repositorio contiene la base del sistema y el pipeline. La lógica de análisis todavía no tiene código.

Implementado:

- `/health/` responde si el proceso está vivo y devuelve el ambiente y el commit desplegado. `/ready/` confirma que la aplicación alcanza la base de datos.
- `core/net.py` contiene la política de salida a internet. `validar_url` exige `http` o `https` y puerto 80 o 443, y rechaza el host si alguna de sus IP no es pública: redes privadas, loopback, link-local, metadatos de nube, CGNAT, multicast o IPv4 dentro de IPv6. También fija el máximo de redirecciones, el timeout y el tamaño de respuesta que usará el analizador. Solo valida; todavía no hace conexiones.
- Cabecera Content-Security-Policy en todas las respuestas (`core/middleware.py`), sin scripts ni estilos en línea.
- Settings por ambiente (`dev`, `test`, `prod`) leídos de variables de entorno. `prod` activa la redirección a HTTPS, cookies `Secure`, HSTS, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy` y TLS obligatorio hacia PostgreSQL.
- Admin de Django en una ruta configurable.
- Celery configurado con Redis como broker, sin tareas definidas.
- Imagen Docker multi-stage que se ejecuta con un usuario sin privilegios. En local y en el CI la aplicación entra a PostgreSQL con un rol sin superusuario.
- Pipeline de GitHub Actions con tests, cobertura, análisis estático, auditoría de dependencias, detección de secretos, escaneo de la imagen, despliegue a Dev y Prod, smoke test y DAST.
- 42 tests en `tests/` sobre los endpoints de salud, la CSP, la política de salida y los settings.

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
| `analisis` | Orquesta cada análisis y contiene los analizadores de URL, imagen y texto | Sin implementar |
| `inteligencia` | Un adaptador por proveedor de Threat Intelligence, con timeout por fuente y circuit breaker | Sin implementar |
| `motor` | Motor de riesgo, motor de explicación y base de reputación propia | Sin implementar |
| `catalogo` | Marcas peruanas, dominios oficiales y variantes de suplantación, con versiones | Sin implementar |
| `curacion` | Cola de reportes, campañas e invalidación de resultados | Sin implementar |

Las cinco apps sin implementar tienen solo su estructura y todavía no están en `INSTALLED_APPS`.

En la nube la aplicación corre en Render, con dos servicios (Dev y Prod) que usan la misma imagen, y PostgreSQL en Neon. El plan gratuito de Render no tiene workers, por eso allí Celery corre en modo eager (`CELERY_EAGER`). En local, `docker-compose.yml` levanta PostgreSQL, Redis, la aplicación y un worker de Celery.

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
├── analisis/               # sin implementar
├── catalogo/               # sin implementar
├── curacion/               # sin implementar
├── inteligencia/           # sin implementar
├── motor/                  # sin implementar
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
