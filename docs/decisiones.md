# Decisiones del equipo

Registro de lo que el equipo decidió y de lo que falta decidir. Una decisión de aquí manda sobre [requisitos.md](requisitos.md) y sobre el plan. Para cambiar una decisión, o para cerrar una pendiente, se edita este archivo en un PR y se ajustan las tareas afectadas.

## Decididas

| Decisión | Motivo | Origen |
|---|---|---|
| Monolito modular en Django con templates y Tailwind CSS, sin SPA | Página liviana, autoescapado contra XSS y una sola tecnología que mantener | Informe del Hito 1 |
| Celery en modo eager y caché en una tabla de PostgreSQL en Render | El plan gratuito no tiene workers ni Redis; pasar a un worker es un cambio de configuración | Informe del Hito 1 |
| Producción se despliega de forma automática cuando Dev pasa el smoke test y el DAST | Pedido del profesor. La aprobación humana queda en el PR, y el DAST tiene reglas que bloquean | Profesor, 2026-10-30 |
| La consulta de números telefónicos queda sin decidir y al final | El equipo todavía no define cómo será. No se programa nada para ella | Equipo, 2026-10-30 |
| El registro estadístico y el panel de estadísticas van al final | Primero el análisis. El modelo de datos del análisis se diseña para ellos desde v1 | Equipo, 2026-10-30 |
| DEBUG, la CSP, el TLS hacia PostgreSQL y la política de salida quedan fijos en el código | Una variable de entorno mal cargada no debe poder apagar un control de seguridad | Equipo, 2026-10-30 |
| `httpx` solo se importa en `core/net.py` | Los controles de salida se aplican en un solo lugar | Equipo, 2026-10-30 |
| La CSP se aplica desde ahora, antes de la interfaz | Es más fácil construir la interfaz respetándola que agregarla después | Equipo, 2026-10-30 |
| La app entra a PostgreSQL con un rol sin superusuario en local y en el CI | Probar con los mismos permisos que exige el informe para producción | Equipo, 2026-10-30 |
| Cobertura mínima de 70 % en `core`, `motor` e `inteligencia`, exigida en el CI | Requisito de mantenibilidad del informe | Equipo, 2026-10-30 |
| Ramas `feature/<descripcion-corta>` y commits `tipo: descripción` | Las ramas siguen el informe; los commits, el historial del repo | Equipo, 2026-10-30 |
| Los agentes pueden hacer commits en su rama; push y PR solo cuando la persona lo pide | La persona revisa antes de publicar | Equipo, 2026-10-30 |
| Colores del semáforo ajustados para cumplir WCAG AA | Los del prototipo no llegaban al contraste mínimo | Equipo, 2026-10-30 |
| Los documentos del curso no se suben al repo y sus códigos de requisito no se citan | El repo es público y los documentos tienen datos personales. Este directorio resume lo necesario para programar | Equipo, 2026-10-30 |
| Se aceptan, en versión reducida, las propuestas de las tareas 4, 5, 7, 31, 32, 33, 40 y 57 | Protegen a usuarios reales de una plataforma pública o muestran prácticas profesionales, y cuestan poco frente al MVP | Equipo, 2026-10-30 |
| Se descartan para el MVP las tareas 41 (fusionada con la 5), 45, 48, 49, 50 y 60 | Cambian el motor, necesitan tareas programadas o moderación, o tienen costo. Quedan como ideas en la tarea 61 | Equipo, 2026-10-30 |
| De la tarea 3 se aceptan el 2FA obligatorio en GitHub, el MFA en Render y Neon y el *private vulnerability reporting*. Se descarta `CODEOWNERS` | Con despliegue automático, una cuenta tomada controla producción. Con tres integrantes, exigir un responsable por ruta frena más de lo que protege, y todo PR ya necesita la aprobación de otro integrante | Equipo, 2026-10-30 |
| Los tres integrantes son administradores del repo | Todos configuran GitHub. A cambio, el 2FA es obligatorio en las tres cuentas | Equipo, 2026-10-30 |
| `pedir_url` admite POST y cabeceras propias, solo para las APIs de las fuentes externas. Con ellos no sigue redirecciones, y no puede cambiar Host, Cookie, User-Agent ni Accept-Encoding | URLhaus y PhishTank exigen POST, y VirusTotal, urlscan.io y AbuseIPDB llevan la clave en una cabecera. Sin redirecciones, la clave o el cuerpo nunca llegan a otro servidor | Usuario, 2026-11-13 |
| Un dominio sin servidor RDAP, como los `.pe`, toma la edad que informan VirusTotal o urlscan.io. Si no dan la fecha de creación, vale desde cuándo VirusTotal conoce la web, que es un mínimo. Si no hay nada, queda sin edad. La edad del registro manda cuando existe, y en un alojamiento compartido no se usa la de las fuentes | El registro de IANA publicado el 2026-10-28 no tiene servidor RDAP para `.pe`, y WHOIS usa el puerto 43, que la política de salida bloquea. Sin edad, ninguna web `.pe` llegaba al 70 % de cobertura. De la fuente solo se guarda el número de días, como señal del análisis | Tarea 16, 2026-11-12; cambiada el 2026-11-13 |
| La vigencia de un análisis externo sin hallazgos depende de la edad de la web: 24 h con menos de 30 días o sin edad conocida, 7 días con menos de un año y 30 días con más. Cambia las 24 h fijas del informe del Hito 1. Es la versión de reglas 2 | Con claves reales, la web de un banco y la del Estado salían «Ten cuidado» con puntaje 0: casi ninguna web legítima tiene un análisis de las últimas 24 h, porque no se envían direcciones a escanear. Una página falsa vive horas o días, así que el plazo corto se mantiene para las webs nuevas | Equipo, 2026-11-13 |
| Si la dirección exacta no tiene un análisis vigente, vale el de la web completa en VirusTotal cuando ningún antivirus la marca, tiene más de un año y figura en algún ranking de webs visitadas. No se aplica a acortadores, alojamientos compartidos ni direcciones que son solo un número | Casi nadie analiza cada página interna de una web conocida. El riesgo aceptado es una web antigua comprometida hace poco: una detección de cualquier fuente sigue mandando, y Seguro aclara que orienta y no garantiza | Equipo, 2026-11-13 |
| Una sospecha de las fuentes externas cuenta desde dos fuentes. Una sola (1 o 2 antivirus en VirusTotal, o una IP reportada en AbuseIPDB) se muestra en el detalle y no suma puntaje ni cobertura. Una confirmación sigue contando sola | Un antivirus entre 90 o una IP compartida con reportes se equivocan seguido | Equipo, 2026-11-13 |
| VirusTotal confirma solo cuando 3 motores o más coinciden en el tipo de amenaza (phishing o malware). Si 3 o más la marcan como «malicious» sin decir el tipo, es una sospecha que fija Ten cuidado como mínimo y como máximo mientras ninguna otra fuente confirme: ni Seguro ni Peligroso. Cambia el «3 motores o más = 100» del informe del Hito 1 | El 2026-11-13 la web de una organización legítima que publica archivos de prueba para antivirus salió Peligroso con 3 motores de 93, ninguno con tipo. Marcar no es confirmar, y evidencia contradictoria debe dar un resultado de incertidumbre | Equipo, 2026-11-13 |
| Una explicación solo afirma el tipo de amenaza que una fuente informó. Sin tipo, dice que no se sabe; nunca que la web roba claves o copia a un banco. El titular de un resultado reportado no habla de estafa | Cada afirmación del resultado debe poder rastrearse a una evidencia | Equipo, 2026-11-13 |
| El detalle de lo que cuenta cada fuente se muestra en el resultado y se guarda solo en la caché técnica, 24 h | Explica el resultado sin pasar datos de terceros a la base ni a la caché de resultados | Equipo, 2026-11-13 |
| Con cobertura menor al 70 % y sin nada en contra, el motivo dice «No encontramos nada malo, pero nos falta información para decir que es segura» | El nivel sigue siendo Ten cuidado, pero no debe sonar a acusación contra una web sin hallazgos | Equipo, 2026-11-13 |
| La legibilidad se mide con Fernández Huerta en la forma L = 206,84 − 0,60·P − 1,02·F, con P = sílabas por 100 palabras y F = palabras por frase. Se mide el texto completo de cada resultado y de cada sección de una página, no cada rótulo suelto | La versión con F = frases por 100 palabras castiga partir una frase en dos (Law, LINGUIST List 22.2332, 2011). El índice se calibró con muestras de unas 100 palabras: una palabra suelta no se puede medir | Tarea 22, 2026-11-13 |
| Desde un enlace, la modalidad de estafa se sugiere por las palabras de la dirección y el resultado lo dice como pista. Solo se muestra desde Ten cuidado y con algún hallazgo, y nunca en una web del Estado (`.gob.pe`) ni en un dominio oficial del catálogo | Sin hallazgos sería una acusación sin pruebas, y «sunat» en sunat.gob.pe es lo esperado | Tarea 33, 2026-11-13 |

