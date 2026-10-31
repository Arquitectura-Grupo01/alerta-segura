# Requisitos de Alerta Segura

Este documento resume lo que el proyecto se comprometió a construir en el informe del Hito 1, con los cambios que decidió el equipo. Reemplaza a los documentos del curso para programar: todo valor que necesites está aquí. Las tareas están en [plan.md](plan.md), los riesgos y las pruebas obligatorias en [seguridad.md](seguridad.md) y las decisiones en [decisiones.md](decisiones.md). Si algo de aquí choca con una decisión registrada, manda la decisión.

## Problema y personas usuarias

Las denuncias por delitos informáticos en el Perú pasaron de 4 304 en 2018 a 42 161 en 2024, y la mayoría afecta al patrimonio. El fraude busca que la persona decida en segundos si abre un enlace, paga o entrega datos. Las herramientas técnicas que existen detectan amenazas, pero responden en lenguaje de analista y no dicen qué hacer.

Alerta Segura recibe lo que llegó a la persona (un enlace, una captura, un código QR o un texto), lo analiza y devuelve un nivel de riesgo, los motivos en palabras simples y qué hacer. Es gratuita, sin registro y pensada para el celular. El 91,3 % de quienes usan internet en el Perú entra desde el celular, y menos de la mitad de las personas de 60 años o más usa internet, muchas sin experiencia digital previa. Por eso la interfaz es liviana, accesible y sin jerga.

La plataforma orienta antes de actuar. No recupera dinero, no investiga y no reemplaza al banco ni a la policía.

## Actores

| Actor | Qué hace | Autenticación |
|---|---|---|
| Ciudadano | Envía contenido, ve el resultado, abre el detalle técnico, sigue la guía si ya interactuó y reporta desacuerdo | Ninguna. Sin registro, sin login y sin datos personales |
| Analista | Cura reportes, gestiona campañas, invalida resultados y ve estadísticas | Usuario, contraseña y TOTP |
| Administrador | Lo mismo que el analista, más catálogo de marcas, reglas y pesos, cuentas internas y auditoría | Usuario, contraseña y TOTP |
| Fuentes externas y modelo de lenguaje opcional | Responden consultas del sistema y nunca inician una interacción | Claves de API por ambiente y token para el modelo |

## Alcance por fase

| Fase | Qué entra |
|---|---|
| v1 | Análisis de enlaces con fuentes externas, edad del dominio y similitud con el catálogo de marcas; motor de riesgo y de explicación; caché de resultados; detalle técnico; guía para quien ya interactuó; reporte de desacuerdo; consola interna con MFA y roles; curación; invalidación; auditoría |
| v2 | Capturas de pantalla (OCR) y códigos QR sobre el mismo flujo |
| v3 | Texto del mensaje con reglas propias, agrupación en campañas y reglas versionadas con simulación. El modelo de lenguaje es opcional y queda desactivado |
| Al final | Registro estadístico anonimizado y panel de estadísticas, con el modelo de datos diseñado para ellos desde v1. Consulta de números telefónicos, sin decidir |

Fuera del alcance:

- Recuperar dinero, bloquear cuentas, investigar responsables o eliminar contenido. Eso corresponde a los bancos y a las autoridades.
- Cuentas, login o historial para ciudadanos.
- Leer conversaciones o integrarse de forma automática con WhatsApp, Facebook o la banca. La persona decide qué envía.
- Antivirus propio, sandbox o análisis de ejecutables.
- Entrenar un modelo de IA desde cero. No hay dataset propio.
- Un servidor propio para el modelo de lenguaje en el MVP.
- Apps nativas de iOS o Android. La web responsiva cubre el MVP.
- Vender o licenciar datos.
- Integración con Truecaller, que no tiene API pública.
- Bases privadas de RENIEC o del sistema financiero, sin marco legal ni convenio.
- Microservicios y Kubernetes.
- Detectar cloaking, es decir, páginas que muestran un contenido limpio a los servidores. Es un riesgo aceptado.

