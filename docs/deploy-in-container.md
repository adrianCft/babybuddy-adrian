# Despliegue desde el LXC

El comando se ejecuta dentro del LXC 106 y descarga un commit concreto de
GitHub, comprobando su SHA256. No necesita Git ni deja archivos en Proxmox.

```bash
bash /root/babybuddy-deploy.sh COMMIT SHA256
```

El último lanzamiento correcto queda en `/root/babybuddy-release.env`. También
puede ejecutarse `bash /root/babybuddy-deploy.sh` para instalar ese lanzamiento.
El snapshot sigue haciéndolo el administrador desde Proxmox.

El script y `scripts/deploy_helpers.py` deben pertenecer a este lanzamiento.
Los paquetes anteriores que no contienen el comprobador se rechazan antes de
parar servicios; para una versión antigua debe usarse su procedimiento anterior.

## Protección de los datos

- Se instalan únicamente los directorios de la aplicación, traducciones y
  estáticos. Se excluyen datos, fotos, entorno virtual, pruebas y configuración
  de desarrollo. `production.py` mantiene su contenido y permisos.
- Se comprueba el archivo antes de extraerlo: se rechazan rutas que salgan del
  paquete, enlaces y archivos de datos o secretos.
- Se detiene `uwsgi` durante la instalación; nginx permanece en funcionamiento.
- Se calcula una huella de los valores existentes de cada tabla de la app, sus
  relaciones y preferencias. Al terminar se comprueban los mismos campos, aunque
  la nueva versión haya añadido columnas. Una base con el mismo número de filas
  pero valores distintos también falla esta comprobación.
- Se verifica que Django apunta a `/opt/data/db.sqlite3`. Las migraciones solo se
  ejecutan si hay pendientes. Cambios que borran o transforman datos (`RemoveField`,
  `DeleteModel`, `RunPython`, `RunSQL`, cambios de tipos, etc.) requieren revisión
  manual: este script se detiene antes de ejecutarlos.
- Si falla la instalación, se restaura el código anterior y se intenta arrancar
  `uwsgi`. Nunca se sustituye la base ni se deshacen sus migraciones. Los cambios
  admitidos son aditivos o de metadatos, compatibles con el código anterior.
- Se comprueban uwsgi, nginx y las respuestas HTTP de Inicio e inicio de sesión.
  No se actualiza el archivo del lanzamiento hasta que las comprobaciones pasan.

La huella de datos no es una copia de seguridad. Una avería de disco o una
interrupción del sistema necesita el snapshot/backup del administrador. Si la
restauración del código falla, el script conserva sus archivos temporales e
indica su ubicación para permitir la recuperación manual.

## Estáticos, traducciones y dependencias

El repositorio incluye `static/staticfiles.json`, sus archivos con hash y sus
versiones comprimidas. Deben generarse con los nuevos estilos y JavaScript antes
de subir el commit. El comprobador rechaza un manifiesto incompleto y los `.gz`
que no corresponden a su archivo original. Las traducciones se compilan antes de
publicar y se instala el catálogo `.mo` preparado.

Con `RUN_COLLECTSTATIC=0` se utilizan los estáticos ya generados. Con valor `1`
se ejecuta además `collectstatic`; el instalador prepara los originales de la
aplicación para que Django pueda encontrarlos. Los archivos estáticos antiguos
se conservan para las páginas que todavía los tengan en caché.

Si `requirements.txt` cambia, el despliegue se detiene antes de copiar código:
primero hay que preparar y comprobar el entorno virtual para esa actualización.
No se instalan dependencias automáticamente sobre el entorno en uso.
