# Respuesta a incidentes

Qué hace el equipo ante un incidente de seguridad. Los procedimientos son cortos a propósito, para seguirlos como una lista durante el incidente. Los reportes de vulnerabilidades llegan por [SECURITY.md](../SECURITY.md).

## Roles

| Rol | Se ocupa de |
|---|---|
| Coordinación | Declarar el incidente, repartir el trabajo, llevar la línea de tiempo y decidir si hay que notificar a la autoridad o avisar a alguien |
| Plataforma | Revocar y rotar secretos, restaurar la base y revisar los logs de GitHub, Render y Neon |
| Contenido | Invalidar resultados, curar casos y revisar el catálogo y las reglas en la consola |

Quién cumple cada rol se anota en el Excel del equipo, fuera del repo. Con tres integrantes, cada uno tiene un rol y cualquiera reemplaza a otro si no está disponible.

El equipo tiene un correo propio para incidentes, que no es el de ningún integrante. Se usa para notificar a la autoridad y como contacto de `security.txt` (tarea 32).

## Pasos comunes

1. Quien detecta el incidente avisa al equipo y Coordinación lo declara.
2. Coordinación abre un registro privado, que puede ser un borrador de security advisory del repo o una hoja del Excel del equipo. Nunca un issue, porque el repo es público.
3. Se anota la hora en que el equipo supo del incidente. Desde esa hora corre el plazo legal de 48 horas descrito al final.
4. Primero se contiene el daño, después se investiga y al final se corrige la causa. Un cambio de código va por PR, como cualquier otro.
5. Al cerrar, el registro dice qué pasó, qué se hizo y qué cambia para que no se repita.

Cambiar una variable en Render redespliega el mismo commit. No despliega código nuevo, así que no se salta el pipeline.

## Secreto filtrado

| Secreto | Dónde se revoca | Dónde se carga el nuevo |
|---|---|---|
| `DJANGO_SECRET_KEY` | Se reemplaza por una clave nueva | Variables del servicio en Render, por ambiente |
| Contraseña del rol de la app, dentro de `DATABASE_URL` | Neon, en Roles, con un reset de la contraseña | `DATABASE_URL` en Render |
| `RENDER_DEPLOY_HOOK` | Render, en Settings del servicio, con «Regenerate Hook» | Secret del environment de GitHub (`development` o `production`) |
| Claves de las fuentes externas | Panel de cada proveedor | Variables del servicio en Render |

1. Revocar primero, en el proveedor. Borrar el commit no alcanza, porque el repo es público y el secreto ya pudo copiarse.
2. Cargar el valor nuevo y comprobar que el ambiente sigue sano con `/ready/`.
3. Buscar otros secretos expuestos en las alertas de secret scanning (pestaña Security) y con `gitleaks detect --source . --redact` en local. La alerta de GitHub se cierra como revocada.
4. Si el secreto quedó en un commit, el job `secretos` falla en cada PR, porque gitleaks revisa todo el historial. Con el secreto ya revocado, un PR agrega a `.gitleaksignore` la huella del hallazgo, que gitleaks muestra como `Fingerprint`. El historial no se reescribe.
5. Revisar si alguien usó el secreto en el panel del proveedor, en el monitoreo de Neon, en los despliegues de Render y en el audit log de la organización en GitHub. Si alguien entró a la base, se sigue también «Base comprometida».

## «Seguro» equivocado sobre una estafa real

La plataforma no guarda cómo contactar a quien consultó, a propósito. Por eso lo urgente es que la próxima consulta dé el resultado correcto.

1. Invalidar en la consola los resultados del dominio, con el motivo (tarea 38). La siguiente consulta recalcula el análisis completo.
2. Confirmar el fraude en la cola de curación (tarea 37). El dominio entra a la reputación propia con piso Peligro alto.
3. Revisar por qué dio Seguro. Cada análisis guarda la versión de reglas, las señales, los pesos y el puntaje, así que se ve qué señal faltó o qué fuente no respondió. El caso entra al set de regresión (tarea 55) y, si hace falta, las reglas cambian con una versión nueva.
4. Buscar dominios parecidos ya analizados. Si es una campaña, se invalidan y se curan todos.
5. Avisar a la marca suplantada por su canal oficial para reportar fraude, que figura en el catálogo, y reportar el sitio a su hosting o registrador para que lo den de baja.

## Acceso indebido a la consola

