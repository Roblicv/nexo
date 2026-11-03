"""ACLED: eventos de protesta y de conflicto armado. Opcional: necesita una cuenta gratuita de ACLED.

Usa las variables de entorno ACLED_USUARIO y ACLED_CLAVE (en GitHub: Settings > Secrets).
ACLED cambió su sistema de acceso en 2025; si la primera ejecución falla aquí, revisa
https://acleddata.com/api-documentation y ajusta URL_TOKEN o URL_DATOS. El resto de Nexo sigue funcionando.
"""
from __future__ import annotations

import datetime as dt
import os

from .comun import FuenteError, resumen

URL_TOKEN = "https://acleddata.com/oauth/token"
URL_DATOS = "https://acleddata.com/api/acled/read"
_TOKEN: list[str] = []


def token(s) -> str:
    if _TOKEN:
        return _TOKEN[0]
    usuario, clave = os.environ.get("ACLED_USUARIO"), os.environ.get("ACLED_CLAVE")
    if not usuario or not clave:
        raise FuenteError("Sin credenciales de ACLED: fuente opcional desactivada.")
    r = s.post(URL_TOKEN, data={"username": usuario, "password": clave,
                                "grant_type": "password", "client_id": "acled"}, timeout=40)
    r.raise_for_status()
    _TOKEN.append(r.json()["access_token"])
    return _TOKEN[0]


def contar(s, tipos: list[str], inicio: dt.date, fin: dt.date, pais: str | None = None) -> int:
    """Cuenta eventos de uno o varios tipos entre dos fechas."""
    return sum(_contar_tipo(s, t, inicio, fin, pais) for t in tipos)


def _contar_tipo(s, tipo: str, inicio: dt.date, fin: dt.date, pais: str | None) -> int:
    total, pagina = 0, 1  # se pagina de 5.000 en 5.000
    while True:
        params = {"_format": "json", "event_type": tipo,
                  "event_date": f"{inicio.isoformat()}|{fin.isoformat()}", "event_date_where": "BETWEEN",
                  "fields": "event_id_cnty", "limit": 5000, "page": pagina}
        if pais:
            params["country"] = pais
        r = s.get(URL_DATOS, headers={"Authorization": f"Bearer {token(s)}"}, params=params, timeout=90)
        r.raise_for_status()
        filas = r.json().get("data", [])
        total += len(filas)
        if len(filas) < 5000 or pagina >= 40:
            return total
        pagina += 1


def _mismo_periodo(fecha: dt.date, anio: int) -> dt.date:
    try:
        return fecha.replace(year=anio)
    except ValueError:  # 29 de febrero
        return fecha.replace(year=anio, day=28)


def leer(s, regla: dict, hoy: dt.date) -> dict:
    tipos = regla.get("tipos_evento", ["Protests"])
    fin = hoy - dt.timedelta(days=7)  # ACLED publica con una semana de retraso
    inicio = fin - dt.timedelta(weeks=4)
    actual = sum(contar(s, tipos, inicio, fin, p) for p in regla["paises"])
    base = []
    for anio in range(2018, 2026):
        i = _mismo_periodo(inicio, anio - (inicio.year != fin.year))
        f = _mismo_periodo(fin, anio)
        base.append(sum(contar(s, tipos, i, f, p) for p in regla["paises"]))
    media, desv = resumen(base)
    return {
        "lectura": actual,
        "media": media,
        "desviacion": desv,
        "fecha_dato": fin.isoformat(),
        "detalle": f"{actual} eventos en 4 semanas en {len(regla['paises'])} países; media 2018-2025: {media:.0f}",
    }


def tregua(s, fechas: list[dt.date], semanas: int, hoy: dt.date) -> list[dict]:
    """Combates y bombardeos en todo el mundo antes y después de cada emergencia."""
    tipos = ["Battles", "Explosions/Remote violence"]
    ventana = dt.timedelta(weeks=semanas)
    salida = []
    for f in fechas:
        if f - ventana < dt.date(2018, 1, 1) or f + ventana > hoy - dt.timedelta(days=7):
            continue
        antes = contar(s, tipos, f - ventana, f - dt.timedelta(days=1))
        despues = contar(s, tipos, f, f + ventana - dt.timedelta(days=1))
        salida.append({"fecha": f.isoformat(), "antes": antes, "despues": despues,
                       "cociente": round(despues / antes, 3) if antes else None})
    return salida