## Funciones para el ciudadano

### Análisis de enlace (v1)

- Acepta URLs con o sin esquema, acortadas o con parámetros de rastreo.
- Normaliza la URL y sigue como máximo 3 redirecciones, validando cada salto.
- El enlace nunca se abre en el dispositivo de la persona.
- Si una fuente falla o agota su cuota, el análisis continúa y el resultado lo dice.

### Análisis de captura de pantalla (v2)

- Acepta JPG, PNG y WEBP de hasta 5 MB, validados por su firma.
- Extrae por OCR texto, enlaces, QR y teléfonos, y los manda al mismo flujo.
- Si no hay texto legible, lo informa.
- La imagen se borra al cerrar el análisis.

### Análisis de código QR (v2)

- Lee el QR desde una imagen o desde la cámara del navegador.
- Muestra el destino como texto no clicable antes de cualquier acción y lo analiza como un enlace.
- Si el QR trae datos de pago, advierte que se verifique el nombre del comercio.

### Análisis del texto del mensaje (v3)

- Reglas propias en español detectan urgencia, amenazas, premios o recompensas, suplantación de entidades y pedidos de credenciales o de pagos, y explican cuál se activó.
- Si el modelo de lenguaje opcional está habilitado, solo puede sumar señales. Si falla o no responde a tiempo, el análisis sigue con las reglas y lo dice.

### Consulta de número telefónico (sin decidir)

El equipo todavía no decide cómo será, así que no se programa. El informe prometió usar solo reportes propios, mostrar la cantidad de reportes y su periodo sin revelar al titular, responder «sin información» y nunca «seguro» cuando no hay reportes, y no consultar servicios de búsqueda inversa de terceros.

### Resultado

- Cuatro niveles: Seguro, Ten cuidado, Peligroso y Peligro alto, cada uno con color, ícono y palabra.
- De 3 a 5 motivos en español cotidiano y al menos una acción recomendada.
- Nunca dice «100 % seguro». En el nivel más bajo aclara que la plataforma orienta y no garantiza.
- «Ver detalle técnico» empieza colapsado y muestra las fuentes consultadas con su estado, la edad del dominio, las señales y la fecha del análisis, cada término con una explicación de una línea.

### Guía si ya interactuó

- Aparece en todo resultado de Ten cuidado o superior.
- Da pasos numerados y simples, como bloquear la tarjeta, cambiar la clave o llamar al banco por su canal oficial, y los canales oficiales de denuncia (DIVINDAT de la PNP e INDECOPI).
- No pide ningún dato.

### Reporte de desacuerdo

- Dos opciones: «sí era estafa» y «era legítimo».
- Se asocia al análisis, nunca a la persona, y entra a la cola de curación.
- Máximo 10 reportes por hora desde un mismo origen.
- Ningún reporte cambia por sí solo un veredicto.

### Resultados recientes

- Si hay un veredicto vigente para la misma URL normalizada y la misma versión de reglas, se devuelve sin consultar fuentes externas y con la leyenda «analizado hace N minutos».
- Los resultados de textos e imágenes nunca se reutilizan.

## Funciones internas

### Consola interna

- Usuario, contraseña y TOTP, en una ruta no predecible.
- Cierre de sesión manual y automático a los 30 minutos sin actividad.
- Sin autoregistro. Un administrador crea las cuentas.

### Roles

- El analista accede a curación, campañas, invalidación y estadísticas.
- El administrador accede además a catálogo, reglas, cuentas internas y auditoría.
- Toda función está denegada hasta que el rol la habilita.

### Curación

- Cola de envíos y de reportes de desacuerdo, priorizada por volumen de envíos parecidos y por nivel de riesgo.
- Permite confirmar, descartar o marcar como falso positivo.
- Cada decisión queda auditada con usuario, fecha y justificación.

### Campañas (v3)

