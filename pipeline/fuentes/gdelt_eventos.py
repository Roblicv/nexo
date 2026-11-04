"""GDELT 2.0, archivos de eventos: descarga directa, sin el límite de consultas de la API.

GDELT publica cada 15 minutos un archivo con los eventos codificados de las noticias del mundo
(columnas separadas por tabuladores, 61 por fila) y otro con los de medios no anglófonos traducidos.
Nexo toma una muestra (un archivo cada 3 horas en los últimos 84 días; dos al día para la historia),
la resume por día y guarda ese resumen en datos/gdelt_diario.jsonl para no volver a descargarla.

Cada ejecución también rellena hacia atrás unos meses de historia desde 2015. Cuando esa historia
esté completa, los motores de movilización, conflicto y cooperación podrán validarse.
"""
from __future__ import annotations

import collections
import concurrent.futures as cf
import datetime as dt
import io
import json
import pathlib
import statistics
import zipfile
from urllib.parse import urlparse

import requests

from .comun import AGENTE, FuenteError, es, resumen

URL = "http://data.gdeltproject.org/gdeltv2/{marca}.{flujo}export.CSV.zip"
FLUJOS = ("", "translation.")  # medios en inglés y medios traducidos
HORAS_RECIENTES = ("000000", "030000", "060000", "090000", "120000", "150000", "180000", "210000")
HORAS_HISTORIA = ("000000", "120000")
DIAS_RECIENTES = 84
DIAS_HISTORIA_POR_EJECUCION = 150
INICIO_HISTORIA = dt.date(2015, 3, 1)
ARCHIVO = pathlib.Path(__file__).resolve().parents[2] / "datos" / "gdelt_diario.jsonl"

# Códigos FIPS del país donde ocurre el evento (columna ActionGeo_CountryCode)
REGIONES = {
    "latam": {"AR", "BL", "BR", "CI", "CO", "EC", "MX", "PE", "VE", "UY", "PA", "PM", "GT", "HO", "NU",
              "ES", "CS", "DR", "CU", "HA"},
    "europa_oeste": {"FR", "GM", "SP", "IT", "UK", "PO", "BE", "NL", "AU", "SZ", "EI", "SW", "DA", "NO", "FI", "GR"},
    "europa_este": {"PL", "UP", "HU", "RO", "RI", "GG", "LO", "BU", "EZ", "BO", "MD", "LH", "LG", "EN", "HR",
                    "SI", "BK", "AL", "MK", "MJ", "KV"},
}
MEDIOS = {
    "ru": ({".ru"}, {"rt.com", "sputniknews.com", "sputnikglobe.com", "tass.com"}),
    "cn": ({".cn"}, {"cgtn.com", "xinhuanet.com", "chinadaily.com.cn", "globaltimes.cn", "ecns.cn"}),
}

_CACHE: dict = {}


