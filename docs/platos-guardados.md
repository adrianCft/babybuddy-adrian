# Platos guardados

## Uso

- Desde **Comidas → Platos guardados**, crear un plato con nombre e ingredientes.
- En una comida, elegir un plato y pulsar **Añadir plato**. Sus ingredientes se
  suman a los que ya estaban marcados. Un ingrediente compartido solo aparece una vez.
- Ajustar los ingredientes de esa comida según lo que se haya preparado ese día.
- **Guardar selección como plato** crea una plantilla con los ingredientes
  marcados, sin salir del formulario. El plato queda guardado aunque después se
  abandone la comida sin enviarla.
- Los ingredientes seleccionados aparecen encima del buscador y no se ocultan
  al buscar. Se pueden desmarcar desde ese mismo bloque con ratón o teclado.
- Quitar el nombre de un plato conserva sus ingredientes; estos se desmarcan
  individualmente para no quitar ingredientes compartidos con otro plato.

Se pueden modificar o desactivar platos desde su catálogo. Los platos desactivados,
vacíos o con algún ingrediente inactivo no se ofrecen en comidas nuevas. Al editar
una receta se conservan sus ingredientes inactivos para poder sustituirlos.

## Conservación de datos

La migración `0041_saved_dishes` añade `Dish`, `DishFood` y el campo opcional
`Meal.dish_names`. No contiene operaciones de carga de datos ni crea platos.
Las comidas existentes reciben una lista vacía de nombres; sus alimentos,
fechas, notas, etiquetas y demás información se conservan.

Cada comida guarda los nombres de los platos de ese momento y su propia selección
de alimentos. Cambiar, desactivar o borrar una receta no modifica esas comidas.
Los informes continúan contando los alimentos individuales. Los nombres también
aparecen en el listado, la cronología, el resumen de la última comida, la API y
la exportación/importación. Los clientes que omiten `dish_names` al actualizar
una comida conservan su valor; `[]` lo vacía explícitamente.

Los permisos `view_dish`, `add_dish` y `change_dish` controlan el catálogo y el
alta rápida. Los usuarios habituales con acceso completo ya los tienen por su
condición de superusuario. Si se utilizan permisos personalizados, asignarlos
desde la administración. No se alteran los permisos existentes.

## Validación y actualización pendiente

Las pruebas Django usan una base independiente. `tests_dish_migration` compara
todas las tablas y columnas existentes antes y después de la migración y verifica
que el catálogo nuevo esté vacío.

```powershell
$env:DATABASE_URL='sqlite:///:memory:'
python manage.py test core api dashboard reports --settings=babybuddy.settings.test --noinput
```

Para ejecutar además la prueba de navegador, instalar Playwright para Node y
establecer `BABYBUDDY_PLAYWRIGHT_MODULE` con la ruta a ese módulo. Por defecto usa
Edge en modo headless; `BABYBUDDY_BROWSER` permite elegir otro canal instalado.
La prueba requiere las dependencias npm del proyecto para cargar Bootstrap.
Verifica selección, búsqueda, ingredientes compartidos, teclado y altas rápidas
con anchuras de 390 y 1280 píxeles. Los datos de estas pruebas son temporales.

Antes de desplegar en el LXC 106, realizar la copia/snapshot acordada. Después de
actualizar el código se ejecutará la migración mediante el procedimiento de
despliegue habitual y se reiniciará el servicio. La migración aún no debe
ejecutarse sobre la base de la aplicación en uso durante el desarrollo.

Comprobaciones realizadas durante el desarrollo:

- Interacciones del selector en Edge headless, a 390 y 1280 píxeles.
- Migración sobre una copia temporal de la base SQLite local: las 38 tablas
  existentes conservaron todas sus filas y columnas originales. El catálogo de
  platos quedó vacío y el SHA-256 del archivo original permaneció idéntico.
- Lint de las plantillas nuevas y revisión de espacios del diff sin errores.

`makemigrations --check` detecta diferencias previas en las opciones de idioma y
zona horaria de `Settings`, y en los permisos de `Feeding`. Se verificó que también
aparecen al excluir los modelos y el campo de esta mejora. No se han incluido
esas diferencias ajenas en `0041_saved_dishes`; para desplegar esta mejora se
aplican las migraciones versionadas, sin generar nuevas migraciones en el LXC.
