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
from .fuentes import acled, cdc, comun, ecdc, gdelt, oms

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "data" / "nexo-data.json"
LECTURAS = RAIZ / "datos" / "lecturas.csv"
FUENTES = {"oms_don": oms.leer, "ecdc_erviss": ecdc.leer, "delphi_fluview": cdc.leer,
           "gdelt": gdelt.leer, "acled": acled.leer}


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
    for clave, regla in reglas["variables"].items():
        info = {"etiqueta": regla["etiqueta"], "motor": regla.get("motor"), "fuente": regla["fuente"],
                "regla": f"{regla['lectura']}. Línea base: {regla['linea_base']}."}
        try:
            r = FUENTES[regla["fuente"]](s, regla, hoy)
            z, x = variables.transformar(r["lectura"], r["media"], r["desviacion"])
            edad = (hoy - dt.date.fromisoformat(r["fecha_dato"])).days
            salida[clave] = {**info, "estado": "ok" if edad <= reglas["vigencia_dias"] else "desactualizado",
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
    return salida, extras


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


def validar_motores(reglas: dict, motores: dict, extras: dict, hoy: dt.date) -> None:
    emerg = _yaml(RAIZ / reglas["validacion"]["archivo"])
    anios_con = {int(d["fecha"][:4]) for d in emerg["declaradas"]}
    resultado = {a: int(a in anios_con) for a in range(emerg["primer_anio"], hoy.year)}
    kw = {"minimo_anios": reglas["validacion"]["minimo_anios"],
          "calentamiento": reglas["validacion"]["anios_calentamiento"]}

    anuales = extras.get("brotes_oms", {}).get("anuales", {})
    primera = extras.get("brotes_oms", {}).get("primera_fecha", "9999")
    completos = {int(a): math.log1p(n) for a, n in anuales.items()
                 if int(a) < hoy.year and f"{a}-01-15" >= primera}
    v = validacion.validar(completos, resultado, **kw) if completos else {
        "estado": "historial_insuficiente", "n": 0, "mensaje": "Sin serie anual de la OMS esta semana."}
    motores["brotes"]["validacion"] = {"predictor": "Notas de la OMS del año anterior", **v}
    if v["estado"] == "validada" and motores["brotes"]["valor"] is not None:
        motores["brotes"]["en_pronostico"] = True
        motores["brotes"]["e"] = v["elasticidad"]

    for nombre, m in motores.items():
        if m["validacion"] is None:
            m["validacion"] = {"estado": "historial_insuficiente",
                               "mensaje": m["pendiente"] or "Aún no hay historial anual para compararlo con las emergencias."}


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


def main() -> None:
    reglas = _yaml(RAIZ / "reglas.yaml")
    anterior = json.loads(SALIDA.read_text(encoding="utf-8")) if SALIDA.exists() else {}
    hoy = dt.date.today()
    print(f"Nexo, reglas v{reglas['version']}, {hoy}")

    s = comun.sesion()
    vars_, extras = leer_variables(s, reglas, anterior, hoy)
    motores = combinar_motores(reglas, vars_)
    validar_motores(reglas, motores, extras, hoy)

    juego = modelo.juego(modelo.JUEGO_BASE)
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
        "juego": {k: round(v, 4) for k, v in juego.items()},
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

    c = pron["cualquiera"]
    print(f"Pronóstico: 50 % en {c['anio_50']}, {c['p_2027_2036']:.0%} entre 2027 y 2036. Escrito en {SALIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
