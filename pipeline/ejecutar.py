"""Ejecución semanal de Nexo: descarga, aplica las reglas, valida y publica.

Uso:  python -m pipeline.ejecutar
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import pathlib
import statistics

import requests
import yaml

from . import modelo, validacion, variables
from .fuentes import acled, acnur, cdc, comun, ecdc, fao, gdelt, gdelt_eventos, oms, rsf

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "data" / "nexo-data.json"
LECTURAS = RAIZ / "datos" / "lecturas.csv"
FUENTES = {"oms_don": oms.leer, "ecdc_erviss": ecdc.leer, "delphi_fluview": cdc.leer,
           "gdelt": gdelt.leer, "gdelt_eventos": gdelt_eventos.leer, "acled": acled.leer,
           "fao": fao.leer, "acnur": acnur.leer, "rsf": rsf.leer}


def _yaml(ruta: pathlib.Path) -> dict:
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))


def _mensaje(e: Exception) -> str:
    if isinstance(e, requests.ConnectionError):
        return "Sin conexión con la fuente en esta ejecución; se reintentará en la próxima."
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"La fuente respondió con el código {e.response.status_code}; se reintentará en la próxima ejecución."
    if isinstance(e, requests.Timeout):
        return "La fuente tardó demasiado en responder; se reintentará en la próxima ejecución."
    if isinstance(e, requests.exceptions.RetryError):
        return "La fuente limitó las consultas por exceso de peticiones; se reintentará en la próxima ejecución."
    if isinstance(e, requests.RequestException):
        return "La fuente no respondió bien en esta ejecución; se reintentará en la próxima."
    return str(e) or e.__class__.__name__


def leer_variables(s, reglas: dict, anterior: dict, hoy: dt.date) -> tuple[dict, dict]:
    salida, extras = {}, {}
    _leer_lista(s, reglas, anterior, hoy, list(reglas["variables"].items()), salida, extras)
    # GDELT limita las consultas: las que fallaron se repiten una vez al final.
    fallidas = [(k, r) for k, r in reglas["variables"].items()
                if r["fuente"] == "gdelt" and salida[k]["estado"] in ("error", "desactualizado")]
    if fallidas:
        print(f"  Segundo intento con GDELT para {len(fallidas)} consultas")
        _leer_lista(s, reglas, anterior, hoy, fallidas, salida, extras)
    return {k: salida[k] for k in reglas["variables"]}, extras


def _leer_lista(s, reglas, anterior, hoy, lista, salida, extras) -> None:
    for clave, regla in lista:
        info = {"etiqueta": regla["etiqueta"], "motor": regla.get("motor"), "fuente": regla["fuente"],
                "regla": f"{regla['lectura']}. Línea base: {regla['linea_base']}."}
        try:
            r = FUENTES[regla["fuente"]](s, regla, hoy)
            z, x = variables.transformar(r["lectura"], r["media"], r["desviacion"])
            edad = (hoy - dt.date.fromisoformat(r["fecha_dato"])).days
            vigencia = regla.get("vigencia_dias", reglas["vigencia_dias"])
            salida[clave] = {**info, "estado": "ok" if edad <= vigencia else "desactualizado",
                             "lectura": round(r["lectura"], 4), "media": round(r["media"], 4),
                             "desviacion": round(r["desviacion"], 4), "z": round(z, 3), "valor": round(x, 3),
                             "fecha_dato": r["fecha_dato"], "detalle": r["detalle"], "detalle_lectura": r["detalle"]}
            if "extra" in r:
                extras[clave] = r["extra"]
            print(f"  ok   {clave}: {r['detalle']}")
        except Exception as e:  # una fuente caída no detiene a las demás
            mensaje = _mensaje(e)
            previa = anterior.get("variables", {}).get(clave, {})
            if previa.get("valor") is not None:
                base = previa.get("detalle_lectura") or previa.get("detalle", "").split(". Última lectura válida")[0]
                salida[clave] = {**previa, **info, "estado": "desactualizado", "detalle_lectura": base,
                                 "detalle": f"{base}. Última lectura válida; en esta ejecución falló: {mensaje}"}
            else:
                desactivada = regla.get("opcional") and "credenciales" in mensaje
                salida[clave] = {**info, "estado": "desactivada" if desactivada else "error",
                                 "valor": None, "detalle": mensaje[:300]}
            print(f"  --   {clave}: {mensaje[:160]}")


def combinar_motores(reglas: dict, vars_: dict) -> dict:
    motores = {}
    for nombre, info in reglas["motores"].items():
        comps = [k for k, v in reglas["variables"].items() if v.get("motor") == nombre]
        al_dia = [k for k in comps if vars_[k]["estado"] == "ok"]
        de_acled = [k for k in al_dia if reglas["variables"][k]["fuente"] == "acled"]
        if de_acled:
            al_dia = de_acled  # regla: ACLED tiene prioridad sobre GDELT
        valor = round(statistics.fmean(vars_[k]["valor"] for k in al_dia), 3) if al_dia else None
        motores[nombre] = {"valor": valor, "componentes": comps, "usadas": al_dia,
                           "e_previa": info["e_previa"], "pendiente": info.get("pendiente"),
                           "en_pronostico": False, "e": 0.0, "validacion": None}
    return motores


MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def _avance_gdelt(extras: dict, minimo: int) -> str:
    """Mensaje de avance de la historia de GDELT hacia 2015."""
    primera = min((e["primera_fecha"] for k, e in extras.items() if k != "brotes_oms" and "primera_fecha" in e),
                  default=None)
    if not primera:
        return "La historia de GDELT se está rellenando hacia atrás en cada ejecución."
    d = dt.date.fromisoformat(primera)
    faltan = max(0, (d - gdelt_eventos.INICIO_HISTORIA).days)
    ejecuciones = math.ceil(faltan / gdelt_eventos.DIAS_HISTORIA_POR_EJECUCION)
    texto = f"La historia de GDELT ya cubre desde el {d.day} {MESES[d.month - 1]} {d.year}. "
    if ejecuciones:
        texto += (f"Cada ejecución añade unos {gdelt_eventos.DIAS_HISTORIA_POR_EJECUCION} días hacia atrás: llegará a 2015 "
                  f"en unas {ejecuciones} ejecuciones, cerca de {ejecuciones * 2} días. ")
    return texto + f"Cuando cubra {minimo} años completos, este motor se pondrá a prueba."


def validar_motores(reglas: dict, motores: dict, extras: dict, hoy: dt.date) -> None:
    emerg = _yaml(RAIZ / reglas["validacion"]["archivo"])
    anios_con = {int(d["fecha"][:4]) for d in emerg["declaradas"]}
    resultado = {a: int(a in anios_con) for a in range(emerg["primer_anio"], hoy.year)}
    kw = {"minimo_anios": reglas["validacion"]["minimo_anios"],
          "calentamiento": reglas["validacion"]["anios_calentamiento"]}

    for nombre, m in motores.items():
        # Busca, entre las variables del motor, una con serie anual (la OMS o los eventos de GDELT).
        fuente = next((k for k in m["componentes"] if extras.get(k, {}).get("anuales")), None)
        if not fuente:
            continue
        ex = extras[fuente]
        if fuente == "brotes_oms":
            predictor = {int(a): math.log1p(n) for a, n in ex["anuales"].items()
                         if int(a) < hoy.year and f"{a}-01-15" >= ex.get("primera_fecha", "9999")}
            texto = "Notas de la OMS del año anterior"
        else:
            predictor = {int(a): v for a, v in ex["anuales"].items() if int(a) < hoy.year}
            texto = f"{reglas['variables'][fuente]['etiqueta']} del año anterior"
            if fuente == "prensa_rsf":
                continue  # la prensa entra solo por el juego
        v = validacion.validar(predictor, resultado, **kw) if predictor else {
            "estado": "historial_insuficiente", "n": 0, "mensaje": "Sin serie anual esta vez."}
        if v["estado"] == "historial_insuficiente" and reglas["variables"][fuente]["fuente"] == "gdelt_eventos":
            v["mensaje"] = _avance_gdelt(extras, kw["minimo_anios"])
        m["validacion"] = {"predictor": texto, **v}
        if v["estado"] == "validada" and m["valor"] is not None:
            m["en_pronostico"] = True
            m["e"] = v["elasticidad"]

    for nombre, m in motores.items():
        if m["validacion"] is None:
            de_gdelt = any(reglas["variables"][k]["fuente"] == "gdelt_eventos" for k in m["componentes"])
            if nombre == "prensa":
                m["validacion"] = {"estado": "historial_insuficiente", "mensaje":
                                   "Entra por el juego. Su historia comparable empieza en 2022, cuando RSF cambió su método."}
                continue
            m["validacion"] = {"estado": "historial_insuficiente", "mensaje": (
                _avance_gdelt(extras, kw["minimo_anios"]) if de_gdelt else
                m["pendiente"] or "Aún no hay historial anual para compararlo con las emergencias.")}


def validar_hipotesis(s, reglas: dict, hoy: dt.date) -> dict:
    h = reglas["hipotesis"]
    salida = {"autor": {"nombre": h["autor"]["nombre"], "peso": 0.0, "estado": "historial_insuficiente",
                        "mensaje": h["autor"]["regla"]}}
    t = h["tregua"]
    tregua = {"nombre": t["nombre"], "peso": 0.0, "estado": "historial_insuficiente", "mensaje": t["regla"], "eventos": []}
    try:
        emerg = _yaml(RAIZ / reglas["validacion"]["archivo"])
        fechas = [dt.date.fromisoformat(d["fecha"]) for d in emerg["declaradas"]]
        eventos = acled.tregua(s, fechas, t["ventana_semanas"], hoy)
        validos = [e for e in eventos if e["cociente"] is not None]
        tregua["eventos"] = eventos
        if len(validos) >= 3:
            a_favor = sum(e["cociente"] < t["umbral"] for e in validos)
            tregua["estado"] = "apoya" if a_favor > len(validos) / 2 else "no_apoya"
            tregua["mensaje"] = (f"En {a_favor} de {len(validos)} emergencias el conflicto bajó al menos un "
                                 f"{round((1 - t['umbral']) * 100)} % en las {t['ventana_semanas']} semanas siguientes.")
        else:
            tregua["mensaje"] = f"Solo {len(validos)} emergencias con datos completos; la regla pide 3."
    except Exception as e:
        if "credenciales" in str(e):
            tregua["estado"] = "sin_fuente"
            tregua["mensaje"] = ("Necesita una cuenta gratuita de ACLED para comparar los combates y bombardeos "
                                 "antes y después de cada emergencia declarada desde 2018.")
        else:
            tregua["mensaje"] = f"No se pudo probar en esta ejecución: {_mensaje(e)}"
    salida["tregua"] = tregua
    return salida


def _series(vars_: dict, maximo: int = 60) -> dict:
    """Últimas lecturas de cada variable, para dibujar su evolución en la página."""
    series: dict[str, dict[str, float]] = {}
    if not LECTURAS.exists():
        return {}
    with LECTURAS.open(encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila.get("variable") in vars_ and fila.get("valor") not in (None, "", "None") and fila.get("estado") == "ok":
                try:
                    series.setdefault(fila["variable"], {})[fila["fecha"]] = round(float(fila["valor"]), 3)
                except ValueError:
                    continue
    return {k: [[f, v[f]] for f in sorted(v)][-maximo:] for k, v in series.items()}


def main() -> None:
    reglas = _yaml(RAIZ / "reglas.yaml")
    anterior = json.loads(SALIDA.read_text(encoding="utf-8")) if SALIDA.exists() else {}
    hoy = dt.date.today()
    print(f"Nexo, reglas v{reglas['version']}, {hoy}")

    s = comun.sesion()
    vars_, extras = leer_variables(s, reglas, anterior, hoy)
    motores = combinar_motores(reglas, vars_)
    validar_motores(reglas, motores, extras, hoy)

    rj = reglas["juego"]
    j_base = modelo.juego(rj["base"])
    j_hoy, params_hoy, usadas = modelo.juego_con_datos(rj["base"], rj["entradas"], motores, rj.get("limites", {}))
    juego = {"base": {k: round(v, 4) for k, v in j_base.items()},
             "hoy": {k: round(v, 4) for k, v in j_hoy.items()},
             "parametros_hoy": params_hoy, "entradas": usadas,
             "multiplicador": round(j_hoy["escape"] / j_base["escape"], 4),
             "en_pronostico": False,
             "validacion": {"estado": "historial_insuficiente", "mensaje": rj["regla"]}}
    log_m = sum(m["e"] * m["valor"] for m in motores.values() if m["en_pronostico"])
    p = reglas["pronostico"]
    pron = {tipo: modelo.pronostico(cfg["eventos"], cfg["anios"], p["tendencia_anual"], math.exp(log_m),
                                    p["simulaciones"], p["semilla"])
            for tipo, cfg in p["tasa_base"].items()}

    historial = [h for h in anterior.get("historial", []) if h["fecha"] != hoy.isoformat()]
    historial.append({"fecha": hoy.isoformat(), "anio_50": pron["cualquiera"]["anio_50"],
                      "p_2027_2036": pron["cualquiera"]["p_2027_2036"]})

    datos = {
        "version_reglas": reglas["version"],
        "generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "reglas": {"tendencia": p["tendencia_anual"], "justificacion_tendencia": p["justificacion_tendencia"],
                   "transformacion": reglas["transformacion"], "vigencia_dias": reglas["vigencia_dias"],
                   "validacion": reglas["validacion"]["regla"]},
        "variables": vars_,
        "motores": motores,
        "juego": juego,
        "multiplicador": round(math.exp(log_m), 4),
        "pronostico": pron,
        "hipotesis": validar_hipotesis(s, reglas, hoy),
        "eventos": _yaml(RAIZ / "datos" / "eventos.yaml")["eventos"],
        "historial": historial[-400:],
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")

    nuevo = not LECTURAS.exists()
    with LECTURAS.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["fecha", "variable", "estado", "lectura", "z", "valor", "fecha_dato"])
        for k, v in vars_.items():
            w.writerow([hoy.isoformat(), k, v["estado"], v.get("lectura"), v.get("z"), v.get("valor"), v.get("fecha_dato")])

    datos["series"] = _series(vars_)
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")

    c = pron["cualquiera"]
    print(f"Pronóstico: 50 % en {c['anio_50']}, {c['p_2027_2036']:.0%} entre 2027 y 2036. Escrito en {SALIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