- Agrupa envíos por similitud de texto, dominio, patrón de URL y marca suplantada.
- Cada campaña registra marca, dominios, primera y última observación y volumen.
- El analista fusiona o separa campañas. Sin observaciones en 30 días, la campaña pasa a inactiva.

### Catálogo de marcas y dominios oficiales

- Guarda la entidad, sus dominios oficiales verificados y las variantes de suplantación observadas.
- Cubre como mínimo bancos con presencia en el Perú, Yape, Plin, SUNAT, RENIEC y programas sociales.
- Todo cambio queda versionado, auditado y es reversible.

### Auditoría

- Lista filtrable por fecha, tipo de evento y usuario, con inicios de sesión, fallos, bloqueos, cambios de catálogo y de reglas, decisiones de curación y destinos bloqueados por anti-SSRF.
- Es de solo lectura. Nadie edita ni borra eventos desde la consola.

### Reglas y pesos versionados (v3)

- Cada cambio crea una versión de reglas nueva.
- La simulación recalcula los últimos 200 análisis y muestra cuántos cambiarían de nivel.
- Aplicar una versión deja sin efecto la caché anterior, porque la clave incluye la versión.

### Invalidación manual

- Por URL exacta o por dominio. La siguiente consulta recalcula todo.
- Cada invalidación queda auditada con usuario, fecha y motivo.

### Registro estadístico anonimizado (al final)

- Guarda fecha, tipo de entrada, veredicto, puntaje, dominio, marca suplantada y departamento aproximado.
- La IP solo se usa en memoria para estimar la región y no se guarda.
- La URL completa se guarda solo con Peligroso o superior. En otro caso, solo el dominio.
- No guarda textos ni imágenes.

### Panel de estadísticas (al final)

- Filtros por fecha, tipo de entrada y departamento.
- Análisis por día, distribución de veredictos, dominios maliciosos más consultados, marcas más suplantadas, campañas activas, reportes pendientes, tasa de aciertos de la caché y estado y cuota de cada fuente.
- Solo agregados. Por región no se muestran grupos con menos de 5 análisis.

## Requisitos de calidad

