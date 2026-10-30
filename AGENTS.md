# AGENTS.md

Reglas para cualquier agente que programe en este repo. Si una regla choca con lo que pide la persona, pregunta antes de actuar.

**El repo es público.** No escribas en él datos personales reales, valores de variables de entorno, URLs de los ambientes desplegados ni la ruta real del admin. En tests y ejemplos usa datos ficticios.

Alerta Segura analiza enlaces, capturas, códigos QR y textos que recibió un ciudadano, y devuelve un nivel de riesgo, los motivos en lenguaje cotidiano y una acción. Es un monolito modular en Django 5.2 con PostgreSQL, Celery y Redis. Hoy solo `core` tiene código; las otras cinco apps son estructura vacía.

`docs/requisitos.md` dice qué hace la plataforma, con todos sus valores; `docs/seguridad.md`, sus riesgos y pruebas obligatorias; `docs/plan.md`, las tareas numeradas; y `docs/decisiones.md`, lo que decidió el equipo, que manda sobre lo demás. Cuando te pidan una tarea por su número, léela completa en el plan junto con las secciones de requisitos y seguridad que toca. Si es una propuesta nueva o algo que requiere acuerdo del equipo y no figura en `docs/decisiones.md`, pregunta antes de programarlo.

## Comandos

Python 3.12. Son los mismos que corre `.github/workflows/pipeline.yml`.

```bash
pip install -r requirements-dev.txt
cp .env.example .env        # manage.py y pytest leen .env
docker compose up -d db     # PostgreSQL 16 con el rol de la app, sin superusuario
ruff check .
python manage.py makemigrations --check --dry-run
pytest --cov                # falla con cobertura menor al 70 % en core, motor e inteligencia
DJANGO_SETTINGS_MODULE=config.settings.prod DJANGO_ALLOWED_HOSTS=ci.example \
DJANGO_SECRET_KEY="$(python -c 'from django.core.management.utils import get_random_secret_key as g; print(g())')" \
python manage.py check --deploy --fail-level WARNING
bandit -r . -x ./tests,./.venv -ll -ii
semgrep scan --config p/python --config p/django --error --metrics=off
pip-audit -r requirements.txt
docker build -t alerta-segura:ci .
```

## Cuándo una tarea está terminada

- Todos los comandos de arriba pasan en local y los cinco jobs del PR (`calidad`, `sast`, `dependencias`, `secretos`, `imagen`) están en verde.
- Todo cambio de comportamiento trae al menos un test nuevo o modificado en `tests/`. pytest solo recolecta esa carpeta.
- Los tests que usan la base de datos llevan `@pytest.mark.django_db`. Un marcador nuevo se registra en `pyproject.toml`, porque corre con `--strict-markers`.
- Todo modelo nuevo o modificado incluye su migración en el mismo commit.
- La primera vez que una app recibe modelos, vistas o tareas, se agrega a `INSTALLED_APPS` en `config/settings/base.py`. Hoy solo está `core`, y `makemigrations --check` no ve las apps sin registrar.
- Se cumple la condición «Terminada cuando» de la tarea en `docs/plan.md`. Los controles que el CI todavía no tiene (accesibilidad, datos personales en claro, prompt injection) llegan con su tarea.

## Apps

| App | Va aquí | No va aquí |
|---|---|---|
| `core` | capa de entrada (validación de tipo y tamaño, rate limit, CSRF, CSP), caché de resultados, auditoría, `/health/`, `/ready/`, `net.py` | puntaje, adaptadores de proveedores |
| `analisis` | orquestador (tipo de entrada, consulta a la caché, tareas de Celery) y analizadores de URL, imagen (OCR y QR) y texto | cálculo del nivel, llamadas directas a proveedores |
| `inteligencia` | un adaptador por proveedor de Threat Intelligence con interfaz común, timeout por fuente y circuit breaker | escritura en la reputación o en estadísticas |
| `motor` | motor de riesgo, motor de explicación, base de reputación propia; es la única app que guarda resultados en la caché | vistas, llamadas de red |
| `catalogo` | marcas, dominios oficiales y variantes de suplantación, con versión y auditoría | lógica de puntaje |
| `curacion` | cola de reportes, campañas, invalidación de resultados en la caché | cambiar un veredicto a partir de un reporte ciudadano |

Django no impone la separación entre apps, así que la sostienen estos imports permitidos. Ninguno va en sentido contrario, para que no haya ciclos:
- `core` no importa de ninguna otra app.
- `catalogo` e `inteligencia` importan solo de `core`.
- `motor` importa de `core` y `catalogo`.
- `analisis` importa de `core`, `catalogo`, `inteligencia` y `motor`.
- `curacion` puede importar de todas; ninguna importa de `curacion`.

## Orden de trabajo

- El orden es el de `docs/plan.md`: base compartida, enlaces, interfaz y consola en v1; capturas y QR en v2; texto, reglas y campañas en v3.
- Consulta de números telefónicos: el equipo todavía no decide cómo será. No crees modelos, rutas ni código para ella.
- Registro estadístico y panel de estadísticas: van al final. Mientras tanto, cada análisis guarda fecha, tipo de entrada, veredicto, puntaje y dominio en campos separados, para poder registrarlo después de forma anónima.

