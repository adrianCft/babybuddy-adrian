# Salud

La sección Salud reúne visitas médicas, vacunas, medicamentos recetados, dosis
administradas y el acceso a las medidas y curvas de crecimiento existentes.

## Uso

- Una visita puede estar programada, realizada o cancelada. Permite guardar el
  motivo, centro, profesional, síntomas, valoración, pruebas, indicaciones y fecha
  de seguimiento. Desde su detalle se añaden medicamentos recetados.
- Cada receta conserva el nombre, la pauta indicada por el profesional, fechas y
  notas. Las sugerencias de nombres proceden de registros que el usuario tiene
  permiso para consultar. Crear una receta no registra dosis administradas.
- Las vacunas pueden estar programadas, administradas o canceladas. La próxima
  fecha se introduce manualmente; no se calcula un calendario ni se envían avisos.
- Visitas, vacunas, recetas y dosis administradas admiten varias fotos. En cada
  envío se aceptan hasta ocho imágenes de 10 MB cada una, validadas por Django y
  Pillow. La galería permite abrirlas; al editar se pueden seleccionar para borrar.
- El ajuste existente `ALLOW_UPLOADS` controla la incorporación de nuevas fotos.
  Las fotos se guardan con el almacenamiento configurado en Django, bajo
  `health/photos/`. Deben incluirse en la copia de los archivos multimedia.
- La ruta de visualización de fotos comprueba el permiso de lectura o edición del
  registro asociado. Los permisos de cada tipo de registro se aplican también a
  las listas, formularios y acciones de borrado.
- El borrado de una visita desde la aplicación se bloquea mientras tenga recetas.
  La eliminación explícita de un bebé conserva el comportamiento de borrado de
  todos sus registros. Los archivos de fotos se eliminan después de confirmar la
  transacción de borrado.

## Instalación

La migración `core.0043_health_records` crea cuatro tablas: visitas, recetas,
vacunas y fotos. No modifica filas ni columnas de las tablas anteriores. Las
dosis y medidas existentes conservan sus rutas y datos.

No hay nuevas dependencias de ejecución. Las bibliotecas de imágenes y Django ya
forman parte del proyecto. El despliegue requiere aplicar la migración, incluir
las plantillas y las traducciones españolas `.po`/`.mo`, y reiniciar la aplicación.
Estos cambios no incorporan archivos estáticos nuevos.

## Comprobaciones

`core.tests.tests_health` comprueba permisos, formularios, fechas, múltiples fotos,
rechazo de imágenes inválidas, aislamiento entre adjuntos, borrado de archivos,
separación de recetas y dosis, filtros por bebé y compatibilidad con los registros
de medicación existentes. Usa una base de pruebas y almacenamiento de imágenes en
memoria.

La comprobación global de migraciones del repositorio también propone cambios
previos en las opciones de alimentación y en las listas de idiomas/zonas horarias
de configuración. No forman parte de la migración de Salud.