1. Rotar `DJANGO_SECRET_KEY` en Render. Django firma las sesiones con esa clave, así que se cierran todas las sesiones de la consola y se anulan los enlaces de cambio de contraseña pendientes.
2. Otro administrador desactiva la cuenta comprometida, le cambia la contraseña y reinicia su TOTP. Si no se sabe qué cuenta fue, se hace con todas.
3. Si la ruta del admin quedó expuesta, cambiar `DJANGO_ADMIN_PATH` en Render.
4. Revisar en la auditoría (tarea 36) qué hizo la cuenta desde su último acceso legítimo. Lo más grave es un dominio oficial agregado al catálogo, porque apaga la alerta para esa marca. Los cambios del catálogo y de las reglas están versionados y se revierten.
5. Invalidar los resultados de las marcas y los dominios que se tocaron.
6. Si la cuenta pudo leer datos personales, aplicar la sección de la ley.

## Base comprometida

Aplica cuando alguien pudo leer o cambiar la base de Prod, por ejemplo con una `DATABASE_URL` filtrada.

1. Rotar en Neon la contraseña del rol de la app y actualizar `DATABASE_URL` en Render. Si se filtró la contraseña del rol dueño del proyecto, rotar también esa.
2. Revisar en el monitoreo de Neon las conexiones y las consultas fuera de lo normal.
3. Rotar `DJANGO_SECRET_KEY`, porque la base guarda las sesiones de la consola. Si pudieron leer la base, reiniciar también el TOTP de todas las cuentas.
4. Si cambiaron datos, restaurar la base a un momento anterior al acceso con el procedimiento de la sección siguiente.
5. Aplicar la sección de la ley. Los análisis guardan datos enmascarados, pero las cuentas de la consola son datos personales.

## Respaldo y restauración

El respaldo es el historial de Neon, que Neon llama history window. Según su documentación, consultada el 2026-10-30, en el plan gratuito cubre las últimas 6 horas. Un daño que se descubre después de ese plazo ya no se deshace con el historial. El plan gratuito incluye además una snapshot manual, que conviene tomar antes de una migración que borra o transforma datos.

Para restaurar Prod:

1. Elegir un momento anterior al incidente, dentro de las 6 horas.
2. Revisar primero los datos de ese momento en una rama de prueba, con los pasos del simulacro.
3. En Neon, abrir la rama de Prod y entrar a Backup & Restore. Elegir «Restore from history» con esa fecha y hora. Neon guarda el estado anterior en una rama `<rama>_old_<fecha>`, así que la restauración se puede deshacer.
4. Comprobar Prod con `bash scripts/smoke.sh <url de Prod> <commit desplegado>`.
5. Borrar la rama `_old_` cuando ya no haga falta, porque contiene los datos del incidente.

Para el simulacro, que nunca se hace sobre Prod:

1. En Neon, entrar a Branches, crear una rama nueva con la de Prod como padre y elegir «Past data» con una hora de hace una o dos horas.
2. Poner la cadena de conexión de esa rama en el `.env` local, solo durante la prueba. No se escribe en ningún archivo del repo.
3. Con la app local apuntando a esa rama, abrir `/ready/` y correr `python manage.py showmigrations` para confirmar que la base está completa.
4. Borrar la rama en Neon y quitar la cadena del `.env`.
5. Anotar la fecha y el resultado en la tabla de simulacros.

Un respaldo nunca se sube como artifact de GitHub Actions, porque en un repo público cualquiera puede descargarlo.

## Datos personales y Ley N.° 29733

La plataforma guarda pocos datos personales por diseño. Enmascara los textos antes de guardarlos, no guarda IP ni capturas y guarda la URL completa solo con veredicto Peligroso o Peligro alto.

El reglamento de la Ley N.° 29733, aprobado por el Decreto Supremo N.° 016-2024-JUS y vigente desde marzo de 2025, pide lo siguiente:

- Si el incidente expone un gran volumen de datos, afecta a muchas personas, involucra datos sensibles o causa un perjuicio evidente, se notifica a la Autoridad Nacional de Protección de Datos Personales dentro de las 48 horas desde que el equipo lo supo, no desde que lo resolvió.
- Si afecta los derechos de los titulares, también se les comunica en 48 horas, en lenguaje claro y con las medidas tomadas.
- Si el incidente ocurrió en el entorno digital, se notifica además al Centro Nacional de Seguridad Digital.
- Una notificación tardía tiene que justificar el retraso.

Esta sección resume la norma y no la reemplaza. Antes de notificar, hay que confirmar el texto vigente en El Peruano.

## Simulacros

Cada simulacro se anota aquí, sin nombres. Faltan el de secreto filtrado, que rota `DJANGO_SECRET_KEY` y la contraseña de Neon de Dev como si se hubieran filtrado, y el de restauración en una rama de Neon.

| Fecha | Qué se probó | Resultado |
|---|---|---|