## Pendientes

| Decisión | Tarea | Recomendación |
|---|---|---|
| Umbral de AbuseIPDB para contar una detección | 20 | Empezar alto y ajustarlo con el set de regresión. El código usa 90 de confianza y una IP reportada vale 50, una sospecha que no confirma por sí sola. Pasarlo a la versión de reglas con la tarea 21 |
| Clave de PhishTank | 18 | Pedirla; si no llega, omitir la fuente |
| Lista de popularidad local (Tranco) como respaldo de los rankings de VirusTotal | 19 | Aprobada el 2026-11-13 y sin programar. La lista del millón pesa más que los 2 MB de la política de salida, necesita una tabla y una tarea que la refresque, y Render no tiene tareas programadas. Hacerla si la cuota de VirusTotal se queda corta |
| Enviar URLs nuevas a VirusTotal o urlscan.io | 19 | No por defecto, porque expone tokens de las víctimas |
| Límite por IP frente al CGNAT de las redes móviles | 12 | Medir los 429 en Prod antes de cambiarlo |
| CodeQL como check obligatorio | 3 | Sí, cuando su primer análisis no dé falsos positivos |
| Plazos de retención de datos | 40 | Análisis y reportes, 12 meses; auditoría, un año como mínimo |
| Habilitar el modelo de lenguaje | 51 | Solo si el set de regresión muestra que mejora la detección |
| Diseño de la consulta de números telefónicos | 54 | Decidir después del registro estadístico |
| Modo oscuro de la interfaz, con degradados solo como luz, en lugar del fondo claro que pide AGENTS.md | 6, 26 | Aceptarlo, porque está en producción desde el PR #16. Después, cambiar en AGENTS.md los colores y la regla de degradados, y decidir en la tarea 6 si el CSS sigue propio o pasa a Tailwind |
| Trigger de PostgreSQL que impide editar o borrar la auditoría | 9 | Sí, en un PR aparte. Lo crea el rol de la app, que es dueño de la tabla, sin superusuario |
| Si un dominio que no resuelve cuenta como destino bloqueado en la auditoría | 11, 39 | No. Pasa a diario con páginas falsas ya dadas de baja y dispararía la alerta de picos de bloqueos. Devolverlo como un resultado aparte y sin evento |
| Si un enlace con un truco para disfrazar su destino (el «@», letras de otros alfabetos o una IP escrita de forma rara) puede salir Seguro | 21 | Hoy puede, si la web de destino es antigua y nadie la reporta; el titular ya no lo niega. Proponer un piso de Ten cuidado y medirlo con el set de regresión |