| Atributo | Requisito y forma de verificarlo |
|---|---|
| Anonimato | Funciones ciudadanas sin registro, login ni datos personales. Solo la cookie de CSRF, sin cookies de identificación ni fingerprinting, verificado con el reporte de ZAP. La interfaz advierte que nunca se escriben contraseñas |
| Despersonalización | DNI, cuentas, tarjetas, correos, teléfonos y montos se enmascaran de forma irreversible antes de guardar o loguear. Las imágenes nunca se guardan. Un test rompe el build si un dato llega en claro a la base o a los logs |
| Licencias de terceros | Las respuestas de fuentes externas solo viven en la caché técnica, 24 h como máximo, y nunca pasan a la reputación ni a las estadísticas. Cada fuente documenta su licencia, su cuota y si permite uso comercial |
| Abuso | Solo http y https en los puertos 80 y 443. Destino rechazado si alguna de sus IP no es pública. Conexión a la IP validada. Máximo 3 redirecciones, 2 s de timeout de conexión y respuesta de 2 MB. Archivos de 5 MB validados por firma. 30 análisis por IP cada 10 minutos y después HTTP 429 |
| Modelo de lenguaje | Desactivado por defecto; la fase v3 cumple sin él. Si se habilita, queda aislado sin internet, herramientas ni base; recibe el contenido como dato delimitado; su salida se valida con un esquema JSON; suma 10 puntos como máximo, nunca resta y no cuenta para la cobertura; un set de 20 o más casos de prompt injection corre en el CI |
| Autenticación interna | Contraseña de 12 caracteres o más y TOTP, hash PBKDF2 o Argon2, bloqueo de 15 minutos tras 5 fallos, cookies HttpOnly, Secure y SameSite=Lax, sesión que vence a los 30 minutos sin actividad |
| Mínimo privilegio | Toda vista interna exige un rol y está denegada por defecto; un test recorre las rutas internas sin sesión y espera 302 o 403. Contenedor sin privilegios. Usuario de base de datos sin superusuario |
| Trazabilidad | Cada análisis guarda la versión de reglas, las señales, los pesos y el puntaje. Con las mismas señales y la misma versión, el puntaje es idéntico. Auditoría de solo agregar |
| Secretos | Todo secreto se lee del entorno, con valores distintos en Dev y Prod. gitleaks revisa todo el historial en cada push |
| Configuración segura | DEBUG apagado, errores genéricos, HTTPS con HSTS, X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy y CSP sin unsafe-inline. `check --deploy` y el smoke test de cabeceras pasan en el pipeline |
| Observabilidad | Logs sin datos personales, auditoría, `/health/` y `/ready/` monitoreados y alerta cuando una fuente supera el 20 % de errores en 15 minutos o el 80 % de su cuota diaria |
| Primer análisis | Enlace en 8 s o menos y captura en 15 s o menos en el percentil 95, medido en Dev con la instancia activa y 50 URLs |
| Respuesta desde la caché | Percentil 95 de 1 s o menos de tiempo de servidor, cero llamadas externas y mediana al menos 5 veces menor que la del primer análisis, con 200 consultas sobre 20 URLs en Dev |
| Redes móviles | Primera carga de 200 KB o menos comprimida, contenido útil en 3 s o menos sobre 3G simulada e indicador de progreso al analizar |
| Fallos externos | Timeout por fuente y circuit breaker que se abre tras 3 fallos y reintenta a los 5 minutos. El resultado distingue fuentes con evidencia, sin información y caídas. Una fuente caída, desconocida o con análisis vencido nunca cuenta como limpia. Sin evidencia de ninguna fuente, nunca Seguro |
| Escalabilidad | Procesos web sin estado local. Se escala con más workers o instancias, y las tareas pasan a un worker dedicado con `CELERY_EAGER=False` |
| Accesibilidad | WCAG 2.1 AA sin violaciones críticas en el CI, tres tamaños de texto, alto contraste, áreas táctiles de 48 × 48 px, teclado con foco visible y veredicto por color, ícono y texto |
| Comprensión | Índice Fernández Huerta de 70 o más en los textos de explicación, lista de términos técnicos prohibidos y 90 % o más de al menos 20 personas de distintas edades entiende el veredicto y la acción |
| Mantenibilidad | Una app de Django por responsabilidad, ruff sin errores, cobertura de 70 % o más en `core`, `motor` e `inteligencia`, la misma imagen en local, Dev y Prod, y lo que cambia entre ambientes leído del entorno |
| CI/CD | Cada PR corre pruebas, SAST, SCA, secretos y escaneo de imagen como checks obligatorios, y otro integrante lo aprueba. Cada push a `main` despliega a Dev, corre smoke test y DAST, y si pasan despliega a Prod de forma automática. Auto-Deploy de Render desactivado |

## Motor de riesgo

El motor decide en cuatro pasos. El nivel final es el mayor entre el nivel del puntaje y el piso que imponga cualquier regla. Los pesos son iniciales y se calibran con el set de regresión mediante versiones de reglas.

Paso 1. Cada señal se normaliza de 0 a 100.

