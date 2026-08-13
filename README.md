# Horarios Primera Federación 2026/27

PWA para consultar el calendario completo de Primera Federación 2026/27, horarios, resultados, clasificación y partidos favoritos.

## Fuente de datos

La fuente automática de horarios y resultados es **BeSoccer**.

- Competición: Primera Federación 2026/27.
- Se recorren los calendarios de los equipos de Grupo 1 y Grupo 2.
- Los partidos se deduplican y se cruzan con `docs/data/horarios.json`.
- GitHub Actions ejecuta el proceso automáticamente dos veces al día.

## Cómo se muestra el calendario

La vista general se organiza por:

**Jornada → día → partidos de ambos grupos**

Cada partido muestra su etiqueta `G1` o `G2` y puede guardarse individualmente con una estrella.

Los partidos se distinguen por estado:

- **CONFIRMADO**: fecha y hora confirmadas.
- **HORA PENDIENTE**: fecha concreta conocida, hora pendiente.
- **POR PROGRAMAR**: todavía no hay fecha/hora definitiva.
- **FINALIZADO**: el partido ya tiene resultado.

Los partidos sin programar no se ocultan ni se asignan artificialmente al domingo.

## Calendario por equipo

El usuario puede elegir un equipo y consultar sus 38 jornadas. La interfaz indica cuántos partidos tienen horario confirmado y permite alternar entre:

- Todos
- Solo confirmados

## Favoritos

Cada partido tiene una estrella propia. Los partidos favoritos se guardan en el navegador mediante `localStorage` y permanecen marcados aunque posteriormente cambie su fecha u hora.

La app conserva también los favoritos por equipo para las notificaciones y recordatorios ya existentes.

## Clasificación

La clasificación se mantiene separada por Grupo 1 y Grupo 2 y se calcula a partir de los resultados almacenados.

## Exportación a calendario

Solo se exportan como eventos con hora los partidos realmente programados. La app no utiliza la fecha genérica de una jornada como si fuera la fecha definitiva del encuentro.

## Estructura

- `docs/`: PWA publicada con GitHub Pages.
- `docs/index.html`: interfaz y lógica del frontend.
- `docs/data/horarios.json`: calendario, horarios y resultados.
- `scraper/besoccer_source.py`: extracción común desde BeSoccer.
- `scraper/scraper.py`: actualización de fechas y horarios.
- `scraper/resultados.py`: actualización de resultados.
- `scraper/notify.py`: notificaciones de nuevos horarios.
- `scraper/reminders.py`: programación de recordatorios.
- `.github/workflows/check-horarios.yml`: automatización.

## GitHub Pages

Configurar:

`Settings → Pages → Deploy from a branch → main → /docs`

## GitHub Actions

El workflow puede ejecutarse manualmente en:

`Actions → Comprobar horarios Primera RFEF → Run workflow`

También se ejecuta automáticamente según el cron definido en `.github/workflows/check-horarios.yml`.

## Dependencias Python

```text
requests
beautifulsoup4
```

## OneSignal

Para activar notificaciones push hay que sustituir `TU_ONESIGNAL_APP_ID` en `docs/index.html` y crear estos Secrets en GitHub:

- `ONESIGNAL_APP_ID`
- `ONESIGNAL_API_KEY`

Si todavía no se han configurado, el calendario y el scraping pueden funcionar igualmente; lo que no funcionará son las notificaciones push.
