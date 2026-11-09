# Despliegue desde el LXC

El despliegue de producción puede ejecutarse dentro del LXC 106. El script no
necesita Git en el contenedor: descarga el tarball de un commit concreto desde
GitHub y comprueba su SHA256.

Instala el script en `/root/babybuddy-deploy.sh` y guarda el lanzamiento en
`/root/babybuddy-release.env`. El script conserva `/opt/data` y
`babybuddy/settings/production.py`, ejecuta las migraciones, comprueba Django y
reinicia `uwsgi` y nginx. Los temporales se crean y eliminan dentro del LXC.

El snapshot del LXC se sigue haciendo desde Proxmox antes de publicar. El
script no intenta crear snapshots porque un LXC sin privilegios no tiene acceso
al volumen del host.