| Señal | Peso | Cómo se lleva a 0 a 100 |
|---|---|---|
| Fuentes externas | 40 % | Detección vale 100 si la fuente reporta phishing o malware (en VirusTotal, 3 motores o más) y 50 si VirusTotal reporta 1 o 2. Sin detecciones vale 0, solo si la fuente tiene un análisis de la URL o del destino de las últimas 24 h sin hallazgos. Desconocido significa que la fuente respondió pero no tiene ese análisis, y no aporta puntaje ni cobertura. Las listas de bloqueo solo aportan detecciones. Vale el valor más alto entre las fuentes con detección o sin detecciones |
| Edad del dominio | 25 % | Menos de 7 días, 100. De 7 a 30 días, 70. De 31 días a 1 año, 30. Más de 1 año, 0. Sin dato, no disponible |
| Heurísticas de URL | 15 % | Suma con tope de 100. IP en lugar de dominio, 40. Acortador, 20. Punycode o caracteres engañosos, 40. Más de 3 subdominios, 20. Palabras como «verifica» o «login» en la ruta, 20 |
| Suplantación de marca | 10 % | Dominio oficial, 0. Marca en un subdominio o dominio a 1 o 2 caracteres de uno oficial, 100. Marca mencionada en el texto sin su dominio oficial, 60 |
| Ingeniería social | 10 % | 25 por categoría detectada (urgencia, amenaza, premio, suplantación de entidad, pedido de credenciales y pedido de pago), con tope de 100 |
| Modelo de lenguaje opcional | Hasta 10 puntos | Desactivado por defecto. Suma hasta 10 puntos, nunca resta y no entra en el reparto de pesos ni en la cobertura |

Paso 2. El puntaje base es el promedio ponderado de las señales con evidencia. El peso de las que faltan se reparte entre las demás, así una señal ausente nunca cuenta como limpia. El puntaje final es el mínimo entre 100 y la suma del puntaje base y el aporte del modelo.

Paso 3. La cobertura es el peso de las categorías aplicables que aportaron evidencia dividido por el peso aplicable total. Solo cuentan las categorías que corresponden al tipo de entrada y que ya existen en la fase vigente. La categoría de fuentes externas queda cubierta con una sola fuente que aporte una detección o un análisis vigente sin detecciones. Con cobertura menor al 70 %, el resultado no puede ser Seguro. Por ejemplo, un enlace sin respuesta útil de fuentes externas tiene una cobertura de (25 + 15 + 10) / 90, cerca de 56 %.

| Tipo de entrada | Señales aplicables | Desde |
|---|---|---|
| Enlace | Fuentes externas, dominio, heurísticas de URL y marca | v1 |
| Captura o QR | Por cada URL extraída, las del enlace; desde v3, además ingeniería social y marca en el texto extraído | v2 |
| Texto | Ingeniería social y marca; si trae URLs, también las del enlace | v3 |
| Teléfono | No usa puntaje: muestra la cantidad de reportes propios y su periodo, o «sin información» | Sin decidir |

Paso 4. Estas reglas fijan un nivel mínimo.

| Regla | Nivel mínimo |
|---|---|
| Una fuente externa confirma phishing o malware | Peligroso |
| Dos o más fuentes lo confirman, o una fuente junto con suplantación de marca | Peligro alto |
| Un analista confirma el fraude | Peligro alto |
| Suplantación de marca (señal de 60 o más) en un dominio de menos de 30 días | Peligroso |
| Pedido de credenciales o de pago junto con urgencia o amenaza | Peligroso |
| Dominio de menos de 30 días | Ten cuidado |
| Cobertura menor al 70 % | Ten cuidado |

| Puntaje | Nivel |
|---|---|
| 0 a 20 | Seguro |
| 21 a 50 | Ten cuidado |
| 51 a 80 | Peligroso |
| 81 a 100 | Peligro alto |

Nunca se declara fraude solo por similitud de nombre; hacen falta al menos dos señales. El modelo nunca baja un nivel. Solo un analista, desde la curación, corrige un veredicto hacia abajo.

El motor de explicación traduce el resultado a 3 a 5 motivos sin jerga, empezando por las reglas que se activaron, y da al menos una acción concreta. Dice «página falsa» en lugar de «phishing» y «web creada hace 3 días» en lugar de «dominio reciente».

## Caché de resultados y reputación propia

La caché guarda el veredicto, el puntaje, los motivos, la recomendación, las fuentes consultadas, la versión de reglas y la fecha. La clave es el SHA-256 de la URL normalizada sin fragmento más la versión de reglas, y no revela la URL. Nunca guarda textos, imágenes ni teléfonos; de una captura o un QR solo se reutiliza el resultado de cada URL extraída.

