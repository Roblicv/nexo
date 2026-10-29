"""CDC de EE. UU.: síndrome gripal (FluView), servido por la API abierta Delphi Epidata (Carnegie Mellon)."""
from __future__ import annotations

import datetime as dt

from .comun import FuenteError, distancia_semanas, resumen, semana_iso

URL = "https://api.delphi.cmu.edu/epidata/fluview/"


def leer(s, regla: dict, hoy: dt.date) -> dict:
    a, w = semana_iso(hoy)
    r = s.get(URL, params={"regions": "nat", "epiweeks": f"{a - 6}01-{a}{w:02d}"}, timeout=60)
    r.raise_for_status()
    datos = r.json()
    if datos.get("result") != 1:
        raise FuenteError(f"Delphi respondió: {datos.get('message')}")
    serie = {}
    for fila in datos.get("epidata", []):
        if fila.get("wili") is not None:
            ew = int(fila["epiweek"])
            serie[(ew // 100, ew % 100)] = float(fila["wili"])
    if not serie:
        raise FuenteError("Sin datos de wILI.")
    (anio, semana), valor = max(serie.items())
    base = [v for (y, x), v in serie.items() if anio - 5 <= y < anio and distancia_semanas(x, semana) <= 2]
    media, desv = resumen(base)
    fecha = dt.date.fromisocalendar(anio, min(semana, 52), 6)
    return {
        "lectura": valor,
        "media": media,
        "desviacion": desv,
        "fecha_dato": fecha.isoformat(),
        "detalle": f"wILI {valor:.2f} % en {anio}-S{semana:02d}; media de 5 temporadas {media:.2f} %",
    }
