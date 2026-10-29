"""ECDC: datos semanales de virus respiratorios (ERVISS), publicados en GitHub."""
from __future__ import annotations

import csv
import datetime as dt
import io

from .comun import FuenteError, distancia_semanas, resumen

URL = ("https://raw.githubusercontent.com/EU-ECDC/Respiratory_viruses_weekly_data/"
       "main/data/sentinelTestsDetectionsPositivity.csv")


def leer(s, regla: dict, hoy: dt.date) -> dict:
    r = s.get(URL, timeout=60)
    r.raise_for_status()
    serie: dict[tuple[int, int], float] = {}
    for fila in csv.DictReader(io.StringIO(r.text)):
        if (fila.get("countryname") == "EU/EEA" and fila.get("pathogen") == "Influenza"
                and fila.get("pathogentype") == "Influenza" and fila.get("pathogensubtype") == "total"
                and fila.get("indicator") == "positivity"):
            try:
                anio, semana = fila["yearweek"].split("-W")
                serie[(int(anio), int(semana))] = float(fila["value"])
            except (KeyError, ValueError):
                continue
    if not serie:
        raise FuenteError("No se encontró la serie de positividad de gripe UE/EEE.")
    (anio, semana), valor = max(serie.items())
    base = [v for (a, w), v in serie.items() if a < anio and distancia_semanas(w, semana) <= 2]
    media, desv = resumen(base)
    fecha = dt.date.fromisocalendar(anio, semana, 7)
    return {
        "lectura": valor,
        "media": media,
        "desviacion": desv,
        "fecha_dato": fecha.isoformat(),
        "detalle": f"Positividad {valor:.1f} % en {anio}-S{semana:02d}; media de temporadas anteriores {media:.1f} %",
    }