| Resultado | Vigencia máxima |
|---|---|
| Peligroso o Peligro alto | 72 h |
| Ten cuidado | 24 h |
| Seguro o sin información | 6 h |
| Dominio de menos de 30 días que queda en Ten cuidado por esa regla | 6 h, o la de su nivel si sube |
| Respuesta cruda de una fuente externa | 24 h |

Un resultado se invalida al vencer, al publicarse una versión de reglas, cuando un analista confirma un error o invalida una URL o un dominio, cuando una fuente o la curación marca como malicioso un dominio que tenía un resultado más favorable, cuando cambia una entrada del catálogo relacionada con el dominio y cuando la entrada está dañada.

Solo el motor escribe en la caché, y un reporte ciudadano nunca la toca. Un acierto de caché pasa igual por la capa de entrada y el rate limit. Las páginas de resultado se envían con `Cache-Control: no-store`.

La reputación propia guarda de forma permanente solo señales propias: heurísticas, edad del dominio, similitud con marcas, confirmaciones del analista y conteo de reportes. Nunca guarda datos de terceros. Un reporte «era legítimo» nunca anula una detección de una fuente externa.

## Fuentes externas

| Fuente | Aporta | Condición de uso |
|---|---|---|
| Google Safe Browsing | Malware e ingeniería social | Gratis solo para uso no comercial |
| VirusTotal | Consolidado de motores antivirus | 500 consultas al día y 4 por minuto; prohíbe el uso comercial y solo sirve para enriquecer |
| URLhaus | Distribución de malware | Uso justo; no se redistribuye |
| PhishTank | Phishing verificado por la comunidad | Requiere registro |
| urlscan.io | Redirecciones, dominio final y captura | Plan gratuito limitado |
| AbuseIPDB | Reputación de direcciones IP | Plan gratuito limitado |

Cada fuente tiene un adaptador con una interfaz común, para reemplazarla o degradarla sin tocar el motor.

## Arquitectura y ambientes

Monolito modular en Django 5.2 con seis apps. La responsabilidad de cada una y los imports permitidos están en [AGENTS.md](../AGENTS.md). La decisión final la toma siempre el motor propio con sus reglas, nunca una fuente externa ni el modelo de lenguaje por sí solos.

Así se procesa una consulta:

1. La persona envía el contenido sin registrarse.
2. La capa de entrada valida formato, tamaño, tipo real del archivo y rate limit.
3. Se extrae el texto o la URL de la imagen o del QR, y la URL se normaliza. La imagen se borra.
4. Si la URL tiene un resultado vigente en la caché, se devuelve.
5. Corren los analizadores del tipo de entrada y se consultan las fuentes externas en paralelo, con timeout por fuente.
6. El motor calcula el puntaje, la cobertura y los pisos.
7. Se muestran el nivel, los motivos y la acción.
8. El resultado se guarda en la caché y en el registro del análisis.
9. Si la persona reporta desacuerdo, el caso pasa a la cola del analista.

| Ambiente | Dónde corre | Settings | Para qué |
|---|---|---|---|
| Local | docker-compose | `config.settings.dev` | Desarrollo. DEBUG solo existe aquí |
| Pruebas | GitHub Actions | `config.settings.test` | Tests, SAST, SCA, secretos e imagen |
| Dev | Render y Neon | `config.settings.prod` | Smoke test y DAST antes de producción |
| Prod | Render y Neon | `config.settings.prod` | Servicio para los ciudadanos, con despliegue automático si Dev pasa |

El plan gratuito condiciona el diseño. Render no tiene background workers, así que Celery corre en modo eager. No hay Redis en Render, así que la caché usa una tabla de PostgreSQL. Hay 512 MB de RAM sin GPU, suficiente para Tesseract pero no para un modelo de lenguaje. La instancia se suspende tras 15 minutos sin tráfico y tarda cerca de un minuto en despertar. Tampoco hay consola en el servidor, así que la primera cuenta interna se crea desde local contra Neon.
