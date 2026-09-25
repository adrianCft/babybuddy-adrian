# Resumen diario y cronología visual

La pantalla **Resumen diario** está disponible en `/daily/`, en la navegación
principal, en el panel de cada niño y desde la cronología anterior.

Permite elegir fecha y niño, ver todos los niños con sus datos separados y
desplazarse al día anterior, al siguiente o a hoy. Las tarjetas resumen el sueño
registrado, las tomas iniciadas, las comidas y alimentos distintos, los pañales,
la medicación y las notas. La cronología también muestra temperatura,
extracciones y tiempo boca abajo.

Los bloques representan actividades con duración y los puntos eventos a una
hora concreta. Pulsarlos lleva al detalle correspondiente. Los registros se
pueden editar si el usuario tiene el permiso necesario. La cronología admite
desplazamiento horizontal en móvil y navegación con teclado; toda la información
también está disponible en la lista de detalle debajo del gráfico.

## Criterios de cálculo

- El día se calcula en la zona horaria del usuario, desde medianoche inclusive
  hasta la siguiente medianoche exclusive. Incluye los últimos microsegundos del día.
- El sueño se recorta al día consultado. Si empieza la víspera a las 22:00 y
  termina a las 07:00, se suman 7 horas al día consultado. Los solapamientos
  existentes en registros importados no duplican el tiempo de sueño.
- Los días de cambio de hora tienen su duración real de 23 o 25 horas. La escala
  y los totales se calculan con tiempo transcurrido, y la pantalla lo indica.
- Los temporizadores de sueño activos se muestran rayados, como provisionales;
  no se suman al sueño registrado. Se actualizan al recargar la pantalla con
  **Actualizar** y requieren permiso de consulta de temporizadores y de sueño.
- Las tomas y su cantidad en biberón se cuentan en el día de inicio. Una toma
  que cruza medianoche se ve en ambos días, pero su cantidad no se duplica.
- Las cantidades se muestran tal como se registran en la aplicación, sin
  atribuir unidades que el modelo no almacena ni sumar dosis de medicamentos.
- Los pañales mixtos se cuentan una vez en el total y en ambas categorías.
- Los espacios vacíos de la cronología significan ausencia de registros; no se
  interpretan como tiempo despierto ni como actividad confirmada.

## Datos y permisos

Esta mejora no necesita migraciones ni modifica los registros. Utiliza el
permiso `view_child` para acceder y los permisos de consulta de cada tipo para
sus tarjetas, bloques y detalles. Los enlaces de edición requieren además
el permiso `change` correspondiente. La versión de platos guardados se conserva
en la etiqueta `checkpoint/platos-guardados-2026-09-25`; esta mejora se desarrolla
en la rama `codex/resumen-diario-cronologia`.

## Pruebas

```powershell
$env:DATABASE_URL='sqlite:///:memory:'
python manage.py test core.tests.tests_daily_summary --settings=babybuddy.settings.test --noinput
```

Las pruebas cubren límites diarios, cambios de hora, solapamientos, temporizadores,
permisos, filtros, selección de niño, cantidades cero y consultas sin escrituras.
Con `BABYBUDDY_PLAYWRIGHT_MODULE` apuntando al módulo Node de Playwright también
se comprueba el navegador a 390 y 1280 píxeles, en modo claro y oscuro.
`BABYBUDDY_DAILY_SCREENSHOTS` permite guardar las capturas en una carpeta existente.

Las pruebas se ejecutan en una base independiente. El despliegue y la snapshot
del LXC se realizan por separado cuando se decida publicar la nueva versión.

La batería general del repositorio se ejecuta con `--exclude-tag=isolate` y,
después, `babybuddy.tests.tests_views.ViewsTestCase.test_password_reset` de forma
independiente, tal como especifica la tarea de Gulp. Esa prueba cierra la sesión
compartida de su clase y no debe mezclarse con las demás.
