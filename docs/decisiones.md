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

## Pendientes

| Decisión | Tarea | Recomendación |
|---|---|---|
| Activar las propuestas nuevas del plan | Todas las marcadas como propuesta nueva | Revisarlas en una reunión y registrar aquí cuáles se hacen |
| Umbral de AbuseIPDB para contar una detección | 20 | Empezar alto y ajustarlo con el set de regresión |
| Edad de los dominios `.pe` sin RDAP | 16 | Verificar si el registro de `.pe` ofrece RDAP; si no, la edad queda no disponible |
| Clave de PhishTank | 18 | Pedirla; si no llega, omitir la fuente |
| Enviar URLs nuevas a VirusTotal o urlscan.io | 19 | No por defecto, porque expone tokens de las víctimas |
| Límite por IP frente al CGNAT de las redes móviles | 12 | Medir los 429 en Prod antes de cambiarlo |
| CodeQL como check obligatorio | 3 | Sí, cuando su primer análisis no dé falsos positivos |
| Plazos de retención de datos | 40 | Análisis y reportes, 12 meses; auditoría, un año como mínimo |
| Dominio propio | 60 | Sí, antes de difundir la plataforma |
| Imagen del CI desplegada en Render por digest | 4 | Revisar primero cómo construye Render hoy |
| Habilitar el modelo de lenguaje | 51 | Solo si el set de regresión muestra que mejora la detección |
| Diseño de la consulta de números telefónicos | 54 | Decidir después del registro estadístico |
