# Nexo

Observatorio abierto que estima, año por año, la probabilidad de la próxima pandemia con tres pilares:
el juego de incentivos entre países para reportar brotes, los datos de las agencias sanitarias
(CDC de EE. UU., ECDC, OMS y equivalentes) y la movilización social.

Cada lunes una tarea automática de GitHub descarga los datos, aplica las reglas de `reglas.yaml`,
valida qué variables mejoran los aciertos y publica el resultado en la página.

## Principio: nadie mueve los datos a mano

1. **Reglas escritas antes de ver resultados.** `reglas.yaml` define de dónde sale cada variable y cómo se calcula.
   Cambiar una regla exige subir `version`, y el cambio queda registrado en el historial de Git.
2. **El norte es acertar.** Un motor entra al pronóstico solo si, probado hacia atrás, anticipa mejor que la tasa
   base los años con emergencias sanitarias internacionales (puntuación de Brier). Si no, su peso es 0.
   Esto vale también para la hipótesis del autor.
3. **La simulación va aparte.** Los deslizadores de la página son para escenarios hipotéticos y nunca se mezclan
   con el pronóstico de datos.

## Estructura

```
.github/workflows/actualizar.yml   tarea semanal (lunes 06:00 UTC) y botón manual
reglas.yaml                        reglas registradas
pipeline/                          código en Python
  ejecutar.py                      orquesta todo: descarga, reglas, validación, publicación
  modelo.py                        la misma matemática que la página
  validacion.py                    prueba hacia atrás con puntuación de Brier
  fuentes/                         un archivo por fuente (OMS, ECDC, CDC vía Delphi, GDELT, ACLED)
datos/
  emergencias_oms.yaml             resultado observado para validar
  eventos.yaml                     eventos políticos y sociales registrados como datos
  lecturas.csv                     historial de lecturas (lo crea la tarea)
docs/                              la página que publica GitHub Pages
  index.html
  data/nexo-data.json              lo escribe la tarea cada semana
  data/caso2020.json               línea de tiempo del caso 2020
```

## Puesta en marcha en GitHub (sin usar la terminal)

1. **Crea el repositorio.** En github.com pulsa *New repository*, ponle de nombre `nexo`, márcalo como *Public*
   (GitHub Pages es gratis en repositorios públicos) y no agregues README. Pulsa *Create repository*.
2. **Sube los archivos.** En la página del repositorio vacío pulsa *uploading an existing file* y arrastra
   **el contenido** de la carpeta `nexo` (no la carpeta misma). Pulsa *Commit changes*.
   - La carpeta `.github` empieza con punto y tu sistema puede ocultarla. En Mac, en Finder pulsa
     `Cmd + Shift + .` para verla. Si aun así no sube, créala a mano: *Add file → Create new file*, escribe
     `.github/workflows/actualizar.yml` como nombre y pega el contenido del archivo.
3. **Activa la página.** *Settings → Pages → Build and deployment*: en *Source* elige *Deploy from a branch*,
   en *Branch* elige `main` y la carpeta `/docs`. Guarda. En uno o dos minutos la página estará en
   `https://TU-USUARIO.github.io/nexo/`.
4. **Lanza la primera actualización.** Pestaña *Actions*. Si GitHub pregunta, habilita los flujos de trabajo.
   Elige *Actualizar datos de Nexo* y pulsa *Run workflow*. Cuando aparezca la marca verde, recarga la página.
5. **Comprueba los permisos si falla el guardado.** Si el registro dice `Permission denied` al hacer `git push`,
   ve a *Settings → Actions → General → Workflow permissions*, elige *Read and write permissions* y guarda.

Desde ahí se actualiza sola cada lunes. GitHub pausa las tareas programadas de repositorios sin actividad
durante 60 días; los guardados semanales cuentan como actividad, pero si alguna vez se pausa, se reactiva
en la pestaña *Actions*.

### Opcional: ACLED

ACLED registra protestas evento por evento y es la mejor fuente para la movilización. Necesita una cuenta
gratuita en acleddata.com. Guarda tu usuario y contraseña en *Settings → Secrets and variables → Actions →
New repository secret* con los nombres `ACLED_USUARIO` y `ACLED_CLAVE`. Nunca los escribas en el código.
ACLED cambió su sistema de acceso en 2025: si esa fuente falla en el registro, revisa su documentación y
ajusta las dos direcciones al inicio de `pipeline/fuentes/acled.py`. El resto sigue funcionando.

## Ejecutarlo en tu computador

```
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pipeline.ejecutar
cd docs && python -m http.server 8000   # y abre http://localhost:8000
```

## Estado inicial y límites

- Las fuentes de la OMS, el CDC (vía Delphi) y GDELT se probaron con respuestas simuladas, no contra el
  servicio real: la primera ejecución en GitHub es la prueba de fuego. Si una falla, aparece como «Sin dato»
  en la página, el registro de *Actions* dice por qué y las demás siguen.
- GDELT solo ofrece unos tres meses hacia atrás, así que su línea base empieza corta y crece con `lecturas.csv`.
- Al principio casi ningún motor tendrá historial suficiente para validarse, así que el pronóstico de datos
  se parecerá a la línea histórica con tendencia. No es un error: significa que aún ninguna variable ha
  demostrado que mejora los aciertos.
- Es una herramienta para ordenar evidencia, no un pronóstico oficial ni asesoramiento sanitario.