## Nombres e idioma

- Dominio, docstrings, comentarios y nombres de tests en español, como en `core/net.py` (`DestinoBloqueado`, `resolver_y_validar`). Lo que impone Django o Python queda en inglés (`models.py`, `views.py`, `settings`). Las apps van en español y sin tilde (`analisis`, `curacion`).
- Tests en `tests/test_<tema>.py` con funciones `test_<comportamiento>`, por ejemplo `test_bloquea_redes_internas`.
- Lo que cambia entre ambientes se lee con `env()` en `config/settings/`, y su nombre se agrega a `.env.example` con un valor de ejemplo que no sea secreto.
- Los controles de seguridad no son configuración: `DEBUG`, la CSP, el TLS hacia PostgreSQL y la política de salida de `core/net.py` quedan fijos en el código. Nunca los conviertas en variables de entorno.

## Seguridad

- SQL solo con el ORM o con `cursor.execute(sql, params)`. Prohibido armar SQL con `+`, f-strings, `%` o `.format`, y prohibido `.extra()`.
- Prohibido `|safe`, `mark_safe` y `{% autoescape off %}` sobre texto del ciudadano o del modelo de lenguaje. La salida del modelo se muestra como texto plano.
- Prohibido `@csrf_exempt`.
- Una respuesta de error nunca incluye el detalle de la excepción. Sigue el patrón de `/ready/`.
- Ningún secreto, token ni credencial en código, tests o fixtures. gitleaks revisa todo el historial.

Conexiones salientes:
- `httpx`, o cualquier cliente HTTP, solo se importa en `core/net.py`. Las demás apps, `inteligencia` incluida, usan las funciones de ese módulo. Así los controles se aplican en un solo lugar.
- Cada URL y cada redirección pasa por `validar_url` antes de conectar: exige `http` o `https`, puerto 80 o 443, y rechaza el host si alguna de sus IP no es pública. Máximo 3 redirecciones, timeout de conexión de 2 s y respuesta de 2 MB; usa las constantes de `core/net.py`, no copies los valores.
- La conexión va a la IP ya validada con el header `Host` original; una segunda resolución DNS permitiría DNS rebinding. Cada destino bloqueado se registra en la auditoría.

Datos del ciudadano:
- Antes de guardar o loguear un texto, enmascara DNI, números de cuenta y de tarjeta, correos, teléfonos y montos. El contenido crudo nunca va a los logs.
- Las capturas no se guardan: nada de `ImageField` ni `FileField` para ellas. El archivo temporal se borra al terminar, también si el análisis falla.
- Uploads: solo JPG, PNG o WEBP de 5 MB como máximo, con el tipo validado por la firma del archivo y no por la extensión.
- No guardes direcciones IP. El rate limit guarda solo un HMAC de la IP, con vigencia de una hora.
- La URL completa se guarda solo con veredicto Peligroso o Peligro alto; si no, solo el dominio. Una URL puede llevar tokens personales.
- El ciudadano no tiene registro, login ni más cookies que la de CSRF.

Motor, caché y fuentes externas. Cada regla de esta lista tiene su propio test:
- Rate limit: 30 análisis por IP cada 10 minutos, después HTTP 429. Un acierto de caché también pasa por la capa de entrada y el rate limit.
- La clave de caché es el SHA-256 de la URL normalizada más la versión de reglas. Vigencia: 72 h para Peligroso y Peligro alto, 24 h para Ten cuidado, 6 h para Seguro y sin información.
- Las respuestas crudas de terceros solo viven en la caché técnica, 24 h como máximo, y nunca pasan a la reputación ni a estadísticas. Sus términos de uso lo prohíben.
- Un reporte ciudadano entra como pendiente y nunca cambia un veredicto ni la caché. Máximo 10 reportes por hora por origen.
- Una fuente caída, que responde "desconocido" o con un análisis de más de 24 h, no prueba que el contenido esté limpio.
- Nunca se emite Seguro con cobertura menor al 70 % ni para un dominio de menos de 30 días. En esos casos el mínimo es Ten cuidado.
- El modelo de lenguaje está desactivado por defecto. Si se habilita, su salida se valida contra un esquema JSON, suma 10 puntos como máximo, nunca resta, no cuenta para la cobertura y el puntaje final no pasa de 100.
- Cada veredicto guarda la versión de reglas, las señales, los pesos y el puntaje. Con las mismas señales y la misma versión, el puntaje es idéntico.

Consola interna:
- Toda vista exige un rol (analista o administrador) y está denegada por defecto. Cada ruta interna nueva tiene un test que la llama sin sesión y espera 302 o 403.
- Login con TOTP, bloqueo de 15 minutos tras 5 intentos fallidos y sesión que expira a los 30 minutos sin actividad.
- La auditoría es de solo agregar: ninguna vista edita ni borra eventos.