def grupo_medio(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for grupo, (sufijos, dominios) in MEDIOS.items():
        if any(host.endswith(s) for s in sufijos) or any(host == d or host.endswith("." + d) for d in dominios):
            return grupo
    return "otros"


def agregar(texto: str, acum: collections.Counter) -> None:
    """Suma los eventos de un archivo al resumen del día."""
    for linea in texto.splitlines():
        c = linea.split("\t")
        if len(c) < 61:
            continue
        try:
            raiz, quad, gold = int(c[28]), int(c[29]), float(c[30])
        except ValueError:
            continue
        a1, a2, pais, medio = c[7], c[17], c[53], grupo_medio(c[60])
        protesta, conflicto = raiz == 14, raiz in (18, 19, 20)
        intl = bool(a1 and a2 and a1 != a2)
        acum["total"] += 1
        acum["protesta"] += protesta
        acum["conflicto"] += conflicto
        if intl:
            acum["intl"] += 1
            acum["intl_gold"] += gold
            acum["coop_intl"] += quad in (1, 2)
            acum["eeuu_iran"] += {a1, a2} == {"USA", "IRN"} and quad == 4
        for region, paises in REGIONES.items():
            if pais in paises:
                acum[f"{region}_total"] += 1
                acum[f"{region}_protesta"] += protesta
        acum[f"{medio}_total"] += 1
        acum[f"{medio}_conflicto"] += conflicto
        if intl:
            acum[f"{medio}_intl"] += 1
            acum[f"{medio}_intl_gold"] += gold


def _descargar(sesion: requests.Session, dia: dt.date, hora: str, flujo: str) -> str | None:
    url = URL.format(marca=dia.strftime("%Y%m%d") + hora, flujo=flujo)
    r = sesion.get(url, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        return z.read(z.namelist()[0]).decode("utf-8", errors="replace")


def _resumir_dias(dias: list[dt.date], horas: tuple[str, ...], muestreo: str) -> dict:
    sesion = requests.Session()
    sesion.headers["User-Agent"] = AGENTE
    tareas = [(d, h, f) for d in dias for h in horas for f in FLUJOS]
    por_dia = {d: collections.Counter() for d in dias}
    archivos = collections.Counter()
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futuros = {ex.submit(_descargar, sesion, d, h, f): d for d, h, f in tareas}
        for fut in cf.as_completed(futuros):
            d = futuros[fut]
            try:
                texto = fut.result()
            except Exception:
                continue
            if texto:
                agregar(texto, por_dia[d])
                archivos[d] += 1
    return {d.isoformat(): {"fecha": d.isoformat(), "muestreo": muestreo, "archivos": archivos[d], **por_dia[d]}
            for d in dias if archivos[d] > 0}


def actualizar(hoy: dt.date) -> dict:
    """Completa el resumen diario y lo devuelve. Se ejecuta una sola vez por corrida."""
    if "datos" in _CACHE:
        return _CACHE["datos"]
    datos = {}
    if ARCHIVO.exists():
        for linea in ARCHIVO.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                fila = json.loads(linea)
                datos[fila["fecha"]] = fila
    recientes = [hoy - dt.timedelta(days=k) for k in range(1, DIAS_RECIENTES + 1)]
    faltan = [d for d in recientes if datos.get(d.isoformat(), {}).get("muestreo") != "3h"]
    if faltan:
        print(f"  GDELT eventos: {len(faltan)} días recientes por descargar")
        datos.update(_resumir_dias(faltan, HORAS_RECIENTES, "3h"))
    tope = min([dt.date.fromisoformat(f) for f in datos] + [recientes[-1]])
    historia, d = [], tope - dt.timedelta(days=1)
    while d >= INICIO_HISTORIA and len(historia) < DIAS_HISTORIA_POR_EJECUCION:
        if d.isoformat() not in datos:
            historia.append(d)
        d -= dt.timedelta(days=1)
    if historia:
        print(f"  GDELT eventos: rellenando historia desde {historia[-1]} hasta {historia[0]}")
        datos.update(_resumir_dias(historia, HORAS_HISTORIA, "12h"))
    if not datos:
        raise FuenteError("No se pudo descargar ningún archivo de eventos de GDELT.")
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVO.write_text("".join(json.dumps(datos[k], ensure_ascii=False) + "\n" for k in sorted(datos)), encoding="utf-8")
    _CACHE["datos"] = datos
    return datos


def _valor(filas: list[dict], num: str, den: str) -> float | None:
    n, m = sum(f.get(num, 0) for f in filas), sum(f.get(den, 0) for f in filas)
    return n / m if m >= 30 else None


def leer(s, regla: dict, hoy: dt.date) -> dict:
    datos = actualizar(hoy)
    num, den, escala = regla["numerador"], regla["denominador"], regla.get("escala", 100.0)
    fin = hoy - dt.timedelta(days=1)

    def ventana(final: dt.date, dias: int) -> list[dict]:
        return [datos[x] for x in ((final - dt.timedelta(days=k)).isoformat() for k in range(dias)) if x in datos]

    actual_filas = ventana(fin, 28)
    if len(actual_filas) < 20:
        raise FuenteError(f"Solo {len(actual_filas)} de los últimos 28 días tienen datos de GDELT.")
    actual = _valor(actual_filas, num, den)
    if actual is None:
        raise FuenteError("Muy pocos eventos en la ventana actual para calcular la lectura.")
    # Línea base: las mismas 4 semanas en años anteriores si hay al menos 3; si no, las 8 semanas previas.
    base, tipo_base = [], ""
    for anios_atras in range(1, 12):
        try:
            f = fin.replace(year=fin.year - anios_atras)
        except ValueError:
            f = fin.replace(year=fin.year - anios_atras, day=28)
        filas = ventana(f, 28)
        if len(filas) >= 20 and (v := _valor(filas, num, den)) is not None:
            base.append(v * escala)
    if len(base) >= 3:
        tipo_base = f"las mismas 4 semanas de {len(base)} años anteriores"
    else:
        base = []
        for semana in range(4, 12):
            filas = ventana(fin - dt.timedelta(days=7 * semana), 7)
            if len(filas) >= 4 and (v := _valor(filas, num, den)) is not None:
                base.append(v * escala)
        tipo_base = "las 8 semanas anteriores"
    media, desv = resumen(base)
    anuales = {}
    for anio in sorted({int(k[:4]) for k in datos}):
        filas = [v for k, v in datos.items() if k.startswith(str(anio))]
        if len(filas) >= 200 and (v := _valor(filas, num, den)) is not None:
            anuales[str(anio)] = round(v * escala, 4)
    unidad = regla.get("unidad", "%")
    fmt = (lambda x: es(x, 2) + " %") if unidad == "%" else (lambda x: ("+" if x > 0 else "") + es(x, 2))
    return {
        "lectura": actual * escala,
        "media": media,
        "desviacion": desv,
        "fecha_dato": max(f["fecha"] for f in actual_filas),
        "detalle": f"{regla.get('que', 'Valor')}: {fmt(actual * escala)} en las últimas 4 semanas; {fmt(media)} en {tipo_base}",
        "extra": {"anuales": anuales, "primera_fecha": min(datos)},
    }
