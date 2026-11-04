"""FAO: índice mensual de precios de los alimentos (FFPI), desde 1990."""
from __future__ import annotations

import datetime as dt
import re
import statistics

from .comun import FuenteError, es, resumen

PAGINA = "https://www.fao.org/worldfoodsituation/foodpricesindex/en/"
CSV_RESPALDO = "https://www.fao.org/media/docs/worldfoodsituationlibraries/wfs-library/food_price_indices_data.csv"


def _url_csv(s) -> str:
    """El enlace al CSV cambia de parámetros cada mes: se toma de la página."""
    try:
        r = s.get(PAGINA, timeout=40)
        r.raise_for_status()
        m = re.search(r'href="([^"]*food_price_indices_data[^"]*\.csv[^"]*)"', r.text)
        if m:
            url = m.group(1).replace("&amp;", "&")
            return url if url.startswith("http") else "https://www.fao.org" + url
    except Exception:
        pass
    return CSV_RESPALDO


def leer(s, regla: dict, hoy: dt.date) -> dict:
    r = s.get(_url_csv(s), timeout=60)
    r.raise_for_status()
    serie: dict[tuple[int, int], float] = {}
    for linea in r.content.decode("utf-8-sig", errors="replace").splitlines():
        c = linea.split(",")
        if len(c) > 1 and re.fullmatch(r"\d{4}-\d{2}", c[0].strip()) and c[1].strip():
            try:
                anio, mes = map(int, c[0].split("-"))
                serie[(anio, mes)] = float(c[1])
            except ValueError:
                continue
    if len(serie) < 48:
        raise FuenteError("El CSV de la FAO no trae la serie mensual esperada.")
    meses = sorted(serie)
    (anio, mes), valor = meses[-1], serie[meses[-1]]
    media, desv = resumen([serie[k] for k in meses[-37:-1]])
    anuales = {}
    for a in sorted({k[0] for k in meses}):
        vals = [v for (y, _), v in serie.items() if y == a]
        if len(vals) == 12:
            anuales[str(a)] = round(statistics.fmean(vals), 2)
    fin_mes = (dt.date(anio + (mes == 12), mes % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
    return {
        "lectura": valor, "media": media, "desviacion": desv, "fecha_dato": fin_mes,
        "detalle": f"Índice {es(valor)} en {mes:02d}/{anio}; media de los 36 meses anteriores {es(media)}",
        "extra": {"anuales": anuales},
    }
