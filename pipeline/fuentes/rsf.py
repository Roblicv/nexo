"""Reporteros sin Fronteras: índice mundial de libertad de prensa (0 a 100, más es más libre).

RSF cambió su método en 2022, así que solo se comparan años desde 2022.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import statistics

from .comun import FuenteError, es, resumen

URL = "https://rsf.org/sites/default/files/import_classement/{anio}.csv"
PRIMER_ANIO = 2022


def _media_mundial(texto: str) -> float | None:
    sep = ";" if texto.count(";") > texto.count(",") else ","
    filas = list(csv.reader(io.StringIO(texto), delimiter=sep))
    if not filas:
        return None
    cab = [c.strip().lower() for c in filas[0]]
    col = next((i for i, c in enumerate(cab) if c.startswith("score")), None)
    if col is None:
        return None
    valores = []
    for f in filas[1:]:
        if len(f) <= col or not f[col].strip():
            continue
        try:
            v = float(f[col].strip().replace(",", "."))
        except ValueError:
            continue
        valores.append(v / 100 if v > 100 else v)  # algunas exportaciones de RSF multiplican por 100
    return statistics.fmean(valores) if len(valores) >= 100 else None


def leer(s, regla: dict, hoy: dt.date) -> dict:
    medias = {}
    for anio in range(PRIMER_ANIO, hoy.year + 1):
        r = s.get(URL.format(anio=anio), timeout=60)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        m = _media_mundial(r.content.decode("utf-8-sig", errors="replace"))
        if m is not None:
            medias[anio] = m
    if len(medias) < 4:
        raise FuenteError(f"Solo se pudieron leer {len(medias)} años del índice de RSF.")
    anios = sorted(medias)
    ultimo = anios[-1]
    media, desv = resumen([medias[a] for a in anios[:-1]])
    return {
        "lectura": medias[ultimo], "media": media, "desviacion": desv, "fecha_dato": f"{ultimo}-05-01",
        "detalle": f"Puntuación media mundial {es(medias[ultimo])} de 100 en {ultimo}; "
                   f"media {anios[0]}-{anios[-2]}: {es(media)}",
        "extra": {"anuales": {str(a): round(medias[a], 2) for a in anios}},
    }