## Interfaz

- Templates de Django con Tailwind CSS compilado y purgado. Sin React, Next.js ni otra SPA. El JavaScript es mínimo, propio y va en archivos estáticos: nada de `<script>` en línea, `<style>` en línea ni atributos `on*` o `style`, porque la CSP de `config/settings/base.py` los bloquea.
- Pensada primero para el celular. La primera carga pesa 200 KB o menos comprimida.
- Cuatro niveles con estos textos exactos, siempre con color, ícono y palabra a la vez. Nunca "100 % seguro"; en el nivel más bajo se aclara que la plataforma orienta y no garantiza.
- Colores: Seguro `#467A5E`, Ten cuidado `#8F6824`, Peligroso `#B4533F`, Peligro alto `#8E2F2A`, texto `#162A38`, fondo `#F7F7F5` y tarjetas blancas. Cada color tiene contraste de 4,5:1 o más sobre ambos fondos (WCAG AA); uno nuevo o modificado también debe tenerlo.
- La pantalla de resultado sigue este orden: nivel, de 3 a 5 motivos, "Qué hacer" con al menos una acción y el enlace "Ver detalle técnico", colapsado por defecto. Se envía con `Cache-Control: no-store`.
- Desde Ten cuidado se muestra la guía para quien ya hizo clic, entregó datos o pagó. Esa guía no pide ningún dato.
- El destino de un QR se muestra como texto no clicable.
- Textos sin jerga: "página falsa" en lugar de "phishing", "web creada hace 3 días" en lugar de "dominio reciente".
- Áreas táctiles de 48 × 48 px como mínimo y navegación por teclado con foco visible.
- Sin degradados, glassmorphism, emojis como íconos, hero con dos botones ni textos de relleno como "Bienvenido a la plataforma".

## Ramas, commits y PR

1. Con `main` al día (`git switch main` y `git pull`), crea la rama con `git switch -c feature/<descripcion-corta>`. Todo cambio va en una rama `feature/`.
2. Commits con formato `tipo: descripción` en español, con tipo `feat`, `fix`, `docs` o `chore`. Ejemplo del historial: `feat: configura entorno y base de datos`.
3. Antes de cada push corre la sección Comandos. Después, `git push -u origin feature/<descripcion-corta>` y un PR hacia `main` que diga qué cambia, por qué y qué comandos corriste con su resultado. Si algo no se pudo verificar, el PR lo dice.
4. Los cinco jobs del PR son obligatorios. Si uno falla, corrige en la misma rama.
5. Otro integrante aprueba. Un push nuevo descarta las aprobaciones anteriores.
6. Al integrar en `main`, el pipeline despliega a Dev, corre smoke test y DAST y, si pasan, despliega a producción sin aprobación manual. La aprobación del PR es la única revisión humana.

Puedes crear commits en tu rama `feature/`. Push y PR, solo cuando la persona lo pida. Nunca hagas push a `main`, `--force` ni merge de un PR, porque un merge llega solo a producción. Solo el pipeline despliega; nunca dispares un despliegue a mano.

## Pide permiso antes de

- Agregar, quitar o cambiar la versión de una dependencia en `requirements*.txt`, o instalar paquetes del sistema en el `Dockerfile` (incluido descomentar Tesseract y zbar). Cada paquete suma superficie que pip-audit y Trivy escanean.
- Escribir migraciones que borran o transforman datos (`RemoveField`, `DeleteModel`, cambios de tipo, `RunSQL`, `RunPython`) o que requieren superusuario, como `CREATE EXTENSION`: la app usa un rol sin superusuario, igual que en producción.
- Cambiar `.github/`, `config/settings/prod.py`, la CSP, la política de salida de `core/net.py`, `SILENCED_SYSTEM_CHECKS` o los archivos de `scripts/`.
- Crear una app o mover responsabilidades entre apps.
- Agregar un proveedor externo, cuya licencia y cuota hay que documentar, o habilitar el modelo de lenguaje.

## Cómo escribir

Vale para documentación, comentarios, commits, PR y textos de interfaz. Los bloques de código quedan exentos.

- Español neutro, frases cortas y voz activa. Los términos que la industria usa en inglés quedan en inglés.
- Sin raya (U+2014) ni semirraya (U+2013). Tampoco las reemplaces por un guion entre espacios, dos puntos o paréntesis que cumplan la misma función: reescribe la frase.
- Sin punto medio (U+00B7), viñeta (U+2022) ni barra vertical como separadores en línea. Usa una frase o una lista.
- Sin relleno: robusto, escalable, potente, integral, de vanguardia, sin fisuras, solución, ecosistema, aprovechar, potenciar, "cabe destacar", "es importante mencionar", "en resumen". Una cualidad se afirma solo si algo del repo la respalda.
- Sin emojis, badges decorativos, banners, firmas, enumeraciones de tres adjetivos, negrita decorativa, encabezados sobre una sola línea, listas de un elemento ni cierres que resumen lo ya dicho.
