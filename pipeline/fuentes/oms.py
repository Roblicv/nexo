"""OMS: Disease Outbreak News (DON)."""
from __future__ import annotations

import collections
import datetime as dt

from .comun import FuenteError, resumen

URL = "https://www.who.int/api/news/diseaseoutbreaknews"
CAMPOS_FECHA = ("PublicationDateAndTime", "PublicationDate", "DatePublished", "Date")


def _fecha(item: dict) -> dt.date | None:
    for campo in CAMPOS_FECHA:
        valor = item.get(campo)
        if isinstance(valor, str) and len(valor) >= 10:
            try:
                return dt.date.fromisoformat(valor[:10])
            except ValueError:
                continue
    return None


def descargar(s, max_paginas: int = 60) -> list[dt.date]:
    fechas: list[dt.date] = []
    usar_orden = True
    for pagina in range(max_paginas):
        params = {"$top": 100, "$skip": pagina * 100}
        if usar_orden:
            params["$orderby"] = "PublicationDateAndTime desc"
        r = s.get(URL, params=params, timeout=40)
        if r.status_code == 400 and usar_orden:
            usar_orden = False  # el campo de orden cambió de nombre: seguimos sin ordenar
            r = s.get(URL, params={"$top": 100, "$skip": pagina * 100}, timeout=40)
        r.raise_for_status()
        valores = r.json().get("value", [])
        if not valores:
            break
        fechas.extend(f for f in (_fecha(v) for v in valores) if f)
    if not fechas:
        raise FuenteError("La API de la OMS no devolvió notas con fecha.")
    return sorted(fechas)


def leer(s, regla: dict, hoy: dt.date) -> dict:
    fechas = descargar(s)
    ventana = dt.timedelta(weeks=12)
    actual = sum(1 for f in fechas if hoy - ventana < f <= hoy)
    base = []
    for anio in range(2015, 2026):
        try:
            fin = hoy.replace(year=anio)
        except ValueError:  # 29 de febrero
            fin = hoy.replace(year=anio, day=28)
        if fin - ventana < fechas[0]:
            continue  # el archivo de la API no llega tan atrás
        base.append(sum(1 for f in fechas if fin - ventana < f <= fin))
    media, desv = resumen(base)
    anuales = collections.Counter(f.year for f in fechas)
    return {
        "lectura": actual,
        "media": media,
        "desviacion": desv,
        "fecha_dato": fechas[-1].isoformat(),
        "detalle": f"{actual} notas en 12 semanas; media histórica {media:.1f} ({len(base)} años)",
        "extra": {"anuales": {str(a): n for a, n in sorted(anuales.items())}, "primera_fecha": fechas[0].isoformat()},
    }
