# -*- coding: utf-8 -*-
"""
COACH LOL  v12  -  Tu plan para salir de Hierro

Como funciona:
  1. Revisa tus partidas y elige UN habito: el que mas victorias te esta costando.
  2. Antes de cada partida (seleccion de campeon) te da la mision de esa partida.
  3. Durante la partida te recuerda la mision en una ventanita, solo cuando toca.
  4. Al terminar te dice si la cumpliste o no, con la prueba.
  5. Cuando la cumples en 4 de 5 partidas, el habito queda dominado y pasa al siguiente.
  Ademas: anti-racha (para por hoy) y revision completa de cada partida.

Lee el cliente de LoL de tu PC (API local del cliente y API oficial de partida en vivo,
las mismas que usan Porofessor o Blitz). Sin API key, sin cuentas, sin instalar nada
aparte de Python.

Arranque: doble clic en INICIAR_COACH.bat   (o en consola:  python coach.py)
"""

import base64
import json
import math
import os
import queue
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# =============================================================== CONFIGURACION
CONFIG = {
    "puerto": 8765,
    "abrir_navegador_al_iniciar": True,
    "abrir_aviso_al_buscar_partida": True,   # si toca parar y buscas partida, te abre el aviso
    "hud_partida": True,                     # en partida: tarjetas pequeñas y oscuras que salen al mantener Tab
    "hud_opacidad": 0.9,                     # 1 = sin transparencia (se cambia desde Ajustes)
    "hud_tecla": 9,                          # tecla que las muestra mientras la mantienes (9 = Tab)
    "ventana_mision": True,                  # ventanita con la mision (seleccion y partida)
    "importar_runas": True,                  # aplica tus runas fijadas (o las de Riot para tu rol) al elegir campeón
    "importar_build": True,                  # pone tu build fijada como set de objetos en la tienda
    "importar_hechizos": True,               # pone los hechizos de invocador de la build elegida (Flash no cambia de tecla)
    "entreno_meta_inicial": 60,              # CS en 10 minutos en la Herramienta de práctica (sube de 10 en 10)

    # ---- Anti-racha
    "tope_partidas_dia": 4,
    "tope_maximo_dia": 7,          # aunque vayas bien, a partir de aqui el coach no estira mas el tope
    "derrotas_seguidas_para_parar": 2,
    "dia_empieza_hora": 5,                     # lo jugado antes de las 5:00 cuenta como el dia anterior
    "colas_anti_racha": [420, 440, 400, 430],  # 420 SoloQ, 440 Flex, 400 Normal Draft, 430 Normal a ciegas
    "colas_analizadas": [420, 440, 400, 430, 480, 490],  # Grieta del Invocador

    # ---- Plan de habitos
    "diag_partidas": 30,          # partidas que mira el diagnostico
    "ventana_dominio": 5,         # un habito se domina cumpliendolo...
    "cumplidas_para_dominar": 4,  # ...4 de las ultimas 5 partidas
    "muertes_max": 5,                         # meta base para subir (dodge.gg: en rangos bajos se muere 7-10)
    "muertes_niveles": [5, 4],                # etapa 1: 5 o menos; etapa 2: 4 o menos
    "cs10_niveles": [50, 60, 70],
    "vision_niveles": {"support": [1.2, 1.5], "otros": [0.6, 0.75]},   # puntuacion de vision por minuto
    "cs_post_min": 7.0,                       # CS/min entre el 14 y el 25 (dodge.gg: 7+ en mitad de partida)
    "nota_consistencia": 6.5,

    # ---- Roles y campeones: el coach elige 2 roles con tus numeros (nunca jungla)
    "roles_permitidos": ["top", "support", "mid", "bot"],   # en el orden que te gustan
    "campeones_preferidos": {"top": [83], "support": [44], "mid": [134], "bot": []},   # Yorick, Taric, Syndra
    "min_partidas_rol": 5,                    # partidas en un rol para que el coach pueda elegirlo
    "revisar_roles_cada": 25,                 # partidas antes de volver a revisar tus roles
    "torres_habito_min": 150,
    "wards_support_min": 0.8,

    # ---- Semaforo: (verde, amarillo). Lo que no llega a amarillo es rojo.
    "muertes": (5, 7),            # verde = la meta para subir (5 o menos); en Hierro lo normal es 7 a 10
    "cs_min": (6.0, 5.0),
    "cs_min_jungla": (5.5, 4.5),
    "cs_diff_10": (0, -14),
    "control_wards": (2, 1),
    "control_wards_support": (3, 2),
    "torres_min": (200, 100),
    "kp": (0.55, 0.45),
    "wards_min_support": (0.9, 0.6),

    # ---- Deteccion de errores
    "oro_sin_gastar": 1300,
    "fin_fase_lineas_min": 14,
    "wards_por_min_minimo": 0.35,

    # Si no encuentra el cliente solo, pon aqui tu carpeta de instalacion,
    # por ejemplo: r"D:\Riot Games\League of Legends"
    "ruta_lol": "",
}

ANALISIS_V = 14
NOTA_BIEN, NOTA_REGULAR = 7, 4.5   # nota del coach: desde 7 "jugaste bien"; desde 4,5 "regular"; menos, "mal"
VENTANA_PELEA_S = 15     # una muerte es "sin tu equipo" si ningun aliado mato, asistio o murio 15 s antes o despues
CONGELADO = bool(getattr(sys, "frozen", False))           # empaquetado como .exe
DIR = Path(sys.executable).resolve().parent if CONGELADO else Path(__file__).resolve().parent
# dashboard.html y la fuente: los de la carpeta si estan (asi una actualizacion vale sin rehacer el .exe)
RECURSOS = DIR if (DIR / "dashboard.html").exists() else Path(getattr(sys, "_MEIPASS", DIR))
VERSION = "44"
DATOS = DIR / "datos"
CRUDO = DATOS / "partidas"
CACHE = DATOS / "cache"
HIST = DATOS / "historial.json"
for _d in (DATOS, CRUDO, CACHE):
    _d.mkdir(parents=True, exist_ok=True)

COLAS = {420: "SoloQ", 440: "Flex", 400: "Normal", 430: "Normal a ciegas",
         480: "Swiftplay", 490: "Partida rápida"}
TIERS = {"IRON": "Hierro", "BRONZE": "Bronce", "SILVER": "Plata", "GOLD": "Oro",
         "PLATINUM": "Platino", "EMERALD": "Esmeralda", "DIAMOND": "Diamante",
         "MASTER": "Maestro", "GRANDMASTER": "Gran Maestro", "CHALLENGER": "Retador"}
FASES = {"None": "En el cliente", "Lobby": "En sala", "Matchmaking": "Buscando partida",
         "ReadyCheck": "Partida encontrada", "ChampSelect": "Selección de campeón",
         "GameStart": "Cargando partida", "InProgress": "En partida",
         "WaitingForStats": "Esperando estadísticas", "PreEndOfGame": "Fin de partida",
         "EndOfGame": "Fin de partida", "Reconnect": "Reconectando"}
ROL_TXT = {"top": "top", "jungla": "jungla", "mid": "mid", "bot": "ADC", "support": "support", "": "sin rol claro"}
POSICION_LCU = {"top": "top", "jungle": "jungla", "middle": "mid", "bottom": "bot", "utility": "support"}
YORICK = 83
SMITE = 11
CONTROL_WARD = 2055
# Objeto de support (Atlas mundial y sus mejoras)
SUPPORT_ITEMS = {3865, 3866, 3867, 3869, 3870, 3871, 3876, 3877}
# Consumibles, wards y amuletos: no cuentan como build
NO_BUILD = {2055, 2003, 2031, 2033, 2138, 2139, 2140, 2010, 2422, 3340, 3363, 3364, 3330, 3513}


def log(msg):
    linea = f"{datetime.now().strftime('%H:%M:%S')} {msg}"
    try:
        print(linea, flush=True)
    except Exception:
        pass                      # sin consola (pythonw o .exe)
    try:
        f = DATOS / "coach.log"
        if f.exists() and f.stat().st_size > 400_000:
            f.write_text("\n".join(f.read_text(encoding="utf-8", errors="ignore").splitlines()[-800:]) + "\n",
                         encoding="utf-8")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().strftime('%Y-%m-%d')} {linea}\n")
    except Exception:
        pass


def abrir_app(url):
    """Abre el coach en su propia ventana (Edge o Chrome en modo aplicacion: sin pestanas ni barra de
    direcciones). Si no hay ninguno, en el navegador de siempre."""
    if os.environ.get("COACH_SIN_NAVEGADOR"):
        return
    if os.name == "nt":
        bases = [os.environ.get(v) for v in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            for b in bases:
                exe = Path(b) / rel if b else None
                if exe and exe.exists():
                    try:
                        subprocess.Popen([str(exe), f"--app={url}", "--window-size=1340,900"],
                                         creationflags=0x08000000)
                        return
                    except Exception:
                        pass
    try:
        webbrowser.open(url)
    except Exception:
        pass


# =============================================================== BUILDS Y RUNAS DE LOLALYTICS (OTP y por rival)
# Lolalytics publica, por campeon y linea, la build y las runas de los "one trick" (quienes solo juegan ese
# campeon) y tambien las de cada enfrentamiento. No es una API oficial: puede cambiar, dejar de responder o
# rechazar al coach (que se identifica siempre como "CoachLoL"). Si falla, el coach usa la build de u.gg y,
# para las runas, las recomendadas por Riot.
LOLA_API = os.environ.get("COACH_LOLA_API", "https://a1.lolalytics.com/mega/")
LOLA_WEB = os.environ.get("COACH_LOLA_WEB", "https://lolalytics.com")
LOLA_LINEA = {"top": "top", "jungla": "jungle", "mid": "middle", "bot": "bottom", "support": "support"}
_PARCHE = {"v": None, "ts": 0}


def estilo_de_runa(pid, rec=None):
    """Arbol al que pertenece una runa, segun los datos del cliente de LoL. None si no se conoce."""
    v = (rec.runa_estilo.get(str(int(pid))) if rec is not None else None)
    return int(v) if v else None


def parches_actuales():
    """Los dos ultimos parches, como "16.22" (de Data Dragon; se recuerda una hora)."""
    if _PARCHE["v"] and time.time() - _PARCHE["ts"] < 3600:
        return _PARCHE["v"]
    base = os.environ.get("COACH_DDRAGON_URL", "https://ddragon.leagueoflegends.com").rstrip("/")
    out = []
    try:
        for v in _http_json(base + "/api/versions.json", timeout=6):
            p = ".".join(str(v).split(".")[:2])
            if re.fullmatch(r"\d+\.\d+", p) and p not in out:
                out.append(p)
            if len(out) == 2:
                break
    except Exception:
        pass
    if out:
        _PARCHE.update(v=out, ts=time.time())
    return out


def _lola_slug(rec, cid):
    a = re.sub(r"[^a-z]", "", (rec.alias.get(str(cid)) or "").lower())
    return {"monkeyking": "wukong"}.get(a, a)


def _no_es_de_build(rec, i):
    """Consumibles, amuletos y wards (categorias del cliente): no cuentan como objeto de build."""
    c = ((rec.items.get(str(i)) or {}).get("cat") or []) if rec is not None else []
    return bool({"Consumable", "Trinket"} & set(c))


def _no_se_compra(rec, i):
    """Objetos que no estan en la tienda (por ejemplo la mejora del objeto de support, que llega sola)."""
    if rec is None:
        return False

    def fuera(x, prof=0):
        d = rec.items.get(str(x)) or {}
        # no esta en la tienda, o sale de una pieza que no se vende (el objeto de support se transforma solo al
        # completar su mision: el cliente lo marca "en tienda", pero la pieza de la que sale no lo esta)
        return d.get("tienda") is False or (prof < 4 and any(fuera(c, prof + 1) for c in d.get("de") or []))
    return fuera(i)


def _lola_extraer(pick, rec=None, raiz=None, linea=None):
    """De un bloque "pick" de Lolalytics (lo mas jugado) saca runas, objetos, hechizos y habilidades.
    Los 3 primeros objetos son el nucleo mas jugado; los 3 siguientes, los mas comprados en 4.º, 5.º y 6.º
    lugar sumados (asi un objeto con 17 partidas no entra por delante de uno con 300).
    raiz: el JSON entero, para guardar ademas botas, objetos populares y % de victorias contra cada rival."""
    try:
        r = pick.get("runes") or {}
        rs = r.get("set") or {}
        pri, sec, mod = [int(x) for x in rs["pri"]], [int(x) for x in rs["sec"]], [int(x) for x in rs.get("mod") or []]
        runas = None
        if len(pri) == 4 and len(sec) == 2:
            e1 = {estilo_de_runa(x, rec) for x in pri} if len(mod) == 3 else {None}
            e2 = {estilo_de_runa(x, rec) for x in sec}
            if len(e1) == 1 and len(e2) == 1 and None not in e1 | e2 and e1 != e2:
                runas = {"primaryStyleId": e1.pop(), "subStyleId": e2.pop(), "selectedPerkIds": pri + sec + mod}
        it = pick.get("items") or {}
        core = it.get("core") or {}
        orden = [int(x) for x in core.get("set") or []]
        porque = {str(i): {"n": core.get("n"), "wr": core.get("wr"), "motivo": "núcleo más jugado"} for i in orden}
        if not orden:
            # Pagina de un enfrentamiento: no trae "nucleo", sino el objeto mas comprado en 1.º, 2.º y 3.º lugar,
            # cada uno con sus partidas y su % de victorias.
            for k in ("item1", "item2", "item3"):
                o = it.get(k)
                if isinstance(o, list):
                    o = max((x for x in o if isinstance(x, dict) and isinstance(x.get("n"), (int, float))),
                            key=lambda x: x["n"], default=None)
                if isinstance(o, dict) and o.get("id") and int(o["id"]) not in orden:
                    orden.append(int(o["id"]))
                    porque[str(int(o["id"]))] = {"n": o.get("n"), "wr": o.get("wr"),
                                                 "motivo": f"el más comprado como {k[-1]}.º objeto"}
        pool = {}
        for k in ("item4", "item5", "item6"):
            for o in it.get(k) or []:
                if isinstance(o, dict) and o.get("id") and isinstance(o.get("n"), (int, float)):
                    pool[int(o["id"])] = pool.get(int(o["id"]), 0) + int(o["n"])
        populares, botas, enemigos = [], [], {}
        if isinstance(raiz, dict):
            populares = [[int(x[0]), float(x[2])] for x in raiz.get("popularItem") or [] if isinstance(x, list) and len(x) >= 4]
            botas = [[int(x[0]), float(x[2])] for x in raiz.get("boots") or [] if isinstance(x, list) and len(x) >= 4]
            cols = raiz.get("enemy_h") or ["id", "wr", "d1", "d2", "pr", "n"]
            if "wr" in cols and "n" in cols:
                for x in ((raiz.get("enemy") or {}).get(linea) or []):
                    if isinstance(x, list) and len(x) == len(cols):
                        enemigos[str(int(x[0]))] = [float(x[cols.index("wr")]), int(x[cols.index("n")])]

        def vale(i):
            return i not in orden and not _no_es_de_build(rec, i) and (rec is None or not rec.items or str(i) in rec.items)
        # 4.º, 5.º y 6.º: en cada posicion, el mas comprado; se cambia por otro con mas % de victorias solo si
        # ese otro tambien se compra mucho (la mitad o mas) y la diferencia supera el margen de error.
        for k in ("item4", "item5", "item6"):
            ops = [o for o in it.get(k) or [] if isinstance(o, dict) and o.get("id") and vale(int(o["id"]))
                   and isinstance(o.get("n"), (int, float)) and isinstance(o.get("wr"), (int, float))]
            if not ops or len(orden) >= 6:
                continue
            top = max(ops, key=lambda o: o["n"])
            if top["n"] < 30:
                continue                                   # pocas partidas en esta posicion: se rellena abajo
            elegido, motivo = top, f"el más comprado como {k[-1]}.º objeto"
            for o in sorted(ops, key=lambda o: -o["wr"]):
                if o is top or o["n"] < 0.5 * top["n"]:
                    continue
                p = (o["wr"] * o["n"] + top["wr"] * top["n"]) / (o["n"] + top["n"]) / 100
                error = 100 * 1.64 * math.sqrt(max(p * (1 - p), 1e-9) * (1 / o["n"] + 1 / top["n"]))
                if o["wr"] - top["wr"] > error:
                    elegido = o
                    motivo = (f"gana más como {k[-1]}.º objeto que {rec.item(int(top['id'])) if rec else top['id']} "
                              f"({_dec(o['wr'])}% frente a {_dec(top['wr'])}%)")
                break
            orden.append(int(elegido["id"]))
            porque[str(int(elegido["id"]))] = {"n": int(elegido["n"]), "wr": elegido["wr"], "motivo": motivo}
        minimo = max(15, 0.04 * max(pool.values())) if pool else 15
        for i, n in sorted(pool.items(), key=lambda x: -x[1]):
            if len(orden) < 6 and vale(i) and n >= minimo:
                orden.append(i)
                porque[str(i)] = {"n": n, "wr": None, "motivo": "el más comprado entre el 4.º y el 6.º objeto"}
        for i, pct in populares:                           # si faltan, los mas comprados en general
            if len(orden) < 6 and vale(i) and pct >= 5 and not _es_bota(rec, i):
                orden.append(i)
        ini = it.get("start") or {}
        inicio = [int(x) for x in ini.get("setUnique") or ini.get("set") or []]
        if rec is not None and rec.items:
            orden = [i for i in orden if str(i) in rec.items]
            inicio = [i for i in inicio if str(i) in rec.items]
        if len(orden) < 3:
            return None
        n_min = min((v["n"] for v in (porque.get(str(i)) for i in orden[:3]) if v and isinstance(v.get("n"), (int, float))),
                    default=None)
        out = {"runas": runas, "inicio": inicio, "orden": orden, "wr": core.get("wr"), "n": core.get("n") or n_min,
               "wr_runas": r.get("wr"), "n_runas": r.get("n"), "pool": {str(k): v for k, v in pool.items()},
               "populares": populares, "botas": botas, "enemigos": enemigos, "porque": porque}
        hs = [int(x) for x in (pick.get("sums") or {}).get("ids") or []]
        if len(hs) == 2:
            out["hechizos"] = hs
        prio = (pick.get("skillpriority") or {}).get("id")
        if isinstance(prio, str) and len(prio) == 3 and set(prio) <= set("QWE"):
            out["habilidades"] = prio
        so = str((pick.get("skillorder") or {}).get("id") or "")
        if len(so) >= 3 and set(so) <= set("1234"):
            out["primeras"] = ["QWER"[int(c) - 1] for c in so[:3]]
        return out
    except Exception:
        return None


def _es_bota(rec, i):
    return rec is not None and i != 1001 and "Boots" in ((rec.items.get(str(i)) or {}).get("cat") or [])


def _qwik(data):
    """Deshace el formato de las paginas de Lolalytics ({_objs: [...]}, donde cada valor es el indice en base 36
    de otro elemento). Devuelve {"pick": bloque con runas, hechizos y objetos del enfrentamiento,
    "wr": % de victorias del campeon contra ese rival, "n": partidas del enfrentamiento} o None."""
    objs = data.get("_objs") if isinstance(data, dict) else None
    if not isinstance(objs, list):
        return None

    def res(ref, prof=0):
        if not isinstance(ref, str) or prof > 12:
            return ref
        limpio = re.sub(r"[^0-9a-z]", "", ref)
        if not limpio or ord(ref[0]) < 32:
            return None
        try:
            v = objs[int(limpio, 36)]
        except Exception:
            return None
        if isinstance(v, dict):
            return {k: res(x, prof + 1) for k, x in v.items()}
        if isinstance(v, list):
            return [res(x, prof + 1) if isinstance(x, str) else x for x in v]
        if isinstance(v, str) and v and ord(v[0]) < 32:
            return None
        return v
    pick = None
    for o in objs:
        if isinstance(o, dict) and "pick" in o and "win" in o:
            cand = res(o["pick"], 1)
            if isinstance(cand, dict) and "items" in cand:
                pick = cand
                break
    if pick is None:
        for o in objs:
            if isinstance(o, dict) and {"skillpriority", "sums", "runes", "items"} <= set(o):
                pick = {k: res(x, 1) for k, x in o.items()}
                break
    if pick is None:
        return None
    out = {"pick": pick, "wr": None, "n": None}
    for o in objs:                       # cabecera del enfrentamiento: % de victorias y partidas contra ese rival
        if isinstance(o, dict) and {"vsWinRate", "wr", "n"} <= set(o):
            wr, n = res(o["wr"], 1), res(o["n"], 1)
            if isinstance(wr, (int, float)) and isinstance(n, (int, float)):
                out["wr"], out["n"] = float(wr), int(n)
            break
    return out


def _lola_cache(nombre, pedir):
    f = CACHE / nombre
    viejo = None
    try:
        viejo = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - viejo.get("ts", 0) < BUILD_DIAS * 86400:
            return viejo
    except Exception:
        pass
    try:
        b = pedir()
        if b:
            b["ts"] = time.time()
            try:
                f.write_text(json.dumps(b), encoding="utf-8")
            except Exception:
                pass
            return b
    except Exception as e:
        log(f"No pude leer Lolalytics ({type(e).__name__}: {e}).")
    return viejo


def lola_build(rec, cid, rol, tier="1trick"):
    """Build y runas de un campeon en una linea. tier "1trick" = solo jugadores OTP."""
    slug, linea = _lola_slug(rec, cid), LOLA_LINEA.get(rol)
    if not slug or not linea:
        return None

    def pedir():
        for parche in parches_actuales() or ["30"]:
            d = _http_json(f"{LOLA_API}?ep=build-full&v=1&patch={parche}&c={slug}&lane={linea}&tier={tier}"
                           "&queue=ranked&region=all", timeout=12)
            b = _lola_extraer(((d or {}).get("summary") or {}).get("pick") or {}, rec, d, linea)
            total = ((d or {}).get("header") or {}).get("n") or 0
            if b and total >= 150:
                b.update(parche=parche, total=total, wr_total=(d.get("header") or {}).get("wr"), tier=tier)
                return b
        return None
    return _lola_cache(f"lola_{int(cid)}_{rol}_{tier}.json", pedir)


def lola_vs(rec, cid, rol, rival):
    """Build y runas de un campeon contra un rival concreto (pagina del enfrentamiento en Lolalytics)."""
    slug, otro, linea = _lola_slug(rec, cid), _lola_slug(rec, rival), LOLA_LINEA.get(rol)
    if not slug or not otro or not linea:
        return None

    def pedir():
        d = _http_json(f"{LOLA_WEB}/lol/{slug}/vs/{otro}/build/q-data.json?lane={linea}&vslane={linea}", timeout=15)
        q = _qwik(d) or {}
        b = _lola_extraer(q.get("pick") or {}, rec)
        if b:
            # "n_obj": partidas del objeto menos comprado de los tres primeros; "n": partidas del enfrentamiento
            b["n_obj"] = b.get("n")
            b["n"], b["wr"] = q.get("n") or b.get("n"), q.get("wr") if q.get("wr") is not None else b.get("wr")
        if b and (b.get("n") or 0) >= 200 and (b.get("n_obj") or 0) >= 30:    # con menos, la build no es fiable
            b["rival"] = int(rival)
            log(f"Lolalytics: build de {slug} contra {otro} leída ({_miles(b['n'])} partidas del enfrentamiento).")
            return b
        if b:
            log(f"Lolalytics: {slug} contra {otro} tiene pocas partidas ({b.get('n')}); no se ofrece esa build.")
        else:                                           # se guarda lo recibido para poder corregir el lector
            log(f"Lolalytics: no pude leer la página de {slug} contra {otro}; guardo lo recibido en datos\\cache.")
            try:
                (CACHE / f"lolavs_crudo_{slug}_{otro}.json").write_text(json.dumps(d)[:600000], encoding="utf-8")
            except Exception:
                pass
        return None
    return _lola_cache(f"lolavs2_{int(cid)}_{rol}_{int(rival)}.json", pedir)


def adaptar_build(rec, build, tipo, apoyo=None):
    """Adapta la build al daño del equipo enemigo ("físico" / "mágico") usando lo que compran de verdad los
    jugadores de ESE campeon (datos de Lolalytics), no una tabla fija:
    - botas defensivas solo si al menos el 10% las compra con ese campeon;
    - el objeto de armadura / resistencia magica mas comprado por ese campeon pasa a ser el 4.º objeto.
    apoyo: otra build del mismo campeon (la de OTP) para tomar de ahi las listas si esta no las trae.
    Devuelve (orden nuevo, lista de cambios)."""
    orden = list((build or {}).get("orden") or [])
    if tipo not in ("físico", "mágico") or not orden:
        return orden, []
    cat = "Armor" if tipo == "físico" else "SpellBlock"
    cambios = []

    def lista(k):
        return (build or {}).get(k) or (apoyo or {}).get(k) or []

    def cats(i):
        return (rec.items.get(str(i)) or {}).get("cat") or []
    # las botas con esa defensa que mas compra tu campeon (la defensa la dicen las categorias del cliente)
    bota_def, pct_bota = max([(i, p) for i, p in lista("botas") if _es_bota(rec, i) and cat in cats(i)] or [(None, 0)],
                             key=lambda x: x[1])
    if bota_def and pct_bota >= 10:
        for k, i in enumerate(orden):
            if _es_bota(rec, i) and i != bota_def:
                orden[k] = bota_def
                cambios.append(f"{rec.item(bota_def)} en vez de {rec.item(i)} (las lleva el {round(pct_bota)}% con tu campeón)")
                break
    pool = dict((build or {}).get("pool") or {})
    for k, v in ((apoyo or {}).get("pool") or {}).items():
        pool.setdefault(k, v)
    cand = {}
    for k, v in pool.items():
        if v >= 15:
            cand[int(k)] = v
    for i, p in lista("populares"):
        if p >= 3:
            cand.setdefault(i, p)
    defensivos = [i for i in list(orden) + sorted(cand, key=lambda x: -cand[x])
                  if cat in cats(i) and not _es_bota(rec, i) and not _no_es_de_build(rec, i) and not _no_se_compra(rec, i)]
    if defensivos:
        elegido = next((i for i in defensivos if i in orden), None) or defensivos[0]
        pos = min(3, len(orden))
        if elegido in orden:
            if orden.index(elegido) > pos:
                orden.remove(elegido)
                orden.insert(pos, elegido)
                cambios.append(f"{rec.item(elegido)} antes: como {pos + 1}.º objeto")
        else:
            orden.insert(pos, elegido)
            orden = orden[:6]
            cambios.append(f"{rec.item(elegido)} como {pos + 1}.º objeto")
    return orden, cambios


# =============================================================== BUILDS DE LA WEB (u.gg)
# Las builds con mas partidas por campeon y rol, de los datos publicos de u.gg. No es una API oficial: puede
# cambiar o dejar de responder. Si falla, el coach sigue con tus builds fijadas y no se rompe nada.
UGG_VERSIONES = os.environ.get("COACH_UGG_VERSIONES",
                               "https://static.bigbrain.gg/assets/lol/riot_patch_update/prod/ugg/ugg-api-versions.json")
UGG_DATOS = os.environ.get("COACH_UGG_DATOS", "https://stats2.u.gg/lol/1.5/overview")
UGG_MATCHUPS = os.environ.get("COACH_UGG_MATCHUPS", UGG_DATOS.rsplit("/", 1)[0] + "/matchups")
UGG_ROL = {"jungla": "1", "support": "2", "bot": "3", "top": "4", "mid": "5"}
BUILD_DIAS = 3            # cada cuanto se vuelve a pedir la build de un campeon


def _http_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "CoachLoL (uso personal)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _ugg_extraer(data, rol):
    """Saca la build del JSON de u.gg: region -> rango -> rol -> [datos, fecha]. De los rangos disponibles se usa
    el que tiene mas partidas."""
    rk = UGG_ROL.get(rol)
    if not rk or not isinstance(data, dict):
        return None
    region = data.get("12") or next(iter(data.values()), None)       # 12 = todas las regiones
    mejor = None
    for rango_k, rango in (region or {}).items():
        try:
            arr = rango[rk][0]
            partidas = int(arr[6][1])
        except Exception:
            continue
        if partidas and (mejor is None or partidas > mejor[0]):
            mejor = (partidas, arr, rango_k)
    if not mejor:
        return None
    partidas, arr = mejor[0], mejor[1]

    def ids(x):
        return [int(i) for i in (x or []) if str(i).isdigit() and int(i) > 0]
    try:
        inicio, orden = ids(arr[2][2]), ids(arr[3][2])
        for opciones in arr[5] or []:
            ops = sorted([o for o in opciones if isinstance(o, list) and len(o) >= 3], key=lambda o: -o[2])
            sig = next((int(o[0]) for o in ops if int(o[0]) not in orden), None)
            if sig and len(orden) < 6:
                orden.append(sig)
        wr = round(100 * int(arr[6][0]) / partidas)
    except Exception:
        return None
    if len(orden) < 2:
        return None
    out = {"inicio": inicio, "orden": orden, "partidas": partidas, "wr": wr, "rango_k": mejor[2]}
    try:                                                 # hechizos y orden de habilidades mas jugados
        out["hechizos"] = ids(arr[1][2])[:2]
        prio = arr[4][3] if len(arr[4]) > 3 else ""
        if isinstance(prio, str) and set(prio) <= set("QWE") and len(prio) == 3:
            out["habilidades"] = prio
        sec = [x for x in (arr[4][2] or []) if x in ("Q", "W", "E", "R")]
        if len(sec) >= 3:
            out["primeras"] = sec[:3]
    except Exception:
        pass
    return out


def texto_habilidades(b, rec=None):
    """Una linea con el orden de habilidades y los hechizos de una build de u.gg ("" si no hay datos)."""
    if not b:
        return ""
    partes = []
    if b.get("habilidades"):
        t = "Habilidades: sube " + " > ".join(b["habilidades"]) + " (y la R siempre que puedas)"
        if b.get("primeras"):
            t += ". Niveles 1 a 3: " + ", ".join(b["primeras"])
        partes.append(t)
    hs = [(rec.hechizos.get(str(h)) if rec is not None else None) for h in b.get("hechizos") or []]
    if len(hs) == 2 and all(hs):
        partes.append("Hechizos: " + " y ".join(hs))
    return ". ".join(partes) + ("." if partes else "")


def matchups_web(cid, rol, rango_k=None, wr_propio=None):
    """% de victorias de un campeon contra cada rival de su mismo rol (u.gg). Devuelve {rival_id: (wr, partidas)}.
    El archivo trae [rival, victorias, partidas, ...]: se comprueba de quien son esas victorias comparando el
    total con el % de victorias del campeon; si no se puede saber, se asume que son del campeon."""
    if not cid or rol not in UGG_ROL:
        return {}
    f = CACHE / f"matchups_{int(cid)}_{rol}.json"
    try:
        viejo = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - viejo.get("ts", 0) < BUILD_DIAS * 86400:
            return {int(k): tuple(v) for k, v in viejo["m"].items()}
    except Exception:
        pass
    try:
        vers = _http_json(UGG_VERSIONES)
        parches = sorted([k for k in vers if re.fullmatch(r"\d+_\d+", k)],
                         key=lambda k: tuple(int(x) for x in k.split("_")), reverse=True)
        for parche in parches[:3]:
            ver = (vers.get(parche) or {}).get("matchups") or "1.5.0"
            try:
                data = _http_json(f"{UGG_MATCHUPS}/{parche}/ranked_solo_5x5/{int(cid)}/{ver}.json", timeout=20)
            except Exception:
                continue
            region = data.get("12") or next(iter(data.values()), None) or {}
            filas = None
            for rk in ([rango_k] if rango_k else []) + list(region.keys()):
                try:
                    cand = [x for x in region[rk][UGG_ROL[rol]][0] if isinstance(x, list) and len(x) >= 3 and x[2]]
                except Exception:
                    continue
                if cand and (filas is None or sum(x[2] for x in cand) > sum(x[2] for x in filas)):
                    filas = cand
                    if rk == rango_k:
                        break
            if not filas or sum(x[2] for x in filas) < 200:
                continue
            tot = sum(x[1] for x in filas) / sum(x[2] for x in filas)
            invertir = False
            if wr_propio is not None and abs(wr_propio - 50) >= 1.5:
                invertir = abs(100 * tot - wr_propio) > abs(100 * (1 - tot) - wr_propio)
            m = {}
            for x in filas:
                if x[2] >= 30:
                    w = x[1] / x[2]
                    m[int(x[0])] = (round(100 * (1 - w if invertir else w), 1), int(x[2]))
            try:
                f.write_text(json.dumps({"ts": time.time(), "m": m}), encoding="utf-8")
            except Exception:
                pass
            return m
    except Exception as e:
        log(f"No pude leer los enfrentamientos de u.gg ({type(e).__name__}: {e}).")
    return {}


def mejor_pick(pool, enemigos, tablas, nombre):
    """De tus campeones del rol, cual gana mas contra los rivales ya elegidos que juegan ese mismo rol.
    tablas: {mi_campeon: {rival: (wr, partidas)}}. Devuelve el texto o ""."""
    filas = []
    for c in pool:
        vistos = [(e, tablas.get(c, {}).get(e)) for e in enemigos if tablas.get(c, {}).get(e)]
        if vistos:
            e, (wr, n) = max(vistos, key=lambda x: x[1][1])        # el rival con mas partidas en ese rol
            filas.append((c, e, wr))
    if len(filas) < 2:
        return ""
    rival = Counter(f[1] for f in filas).most_common(1)[0][0]
    filas = sorted([f for f in filas if f[1] == rival], key=lambda f: -f[2])
    if len(filas) < 2:
        return ""
    lista = ", ".join(f"{nombre(c)} {_dec(wr)}%" for c, _, wr in filas)
    return f"De tu pool contra {nombre(rival)} (Lolalytics): {lista}."


FASE_SEL = {"PLANNING": "Declaración de intenciones", "BAN_PICK": "Bloqueos y elecciones",
            "FINALIZATION": "Últimos segundos: cambia runas y hechizos", "GAME_STARTING": "La partida empieza"}


def draft_equipos(ses, ahora_ms=None):
    """Lo que el cliente ya te enseña en la seleccion, ordenado para el panel: fase, cuenta atras, de quien es el
    turno, los dos equipos y los bloqueos. Solo datos visibles en el cliente (sin nombres ocultos)."""
    ahora_ms = ahora_ms if ahora_ms is not None else time.time() * 1000
    celda = ses.get("localPlayerCellId")
    tm = ses.get("timer") or {}
    fase = (tm.get("phase") or "").upper()
    accion, mi_turno, bans_n, bans_s, hover = "", False, [], [], {}
    aliados_celdas = {m.get("cellId") for m in ses.get("myTeam") or []}
    for grupo in ses.get("actions") or []:
        for a in grupo or []:
            tipo = a.get("type")
            if tipo == "ban" and a.get("completed") and (a.get("championId") or 0) > 0:
                (bans_n if a.get("actorCellId") in aliados_celdas else bans_s).append(a["championId"])
            if a.get("isInProgress"):
                if not accion:
                    accion = tipo if tipo in ("ban", "pick") else ""
                if a.get("actorCellId") == celda:
                    mi_turno = True
                    accion = tipo if tipo in ("ban", "pick") else accion
                if tipo == "pick" and a.get("championId"):
                    hover[a.get("actorCellId")] = a["championId"]
    b = ses.get("bans") or {}
    if not bans_n and not bans_s:
        bans_n = [c for c in b.get("myTeamBans") or [] if c and c > 0]
        bans_s = [c for c in b.get("theirTeamBans") or [] if c and c > 0]

    def fila(m, mio):
        cid = m.get("championId") or 0
        intento = 0 if cid else (m.get("championPickIntent") or 0)
        h = hover.get(m.get("cellId"))
        if h and not cid:
            intento = h
        return {"celda": m.get("cellId"), "cid": cid or None, "intento": intento or None,
                "pos": POSICION_LCU.get((m.get("assignedPosition") or "").lower(), ""),
                "yo": bool(mio and m.get("cellId") == celda)}
    aliados = [fila(m, True) for m in ses.get("myTeam") or []]
    rivales = [fila(m, False) for m in ses.get("theirTeam") or []]
    restante = tm.get("adjustedTimeLeftInPhase")
    t_fin = int(ahora_ms + restante) if isinstance(restante, (int, float)) and restante > 0 else None
    if fase == "BAN_PICK":
        fase_txt = ("Tu turno: bloquea" if accion == "ban" else "Tu turno: elige") if mi_turno else (
            "Bloqueos" if accion == "ban" else "Elecciones" if accion == "pick" else FASE_SEL[fase])
    else:
        fase_txt = FASE_SEL.get(fase, "Selección de campeón")
    return {"fase": fase, "fase_txt": fase_txt, "accion": accion, "mi_turno": mi_turno, "t_fin": t_fin,
            "aliados": aliados, "rivales": rivales, "bans_nuestros": bans_n, "bans_suyos": bans_s}


def draft_sugerencias(pool_rol, tabla_de, rival, ocupados, mi_cid=None, maximo=5):
    """Picks para tu linea y bloqueos sugeridos.
    pool_rol: tus campeones de esa linea [{cid, nombre, n, v, wr}] (del mas jugado al menos).
    tabla_de(cid) -> {rival: (wr, partidas)} de Lolalytics (o None/{} si aun no esta).
    rival: el rival probable de tu linea (o None). ocupados: campeones ya elegidos o bloqueados.
    Devuelve {"picks": [...], "bans": [...]}."""
    picks = []
    for x in pool_rol:
        if x["cid"] in ocupados and x["cid"] != mi_cid:
            continue
        tu = (x["v"] + 2.5) / (x["n"] + 5) * 100            # tu % con 5 partidas "neutras" para no fiarse de 1-0
        vs = None
        t = tabla_de(x["cid"]) if rival else None
        if t and rival in t and t[rival][1] >= 100:
            vs = round(t[rival][0], 1)
        puntos = tu + (2 * (vs - 50) if vs is not None else 0) + min(x["n"], 10) * 0.6
        motivo = []
        if x["n"]:
            motivo.append(f"{x['v']}V {x['n'] - x['v']}D tuyas")
        if vs is not None:
            motivo.append(f"{_dec(vs)} % contra el rival")
        picks.append({"cid": x["cid"], "nombre": x["nombre"], "n": x["n"], "wr": x["wr"], "vs": vs,
                      "puntos": round(puntos, 1), "motivo": " · ".join(motivo)})
    picks.sort(key=lambda f: -f["puntos"])
    if picks:
        picks[0]["mejor"] = True
    bans, vistos = [], set(ocupados)
    base = mi_cid or (pool_rol[0]["cid"] if pool_rol else None)
    t = tabla_de(base) if base else None
    if t:
        n_tot = sum(v[1] for v in t.values())
        minimo = max(150, 0.008 * n_tot)
        for rid, (wr, n) in sorted(t.items(), key=lambda kv: kv[1][0]):
            if n < minimo or rid in vistos or wr >= 49:
                continue
            bans.append({"cid": rid, "wr": round(wr, 1), "base": base, "motivo": "dificil"})
            vistos.add(rid)
            if len(bans) >= 3:
                break
    return {"picks": picks[:maximo], "bans": bans}



POS_ORDEN = ["top", "jungla", "mid", "bot", "support"]
POS_CORTO = {"top": "Top", "jungla": "Jungla", "mid": "Mid", "bot": "ADC", "support": "Support"}


def posiciones_rivales(aliados, rivales, gen_de, minimo=200):
    """En clasificatoria no se ve la linea de los rivales: se deduce con Lolalytics. Pesa sobre todo en que linea
    se juega mas ese campeon (sus partidas en cada linea) y, de apoyo, cuantas partidas tiene cada aliado contra el
    en su linea. aliados/rivales: [{"cid", "pos"}]. Devuelve {cid_rival: pos}."""
    mu = {}
    for a in aliados:
        if not a.get("cid") or a.get("pos") not in POS_ORDEN:
            continue
        tabla = (gen_de(a["cid"], a["pos"]) or {}).get("enemigos") or {}
        tot = sum(v[1] for v in tabla.values()) or 1
        for r in rivales:
            x = tabla.get(str(r.get("cid"))) or tabla.get(r.get("cid"))
            if r.get("cid") and x and x[1] >= minimo:
                mu[(r["cid"], a["pos"])] = x[1] / tot
    puntos = []
    for r in rivales:
        if not r.get("cid"):
            continue
        datos = {pos: gen_de(r["cid"], pos) for pos in POS_ORDEN}
        ns = {pos: (g or {}).get("total") or (g or {}).get("n") or 0 for pos, g in datos.items()}   # partidas en esa linea
        tot = sum(ns.values())
        for pos in POS_ORDEN:
            m = mu.get((r["cid"], pos), 0)
            if tot >= 500:
                puntos.append((ns[pos] / tot + 0.25 * m, r["cid"], pos))
            elif m:
                puntos.append((m, r["cid"], pos))
    out, usadas = {}, set()
    for r in rivales:                        # si el cliente ya dice su linea (partidas normales), manda eso
        if r.get("cid") and r.get("pos") in POS_ORDEN and r["pos"] not in usadas:
            out[r["cid"]] = r["pos"]
            usadas.add(r["pos"])
    for sc, cid, pos in sorted(puntos, reverse=True):
        if sc > 0.05 and cid not in out and pos not in usadas:
            out[cid] = pos
            usadas.add(pos)
    return out


def prob_draft(aliados, rivales, gen_de, dano_de=None, propio=None):
    """Probabilidad estimada de ganar con los campeones elegidos (Lolalytics Esmeralda+):
    - linea con los dos campeones conocidos: el % de tu campeon contra el suyo en esa linea;
    - campeon sin pareja: su % de victorias general en su linea (a favor o en contra);
    - composicion: un equipo que hace casi todo un tipo de daño se contrarresta facil;
    - tu experiencia con tu campeon (propio = {"nombre", "n", "v"}).
    Devuelve {"p", "factores": [{"txt", "d"}], "faltan", "pos_rivales"} o None si no hay nada que medir."""
    pos_r = posiciones_rivales(aliados, rivales, gen_de)
    al = {a["pos"]: a for a in aliados if a.get("cid") and a.get("pos") in POS_ORDEN}
    ri = {pos: next((r for r in rivales if r.get("cid") == cid), {"cid": cid}) for cid, pos in pos_r.items()}
    factores, faltan = [], 0
    for pos in POS_ORDEN:
        a, r = al.get(pos), ri.get(pos)
        if a and r:
            g = gen_de(a["cid"], pos) or {}
            x = (g.get("enemigos") or {}).get(str(r["cid"])) or (g.get("enemigos") or {}).get(r["cid"])
            if x and x[1] >= 100:
                factores.append({"txt": f"{POS_CORTO[pos]}: {a.get('nombre', '')} contra {r.get('nombre', '')}".strip(),
                                 "d": (x[0] - 50) * 0.55, "pos": pos, "a": a["cid"], "r": r["cid"], "tipo": "linea"})
                continue
        for lado, c, signo in (("a", a, 1), ("r", r, -1)):
            if not c:
                continue
            g = gen_de(c["cid"], pos)
            if g is None:
                faltan += 1
                continue
            wr = (g or {}).get("wr_total")
            if wr is not None:
                factores.append({"txt": f"{POS_CORTO[pos]}: {c.get('nombre', '')}".strip(), "d": signo * (wr - 50) * 0.55,
                                 "pos": pos, lado: c["cid"], "tipo": "campeon"})
    for lado, eq, signo in (("tu equipo", [a["cid"] for a in aliados if a.get("cid")], 1),
                            ("su equipo", [r["cid"] for r in rivales if r.get("cid")], -1)):
        if dano_de and len(eq) >= 4:
            tipos = [dano_de(c) for c in eq]
            fis = sum(1 for t in tipos if t == "físico") + 0.5 * sum(1 for t in tipos if t == "mixto")
            mag = sum(1 for t in tipos if t == "mágico") + 0.5 * sum(1 for t in tipos if t == "mixto")
            if max(fis, mag) >= len(eq) - 0.5:
                cual = "físico" if fis > mag else "mágico"
                factores.append({"txt": f"Casi todo el daño de {lado} es {cual}: se contrarresta con un solo tipo de defensa",
                                 "d": -2.0 * signo, "tipo": "comp"})
    if propio and propio.get("nombre"):
        n, v = propio.get("n") or 0, propio.get("v") or 0
        if n == 0:
            factores.append({"txt": f"Primera partida con {propio['nombre']} en esta línea", "d": -1.5, "tipo": "tuyo"})
        else:
            tu = (v + 2.5) / (n + 5) * 100
            factores.append({"txt": f"Tu experiencia con {propio['nombre']} ({v}V {n - v}D)", "d": (tu - 50) * 0.25,
                             "tipo": "tuyo"})
    if not factores:
        return None
    p = 50 + sum(f["d"] for f in factores)
    for f in factores:
        f["d"] = round(f["d"], 1)
    return {"p": round(max(25.0, min(75.0, p)), 1), "factores": sorted(factores, key=lambda f: -abs(f["d"])),
            "faltan": faltan, "pos_rivales": pos_r}


def build_web(cid, rol):
    """Build mas jugada de un campeon en un rol (guardada en disco unos dias). None si no se puede leer."""
    if not cid or rol not in UGG_ROL:
        return None
    f = CACHE / f"build2_{int(cid)}_{rol}.json"
    viejo = None
    try:
        viejo = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - viejo.get("ts", 0) < BUILD_DIAS * 86400:
            return viejo
    except Exception:
        pass
    try:
        vers = _http_json(UGG_VERSIONES)
        parches = sorted([k for k in vers if re.fullmatch(r"\d+_\d+", k)],
                         key=lambda k: tuple(int(x) for x in k.split("_")), reverse=True)
        for parche in parches[:3]:                      # un parche recien salido puede no tener datos aun
            ver = (vers.get(parche) or {}).get("overview") or "1.5.0"
            try:
                b = _ugg_extraer(_http_json(f"{UGG_DATOS}/{parche}/ranked_solo_5x5/{int(cid)}/{ver}.json"), rol)
            except Exception:
                b = None
            if b and b["partidas"] >= 50:
                b.update(ts=time.time(), parche=parche.replace("_", "."), fuente="u.gg")
                try:
                    f.write_text(json.dumps(b), encoding="utf-8")
                except Exception:
                    pass
                return b
    except Exception as e:
        log(f"No pude leer la build de u.gg ({type(e).__name__}: {e}).")
    return viejo                                         # mejor una build vieja que ninguna


def siguiente_objeto(rec, orden, tengo, oro):
    """El siguiente objeto de tu build que todavia no tienes y cuanto oro te falta (descontando las piezas que ya
    llevas). Solo mira TU inventario y TU oro."""
    tengo = [int(x) for x in tengo if x]

    def info(i):
        return rec.items.get(str(i)) or {}

    def botas(i):
        return i != 1001 and "Boots" in (info(i).get("cat") or [])
    con_botas = any(botas(i) for i in tengo)
    for iid in orden:
        if iid in tengo or (botas(iid) and con_botas) or _no_se_compra(rec, iid):
            continue                 # la mejora del objeto de support llega sola con la mision: no se compra
        precio = info(iid).get("precio")
        if not precio:
            return {"id": iid, "nombre": rec.item(iid), "falta": None}
        resto, credito = list(tengo), 0

        def piezas(i, prof=0):
            nonlocal credito
            for c in info(i).get("de") or []:
                if c in resto:
                    resto.remove(c)
                    credito += info(c).get("precio") or 0
                elif prof < 3:
                    piezas(c, prof + 1)
        piezas(iid)
        return {"id": iid, "nombre": rec.item(iid), "falta": max(0, int(precio - credito - oro))}
    return None


def habilidad_a_subir(abilities, nivel, orden):
    """Que habilidad subir ahora con tus puntos libres: la R en cuanto se puede (6, 11, 16); si no, la primera del
    orden de la build (p. ej. "E > Q > W") que aun no esta al tope de tu nivel. None si no te quedan puntos."""
    try:
        lv = {k: int((abilities.get(k) or {}).get("abilityLevel") or 0) for k in ("Q", "W", "E", "R")}
    except Exception:
        return None
    nivel = int(nivel or 0)
    if not nivel or sum(lv.values()) >= nivel:
        return None
    if lv["R"] < sum(1 for x in (6, 11, 16) if nivel >= x):
        return "R"
    pri = [x for x in (orden or []) if x in ("Q", "W", "E")] + [x for x in ("Q", "W", "E") if x not in (orden or [])]
    if nivel <= 3:                       # primeros niveles: una de cada, empezando por la que mas se sube
        for k in pri:
            if lv[k] == 0:
                return k
    tope = min(5, (nivel + 1) // 2)
    for k in pri:
        if lv[k] < tope:
            return k
    return None


def tira_build(rec, orden, tengo):
    """Tu build entera con el estado de cada objeto: "ok" (ya lo tienes), "sig" (el siguiente) o "fut"."""
    tengo = [int(x) for x in tengo if x]

    def botas(i):
        return i != 1001 and "Boots" in ((rec.items.get(str(i)) or {}).get("cat") or [])
    con_botas = any(botas(i) for i in tengo)
    out, hay_sig = [], False
    def viene_de(i, prof=0):                 # objetos de los que sale (y los de esos), segun el cliente
        out = set()
        for c in (rec.items.get(str(i)) or {}).get("de") or []:
            out.add(c)
            if prof < 4:
                out |= viene_de(c, prof + 1)
        return out
    for iid in orden:
        if iid in tengo or (botas(iid) and con_botas) or (_no_se_compra(rec, iid) and viene_de(iid) & set(tengo)):
            est = "ok"
        elif _no_se_compra(rec, iid):
            est = "fut"
        elif not hay_sig:
            est, hay_sig = "sig", True
        else:
            est = "fut"
        out.append({"id": iid, "estado": est})
    return out


# ---- Daño del equipo enemigo y que defensa comprar (fijo: se calcula antes de empezar, con sus campeones)
def dano_equipo(tipos, mis_tags):
    """tipos: lista de "físico" / "mágico" / "mixto" de sus campeones. Devuelve el texto y los objetos sugeridos
    (solo si casi todo su daño es de un tipo)."""
    tipos = [t for t in tipos if t]
    if len(tipos) < 3:
        return None
    fis = sum(1 if t == "físico" else 0.5 if t == "mixto" else 0 for t in tipos)
    mag = len(tipos) - fis
    n_f, n_m, n_x = tipos.count("físico"), tipos.count("mágico"), tipos.count("mixto")
    partes = [f"{n} de daño {txt}" for n, txt in ((n_f, "físico"), (n_m, "mágico"), (n_x, "mixto")) if n]
    base = "Su equipo: " + ", ".join(partes) + "."
    mayor = "físico" if fis >= mag else "mágico"
    if max(fis, mag) / len(tipos) < 0.7:
        return {"texto": base + " Daño repartido: sigue tu build.", "items": [], "tipo": None}
    que = "armadura" if mayor == "físico" else "resistencia mágica"
    return {"texto": base + f" Casi todo es daño {mayor}: después de tu primer objeto, compra {que}.",
            "items": [], "tipo": mayor}


# =============================================================== CLIENTE (LCU)
_INSTALACION = {"ruta": None}     # carpeta de LoL vista en la linea de comandos del cliente
_POWERSHELL = {"t": 0.0}          # PowerShell es pesado: como mucho una vez por minuto


def _rutas_instalacion():
    rutas = []
    if CONFIG["ruta_lol"]:
        rutas.append(Path(CONFIG["ruta_lol"]))
    if _INSTALACION["ruta"]:
        rutas.append(Path(_INSTALACION["ruta"]))
    progdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    yaml = (Path(progdata) / "Riot Games" / "Metadata" / "league_of_legends.live"
            / "league_of_legends.live.product_settings.yaml")
    try:
        txt = yaml.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'product_install_full_path:\s*"?([^"\r\n]+)"?', txt)
        if m:
            rutas.append(Path(m.group(1).strip()))
    except Exception:
        pass
    for letra in "CDEFG":
        rutas.append(Path(f"{letra}:/Riot Games/League of Legends"))
    return rutas


def _credenciales_lockfile():
    for r in _rutas_instalacion():
        try:
            partes = (r / "lockfile").read_text(encoding="utf-8").strip().split(":")
            if len(partes) >= 5:
                _INSTALACION["ruta"] = str(r)          # ahi tambien estan los ajustes del juego
                return partes[2], partes[3]
        except Exception:
            continue
    return None


def _credenciales_proceso():
    if os.name != "nt":
        return None
    lineas = []
    try:
        import psutil  # opcional
        for p in psutil.process_iter(["name", "cmdline"]):
            if (p.info.get("name") or "").lower() == "leagueclientux.exe":
                lineas.append(" ".join(p.info.get("cmdline") or []))
    except Exception:
        pass
    if not lineas and time.time() - _POWERSHELL["t"] >= 60:
        _POWERSHELL["t"] = time.time()
        try:
            cmd = ("Get-CimInstance Win32_Process -Filter \"name='LeagueClientUx.exe'\" "
                   "| Select-Object -ExpandProperty CommandLine")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                                 capture_output=True, text=True, timeout=15,
                                 creationflags=0x08000000)
            lineas.append(out.stdout or "")
        except Exception:
            pass
    for linea in lineas:
        port = re.search(r"--app-port=(\d+)", linea)
        tok = re.search(r"--remoting-auth-token=([\w\-]+)", linea)
        if port and tok:
            carpeta = re.search(r'--install-directory=("?)([^"]+?)\1(?:\s--|"|$)', linea)
            if carpeta:
                _INSTALACION["ruta"] = carpeta.group(2).strip()   # la proxima vez basta el lockfile
            return port.group(1), tok.group(1)
    return None


_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE   # el cliente y el juego usan certificados propios de Riot


class LCU:
    """Cliente minimo de la API local del cliente de LoL."""

    def __init__(self):
        self.base = None
        self.auth = None

    def conectar(self):
        prueba = os.environ.get("COACH_LCU_URL")    # solo para pruebas
        if prueba:
            self.base = prueba.rstrip("/")
            self.auth = "Basic " + base64.b64encode(b"riot:prueba").decode()
            return True
        cred = _credenciales_lockfile() or _credenciales_proceso()
        if not cred:
            self.base = None
            return False
        port, token = cred
        self.base = f"https://127.0.0.1:{port}"
        self.auth = "Basic " + base64.b64encode(f"riot:{token}".encode()).decode()
        return True

    def get(self, ruta, crudo=False, timeout=10):
        if not self.base:
            raise ConnectionError("sin cliente")
        url = self.base + urllib.parse.quote(ruta, safe="/?=&:%-_.")
        req = urllib.request.Request(url, headers={"Authorization": self.auth,
                                                   "Accept": "application/json, image/*"})
        ctx = _CTX if self.base.startswith("https") else None
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            data = r.read()
        return data if crudo else json.loads(data.decode("utf-8"))

    def post(self, ruta, cuerpo=None, timeout=10):
        return self._enviar("POST", ruta, cuerpo, timeout)

    def put(self, ruta, cuerpo=None, timeout=10):
        return self._enviar("PUT", ruta, cuerpo, timeout)

    def delete(self, ruta, timeout=10):
        return self._enviar("DELETE", ruta, None, timeout)

    def patch(self, ruta, cuerpo=None, timeout=10):
        return self._enviar("PATCH", ruta, cuerpo, timeout)

    def _enviar(self, metodo, ruta, cuerpo, timeout):
        if not self.base:
            raise ConnectionError("sin cliente")
        url = self.base + urllib.parse.quote(ruta, safe="/?=&:%-_.")
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        req = urllib.request.Request(url, data=datos, method=metodo,
                                     headers={"Authorization": self.auth, "Content-Type": "application/json"})
        ctx = _CTX if self.base.startswith("https") else None
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            data = r.read()
        try:
            return json.loads(data.decode("utf-8")) if data else None
        except Exception:
            return None


# =============================================================== MODO DE PANTALLA DEL JUEGO
# En PANTALLA COMPLETA ninguna ventana se puede mostrar encima del juego: si una ventana "siempre encima"
# se pone delante, Windows saca al juego de la pantalla completa y lo manda al escritorio. Por eso, en
# pantalla completa la ventanita se oculta durante la partida. En "Sin bordes" se ve encima sin problemas.
EN_JUEGO = ("GameStart", "InProgress", "Reconnect")
NOMBRE_MODO = {0: "Pantalla completa", 1: "Ventana", 2: "Sin bordes"}


def _modo_en_cfg(texto):
    """WindowMode de la seccion [General] de game.cfg: 0 pantalla completa, 1 ventana, 2 sin bordes."""
    seccion = ""
    for linea in texto.splitlines():
        lin = linea.strip()
        if lin.startswith("[") and lin.endswith("]"):
            seccion = lin[1:-1].strip().lower()
        elif seccion == "general" and "=" in lin:
            clave, valor = lin.split("=", 1)
            if clave.strip().lower() == "windowmode":
                try:
                    return int(float(valor.strip()))
                except ValueError:
                    return None
    return None


def _modo_en_persisted(texto):
    """WindowMode dentro de Config/PersistedSettings.json (la copia de los ajustes que guarda el juego)."""
    try:
        data = json.loads(texto)
    except Exception:
        return None
    for f in data.get("files") or []:
        if (f.get("name") or "").lower() != "game.cfg":
            continue
        for sec in f.get("sections") or []:
            if (sec.get("name") or "").lower() != "general":
                continue
            for s in sec.get("settings") or []:
                if (s.get("name") or "").lower() == "windowmode":
                    try:
                        return int(float(s.get("value")))
                    except (TypeError, ValueError):
                        return None
    return None


def modo_pantalla(lcu):
    """Como tienes el juego: (modo, de donde se leyo). Modo 0 pantalla completa, 1 ventana, 2 sin bordes;
    None si no se puede saber. Primero los archivos del juego (cambian en cuanto tocas la opcion), luego
    lo que guarda el cliente (puede ir con retraso)."""
    rutas = []
    try:
        carpeta = lcu.get("/data-store/v1/install-dir", timeout=5)
        if isinstance(carpeta, str) and carpeta:
            rutas.append(Path(carpeta))
    except Exception:
        pass
    vistas = set()
    for r in rutas + _rutas_instalacion():
        if str(r).lower() in vistas:
            continue
        vistas.add(str(r).lower())
        for sub in (Path("Config"), Path("Game") / "Config"):
            try:
                modo = _modo_en_cfg((r / sub / "game.cfg").read_text(encoding="utf-8", errors="ignore"))
                if modo is not None:
                    return modo, "game.cfg"
            except Exception:
                pass
            try:
                modo = _modo_en_persisted((r / sub / "PersistedSettings.json").read_text(
                    encoding="utf-8", errors="ignore"))
                if modo is not None:
                    return modo, "PersistedSettings.json"
            except Exception:
                pass
    try:
        ajustes = lcu.get("/lol-game-settings/v1/game-settings", timeout=5) or {}
        valor = (ajustes.get("General") or {}).get("WindowMode")
        if valor is not None:
            return int(valor), "ajustes del cliente"
    except Exception:
        pass
    return None, ""


def d3d_pantalla_completa():
    """Windows: True si hay un juego en pantalla completa exclusiva (lo mismo que mira Windows para no
    mostrar notificaciones encima de un juego)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        estado = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(estado)) == 0:
            return estado.value == 3          # QUNS_RUNNING_D3D_FULL_SCREEN
    except Exception:
        pass
    return False


def partida_en_vivo():
    """API oficial de partida en vivo (puerto 2999). Solo existe mientras juegas."""
    base = os.environ.get("COACH_LIVE_URL", "https://127.0.0.1:2999").rstrip("/")
    ctx = _CTX if base.startswith("https") else None
    with urllib.request.urlopen(base + "/liveclientdata/allgamedata", context=ctx, timeout=2) as r:
        return json.loads(r.read().decode("utf-8"))


# =============================================================== RECURSOS
class Recursos:
    """Nombres de campeones/objetos e iconos, guardados en disco para usarlos sin cliente."""

    def __init__(self):
        self.campeones = self._leer("campeones.json", {})
        self.alias = self._leer("alias.json", {})
        self.items = self._leer("items.json", {})
        self.runas = self._leer("runas.json", {})
        self.runas_ico = self._leer("runas_ico.json", {})
        self.runa_estilo = self._leer("runa_estilo.json", {})    # runa -> arbol, segun el cliente
        self.hechizos = self._leer("hechizos.json", {})          # hechizo de invocador -> nombre, segun el cliente
        self.idioma = "es_MX"
        self._ver_dd = None

    @staticmethod
    def _leer(nombre, defecto):
        try:
            return json.loads((CACHE / nombre).read_text(encoding="utf-8"))
        except Exception:
            return defecto

    @staticmethod
    def _escribir(nombre, data):
        try:
            (CACHE / nombre).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def actualizar(self, lcu):
        try:
            data = lcu.get("/lol-game-data/assets/v1/champion-summary.json")
            camp = {str(c["id"]): c.get("name", "") for c in data if c.get("id", -1) > 0}
            alias = {str(c["id"]): c.get("alias", "") for c in data if c.get("id", -1) > 0 and c.get("alias")}
            if camp:
                self.campeones = camp
                self._escribir("campeones.json", camp)
            if alias:
                self.alias = alias
                self._escribir("alias.json", alias)
        except Exception as e:
            log(f"No pude leer campeones: {e}")
        try:
            runas, icos = {}, {}
            for c in lcu.get("/lol-game-data/assets/v1/perks.json"):
                if c.get("id"):
                    runas[str(c["id"])] = c.get("name", "")
                    icos[str(c["id"])] = c.get("iconPath", "")
            est = lcu.get("/lol-game-data/assets/v1/perkstyles.json")
            estilo = {}
            for c in (est.get("styles") if isinstance(est, dict) else est) or []:
                if c.get("id"):
                    runas[str(c["id"])] = c.get("name", "")
                    icos[str(c["id"])] = c.get("iconPath", "")
                    for sl in c.get("slots") or []:
                        if sl.get("type") in (None, "kMixedRegularSplashable", "kKeyStone") or "Stat" not in str(sl.get("type")):
                            for pk in sl.get("perks") or []:
                                estilo[str(pk)] = c["id"]
            if estilo:
                self.runa_estilo = estilo
                self._escribir("runa_estilo.json", estilo)
            if runas:
                self.runas, self.runas_ico = runas, icos
                self._escribir("runas.json", runas)
                self._escribir("runas_ico.json", icos)
        except Exception:
            pass
        try:
            hz = {str(x["id"]): x.get("name", "") for x in lcu.get("/lol-game-data/assets/v1/summoner-spells.json") or []
                  if x.get("id") and x.get("name")}
            if hz:
                self.hechizos = hz
                self._escribir("hechizos.json", hz)
        except Exception:
            pass
        try:
            loc = lcu.get("/riotclient/region-locale")
            if loc.get("locale"):
                self.idioma = loc["locale"]
        except Exception:
            pass
        try:
            data = lcu.get("/lol-game-data/assets/v1/items.json")
            its = {str(i["id"]): {"nombre": i.get("name", ""), "icono": i.get("iconPath", ""),
                                  "precio": i.get("priceTotal") or 0, "de": i.get("from") or [],
                                  "cat": i.get("categories") or [], "tienda": i.get("inStore", True)}
                   for i in data if i.get("id")}
            if its:
                self.items = its
                self._escribir("items.json", its)
        except Exception as e:
            log(f"No pude leer objetos: {e}")

    def campeon(self, cid):
        return self.campeones.get(str(cid)) or f"Campeón {cid}"

    def consejos(self, cid):
        """Consejos oficiales de Riot para jugar contra un campeon (Data Dragon), guardados en disco."""
        alias = self.alias.get(str(cid))
        if not alias:
            return None
        f = CACHE / f"consejos_{alias}_{self.idioma}.json"
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
        base = os.environ.get("COACH_DDRAGON_URL", "https://ddragon.leagueoflegends.com").rstrip("/")
        try:
            if not self._ver_dd:
                with urllib.request.urlopen(base + "/api/versions.json", timeout=6) as r:
                    self._ver_dd = json.loads(r.read().decode("utf-8"))[0]
            url = f"{base}/cdn/{self._ver_dd}/data/{self.idioma}/champion/{alias}.json"
            with urllib.request.urlopen(url, timeout=6) as r:
                c = json.loads(r.read().decode("utf-8"))["data"][alias]
            info = c.get("info") or {}
            out = {"contra": c.get("enemytips") or [], "con": c.get("allytips") or [],
                   "tags": c.get("tags") or [],
                   "dano": "mágico" if (info.get("magic") or 0) > (info.get("attack") or 0) else "físico"}
            f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            return out
        except Exception:
            return None

    def tipo_dano(self, cid, lcu=None):
        """Daño principal de un campeon: "físico", "mágico" o "mixto" (dato de Riot; se guarda en disco)."""
        if not cid:
            return None
        if not hasattr(self, "_dano"):
            self._dano = self._leer("dano.json", {})
        if str(cid) in self._dano:
            return self._dano[str(cid)]
        tipo = None
        try:
            if lcu is not None:
                c = lcu.get(f"/lol-game-data/assets/v1/champions/{int(cid)}.json", timeout=4)
                dt = ((c or {}).get("tacticalInfo") or {}).get("damageType") or ""
                tipo = {"kphysical": "físico", "kmagic": "mágico", "kmixed": "mixto"}.get(dt.lower())
        except Exception:
            tipo = None
        if not tipo:
            tipo = (self.consejos(cid) or {}).get("dano")
        if tipo:
            self._dano[str(cid)] = tipo
            try:
                (CACHE / "dano.json").write_text(json.dumps(self._dano, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
        return tipo

    def runa(self, rid):
        return self.runas.get(str(rid)) or f"Runa {rid}"

    def detalle_runas(self, r):
        if not r:
            return None
        ids = r.get("selectedPerkIds") or []
        d = lambda i: {"id": i, "nombre": self.runa(i)}
        return {"estilo": d(r.get("primaryStyleId")), "sub": d(r.get("subStyleId")),
                "principales": [d(i) for i in ids[:4]], "secundarias": [d(i) for i in ids[4:6]],
                "fragmentos": [d(i) for i in ids[6:9]]}

    def texto_runas(self, r):
        if not r:
            return ""
        ids = r.get("selectedPerkIds") or []
        prin = ", ".join(self.runa(i) for i in ids[:4])
        sec = ", ".join(self.runa(i) for i in ids[4:6])
        return f"{self.runa(r.get('primaryStyleId'))}: {prin}. {self.runa(r.get('subStyleId'))}: {sec}."

    def item(self, iid):
        return (self.items.get(str(iid)) or {}).get("nombre") or f"Objeto {iid}"

    def icono(self, tipo, ident, lcu):
        """Imagen de un campeon, objeto, runa, icono de perfil o splash. Primero la copia guardada, luego el
        cliente de LoL y, si esta cerrado, CommunityDragon (copia publica de los mismos archivos del juego)."""
        ident = re.sub(r"[^0-9]", "", str(ident))
        if not ident:
            return None
        f = CACHE / f"{tipo}_{ident}.png"
        if f.exists():
            return f.read_bytes()
        if tipo == "campeon":
            ruta = f"/lol-game-data/assets/v1/champion-icons/{ident}.png"
        elif tipo == "perfil":
            ruta = f"/lol-game-data/assets/v1/profile-icons/{ident}.jpg"
        elif tipo == "splash":
            ruta = self._ruta_splash(ident, lcu)
        elif tipo == "runa":
            ruta = self.runas_ico.get(ident)
        else:
            ruta = (self.items.get(ident) or {}).get("icono")
        if not ruta:
            return None
        data = None
        try:
            data = lcu.get(ruta, crudo=True)
        except Exception:
            data = None
        if not (data and len(data) > 100):
            data = _img_cdragon(ruta)
        if data and len(data) > 100:
            try:
                f.write_bytes(data)
            except Exception:
                pass
            return data
        return None

    def _ruta_splash(self, cid, lcu):
        """Ruta del arte del campeon (aspecto base). Se lee de la ficha del campeon: Riot cambio de carpeta estas
        imagenes y no todos los campeones estan en la nueva. Si la ficha no se puede leer, la ruta de siempre."""
        f = CACHE / f"splashruta_{cid}.json"
        try:
            ruta = json.loads(f.read_text(encoding="utf-8")).get("ruta")
            if ruta:
                return ruta
        except Exception:
            pass
        url, ficha = f"/lol-game-data/assets/v1/champions/{cid}.json", None
        try:
            ficha = lcu.get(url)
        except Exception:
            ficha = None
        if not isinstance(ficha, dict):
            crudo = _img_cdragon(url, "application/json")
            try:
                ficha = json.loads(crudo.decode("utf-8")) if crudo else None
            except Exception:
                ficha = None
        ruta = None
        for a in (ficha or {}).get("skins") or []:
            if isinstance(a, dict) and (a.get("isBase") or ruta is None):
                ruta = a.get("splashPath") or a.get("uncenteredSplashPath") or ruta
                if a.get("isBase") and ruta:
                    break
        if ruta:
            try:
                f.write_text(json.dumps({"ruta": ruta}), encoding="utf-8")
            except Exception:
                pass
        return ruta or f"/lol-game-data/assets/v1/champion-splashes/{cid}/{cid}000.jpg"


CDRAGON = os.environ.get("COACH_CDRAGON_URL",
                         "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default").rstrip("/")
_CDRAGON_FALLOS = {}


def _img_cdragon(ruta, acepta="image/*"):
    """El mismo archivo que da el cliente, pedido a CommunityDragon: la ruta es la del cliente en minusculas.
    Lo que falla no se vuelve a pedir en 10 minutos."""
    r = ruta.lower()
    r = r[len("/lol-game-data/assets"):] if r.startswith("/lol-game-data/assets") else r
    url = CDRAGON + "/" + r.lstrip("/")
    if time.time() - _CDRAGON_FALLOS.get(url, 0) < 600:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CoachLoL (uso personal)", "Accept": acepta})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        if data and len(data) > 100:
            return data
    except Exception:
        pass
    _CDRAGON_FALLOS[url] = time.time()
    return None


# =============================================================== UTILIDADES
def _dur_seg(v):
    v = v or 0
    return v / 1000.0 if v > 20000 else float(v)


def _mmss(ms):
    s = int(ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


def _miles(n):
    return f"{int(round(n)):,}".replace(",", ".")


def _signo(n, miles=False):
    txt = _miles(abs(n)) if miles else str(int(round(abs(n))))
    return ("+" if n > 0 else "-" if n < 0 else "") + txt


def _dec(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def _zona(pos, equipo):
    if not pos:
        return None
    s = (pos.get("x") or 0) + (pos.get("y") or 0)
    if abs(s - 14800) <= 1100:
        return "rio"
    propio = (s < 14800) if equipo == 100 else (s > 14800)
    return "propia" if propio else "enemiga"


ZONA_TXT = {"propia": "tu lado", "rio": "río / centro", "enemiga": "lado enemigo", None: "-"}


def _frame_en(frames, minuto):
    if not frames:
        return None
    obj = minuto * 60000
    i = min(range(len(frames)), key=lambda k: abs((frames[k].get("timestamp") or k * 60000) - obj))
    if abs((frames[i].get("timestamp") or i * 60000) - obj) > 90000:
        return None
    return frames[i]


def _pf(frame, pid):
    if not frame or pid is None:
        return None
    return (frame.get("participantFrames") or {}).get(str(pid))


def _cs_pf(x):
    return (x.get("minionsKilled") or 0) + (x.get("jungleMinionsKilled") or 0)


def prob_victoria(dif_oro, minuto):
    """Estimacion sencilla de la probabilidad de ganar con la ventaja de oro del equipo y el minuto (la misma
    ventaja pesa menos cuanto mas tarde). No es el modelo de ninguna app: es una curva aproximada."""
    k = 0.00045 * math.sqrt(15 / max(minuto, 8))
    return max(3, min(97, round(100 / (1 + math.exp(-k * dif_oro)))))


def puestos_partida(parts, roles, mins, yo_id, rec):
    """Puntuacion de los 10 jugadores (0 a 10) y premios. Propia del coach: KDA, participacion y muertes
    comparados con los 10; daño, oro, CS, vision y torres comparados con el rival del mismo rol."""
    filas = {}
    kills_eq = Counter()
    for pid, p in parts.items():
        kills_eq[p.get("teamId")] += (p.get("stats") or {}).get("kills", 0)
    for pid, p in parts.items():
        st = p.get("stats") or {}
        k, d, a = st.get("kills", 0), st.get("deaths", 0), st.get("assists", 0)
        filas[pid] = {"kda": (k + a) / max(d, 1), "kp": (k + a) / max(kills_eq[p.get("teamId")], 1), "d": d,
                      "dano": st.get("totalDamageDealtToChampions") or 0, "oro": st.get("goldEarned") or 0,
                      "cs": (st.get("totalMinionsKilled") or 0) + (st.get("neutralMinionsKilled") or 0),
                      "vision": st.get("visionScore") or 0, "torres": st.get("damageDealtToTurrets") or 0,
                      "k": k, "a": a}

    def z(campo, pid, signo=1):
        vals = [f[campo] for f in filas.values()]
        m = sum(vals) / len(vals)
        de = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5
        return 0 if not de else max(-2, min(2, signo * (filas[pid][campo] - m) / de))

    def duelo(campo, pid):
        rol = roles.get(pid)
        otro = next((q for q in parts if parts[q].get("teamId") != parts[pid].get("teamId") and roles.get(q) == rol), None)
        if otro is None:
            return z(campo, pid)
        a, b = filas[pid][campo], filas[otro][campo]
        return 0 if a + b == 0 else max(-1.5, min(1.5, 3 * (a - b) / (a + b)))
    PESOS = {"support": {"kda": .25, "kp": .25, "d": .15, "vision": .25, "dano": .10},
             "jungla": {"kda": .25, "kp": .25, "d": .15, "dano": .15, "oro": .15, "vision": .05},
             None: {"kda": .20, "kp": .15, "d": .15, "dano": .20, "oro": .15, "cs": .10, "torres": .05}}
    out = []
    for pid, p in parts.items():
        st = p.get("stats") or {}
        pesos = PESOS.get(roles.get(pid)) or PESOS[None]
        total = 0
        for campo, w in pesos.items():
            total += w * (z("kda", pid) if campo == "kda" else z("kp", pid) if campo == "kp"
                          else z("d", pid, -1) if campo == "d" else duelo(campo, pid))
        nota = max(0, min(10, round(5 + 2.4 * total + (0.5 if st.get("win") else -0.3), 1)))
        f = filas[pid]
        out.append({"pid": pid, "campeon_id": p.get("championId"), "campeon": rec.campeon(p.get("championId")),
                    "rol": roles.get(pid) or "", "aliado": p.get("teamId") == parts[yo_id].get("teamId"),
                    "yo": pid == yo_id, "gano": bool(st.get("win")), "kda": f"{f['k']}/{f['d']}/{f['a']}",
                    "dano": f["dano"], "oro": f["oro"], "cs": f["cs"], "vision": f["vision"], "nota": nota,
                    "premios": []})
    out.sort(key=lambda x: -x["nota"])
    for i, x in enumerate(out, 1):
        x["puesto"] = i
    gan = next((x for x in out if x["gano"]), None)
    per = next((x for x in out if not x["gano"]), None)
    if gan:
        gan["premios"].append("MVP")
    if per:
        per["premios"].append("Mejor del equipo que perdió")
    for campo, nombre in (("dano", "Más daño"), ("oro", "Más oro"), ("vision", "Más visión"), ("cs", "Más CS")):
        max(out, key=lambda x: x[campo])["premios"].append(nombre)
    return out


def resumen_stats(p):
    """Numeros de una partida para la lista y la pantalla de rendimiento: participacion, CS y vision por minuto,
    daño por minuto y % del daño de tu equipo, oro contra tu rival al 14, kills en solitario y como jugo tu equipo."""
    dh = p.get("datos_h") or {}
    mins = p.get("minutos") or dh.get("mins") or 0
    pu = p.get("puestos") or []
    yo = next((x for x in pu if x.get("yo")), None)
    dano_eq = sum(x.get("dano") or 0 for x in pu if x.get("aliado"))
    st = {"kp": round(dh["kp"] * 100) if dh.get("kp") is not None else None,
          "csmin": round(dh["csmin"], 2) if dh.get("csmin") is not None else None,
          "vmin": round(dh["vision_min"], 2) if dh.get("vision_min") is not None else None,
          "oro14": dh.get("oro14_diff"), "solo": dh.get("solo_kills"),
          "dmin": round(yo["dano"] / mins) if yo and yo.get("dano") is not None and mins else None,
          "dpct": round(100 * yo["dano"] / dano_eq) if yo and yo.get("dano") is not None and dano_eq else None}
    # como jugaron tus 4 aliados frente a los 5 rivales (nota media del coach). Como DPM: solo promedio, malo o
    # muy malo; los cortes reproducen sus etiquetas en 4 partidas tuyas (-1,3 y -2,45 malo; -3,62 muy malo; +3,7 promedio)
    al = [x["nota"] for x in pu if x.get("aliado") and not x.get("yo") and x.get("nota") is not None]
    en = [x["nota"] for x in pu if not x.get("aliado") and x.get("nota") is not None]
    if len(al) >= 3 and len(en) >= 3:
        r = sum(al) / len(al) - sum(en) / len(en)
        st["equipo"] = "muy_malo" if r <= -3.0 else "malo" if r <= -1.0 else "promedio"
    if yo:
        st["ace"] = "Mejor del equipo que perdió" in (yo.get("premios") or [])
    return st


def _frame_antes(frames, ts):
    previo = None
    for f in frames:
        if (f.get("timestamp") or 0) <= ts:
            previo = f
        else:
            break
    return previo


def _eventos(frames):
    for f in frames:
        for e in f.get("events") or []:
            yield (e.get("type") or "").upper(), e


def _nombre_edificio(e):
    carril = {"TOP_LANE": "top", "MID_LANE": "mid", "BOT_LANE": "bot"}.get(e.get("laneType"), "")
    b = e.get("buildingType")
    if b == "INHIBITOR_BUILDING":
        return f"el inhibidor de {carril}" if carril else "un inhibidor"
    if b == "TOWER_BUILDING":
        return f"la torre de {carril}" if carril else "una torre"
    return ""


def _nombre_monstruo(e):
    return {"DRAGON": "el dragón", "ELDER_DRAGON": "el dragón anciano", "BARON_NASHOR": "el Barón",
            "RIFTHERALD": "el Heraldo", "HORDE": "las larvas del vacío", "ATAKHAN": "Atakhan"}.get(
        (e.get("monsterType") or "").upper(), "")


_SIGLA_OBJ = {"DRAGON": "D", "ELDER_DRAGON": "A", "BARON_NASHOR": "B", "RIFTHERALD": "H", "HORDE": "L", "ATAKHAN": "K"}


MULTI_NOMBRE = {2: "Doble kill", 3: "Triple kill", 4: "Cuádruple kill", 5: "Pentakill"}


def clips_partida(frames, parts, yo_id, rol, camp):
    """Tus jugadas clave de la partida (como los clips de DPM, sin grabar video): multikills, kills en solitario,
    primera sangre, peleas ganadas, aces y objetivos grandes en los que estuviste. Cada una con el segundo para
    abrirla en la repeticion. Ordenadas por tiempo; como mucho 12 (las de mas peso)."""
    if yo_id not in parts:
        return []
    equipo = parts[yo_id].get("teamId")
    kills = []                                  # (ts, killer, victima, asistentes)
    objetivos = []
    for t, e in _eventos(frames):
        if t == "CHAMPION_KILL":
            kills.append((e.get("timestamp") or 0, e.get("killerId"), e.get("victimId"), e.get("assistingParticipantIds") or []))
        elif t == "ELITE_MONSTER_KILL":
            objetivos.append(e)
    kills.sort(key=lambda x: x[0])
    enemigo = lambda pid: pid in parts and parts[pid].get("teamId") != equipo
    clips, usados = [], set()

    def clip(ts, tipo, titulo, sub, peso, tono="az"):
        clips.append({"seg": max(0, int(ts / 1000)), "tipo": tipo, "titulo": titulo, "sub": sub, "peso": peso, "tono": tono})

    # multikills: tus kills seguidas con menos de 10 s entre una y otra (30 s para la penta tras la cuadruple)
    mias = [k for k in kills if k[1] == yo_id and enemigo(k[2])]
    i = 0
    while i < len(mias):
        j = i
        while j + 1 < len(mias) and mias[j + 1][0] - mias[j][0] <= (30000 if j - i + 1 == 4 else 10000):
            j += 1
        n = min(j - i + 1, 5)
        if n >= 2:
            clip(mias[i][0], "multi", MULTI_NOMBRE[n], _lista_y([camp(x[2]) for x in mias[i:j + 1]]),
                 {2: 40, 3: 70, 4: 90, 5: 100}[n], "or" if n >= 4 else "az")
            usados |= {x[0] for x in mias[i:j + 1]}
        i = j + 1
    if kills and kills[0][1] == yo_id and enemigo(kills[0][2]):
        clip(kills[0][0], "primera", "Primera sangre", f"A {camp(kills[0][2])}", 45)
        usados.add(kills[0][0])
    for ts, kid, vid, asis in mias:
        if not asis and ts not in usados:
            clip(ts, "solo", "Kill en solitario", f"A {camp(vid)}, sin ayuda", 35)
    # peleas: kills en ventanas de 15 s en las que participaste; ganada si caen 3 o mas de ellos y menos de los tuyos
    i = 0
    while i < len(kills):
        j = i
        while j + 1 < len(kills) and kills[j + 1][0] - kills[j][0] <= 15000:
            j += 1
        grupo = kills[i:j + 1]
        suyos = {k[2] for k in grupo if enemigo(k[2])}
        nuestros = {k[2] for k in grupo if k[2] in parts and not enemigo(k[2])}
        estuve = any(yo_id in (k[1], k[2], *k[3]) for k in grupo)
        solo_mias = any(k[0] in usados for k in grupo)          # ya contada como multikill o primera sangre
        if estuve and not solo_mias and len(suyos) >= 3 and len(suyos) > len(nuestros):
            ace = len(suyos) >= 5
            clip(grupo[0][0], "ace" if ace else "pelea", "Ace" if ace else f"Pelea ganada {len(suyos)} por {len(nuestros)}",
                 ("Cayeron los 5" if ace else f"Cayeron {len(suyos)} de ellos") + (f" y {len(nuestros)} de los tuyos" if nuestros else " y ninguno de los tuyos"),
                 80 if ace else 50 + 5 * len(suyos), "or" if ace else "vd")
        i = j + 1
    # objetivos grandes con tu participacion (y el remate, si no eres la jungla)
    for e in objetivos:
        mt = (e.get("monsterType") or "").upper()
        kid, asis = e.get("killerId"), e.get("assistingParticipantIds") or []
        if kid not in parts or parts[kid].get("teamId") != equipo or yo_id not in (kid, *asis):
            continue
        nombre = _nombre_monstruo(e)
        if mt in ("BARON_NASHOR", "ELDER_DRAGON"):
            clip(e.get("timestamp") or 0, "objetivo", "Barón para tu equipo" if mt == "BARON_NASHOR" else "Anciano para tu equipo",
                 "El remate fue tuyo" if kid == yo_id else "Estuviste en la jugada", 60, "vi")
        elif kid == yo_id and rol != "jungla" and nombre and mt != "HORDE":
            clip(e.get("timestamp") or 0, "objetivo", f"Remataste {nombre}", "Último golpe sin ser la jungla", 55, "vi")
    mejores = sorted(clips, key=lambda c: -c["peso"])[:12]
    return sorted(mejores, key=lambda c: c["seg"])


def minuto_a_minuto(juego, tl, puuid, rec):
    """La partida minuto a minuto (como dpm.lol o itero): tu oro, XP y CS contra tu rival de linea, la ventaja de oro
    de tu equipo con su probabilidad de ganar estimada, lo que paso y los momentos que decidieron la partida."""
    frames = (tl or {}).get("frames") or []
    if len(frames) < 4:
        return None
    mins = max(_dur_seg(juego.get("gameDuration")) / 60.0, 1.0)
    idents = {pi.get("participantId"): (pi.get("player") or {}) for pi in juego.get("participantIdentities") or []}
    parts = {p.get("participantId"): p for p in juego.get("participants") or []}
    yo_id = next((pid for pid, pl in idents.items() if pl.get("puuid") == puuid), None)
    if yo_id not in parts:
        return None
    equipo = parts[yo_id].get("teamId")
    roles = _roles(parts, frames, mins)
    rival_id = _encontrar_rival(yo_id, parts, frames, roles)
    nuestros = {pid for pid, q in parts.items() if q.get("teamId") == equipo}
    camp = lambda pid: rec.campeon(parts[pid].get("championId")) if pid in parts else ""

    serie = []
    for f in frames:
        m = round((f.get("timestamp") or 0) / 60000, 2)
        yo, rv = _pf(f, yo_id) or {}, (_pf(f, rival_id) or {}) if rival_id else {}
        oro = lambda pids: sum((_pf(f, pid) or {}).get("totalGold") or 0 for pid in pids)
        dif = oro(nuestros) - oro(set(parts) - nuestros)
        serie.append({"m": m, "oro": yo.get("totalGold"), "oro_r": rv.get("totalGold"), "xp": yo.get("xp"),
                      "xp_r": rv.get("xp"), "cs": _cs_pf(yo) if yo else None, "cs_r": _cs_pf(rv) if rv else None,
                      "niv": yo.get("level"), "niv_r": rv.get("level"), "eq": dif,
                      "pv": prob_victoria(dif, max(m, 1)) if m >= 1 else 50})

    eventos = []
    for t, e in _eventos(frames):
        ts = e.get("timestamp") or 0
        if t == "CHAMPION_KILL":
            kid, vid, asis = e.get("killerId"), e.get("victimId"), e.get("assistingParticipantIds") or []
            nuestro = (parts[kid].get("teamId") == equipo) if kid in parts else ((parts.get(vid) or {}).get("teamId") != equipo)
            tipo = ("muerte" if vid == yo_id else "kill" if kid == yo_id else "asist" if yo_id in asis
                    else "kill_eq" if nuestro else "muerte_eq")
            eventos.append({"ts": ts, "tipo": tipo, "nuestro": nuestro, "victima": camp(vid),
                            "asesino": camp(kid) or "una torre o súbditos"})
        elif t == "ELITE_MONSTER_KILL":
            kid = e.get("killerId")
            nuestro = (parts[kid].get("teamId") == equipo) if kid in parts else e.get("killerTeamId") == equipo
            mt = (e.get("monsterType") or "").upper()
            eventos.append({"ts": ts, "tipo": "objetivo", "nuestro": nuestro, "nombre": _nombre_monstruo(e),
                            "sigla": _SIGLA_OBJ.get(mt, "?")})
        elif t == "BUILDING_KILL" and _nombre_edificio(e):
            eventos.append({"ts": ts, "tipo": "torre", "nuestro": e.get("teamId") != equipo, "nombre": _nombre_edificio(e)})

    # momentos que decidieron la partida: los mayores cambios de la ventaja del equipo en 2 minutos
    cambios = []
    for i in range(2, len(serie)):
        d = serie[i]["eq"] - serie[i - 2]["eq"]
        if abs(d) >= 900:
            cambios.append((abs(d), i, d))
    elegidos = []
    for _, i, d in sorted(cambios, reverse=True):
        if all(abs(i - j) >= 3 for j, _ in elegidos):
            elegidos.append((i, d))
        if len(elegidos) == 3:
            break
    momentos = []
    for i, d in sorted(elegidos):
        a, b = serie[i - 2], serie[i]
        ev = [x for x in eventos if a["m"] * 60000 < x["ts"] <= b["m"] * 60000]
        bien = d > 0
        caen_nuestros = [x for x in ev if x["tipo"] in ("muerte", "muerte_eq")]
        caen_suyos = [x for x in ev if x["tipo"] in ("kill", "kill_eq", "asist")]
        obj_n = [x["nombre"] for x in ev if x["tipo"] in ("objetivo", "torre") and x["nuestro"]]
        obj_s = [x["nombre"] for x in ev if x["tipo"] in ("objetivo", "torre") and not x["nuestro"]]
        mia = next((x for x in ev if x["tipo"] == "muerte"), None)
        partes = []
        caen = lambda k: "cayó 1" if k == 1 else f"cayeron {k}"
        if caen_suyos:
            partes.append(f"{caen(len(caen_suyos))} de los suyos")
        if caen_nuestros:
            partes.append(f"{caen(len(caen_nuestros))} de los tuyos" + (" (tú incluido)" if mia else ""))
        if obj_n:
            partes.append("tu equipo se llevó " + _lista_y(obj_n[:3]))
        if obj_s:
            partes.append("ellos se llevaron " + _lista_y(obj_s[:3]))
        que = (_lista_y(partes) + ".") if partes else "Nadie murió: fue farmeo y presión de oleadas."
        if not bien and obj_s and len(caen_nuestros) >= 2:
            leccion = ("Perder la pelea les dio el objetivo. Si caen 2 de los tuyos, cede ese objetivo y defiende: "
                       "no regales más.")
        elif not bien and mia:
            leccion = (f"Tu muerte (te mató {mia['asesino']}) abrió el hueco. Antes de entrar, mira cuántos "
                       "enemigos no ves en el mapa.")
        elif not bien and caen_nuestros:
            leccion = "Pelea perdida. Si vais con menos gente o menos vida, no se entra: se espera a la siguiente."
        elif not bien:
            leccion = "Perdisteis oro sin pelear: oleadas y campamentos que se llevó el rival. Junta oleadas antes de ir a otro sitio."
        elif obj_n:
            leccion = "Bien convertido: tras ganar la pelea, fuisteis a por el objetivo. Eso es lo que gana partidas."
        elif caen_suyos:
            leccion = "Ganasteis la pelea pero no tomasteis nada. Después de ganar una pelea, ve a por torre o dragón."
        else:
            leccion = "Ventaja de farmeo: sigue así y conviértela en un objetivo."
        primero = min((x["ts"] for x in ev if x["tipo"] not in ("asist",)), default=int(a["m"] * 60000))
        momentos.append({"desde": a["m"], "hasta": b["m"], "dif": d, "bien": bien, "que": que, "leccion": leccion,
                         "pv_antes": a["pv"], "pv_despues": b["pv"], "seg": max(0, int(primero / 1000))})

    resumen = {}
    eqs = [(x["eq"], x["m"]) for x in serie]
    if eqs:
        mx, mn = max(eqs), min(eqs)
        resumen["max"] = {"dif": mx[0], "m": mx[1]}
        resumen["min"] = {"dif": mn[0], "m": mn[1]}
        gano = bool((parts[yo_id].get("stats") or {}).get("win"))
        if gano and mn[0] <= -2500:
            resumen["historia"] = f"Remontada: tu equipo llegó a ir {_miles(-mn[0])} de oro por detrás (min {int(mn[1])})."
        elif not gano and mx[0] >= 2500:
            resumen["historia"] = f"Ventaja perdida: tu equipo llegó a ir {_miles(mx[0])} de oro por delante (min {int(mx[1])})."
    try:
        clips = clips_partida(frames, parts, yo_id, roles.get(yo_id), camp)
    except Exception:
        clips = []
    return {"serie": serie, "eventos": [x for x in eventos if x["tipo"] != "kill_eq" or True], "momentos": momentos,
            "resumen": resumen, "rival": camp(rival_id) if rival_id else "", "clips": clips}


def _lista_y(items):
    items = [i for i in items if i]
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def _color_mayor(v, verde, amarillo):
    return "verde" if v >= verde else "amarillo" if v >= amarillo else "rojo"


def _color_menor(v, verde, amarillo):
    return "verde" if v <= verde else "amarillo" if v <= amarillo else "rojo"


def _rol_por_posicion(pid, frames):
    xs, ys = [], []
    for f in frames[3:10]:
        pos = (_pf(f, pid) or {}).get("position")
        if pos:
            xs.append(pos["x"])
            ys.append(pos["y"])
    if not xs:
        return ""
    x, y = sum(xs) / len(xs), sum(ys) / len(ys)
    if y - x > 4000:
        return "top"
    if x - y > 4000:
        return "bot"
    return "mid"


# Puntos de referencia de cada linea en el mapa (para asignar roles por posicion)
ANCLAS = {"top": (1800, 12800), "mid": (7400, 7400), "bot": (12800, 1800)}
# Fosos de los objetivos grandes (cuando el evento no trae la posicion)
POZOS = {"DRAGON": (9866, 4414), "ELDER_DRAGON": (9866, 4414), "BARON_NASHOR": (5007, 10471),
         "RIFTHERALD": (5007, 10471), "HORDE": (5007, 10471)}
LANE_ROL = {"TOP": "top", "MIDDLE": "mid", "MID": "mid", "BOTTOM": "bot", "JUNGLE": "jungla"}


def _pos_media(pid, frames):
    xs, ys = [], []
    for f in frames[2:11]:
        pos = (_pf(f, pid) or {}).get("position")
        if pos:
            xs.append(pos["x"])
            ys.append(pos["y"])
    return (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else None


def _roles(parts, frames, mins):
    """Un rol por jugador y por equipo: 1 jungla, 1 support, y top/mid/ADC segun donde jugo cada uno.
    Asi un support siempre se compara con el support rival, nunca con el ADC."""
    from itertools import permutations
    compras = {}
    for t, e in _eventos(frames):
        if t == "ITEM_PURCHASED":
            compras.setdefault(e.get("participantId"), set()).add(e.get("itemId"))
    roles, equipos = {}, {}
    for pid, p in parts.items():
        equipos.setdefault(p.get("teamId"), []).append(pid)
    for ids in equipos.values():
        info = {}
        for pid in ids:
            p = parts[pid]
            st = p.get("stats") or {}
            tl = p.get("timeline") or {}
            items = {st.get(f"item{i}") for i in range(7)} | compras.get(pid, set())
            info[pid] = {"smite": SMITE in (p.get("spell1Id"), p.get("spell2Id")),
                         "sup_item": bool(items & SUPPORT_ITEMS),
                         "cs": (st.get("totalMinionsKilled") or 0) + (st.get("neutralMinionsKilled") or 0),
                         "jcs": st.get("neutralMinionsKilled") or 0,
                         "lane": tl.get("lane"), "role": tl.get("role"), "pos": _pos_media(pid, frames)}
        resto = list(ids)
        jg = [x for x in resto if info[x]["smite"]] or [x for x in resto if info[x]["lane"] == "JUNGLE"]
        if jg:
            j = max(jg, key=lambda x: info[x]["jcs"])
            roles[j] = "jungla"
            resto.remove(j)
        sup = [x for x in resto if info[x]["sup_item"]] or [x for x in resto if info[x]["role"] == "DUO_SUPPORT"]
        if sup:
            s = min(sup, key=lambda x: info[x]["cs"])
            roles[s] = "support"
            resto.remove(s)
        huecos = ["top", "mid", "bot"] + ([] if sup else ["bot"])
        if resto and len(resto) <= len(huecos) and all(info[x]["pos"] for x in resto):
            mejor = min(set(permutations(huecos, len(resto))),
                        key=lambda perm: sum(math.dist(info[x]["pos"], ANCLAS[r]) for x, r in zip(resto, perm)))
            asign = dict(zip(resto, mejor))
            de_bot = [x for x, r in asign.items() if r == "bot"]
            if not sup and len(de_bot) == 2:          # dos en bot: el que menos farmea es el support
                asign[min(de_bot, key=lambda x: info[x]["cs"])] = "support"
            roles.update(asign)
        else:
            for x in resto:
                r = LANE_ROL.get(info[x]["lane"] or "", "")
                if not r and info[x]["pos"]:
                    r = min(ANCLAS, key=lambda k: math.dist(info[x]["pos"], ANCLAS[k]))
                if r == "bot" and mins > 15 and info[x]["cs"] / mins < 2.2:
                    r = "support"
                roles[x] = r
    return roles


def _encontrar_rival(yo_id, parts, frames, roles):
    yo = parts[yo_id]
    enemigos = [p for p in parts.values() if p.get("teamId") != yo.get("teamId")]
    if not enemigos:
        return None
    mismos = [p for p in enemigos if roles.get(p["participantId"]) == roles.get(yo_id) and roles.get(yo_id)]
    if len(mismos) == 1:
        return mismos[0]["participantId"]
    if not mismos and roles.get(yo_id) == "support":
        return None       # sin support rival claro: mejor no comparar que comparar contra el ADC
    yo_smite = SMITE in (yo.get("spell1Id"), yo.get("spell2Id"))
    candidatos = mismos or [p for p in enemigos
                            if (SMITE in (p.get("spell1Id"), p.get("spell2Id"))) == yo_smite] or enemigos
    mejor, dmin = None, float("inf")
    for p in candidatos:
        ds = []
        for f in frames[3:13]:
            a = (_pf(f, yo_id) or {}).get("position")
            b = (_pf(f, p["participantId"]) or {}).get("position")
            if a and b:
                ds.append(math.hypot(a["x"] - b["x"], a["y"] - b["y"]))
        if ds and sum(ds) / len(ds) < dmin:
            dmin, mejor = sum(ds) / len(ds), p["participantId"]
    return mejor or candidatos[0]["participantId"]


# =============================================================== ANALISIS DE PARTIDA
def analizar(juego, tl, puuid, rec, rango_txt=""):
    """Convierte la partida + timeline del cliente en la revision del coach."""
    dur = _dur_seg(juego.get("gameDuration"))
    mins = max(dur / 60.0, 1.0)
    idents = {pi.get("participantId"): (pi.get("player") or {})
              for pi in juego.get("participantIdentities") or []}
    parts = {p.get("participantId"): p for p in juego.get("participants") or []}
    yo_id = next((pid for pid, pl in idents.items() if pl.get("puuid") == puuid), None)
    if yo_id is None or yo_id not in parts:
        return None
    yo = parts[yo_id]
    equipo = yo.get("teamId")
    st = yo.get("stats") or {}
    frames = (tl or {}).get("frames") or []
    roles = _roles(parts, frames, mins)
    rol = roles.get(yo_id, "")
    rival_id = _encontrar_rival(yo_id, parts, frames, roles)
    rival = parts.get(rival_id) or {}
    rst = rival.get("stats") or {}
    enemigos_ids = {pid for pid, p in parts.items() if p.get("teamId") != equipo}
    victoria = bool(st.get("win"))
    if "win" not in st:
        victoria = any(t.get("teamId") == equipo and str(t.get("win")).lower() in ("win", "true")
                       for t in juego.get("teams") or [])
    k, d, a = st.get("kills", 0), st.get("deaths", 0), st.get("assists", 0)
    cs = (st.get("totalMinionsKilled") or 0) + (st.get("neutralMinionsKilled") or 0)
    rcs = (rst.get("totalMinionsKilled") or 0) + (rst.get("neutralMinionsKilled") or 0)
    yo_camp = rec.campeon(yo.get("championId"))
    rival_camp = rec.campeon(rival.get("championId")) if rival else "-"
    es_yorick = yo.get("championId") == YORICK
    kills_equipo = sum((p.get("stats") or {}).get("kills", 0) for p in parts.values() if p.get("teamId") == equipo)
    kp = (k + a) / kills_equipo if kills_equipo else 0
    cw = st.get("visionWardsBoughtInGame") or 0
    wards = st.get("wardsPlaced") or 0
    tor = st.get("damageDealtToTurrets") or 0
    tmin = tor / mins
    compras_yo = {e.get("itemId") for t, e in _eventos(frames)
                  if t == "ITEM_PURCHASED" and e.get("participantId") == yo_id}
    final_yo = {st.get(f"item{i}") for i in range(7)}
    tiene_support_item = bool((compras_yo | final_yo) & SUPPORT_ITEMS)

    def valor_en(pid, minuto, campo):
        x = _pf(_frame_en(frames, minuto), pid)
        if not x:
            return None
        return _cs_pf(x) if campo == "cs" else x.get(campo)

    # ---------- Comparacion con el rival
    comp = []

    def fila(nombre, mio, suyo, miles=False):
        if mio is None or suyo is None:
            return
        comp.append({"nombre": nombre, "yo": _miles(mio) if miles else str(mio),
                     "rival": _miles(suyo) if miles else str(suyo),
                     "diff": _signo(mio - suyo, miles), "diff_num": mio - suyo})

    cs10, rcs10 = valor_en(yo_id, 10, "cs"), valor_en(rival_id, 10, "cs")
    if rol != "support":
        fila("CS a los 10 min", cs10, rcs10)
    fila("Oro a los 10 min", valor_en(yo_id, 10, "totalGold"), valor_en(rival_id, 10, "totalGold"), True)
    fila("Oro a los 15 min", valor_en(yo_id, 15, "totalGold"), valor_en(rival_id, 15, "totalGold"), True)
    niv15y, niv15r = valor_en(yo_id, 15, "level"), valor_en(rival_id, 15, "level")
    fila("Nivel a los 15 min", niv15y, niv15r)
    if rol != "support":
        fila("CS final", cs, rcs)
    m14 = 14 if mins >= 14.5 else max(5, int(mins) - 1)
    oro14y, oro14r = valor_en(yo_id, m14, "totalGold"), valor_en(rival_id, m14, "totalGold")
    oro14_diff = (oro14y - oro14r) if (oro14y is not None and oro14r is not None) else None
    fila("Daño a campeones", st.get("totalDamageDealtToChampions") or 0,
         rst.get("totalDamageDealtToChampions") or 0, True)
    fila("Daño a torres", tor, rst.get("damageDealtToTurrets") or 0, True)

    # ---------- Semaforo: solo lo que decide partidas (con peso)
    metricas = []
    extra = max(0, int((mins - 30) // 8))
    mv, ma = CONFIG["muertes"][0] + extra, CONFIG["muertes"][1] + extra
    metricas.append({"clave": "muertes", "nombre": "Muertes", "valor": str(d), "peso": 3,
                     "meta": f"{mv} o menos", "color": _color_menor(d, mv, ma),
                     "nota": "Cada muerte regala oro, experiencia y tiempo al rival."})
    if rol != "support":
        umbral = CONFIG["cs_min_jungla"] if rol == "jungla" else CONFIG["cs_min"]
        csm = cs / mins
        metricas.append({"clave": "cs_min", "nombre": "CS por minuto", "valor": _dec(csm), "peso": 2,
                         "meta": f"{_dec(umbral[0])} o más", "color": _color_mayor(csm, *umbral),
                         "nota": f"{cs} de CS en {int(mins)} min."})
        if cs10 is not None and rcs10 is not None and rol != "jungla":
            dif = cs10 - rcs10
            metricas.append({"clave": "cs_diff_10", "nombre": "CS vs rival al min 10", "valor": _signo(dif),
                             "peso": 1, "meta": "0 o más", "color": _color_mayor(dif, *CONFIG["cs_diff_10"]),
                             "nota": f"Tú {cs10}, {rival_camp} {rcs10}."})
    if oro14_diff is not None:
        metricas.append({"clave": "oro14", "nombre": f"Oro vs rival al min {m14}", "valor": _signo(oro14_diff, True),
                         "peso": 2, "meta": "0 o más", "color": _color_mayor(oro14_diff, 0, -700),
                         "nota": f"Tú {_miles(oro14y)}, {rival_camp} {_miles(oro14r)}. Es el resultado de tu línea."})
    if rol == "support":
        metricas.append({"clave": "objeto_support", "nombre": "Objeto de support", "peso": 2,
                         "valor": "Sí" if tiene_support_item else "No", "meta": "Sí",
                         "color": "verde" if tiene_support_item else "rojo",
                         "nota": "Sin él una support no gana oro."})
    if rol == "top" or rol == "":
        metricas.append({"clave": "torres", "nombre": "Daño a torres", "valor": _miles(tor), "peso": 1,
                         "meta": f"{_miles(CONFIG['torres_min'][0] * mins)} o más",
                         "color": _color_mayor(tmin, *CONFIG["torres_min"]),
                         "nota": (f"{int(tmin)} por minuto. " +
                                  ("Yorick gana partidas tirando torres." if es_yorick
                                   else "Las torres ganan partidas, las kills no."))})
    else:
        metricas.append({"clave": "kp", "nombre": "Participación en kills", "valor": f"{round(kp * 100)}%",
                         "peso": 1, "meta": f"{round(CONFIG['kp'][0] * 100)}% o más",
                         "color": _color_mayor(kp, *CONFIG["kp"]),
                         "nota": f"Estuviste en {k + a} de las {kills_equipo} kills de tu equipo."})

    # ---------- Muertes en la timeline
    compras_ts = [e.get("timestamp", 0) for t, e in _eventos(frames)
                  if t == "ITEM_PURCHASED" and e.get("participantId") == yo_id]
    muertes = []
    for t, e in _eventos(frames):
        if t != "CHAMPION_KILL" or e.get("victimId") != yo_id:
            continue
        ts = e.get("timestamp") or 0
        killer = e.get("killerId") or 0
        asist = [x for x in (e.get("assistingParticipantIds") or []) if x in enemigos_ids]
        n_enem = (1 if killer in enemigos_ids else 0) + len(asist)
        fa = _frame_antes(frames, ts)
        oro = (_pf(fa, yo_id) or {}).get("currentGold")
        compro = any((fa.get("timestamp") or 0) < c <= ts for c in compras_ts) if fa else True
        quien = rec.campeon(parts[killer].get("championId")) if killer in parts else "Torre / súbditos"
        z = _zona(e.get("position"), equipo)
        muertes.append({"ts": ts, "min": _mmss(ts), "killer": quien, "killer_id": killer,
                        "killer_cid": parts[killer].get("championId") if killer in parts else None,
                        "x": (e.get("position") or {}).get("x"), "y": (e.get("position") or {}).get("y"),
                        "asistentes": len(asist), "asist_ids": asist, "n_enemigos": n_enem,
                        "zona": z, "zona_txt": ZONA_TXT[z],
                        "oro": None if oro is None else int(oro),
                        "oro_sin_gastar": (oro is not None and not compro and oro >= CONFIG["oro_sin_gastar"])})
    muertes.sort(key=lambda m: m["ts"])

    # ---------- Costo de cada muerte: el oro que pierde tu equipo. Los objetivos que caen despues NO se te
    # cargan a ti (dependen de tu jungla y de tu equipo); solo aparecen en el momento en que se rompio la partida.
    aliados_ids = {pid for pid, p in parts.items() if p.get("teamId") == equipo}

    # Muerte "sin tu equipo": ningun aliado mato, asistio o murio en los 15 s de antes o de despues
    kills_ev = [(e.get("timestamp") or 0, e) for t, e in _eventos(frames) if t == "CHAMPION_KILL"]
    otros_aliados = aliados_ids - {yo_id}
    for m in muertes:
        con_eq = False
        for ts2, e in kills_ev:
            if abs(ts2 - m["ts"]) <= VENTANA_PELEA_S * 1000:
                ids = {e.get("killerId"), e.get("victimId"), *(e.get("assistingParticipantIds") or [])}
                if ids & otros_aliados:
                    con_eq = True
                    break
        m["sin_equipo"] = not con_eq

    def dif_oro(frame):
        if not frame:
            return None
        pfs = frame.get("participantFrames") or {}
        return (sum((pfs.get(str(x)) or {}).get("totalGold", 0) for x in aliados_ids)
                - sum((pfs.get(str(x)) or {}).get("totalGold", 0) for x in enemigos_ids))

    def frame_despues(ts):
        for f in frames:
            if (f.get("timestamp") or 0) >= ts:
                return f
        return frames[-1] if frames else None

    perdidas_ev = []
    for t, e in _eventos(frames):
        ts = e.get("timestamp") or 0
        kid = e.get("killerId") or 0
        if t == "BUILDING_KILL":
            nuestro = (e.get("teamId") == equipo) if "teamId" in e else (kid in enemigos_ids)
            if nuestro:
                perdidas_ev.append((ts, _nombre_edificio(e)))
        elif t == "ELITE_MONSTER_KILL":
            kteam = e.get("killerTeamId")
            if kid in enemigos_ids or (kid not in aliados_ids and kteam is not None and kteam != equipo):
                perdidas_ev.append((ts, _nombre_monstruo(e)))
    for m in muertes:
        antes, despues = dif_oro(_frame_antes(frames, m["ts"])), dif_oro(frame_despues(m["ts"] + 60000))
        m["costo_oro"] = None if antes is None or despues is None else int(despues - antes)
        m["costo_txt"] = f"{_signo(m['costo_oro'], True)} de oro" if m["costo_oro"] is not None else ""
        if antes is not None and despues is not None:
            m["prob_antes"] = prob_victoria(antes, m["ts"] / 60000)
            m["prob_despues"] = prob_victoria(despues, m["ts"] / 60000 + 1)
    cara = None
    for m in muertes:
        puntos = -(m["costo_oro"] or 0)
        if puntos > 300 and (cara is None or puntos > cara[0]):
            cara = (puntos, m)
    muerte_cara = None
    if cara:
        m = cara[1]
        m["mas_cara"] = True
        muerte_cara = {"min": m["min"], "killer": m["killer"],
                       "texto": f"Min {m['min']} ({m['killer']}): tu equipo perdió {_miles(-m['costo_oro'])} de oro "
                                "de diferencia en el minuto siguiente." +
                                (" Moriste sin ningún aliado en la pelea." if m["sin_equipo"] and
                                 m["ts"] >= CONFIG["fin_fase_lineas_min"] * 60000 else "")}

    # ---------- Errores
    errores = []
    if muerte_cara:
        tarde = cara[1]["ts"] >= 20 * 60000
        errores.append({"clave": "cara", "sev": "alta" if cara[0] >= 1200 else "media",
                        "titulo": f"Tu muerte más cara fue la del minuto {cara[1]['min']}",
                        "detalle": (lambda s: s[:1].upper() + s[1:])(muerte_cara["texto"].split(": ", 1)[1]),
                        "consejo": ("Después del minuto 20 cada muerte deja a tu equipo jugando con uno menos "
                                    "casi un minuto. A esa altura, no morir vale más que cualquier kill."
                                    if tarde else
                                    "Esa muerte le dio al rival mucho más que una kill. Mírala en la repetición y "
                                    "busca qué no viste antes de morir: al jungla, a su mid o la falta de visión."),
                        "minutos": [cara[1]["min"]]})
    fase_ms = CONFIG["fin_fase_lineas_min"] * 60000

    def lista_min(ms):
        ms = [m["min"] for m in ms]
        return ", ".join(ms[:-1]) + " y " + ms[-1] if len(ms) > 1 else ms[0]

    if rol == "support" and not tiene_support_item:
        errores.append({"clave": "sin_support_item", "sev": "alta",
                        "titulo": "Jugaste de support sin objeto de support",
                        "detalle": "No lo compraste en toda la partida.",
                        "consejo": "Es lo que le da oro y wards a una support. Sin él juegas toda la partida "
                                   "pobre y sin visión. Cómpralo siempre antes de salir de base.",
                        "minutos": []})

    tempranas = [m for m in muertes if m["ts"] < fase_ms]
    if len(tempranas) >= 2:
        errores.append({"clave": "tempranas", "sev": "alta" if len(tempranas) >= 3 else "media",
                        "titulo": f"{len(tempranas)} muertes antes del minuto {CONFIG['fin_fase_lineas_min']}",
                        "detalle": f"Min {lista_min(tempranas)}.",
                        "consejo": "En fase de líneas cada muerte le da a tu rival unos 300 de oro y te hace "
                                   "perder la oleada. Hasta tu primer objeto completo juega a farmear: "
                                   "si dudas de un intercambio, no lo hagas.",
                        "minutos": [m["min"] for m in tempranas]})

    oro_muerto = [m for m in muertes if m["oro_sin_gastar"]]
    if oro_muerto:
        det = "; ".join(f"Min {m['min']} con ~{_miles(m['oro'])}" for m in oro_muerto)
        errores.append({"clave": "oro", "sev": "alta" if len(oro_muerto) >= 2 else "media",
                        "titulo": ("Moriste con oro sin gastar" if len(oro_muerto) == 1
                                   else f"{len(oro_muerto)} muertes con oro sin gastar"),
                        "detalle": f"{det} (oro del minuto anterior a morir).",
                        "consejo": f"Ese oro ya era un objeto. Con {_miles(CONFIG['oro_sin_gastar'])}+ de oro y "
                                   "la oleada empujada, vuelve a base antes de buscar pelea.",
                        "minutos": [m["min"] for m in oro_muerto]})

    # Morir en una pelea de equipo contra 3 es normal (sobre todo de support o tanque); lo evitable es morir SOLO
    solas = [m for m in muertes if m["ts"] >= fase_ms and m["sin_equipo"]]
    if len(solas) >= 2:
        errores.append({"clave": "solo", "sev": "alta" if len(solas) >= 3 else "media",
                        "titulo": f"Moriste {len(solas)} veces sin tu equipo después del minuto "
                                  f"{CONFIG['fin_fase_lineas_min']}",
                        "detalle": f"Min {lista_min(solas)}: nadie de tu equipo mató, asistió ni murió "
                                   f"{VENTANA_PELEA_S} segundos antes o después.",
                        "consejo": ("De support pasa al ir a poner visión: no entres primero a un arbusto ni a su "
                                    "jungla sin visión. Lanza el ward desde fuera y ve con tu jungla o tu tirador cerca."
                                    if rol == "support" else
                                    "Pasa al hacer split sin saber dónde están. Regla: si en el minimapa no ves a 3 "
                                    "enemigos, no pases del río, y retírate antes de que lleguen, no después."
                                    if rol == "top" else
                                    "Desde el minuto 14, muévete con al menos un aliado o por zonas que tu equipo ve. "
                                    "Si no hay visión, no entres primero."),
                        "minutos": [m["min"] for m in solas]})

    solo_rival = [m for m in muertes if m["killer_id"] == rival_id and m["asistentes"] == 0]
    if len(solo_rival) >= 2:
        errores.append({"clave": "solo_rival", "sev": "alta" if len(solo_rival) >= 3 else "media",
                        "titulo": f"{rival_camp} te mató solo {len(solo_rival)} veces",
                        "detalle": f"Duelos 1 contra 1 perdidos en el min {lista_min(solo_rival)}.",
                        "consejo": "Ese duelo no lo ganas ahora mismo. Deja de pelearle de frente: farmea, "
                                   "pide ayuda a tu jungla y pelea solo cuando tenga sus habilidades en "
                                   "enfriamiento.",
                        "minutos": [m["min"] for m in solo_rival]})

    cadenas, actual = [], []
    for m in muertes:
        if actual and m["ts"] - actual[-1]["ts"] <= 240000:
            actual.append(m)
        else:
            if len(actual) >= 2:
                cadenas.append(actual)
            actual = [m]
    if len(actual) >= 2:
        cadenas.append(actual)
    if cadenas:
        det = "; ".join(" → ".join(x["min"] for x in c) for c in cadenas)
        larga = max(cadenas, key=len)
        span = max(1, round((larga[-1]["ts"] - larga[0]["ts"]) / 60000))
        errores.append({"clave": "seguidas", "sev": "alta" if len(larga) >= 3 else "media",
                        "titulo": (f"Encadenaste {len(larga)} muertes en {span} minutos" if len(cadenas) == 1
                                   else f"Encadenaste muertes {len(cadenas)} veces"),
                        "detalle": f"Min {det}.",
                        "consejo": "Después de morir no fuerces para recuperar lo perdido. Vuelve, juega seguro "
                                   "y vuelve a evaluar. La segunda muerte duele más que la primera.",
                        "minutos": [x["min"] for c in cadenas for x in c]})

    lado_enem = [m for m in tempranas if m["zona"] == "enemiga"]
    if len(lado_enem) >= 2:
        errores.append({"clave": "adelantado", "sev": "media",
                        "titulo": f"{len(lado_enem)} muertes tempranas en el lado enemigo del mapa",
                        "detalle": f"Min {lista_min(lado_enem)}.",
                        "consejo": "Estabas demasiado adelantado y sin visión: presa fácil de la jungla rival. "
                                   "Si tu oleada está cerca de su torre y no tienes ward, retrocede.",
                        "minutos": [m["min"] for m in lado_enem]})

    if oro14_diff is not None and oro14_diff <= -1000:
        errores.append({"clave": "linea", "sev": "alta" if oro14_diff <= -2000 else "media",
                        "titulo": f"Perdiste tu línea: {_miles(-oro14_diff)} de oro por detrás de {rival_camp} "
                                  f"al minuto {m14}",
                        "detalle": f"Tú {_miles(oro14y)}, {rival_camp} {_miles(oro14r)}.",
                        "consejo": "Una línea perdida casi siempre empieza con muertes o farmeo flojo. Cuando tu "
                                   "rival es más fuerte, farmea bajo tu torre, no intercambies y pide ayuda a tu jungla.",
                        "minutos": []})

    errores.sort(key=lambda e: (0 if e["sev"] == "alta" else 1))

    # ---------- Nota: ponderada por lo que decide partidas
    validas = [m for m in metricas if m["color"]]
    peso_t = sum(m["peso"] for m in validas)
    pts = sum(m["peso"] * {"verde": 1, "amarillo": 0.5, "rojo": 0}[m["color"]] for m in validas)
    nota = (pts / peso_t * 10) if peso_t else 5
    altas = [e for e in errores if e["sev"] == "alta"]
    nota -= min(2.5, 0.8 * len(altas) + 0.3 * (len(errores) - len(altas)))
    nota = round(max(0.0, min(10.0, nota)), 1)
    nivel = "bien" if nota >= NOTA_BIEN else "regular" if nota >= NOTA_REGULAR else "mal"
    titulo = {"bien": "Jugaste bien", "regular": "Jugaste regular", "mal": "Jugaste mal"}[nivel]

    # ---------- Por que se gano o se perdio: separa tu partida de lo que no dependia de ti
    def afk_de(pid):
        if not frames or "xp" not in (_pf(frames[min(2, len(frames) - 1)], pid) or {}):
            return None
        racha, inicio, mejor = 0, 0, (0, 0)
        for f0, f1 in zip(frames[2:], frames[3:]):
            a0, a1 = _pf(f0, pid) or {}, _pf(f1, pid) or {}
            if not a0 or not a1:
                continue
            quieto = ((a1.get("xp") or 0) - (a0.get("xp") or 0) <= 0 and _cs_pf(a1) - _cs_pf(a0) <= 0
                      and (a1.get("totalGold") or 0) - (a0.get("totalGold") or 0) < 200)
            if quieto:
                if racha == 0:
                    inicio = f0.get("timestamp") or 0
                racha += 1
                if racha > mejor[0]:
                    mejor = (racha, inicio)
            else:
                racha = 0
        return {"minutos": mejor[0], "desde": _mmss(mejor[1])} if mejor[0] >= 3 else None

    afk_al, afk_en = [], []
    for pid, p in parts.items():
        if pid == yo_id:
            continue
        x = afk_de(pid)
        if x:
            (afk_al if pid in aliados_ids else afk_en).append({"campeon": rec.campeon(p.get("championId")),
                                                               "cid": p.get("championId"), **x})
    regalan = [{"campeon": rec.campeon(p.get("championId")), "cid": p.get("championId"),
                "d": (p.get("stats") or {}).get("deaths", 0)}
               for pid, p in parts.items() if pid in aliados_ids and pid != yo_id
               and (p.get("stats") or {}).get("deaths", 0) >= max(8, d + 4)]
    linea = None
    if oro14_diff is not None:
        linea = "ganada" if oro14_diff >= 500 else "perdida" if oro14_diff <= -500 else "pareja"
    elif cs10 is not None and rcs10 is not None:
        linea = "ganada" if cs10 - rcs10 >= 15 else "perdida" if cs10 - rcs10 <= -15 else "pareja"

    quiebre = None
    difs = [(f.get("timestamp") or 0, dif_oro(f)) for f in frames]
    if len(difs) >= 6:
        signo = 1 if victoria else -1
        mejor_i, mejor_d = None, 0
        for i in range(len(difs) - 3):
            cambio = (difs[i + 3][1] - difs[i][1]) * signo
            if cambio > mejor_d:
                mejor_i, mejor_d = i, cambio
        if mejor_i is not None and mejor_d >= 2000:
            t0, t1 = difs[mejor_i][0], difs[mejor_i + 3][0]
            muertes_al = Counter()
            for t, e in _eventos(frames):
                ts = e.get("timestamp") or 0
                if t == "CHAMPION_KILL" and t0 <= ts <= t1:
                    v = e.get("victimId")
                    if (v in aliados_ids) == (not victoria):
                        muertes_al["tú" if v == yo_id else rec.campeon(parts[v].get("championId"))] += 1
            obj = [n for ts, n in perdidas_ev if t0 <= ts <= t1 and n] if not victoria else []
            partes = [f"tu equipo pasó de {_signo(difs[mejor_i][1], True)} a {_signo(difs[mejor_i + 3][1], True)} de oro"]
            if muertes_al:
                quien = ", ".join(f"{n} ({c})" if c > 1 else n for n, c in muertes_al.most_common())
                partes.append(("murieron " if not victoria else "cayeron del otro equipo ") + quien)
            if obj:
                partes.append("cayó " + _lista_y(obj))
            quiebre = (f"La partida se {'rompió' if not victoria else 'decidió'} entre el minuto "
                       f"{int(t0 // 60000)} y el {int(t1 // 60000)}: " + "; ".join(partes) + ".")

    graves = [e for e in altas if e["clave"] in
              ("cara", "tempranas", "seguidas", "linea", "solo", "solo_rival", "sin_support_item", "oro")]
    resumen = []
    if linea == "ganada":
        resumen.append(f"ganaste tu línea ({_signo(oro14_diff, True)} de oro al minuto {m14})"
                       if oro14_diff is not None else "ganaste tu línea")
    resumen.append(f"moriste {'solo ' if d <= 3 else ''}{d} {'vez' if d == 1 else 'veces'}")
    causas = []
    for x in afk_al:
        causas.append({"tipo": "externo", "cid": x["cid"],
                       "texto": f"{x['campeon']} estuvo AFK o desconectado unos {x['minutos']} "
                                f"minutos desde el {x['desde']}."})
    for x in regalan:
        causas.append({"tipo": "externo", "cid": x["cid"], "texto": f"{x['campeon']}, de tu equipo, murió {x['d']} veces."})
    if linea == "ganada":
        causas.append({"tipo": "bueno", "cid": rival.get("championId"), "texto": f"Ganaste tu línea contra {rival_camp}"
                       + (f": {_signo(oro14_diff, True)} de oro al minuto {m14}" if oro14_diff is not None else "")
                       + f". {rival_camp} terminó {rst.get('kills', 0)}/{rst.get('deaths', 0)}/{rst.get('assists', 0)}."})
    elif linea == "perdida":
        causas.append({"tipo": "propio", "cid": rival.get("championId"), "texto": f"Perdiste tu línea contra {rival_camp}: "
                                                  f"{_signo(oro14_diff, True)} de oro al minuto {m14}."})
    for e in graves[:2]:
        if e["clave"] != "linea":
            causas.append({"tipo": "propio", "texto": f"{e['titulo']}. {e['detalle']}"})
    if quiebre:
        causas.append({"tipo": "neutral", "texto": quiebre})
    for x in afk_en:
        causas.append({"tipo": "externo", "cid": x["cid"], "texto": f"En el equipo rival, {x['campeon']} estuvo AFK o desconectado "
                                                   f"unos {x['minutos']} minutos desde el {x['desde']}."})

    if victoria:
        culpa = None
        sub = {"bien": "Ganaste y tus números lo respaldan.",
               "regular": "Ganaste, pero hubo errores que en otra partida te cuestan la derrota.",
               "mal": "Ganaste, pero no por cómo jugaste. Esto no se repite solo."}[nivel]
        if afk_en:
            sub += " Ojo: el rival jugó con un AFK."
    elif afk_al and nivel != "mal":
        culpa = "no_tuya"
        sub = (f"Perdiste por un AFK: {afk_al[0]['campeon']} se fue en el minuto {afk_al[0]['desde']}. "
               + ("Tu parte la hiciste." if nivel == "bien" else "Igual, mira tus errores de abajo."))
    elif not graves and nivel == "bien":
        culpa = "no_tuya"
        sub = "Perdiste, pero no por ti: " + " y ".join(resumen) + "."
        if regalan:
            sub += f" {regalan[0]['campeon']} murió {regalan[0]['d']} veces."
    elif graves:
        culpa = "tuya" if (nivel == "mal" and not afk_al and not regalan) else "compartida"
        sub = ("Perdiste y tus errores pesaron: " + graves[0]["titulo"][:1].lower() + graves[0]["titulo"][1:] + "."
               if culpa == "tuya" else
               "Perdiste. Hubo cosas que no dependían de ti, pero también errores tuyos que cuestan partidas.")
    else:
        culpa = "compartida"
        sub = "Perdiste en una partida pareja: tus números no explican la derrota por sí solos."
    por_que = {"titulo": "Por qué ganaste" if victoria else "Por qué perdiste", "causas": causas, "culpa": culpa}


    # ---------- Datos para las etapas siguientes (linea, mapa, objetivos, despues de la linea)
    jg_rival = next((pid for pid in enemigos_ids if roles.get(pid) == "jungla"), None)
    muertes_14 = [m for m in muertes if m["ts"] < fase_ms]
    muertes_gank = [m for m in muertes_14 if jg_rival and (m["killer_id"] == jg_rival
                                                            or jg_rival in (m.get("asist_ids") or []))]
    vision_score = st.get("visionScore")
    objetivos = []
    for t, e in _eventos(frames):
        ts = e.get("timestamp") or 0
        mt = (e.get("monsterType") or "").upper()
        if t != "ELITE_MONSTER_KILL" or ts < 5 * 60000 or mt not in POZOS and not e.get("position"):
            continue
        pos = e.get("position") or {"x": POZOS[mt][0], "y": POZOS[mt][1]}
        # lo mataste o ayudaste a matarlo: estabas, aunque el minuto exacto te pille de camino
        cerca = yo_id is not None and (e.get("killerId") == yo_id or yo_id in (e.get("assistingParticipantIds") or []))
        for f in ((_frame_antes(frames, ts), frame_despues(ts)) if not cerca else ()):
            q = (_pf(f, yo_id) or {}).get("position") if f else None
            if q and math.dist((q.get("x", 0), q.get("y", 0)), (pos.get("x", 0), pos.get("y", 0))) <= 3000:
                cerca = True
        if not cerca:      # o estuviste en una pelea junto al objetivo
            for ts2, e2 in kills_ev:
                pe = e2.get("position") or {}
                ids = {e2.get("killerId"), e2.get("victimId"), *(e2.get("assistingParticipantIds") or [])}
                if (abs(ts2 - ts) <= 45000 and yo_id in ids and pe
                        and math.dist((pe.get("x", 0), pe.get("y", 0)), (pos.get("x", 0), pos.get("y", 0))) <= 4000):
                    cerca = True
                    break
        objetivos.append({"min": _mmss(ts), "nombre": _nombre_monstruo(e) or "un objetivo", "ok": cerca})
    cs_post, cs_post_hasta = None, None
    if rol in ("top", "mid", "bot") and mins >= 20 and frames:
        hasta = min(25, int(mins))
        c14, cf = valor_en(yo_id, fase_ms // 60000, "cs"), valor_en(yo_id, hasta, "cs")
        if c14 is not None and cf is not None and hasta > fase_ms // 60000:
            cs_post, cs_post_hasta = round((cf - c14) / (hasta - fase_ms // 60000), 2), hasta

    # ---------- Datos para los habitos
    datos_h = {
        "rol": rol, "mins": round(mins, 2), "con_tl": bool(frames), "d": d,
        "muertes_10": [{"min": m["min"], "killer": m["killer"], "n": m["n_enemigos"]}
                       for m in muertes if m["ts"] < 600000],
        "oro_muerto": [{"min": m["min"], "oro": m["oro"]} for m in oro_muerto],
        "cs10": cs10, "cw": cw, "support_item": tiene_support_item, "wards": wards,
        "solo_14": [{"min": m["min"], "killer": m["killer"], "n": m["n_enemigos"]} for m in solas],
        "muertes_14": [{"min": m["min"], "killer": m["killer"], "n": m["n_enemigos"]} for m in muertes_14],
        "muertes_gank": [{"min": m["min"], "killer": m["killer"], "n": m["n_enemigos"]} for m in muertes_gank],
        "jg_rival": bool(jg_rival),
        "vision_min": round(vision_score / mins, 3) if vision_score is not None else None,
        "objetivos": objetivos if frames else None,
        "cs_post": cs_post, "cs_post_hasta": cs_post_hasta,
        "d_25": sum(1 for m in muertes if m["ts"] >= 25 * 60000),
        "nota": nota,
        "d_14": sum(1 for m in muertes if m["ts"] >= fase_ms),
        "torres": tor, "kp": round(kp, 3), "csmin": round(cs / mins, 2), "torres_min": round(tmin, 1),
        "wards_min": round(wards / mins, 3),
        "cs10_diff": (cs10 - rcs10) if (cs10 is not None and rcs10 is not None) else None,
        "rival_id": rival.get("championId"),
        "solo_rival": len(solo_rival),
        "oro14_diff": oro14_diff, "linea": linea,
        "afk_aliado": bool(afk_al), "afk_rival": bool(afk_en), "campeon_id": yo.get("championId"),
    }

    creacion = juego.get("gameCreation") or 0
    cola = juego.get("queueId")
    items_yo = [st.get(f"item{i}") for i in range(7) if st.get(f"item{i}")]
    items_rival = [rst.get(f"item{i}") for i in range(7) if rst.get(f"item{i}")]

    # ---------- Runas y build de esta partida (para poder fijarlas)
    runas = None
    perks = [st.get(f"perk{i}") for i in range(6)]
    if st.get("perkPrimaryStyle") and all(perks):
        shards = [st.get(f"statPerk{i}") for i in range(3)]
        runas = {"primaryStyleId": st.get("perkPrimaryStyle"), "subStyleId": st.get("perkSubStyle"),
                 "selectedPerkIds": perks + (shards if all(shards) else [5008, 5008, 5011])}
    primera = {}
    for t, e in _eventos(frames):
        if t == "ITEM_PURCHASED" and e.get("participantId") == yo_id:
            primera.setdefault(e.get("itemId"), e.get("timestamp") or 0)
    orden = sorted([i for i in items_yo if i not in NO_BUILD], key=lambda i: primera.get(i, 10 ** 12))
    inicio = sorted({i for i, ts in primera.items() if ts < 90000 and i})
    build = {"inicio": inicio, "orden": orden} if orden else None
    # ---------- Ventaja de oro de tu equipo minuto a minuto y tus numeros por fase
    oro_serie = []
    for f in frames:
        dd = dif_oro(f)
        if dd is not None:
            oro_serie.append([round((f.get("timestamp") or 0) / 60000, 1), int(dd)])
    fases = []
    if frames:
        fin_ms = frames[-1].get("timestamp") or int(dur * 1000)
        ka = []
        for t, e in _eventos(frames):
            if t == "CHAMPION_KILL" and (e.get("killerId") == yo_id or yo_id in (e.get("assistingParticipantIds") or [])):
                ka.append(e.get("timestamp") or 0)
        for nombre_f, a_min, b_min in (("Línea", 0, 14), ("Mitad", 14, 25), ("Final", 25, None)):
            a_ms = a_min * 60000
            b_ms = min(fin_ms, b_min * 60000) if b_min else fin_ms
            if b_ms - a_ms < 120000:
                continue
            x0, x1 = _pf(_frame_antes(frames, a_ms), yo_id), _pf(_frame_antes(frames, b_ms), yo_id)
            if a_min == 0 and not x0:
                x0 = {}
            if x0 is None or not x1:
                continue
            m_f = (b_ms - a_ms) / 60000
            fases.append({"nombre": nombre_f, "de": a_min, "a": round(b_ms / 60000),
                          "cs_min": round((_cs_pf(x1) - _cs_pf(x0)) / m_f, 1),
                          "oro_min": int(((x1.get("totalGold") or 0) - (x0.get("totalGold") or 0)) / m_f),
                          "muertes": sum(1 for m in muertes if a_ms <= m["ts"] < b_ms or (not b_min and m["ts"] >= a_ms)),
                          "ka": sum(1 for ts in ka if a_ms <= ts < b_ms or (not b_min and ts >= a_ms))})
    # ---------- Tus mejores jugadas (para verlas en la repeticion): kills seguidas y kills en solitario
    jugadas = []
    mis_k = sorted([(e.get("timestamp") or 0, e) for t, e in _eventos(frames)
                    if t == "CHAMPION_KILL" and e.get("killerId") == yo_id], key=lambda x: x[0])
    grupo = []
    for ts, e in mis_k + [(10 ** 12, None)]:
        if grupo and ts - grupo[-1][0] > 12000:
            n_k = len(grupo)
            solo = sum(1 for _, x in grupo if not [a for a in (x.get("assistingParticipantIds") or []) if a in aliados_ids])
            victimas = [rec.campeon(parts[x.get("victimId")].get("championId")) for _, x in grupo if x.get("victimId") in parts]
            if n_k >= 2 or solo:
                nombre_j = {2: "Doble kill", 3: "Triple kill", 4: "Cuádruple kill"}.get(n_k, "Pentakill" if n_k >= 5 else "Kill en solitario")
                jugadas.append({"ts": grupo[0][0], "min": _mmss(grupo[0][0]), "titulo": nombre_j,
                                "texto": "Mataste a " + _lista_y(victimas) + (" sin ayuda" if solo == n_k else "") + ".",
                                "puntos": n_k * 2 + solo, "seg": max(0, int(grupo[0][0] / 1000) - 12)})
            grupo = []
        if e is not None:
            grupo.append((ts, e))
    jugadas = sorted(sorted(jugadas, key=lambda j: -j["puntos"])[:5], key=lambda j: j["ts"])
    # ---------- mas numeros de la partida para los retos (todos del resultado oficial de la partida)
    oro_ganado = st.get("goldEarned") or 0
    datos_h.update({
        "solo_kills": sum(1 for _, x in mis_k if not [a for a in (x.get("assistingParticipantIds") or []) if a in aliados_ids]),
        "wards_quitados": st.get("wardsKilled"), "dano_objetivos": st.get("damageDealtToObjectives"),
        "racha": st.get("largestKillingSpree"), "cc_seg": st.get("timeCCingOthers"),
        "nivel15_diff": (niv15y - niv15r) if (niv15y is not None and niv15r is not None) else None,
        "oro_gastado_pct": round(100 * (st.get("goldSpent") or 0) / oro_ganado) if oro_ganado else None,
        "dives": len([m for m in muertes if m.get("zona") == "enemiga" and m.get("sin_equipo") and m["ts"] >= 600000]),
    })
    try:
        puestos = puestos_partida(parts, roles, mins, yo_id, rec) if len(parts) == 10 else []
    except Exception:
        puestos = []
    obj_support = None
    if rol == "support":
        def primera_vez(ids):
            ts = [e.get("timestamp") or 0 for t, e in _eventos(frames)
                  if e.get("participantId") == yo_id and t.startswith("ITEM")
                  and (e.get("itemId") in ids or e.get("afterId") in ids)]
            return min(ts) if ts else None
        t1, t2 = primera_vez({3866}), primera_vez({3867, 3869, 3870, 3871, 3876, 3877})
        obj_support = {"t1": None if t1 is None else _mmss(t1), "t2": None if t2 is None else _mmss(t2),
                       "t2_min": None if t2 is None else round(t2 / 60000, 1),
                       "completo": bool(final_yo & {3867, 3869, 3870, 3871, 3876, 3877})}
    an = {
        "v": ANALISIS_V, "id": str(juego.get("gameId")), "creacion": creacion,
        "fin_ts": creacion + int(dur * 1000),
        "fecha": datetime.fromtimestamp(creacion / 1000).strftime("%Y-%m-%d %H:%M") if creacion else "",
        "cola_id": cola, "cola": COLAS.get(cola, f"Cola {cola}"),
        "cuenta_anti": cola in CONFIG["colas_anti_racha"],
        "duracion": _mmss(dur * 1000), "minutos": round(mins, 1),
        "victoria": victoria, "rol": rol, "carril": ROL_TXT.get(rol, ""), "equipo": equipo,
        "yo": {"campeon": yo_camp, "campeon_id": yo.get("championId"), "k": k, "d": d, "a": a,
               "kda": f"{k}/{d}/{a}", "ratio": round((k + a) / max(d, 1), 2), "cs": cs,
               "nivel": st.get("champLevel"), "oro": st.get("goldEarned"),
               "items": [{"id": i, "nombre": rec.item(i)} for i in items_yo]},
        "rival": {"campeon": rival_camp, "campeon_id": rival.get("championId"),
                  "kda": f"{rst.get('kills', 0)}/{rst.get('deaths', 0)}/{rst.get('assists', 0)}",
                  "cs": rcs, "items": [{"id": i, "nombre": rec.item(i)} for i in items_rival]} if rival else None,
        "metricas": metricas, "errores": errores, "muertes": muertes, "comparacion": comp,
        "veredicto": {"nivel": nivel, "titulo": titulo, "sub": sub, "nota": nota, "culpa": culpa},
        "por_que": por_que,
        "con_timeline": bool(frames), "datos_h": datos_h, "muerte_cara": muerte_cara,
        "runas": runas, "build": build, "oro_serie": oro_serie, "fases": fases,
        "puestos": puestos, "puesto": next((x["puesto"] for x in puestos if x["yo"]), None),
        "obj_support": obj_support, "jugadas": jugadas,
    }
    an["texto_claude"] = _texto_claude(an, rango_txt)
    return an


def _texto_claude(an, rango_txt):
    yo, rv = an["yo"], an["rival"]
    L = ["Analiza esta partida mía de League of Legends." + (f" Mi rango: {rango_txt}." if rango_txt else ""),
         f"Resultado: {'Victoria' if an['victoria'] else 'Derrota'} | {an['cola']} | {an['duracion']} | {an['fecha']}",
         f"Yo: {yo['campeon']}" + (f" ({an['carril']})" if an['carril'] else "") +
         f" - KDA {yo['kda']}, {yo['cs']} CS, nivel {yo['nivel']}"]
    if rv:
        L.append(f"Rival directo: {rv['campeon']} - KDA {rv['kda']}, {rv['cs']} CS")
    if an["comparacion"]:
        L.append("Comparación con el rival: " + " | ".join(
            f"{c['nombre']}: {c['yo']} vs {c['rival']} ({c['diff']})" for c in an["comparacion"]))
    L.append("Semáforo: " + " | ".join(
        f"{m['nombre']} {m['valor']} ({m['color'] or 'sin dato'}, meta {m['meta']})" for m in an["metricas"]))
    if an["errores"]:
        L.append("Errores detectados:")
        for e in an["errores"]:
            L.append(f"- {e['titulo']}. {e['detalle']}")
    if an["muertes"]:
        L.append("Muertes (minuto | quién me mató | enemigos involucrados | zona | oro encima aprox. | "
                 "costo para mi equipo en el minuto siguiente):")
        for m in an["muertes"]:
            L.append(f"- {m['min']} | {m['killer']} | {m['n_enemigos']} | {m['zona_txt']} | "
                     f"{_miles(m['oro']) if m['oro'] is not None else '-'} | {m.get('costo_txt') or '-'}")
    if yo["items"]:
        L.append("Mis objetos finales: " + ", ".join(i["nombre"] for i in yo["items"]))
    if rv and rv["items"]:
        L.append("Objetos finales del rival: " + ", ".join(i["nombre"] for i in rv["items"]))
    v = an["veredicto"]
    L.append(f"Veredicto del coach: {v['titulo']} ({v['nota']}/10). {v['sub']}")
    if an.get("por_que") and an["por_que"]["causas"]:
        L.append(an["por_que"]["titulo"] + ": " + " ".join(c["texto"] for c in an["por_que"]["causas"]))
    L.append("Dime, sin rodeos, los 2 errores que más me costaron esta partida y qué tengo que hacer "
             "distinto en la siguiente.")
    return "\n".join(L)


# =============================================================== HABITOS
# Cada mision es una CONDUCTA TUYA que se cumple jugando tu rol y que se mide sin depender de lo que hagan
# los demas. Nada de culparte por resultados del equipo ni de cosas que se deciden fuera de la partida
# (elegir campeon, comprar un objeto): eso va como recomendacion en la seleccion y en la pantalla de carga.
# Van por etapas (ETAPAS, mas abajo): primero morir menos y farmear; los objetivos, la vision y el macro
# llegan cuando lo basico ya esta dominado, como dice la investigacion por rango.
HABITOS = [
    {"clave": "vivo_10", "nombre": "Sobrevivir la fase de líneas", "roles": None, "defecto": 0.22,
     "por_que": "Cada muerte temprana le da a tu rival oro y la oleada, y te deja atrás el resto de la partida.",
     "como": ["Hasta el minuto 10 tu trabajo es farmear y no morir. Nada más.",
              "Si no ves al jungla rival en el minimapa, juega cerca de tu torre.",
              "Con menos de media vida, vuelve a base. No esperes a la siguiente oleada."],
     "como_rol": {"support": [
         "Hasta el minuto 10 tu trabajo es no morir y que tu tirador farmee. Intercambia solo cuando el rival falle "
         "su habilidad principal.",
         "Contra ganchos y enganches (Thresh, Blitzcrank, Nautilus...), quédate detrás de tus súbditos.",
         "Si no ves al jungla rival en el minimapa, no te metas en su arbusto: juega al lado de tu tirador."]}},
    {"clave": "muertes", "nombre": "Morir poco", "roles": None, "defecto": 0.25, "niveles": True,
     "por_que": "Morir es lo que más partidas pierde en Hierro: cada muerte es oro, experiencia y tiempo para el rival.",
     "como": ["Antes de cada pelea pregúntate dónde están los 5 enemigos.",
              "Si dudas, no entres. Una muerte menos vale más que una kill más.",
              "Después de morir, juega seguro: no fuerces para recuperar lo perdido."]},
    {"clave": "solo", "nombre": "No morir solo", "roles": None, "defecto": 0.18,
     "por_que": "Pasada la fase de líneas, morir sin tu equipo en la pelea es la muerte más fácil de evitar y la que "
                "menos da a cambio: no cambias tu vida por nada y tu equipo juega con uno menos.",
     "como": ["Desde el minuto 14, muévete con al menos un aliado o por zonas que tu equipo ve.",
              "No entres primero a la niebla ni a un arbusto sin visión.",
              "Si 3 o más enemigos desaparecen del minimapa, retrocede hacia tu equipo."],
     "como_rol": {
         "support": ["No entres primero a un arbusto sin visión: lanza el ward desde fuera o tira una habilidad antes.",
                     "Desde el minuto 14, pon visión con tu jungla o tu tirador cerca; no vayas solo al lado enemigo.",
                     "Si en el minimapa no ves a 3 enemigos, no avances a poner wards en su jungla."],
         "top": ["Si haces split, mira el minimapa en cada oleada: si no ves a 3 enemigos, no pases del río.",
                 "Empuja la oleada y retírate antes de que lleguen, no después.",
                 "Si 3 o más enemigos desaparecen del minimapa, asume que vienen por ti."]}},
    {"clave": "cs10", "nombre": "Farmear", "roles": {"top", "mid", "bot", "jungla"}, "defecto": 0.15,
     "niveles": True,
     "por_que": "El CS es oro que nadie te puede quitar: decide si llegas a las peleas con objetos o sin ellos.",
     "como": ["Último golpe a cada súbdito, también bajo tu torre.",
              "Prioriza los súbditos de cañón: valen más.",
              "Antes de jugar, 5 minutos en Herramienta de práctica solo dando último golpe."]},
    {"clave": "oro", "nombre": "No morir con oro", "roles": None, "defecto": 0.10,
     "por_que": "El oro en el bolsillo no pelea. Morir con él es regalar un objeto.",
     "como": ["Con 1.300 de oro y la oleada empujada, vuelve a base.",
              "Antes de pelear, mira tu oro: si es mucho, primero compra.",
              "Si vas a hacer split, compra antes de salir."]},
    {"clave": "torres", "nombre": "Tirar torres", "roles": {"top"}, "defecto": 0.10,
     "por_que": "Las torres ganan partidas, las kills no.",
     "como": ["Si tu oleada llega a su torre y no hay pelea cerca, golpéala.",
              "Después de ganar un duelo o una pelea, ve a la torre, no a la jungla.",
              "Con Yorick: tus necrófagos y la Doncella tiran torres solos. Úsalos."]},
    # ---- Etapa 2 (Bronce a Plata): tu linea
    {"clave": "vivo_14", "nombre": "Fase de líneas sin morir", "roles": None, "defecto": 0.20,
     "por_que": "Hasta el minuto 14 cada muerte en línea le da a tu rival oro, experiencia y las placas de tu torre. "
                "Llegar al 14 sin morir es la base de ganar tu línea.",
     "como": ["Intercambia solo cuando su habilidad principal esté en enfriamiento.",
              "Vuelve a base con poca vida aunque pierdas una oleada: la oleada se recupera, la muerte no.",
              "Si su jungla no aparece en el minimapa, asume que viene a tu línea."],
     "como_rol": {"support": [
         "No te adelantes a tu tirador sin visión del río.",
         "Contra ganchos y enganches, quédate detrás de tus súbditos aunque no puedas pegar.",
         "Si tu tirador vuelve a base, vuelve con él o quédate bajo la torre."]}},
    {"clave": "cs_rival", "nombre": "No perder el farmeo", "roles": {"top", "mid", "bot"}, "defecto": 0.15,
     "por_que": "La diferencia de CS al minuto 10 es la mejor medida de quién ganó la línea: es oro que tu rival tiene "
                "y tú no. Con 2 o 3 campeones de siempre sabes cuándo puedes farmear y cuándo no.",
     "como": ["Si tu rival te presiona, farmea bajo tu torre: los súbditos llegan igual.",
              "Cuando tu rival vuelva a base o se vaya de la línea, empuja la oleada hasta su torre.",
              "Practica el último golpe bajo torre en la Herramienta de práctica."]},
    # ---- Etapa 3 (Plata a Oro): mirar el mapa
    {"clave": "gank", "nombre": "Que no te ganqueen", "roles": {"top", "mid", "bot", "support"}, "defecto": 0.18,
     "por_que": "En Plata casi todas las muertes en línea son ganks que se podían ver venir. Saber dónde está el jungla "
                "rival es lo que más separa a Oro de Plata.",
     "como": ["Mira el minimapa cada vez que das un último golpe.",
              "Si el jungla rival aparece en una línea, en 30 o 40 segundos puede estar en la tuya.",
              "Si no sabes dónde está y tu oleada está adelantada, retrocede o pon un ward en el río."]},
    {"clave": "vision", "nombre": "Visión", "roles": None, "defecto": 0.12, "niveles": True,
     "por_que": "Desde Oro la visión decide qué pelea tomar y cuál no: saber dónde está el jungla rival no sirve si no "
                "tienes wards. Las metas son las que se ven en Oro a Diamante (dodge.gg).",
     "como": ["Compra un control ward cada vez que vuelvas a base y ponlo en el río.",
              "Usa el ward del amuleto cada vez que esté listo.",
              "Un minuto antes de un dragón o un Barón, pon visión a su alrededor."],
     "como_rol": {"support": [
         "Gasta todas las cargas del objeto de support: un ward guardado no ve nada.",
         "Control ward en cada vuelta a base, y la lente para quitar sus wards antes de los objetivos.",
         "Pon la visión con tu jungla cerca, no solo en el lado enemigo."]}},
    {"clave": "presencia", "nombre": "Llegar a los objetivos", "roles": {"mid", "bot", "support"}, "defecto": 0.15,
     "por_que": "De Plata a Oro se aprende a jugar alrededor de los objetivos: el equipo que llega primero y con más gente "
                "los gana. De support, mid y tirador te toca llegar con tu jungla antes de que salgan (dodge.gg).",
     "como": ["Un minuto antes de que salga el dragón, empuja tu oleada y ve hacia el río.",
              "Si llegan ellos con más gente, no pelees: cambia el objetivo por una torre.",
              "Después de una pelea ganada, ve al objetivo más cercano en vez de volver a farmear."],
     "como_rol": {"support": [
         "Llega con tu jungla al río unos 15 segundos antes de que salga el objetivo.",
         "Pon visión alrededor del objetivo un minuto antes y quita la suya con la lente.",
         "Si tu tirador está empujando, avísale antes de irte."]}},
    # ---- Etapa 4 (Oro a Platino): despues de la linea
    {"clave": "cs_post", "nombre": "Farmear después de la línea", "roles": {"top", "mid", "bot"}, "defecto": 0.15,
     "por_que": "Después de la fase de líneas, los jugadores de Oro dejan de farmear y van detrás de las peleas; los de "
                "Platino siguen farmeando las líneas laterales (7 CS por minuto o más, dodge.gg).",
     "como": ["Si no hay un objetivo en el próximo minuto, ve a la línea lateral que tenga una oleada.",
              "Empuja la oleada y vuelve con tu equipo antes del siguiente objetivo.",
              "Entre oleada y oleada, toma los campamentos de tu lado si tu jungla no los necesita."]},
    {"clave": "tarde", "nombre": "No regalar el final", "roles": None, "defecto": 0.15,
     "por_que": "Después del minuto 25 una muerte puede costar la partida: tu equipo juega con uno menos casi un minuto "
                "y el rival puede hacer Barón o el dragón.",
     "como": ["Después del 25, no camines solo por zonas sin visión.",
              "Si vas a una línea lateral, vuelve antes de que salga el Barón o el dragón.",
              "En las peleas, colócate detrás de tu primera línea."]},
    # ---- Etapa 5 (Platino a Esmeralda): intercambios con ventaja
    {"clave": "oro_rival", "nombre": "Ganar tu línea", "roles": None, "defecto": 0.15,
     "por_que": "En Platino y Esmeralda los intercambios se ganan con información (nivel, objeto, enfriamientos), no "
                "al azar. Llegar al 14 por delante de tu rival es el resultado de intercambiar bien.",
     "como": ["Intercambia cuando gaste su habilidad principal en la oleada o cuando llegues antes a nivel 2, 3 o 6.",
              "Si él tiene ventaja de nivel u objeto, no pelees: farmea.",
              "Cuando vuelva a base, empuja la oleada a su torre o toma una placa."]},
    # ---- Etapa 6 (Esmeralda a Diamante): consistencia
    {"clave": "nota", "nombre": "Consistencia", "roles": None, "defecto": 0.15,
     "por_que": "De Esmeralda a Diamante sube quien juega bien siempre, no quien hace partidas brillantes de vez en "
                "cuando (dodge.gg: consistencia en 50 partidas o más, sin rachas de tilt).",
     "como": ["Juega cada partida con tu misión, también cuando vas perdiendo.",
              "Si terminas enfadado, para: la siguiente sale peor.",
              "Revisa las muertes clave de cada partida antes de buscar otra."]},
]
HAB = {h["clave"]: h for h in HABITOS}


# =============================================================== LECCIONES
# Medir no enseña. Cada habito trae su leccion: el concepto (por que pasa), un ejercicio para practicarlo y que
# mirar en la repeticion. Lo de support va aparte cuando cambia.
LECCIONES = {
    "vivo_10": {
        "concepto": "Casi todas las muertes antes del minuto 10 salen de tres errores. Uno: pegarle al rival cuando él "
                    "tiene más súbditos que tú; sus súbditos te atacan cada vez que lo golpeas y pierdes el intercambio "
                    "aunque juegues bien. Dos: pelear con un nivel menos; en línea individual se llega a nivel 2 con la "
                    "primera oleada y un súbdito de la segunda, y el que llega primero gana ese intercambio. Tres: "
                    "tener la oleada cerca de su torre sin saber dónde está su jungla.",
        "ejercicio": "En tus próximas partidas, antes de cada intercambio cuenta los súbditos: si él tiene más, no "
                     "pegues. Y mira el nivel de los dos antes de pelear.",
        "repeticion": "En cada muerte antes del 10, pausa 10 segundos antes: ¿quién tenía más súbditos?, ¿quién tenía "
                      "más nivel?, ¿la oleada estaba cerca de su torre?, ¿se veía a su jungla en el minimapa?",
        "support": {
            "concepto": "De support, las muertes tempranas salen de tres errores: adelantarte a tus súbditos contra un "
                        "campeón con gancho o enganche, pelear cuando ellos llegan antes a nivel 2 (en la línea de "
                        "abajo se llega con la primera oleada y tres súbditos de la segunda) y quedarte cuando tu "
                        "tirador ya se fue o está sin vida.",
            "ejercicio": "Antes de avanzar, mira dónde está tu tirador y cuántos súbditos tiene cada lado. Si ellos "
                         "van a llegar antes a nivel 2, retrocede hasta que tú también llegues."}},
    "muertes": {
        "concepto": "Una muerte no es solo la kill del rival: son unos 300 de oro para él, la experiencia y el oro "
                    "de los súbditos que pierdes mientras estás muerto, y tu equipo jugando con uno menos. Cuanto más "
                    "avanza la partida, más dura el contador de muerte. Antes de entrar a una pelea hazte tres "
                    "preguntas: ¿cuántos enemigos veo en el minimapa?, ¿tengo mis habilidades y mis hechizos?, ¿qué "
                    "gano si sale bien? Si no ves a los enemigos, están donde tú vas.",
        "ejercicio": "Cada vez que mueras, di en voz alta en una frase por qué moriste antes de reaparecer. Si no "
                     "sabes decirlo, esa es la muerte que tienes que revisar.",
        "repeticion": "Revisa tus muertes con el botón \"Revisar\" y marca la causa. Con 5 revisadas, el coach te dice "
                      "cuál se repite."},
    "solo": {
        "concepto": "Hacia el minuto 14 caen las placas de las torres y los equipos empiezan a moverse juntos. Desde "
                    "ahí, quien camina solo por una zona sin visión se encuentra con dos o tres enemigos. Regla "
                    "práctica: antes de cruzar el río o entrar a su jungla, cuenta cuántos enemigos ves en el "
                    "minimapa. Los que no ves pueden estar donde vas.",
        "ejercicio": "Desde el minuto 14, antes de cruzar el río cuenta en voz alta los enemigos que ves en el "
                     "minimapa. Si ves menos de 3, no cruces sin un aliado.",
        "repeticion": "En cada muerte marcada \"sin tu equipo\", mira 15 segundos antes: ¿a cuántos enemigos veías?, "
                      "¿dónde estaba tu aliado más cercano?, ¿a qué ibas?"},
    "cs10": {
        "concepto": "El farmeo es el oro más seguro del juego: unos 15 súbditos valen lo que una kill. Hasta el minuto "
                    "10 llegan a tu línea unos 100; con 70 ya juegas con más oro que casi todos en rangos bajos. Para "
                    "el último golpe, no ataques al súbdito hasta que tu golpe lo mate. Bajo tu torre: al súbdito "
                    "cuerpo a cuerpo, dos disparos de torre y luego tu golpe; al mago, un golpe tuyo, un disparo de "
                    "torre y otro golpe tuyo.",
        "ejercicio": "El Entrenamiento de CS del coach (pestaña Progreso): 10 minutos en la Herramienta de práctica, "
                     "solo último golpe, sin habilidades. Hazlo antes de tu primera partida del día.",
        "repeticion": "Mira del minuto 2 al 6 y cuenta los súbditos que perdiste. Apunta por qué: atacaste antes de "
                      "tiempo, estabas intercambiando o los mató tu torre."},
    "oro": {
        "concepto": "El oro que llevas encima no hace nada: solo cuenta cuando lo conviertes en objetos. Volver a "
                    "base bien tiene un orden: empuja la oleada entera contra su torre y entonces vuelve; así su torre "
                    "mata tus súbditos mientras compras y pierdes pocos. Si vuelves con la oleada en medio, él la "
                    "empuja contra tu torre y pierdes oro y experiencia.",
        "ejercicio": "Cada vez que tengas 1.300 de oro, tu siguiente tarea es empujar la oleada y volver a base. "
                     "Antes de pulsar B, pregúntate: ¿mi oleada va hacia su torre?",
        "repeticion": "En las muertes con oro sin gastar, retrocede 1 minuto: ¿cuándo pudiste empujar y volver?"},
    "torres": {
        "concepto": "Las torres dan oro a todo tu equipo y abren el mapa. De top, tu presión en una línea lateral "
                    "obliga al rival a mandar a uno o dos a pararte, y tu equipo juega con ventaja en el otro lado. "
                    "El orden: mata la oleada, pega a la torre mientras tus súbditos la reciben, y vete antes de que "
                    "lleguen.",
        "ejercicio": "Después de ganar un intercambio o de que tu rival vuelva a base, empuja y pega a la torre en "
                     "vez de volver tú también.",
        "repeticion": "Busca los momentos en que tu rival no estaba en la línea: ¿pegaste a la torre o te fuiste?"},
    "vivo_14": {
        "concepto": "Dónde está la oleada decide si estás seguro. Cerca de tu torre, su jungla no puede ganquearte y "
                    "tú sí puedes recibir ayuda; cerca de la suya, eres tú el expuesto. Si matas los súbditos más "
                    "rápido que tu rival, la oleada avanza hacia su torre: hazlo solo cuando sepas dónde está su "
                    "jungla o cuando vayas a volver a base. Si no, da solo el último golpe y deja que la oleada "
                    "venga hacia ti.",
        "ejercicio": "Durante la fase de líneas, pregúntate cada minuto: ¿hacia dónde va mi oleada y por qué?",
        "repeticion": "En cada muerte antes del 14: ¿dónde estaba la oleada?, ¿quién la había empujado hasta ahí?",
        "support": {
            "concepto": "De support, tu posición depende de la oleada y de tu tirador. Con la oleada cerca de su "
                        "torre, su jungla puede llegar por el río o por detrás: ahí necesitas un ward en el río o en "
                        "el arbusto del triángulo. Con la oleada en tu torre, tu trabajo es proteger a tu tirador "
                        "mientras farmea, no buscar pelea.",
            "ejercicio": "Cada vez que tu oleada pase del centro de la línea, comprueba que hay un ward en el río. "
                         "Si no lo hay, ponlo o retrocede."}},
    "cs_rival": {
        "concepto": "Ir por debajo en súbditos al minuto 10 es ir por debajo en oro sin que te hayan matado. Pasa por "
                    "dos motivos: te echa de la oleada o vuelves a base en mal momento. Si te presiona, no pelees por "
                    "cada súbdito: deja que la oleada llegue a tu torre y farmea ahí. Y cuando él vuelva a base, "
                    "empuja la oleada entera contra su torre: los súbditos que mate su torre son oro que él pierde.",
        "ejercicio": "En tus próximas partidas, mira el marcador (Tab) al minuto 5 y al 10 y compara tus súbditos con "
                     "los de tu rival.",
        "repeticion": "Busca el momento en que se abrió la diferencia: ¿una vuelta a base tuya, una muerte o te echó "
                      "de la oleada?"},
    "gank": {
        "concepto": "Un gank se ve venir si sabes dónde empezó su jungla. Fíjate qué línea llega tarde o con menos "
                    "vida al inicio: esa ayudó a su jungla, que empezó de ese lado. El primer gank suele llegar entre "
                    "el minuto 2:30 y el 3:30. Si su jungla aparece en otra línea, tienes unos 30 segundos de "
                    "tranquilidad. Si no lo ves y tu oleada está adelantada, estás en peligro.",
        "ejercicio": "Pon un ward en el río hacia el minuto 2:45 y mira el minimapa cada vez que das un último "
                     "golpe. Di en voz alta dónde crees que está su jungla.",
        "repeticion": "En cada muerte con su jungla: ¿dónde lo habías visto por última vez?, ¿tenías ward?, ¿dónde "
                      "estaba tu oleada?"},
    "vision": {
        "concepto": "No puedes decidir bien con el mapa a oscuras. Tu puntuación de visión sube por poner wards y "
                    "por quitar los del rival. La forma más simple de subirla: un control ward en cada vuelta a base "
                    "(cuesta 75 de oro) y usar el amuleto en cuanto esté listo, en vez de guardarlo. El mejor ward es "
                    "el que pones antes de necesitarlo: en el río antes de empujar, cerca del objetivo un minuto antes "
                    "de que salga.",
        "ejercicio": "Regla fija: no salgas de base sin un control ward si tienes 75 de oro, y no dejes el amuleto "
                     "listo más de 30 segundos.",
        "repeticion": "Mira los dos minutos anteriores a cada dragón: ¿había wards tuyos cerca?"},
    "presencia": {
        "concepto": "Los objetivos se ganan antes de que salgan: el equipo que llega primero, con visión y con las "
                    "líneas empujadas, elige cómo pelear. El contador de cada objetivo se ve en el marcador (Tab) y en "
                    "el minimapa. Un minuto antes: empuja tu oleada, vuelve a base si lo necesitas y camina hacia el "
                    "objetivo con tu equipo. Llegar tarde y de uno en uno es como más se pierden.",
        "ejercicio": "Cuando falte 1 minuto para un dragón o un Barón, dilo en voz alta y haz en orden: empujar "
                     "oleada, ir hacia el objetivo, poner visión.",
        "repeticion": "En cada objetivo donde no estabas: ¿qué hacías un minuto antes?, ¿podías haber llegado?"},
    "cs_post": {
        "concepto": "Después de la fase de líneas, mucha gente deja de farmear y se pasea entre peleas. Las oleadas "
                    "de las líneas laterales siguen dando oro y experiencia. Rutina: si no hay objetivo en el próximo "
                    "minuto, ve a la línea que tenga una oleada grande, mátala y vuelve con tu equipo. No pases del "
                    "río sin visión, y no farmees una oleada lejana cuando el objetivo sale en 30 segundos.",
        "ejercicio": "Después del minuto 14, cada vez que no sepas qué hacer, mira dónde hay una oleada grande y ve a "
                     "por ella.",
        "repeticion": "Mira del minuto 15 al 20 y cuenta el tiempo que pasaste sin farmear ni pelear."},
    "tarde": {
        "concepto": "Al final de la partida el contador de muerte es muy largo, y con uno menos el rival puede hacer "
                    "Barón, dragón o terminar. Por eso no morir vale más que cualquier jugada. Camina con tu equipo, "
                    "por zonas con visión, y en las peleas espera a que entre tu primera línea antes de entrar tú.",
        "ejercicio": "Después del minuto 25, antes de separarte de tu equipo mira el contador del Barón y del dragón: "
                     "si falta menos de un minuto, no te vayas.",
        "repeticion": "En cada muerte después del 25: ¿dónde estaba tu equipo?, ¿qué hizo el rival mientras estabas "
                      "muerto?"},
    "oro_rival": {
        "concepto": "Un intercambio se gana antes de empezarlo. Las ventanas buenas son: él acaba de gastar su "
                    "habilidad principal, tú tienes más súbditos, o acabas de llegar a nivel 2, 3 o 6 antes que él, o "
                    "vuelves de base con un objeto que él no tiene. Fuera de esas ventanas, farmea. Y cada ventaja "
                    "se convierte en oro: placas, súbditos que él pierde o una vuelta a base mejor que la suya.",
        "ejercicio": "Usa tu libreta de enfrentamientos: al terminar cada partida, escribe cuál es la habilidad que "
                     "tienes que esperar contra ese campeón.",
        "repeticion": "Mira tus intercambios de los minutos 2 a 8: ¿en cuáles tenías una ventaja antes de empezar?"},
    "nota": {
        "concepto": "A partir de aquí no falta saber qué hacer, sino hacerlo todas las partidas. Los que suben "
                    "cuidan la rutina: calientan, juegan sus campeones, paran cuando se enfadan y revisan sus errores "
                    "aunque hayan ganado. Una partida mala suelta no importa; tres seguidas por tilt, sí.",
        "ejercicio": "Antes de cada sesión: calentamiento de CS. Después de cada partida: marca tu ánimo y revisa "
                     "tus 2 muertes clave antes de buscar otra.",
        "repeticion": "Compara una partida con nota alta y una con nota baja de la misma semana: ¿qué cambió antes del "
                      "minuto 10?"},
}


def leccion_habito(clave, rol=""):
    base = LECCIONES.get(clave)
    if not base:
        return None
    out = {k: base[k] for k in ("concepto", "ejercicio", "repeticion")}
    out.update(base.get(rol) or {})
    return out


def como_habito(clave, rol=""):
    """Como cumplir la mision, con consejos propios del rol si los hay (support no farmea, top hace split...)."""
    h = HAB.get(clave) or {}
    return (h.get("como_rol") or {}).get(rol) or h.get("como") or []


def _niveles(clave, rol=""):
    """Metas por nivel de los habitos que suben de dificultad (CS, muertes, vision)."""
    if clave == "cs10":
        return CONFIG["cs10_niveles"]
    if clave == "muertes":
        return CONFIG["muertes_niveles"]
    if clave == "vision":
        return CONFIG["vision_niveles"]["support" if rol == "support" else "otros"]
    return [None]


def _meta(clave, nivel=0, rol=""):
    nv = _niveles(clave, rol)
    return nv[min(nivel, len(nv) - 1)]


def _meta_cs10(nivel):
    return _meta("cs10", nivel)


def regla_habito(clave, nivel=0, ctx=None):
    ctx = ctx or {}
    rol = ctx.get("rol") or ctx.get("rol_main") or ""
    fm = CONFIG["fin_fase_lineas_min"]
    if clave == "vision":
        return (f"Puntuación de visión de {_dec(_meta('vision', nivel, rol), 2)} por minuto o más"
                + (" (support)" if rol == "support" else ""))
    return {
        "vivo_10": "0 muertes antes del minuto 10",
        "muertes": f"{_meta('muertes', nivel)} muertes o menos en toda la partida",
        "solo": f"Desde el minuto {fm}, 0 muertes sin tu equipo en la pelea",
        "oro": f"Nunca mueras con {_miles(CONFIG['oro_sin_gastar'])} de oro o más sin gastar",
        "cs10": f"{_meta_cs10(nivel)} CS o más al minuto 10",
        "torres": f"{CONFIG['torres_habito_min']} de daño a torres por minuto",
        "vivo_14": f"0 muertes antes del minuto {fm}",
        "cs_rival": "Al minuto 10, tantos CS como tu rival o más",
        "gank": f"0 muertes antes del minuto {fm} con el jungla rival en la pelea",
        "presencia": "Estar en la mitad o más de los dragones, Heraldos y Barones",
        "cs_post": f"{_dec(CONFIG['cs_post_min'])} CS por minuto o más entre el minuto {fm} y el 25",
        "tarde": "Como mucho 1 muerte después del minuto 25",
        "oro_rival": f"Llegar al minuto {fm} con más oro que tu rival",
        "nota": f"Nota del coach de {_dec(CONFIG['nota_consistencia'])} o más",
    }.get(clave, "")


def evaluar_habito(clave, dh, nivel=0, ctx=None):
    """Devuelve (aplica, cumplido, evidencia) para una partida."""
    h = HAB.get(clave)
    if not h:
        return False, None, ""
    ctx = ctx or {}
    rol = dh.get("rol", "")
    if h["roles"] and rol not in h["roles"]:
        return False, None, "No aplica al rol que jugaste."
    mins = dh.get("mins") or 1
    tl = dh.get("con_tl")
    if clave == "vivo_10":
        if not tl:
            return False, None, "Sin línea de tiempo."
        m = dh["muertes_10"]
        if not m:
            return True, True, "Llegaste al minuto 10 sin morir."
        txt = ", ".join(f"{x['min']} ({x['killer']}" + (f" y {x['n'] - 1} más)" if x["n"] > 1 else ")") for x in m)
        return True, False, f"Moriste en el {txt}."
    if clave == "muertes":
        lim = _meta("muertes", nivel)
        return True, dh["d"] <= lim, f"{dh['d']} muertes (máximo {lim})."
    if clave in NUEVOS_EVAL:
        return NUEVOS_EVAL[clave](dh, nivel, rol, mins, tl)
    if clave == "solo":
        if not tl or "solo_14" not in dh:
            return False, None, "Sin línea de tiempo."
        s = dh["solo_14"]
        if s:
            txt = ", ".join(f"{x['min']} ({x['killer']}" + (f" y {x['n'] - 1} más)" if x["n"] > 1 else ")") for x in s)
            return True, False, (f"Moriste sin tu equipo en el {txt}: nadie de tu equipo mató, asistió ni murió "
                                 f"{VENTANA_PELEA_S} segundos antes o después.")
        if mins < 20:
            return False, None, "La partida terminó antes del minuto 20: no da para medirlo."
        n14 = dh.get("d_14", 0)
        return True, True, (f"No moriste desde el minuto {CONFIG['fin_fase_lineas_min']}." if not n14 else
                            f"Tu muerte desde el minuto {CONFIG['fin_fase_lineas_min']} fue en una pelea con tu equipo."
                            if n14 == 1 else
                            f"Tus {n14} muertes desde el minuto {CONFIG['fin_fase_lineas_min']} fueron en peleas "
                            "con tu equipo.")
    if clave == "oro":
        if not tl:
            return False, None, "Sin línea de tiempo."
        om = dh["oro_muerto"]
        if not om:
            return True, True, "Ninguna muerte con oro sin gastar."
        return True, False, "Moriste con oro sin gastar en el " + ", ".join(
            f"{x['min']} (~{_miles(x['oro'])})" for x in om) + "."
    if clave == "cs10":
        if dh.get("cs10") is None:
            return False, None, "Sin línea de tiempo."
        meta = _meta_cs10(nivel)
        return True, dh["cs10"] >= meta, f"{dh['cs10']} CS al minuto 10 (meta {meta})."
    if clave == "torres":
        meta = CONFIG["torres_habito_min"] * mins
        return True, dh["torres"] >= meta, f"{_miles(dh['torres'])} de daño a torres (meta {_miles(meta)})."
    return False, None, ""


# ---- Evaluacion de los habitos de las etapas 2 a 6
def _lista_muertes(xs):
    return ", ".join(f"{x['min']} ({x['killer']}" + (f" y {x['n'] - 1} más)" if x["n"] > 1 else ")") for x in xs)


def _ev_vivo_14(dh, nivel, rol, mins, tl):
    if not tl or "muertes_14" not in dh:
        return False, None, "Sin línea de tiempo."
    if dh["muertes_14"]:
        return True, False, f"Moriste en el {_lista_muertes(dh['muertes_14'])}."
    if mins < CONFIG["fin_fase_lineas_min"]:
        return False, None, "La partida terminó antes del minuto 14."
    return True, True, f"Llegaste al minuto {CONFIG['fin_fase_lineas_min']} sin morir."


def _ev_cs_rival(dh, nivel, rol, mins, tl):
    d = dh.get("cs10_diff")
    if d is None or dh.get("cs10") is None:
        return False, None, "Sin datos de tu rival al minuto 10."
    return True, d >= 0, f"Al minuto 10: tú {dh['cs10']} CS, tu rival {dh['cs10'] - d}."


def _ev_gank(dh, nivel, rol, mins, tl):
    if not tl or "muertes_gank" not in dh:
        return False, None, "Sin línea de tiempo."
    if not dh.get("jg_rival"):
        return False, None, "No se pudo saber quién era el jungla rival."
    if dh["muertes_gank"]:
        return True, False, f"Muertes con su jungla en la pelea: {_lista_muertes(dh['muertes_gank'])}."
    if mins < CONFIG["fin_fase_lineas_min"]:
        return False, None, "La partida terminó antes del minuto 14."
    return True, True, f"Ninguna muerte con su jungla en la pelea antes del minuto {CONFIG['fin_fase_lineas_min']}."


def _ev_vision(dh, nivel, rol, mins, tl):
    v = dh.get("vision_min")
    if v is None:
        return False, None, "El cliente no dio tu puntuación de visión."
    meta = _meta("vision", nivel, rol)
    return True, v >= meta, f"Puntuación de visión: {_dec(v, 2)} por minuto (meta {_dec(meta, 2)})."


def _ev_presencia(dh, nivel, rol, mins, tl):
    obj = dh.get("objetivos")
    if not tl or obj is None:
        return False, None, "Sin línea de tiempo."
    if len(obj) < 2:
        return False, None, "Hubo menos de 2 objetivos grandes: no da para medirlo."
    k = sum(1 for o in obj if o["ok"])
    falto = [o for o in obj if not o["ok"]]
    txt = f"Estuviste en {k} de {len(obj)} objetivos"
    if falto:
        txt += ". No estabas en " + ", ".join(f"{o['nombre']} del {o['min']}" for o in falto[:3])
    return True, k * 2 >= len(obj), txt + "."


def _ev_cs_post(dh, nivel, rol, mins, tl):
    v = dh.get("cs_post")
    if v is None:
        return False, None, "La partida terminó antes del minuto 20 o no hay línea de tiempo."
    meta = CONFIG["cs_post_min"]
    return True, v >= meta, (f"{_dec(v)} CS por minuto entre el minuto {CONFIG['fin_fase_lineas_min']} y el "
                             f"{dh.get('cs_post_hasta', 25)} (meta {_dec(meta)}).")


def _ev_tarde(dh, nivel, rol, mins, tl):
    if not tl or "d_25" not in dh:
        return False, None, "Sin línea de tiempo."
    n = dh["d_25"]
    if n <= 1 and mins < 28:
        return False, None, "La partida terminó antes del minuto 28: no da para medirlo."
    return True, n <= 1, f"{n} {'muerte' if n == 1 else 'muertes'} después del minuto 25 (máximo 1)."


def _ev_oro_rival(dh, nivel, rol, mins, tl):
    d = dh.get("oro14_diff")
    if d is None:
        return False, None, "Sin datos de tu rival al minuto 14."
    return True, d >= 0, f"Al minuto 14 ibas {_signo(d, True)} de oro contra tu rival."


def _ev_nota(dh, nivel, rol, mins, tl):
    n = dh.get("nota")
    if n is None:
        return False, None, "Sin nota."
    meta = CONFIG["nota_consistencia"]
    return True, n >= meta, f"Nota {_dec(n)} (meta {_dec(meta)})."


NUEVOS_EVAL = {"vivo_14": _ev_vivo_14, "cs_rival": _ev_cs_rival, "gank": _ev_gank, "vision": _ev_vision,
               "presencia": _ev_presencia, "cs_post": _ev_cs_post, "tarde": _ev_tarde,
               "oro_rival": _ev_oro_rival, "nota": _ev_nota}


def _pool(partidas):
    pool = {}
    for p in partidas:
        key = (p["yo"]["campeon_id"], p.get("rol", ""))
        s = pool.setdefault(key, {"campeon": p["yo"]["campeon"], "campeon_id": p["yo"]["campeon_id"],
                                  "rol": p.get("rol", ""), "rol_txt": ROL_TXT.get(p.get("rol", ""), ""),
                                  "n": 0, "v": 0, "suma_nota": 0.0})
        s["n"] += 1
        s["v"] += 1 if p["victoria"] else 0
        s["suma_nota"] += p["veredicto"]["nota"]
    lista = []
    for s in pool.values():
        lista.append({**{k: v for k, v in s.items() if k != "suma_nota"}, "d": s["n"] - s["v"],
                      "wr": round(100 * s["v"] / s["n"]), "nota": round(s["suma_nota"] / s["n"], 1)})
    lista.sort(key=lambda s: (-s["n"], -s["nota"]))
    return lista


def _wr_validas(lst):
    """% de victorias sin contar las partidas con un AFK en tu equipo (no se podian ganar)."""
    lst = [p for p in lst if not p["datos_h"].get("afk_aliado")]
    return round(100 * sum(1 for p in lst if p["victoria"]) / len(lst)) if lst else None


def _n_validas(lst):
    return sum(1 for p in lst if not p["datos_h"].get("afk_aliado"))


def _recientes(partidas):
    partidas = sorted(partidas, key=lambda p: p.get("creacion") or 0)
    return [p for p in partidas if p.get("datos_h")][-CONFIG["diag_partidas"]:]


def _fila_habito(recientes, h, nivel, ctx, orden=0, rol_main=""):
    """Como vas en un habito (a un nivel) en tus ultimas partidas."""
    vent, nec = CONFIG["ventana_dominio"], CONFIG["cumplidas_para_dominar"]
    ev = []
    for p in recientes:
        aplica, ok, evid = evaluar_habito(h["clave"], p["datos_h"], nivel, ctx)
        if aplica:
            ev.append((p, ok, evid))
    n = len(ev)
    si = [p for p, ok, _ in ev if ok]
    no = [p for p, ok, _ in ev if not ok]
    ult = ev[-vent:]
    dominado = len(ult) >= vent and sum(1 for _, ok, _ in ult if ok) >= nec
    kk = min(_n_validas(si), _n_validas(no))
    imp_datos = ((_wr_validas(si) - _wr_validas(no)) / 100
                 if _n_validas(si) >= 4 and _n_validas(no) >= 4 else None)
    # Tu diferencia de victorias en ~30 partidas es ruidosa y exagera (en las partidas que ya vas perdiendo mueres
    # mas): pesa mas la prioridad que da la investigacion (defecto) que esa diferencia.
    imp = h["defecto"] if imp_datos is None else (imp_datos * kk + h["defecto"] * 15) / (kk + 15)
    costo = (len(no) / n) * max(0.02, imp) if n else h["defecto"]
    return {
        "clave": h["clave"], "nombre": h["nombre"], "nivel": nivel,
        "regla": regla_habito(h["clave"], nivel, ctx),
        "orden": orden, "n": n, "k": len(si), "tasa": round(100 * len(si) / n) if n else None,
        "wr_si": _wr_validas(si), "n_si": _n_validas(si), "wr_no": _wr_validas(no), "n_no": _n_validas(no),
        "datos_wr": imp_datos is not None, "dominado": dominado,
        "ult_ok": sum(1 for _, ok, _ in ult if ok), "ult_n": len(ult),
        "aplica_main": (not h["roles"]) or (rol_main in h["roles"]),
        "costo": round(costo, 4),
        "progreso": [{"id": p["id"], "ok": ok, "campeon": p["yo"]["campeon"], "campeon_id": p["yo"]["campeon_id"],
                      "victoria": p["victoria"], "fecha": p["fecha"], "evid": evid} for p, ok, evid in ev[-10:]],
    }


def diagnostico(partidas, niveles, rol_main=None):
    recientes = _recientes(partidas)
    if not rol_main:
        roles = [p.get("rol") for p in recientes[-20:] if p.get("rol")]
        rol_main = Counter(roles).most_common(1)[0][0] if roles else ""
    lista = _pool(recientes)
    del_rol = [s for s in lista if s["rol"] == rol_main]
    ctx = {"rol_main": rol_main, "rol": rol_main, "campeones": [s["campeon"] for s in del_rol[:3]],
           "campeones_ids": [s["campeon_id"] for s in del_rol[:3]]}
    habs = [_fila_habito(recientes, h, niveles.get(h["clave"], 0), ctx, orden, rol_main)
            for orden, h in enumerate(HABITOS)]
    por_rol = {}
    for s_ in lista:
        if s_["rol"] and s_["rol"] not in por_rol:
            por_rol[s_["rol"]] = s_
    recomendado = del_rol[0] if del_rol else (lista[0] if lista else None)
    return {"rol": rol_main, "habitos": habs, "n": len(recientes), "ctx": ctx,
            "pool": {"recomendado": recomendado, "lista": lista[:6], "por_rol": por_rol,
                     "todos": lista}}


def _por_que(h):
    base = HAB[h["clave"]]["por_que"]
    if h["datos_wr"] and h["n_si"] >= 8 and h["n_no"] >= 8:
        # con menos de 8 partidas por lado, esos porcentajes son ruido: no se muestran
        return (f"En tus últimas {h['n']} partidas lo cumpliste {h['k']} "
                f"{'vez' if h['k'] == 1 else 'veces'}. Cuando lo cumples ganas el {h['wr_si']}% "
                f"({h['n_si']} partidas); cuando no, el {h['wr_no']}% ({h['n_no']}), sin contar partidas con un "
                f"AFK en tu equipo. {base}")
    if h["n"]:
        return f"Lo cumpliste en {h['k']} de tus últimas {h['n']} partidas. {base}"
    return base


# =============================================================== ALMACEN
class Almacen:
    def __init__(self):
        self.lock = threading.RLock()
        self.d = {"version": 2, "jugador": None, "rango": None, "rango_hist": [],
                  "partidas": {}, "animo": {}, "avisos": {}, "misiones": {},
                  "plan": {"foco": None, "niveles": {}, "dominados": []}}
        try:
            data = json.loads(HIST.read_text(encoding="utf-8"))
            self.d.update(data)
        except Exception:
            pass
        self.d.setdefault("misiones", {})
        self.d.setdefault("plan", {"foco": None, "niveles": {}, "dominados": []})
        # La version 24 trae el tema oscuro como principal: se pone una sola vez; despues manda lo que elijas tu.
        if self.d.get("tema_v") != 24:
            self.d["tema"], self.d["tema_v"] = "oscuro", 24

    def guardar(self):
        with self.lock:
            tmp = HIST.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, HIST)

    def rango_txt(self):
        return (self.d.get("rango") or {}).get("texto", "")

    def reanalizar(self, rec):
        cambios = 0
        for p in self.d["partidas"].values():      # las colas que cuentan para "hoy" pueden cambiar en CONFIG
            ca = p.get("cola_id") in CONFIG["colas_anti_racha"]
            if p.get("cuenta_anti") != ca:
                p["cuenta_anti"] = ca
                cambios += 1
        for f in CRUDO.glob("*.json"):
            gid = f.stem
            actual = self.d["partidas"].get(gid)
            if actual and actual.get("v") == ANALISIS_V:
                continue
            try:
                crudo = json.loads(f.read_text(encoding="utf-8"))
                an = analizar(crudo["juego"], crudo.get("timeline"), crudo.get("puuid"), rec, self.rango_txt())
                if an:
                    self.d["partidas"][gid] = an
                    cambios += 1
            except Exception as e:
                log(f"No pude analizar {gid}: {e}")
        if cambios:
            self.guardar()
        return cambios


# =============================================================== ROLES Y CAMPEONES
_REC = {"rec": None}          # para poner nombre a campeones sin partidas (lo fija main)


def _nombre_campeon(cid):
    conocidos = {83: "Yorick", 44: "Taric", 134: "Syndra"}
    rec = _REC["rec"]
    nombre = rec.campeon(cid) if rec else ""
    return nombre if nombre and not nombre.startswith("Campeón ") else conocidos.get(cid, nombre or f"Campeón {cid}")


def _stats_rol(ps, rol):
    lst = [p for p in ps if p.get("rol") == rol and not (p.get("datos_h") or {}).get("afk_aliado")]
    n = len(lst)
    v = sum(1 for p in lst if p["victoria"])
    nota = _prom([p["veredicto"]["nota"] for p in lst])
    return {"n": n, "v": v, "wr": round(100 * v / n) if n else None,
            "nota": round(nota, 1) if nota is not None else None}


def _puntaje_rol(s, i, total, base_wr, base_nota):
    """Tu % de victorias y tu nota en el rol, comparados con tu media (con pocas partidas pesa tu media: un rol sin
    partidas no es mejor por no tener derrotas), un poco de experiencia y, para desempatar, el orden en que dijiste
    que te gustan los roles."""
    k = 8
    wr = (s["v"] + base_wr * k) / (s["n"] + k)
    nota = ((s["nota"] if s["nota"] is not None else base_nota) * s["n"] + base_nota * k) / (s["n"] + k)
    return 100 * wr + 3 * (nota - base_nota) + 0.2 * min(s["n"], 30) + 0.5 * (total - i)


def pool_rol(partidas, rol, maximo):
    """Tus campeones para un rol: primero el que dijiste que te gusta, luego los que mejor te van (3+ partidas)."""
    pref = [c for c in CONFIG["campeones_preferidos"].get(rol) or []]
    por = {}
    for p in sorted(partidas, key=lambda x: x.get("creacion") or 0)[-120:]:
        if p.get("rol") != rol:
            continue
        x = por.setdefault(p["yo"]["campeon_id"], {"n": 0, "v": 0, "nombre": p["yo"]["campeon"]})
        x["n"] += 1
        x["v"] += 1 if p["victoria"] else 0
    otros = sorted([c for c, x in por.items() if x["n"] >= 3 and c not in pref],
                   key=lambda c: -((por[c]["v"] + 3) / (por[c]["n"] + 6) + 0.005 * min(por[c]["n"], 20)))
    return [{"id": c, "nombre": (por.get(c) or {}).get("nombre") or _nombre_campeon(c),
             "n": (por.get(c) or {}).get("n", 0), "v": (por.get(c) or {}).get("v", 0)}
            for c in (pref + otros)[:maximo]]


def elegir_roles(partidas, previo=None):
    """El coach elige tu rol principal y el secundario (nunca jungla) con tus numeros. Los revisa cada N partidas
    y solo cambia un rol si otro te va claramente mejor: cambiar de rol es empezar de cero."""
    permitidos = CONFIG["roles_permitidos"]
    analizadas = [p for p in partidas if p.get("datos_h")]
    total = len(analizadas)
    ultimas = sorted([p for p in analizadas if p.get("rol") in permitidos],
                     key=lambda p: p.get("creacion") or 0)[-60:]
    stats = {r: _stats_rol(ultimas, r) for r in permitidos}
    n_tot = sum(stats[r]["n"] for r in permitidos)
    base_wr = sum(stats[r]["v"] for r in permitidos) / n_tot if n_tot else 0.5
    base_nota = (sum((stats[r]["nota"] or 0) * stats[r]["n"] for r in permitidos) / n_tot) if n_tot else 5.0
    punt = {r: _puntaje_rol(stats[r], i, len(permitidos), base_wr, base_nota) for i, r in enumerate(permitidos)}
    # Un rol solo se puede elegir si ya lo jugaste lo suficiente: uno sin partidas no pasa por delante de uno
    # que ya juegas. Si no llegan a dos, se completa con el orden en que dijiste que te gustan.
    minimo = CONFIG["min_partidas_rol"]
    con_datos = [r for r in permitidos if stats[r]["n"] >= minimo]
    # Los que aun no llegan al minimo van detras y ordenados por partidas jugadas (4 partidas pesan mas que 0);
    # a igualdad, por el orden en que dijiste que te gustan.
    orden = (sorted(con_datos, key=lambda r: -punt[r]) +
             sorted([r for r in permitidos if r not in con_datos], key=lambda r: (-stats[r]["n"], permitidos.index(r))))
    if previo and previo.get("principal") in permitidos and previo.get("secundario") in permitidos:
        actuales = [previo["principal"], previo["secundario"]]
        sin_base = [r for r in actuales if r not in con_datos]
        nuevos = list(actuales)
        # Un rol elegido sin partidas suficientes (por ejemplo, el que se puso antes de importar tu historial) se
        # cambia ya por cualquier otro que hayas jugado mas; y el principal es siempre el que mas respaldo tiene.
        for r in sorted(sin_base, key=lambda r: stats[r]["n"]):
            cand = next((c for c in orden if c not in nuevos and stats[c]["n"] > stats[r]["n"]), None)
            if cand:
                nuevos[nuevos.index(r)] = cand
        if sin_base:
            nuevos.sort(key=orden.index)
        if nuevos != actuales:
            elegidos, n_al, ts = nuevos, total, int(time.time() * 1000)
        elif total - (previo.get("n_al_elegir") or 0) < CONFIG["revisar_roles_cada"]:
            elegidos, n_al, ts = actuales, previo.get("n_al_elegir") or 0, previo.get("ts")
        else:
            nuevos = list(actuales)
            for cand in orden:
                if cand in nuevos or cand not in con_datos:
                    continue
                peor = min(nuevos, key=lambda r: punt[r])
                if punt[cand] - punt[peor] >= 5:
                    nuevos[nuevos.index(peor)] = cand
            nuevos.sort(key=lambda r: -punt[r])
            elegidos, n_al = nuevos, total
            ts = previo.get("ts") if nuevos == actuales else int(time.time() * 1000)
    else:
        elegidos, n_al, ts = orden[:2], total, int(time.time() * 1000)
    if sum(stats[r]["n"] for r in permitidos) < 10:
        motivo = ("Todavía hay pocas partidas tuyas por rol, así que el coach empieza por los roles y campeones que "
                  "más te gustan y los revisa con tus números cada " + str(CONFIG["revisar_roles_cada"]) + " partidas.")
    else:
        motivo = "Con tus últimas partidas, sin contar las que tuvieron un AFK: " + "; ".join(
            f"{ROL_TXT[r]} {stats[r]['n']} partidas, {stats[r]['wr']}% de victorias, nota {_dec(stats[r]['nota'])}"
            if stats[r]["n"] else f"{ROL_TXT[r]} sin partidas" for r in orden) + "."
    return {"principal": elegidos[0], "secundario": elegidos[1], "n_al_elegir": n_al, "ts": ts,
            "principal_txt": ROL_TXT[elegidos[0]], "secundario_txt": ROL_TXT[elegidos[1]],
            "stats": stats, "motivo": motivo,
            "revisa_en": max(0, n_al + CONFIG["revisar_roles_cada"] - total),
            "pools": {r: pool_rol(partidas, r, 3 if r == elegidos[0] else 2) for r in permitidos}}


# =============================================================== RUTA POR ETAPAS
# Que aprender en cada salto de rango (dodge.gg, guias 2026 de Hierro a Oro y de Oro a Diamante):
# Hierro-Bronce: CS y morir menos | Bronce-Plata: pool de campeones y oleadas | Plata-Oro: mapa y prioridad de
# objetivos | Oro-Platino: CS despues de la linea y lineas laterales | Platino-Esmeralda: intercambios con ventaja
# | Esmeralda-Diamante: consistencia en 50+ partidas sin romperte.
# Cada etapa pide habitos (a un nivel). Se avanza cuando los dominas (4 de tus ultimas 5 partidas).
ETAPAS = [
    {"id": 1, "nombre": "Sobrevivir y farmear", "rango": "Hierro a Bronce",
     "que": "Morir menos y farmear. Es lo que más separa a Hierro de Bronce.",
     "req": [("vivo_10", 0), ("muertes", 0), ("solo", 0), ("oro", 0), ("cs10", 1)]},
    {"id": 2, "nombre": "Ganar tu línea", "rango": "Bronce a Plata",
     "que": "Jugar siempre tus mismos campeones y ganar la línea: 70 CS al minuto 10, no perder el farmeo contra "
            "tu rival y llegar al 14 sin morir.",
     "req": [("vivo_14", 0), ("cs10", 2), ("cs_rival", 0), ("muertes", 1)]},
    {"id": 3, "nombre": "Mirar el mapa", "rango": "Plata a Oro",
     "que": "Saber dónde está el jungla rival, tener visión y, de support, mid y tirador, llegar a los objetivos con "
            "tu jungla.",
     "req": [("gank", 0), ("vision", 0), ("presencia", 0)]},
    {"id": 4, "nombre": "Después de la línea", "rango": "Oro a Platino",
     "que": "Seguir farmeando las líneas laterales después del minuto 14, de top presionar torres, y no regalar "
            "muertes al final.",
     "req": [("cs_post", 0), ("torres", 0), ("vision", 1), ("tarde", 0)]},
    {"id": 5, "nombre": "Intercambios con ventaja", "rango": "Platino a Esmeralda",
     "que": "Intercambiar solo con ventaja (nivel, objeto o enfriamiento) y llegar al minuto 14 por delante de tu "
            "rival.",
     "req": [("oro_rival", 0)]},
    {"id": 6, "nombre": "Consistencia", "rango": "Esmeralda a Diamante",
     "que": "Jugar bien todas las partidas, no solo algunas: nota de 6,5 o más de forma constante y sin rachas "
            "de tilt.",
     "req": [("nota", 0)]},
]


def _req_aplica(clave, rol):
    roles = HAB[clave]["roles"]
    return (not roles) or (rol in roles)


def _hecho(plan, clave, nivel):
    """Si ese habito, a ese nivel, ya lo dominaste."""
    if HAB.get(clave, {}).get("niveles") and (plan.get("niveles") or {}).get(clave, 0) > nivel:
        return True
    return any(d.get("clave") == clave and (d.get("nivel") or 0) >= nivel for d in plan.get("dominados") or [])


def etapa_actual(plan, rol_main):
    """La primera etapa con algo pendiente para tu rol principal."""
    for i, e in enumerate(ETAPAS):
        pend = [(c, n) for c, n in e["req"] if _req_aplica(c, rol_main) and not _hecho(plan, c, n)]
        if pend:
            return i, pend
    return len(ETAPAS) - 1, []


def _registrar_dominio(plan, clave, nivel, rol_main, estrellas=None, partidas=None, ya=False):
    plan["dominados"].append({"clave": clave, "nombre": HAB[clave]["nombre"], "nivel": nivel,
                              "regla": regla_habito(clave, nivel, {"rol": rol_main}),
                              "estrellas": estrellas, "partidas": partidas, "ya": ya,
                              "ts": int(time.time() * 1000)})
    nv = plan.setdefault("niveles", {})
    if HAB[clave].get("niveles") and nivel + 1 < len(_niveles(clave, rol_main)) and nv.get(clave, 0) <= nivel:
        nv[clave] = nivel + 1


# =============================================================== PLAN
def plan_actual(alm):
    """Tu ruta por etapas. El coach elige tus roles y UN foco dentro de tu etapa; lo cambia solo cuando lo dominas.
    Lo que ya haces bien cuenta como dominado (no te hace repetir lo que ya sabes) y, si un fundamento se te cae,
    vuelve como repaso."""
    with alm.lock:
        plan = alm.d["plan"]
        niveles = plan.setdefault("niveles", {})
        plan.setdefault("dominados", [])
        partidas = list(alm.d["partidas"].values())
        cambio = False
        ahora = int(time.time() * 1000)
        for x in plan["dominados"]:              # arregla logros guardados como "dominado en 0 partidas"
            if not x.get("ya") and not x.get("partidas"):
                x.update(ya=True, estrellas=None, partidas=None)
                cambio = True

        # 1) Tus roles y tus campeones
        roles = elegir_roles(partidas, plan.get("roles"))
        guardar_roles = {k: roles[k] for k in ("principal", "secundario", "n_al_elegir", "ts")}
        if guardar_roles != plan.get("roles"):
            plan["roles"] = guardar_roles
            cambio = True
        rol_main = roles["principal"]
        ctx = {"rol_main": rol_main, "rol": rol_main}
        recientes = _recientes(partidas)
        vent = CONFIG["ventana_dominio"]

        # 2) Tu foco: si ya lo dominaste, queda registrado con sus estrellas
        foco = plan.get("foco")
        if foco and (foco.get("manual") or foco.get("clave") not in HAB):
            foco, cambio = None, True
        if foco and "nivel" not in foco:
            foco["nivel"] = niveles.get(foco["clave"], 0)
        if foco:
            ff = _fila_habito(recientes, HAB[foco["clave"]], foco["nivel"], ctx, rol_main=rol_main)
            if ff["dominado"]:
                if not foco.get("repaso") and not _hecho(plan, foco["clave"], foco["nivel"]):
                    n_desde = sum(1 for p in partidas if p.get("datos_h") and (p.get("creacion") or 0) >= foco.get("desde", 0)
                                  and evaluar_habito(foco["clave"], p["datos_h"], foco["nivel"], ctx)[0])
                    if n_desde:
                        est = 3 if n_desde <= vent else 2 if n_desde <= vent + 3 else 1
                        _registrar_dominio(plan, foco["clave"], foco["nivel"], rol_main, est, n_desde)
                    else:        # ya lo cumplias antes de que fuera tu foco: no es un logro de "0 partidas"
                        _registrar_dominio(plan, foco["clave"], foco["nivel"], rol_main, ya=True)
                foco, cambio = None, True

        # 3) Lo que ya cumples de forma constante cuenta como dominado
        for _ in range(12):
            idx, pend = etapa_actual(plan, rol_main)
            nuevo = False
            for c, n in pend:
                if foco and foco["clave"] == c:
                    continue
                if _fila_habito(recientes, HAB[c], n, ctx, rol_main=rol_main)["dominado"]:
                    _registrar_dominio(plan, c, n, rol_main, ya=True)
                    nuevo = cambio = True
            if not nuevo:
                break
        idx, pend = etapa_actual(plan, rol_main)

        # 4) Si no hay foco (o ya no aplica a tu rol principal), el coach elige: lo pendiente de tu etapa o un
        #    fundamento que se te cayo (2 o menos de tus ultimas 5)
        if foco and not _req_aplica(foco["clave"], rol_main):
            foco, cambio = None, True
        if not foco:
            cands = []
            for c, n in pend:
                f = _fila_habito(recientes, HAB[c], n, ctx, rol_main=rol_main)
                cands.append((f["costo"], -f["orden"], c, n, False))
            for e in ETAPAS[:idx + 1]:
                for c, n in e["req"]:
                    if _req_aplica(c, rol_main) and _hecho(plan, c, n):
                        f = _fila_habito(recientes, HAB[c], n, ctx, rol_main=rol_main)
                        if f["ult_n"] >= vent and f["ult_ok"] <= 2:
                            # un fundamento que se cae va primero: se mide con tus ultimas partidas, no con las 30
                            cands.append(((1 - f["ult_ok"] / f["ult_n"]) * HAB[c]["defecto"] * 1.3,
                                          -f["orden"], c, n, True))
            if cands:
                _, _, c, n, rep = max(cands, key=lambda x: (x[0], x[1]))
                foco, cambio = {"clave": c, "nivel": n, "desde": ahora, "repaso": rep}, True
        plan["foco"] = foco
        if plan.get("etapa") != ETAPAS[idx]["id"]:
            plan["etapa"] = ETAPAS[idx]["id"]
            cambio = True
        if cambio:
            alm.guardar()

        # 5) Salida
        actualizar_tareas(alm)
        tareas_pub = [_tarea_publica(t) for t in alm.d.get("tareas", [])]
        diag = diagnostico(partidas, niveles, rol_main)
        habitos = []
        for h in diag["habitos"]:
            fila = {k: h[k] for k in ("clave", "nombre", "regla", "nivel", "n", "k", "tasa", "wr_si", "n_si",
                                      "wr_no", "n_no", "datos_wr", "ult_ok", "ult_n")}
            fila["estado"] = ("foco" if foco and h["clave"] == foco["clave"] else
                              "dominado" if _hecho(plan, h["clave"], h["nivel"]) else
                              "no_aplica" if not h["aplica_main"] else "pendiente")
            habitos.append(fila)
        etapas = []
        for i, e in enumerate(ETAPAS):
            reqs = []
            for c, n in e["req"]:
                aplica = _req_aplica(c, rol_main)
                es_foco = bool(foco and foco["clave"] == c and foco["nivel"] == n)
                f = _fila_habito(recientes, HAB[c], n, ctx, rol_main=rol_main) if aplica and i <= idx else None
                reqs.append({"clave": c, "nivel": n, "nombre": HAB[c]["nombre"], "regla": regla_habito(c, n, ctx),
                             "estado": ("foco" if es_foco else "hecho" if aplica and _hecho(plan, c, n)
                                        else "no_aplica" if not aplica else "pendiente"),
                             "tasa": f["tasa"] if f else None, "ult_ok": f["ult_ok"] if f else None,
                             "ult_n": f["ult_n"] if f else None})
            etapas.append({"id": e["id"], "nombre": e["nombre"], "rango": e["rango"], "que": e["que"],
                           "estado": ("hecha" if i < idx or (i == idx and not pend) else
                                      "actual" if i == idx else "siguiente"),
                           "reqs": reqs})
        e = ETAPAS[idx]
        out = {"rol": rol_main, "rol_txt": ROL_TXT.get(rol_main, ""), "n_partidas": diag["n"],
               "habitos": habitos, "pool": diag["pool"], "roles": roles,
               "etapa": {"idx": idx, "id": e["id"], "nombre": e["nombre"], "rango": e["rango"], "que": e["que"],
                         "total": len(ETAPAS), "completa": not pend},
               "etapas": etapas,
               "dominados": [x for x in plan["dominados"] if x.get("clave") in HAB][-8:],
               "ventana": vent, "necesarias": CONFIG["cumplidas_para_dominar"], "foco": None, "ctx": ctx,
               "tareas": tareas_pub}
        if foco:
            fh = _fila_habito(recientes, HAB[foco["clave"]], foco["nivel"], ctx, rol_main=rol_main)
            out["foco"] = {"clave": fh["clave"], "nombre": fh["nombre"], "regla": fh["regla"], "nivel": fh["nivel"],
                           "como": como_habito(fh["clave"], rol_main), "por_que": _por_que(fh),
                           "leccion": leccion_habito(fh["clave"], rol_main),
                           "progreso": fh["progreso"], "ult_ok": fh["ult_ok"], "ult_n": fh["ult_n"],
                           "desde": foco.get("desde"), "repaso": bool(foco.get("repaso"))}
        return out


def mision_para_rol(plan, rol):
    """Mision de la partida segun el rol que vas a jugar (si se sabe). Si el coach te dejo tareas en una sesion,
    la mision son tus tareas; si no, el foco de tu etapa."""
    mias = [t for t in plan.get("tareas") or [] if not t["rol"] or not rol or t["rol"] == rol]
    if mias:
        t0 = mias[0]
        return {"clave": t0["id"].split(":")[0] if t0["id"].split(":")[0] in ("vivo_10", "solo", "oro") else "tarea",
                "nombre": "Tu tarea", "regla": t0["medida"], "nivel": 0, "fuera_de_rol": False,
                "como": [t["regla"] for t in mias] + [f"También se mide: {t['medida'][:1].lower() + t['medida'][1:]}."
                                                      for t in mias[1:]]}
    foco = plan.get("foco")
    if not foco:
        return None
    roles = HAB[foco["clave"]]["roles"]
    if rol and roles and rol not in roles:
        # tu foco no aplica a este rol: lo pendiente de tu etapa (o de las anteriores) que si aplica
        alt = None
        for e in plan.get("etapas") or []:
            if e["estado"] == "siguiente":
                break
            for r in e["reqs"]:
                if r["estado"] in ("pendiente", "foco", "no_aplica") and _req_aplica(r["clave"], rol) \
                        and r["clave"] != foco["clave"]:
                    alt = r
                    break
            if alt:
                break
        if not alt:
            alt = {"clave": "muertes", "nivel": 0}
        return {"clave": alt["clave"], "nombre": HAB[alt["clave"]]["nombre"],
                "regla": regla_habito(alt["clave"], alt["nivel"], {"rol": rol}), "nivel": alt["nivel"],
                "como": como_habito(alt["clave"], rol), "fuera_de_rol": True}
    return {"clave": foco["clave"], "nombre": foco["nombre"],
            "regla": regla_habito(foco["clave"], foco["nivel"], {"rol": rol or plan.get("rol") or ""}),
            "nivel": foco["nivel"], "como": como_habito(foco["clave"], rol or plan.get("rol") or ""),
            "fuera_de_rol": False}


# =============================================================== SESION DE COACHING
# Lo que hace un coach de verdad despues de cada partida: (1) comprueba la tarea que te dejo, (2) elige los 2 errores
# que mas te costaron (no solo muertes), (3) te pregunta POR QUE lo hiciste para encontrar la causa, (4) te deja una
# tarea concreta y medible, y (5) en tus siguientes partidas comprueba si la cumpliste. El avance se mide con cuantos
# errores de estos cometes por partida.
TAREAS_MAX = 3            # tareas activas a la vez
TAREA_PARTIDAS = 3        # partidas en las que se comprueba cada tarea
TAREA_CUMPLIDAS = 2       # cumplidas necesarias para darla por superada


def _cmp(p, nombre):
    """Valor tuyo y de tu rival en la tabla de comparacion (o None, None)."""
    def num(x):
        try:
            return int(str(x).replace(".", "").replace("+", "").replace(",", ""))
        except (TypeError, ValueError):
            return None
    for c in p.get("comparacion") or []:
        if c.get("nombre") == nombre:
            return num(c.get("yo")), num(c.get("rival"))
    return None, None


def _muertes_dive(p):
    # desde el minuto 10: antes es fase de lineas y ya lo cubre "moriste en la fase de lineas"
    return [m for m in p.get("muertes") or [] if m.get("zona") == "enemiga" and m.get("sin_equipo")
            and (m.get("ts") or 0) >= 600000]


def _lista_min(ms):
    return ", ".join(f"{m['min']} ({m['killer']})" for m in ms)


def _h_lejos(p, dh):
    if p.get("rol") != "support" or dh.get("kp") is None or (p.get("minutos") or 0) < 18:
        return None
    dc, _ = _cmp(p, "Daño a campeones")
    tor = dh.get("torres") or 0
    if dh["kp"] >= 0.45 or not (dh["kp"] < 0.35 or (dc is not None and tor > dc)):
        return None
    ev = f"Participaste en el {round(dh['kp'] * 100)}% de las kills de tu equipo."
    if dc is not None and tor > dc:
        ev += f" Hiciste {_miles(tor)} de daño a torres y {_miles(dc)} a campeones: estabas empujando mientras tu equipo peleaba."
    return {"evid": ev, "costo": 3 + (0.5 - dh["kp"]) * 10}


def _h_nivel(p, dh):
    yo, rv = _cmp(p, "Nivel a los 15 min")
    if yo is None or rv is None or rv - yo < 2:
        return None
    return {"evid": f"Al minuto 15 eras nivel {yo}; tu rival, nivel {rv}.", "costo": 1 + (rv - yo) * 1.5}


def _h_dive(p, dh):
    ms = _muertes_dive(p)
    if not ms:
        return None
    return {"evid": f"Moriste en el lado enemigo sin ningún aliado en la pelea: {_lista_min(ms)}.",
            "costo": 1.5 + 1.5 * len(ms)}


def _h_solo(p, dh):
    ms = dh.get("solo_14") or []
    if len(ms) < 2 or _muertes_dive(p):
        return None
    return {"evid": "Moriste sin tu equipo después del minuto 14: " + ", ".join(
        f"{m['min']} ({m['killer']})" for m in ms) + ".", "costo": 1 + 1.2 * len(ms)}


def _h_tempranas(p, dh):
    ms = dh.get("muertes_10") or []
    if not ms:
        return None
    return {"evid": "Moriste antes del minuto 10: " + ", ".join(f"{m['min']} ({m['killer']})" for m in ms) + ".",
            "costo": 1 + 2 * len(ms)}


def _h_farmeo(p, dh):
    cs, dif = dh.get("cs10"), dh.get("cs10_diff")
    if p.get("rol") not in ("top", "mid", "bot") or cs is None or not (cs < 50 or (dif is not None and dif <= -15)):
        return None
    ev = f"{cs} CS al minuto 10" + (f"; tu rival, {cs - dif}." if dif is not None else ".")
    return {"evid": ev, "costo": 1 + max(0, 60 - cs) / 10 + (max(0, -dif) / 15 if dif is not None else 0)}


def _h_muertes(p, dh):
    if (dh.get("d") or 0) < 7:
        return None
    return {"evid": f"Moriste {dh['d']} veces. La meta para subir es 5 o menos.", "costo": dh["d"] - 4}


def _h_oro(p, dh):
    ms = dh.get("oro_muerto") or []
    if not ms:
        return None
    return {"evid": f"Moriste {len(ms)} {'vez' if len(ms) == 1 else 'veces'} con {_miles(CONFIG['oro_sin_gastar'])} "
                    "de oro o más sin gastar.", "costo": 1 + 0.8 * len(ms)}


def _meta_cs(p, dh):
    return int(min(70, max(40, 5 * math.ceil(((dh.get("cs10") or 30) + 10) / 5))))


def _meta_muertes(p, dh):
    return int(max(5, min((dh.get("d") or 7) - 2, 7)))


HALLAZGOS = [
    {"clave": "lejos", "titulo": "Jugaste lejos de tu equipo", "det": _h_lejos,
     "pregunta": "Cuando tu equipo peleaba y tú no estabas, ¿qué pasaba?",
     "tarea": {"tipo": "kp", "meta": lambda p, dh: 0.5, "rol": True,
               "medida": lambda m: "Participar en el 50% o más de las kills de tu equipo"},
     "opciones": [
         {"id": "a", "texto": "Lo veía en el minimapa y prefería seguir empujando o farmeando", "diag": "Decisión",
          "explica": "De support, tu valor está al lado de un aliado: tu curación, tu escudo y tu control no hacen "
                     "nada en una línea vacía. Tu equipo pelea 4 contra 5, y lo que tú haces en la torre lo hace una "
                     "oleada de súbditos sola.",
          "regla": "Si ves una pelea en el minimapa y puedes llegar, deja lo que estés haciendo y ve."},
         {"id": "b", "texto": "No me daba cuenta de que estaban peleando", "diag": "Atención al mapa",
          "explica": "No es una mala decisión: es no mirar. El minimapa se mira por costumbre, no cuando te acuerdas.",
          "regla": "Mira el minimapa cada vez que termines algo: un ward, una oleada, una vuelta a base."},
         {"id": "c", "texto": "Estaba lejos y llegaba tarde a todo", "diag": "Posición",
          "explica": "Si siempre llegas tarde, es que te colocas lejos antes de que la pelea empiece. Las peleas se "
                     "ven venir: un objetivo que va a salir, dos equipos en la misma línea.",
          "regla": "Desde el minuto 14, quédate a menos de una pantalla de tu tirador o del aliado que va mejor."},
         {"id": "d", "texto": "Mi equipo peleaba mal y no quería morir con ellos", "diag": "Cabeza",
          "explica": "Puede que peleen mal, pero sin su support pelean peor. No tienes que entrar primero: basta con "
                     "estar detrás y usar tus habilidades sobre el aliado que va mejor.",
          "regla": "Ve a las peleas de tu equipo y colócate detrás: tus habilidades, sobre el aliado que va mejor."}]},
    {"clave": "nivel", "titulo": "Te quedaste atrás en nivel", "det": _h_nivel,
     "pregunta": "¿Dónde estabas mientras tu rival subía de nivel?",
     "tarea": {"tipo": "nivel15", "meta": lambda p, dh: -1, "rol": False,
               "medida": lambda m: "Al minuto 15, como mucho 1 nivel por debajo de tu rival"},
     "opciones": [
         {"id": "a", "texto": "En mi línea, pero lejos de los súbditos (me echaban o me escondía)", "diag": "Fase de líneas",
          "explica": "La experiencia solo te llega si estás cerca cuando muere el súbdito. Aunque no puedas dar el "
                     "último golpe, quédate a distancia de recibirla.",
          "regla": "Aunque no puedas farmear, quédate cerca de la oleada para recibir la experiencia."},
         {"id": "b", "texto": "Moviéndome a otras líneas o por la jungla", "diag": "Decisión",
          "explica": "Cada rotación que no termina en una kill o un objetivo te cuesta una oleada entera de "
                     "experiencia. Rotar es bueno solo cuando tu oleada ya está empujada contra su torre.",
          "regla": "Antes del minuto 10 no salgas de tu línea salvo que la oleada esté empujada contra su torre."},
         {"id": "c", "texto": "Muerto, o volviendo a base muchas veces", "diag": "Supervivencia",
          "explica": "Cada muerte y cada vuelta a base con la oleada en medio son súbditos que mueren sin ti.",
          "regla": "Vuelve a base solo después de empujar la oleada contra su torre."},
         {"id": "d", "texto": "Cubriendo otra línea porque un compañero no estaba", "diag": "En parte no dependía de ti",
          "explica": "Cubrir a un compañero ausente está bien. Pero solo en una línea se sube de nivel rápido: si aun "
                     "así te quedaste atrás, estabas lejos de la oleada cuando morían los súbditos.",
          "regla": "Si cubres una línea, quédate en ella: mata cada oleada antes de moverte."}]},
    {"clave": "dive", "titulo": "Entraste solo al lado enemigo", "det": _h_dive,
     "pregunta": "¿A qué ibas?",
     "tarea": {"tipo": "dive", "meta": lambda p, dh: 0, "rol": False,
               "medida": lambda m: "0 muertes en el lado enemigo sin tu equipo"},
     "opciones": [
         {"id": "a", "texto": "A rematar a un enemigo con poca vida", "diag": "Decisión",
          "explica": "Un enemigo con poca vida en su lado o bajo su torre no es una kill segura: la torre y sus "
                     "compañeros llegan antes. Solo vale la pena si lo matas tú de una combinación o si un aliado "
                     "con daño ya está entrando.",
          "regla": "No persigas a un enemigo con poca vida hasta su torre si vas solo."},
         {"id": "b", "texto": "A empujar una línea o tirar una torre", "diag": "Mapa",
          "explica": "Empujar pasado el río sin saber dónde están es apostar. Los enemigos que no ves en el minimapa "
                     "pueden estar yendo hacia ti.",
          "regla": "No pases del río en una línea si no ves a 3 enemigos en el minimapa."},
         {"id": "c", "texto": "A poner visión", "diag": "Visión",
          "explica": "La visión en su lado se pone con el equipo cerca o desde lejos. Un ward no vale una muerte.",
          "regla": "Pon visión en el lado enemigo solo con un aliado cerca."},
         {"id": "d", "texto": "Creía que mi equipo venía conmigo", "diag": "Coordinación",
          "explica": "Entrar esperando que te sigan es la forma más común de morir solo. La regla es al revés: entras "
                     "cuando ya ves a tu aliado entrando, no antes.",
          "regla": "No entres primero ni solo: entra cuando un aliado con daño ya esté entrando."}]},
    {"clave": "solo", "titulo": "Te mataron solo varias veces", "det": _h_solo,
     "pregunta": "¿Qué estabas haciendo cuando te encontraron?",
     "tarea": {"tipo": "solo", "meta": lambda p, dh: 0, "rol": False,
               "medida": lambda m: f"Desde el minuto {CONFIG['fin_fase_lineas_min']}, 0 muertes sin tu equipo"},
     "opciones": [
         {"id": "a", "texto": "Farmeando o empujando una línea", "diag": "Mapa",
          "explica": "Farmear una línea lateral está bien, pero con información: si no ves a los enemigos, vienen.",
          "regla": "En una línea lateral, si 3 enemigos desaparecen del minimapa, retrocede."},
         {"id": "b", "texto": "Caminando de un sitio a otro", "diag": "Rutas",
          "explica": "Te cazan en el camino, no en el destino: cruzando su jungla o el río sin visión.",
          "regla": "Muévete por tu lado del mapa y por zonas con visión, aunque tardes más."},
         {"id": "c", "texto": "Poniendo visión", "diag": "Visión",
          "explica": "Un ward no vale una muerte. Se pone con un aliado cerca o antes de que el rival llegue a la zona.",
          "regla": "No entres primero a un arbusto sin visión: lanza el ward desde fuera."},
         {"id": "d", "texto": "Iba a una pelea y llegué cuando ya había terminado", "diag": "Tiempos",
          "explica": "Llegar tarde a una pelea perdida es regalar otra muerte.",
          "regla": "Si la pelea ya está perdida cuando llegas, da la vuelta."}]},
    {"clave": "tempranas", "titulo": "Moriste en la fase de líneas", "det": _h_tempranas,
     "pregunta": "¿Qué pasó en esas muertes?",
     "tarea": {"tipo": "vivo_10", "meta": lambda p, dh: 0, "rol": False,
               "medida": lambda m: "0 muertes antes del minuto 10"},
     "opciones": [
         {"id": "a", "texto": "Vino su jungla, o alguien de otra línea", "diag": "Mapa",
          "explica": "Un gank funciona cuando tu oleada está adelantada y no sabes dónde está su jungla.",
          "regla": "Con la oleada pasada del centro y sin ver a su jungla, retrocede."},
         {"id": "b", "texto": "Perdí el intercambio contra mi rival", "diag": "Intercambios",
          "explica": "Los intercambios se pierden antes de empezar: él tenía más súbditos (te pegan cuando lo "
                     "atacas), más nivel o sus habilidades listas.",
          "regla": "No pegues a tu rival si él tiene más súbditos o más nivel que tú."},
         {"id": "c", "texto": "Me quedé en la línea con poca vida", "diag": "Vuelta a base",
          "explica": "Con poca vida no puedes farmear ni pelear: solo puedes morir. Perder una oleada es más barato.",
          "regla": "Con menos de media vida y sin pociones, vuelve a base."},
         {"id": "d", "texto": "Me engancharon o me aturdieron y no pude salir", "diag": "Posición",
          "explica": "Contra un campeón con enganche, tu posición importa más que tus manos: los súbditos bloquean "
                     "casi todos los ganchos.",
          "regla": "Contra un campeón con enganche, quédate detrás de tus súbditos."}]},
    {"clave": "farmeo", "titulo": "Perdiste mucho farmeo", "det": _h_farmeo,
     "pregunta": "¿Por qué se te escaparon los súbditos?",
     "tarea": {"tipo": "cs10", "meta": _meta_cs, "rol": True, "medida": lambda m: f"{m} CS o más al minuto 10"},
     "opciones": [
         {"id": "a", "texto": "Fallo el último golpe", "diag": "Mecánica",
          "explica": "Es práctica pura. 10 minutos al día en la Herramienta de práctica se notan en una semana.",
          "regla": "Haz el Entrenamiento de CS antes de jugar, y no ataques al súbdito hasta que tu golpe lo mate."},
         {"id": "b", "texto": "Mi rival me echaba de la oleada", "diag": "Fase de líneas",
          "explica": "Si no puedes acercarte, no pelees por cada súbdito: deja que la oleada llegue a tu torre.",
          "regla": "Si te presiona, deja que la oleada llegue a tu torre y farmea ahí."},
         {"id": "c", "texto": "Estaba muerto o en base", "diag": "Supervivencia",
          "explica": "Cada muerte y cada vuelta a base a destiempo son una o dos oleadas perdidas.",
          "regla": "Vuelve a base solo después de empujar la oleada contra su torre."},
         {"id": "d", "texto": "Estaba peleando o persiguiendo", "diag": "Decisión",
          "explica": "Unos 15 súbditos valen lo que una kill, y son seguros. Una persecución que no mata no da nada.",
          "regla": "Hasta el minuto 10, no dejes una oleada por un intercambio que no va a matar."}]},
    {"clave": "muertes", "titulo": "Moriste demasiadas veces", "det": _h_muertes,
     "pregunta": "¿Cómo fueron la mayoría de tus muertes?",
     "tarea": {"tipo": "muertes", "meta": _meta_muertes, "rol": False,
               "medida": lambda m: f"{m} muertes o menos en la partida"},
     "opciones": [
         {"id": "a", "texto": "Entrando a peleas que ya estaban perdidas", "diag": "Decisión",
          "explica": "Si tu equipo ya perdió a dos, la pelea está decidida: entrar solo le da más oro al rival.",
          "regla": "Si tu equipo ya perdió a dos en la pelea, no entres: retírate."},
         {"id": "b", "texto": "Yendo solo por el mapa", "diag": "Mapa",
          "explica": "Después de la fase de líneas, quien camina solo se encuentra con dos o tres.",
          "regla": "Desde el minuto 14, muévete con un aliado o por zonas con visión."},
         {"id": "c", "texto": "Entrando yo primero a las peleas", "diag": "Posición",
          "explica": "El primero en entrar recibe todas las habilidades. Ese papel es del tanque.",
          "regla": "Espera a que entre tu primera línea antes de entrar tú."},
         {"id": "d", "texto": "Volviendo a pelear enseguida después de morir, enfadado", "diag": "Cabeza",
          "explica": "Después de morir vuelves con menos nivel y menos oro que tu rival: pelear enseguida es morir "
                     "otra vez.",
          "regla": "Después de morir, juega un minuto seguro: farmea y no pelees."}]},
    {"clave": "oro", "titulo": "Moriste con oro sin gastar", "det": _h_oro,
     "pregunta": "¿Por qué no habías vuelto a base?",
     "tarea": {"tipo": "oro", "meta": lambda p, dh: 0, "rol": False,
               "medida": lambda m: f"Nunca morir con {_miles(CONFIG['oro_sin_gastar'])} de oro o más sin gastar"},
     "opciones": [
         {"id": "a", "texto": "No me fijé en cuánto oro tenía", "diag": "Atención",
          "explica": "El oro que llevas encima no hace nada hasta que lo conviertes en objetos.",
          "regla": "Mira tu oro cada vez que mates una oleada: con 1.300, empuja y vuelve a base."},
         {"id": "b", "texto": "Quería una oleada o una pelea más", "diag": "Decisión",
          "explica": "Esa oleada de más vale unos 100 de oro; el objeto que no compraste, una pelea entera.",
          "regla": "Con 1.300 de oro, tu siguiente tarea es empujar y volver. Nada más."},
         {"id": "c", "texto": "No sé cuándo es buen momento para volver", "diag": "Fase de líneas",
          "explica": "El buen momento es justo después de empujar la oleada contra su torre: su torre mata tus "
                     "súbditos mientras compras y casi no pierdes nada.",
          "regla": "Empuja la oleada contra su torre y entonces vuelve a base."}]},
]
HALL = {h["clave"]: h for h in HALLAZGOS}


def hallazgos_de(p):
    """Todos los errores caros de la partida, del mas caro al menos."""
    dh = p.get("datos_h") or {}
    out = []
    for h in HALLAZGOS:
        try:
            r = h["det"](p, dh)
        except Exception:
            r = None
        if r:
            out.append({"clave": h["clave"], "titulo": h["titulo"], "evid": r["evid"], "costo": round(r["costo"], 2)})
    return sorted(out, key=lambda x: -x["costo"])


def revisar_tarea(t, p):
    """(aplica, cumplida, prueba) de una tarea en una partida."""
    dh = p.get("datos_h") or {}
    if t.get("rol") and p.get("rol") != t["rol"]:
        return False, None, ""
    tipo, meta = t["tipo"], t.get("meta")
    if tipo == "kp":
        if dh.get("kp") is None or (p.get("minutos") or 0) < 15:
            return False, None, ""
        return True, dh["kp"] >= meta, f"Participaste en el {round(dh['kp'] * 100)}% de las kills."
    if tipo == "nivel15":
        yo, rv = _cmp(p, "Nivel a los 15 min")
        if yo is None or rv is None:
            return False, None, ""
        return True, yo - rv >= meta, f"Al minuto 15: tú nivel {yo}, tu rival {rv}."
    if tipo == "dive":
        if not p.get("con_timeline"):
            return False, None, ""
        ms = _muertes_dive(p)
        return True, not ms, (f"Moriste solo en el lado enemigo: {_lista_min(ms)}." if ms
                              else "Ninguna muerte solo en el lado enemigo.")
    if tipo == "cs10":
        if dh.get("cs10") is None:
            return False, None, ""
        return True, dh["cs10"] >= meta, f"{dh['cs10']} CS al minuto 10 (meta {meta})."
    if tipo == "muertes":
        return True, (dh.get("d") or 0) <= meta, f"{dh.get('d') or 0} muertes (máximo {meta})."
    if tipo in ("vivo_10", "solo", "oro"):
        return evaluar_habito(tipo, dh, 0, {"rol": p.get("rol") or ""})
    return False, None, ""


def actualizar_tareas(alm):
    """Comprueba tus tareas en las partidas jugadas despues de recibirlas. Cada tarea se mide en 3 partidas: con 2
    cumplidas queda superada; si no, se repite. Llamar con el candado tomado."""
    tareas = alm.d.setdefault("tareas", [])
    hechas = alm.d.setdefault("tareas_hechas", [])
    partidas = sorted([p for p in alm.d["partidas"].values() if p.get("datos_h")],
                      key=lambda p: p.get("creacion") or 0)
    cambio = False
    for t in list(tareas):
        vistos = {r["gid"] for r in t["res"]} | set(t.get("vistas") or [])
        for p in partidas:
            if (p.get("creacion") or 0) <= t["tras"] or p["id"] in vistos or len(t["res"]) >= TAREA_PARTIDAS:
                continue
            aplica, ok, evid = revisar_tarea(t, p)
            if aplica:
                t["res"].append({"gid": p["id"], "ok": bool(ok), "evid": evid, "campeon": p["yo"]["campeon"],
                                 "campeon_id": p["yo"]["campeon_id"], "fecha": p["fecha"]})
                cambio = True
        if len(t["res"]) >= TAREA_PARTIDAS:
            cambio = True
            if sum(1 for r in t["res"] if r["ok"]) >= TAREA_CUMPLIDAS:
                tareas.remove(t)
                hechas.append(dict(t, cerrada=int(time.time() * 1000)))
            else:       # no salio: se repite desde la ultima partida medida
                ult = alm.d["partidas"].get(t["res"][-1]["gid"]) or {}
                t["historial"] = (t.get("historial") or []) + [t["res"]]
                t["vueltas"] = t.get("vueltas", 0) + 1
                t["tras"] = ult.get("creacion") or t["tras"]
                t["res"] = []
    if cambio:
        alm.guardar()


def _tarea_publica(t):
    return {"id": t["id"], "regla": t["regla"], "medida": t["medida"], "rol": t.get("rol") or "",
            "rol_txt": ROL_TXT.get(t.get("rol") or "", ""), "titulo": HALL[t["origen"]]["titulo"] if t["origen"] in HALL else "",
            "diag": t.get("diag", ""), "res": t["res"], "vueltas": t.get("vueltas", 0),
            "partidas": TAREA_PARTIDAS, "necesarias": TAREA_CUMPLIDAS}


def sesion_coaching(alm, p):
    """La sesion de una partida: como fue tu tarea, los 2 errores mas caros con su pregunta y lo que ya contestaste."""
    with alm.lock:
        actualizar_tareas(alm)
        ses = (alm.d.get("sesiones") or {}).get(p["id"]) or {}
        todas = alm.d.get("tareas", []) + alm.d.get("tareas_hechas", [])
        activas = list(alm.d.get("tareas", []))
    resp = ses.get("resp") or {}
    medidas = []
    for t in todas:
        for grupo in [t["res"]] + (t.get("historial") or []):
            for r in grupo:
                if r["gid"] == p["id"]:
                    medidas.append({"regla": t["regla"], "medida": t["medida"], "ok": r["ok"], "evid": r["evid"]})
    todos = hallazgos_de(p)
    top = todos[:2]
    hall = []
    for h in top:
        d = HALL[h["clave"]]
        item = dict(h, pregunta=d["pregunta"], opciones=[{"id": o["id"], "texto": o["texto"]} for o in d["opciones"]])
        op = next((o for o in d["opciones"] if o["id"] == resp.get(h["clave"])), None)
        if op:
            dh = p.get("datos_h") or {}
            meta = d["tarea"]["meta"](p, dh)
            tid = d["tarea"]["tipo"] + (":" + p.get("rol", "") if d["tarea"]["rol"] else "")
            activa = any(t["id"] == tid for t in activas)
            item["respuesta"] = {"id": op["id"], "texto": op["texto"], "diag": op["diag"], "explica": op["explica"],
                                 "regla": op["regla"], "medida": d["tarea"]["medida"](meta),
                                 "estado": "activa" if activa else (ses.get("estado") or {}).get(h["clave"], "")}
            libre = (ses.get("texto") or {}).get(h["clave"])
            if libre:                                # lo escribiste con tus palabras y la IA lo clasifico
                item["respuesta"]["tuyo"], item["respuesta"]["porque"] = libre.get("texto"), libre.get("porque")
        hall.append(item)
    return {"medidas": medidas, "hallazgos": hall, "otros": [h["titulo"] for h in todos[2:]],
            "completa": all("respuesta" in h for h in hall), "limpia": not todos}


def responder_sesion(alm, gid, clave, opcion):
    """Guarda tu respuesta y te deja la tarea (si no la tienes ya y hay hueco)."""
    with alm.lock:
        p = alm.d["partidas"].get(gid)
        d = HALL.get(clave)
        op = next((o for o in (d or {}).get("opciones", []) if o["id"] == opcion), None)
        if not p or not d or not op or clave not in [h["clave"] for h in hallazgos_de(p)[:2]]:
            return False
        ses = alm.d.setdefault("sesiones", {}).setdefault(gid, {"resp": {}, "estado": {}})
        ses["resp"][clave] = opcion
        ses["ts"] = int(time.time() * 1000)
        tareas = alm.d.setdefault("tareas", [])
        dh = p.get("datos_h") or {}
        meta = d["tarea"]["meta"](p, dh)
        rol = p.get("rol", "") if d["tarea"]["rol"] else ""
        tid = d["tarea"]["tipo"] + (":" + rol if rol else "")
        existente = next((t for t in tareas if t["id"] == tid), None)
        if existente:
            existente["regla"], existente["diag"] = op["regla"], op["diag"]     # la causa mas reciente manda
            ses["estado"][clave] = "activa"
        elif len(tareas) >= TAREAS_MAX:
            ses["estado"][clave] = "espera"
        else:
            tareas.append({"id": tid, "tipo": d["tarea"]["tipo"], "meta": meta, "rol": rol, "origen": clave,
                           "regla": op["regla"], "medida": d["tarea"]["medida"](meta), "diag": op["diag"],
                           "tras": p.get("creacion") or 0, "res": [], "vueltas": 0,
                           "desde": int(time.time() * 1000)})
            ses["estado"][clave] = "activa"
        alm.guardar()
    return True


def avance(alm):
    """Tu avance medido: cuantos errores caros cometes por partida (ultimas 10 contra las 10 anteriores), cuales
    se repiten y cuantas tareas superaste."""
    with alm.lock:
        actualizar_tareas(alm)
        ps = sorted([p for p in alm.d["partidas"].values() if p.get("datos_h") and not p["datos_h"].get("afk_aliado")],
                    key=lambda p: p.get("creacion") or 0)
        hechas = list(alm.d.get("tareas_hechas", []))
        activas = list(alm.d.get("tareas", []))
        n_ses = sum(1 for x in (alm.d.get("sesiones") or {}).values() if x.get("resp"))
    ult, prev = ps[-10:], ps[-20:-10]

    def cuenta(lst):
        c = Counter()
        for p in lst:
            for h in hallazgos_de(p):
                c[h["clave"]] += 1
        return c
    cu, cp = cuenta(ult), cuenta(prev)
    media_u = round(sum(cu.values()) / len(ult), 1) if ult else None
    media_p = round(sum(cp.values()) / len(prev), 1) if len(prev) >= 5 else None
    tipos = [{"clave": h["clave"], "titulo": h["titulo"], "ahora": cu.get(h["clave"], 0), "n": len(ult),
              "antes": cp.get(h["clave"], 0) if len(prev) >= 5 else None, "n_antes": len(prev)}
             for h in HALLAZGOS if cu.get(h["clave"]) or cp.get(h["clave"])]
    tipos.sort(key=lambda x: -x["ahora"])
    if media_u is None:
        texto = "Todavía no hay partidas para medir."
    elif media_p is None:
        texto = (f"En tus últimas {len(ult)} partidas cometes {_dec(media_u)} errores caros por partida. Con 15 "
                 "partidas o más, el coach te dirá si vas a mejor o a peor.")
    elif media_u <= media_p - 0.3:
        texto = (f"Vas a mejor: {_dec(media_u)} errores caros por partida en tus últimas {len(ult)}, contra "
                 f"{_dec(media_p)} en las {len(prev)} anteriores.")
    elif media_u >= media_p + 0.3:
        texto = (f"Vas a peor: {_dec(media_u)} errores caros por partida en tus últimas {len(ult)}, contra "
                 f"{_dec(media_p)} en las {len(prev)} anteriores.")
    else:
        texto = (f"Estás igual: {_dec(media_u)} errores caros por partida en tus últimas {len(ult)}, contra "
                 f"{_dec(media_p)} en las {len(prev)} anteriores.")
    return {"media": media_u, "media_antes": media_p, "texto": texto, "tipos": tipos, "sesiones": n_ses,
            "superadas": [{"regla": t["regla"], "medida": t["medida"], "vueltas": t.get("vueltas", 0)}
                          for t in hechas][-6:],
            "n_superadas": len(hechas), "n_activas": len(activas)}


def mision_de_partida(alm, p, plan):
    reg = alm.d["misiones"].get(p["id"])
    if reg and reg.get("clave") not in HAB:
        reg = None          # habito que ya no forma parte del plan
    registrada = bool(reg)
    if not reg:
        if not plan.get("foco"):
            return None
        reg = {"clave": plan["foco"]["clave"], "nivel": plan["foco"]["nivel"]}
    ctx = dict(plan.get("ctx") or {}, rol=p.get("rol") or (plan.get("ctx") or {}).get("rol_main", ""))
    aplica, ok, evid = evaluar_habito(reg["clave"], p.get("datos_h") or {}, reg.get("nivel", 0), ctx)
    return {"clave": reg["clave"], "nombre": HAB[reg["clave"]]["nombre"],
            "regla": regla_habito(reg["clave"], reg.get("nivel", 0), ctx),
            "como": como_habito(reg["clave"], p.get("rol") or ""),     # consejos del rol que jugaste
            "repeticion": (leccion_habito(reg["clave"], p.get("rol") or "") or {}).get("repeticion", ""),
            "aplica": aplica, "ok": ok, "evid": evid, "registrada": registrada}


# =============================================================== RIVAL Y MATCHUP
def nota_matchup(alm, yo_cid, rival_cid):
    """Tu libreta de enfrentamientos: la nota de ese campeon tuyo contra ese rival; si no hay, la ultima que
    escribiste contra ese rival con otro campeon."""
    if not rival_cid:
        return None
    with alm.lock:
        mu = dict(alm.d.get("matchups") or {})
    x = mu.get(f"{yo_cid}:{rival_cid}") if yo_cid else None
    if x:
        return x
    otras = [v for k, v in mu.items() if k.endswith(f":{rival_cid}")]
    return max(otras, key=lambda v: v.get("ts", 0)) if otras else None


def historial_contra(partidas, cid):
    """Tus partidas contra un campeon como rival directo."""
    ps = [p for p in partidas if (p.get("datos_h") or {}).get("rival_id") == cid]
    if not ps:
        return None
    difs = [p["datos_h"].get("cs10_diff") for p in ps if p["datos_h"].get("cs10_diff") is not None]
    return {"n": len(ps), "v": sum(1 for p in ps if p["victoria"]), "d": sum(1 for p in ps if not p["victoria"]),
            "solo": sum(p["datos_h"].get("solo_rival", 0) for p in ps),
            "cs10": round(sum(difs) / len(difs)) if difs else None}


def guia_enfrentamiento(rival, consejos, wr=None, hist=None, maximo=3):
    """Guia fija contra tu rival de linea para la tarjeta del Tab: lo mismo toda la partida (no reacciona a lo que
    pasa en ella). Tu % contra el en Esmeralda+, tu historial, el nivel 6 (su definitiva) y los consejos oficiales
    de Riot para jugar contra el."""
    if not rival:
        return None
    datos = []
    if wr and wr[1] and wr[1] >= 50:
        datos.append(f"Tu campeón gana {_dec(wr[0], 1)} % contra él en Esmeralda+")
    if hist:
        datos.append(f"tú {hist['v']}V {hist['d']}D")
    tips = ["Desde su nivel 6 tiene la definitiva: respeta más sus entradas."]
    for t in (consejos or {}).get("contra") or []:
        t = re.sub(r"\s+", " ", str(t)).strip()
        if t and len(tips) < maximo:
            tips.append(t if len(t) <= 150 else t[:147].rsplit(" ", 1)[0] + "…")
    return {"rival": rival, "dato": " · ".join(datos), "tips": tips,
            "tono": "mal" if wr and wr[1] and wr[1] >= 50 and wr[0] < 48.5 else "bien" if wr and wr[1] and wr[1] >= 50 and wr[0] > 51.5 else ""}


def texto_historial(h, nombre):
    s = f"Tu historial contra {nombre}: {h['v']}V {h['d']}D."
    if h["solo"]:
        s += f" Te mató solo {h['solo']} {'vez' if h['solo'] == 1 else 'veces'}."
    if h["cs10"] is not None:
        s += f" CS al 10: {_signo(h['cs10'])} de media."
    return s


# =============================================================== SCOUTING DE LOS 10
_FICHAS = {}                  # puuid -> (momento, ficha): no repetir peticiones si vuelve a salir
# el bufo de cada mitad de la jungla segun el lado del equipo (azul = 100, abajo a la izquierda)
_BUFO = {(100, "arriba"): "azul", (100, "abajo"): "rojo", (200, "arriba"): "rojo", (200, "abajo"): "azul"}
POS_CORTA = {"TOP": "top", "JUNGLE": "jungla", "MIDDLE": "mid", "BOTTOM": "adc", "UTILITY": "support"}


def zona_mapa(x, y):
    """Zona de la Grieta por coordenadas: base, top, bot, mid, o la mitad de jungla de arriba / abajo (la
    diagonal de mid separa la mitad de arriba, y > x, de la de abajo)."""
    if (x < 3600 and y < 3600) or (x > 11200 and y > 11200):
        return "base"
    # cada linea: su tramo recto pegado al borde y el triangulo de la esquina (los campamentos quedan fuera:
    # el gromp azul esta en ~(2100, 8400), el rojo en ~(12700, 6400))
    if x < 1900 or y > 12900 or (x < 4200 and y > 10600 and y - x > 8500):
        return "top"
    if y < 1900 or x > 12900 or (x > 10600 and y < 4200 and x - y > 8500):
        return "bot"
    if abs(x - y) < 1500:
        return "mid"
    return "arriba" if y > x else "abajo"


def perfil_jugador(games, cid):
    """Resumen de las ultimas partidas de la Grieta de un jugador (lista del historial de la LCU)."""
    gs = sorted(games or [], key=lambda g: g.get("gameCreation") or 0, reverse=True)
    f = {"n": 0, "v": 0, "con": 0, "v_con": 0, "kda_con": None, "racha": 0, "jungla": []}
    k = d = a = 0
    res = []
    for g in gs:
        if g.get("mapId") not in (None, 11) or (g.get("gameDuration") or 999) < 300:
            continue                                   # ARAM, modos raros y partidas rehechas no cuentan
        p = (g.get("participants") or [{}])[0]
        st = p.get("stats") or {}
        win = bool(st.get("win"))
        f["n"] += 1
        f["v"] += win
        res.append(win)
        if p.get("championId") == cid:
            f["con"] += 1
            f["v_con"] += win
            k, d, a = k + (st.get("kills") or 0), d + (st.get("deaths") or 0), a + (st.get("assists") or 0)
        if SMITE in (p.get("spell1Id"), p.get("spell2Id")):
            f["jungla"].append({"gid": g.get("gameId"), "pid": p.get("participantId"), "team": p.get("teamId")})
    if f["con"]:
        f["kda_con"] = round((k + a) / max(d, 1), 1)
    for x in res:
        if x != res[0]:
            break
        f["racha"] += 1 if res[0] else -1
    return f


def etiquetas_jugador(f, enemigo=True):
    """Chips cortos de un jugador: [(texto, tono)]. El tono es para ti: 'mal' = cuidado, 'bien' = a tu favor."""
    t = []
    n, con = f.get("n") or 0, f.get("con") or 0
    fuerte, flojo = ("mal", "bien") if enemigo else ("bien", "mal")
    if n >= 8 and con >= max(6, n // 2):
        t.append((f"OTP {con}/{n}", fuerte))
    elif n >= 5 and con == 0:
        t.append(("1ª vez con él", flojo))
    elif con >= 5:
        wr = round(100 * f["v_con"] / con)
        if wr >= 60 or wr <= 40:
            t.append((f"{wr}% con él", fuerte if wr >= 60 else flojo))
    r = f.get("racha") or 0
    if r >= 3:
        t.append((f"gana {r} seguidas", fuerte))
    elif r <= -3:
        t.append((f"pierde {-r} seguidas", flojo))
    if f.get("nivel") and f["nivel"] < 50 and n >= 8 and f["v"] / n >= 0.7:
        t.append(("posible smurf", fuerte))
    return t


def lineas_ficha(f, nombre):
    """Lo que se sabe de tu rival de linea, en frases."""
    lineas = []
    if f.get("rango"):
        lineas.append(f"Rango: {f['rango']}")
    n, con = f.get("n") or 0, f.get("con") or 0
    if n:
        if con >= max(6, n // 2):
            lineas.append(f"Es main de {nombre}: {con} de sus últimas {n} partidas.")
        elif not con:
            lineas.append(f"No ha jugado {nombre} en sus últimas {n} partidas.")
        else:
            lineas.append(f"{con} de sus últimas {n} partidas con {nombre}.")
        r = f.get("racha") or 0
        if abs(r) >= 3:
            lineas.append(f"Viene de {abs(r)} {'victorias' if r > 0 else 'derrotas'} seguidas.")
    return lineas


def ficha_jugador(lcu, puuid, cid):
    """Rango, nivel y ultimas 20 partidas de un jugador. Solo despues de la pantalla de carga (antes la LCU
    esconde a los rivales)."""
    c = _FICHAS.get(puuid)
    if c and time.time() - c[0] < 1800 and c[1].get("cid") == cid:
        return c[1]
    f = {"cid": cid, "rango": "", "nivel": None}
    try:
        r = lcu.get(f"/lol-ranked/v1/ranked-stats/{puuid}", timeout=5)
        q = (r.get("queueMap") or {}).get("RANKED_SOLO_5x5") or {}
        tier = (q.get("tier") or "").upper()
        if tier and tier != "NONE":
            div = q.get("division") or ""
            f["rango"] = f"{TIERS.get(tier, tier.title())}{'' if div in ('', 'NA') or tier in ('MASTER', 'GRANDMASTER', 'CHALLENGER') else ' ' + div}"
    except Exception:
        pass
    try:
        f["nivel"] = (lcu.get(f"/lol-summoner/v2/summoners/puuid/{puuid}", timeout=5) or {}).get("summonerLevel")
    except Exception:
        pass
    try:
        h = lcu.get(f"/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex=19", timeout=8)
        f.update(perfil_jugador((h.get("games") or {}).get("games") or [], cid))
    except Exception:
        pass
    _FICHAS[puuid] = (time.time(), f)
    return f


def explorar_rival(lcu, rec, puuid, cid):
    """Datos publicos del rival de linea, en frases."""
    return lineas_ficha(ficha_jugador(lcu, puuid, cid), rec.campeon(cid))


def timelines_jungla(lcu, juegos, puuid, maximo=5):
    """Las lineas de tiempo de sus ultimas partidas de jungla (en paralelo)."""
    def campamentos(fr, pid):
        return int((((fr[3].get("participantFrames") or {}).get(str(pid)) or {}).get("jungleMinionsKilled") or 0)
                   if len(fr) > 3 and pid else 0)

    def una(j):
        try:
            tl = lcu.get(f"/lol-match-history/v1/game-timelines/{j['gid']}", timeout=15)
            fr = (tl or {}).get("frames") or []
            pid, team = j.get("pid"), j.get("team")
            if not campamentos(fr, pid):
                # el id del historial no cuadra con la partida (o no viene): se busca por su puuid
                g = lcu.get(f"/lol-match-history/v1/games/{j['gid']}", timeout=8)
                pid = next((x.get("participantId") for x in g.get("participantIdentities") or []
                            if (x.get("player") or {}).get("puuid") == puuid), None)
                team = next((x.get("teamId") for x in g.get("participants") or [] if x.get("participantId") == pid), None)
                if not campamentos(fr, pid):
                    return None
            return {"team": team or (100 if int(pid) <= 5 else 200), "pid": int(pid), "frames": fr}
        except Exception:
            return None
    hilos, out = [], [None] * min(maximo, len(juegos))
    for i, j in enumerate(juegos[:maximo]):
        t = threading.Thread(target=lambda i=i, j=j: out.__setitem__(i, una(j)), daemon=True)
        t.start()
        hilos.append(t)
    for t in hilos:
        t.join(25)
    return [x for x in out if x and x["frames"]]


def plan_jungla(juegos):
    """Como empieza un jungla: con que bufo (por donde esta en el minuto 1-2) y donde hace su primera jugada
    (la primera kill, asistencia o muerte en una linea antes del 6; si no, la primera vez que aparece en una
    linea entre el 3 y el 5). La jugada se guarda relativa a su inicio: en la linea de su mismo lado (gank
    temprano) o en la del otro (tras limpiar toda la jungla). juegos: [{"team", "pid", "frames"}]."""
    bufos, jugadas = Counter(), []
    for j in juegos:
        fr, pid, team = j.get("frames") or [], int(j["pid"]), j.get("team")
        if len(fr) < 6 or team not in (100, 200):
            continue

        def zona(m):
            pos = ((fr[m].get("participantFrames") or {}).get(str(pid)) or {}).get("position") or {}
            return zona_mapa(pos.get("x", 0), pos.get("y", 0)) if pos else None
        lado = next((z for z in (zona(1), zona(2)) if z in ("arriba", "abajo")), None)
        if not lado:
            continue
        bufos[_BUFO[(team, lado)]] += 1
        donde = minuto = None
        for f in fr[:8]:
            for e in f.get("events") or []:
                if e.get("type") != "CHAMPION_KILL" or (e.get("timestamp") or 0) > 360000:
                    continue
                if pid in [e.get("killerId"), e.get("victimId")] + list(e.get("assistingParticipantIds") or []):
                    p = e.get("position") or {}
                    z = zona_mapa(p.get("x", 0), p.get("y", 0))
                    if z in ("top", "mid", "bot"):
                        donde, minuto = z, e["timestamp"] / 60000
                        break
            if donde:
                break
        if not donde:
            for m in (3, 4, 5):            # por posicion solo top/bot: en mid casi siempre es que cruza el rio
                if zona(m) in ("top", "bot"):
                    donde, minuto = zona(m), float(m)
                    break
        if donde:
            rel = "mid" if donde == "mid" else ("mismo" if (donde == "top") == (lado == "arriba") else "otro")
            jugadas.append((rel, minuto))
    n = sum(bufos.values())
    plan = {"n": n}
    if n < 3:
        return plan
    plan["bufo"], plan["n_bufo"] = bufos.most_common(1)[0]
    rels = Counter(r for r, _ in jugadas)
    if rels:
        rel, nr = rels.most_common(1)[0]
        if nr >= max(2, 0.4 * n):
            mins = sorted(m for r, m in jugadas if r == rel)
            plan.update(jugada=rel, n_jugada=nr, minuto=round(mins[len(mins) // 2], 1))
    return plan


def _min_seg(m):
    s = int(round(m * 60))
    return f"{s // 60}:{s % 60:02d}"


def texto_plan_jungla(plan, team, nombre, mi_rol=""):
    """El plan del jungla rival para ESTA partida. team: su lado ahora (100 azul / 200 rojo)."""
    if not plan or (plan.get("n") or 0) < 3 or team not in (100, 200):
        return None
    lado = next(l for (t, l), b in _BUFO.items() if t == team and b == plan["bufo"])
    txt = (f"{nombre} empieza en su bufo {plan['bufo']} ({plan['n_bufo']} de sus {plan['n']} últimas de jungla): "
           f"aquí, por {'arriba' if lado == 'arriba' else 'abajo'}.")
    out = {"txt": txt, "alerta": False, "linea": None, "minuto": None, "lado": lado}
    if plan.get("jugada"):
        if plan["jugada"] == "mid":
            linea = "mid"
        elif plan["jugada"] == "mismo":
            linea = "top" if lado == "arriba" else "bot"
        else:
            linea = "bot" if lado == "arriba" else "top"
        out.update(linea=linea, minuto=plan["minuto"])
        out["txt"] += f" Su primera jugada suele ser en {linea} hacia el {_min_seg(plan['minuto'])} ({plan['n_jugada']} de {plan['n']})."
        mia = {"top": "top", "mid": "mid", "bot": "bot", "support": "bot"}.get(mi_rol)
        if mia == linea:
            out["alerta"] = True
            out["txt"] += " Es tu línea: ward en el río antes de ese minuto y no pases de la mitad."
    return out


# =============================================================== REPETICIONES
def activar_replay_api_cfg(txt):
    """game.cfg con EnableReplayApi=1 en [General]. Devuelve (texto nuevo, cambio?)."""
    nl = "\r\n" if "\r\n" in txt else "\n"
    lineas = txt.split(nl)
    sec, gen = None, None
    for i, l in enumerate(lineas):
        t = l.strip()
        if t.startswith("[") and t.endswith("]"):
            sec = t[1:-1].strip().lower()
            if sec == "general" and gen is None:
                gen = i
            continue
        if sec == "general" and t.split("=", 1)[0].strip().lower() == "enablereplayapi":
            if t.split("=", 1)[-1].strip() == "1":
                return txt, False
            lineas[i] = "EnableReplayApi=1"
            return nl.join(lineas), True
    if gen is None:
        return "[General]" + nl + "EnableReplayApi=1" + nl + txt, True
    lineas.insert(gen + 1, "EnableReplayApi=1")
    return nl.join(lineas), True


def activar_replay_api():
    """La Replay API del juego (la que deja saltar a un minuto de la repetición) viene apagada en game.cfg.
    Se enciende antes de abrir una repetición. True si quedó encendida."""
    for r in _rutas_instalacion():
        cfg = Path(r) / "Config" / "game.cfg"
        try:
            if not cfg.exists():
                continue
            crudo = cfg.read_bytes()
            bom = crudo.startswith(b"\xef\xbb\xbf")
            txt = crudo.decode("utf-8-sig", errors="replace")
            nuevo, cambio = activar_replay_api_cfg(txt)
            if cambio:
                cfg.write_bytes((b"\xef\xbb\xbf" if bom else b"") + nuevo.encode("utf-8"))
                log(f"Repeticiones: activé EnableReplayApi en {cfg} para poder saltar al minuto.")
            return True
        except Exception as e:
            log(f"Repeticiones: no pude activar la Replay API ({type(e).__name__}: {e}).")
            return False
    return False


def _saltar_en_repeticion(segundo):
    """Espera a que la repetición esté cargada y corriendo (la API responde ya en la pantalla de carga, y ahí
    el salto se pierde) y salta unos segundos antes del momento. Comprueba que el salto se hizo."""
    base = os.environ.get("COACH_LIVE_URL", "https://127.0.0.1:2999").rstrip("/")
    ctx = _CTX if base.startswith("https") else None
    meta = max(0, segundo - 15)

    def pedir(metodo, cuerpo=None):
        req = urllib.request.Request(base + "/replay/playback", method=metodo,
                                     data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, context=ctx, timeout=3) as r:
            return json.loads(r.read().decode("utf-8") or "{}")

    fin, previo, intentos, vio_api = time.time() + 300, None, 0, False
    while time.time() < fin:
        time.sleep(2)
        try:
            st = pedir("GET")
        except Exception:
            continue
        vio_api = True
        t, largo = st.get("time") or 0, st.get("length") or 0
        if largo <= 0 or previo is None or t <= previo:      # aun cargando: el tiempo no avanza
            previo = t
            continue
        if abs(t - meta) < 8:
            log(f"Repeticiones: salté al {int(meta) // 60}:{int(meta) % 60:02d}.")
            return
        try:
            pedir("POST", {"time": min(meta, max(0, largo - 1)), "paused": False})
        except Exception:
            pass
        intentos += 1
        previo = None
        if intentos >= 5:
            break
    log("Repeticiones: no pude saltar al minuto " + ("(la repetición no avanzó)." if vio_api else
        "(el juego no abrió la Replay API: reinicia el cliente de LoL para que lea EnableReplayApi=1)."))


def abrir_repeticion(lcu, gid, segundo):
    malos = {"incompatible": "Esa repetición es de un parche anterior: el cliente ya no puede abrirla.",
             "missingOrExpired": "Esa repetición ya no está en los servidores de Riot.",
             "lost": "La repetición se perdió.", "error": "El cliente dio un error con esa repetición.",
             "unsupported": "Esa repetición no se puede abrir."}

    def estado():
        try:
            return (lcu.get(f"/lol-replays/v1/metadata/{gid}", timeout=5) or {}).get("state")
        except Exception:
            return None

    s = estado()
    if s in malos:
        return False, malos[s]
    if s != "watch":
        try:
            lcu.post(f"/lol-replays/v1/rofls/{gid}/download", {"contextData": "coach-lol"})
        except Exception:
            return False, "El cliente no aceptó descargar la repetición. ¿Está abierto?"
        fin = time.time() + 150
        while True:
            time.sleep(2)
            s = estado()
            if s == "watch":
                break
            if s in malos:
                return False, malos[s]
            if time.time() > fin:
                return False, "La descarga de la repetición tardó demasiado. Inténtalo otra vez."
    activar_replay_api()
    try:
        lcu.post(f"/lol-replays/v1/rofls/{gid}/watch", {"contextData": "coach-lol"})
    except Exception:
        return False, "El cliente no pudo abrir la repetición."
    threading.Thread(target=_saltar_en_repeticion, args=(segundo,), daemon=True).start()
    m = max(0, int(segundo) - 15)
    return True, (f"Abriendo la repetición: cuando termine de cargar salta sola al {m // 60}:{m % 60:02d}, "
                  "unos segundos antes del momento.")


# =============================================================== PROGRESO
def _prom(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _p_mayor(v, meta):
    return None if v is None else max(0, min(100, round(100 * v / meta)))


def _p_menor(v, meta):
    return None if v is None else max(0, min(100, round(100 * meta / max(v, meta / 4))))


def _wr(lst):
    return round(100 * sum(1 for p in lst if p["victoria"]) / len(lst)) if lst else None


def _areas_partida(p):
    dh, rol = p["datos_h"], p.get("rol", "")
    sup = rol == "support"
    a = {"supervivencia": _prom([_p_menor(dh["d"], CONFIG["muertes_max"]),
                                 (0 if dh["muertes_10"] else 100) if dh.get("con_tl") else None]),
         "vision": _prom([_p_mayor(dh["cw"], 3 if sup else 2), _p_mayor(dh.get("wards_min"), 0.9 if sup else 0.4)]),
         "impacto": (_p_mayor(dh.get("torres_min"), CONFIG["torres_min"][0]) if rol in ("top", "")
                     else _p_mayor(dh.get("kp"), CONFIG["kp"][0]))}
    if not sup:
        meta_csm = CONFIG["cs_min_jungla"][0] if rol == "jungla" else CONFIG["cs_min"][0]
        a["farmeo"] = _prom([_p_mayor(dh.get("csmin"), meta_csm), _p_mayor(dh.get("cs10"), 60)])
    if dh.get("oro14_diff") is not None:
        # 50 = parejo con tu rival al 14; 100 = +1.000 o mas; 0 = -1.000 o peor
        a["linea"] = max(0, min(100, round(50 + dh["oro14_diff"] / 20)))
    return a


AREAS = [("supervivencia", "Supervivencia", "Muertes por partida y muertes antes del minuto 10."),
         ("linea", "Tu línea", "Oro contra tu rival directo al minuto 14. 50 es ir parejo."),
         ("farmeo", "Farmeo", "CS por minuto y CS al minuto 10 (no cuenta tus partidas de support)."),
         ("vision", "Visión", "Control wards y wards por minuto, con metas distintas para support."),
         ("impacto", "Impacto", "Daño a torres si juegas top; participación en kills en los demás roles."),
         ("disciplina", "Disciplina", "Si paras cuando el coach te dice que pares.")]


def _mediana(vals):
    vals = sorted(v for v in vals if v is not None)
    return vals[len(vals) // 2] if vals else None


def _patrones_metricas(todas):
    """Que cosas van con ganar en TUS partidas (sin contar partidas con un AFK en tu equipo)."""
    ps = [p for p in todas if p.get("datos_h") and not p["datos_h"].get("afk_aliado")][-40:]
    rol_main = Counter(p.get("rol") for p in ps if p.get("rol")).most_common(1)
    rol_main = rol_main[0][0] if rol_main else ""
    out = []

    def comparar(titulo, txt_si, txt_no, pred, filtro=lambda p: True):
        grupo = [p for p in ps if filtro(p)]
        si = [p for p in grupo if pred(p) is True]
        no = [p for p in grupo if pred(p) is False]
        if len(si) >= 4 and len(no) >= 4:
            a, b = _wr(si), _wr(no)
            if abs(a - b) >= 15:
                out.append({"titulo": titulo, "dif": abs(a - b), "malo": False,
                            "texto": f"Cuando {txt_si} ganas el {a}% ({len(si)} partidas); "
                                     f"cuando {txt_no}, el {b}% ({len(no)})."})

    nosup = lambda p: p.get("rol") != "support"
    med_w = _mediana([p["datos_h"].get("wards_min") for p in ps if nosup(p)])
    if med_w:
        comparar("Visión", f"pones {_dec(med_w, 2)} wards por minuto o más", "pones menos",
                 lambda p: None if p["datos_h"].get("wards_min") is None else p["datos_h"]["wards_min"] >= med_w, nosup)
    med_ws = _mediana([p["datos_h"].get("wards_min") for p in ps if not nosup(p)])
    if med_ws:
        comparar("Visión de support", f"de support pones {_dec(med_ws, 2)} wards por minuto o más", "pones menos",
                 lambda p: p["datos_h"].get("wards_min", 0) >= med_ws, lambda p: not nosup(p))
    comparar("Control wards", "compras 2 control wards o más", "compras menos", lambda p: p["datos_h"]["cw"] >= 2)
    comparar("Fase de líneas", "no mueres antes del minuto 10", "mueres antes del 10",
             lambda p: (not p["datos_h"]["muertes_10"]) if p["datos_h"].get("con_tl") else None)
    comparar("Muertes", f"mueres {CONFIG['muertes_max']} veces o menos", "mueres más",
             lambda p: p["datos_h"]["d"] <= CONFIG["muertes_max"])
    med_cs = _mediana([p["datos_h"].get("cs10") for p in ps if nosup(p)])
    if med_cs:
        comparar("Farmeo", f"llegas al minuto 10 con {med_cs} CS o más", "llegas con menos",
                 lambda p: None if p["datos_h"].get("cs10") is None else p["datos_h"]["cs10"] >= med_cs, nosup)
    comparar("Tu línea", "vas parejo o por delante de tu rival al minuto 14", "vas por detrás",
             lambda p: None if p["datos_h"].get("oro14_diff") is None else p["datos_h"]["oro14_diff"] >= 0)
    comparar("Morir solo", f"no mueres sin tu equipo después del minuto {CONFIG['fin_fase_lineas_min']}",
             "mueres sin tu equipo alguna vez",
             lambda p: (not p["datos_h"]["solo_14"]) if p["datos_h"].get("con_tl") and "solo_14" in p["datos_h"]
             else None)
    comparar("Peleas", "participas en la mitad o más de las kills de tu equipo", "participas en menos",
             lambda p: None if p["datos_h"].get("kp") is None else p["datos_h"]["kp"] >= 0.5)
    if rol_main:
        comparar("Tu rol", f"juegas {ROL_TXT.get(rol_main, rol_main)}", "juegas otro rol",
                 lambda p: p.get("rol") == rol_main if p.get("rol") else None)
    out.sort(key=lambda x: -x["dif"])
    return out[:6]


# =============================================================== RETOS (los eliges tu; el coach los mide)
# Como los "Challenges" de Mobalytics. Ninguna meta esta escrita a mano:
# - retos "de rango": la meta es la media REAL de los jugadores de ese rango con tu mismo campeon y linea
#   (Lolalytics, parche actual). Nivel Hierro = superar la media de Hierro; luego Bronce, Plata, Oro, Platino.
# - retos "personales" (lo que Lolalytics no publica): la meta sale de tus propias partidas: hacerlo mejor que
#   en el 70% de tus ultimas 20.
# Activas hasta 3; cada uno se comprueba solo y se supera cumpliendolo en 3 de 5 partidas.
RETO_NIVELES = ["Hierro", "Bronce", "Plata", "Oro", "Platino"]
RETO_TIERS = ["iron", "bronze", "silver", "gold", "platinum"]
RETO_TIER = {"IRON": 0, "BRONZE": 1, "SILVER": 2, "GOLD": 3}
RETOS_MAX = 3
_MEDIAS = {"mem": {}, "cola": queue.Queue(), "pedidas": set(), "hilo": None}


def lola_medias(rec, cid, rol, tier):
    """Medias por partida de un campeon en una linea y un rango (Lolalytics): muertes, kills, asistencias, CS,
    oro y daño. Se guarda en disco unos dias. None si no hay datos suficientes."""
    slug, linea = _lola_slug(rec, cid), LOLA_LINEA.get(rol)
    if not slug or not linea:
        return None

    def pedir():
        for parche in parches_actuales() or ["30"]:
            d = _http_json(f"{LOLA_API}?ep=build-full&v=1&patch={parche}&c={slug}&lane={linea}&tier={tier}"
                           "&queue=ranked&region=all", timeout=12)
            n = ((d or {}).get("header") or {}).get("n") or 0
            filas = (((d or {}).get("sidebar") or {}).get("stats") or {}).get("stats") or []
            st = {str(x[0]): float(x[2]) for x in filas if isinstance(x, list) and len(x) >= 3
                  and isinstance(x[2], (int, float))}
            if n >= 300 and "deaths" in st:
                # duracion media: Lolalytics da cuantas partidas hay en cada tramo de duracion (7 tramos de 5
                # minutos: menos de 15, 15-20 ... 40 o mas); se usa el punto medio de cada tramo, asi que es aproximada
                tr = (((d or {}).get("sidebar") or {}).get("time") or {}).get("time") or {}
                tot = sum(v for v in tr.values() if isinstance(v, (int, float)))
                dur = (sum(LOLA_TRAMO[k] * v for k, v in tr.items() if k in LOLA_TRAMO) / tot) if tot and set(tr) <= set(LOLA_TRAMO) else None
                return {"n": int(n), "parche": parche, "tier": tier, "min": dur, "deaths": st.get("deaths"), "kills": st.get("kills"),
                        "assists": st.get("assists"), "gold": st.get("gold"), "damage": st.get("damage"),
                        "cs": None if st.get("minions") is None else st["minions"] + (st.get("jungleCS") or 0)}
        return None
    return _lola_cache(f"lolamed2_{int(cid)}_{rol}_{tier}.json", pedir)


# =============================================================== COACH POR CAMPEON
REF_CAMPEON = "emerald_plus"          # con quien te comparas en la pagina de cada campeon (Lolalytics)


def lola_rivales(rec, cid, rol, tier=REF_CAMPEON):
    """Tu campeon contra cada rival de su linea (Lolalytics): {"wr", "n", "parche", "rivales": {id: [wr, n]}}.
    El wr de cada rival es el de TU campeon en ese enfrentamiento."""
    slug, linea = _lola_slug(rec, cid), LOLA_LINEA.get(rol)
    if not slug or not linea:
        return None

    def pedir():
        for parche in parches_actuales() or ["30"]:
            d = _http_json(f"{LOLA_API}?ep=build-full&v=1&patch={parche}&c={slug}&lane={linea}&tier={tier}"
                           "&queue=ranked&region=all", timeout=12)
            h = (d or {}).get("header") or {}
            filas = ((d or {}).get("enemy") or {}).get(linea) or []
            riv = {str(int(x[0])): [float(x[1]), int(x[5])] for x in filas
                   if isinstance(x, list) and len(x) >= 6 and x[0] and isinstance(x[1], (int, float))}
            if (h.get("n") or 0) >= 300 and riv:
                return {"wr": h.get("wr"), "n": int(h["n"]), "parche": parche, "rivales": riv}
        return None
    return _lola_cache(f"lolariv_{int(cid)}_{rol}_{tier}.json", pedir)


def pool_campeones(alm):
    """Tus campeones (por campeon y linea) con partidas, % de victorias y KDA, del mas jugado al menos."""
    with alm.lock:
        ps = [p for p in alm.d["partidas"].values() if p.get("rol") and (p.get("yo") or {}).get("campeon_id")]
    g = {}
    for p in ps:
        y = p["yo"]
        x = g.setdefault((y["campeon_id"], p["rol"]), {"cid": y["campeon_id"], "rol": p["rol"], "nombre": y.get("campeon") or "",
                                                       "n": 0, "v": 0, "k": 0, "d": 0, "a": 0, "ult": 0})
        x["n"] += 1
        x["v"] += bool(p.get("victoria"))
        x["k"], x["d"], x["a"] = x["k"] + (y.get("k") or 0), x["d"] + (y.get("d") or 0), x["a"] + (y.get("a") or 0)
        x["ult"] = max(x["ult"], p.get("creacion") or 0)
    for x in g.values():
        x["wr"] = round(100 * x["v"] / x["n"])
        x["kda"] = round((x["k"] + x["a"]) / max(x["d"], 1), 1)
    return sorted(g.values(), key=lambda x: (-x["n"], -x["ult"]))


def _media(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# (titulo de la tarjeta, explicacion). {yo} {ref} {c} se rellenan; {extra} depende del rol
CONSEJO_CAMPEON = {
    "cs": ("Farmea más", "Sacas {yo} CS por minuto y en Esmeralda+ con {c} sacan {ref}: son unos {dif15} súbditos "
                         "menos al minuto 15 (unos {oro15} de oro). Diez minutos de último golpe en la herramienta de "
                         "práctica antes de jugar y, antes de volver a base, empuja la oleada para no perder la siguiente."),
    "oro": ("Gana más oro", "Generas {yo} de oro por minuto; en Esmeralda+ con {c}, {ref}. {extra}"),
    "dano": ("Haz más daño", "Haces {yo} de daño a campeones por minuto; en Esmeralda+ con {c}, {ref}. Pega cuando el "
                             "rival va a por un súbdito o acaba de gastar su habilidad principal, y en las peleas "
                             "colócate donde puedas pegar sin ser el primero al que alcanzan."),
    "muertes": ("Muere menos", "Mueres {yo} veces cada 10 minutos; en Esmeralda+ con {c}, {ref}. Antes de pasar de la "
                               "mitad del mapa mira el minimapa: si faltan 2 o más rivales, no avances sin visión."),
    "kda": ("Elige mejor tus peleas", "Tu KDA con {c} es {yo}; en Esmeralda+, {ref}. Entra a pelear cuando tu equipo "
                                      "está cerca y con tus habilidades listas; si no llegas a tiempo, no vayas solo."),
}
EXTRA_ORO = {"support": "Completa pronto la misión de tu objeto de support y gasta el oro en tus objetos, no en "
                        "guardar: un support con objetos a tiempo pesa mucho más en las peleas.",
             "jungla": "Limpia campamentos entre gank y gank: un jungla que solo gankea se queda pobre."}


def ficha_campeon(alm, rec, cid, rol, red=True):
    """La pagina de un campeon tuyo: tus numeros contra Esmeralda+ (Lolalytics), lo que mas te separa de ellos,
    tus enfrentamientos y los rivales faciles y dificiles de ese campeon. red=False: sin pedir nada a internet."""
    with alm.lock:
        ps = sorted([p for p in alm.d["partidas"].values()
                     if (p.get("yo") or {}).get("campeon_id") == cid and p.get("rol") == rol],
                    key=lambda p: p.get("creacion") or 0)
    if not ps:
        return None
    nombre = ps[-1]["yo"].get("campeon") or rec.campeon(cid)

    def pm(f):                                           # media por minuto de juego
        return _media([f(p) / p["minutos"] for p in ps if p.get("minutos") and f(p) is not None])
    k, d, a = (sum(p["yo"].get(x) or 0 for p in ps) for x in ("k", "d", "a"))
    muertes = pm(lambda p: p["yo"].get("d"))
    yo = {"cs": pm(lambda p: p["yo"].get("cs")), "oro": pm(lambda p: p["yo"].get("oro")), "dano": pm(_r_dano_total),
          "muertes": None if muertes is None else 10 * muertes, "kda": (k + a) / max(d, 1)}
    m = lola_medias(rec, cid, rol, REF_CAMPEON) if red else None
    ref = {}
    if m and m.get("min"):
        mn = m["min"]
        ref = {"cs": m["cs"] / mn if m.get("cs") is not None else None,
               "oro": m["gold"] / mn if m.get("gold") is not None else None,
               "dano": m["damage"] / mn if m.get("damage") is not None else None,
               "muertes": 10 * m["deaths"] / mn if m.get("deaths") is not None else None,
               "kda": (m["kills"] + m["assists"]) / max(m["deaths"], 0.1) if m.get("deaths") is not None and m.get("kills") is not None else None}
    filas = []
    for clave, titulo, dec, menor in (("cs", "CS por minuto", 1, False), ("oro", "Oro por minuto", 0, False),
                                      ("dano", "Daño a campeones por minuto", 0, False),
                                      ("muertes", "Muertes cada 10 minutos", 1, True), ("kda", "KDA", 1, False)):
        if clave == "cs" and rol == "support":
            continue
        y, r = yo.get(clave), ref.get(clave)
        if y is None:
            continue
        f = {"clave": clave, "titulo": titulo, "yo": round(y, dec) if dec else round(y),
             "ref": None if r is None else (round(r, dec) if dec else round(r)), "menor": menor}
        if r:
            f["pct"] = round(100 * ((r / y if y else 2) if menor else y / r))      # 100 = como Esmeralda+
        filas.append(f)
    out = {"cid": cid, "nombre": nombre, "rol": rol, "n": len(ps), "v": sum(1 for p in ps if p.get("victoria")),
           "kda": round(yo["kda"], 1), "metricas": filas,
           "ref": {"tier": "Esmeralda+", "n": m.get("n"), "parche": m.get("parche")} if m else None}
    out["wr"] = round(100 * out["v"] / out["n"])
    con_pct = [f for f in filas if f.get("pct") is not None]
    if con_pct:
        peor, mejor = min(con_pct, key=lambda f: f["pct"]), max(con_pct, key=lambda f: f["pct"])
        if peor["pct"] < 95:
            tit, txt = CONSEJO_CAMPEON[peor["clave"]]
            dif = (ref["cs"] - yo["cs"]) if peor["clave"] == "cs" else 0
            fmt = (lambda v: _dec(v, 1)) if isinstance(peor["yo"], float) else (lambda v: _miles(v))
            out["mejora"] = {"clave": peor["clave"], "titulo": tit, "pct": peor["pct"],
                             "texto": txt.format(yo=fmt(peor["yo"]), ref=fmt(peor["ref"]), c=nombre,
                                                 dif15=round(dif * 15), oro15=_miles(round(dif * 15 * 21)),
                                                 extra=EXTRA_ORO.get(rol, "El oro sale del farmeo, las placas de las "
                                                                          "torres y los objetivos: no dejes oleadas "
                                                                          "al irte y presiona torres cuando tu rival "
                                                                          "no está."))}
        if mejor["pct"] >= 100 and mejor is not peor:
            out["fuerte"] = {"titulo": mejor["titulo"], "pct": mejor["pct"], "yo": mejor["yo"], "ref": mejor["ref"]}
    # tus enfrentamientos con este campeon
    lr = lola_rivales(rec, cid, rol) if red else None
    riv_ref = (lr or {}).get("rivales") or {}
    propios = {}
    for p in ps:
        rid = (p.get("datos_h") or {}).get("rival_id") or (p.get("rival") or {}).get("campeon_id")
        if not rid:
            continue
        x = propios.setdefault(rid, {"cid": rid, "nombre": (p.get("rival") or {}).get("campeon") or rec.campeon(rid),
                                     "n": 0, "v": 0, "cs10": [], "oro14": []})
        x["n"] += 1
        x["v"] += bool(p.get("victoria"))
        x["cs10"].append((p.get("datos_h") or {}).get("cs10_diff"))
        x["oro14"].append((p.get("datos_h") or {}).get("oro14_diff"))
    for x in propios.values():
        c10, o14 = _media(x["cs10"]), _media(x["oro14"])
        x["cs10"], x["oro14"] = (None if c10 is None else round(c10)), (None if o14 is None else round(o14))
        r = riv_ref.get(str(x["cid"]))
        x["wr_ref"] = r[0] if r and r[1] >= 100 else None
    out["propios"] = sorted(propios.values(), key=lambda x: (-x["n"], x["nombre"]))
    if riv_ref:
        minimo = max(150, 0.008 * (lr.get("n") or 0))     # fuera los picks raros de esa linea
        validos = [(int(c), wr, nn) for c, (wr, nn) in riv_ref.items() if nn >= minimo]
        fila = lambda t: {"cid": t[0], "nombre": rec.campeon(t[0]), "wr": round(t[1], 1), "n": t[2]}
        out["faciles"] = [fila(t) for t in sorted(validos, key=lambda t: -t[1])[:4]]
        out["dificiles"] = [fila(t) for t in sorted(validos, key=lambda t: t[1])[:4]]
        out["wr_ref"] = lr.get("wr")
    return out


LOLA_TRAMO = {"1": 12.5, "2": 17.5, "3": 22.5, "4": 27.5, "5": 32.5, "6": 37.5, "7": 42.5}
TIERS_ORDEN = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER"]
TIER_ES = {"IRON": "Hierro", "BRONZE": "Bronce", "SILVER": "Plata", "GOLD": "Oro", "PLATINUM": "Platino",
           "EMERALD": "Esmeralda", "DIAMOND": "Diamante", "MASTER": "Maestro"}


def tier_siguiente(tier):
    """El rango de encima del tuyo (sin clasificar cuenta como Hierro)."""
    t = (tier or "").upper()
    i = TIERS_ORDEN.index(t) if t in TIERS_ORDEN else 0
    return TIERS_ORDEN[min(i + 1, len(TIERS_ORDEN) - 1)]


def compra_base(rec, orden, tengo, oro):
    """¿Te alcanza el oro para algo de tu build? Solo mira TU inventario y TU oro.
    "listo": el objeto de support termino su mision y toca elegir la mejora (gratis).
    "completo": te alcanza para el siguiente objeto entero.
    "pieza": te alcanza para la pieza mas cara que te falta de ese objeto."""
    tengo = [int(x) for x in tengo if x]

    def info(i):
        return rec.items.get(str(i)) or {}
    for iid in orden:
        if iid not in tengo and _no_se_compra(rec, iid) and any(c in tengo for c in info(iid).get("de") or []):
            return {"tipo": "listo", "id": iid, "nombre": rec.item(iid)}
    so = siguiente_objeto(rec, orden, tengo, oro)
    if not so or so["falta"] is None:
        return None
    if so["falta"] == 0:
        return {"tipo": "completo", "id": so["id"], "nombre": so["nombre"]}
    resto, faltan = list(tengo), []
    for c in info(so["id"]).get("de") or []:
        if c in resto:
            resto.remove(c)
        else:
            faltan.append(c)
    cand = sorted(((info(c).get("precio") or 0, c) for c in faltan), reverse=True)
    if cand and cand[0][0]:
        c = cand[0][1]
        s2 = siguiente_objeto(rec, [c], resto, oro)
        if s2 and s2["falta"] == 0:
            return {"tipo": "pieza", "id": c, "nombre": rec.item(c), "para": so["nombre"]}
    return None


def medias_de(rec, cid, rol, nivel):
    """Medias del rango 'nivel' para ese campeon y linea. Si aun no estan, las pide aparte (una peticion cada
    medio segundo, para no cargar a Lolalytics) y devuelve None: llegan en unos segundos."""
    return medias_tier(rec, cid, rol, RETO_TIERS[min(nivel, len(RETO_TIERS) - 1)])


def medias_tier(rec, cid, rol, tier):
    k = (int(cid), rol, tier)
    if k in _MEDIAS["mem"]:
        return _MEDIAS["mem"][k] or None
    if k not in _MEDIAS["pedidas"]:
        _MEDIAS["pedidas"].add(k)
        _MEDIAS["cola"].put(k)
        if not _MEDIAS["hilo"] or not _MEDIAS["hilo"].is_alive():
            def trabajar():
                while True:
                    try:
                        c, r, t = _MEDIAS["cola"].get(timeout=20)
                    except queue.Empty:
                        return
                    m = lola_medias(rec, c, r, t)
                    if not m and t != "all":                 # campeon poco jugado en ese rango: media de todos
                        m = lola_medias(rec, c, r, "all")
                        if m:
                            m = dict(m, general=True)
                    _MEDIAS["mem"][(c, r, t)] = m or False
                    time.sleep(0.5)
            _MEDIAS["hilo"] = threading.Thread(target=trabajar, daemon=True)
            _MEDIAS["hilo"].start()
    return None


def _r_dano_total(p):
    yo = next((x for x in p.get("puestos") or [] if x.get("yo")), None)
    return yo["dano"] if yo else None


def _r_tarde(p):
    fs = [f for f in p.get("fases") or [] if f["de"] >= 14]
    mins = sum(f["a"] - f["de"] for f in fs)
    return round(sum(f["cs_min"] * (f["a"] - f["de"]) for f in fs) / mins, 1) if mins >= 4 else None


def _dh(campo, dec=None):
    def f(p):
        v = (p.get("datos_h") or {}).get(campo)
        return v if (v is None or dec is None) else round(v, dec)
    return f


def _lar(campo):
    return lambda p: len((p.get("datos_h") or {}).get(campo) or [])


# Cada reto: una meta principal y, en los de pelea y agresion, una condicion extra ("guarda"): no morir mas que
# la media de tu rango. Asi no se cumple un reto de kills regalando muertes (igual que hace Mobalytics).
# "media": la meta es la media real de tu rango (Lolalytics). Sin "media": la meta sale de tus propias partidas.
RETOS = [
    # ------------------------------------------------------------------ Pelea
    {"clave": "duelos", "hab": "Pelea", "nombre": "Duelos", "medida": "Oro contra tu rival de línea al minuto 14",
     "unidad": "de oro", "dec": 0, "valor": _dh("oro14_diff"), "sin": ("jungla",), "guarda": True,
     "como": "Intercambia solo cuando su habilidad principal esté en enfriamiento y vuelve a base con oro para un objeto."},
    {"clave": "kills_solo", "hab": "Pelea", "nombre": "Kills en solitario", "medida": "Kills sin ayuda de tu equipo",
     "unidad": "kills", "dec": 0, "minimo": 1, "valor": _dh("solo_kills"), "sin": ("support",), "guarda": True,
     "como": "Busca la kill cuando tengas ventaja de nivel u objeto y sepas dónde está su jungla."},
    {"clave": "peleas", "hab": "Pelea", "nombre": "Kills y asistencias", "medida": "Kills más asistencias en la partida",
     "unidad": "kills + asistencias", "media": ("kills", "assists"), "dec": 1, "guarda": True,
     "valor": lambda p: p["yo"]["k"] + p["yo"]["a"],
     "como": "Cuando tu equipo se junta para un objetivo, ve con ellos aunque dejes una oleada."},
    {"clave": "participacion", "hab": "Pelea", "nombre": "Participación en kills", "medida": "% de las kills de tu equipo en las que participas",
     "unidad": "%", "dec": 0, "valor": lambda p: None if (p.get("datos_h") or {}).get("kp") is None else round(100 * p["datos_h"]["kp"]),
     "como": "Mira el minimapa cada vez que termines una oleada: si hay pelea y llegas, ve."},
    {"clave": "dano", "hab": "Pelea", "nombre": "Daño a campeones", "medida": "Daño a campeones en la partida",
     "unidad": "de daño", "media": "damage", "dec": 0, "min": 20, "valor": _r_dano_total, "guarda": True,
     "como": "En las peleas, pega al que tengas a tiro sin morir: un jugador muerto no hace daño."},
    {"clave": "control_masas", "hab": "Pelea", "nombre": "Control en peleas", "medida": "Segundos de control aplicados a enemigos",
     "unidad": "segundos", "dec": 0, "min": 20, "valor": _dh("cc_seg"),
     "como": "Guarda tu aturdimiento para el enemigo que más daño hace, no para el primero que veas."},
    # ------------------------------------------------------------------ Agresión
    {"clave": "racha", "hab": "Agresión", "nombre": "Racha sin morir", "medida": "Mayor racha de kills seguidas sin morir",
     "unidad": "kills", "dec": 0, "minimo": 2, "valor": _dh("racha"), "sin": ("support",), "guarda": True,
     "como": "Después de una kill, vuelve a base y gasta el oro en vez de buscar otra pelea con poca vida."},
    {"clave": "ventaja_nivel", "hab": "Agresión", "nombre": "Ventaja de nivel", "medida": "Tu nivel menos el de tu rival al minuto 15",
     "unidad": "niveles", "dec": 0, "valor": _dh("nivel15_diff"), "sin": ("support",),
     "como": "No te vayas de la línea sin empujar la oleada: la experiencia que pierdes en base no vuelve."},
    {"clave": "ventaja_cs", "hab": "Agresión", "nombre": "Ganarle en farmeo", "medida": "Tu CS menos el de tu rival al minuto 10",
     "unidad": "CS", "dec": 0, "valor": _dh("cs10_diff"), "sin": ("support", "jungla"),
     "como": "Castiga cuando él vaya a dar el último golpe: es cuando no puede responderte."},
    # ------------------------------------------------------------------ Farmeo
    {"clave": "cs_total", "hab": "Farmeo", "nombre": "Farmeo de la partida", "medida": "CS en la partida",
     "unidad": "CS", "media": "cs", "dec": 0, "min": 20, "sin": ("support",), "valor": lambda p: p["yo"].get("cs"),
     "como": "Entre pelea y pelea, recoge la oleada más cercana. Nunca te quedes parado sin farmear."},
    {"clave": "cs_minuto", "hab": "Farmeo", "nombre": "Eficiencia de CS", "medida": "CS por minuto en toda la partida",
     "unidad": "por minuto", "dec": 1, "valor": _dh("csmin", 1), "sin": ("support",),
     "como": "Cada oleada vale casi lo mismo que una kill. No dejes ninguna morir en tu torre."},
    {"clave": "cs_temp", "hab": "Farmeo", "nombre": "Farmeo temprano", "medida": "CS al minuto 10",
     "unidad": "CS", "dec": 0, "valor": _dh("cs10"), "sin": ("support", "jungla"),
     "como": "Último golpe con calma: 10 minutos en la Herramienta de práctica antes de jugar."},
    {"clave": "cs_tarde", "hab": "Farmeo", "nombre": "Farmeo tardío", "medida": "CS por minuto después del minuto 14",
     "unidad": "por minuto", "dec": 1, "valor": _r_tarde, "sin": ("support",),
     "como": "Después de la línea, empuja la oleada lateral antes de cada objetivo y vuelve con tu equipo."},
    {"clave": "ingreso", "hab": "Farmeo", "nombre": "Oro de la partida", "medida": "Oro ganado en la partida",
     "unidad": "de oro", "media": "gold", "dec": 0, "min": 20, "valor": lambda p: p["yo"].get("oro"),
     "como": "Oro es farmeo, torres y kills seguras. Si no hay nada que hacer, hay una oleada que recoger."},
    {"clave": "oro_gastado", "hab": "Farmeo", "nombre": "Gastar el oro", "medida": "% de tu oro que llegaste a gastar",
     "unidad": "%", "dec": 0, "valor": _dh("oro_gastado_pct"),
     "como": "Oro en el bolsillo no pelea. Vuelve a base cuando te alcance para un objeto o una pieza grande."},
    {"clave": "oro_muerto", "hab": "Farmeo", "nombre": "No morir con oro", "medida": "Muertes con mucho oro sin gastar",
     "unidad": "muertes", "menor": True, "dec": 0, "valor": _lar("oro_muerto"),
     "como": "Antes de una pelea o un objetivo, mira tu oro: si te alcanza para un objeto, primero base."},
    # ------------------------------------------------------------------ Supervivencia
    {"clave": "morir_poco", "hab": "Supervivencia", "nombre": "Morir poco", "medida": "Muertes en la partida",
     "unidad": "muertes", "menor": True, "media": "deaths", "dec": 1, "valor": _dh("d"),
     "como": "Antes de avanzar, pregúntate dónde están sus 5. Si no lo sabes, no avances."},
    {"clave": "linea_viva", "hab": "Supervivencia", "nombre": "Línea sin morir", "medida": "Muertes antes del minuto 10",
     "unidad": "muertes", "menor": True, "dec": 0, "valor": _lar("muertes_10"),
     "como": "Con menos de media vida, vuelve a base. No esperes a la siguiente oleada."},
    {"clave": "ganks", "hab": "Supervivencia", "nombre": "Que no te gankeen", "medida": "Muertes por emboscada de su jungla en la línea",
     "unidad": "muertes", "menor": True, "dec": 0, "valor": _lar("muertes_gank"), "sin": ("jungla",),
     "como": "Si no ves a su jungla en el minimapa, juega del lado de tu torre y guarda tu escape."},
    {"clave": "picks", "hab": "Supervivencia", "nombre": "Que no te cacen", "medida": "Muertes solo, sin tu equipo, desde el minuto 14",
     "unidad": "muertes", "menor": True, "dec": 0, "valor": _lar("solo_14"),
     "como": "Desde el minuto 14 no cruces el río sin ver a sus jugadores en el minimapa."},
    {"clave": "lado_enemigo", "hab": "Supervivencia", "nombre": "No entrar solo", "medida": "Muertes en el lado enemigo sin tu equipo",
     "unidad": "muertes", "menor": True, "dec": 0, "valor": _dh("dives"),
     "como": "Para pasar del río necesitas ver dónde están ellos o ir con tu equipo. Si no, da la vuelta."},
    {"clave": "final_vivo", "hab": "Supervivencia", "nombre": "Vivo al final", "medida": "Muertes después del minuto 25",
     "unidad": "muertes", "menor": True, "dec": 0, "min": 28, "valor": _dh("d_25"),
     "como": "Pasado el minuto 25 una muerte tuya puede costar Barón o la partida: quédate detrás de tu equipo."},
    # ------------------------------------------------------------------ Visión
    {"clave": "vision", "hab": "Visión", "nombre": "Puntuación de visión", "medida": "Visión por minuto",
     "unidad": "por minuto", "dec": 2, "valor": _dh("vision_min", 2),
     "como": "Usa el amuleto cada vez que esté disponible y lleva un ward de control encima."},
    {"clave": "wards", "hab": "Visión", "nombre": "Poner wards", "medida": "Wards colocados por minuto",
     "unidad": "por minuto", "dec": 2, "valor": _dh("wards_min", 2),
     "como": "Un ward antes de cada objetivo y otro cada vez que vuelvas a la línea desde base."},
    {"clave": "control", "hab": "Visión", "nombre": "Wards de control", "medida": "Wards de control comprados",
     "unidad": "wards", "dec": 0, "minimo": 1, "valor": _dh("cw"),
     "como": "Un ward de control en cada vuelta a base en la que te sobre el oro."},
    {"clave": "limpiar", "hab": "Visión", "nombre": "Quitar su visión", "medida": "Wards enemigos destruidos",
     "unidad": "wards", "dec": 0, "minimo": 1, "valor": _dh("wards_quitados"),
     "como": "Cambia el amuleto por la lente desde el minuto 15 y úsala antes de cada objetivo."},
    # ------------------------------------------------------------------ Objetivos
    {"clave": "torres", "hab": "Objetivos", "nombre": "Daño a torres", "medida": "Daño a torres por minuto",
     "unidad": "por minuto", "dec": 0, "valor": _dh("torres_min", 0), "sin": ("support",),
     "como": "Después de ganar una pelea o matar a tu rival, pega a la torre antes de volver a base."},
    {"clave": "dano_objetivos", "hab": "Objetivos", "nombre": "Daño a objetivos", "medida": "Daño a torres, dragones, heraldo y Barón",
     "unidad": "de daño", "dec": 0, "min": 20, "valor": _dh("dano_objetivos"),
     "como": "Cuando tu equipo empieza un dragón o Barón, ve y pega: los objetivos ganan partidas, las kills no."},
    {"clave": "objeto_support", "hab": "Objetivos", "nombre": "Objeto de support a tiempo", "medida": "Minuto en que completas el objeto de support",
     "unidad": "minuto", "menor": True, "dec": 1, "solo": ("support",),
     "valor": lambda p: (p.get("obj_support") or {}).get("t2_min"),
     "como": "Gasta las cargas del objeto en cuanto las tengas, pegando al rival o rematando el súbdito que toca."},
]


def _reto_valor(r, p):
    if (p.get("rol") in r.get("sin", ()) or (r.get("solo") and p.get("rol") not in r["solo"])
            or (p.get("minutos") or 0) < r.get("min", 15)):
        return None
    try:
        return r["valor"](p)
    except Exception:
        return None


def _reto_meta_rango(r, rec, p, nivel):
    """(meta, pendiente): la media del rango para el campeon y la linea de ESA partida."""
    m = medias_de(rec, p["yo"]["campeon_id"], p.get("rol"), nivel)
    if m is None:
        return None, (int(p["yo"]["campeon_id"]), p.get("rol"), RETO_TIERS[min(nivel, 4)]) not in _MEDIAS["mem"]
    campos = r["media"] if isinstance(r["media"], tuple) else (r["media"],)
    if any(m.get(c) is None for c in campos):
        return None, False
    return round(sum(m[c] for c in campos), r.get("dec", 1)), False


def _percentil(vals, q):
    v = sorted(vals)
    if not v:
        return None
    k = (len(v) - 1) * q
    a, b = int(k), min(int(k) + 1, len(v) - 1)
    return v[a] + (v[b] - v[a]) * (k - a)


def _reto_meta_personal(r, valores):
    """Tu propia vara: hacerlo mejor que en el 70% de tus ultimas partidas. None con menos de 8."""
    if len(valores) < 8:
        return None
    m = _percentil(valores[-20:], 0.3 if r.get("menor") else 0.7)
    m = round(m, r.get("dec", 1)) if r.get("dec") else int(math.floor(m) if r.get("menor") else math.ceil(m))
    if r.get("minimo") is not None and not r.get("menor"):
        m = max(m, r["minimo"])              # "al menos una": un reto de hacer algo no puede pedir cero
    return m


def texto_reto(r):
    """Un reto en una linea que se entiende sola: que se mide y cuanto pide. Las metas de rango dependen del
    campeon y la linea de cada partida, asi que se dicen sin numero."""
    medida = r["medida"][:1].lower() + r["medida"][1:]
    op = "como mucho" if r.get("menor") else "al menos"
    if r.get("tipo") == "rango":
        return f"{r['nombre']}: {medida}, {'no más que' if r.get('menor') else 'igual o más que'} la media de {r.get('nivel_txt') or 'tu rango'} con tu campeón."
    m = r["meta"]
    if r.get("menor") and m == 0:
        return f"{r['nombre']}: {medida}: ninguna."
    num = (_dec(m, 2).rstrip("0").rstrip(",") if isinstance(m, float) else _miles(m) if abs(m) >= 1000 else str(m))
    if not r.get("menor") and isinstance(m, (int, float)) and m < 0:
        op = "perder como mucho por"
        num = num.lstrip("-")
    return f"{r['nombre']}: {medida}, {op} {num} {r.get('unidad') or ''}".rstrip() + "."


def retos_estado(alm, rec):
    """Estado de todos los retos: nivel, meta, tus ultimas partidas y si estan activos. Sube el nivel de un reto
    activo cuando lo cumples en 3 de tus ultimas 5 partidas desde que lo activaste (o subiste)."""
    with alm.lock:
        partidas = sorted([p for p in alm.d["partidas"].values() if p.get("datos_h")], key=lambda p: p.get("creacion") or 0)
        guardados = alm.d.setdefault("retos", {})
        tier = ((alm.d.get("rango") or {}).get("tier") or "").upper()
        base = RETO_TIER.get(tier, 4 if tier and tier not in ("NONE", "UNRANKED") else 0)
        cambio, pendiente, out = False, False, []
        for r in RETOS:
            st = guardados.get(r["clave"]) or {}
            rango = bool(r.get("media"))
            nivel = st.get("nivel", base if rango else 0)
            con_valor = [(p, _reto_valor(r, p)) for p in partidas]
            con_valor = [(p, v) for p, v in con_valor if v is not None]
            meta_p = None
            if not rango:
                previas = [v for p, v in con_valor if (p.get("creacion") or 0) <= (st.get("desde") or 10 ** 15)]
                meta_p = st.get("meta") if st.get("activo") and st.get("meta") is not None else _reto_meta_personal(r, previas)

            def fila(p, v):
                nonlocal pendiente
                if rango:
                    meta, pend = _reto_meta_rango(r, rec, p, nivel)
                    pendiente = pendiente or pend
                else:
                    meta = meta_p
                if meta is None:
                    return None
                ok = v <= meta if r.get("menor") else v >= meta
                guarda = None
                if r.get("guarda"):                          # sin morir mas que la media de tu rango
                    mm = medias_de(rec, p["yo"]["campeon_id"], p.get("rol"), base)
                    if mm and mm.get("deaths") is not None:
                        guarda = {"max": math.ceil(mm["deaths"]), "d": p["yo"]["d"]}
                        guarda["ok"] = guarda["d"] <= guarda["max"]
                        ok = ok and guarda["ok"]
                return {"id": p["id"], "valor": v, "meta": meta, "ok": ok, "guarda": guarda,
                        "campeon": p["yo"]["campeon"], "campeon_id": p["yo"]["campeon_id"], "rol": p.get("rol"),
                        "creacion": p.get("creacion")}
            ult = [x for x in (fila(p, v) for p, v in con_valor[-10:]) if x]
            res, subio = [], None
            if st.get("activo"):
                res = [x for x in (fila(p, v) for p, v in con_valor if (p.get("creacion") or 0) > (st.get("desde") or 0)) if x][-5:]
                if len(res) >= 3 and sum(1 for x in res if x["ok"]) >= 3:
                    st.setdefault("superados", []).append({"nivel": nivel, "ts": int(time.time() * 1000),
                                                           "estrellas": {3: 3, 4: 2}.get(len(res), 1)})
                    subio = RETO_NIVELES[min(nivel, 4)] if rango else "personal"
                    st["desde"] = res[-1]["creacion"]
                    if rango and nivel >= len(RETO_NIVELES) - 1:
                        st["activo"] = False
                    else:
                        st["nivel"] = nivel = nivel + 1
                        if not rango:                      # nueva vara con tus partidas hasta hoy
                            st["meta"] = meta_p = _reto_meta_personal(r, [v for _, v in con_valor])
                    guardados[r["clave"]] = st
                    cambio, res = True, []
            ref = ult[-1] if ult else None
            meta_txt = None
            if rango and ref:
                m = medias_de(rec, ref["campeon_id"], ref["rol"], nivel)
                meta_txt = (f"Media de {'todos los rangos' if (m or {}).get('general') else RETO_NIVELES[min(nivel, 4)]} con "
                            f"{ref['campeon']} de {ROL_TXT.get(ref['rol'], ref['rol'])}"
                            + (f" ({_miles(m['n'])} partidas, parche {m['parche']})" if m else "")
                            + ". Cambia según el campeón y la línea de cada partida.")
            elif not rango and meta_p is not None:
                meta_txt = "Tu propia vara: hacerlo mejor que en el 70% de tus últimas partidas."
            media = round(sum(x["valor"] for x in ult) / len(ult), 2) if ult else None
            meta = ref["meta"] if (rango and ref) else meta_p
            falta = None
            if media is not None and meta is not None:
                esc = max(abs(meta), 1)
                falta = (media - meta) / esc if r.get("menor") else (meta - media) / esc
            out.append({"clave": r["clave"], "hab": r["hab"], "nombre": r["nombre"], "medida": r["medida"],
                        "unidad": r["unidad"], "menor": bool(r.get("menor")), "como": r["como"],
                        "tipo": "rango" if rango else "personal", "nivel": nivel,
                        "nivel_txt": RETO_NIVELES[min(nivel, 4)] if rango else (f"Personal {nivel + 1}"),
                        "meta": meta, "meta_txt": meta_txt, "activo": bool(st.get("activo")), "res": res,
                        "media": media, "n_media": len(ult), "cumples": sum(1 for x in ult if x["ok"]),
                        "falta": falta, "subio": subio, "superados": len(st.get("superados") or []),
                        "estrellas": sum(x.get("estrellas", 1) for x in st.get("superados") or []),
                        "guarda": bool(r.get("guarda")), "origen": st.get("origen") if st.get("activo") else None,
                        "sin": list(r.get("sin") or ()),
                        "motivo": st.get("motivo") if st.get("activo") else None, "dejado": bool(st.get("dejado")),
                        "maximo": rango and nivel >= len(RETO_NIVELES) - 1 and bool(st.get("superados")) and not st.get("activo")})
        if cambio:
            alm.guardar()
    cand = sorted([x for x in out if not x["activo"] and x["falta"] is not None and x["falta"] > 0 and x["n_media"] >= 3],
                  key=lambda x: -x["falta"])[:3]
    for x in out:
        x["recomendado"] = x in cand
    return {"retos": out, "activos": sum(1 for x in out if x["activo"]), "max": RETOS_MAX, "niveles": RETO_NIVELES,
            "pendiente": pendiente}


def activar_reto(alm, rec, clave, activar, origen="tú", motivo=""):
    r = next((x for x in RETOS if x["clave"] == clave), None)
    if not r:
        return False, "Ese reto no existe."
    with alm.lock:
        g = alm.d.setdefault("retos", {})
        st = g.setdefault(clave, {})
        if activar and not st.get("activo"):
            if sum(1 for x in g.values() if x.get("activo")) >= RETOS_MAX:
                return False, f"Ya tienes {RETOS_MAX} retos activos. Deja uno antes de activar otro."
            ps = sorted([p for p in alm.d["partidas"].values() if p.get("datos_h")], key=lambda p: p.get("creacion") or 0)
            if not r.get("media"):
                meta = _reto_meta_personal(r, [v for v in (_reto_valor(r, p) for p in ps) if v is not None])
                if meta is None:
                    return False, "Aún no hay suficientes partidas tuyas para ponerte una meta en este reto (hacen falta 8)."
                st["meta"] = meta
            st.update(activo=True, desde=max([p.get("creacion") or 0 for p in ps] or [0]),
                      origen=origen, motivo=motivo, dejado=False)
        elif not activar:
            st["activo"] = False
            st["dejado"] = True                  # lo dejaste tu: el coach no te lo vuelve a asignar solo
        alm.guardar()
    return True, ""


_DESHACER = {}          # token -> (seccion, clave, copia de como estaba): "Deshacer" del aviso, unos minutos


def guardar_deshacer(seccion, clave, valor):
    """Guarda una copia exacta de alm.d[seccion][clave] antes de cambiarlo. Devuelve el token para deshacer."""
    import copy
    import secrets
    ahora = time.time()
    for k in [k for k, v in _DESHACER.items() if ahora - v[3] > 600]:
        _DESHACER.pop(k, None)
    token = secrets.token_hex(8)
    _DESHACER[token] = (seccion, clave, copy.deepcopy(valor), ahora)
    return token


def deshacer(alm, token):
    with alm.lock:                       # el mismo cerrojo con el que se guardan las copias: nada cambia a medias
        x = _DESHACER.get(token)
        if not x:
            return False, "Ya no se puede deshacer."
        seccion, clave, valor, _ = x
        g = alm.d.setdefault(seccion, {})
        if seccion == "retos" and (valor or {}).get("activo") and not (g.get(clave) or {}).get("activo") \
                and sum(1 for v in g.values() if v.get("activo")) >= RETOS_MAX:
            # el token se conserva: deja otro reto y vuelve a pulsar Deshacer (vale unos minutos)
            return False, f"Ya tienes {RETOS_MAX} retos activos: deja uno y vuelve a deshacer."
        _DESHACER.pop(token, None)
        if valor is None:
            g.pop(clave, None)
        else:
            g[clave] = valor
        alm.guardar()
    return True, "Deshecho."


def retos_de_partida(alm, rec, p):
    """Como te fue en tus retos activos en una partida concreta."""
    with alm.lock:
        g = dict(alm.d.get("retos") or {})
        tier = ((alm.d.get("rango") or {}).get("tier") or "").upper()
    base = RETO_TIER.get(tier, 4 if tier and tier not in ("NONE", "UNRANKED") else 0)
    out = []
    if not p.get("datos_h"):
        return out
    for r in RETOS:
        st = g.get(r["clave"]) or {}
        v = _reto_valor(r, p) if st.get("activo") else None
        if v is None:
            continue
        meta = _reto_meta_rango(r, rec, p, st.get("nivel", base))[0] if r.get("media") else st.get("meta")
        if meta is None:
            continue
        ok = v <= meta if r.get("menor") else v >= meta
        guarda = None
        if r.get("guarda"):
            mm = medias_de(rec, p["yo"]["campeon_id"], p.get("rol"), base)
            if mm and mm.get("deaths") is not None:
                guarda = {"max": math.ceil(mm["deaths"]), "d": p["yo"]["d"], "ok": p["yo"]["d"] <= math.ceil(mm["deaths"])}
                ok = ok and guarda["ok"]
        out.append({"nombre": r["nombre"], "medida": r["medida"], "valor": v, "meta": meta, "unidad": r["unidad"],
                    "menor": bool(r.get("menor")), "ok": ok, "guarda": guarda})
    return out


# =============================================================== ANALISIS ESCRITO POR IA (opcional, API gratis)
# Gemini de Google, plan gratuito, con TU clave (se crea gratis en aistudio.google.com/apikey y se guarda solo
# en tu PC, en datos\ia.json). La IA solo REDACTA: recibe los numeros que el coach ya calculo y tiene prohibido
# inventar datos, builds o jugadas. Si no hay clave, el coach funciona igual sin esta parte.
IA_URL = os.environ.get("COACH_IA_URL", "https://generativelanguage.googleapis.com/v1beta")
IA_ALIAS = "gemini-flash-latest"     # el nombre que Google mantiene apuntando a su Flash mas nuevo
_IA_MODELOS = {"clave": None, "lista": None, "ts": 0, "ok": None, "ok_ts": 0}
IA_PASO = {"txt": ""}                 # que esta haciendo la IA ahora (para mostrarlo mientras escribe)
IA_TRABAJOS = {}                      # partida -> {"estado": "en_curso" | "ok" | "error", "msg": ...}


def ia_modelos(clave):
    """Los modelos Flash que TU clave puede usar, preguntados a Google (se recuerda 6 horas): primero el alias
    del mas nuevo y luego las versiones de mas nueva a mas vieja. Nada escrito a mano salvo el alias."""
    m = _IA_MODELOS
    if m["clave"] == clave and m["lista"] and time.time() - m["ts"] < 6 * 3600:
        return m["lista"]
    lista = []
    try:
        req = urllib.request.Request(f"{IA_URL}/models?pageSize=200", headers={"x-goog-api-key": clave})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
        nombres = [(x.get("name") or "").split("/")[-1] for x in d.get("models") or []
                   if "generateContent" in (x.get("supportedGenerationMethods") or [])]
        vers = []
        for nmb in nombres:
            mm = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", nmb)
            if mm:
                vers.append((float(mm.group(1)), nmb))
        lista = ([IA_ALIAS] if IA_ALIAS in nombres else []) + [nmb for _, nmb in sorted(vers, reverse=True)]
    except Exception:
        pass
    if not lista:
        return [IA_ALIAS]
    m.update(clave=clave, lista=lista, ts=time.time())
    return lista

IA_FICH = DATOS / "ia.json"
IA_SISTEMA = (
    "Eres un coach de League of Legends que habla con un jugador de rango bajo que quiere subir. Escribes en "
    "español, directo y sin relleno. Reglas estrictas: 1) Usa SOLO los datos que te dan; no inventes números, "
    "objetos, runas, jugadas ni minutos. Si un dato no está, no lo menciones. 2) No recomiendes builds ni runas. "
    "2b) No presentes como error un número que cumple su meta (está en verde) o que supera al de su rival: "
    "si en esta partida no hay errores claros, dilo en una frase y céntrate en qué repetir. "
    "3) No culpes a sus compañeros ni le pidas cosas que dependen de otros: solo conductas que él controla en "
    "su rol. 4) Si su equipo tuvo un AFK o compañeros que murieron mucho, no le cargues esa derrota. "
    "5) Máximo 170 palabras. Formato exacto, tres bloques con estos títulos en una línea cada uno: "
    "'Lo que más te costó' (1 o 2 puntos, cada uno con el dato que lo demuestra), "
    "'En tu próxima partida' (2 acciones concretas y medibles), 'Lo que hiciste bien' (1 punto). "
    "Sin saludos, sin despedida, sin markdown.")


# Respaldo opcional si Gemini no responde: servicios gratuitos con modelos abiertos (Llama, gpt-oss...). Todos
# usan el mismo formato de API; el modelo se elige de la lista que el propio servicio da para tu clave.
IA_OTROS = {"groq": ("Groq", os.environ.get("COACH_IA_GROQ_URL", "https://api.groq.com/openai/v1")),
            "openrouter": ("OpenRouter", os.environ.get("COACH_IA_OPENROUTER_URL", "https://openrouter.ai/api/v1"))}


def ia_config():
    try:
        c = json.loads(IA_FICH.read_text(encoding="utf-8"))
        r = c.get("respaldo") or {}
        return {"clave": (c.get("clave") or "").strip(), "modelo": (c.get("modelo") or "").strip(),
                "respaldo": {"prov": r.get("prov") if r.get("prov") in IA_OTROS else "", "clave": (r.get("clave") or "").strip()}}
    except Exception:
        return {"clave": "", "modelo": "", "respaldo": {"prov": "", "clave": ""}}


def ia_guardar(clave, modelo="", respaldo=None):
    DATOS.mkdir(exist_ok=True)
    if respaldo is None:
        respaldo = ia_config()["respaldo"]
    IA_FICH.write_text(json.dumps({"clave": (clave or "").strip(), "modelo": (modelo or "").strip(),
                                   "respaldo": respaldo}), encoding="utf-8")


def ia_pedir_abierto(prov, clave, texto, sistema):
    """Pide el texto a un servicio con formato OpenAI (Groq, OpenRouter). Devuelve (respuesta, "Servicio: modelo")."""
    nombre, url = IA_OTROS[prov]
    cab = {"Authorization": f"Bearer {clave}", "Content-Type": "application/json", "User-Agent": "CoachLoL (uso personal)"}
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{url}/models", headers=cab), timeout=20) as r:
            ids = [x.get("id", "") for x in json.loads(r.read().decode("utf-8")).get("data") or []]
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError(f"{nombre} no acepta la clave. Revisa que la copiaste entera.")
        raise RuntimeError(f"{nombre} devolvió un error ({e.code}).")
    except Exception as e:
        raise RuntimeError(f"No pude conectar con {nombre} ({type(e).__name__}).")
    if prov == "openrouter":
        ids = [i for i in ids if i.endswith(":free")]            # solo los modelos gratuitos
    ids = [i for i in ids if not re.search(r"whisper|guard|tts|embed|speech|rerank|image|audio|vision|ocr", i.lower())]

    def tam(i):                                                  # el modelo mas grande suele ser el mas capaz
        ns = re.findall(r"(\d+(?:\.\d+)?)b\b", i.lower())
        return max([float(x) for x in ns] or [0])
    ultimo = f"{nombre} no tiene modelos de texto para tu clave."
    for modelo in sorted(ids, key=lambda i: -tam(i))[:3]:
        IA_PASO["txt"] = "Hay mucha gente usando la IA ahora: lo intento por otra vía…"
        t0 = time.time()
        cuerpo = json.dumps({"model": modelo, "temperature": 0.3,
                             "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": texto}]}).encode("utf-8")
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{url}/chat/completions", data=cuerpo, method="POST", headers=cab),
                                        timeout=40) as r:
                d = json.loads(r.read().decode("utf-8"))
            out = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            if out:
                log(f"IA: {nombre} {modelo} respondió en {time.time() - t0:.0f} s.")
                return out, f"{nombre}: {modelo}"
            ultimo = f"{nombre} respondió vacío."
        except urllib.error.HTTPError as e:
            ultimo = (f"Llegaste al límite gratis de {nombre} por ahora." if e.code == 429
                      else f"{nombre} devolvió un error ({e.code}).")
            log(f"IA: {nombre} {modelo} -> error {e.code}")
        except Exception as e:
            ultimo = f"No pude conectar con {nombre} ({type(e).__name__})."
            log(f"IA: {nombre} {modelo} -> sin respuesta tras {time.time() - t0:.0f} s ({type(e).__name__})")
    raise RuntimeError(ultimo)


def ia_pedir(texto, sistema=IA_SISTEMA, json_=False):
    """Devuelve (respuesta, modelo): primero Gemini y, si no responde, tu servicio de respaldo si pusiste uno.
    Lanza RuntimeError con un mensaje para mostrarle al jugador."""
    cfg = ia_config()
    rsp = cfg["respaldo"]
    if not cfg["clave"] and not (rsp["prov"] and rsp["clave"]):
        raise RuntimeError("Falta tu clave de Gemini.")
    error = None
    if cfg["clave"]:
        t_ini = time.time()
        try:
            return _ia_pedir_gemini(cfg, texto, sistema, json_)
        except RuntimeError as e:
            error = e
            # saturado o con limite: una segunda pasada tras unos segundos suele bastar (solo si la primera fue rapida)
            if ("saturado" in str(e) or "límite" in str(e)) and time.time() - t_ini < 30:
                IA_PASO["txt"] = "Hay mucha gente usando la IA ahora: espera unos segundos…"
                log("IA: Gemini saturado; reintento en 8 s.")
                time.sleep(8)
                try:
                    return _ia_pedir_gemini(cfg, texto, sistema, json_)
                except RuntimeError as e2:
                    error = e2
    if rsp["prov"] and rsp["clave"]:
        try:
            return ia_pedir_abierto(rsp["prov"], rsp["clave"], texto, sistema)
        except RuntimeError as e:
            error = RuntimeError(f"{error} {e}" if error else str(e))
    raise error


def _ia_pedir_gemini(cfg, texto, sistema, json_=False):
    modelos = ([cfg["modelo"]] if cfg["modelo"] else []) + [m for m in ia_modelos(cfg["clave"]) if m != cfg["modelo"]]
    # el ultimo modelo que respondio va primero durante 7 dias y los que se colgaron o estaban saturados en las
    # ultimas 24 h van al final (se recuerda al reabrir el coach): los mas nuevos suelen estar saturados en el plan
    # gratis y esperar 45 s por cada uno hacia que el analisis tardara minutos
    if not _IA_MODELOS["ok"]:
        try:
            g = json.loads((CACHE / "ia_ok.json").read_text(encoding="utf-8"))
            _IA_MODELOS["ok"], _IA_MODELOS["ok_ts"] = g.get("modelo"), g.get("ts") or 0
            _IA_MODELOS["lentos"] = {k: v for k, v in (g.get("lentos") or {}).items() if time.time() - v < 86400}
        except Exception:
            pass
    lentos = _IA_MODELOS.setdefault("lentos", {})
    bueno = (_IA_MODELOS["ok"] if _IA_MODELOS["ok"] in modelos and time.time() - _IA_MODELOS["ok_ts"] < 7 * 86400
             and lentos.get(_IA_MODELOS["ok"], 0) < _IA_MODELOS["ok_ts"] else None)     # si despues se colgo, ya no
    modelos = ([bueno] if bueno else []) + sorted([m for m in modelos if m != bueno],
                                                   key=lambda m: time.time() - lentos.get(m, 0) < 86400)

    def recordar():
        try:
            (CACHE / "ia_ok.json").write_text(json.dumps({"modelo": _IA_MODELOS["ok"], "ts": _IA_MODELOS["ok_ts"],
                                                          "lentos": lentos}), encoding="utf-8")
        except Exception:
            pass
    inicio = time.time()
    ultimo = "No pude hablar con Gemini."
    cuerpo = json.dumps({"systemInstruction": {"parts": [{"text": sistema}]},
                         "contents": [{"role": "user", "parts": [{"text": texto}]}],
                         "generationConfig": dict({"temperature": 0.3},
                                                  **({"responseMimeType": "application/json"} if json_ else {}))}).encode("utf-8")
    for modelo in modelos[:6]:
        if time.time() - inicio > 70:            # tope de tiempo: mejor pasar al respaldo que esperar minutos
            log("IA: Gemini tardó más de 70 segundos; paso al respaldo si lo hay.")
            break
        IA_PASO["txt"] = "Escribiendo tu análisis…" if modelo == modelos[0] else "Tarda un poco más de lo normal…"
        for intento in range(1):                 # si un modelo esta saturado se pasa al siguiente sin esperar
            t0 = time.time()
            req = urllib.request.Request(f"{IA_URL}/models/{modelo}:generateContent", data=cuerpo, method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": cfg["clave"]})
            try:
                with urllib.request.urlopen(req, timeout=45 if modelo == bueno else 25) as r:
                    d = json.loads(r.read().decode("utf-8"))
                partes = (((d.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
                out = "".join(x.get("text", "") for x in partes if not x.get("thought")).strip()
                if out:
                    _IA_MODELOS["ok"], _IA_MODELOS["ok_ts"] = modelo, time.time()
                    lentos.pop(modelo, None)
                    recordar()
                    log(f"IA: {modelo} respondió en {time.time() - t0:.0f} s.")
                    return out, modelo
                ultimo = "Gemini respondió vacío."
                break
            except urllib.error.HTTPError as e:
                try:
                    msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
                except Exception:
                    msg = ""
                if e.code in (401, 403) or (e.code == 400 and "API key" in msg):
                    raise RuntimeError("Gemini no acepta la clave. Revisa que la copiaste entera.")
                if e.code in (500, 502, 503, 504):
                    ultimo = "Gemini está saturado ahora mismo. Prueba en unos minutos."
                    lentos[modelo] = time.time()
                    recordar()
                elif e.code == 429:
                    ultimo = "Llegaste al límite gratis de Gemini por ahora. Prueba en unos minutos."
                elif e.code == 404:
                    ultimo = f"Gemini no encuentra el modelo {modelo}."
                else:
                    ultimo = f"Gemini devolvió un error ({e.code})" + (f": {msg[:120]}" if msg else ".")
                log(f"IA: {modelo} -> error {e.code}" + (f" ({msg[:100]})" if msg else ""))
                break
            except Exception as e:
                ultimo = f"No pude conectar con Gemini ({type(e).__name__})."
                log(f"IA: {modelo} -> sin respuesta tras {time.time() - t0:.0f} s ({type(e).__name__})")
                if "timeout" in type(e).__name__.lower() or "timed out" in str(e).lower():
                    lentos[modelo] = time.time()
                    recordar()
                break
    raise RuntimeError(ultimo)


def ia_texto_partida(alm, rec, p):
    """Lo que se le manda a la IA: solo numeros de la partida ya calculados por el coach. Sin tu nombre."""
    L = [p.get("texto_claude") or ""]
    try:
        L[0] = L[0].split("Dime, sin rodeos")[0].strip()
    except Exception:
        pass
    if p.get("fases"):
        L.append("Por fase: " + "; ".join(
            f"{f['nombre']} (min {f['de']}-{f['a']}): {f['cs_min']} CS/min, {f['muertes']} muertes, {f['ka']} kills+asistencias"
            for f in p["fases"]))
    if p.get("puesto"):
        L.append(f"Puesto entre los 10 jugadores según la nota del coach: {p['puesto']}.º")
    try:
        ses = sesion_coaching(alm, p)
        if ses and ses.get("hallazgos"):
            L.append("Errores caros que detectó el coach: " + "; ".join(f"{h['titulo']} ({h['evid']})" for h in ses["hallazgos"]))
    except Exception:
        pass
    try:
        rs = retos_de_partida(alm, rec, p)
        if rs:
            L.append("Sus retos activos en esta partida: " + "; ".join(
                f"{r['nombre']} ({r['medida']}): {r['valor']} con meta {'≤' if r['menor'] else '≥'} {r['meta']} -> "
                f"{'cumplido' if r['ok'] else 'no cumplido'}" for r in rs))
    except Exception:
        pass
    with alm.lock:
        ts = [t for t in alm.d.get("tareas") or [] if not t.get("hecha")]
    if ts:
        L.append("Tareas que ya tiene del coach: " + "; ".join(t.get("regla", "") for t in ts[:3]))
    return "\n".join(x for x in L if x)


def ia_json(texto, sistema):
    """Pide a la IA una respuesta en JSON y la devuelve como dict (o lanza RuntimeError)."""
    out, modelo = ia_pedir(texto, sistema, json_=True)
    try:
        d = json.loads(out[out.index("{"):out.rindex("}") + 1])
        if isinstance(d, dict):
            return d, modelo
    except Exception:
        pass
    raise RuntimeError("La IA no respondió en el formato pedido.")


IA_SIS_RETO = (
    "Eres un coach de League of Legends. Te doy los datos de la última partida de un jugador de rango bajo y un "
    "catálogo de retos medibles con su meta, su media reciente y cuántas veces la cumple. Elige EL reto que más le "
    "conviene trabajar ahora: el que ataca lo que más le costó en esta partida y en el que está lejos de la meta. "
    "Solo puedes elegir una 'clave' del catálogo; no inventes retos. No elijas algo que dependa de sus compañeros. "
    "Si su equipo tuvo un AFK, no bases la elección en el resultado. Responde SOLO un JSON: "
    '{"clave": "<clave del catálogo>", "motivo": "<una o dos frases en español, citando un dato de la partida>"}. '
    'Si ninguno conviene, responde {"clave": null, "motivo": ""}.')
IA_SIS_SESION = (
    "Eres un coach de League of Legends. El coach detectó un error en la partida de un jugador y le preguntó por "
    "qué pasó. El jugador respondió con sus palabras. Tu trabajo es clasificar su respuesta en UNA de las opciones "
    "dadas (cada una es una causa). Elige la que mejor describe lo que cuenta; si lo que cuenta no encaja en "
    'ninguna, responde con "opcion": null. Responde SOLO un JSON: {"opcion": "<id>", "porque": "<una frase en '
    'español explicando por qué encaja>"}.')


def asignar_reto(alm, rec, p, espera=True, forzar=False):
    """Tras una partida nueva, deja un reto activo si hay hueco: lo elige la IA dentro del catalogo y, si la IA no
    esta o falla, la regla (aquel en el que estas mas lejos de la meta). Uno por partida como mucho."""
    gid = str(p["id"])
    with alm.lock:
        if gid in (alm.d.get("retos_asig") or {}) and not forzar:
            return None
    est = retos_estado(alm, rec)
    for _ in range(4 if espera else 0):                    # las medias de Lolalytics pueden estar bajando
        if not est["pendiente"]:
            break
        time.sleep(6)
        est = retos_estado(alm, rec)
    if est["activos"] >= RETOS_MAX:
        return None
    cand = [r for r in est["retos"] if not r["activo"] and not r["dejado"] and not r["maximo"] and r["meta"] is not None
            and r["n_media"] >= 3 and r["falta"] is not None and r["falta"] > 0]
    if not cand:
        return None
    elegido, motivo, origen = None, "", "coach"
    if ia_config()["clave"] or ia_config()["respaldo"]["clave"]:
        try:
            cat = [{"clave": r["clave"], "habilidad": r["hab"], "nombre": r["nombre"], "medida": r["medida"],
                    "meta": ("<= " if r["menor"] else ">= ") + str(r["meta"]), "su_media": r["media"],
                    "la_cumple": f"{r['cumples']} de {r['n_media']}"} for r in cand]
            activos = [r["nombre"] for r in est["retos"] if r["activo"]]
            d, _ = ia_json(ia_texto_partida(alm, rec, p) + "\n\nRetos que ya tiene activos (no repetir): "
                           + (", ".join(activos) or "ninguno") + "\n\nCatálogo:\n" + json.dumps(cat, ensure_ascii=False),
                           IA_SIS_RETO)
            c = next((r for r in cand if r["clave"] == d.get("clave")), None)
            if c:
                elegido, motivo, origen = c, str(d.get("motivo") or "").strip()[:320], "IA"
            elif d.get("clave") is None:
                with alm.lock:
                    alm.d.setdefault("retos_asig", {})[gid] = None
                    alm.guardar()
                return None
        except RuntimeError as e:
            log(f"IA: no eligió reto ({e}). Lo elige la regla.")
    if not elegido:
        elegido = max(cand, key=lambda r: r["falta"])
        motivo = (f"Es donde estás más lejos de la meta: tu media es {_dec(elegido['media'], 2).rstrip('0').rstrip(',')} "
                  f"y la meta es {'≤' if elegido['menor'] else '≥'} {elegido['meta']}.")
    ok, _ = activar_reto(alm, rec, elegido["clave"], True, origen, motivo)
    if not ok:
        return None
    with alm.lock:
        alm.d.setdefault("retos_asig", {})[gid] = elegido["clave"]
        alm.guardar()
    log(f"Reto asignado por {'la IA' if origen == 'IA' else 'el coach'}: {elegido['nombre']}. {motivo}")
    return elegido["clave"]


def ia_sesion_texto(alm, gid, clave, texto):
    """Tu respuesta escrita a la pregunta de la sesion: la IA la clasifica en una de las causas del coach y a
    partir de ahi todo sigue igual (causa, regla y tarea medible). Devuelve (ok, mensaje)."""
    d = HALL.get(clave)
    texto = (texto or "").strip()[:600]
    if not d or len(texto) < 4:
        return False, "Escribe qué pasó con tus palabras."
    with alm.lock:
        p = alm.d["partidas"].get(str(gid))
    if not p:
        return False, "Esa partida no existe."
    h = next((x for x in hallazgos_de(p)[:2] if x["clave"] == clave), None)
    if not h:
        return False, "Ese error ya no está en esta sesión."
    try:
        r, _ = ia_json("Error detectado: " + d["titulo"] + ". " + str(h.get("evid") or "") + "\nPregunta del coach: "
                       + d["pregunta"] + "\nRespuesta del jugador: " + texto + "\nOpciones:\n"
                       + json.dumps([{"id": o["id"], "causa": o["diag"], "texto": o["texto"]} for o in d["opciones"]],
                                    ensure_ascii=False), IA_SIS_SESION)
    except RuntimeError as e:
        return False, f"{e} Elige una de las opciones."
    op = next((o for o in d["opciones"] if o["id"] == r.get("opcion")), None)
    if not op:
        return False, "Lo que cuentas no encaja en ninguna de las causas. Elige la que más se parezca."
    if not responder_sesion(alm, str(gid), clave, op["id"]):
        return False, "No pude guardar tu respuesta."
    with alm.lock:
        ses = alm.d["sesiones"][str(gid)]
        ses.setdefault("texto", {})[clave] = {"texto": texto, "porque": str(r.get("porque") or "")[:300]}
        alm.guardar()
    return True, ""


def ia_analizar(alm, rec, gid, forzar=False):
    """Analisis escrito de una partida (se guarda para no gastar peticiones). Devuelve (dict, error)."""
    with alm.lock:
        p = alm.d["partidas"].get(str(gid))
        previo = (alm.d.get("ia") or {}).get(str(gid))
    if not p:
        return None, "Esa partida no existe."
    if previo and not forzar:
        return previo, None
    try:
        texto, modelo = ia_pedir(ia_texto_partida(alm, rec, p))
    except RuntimeError as e:
        return None, str(e)
    r = {"texto": texto, "modelo": modelo, "ts": int(time.time() * 1000)}
    with alm.lock:
        alm.d.setdefault("ia", {})[str(gid)] = r
        alm.guardar()
    return r, None


def calendario(partidas, semanas=10):
    """Tus ultimos dias de juego: partidas y victorias por dia (para pintarlo como calendario)."""
    por = {}
    for p in partidas:
        if p.get("fin_ts"):
            x = por.setdefault(dia_de(p["fin_ts"]), [0, 0])
            x[0] += 1
            x[1] += 1 if p["victoria"] else 0
    hoy = datetime.strptime(dia_de(int(time.time() * 1000)), "%Y-%m-%d")
    ini = hoy - timedelta(days=hoy.weekday() + 7 * (semanas - 1))
    dias = []
    d = ini
    while d <= hoy:
        k = d.strftime("%Y-%m-%d")
        n, v = por.get(k, [0, 0])
        dias.append({"dia": k, "n": n, "v": v})
        d += timedelta(days=1)
    return dias


def tendencia_campeones(todas):
    """Por cada campeon que juegas (6+ partidas): tus ultimas partidas con el contra las anteriores."""
    por = {}
    for p in todas:
        por.setdefault(p["yo"]["campeon_id"], []).append(p)

    def res(ps):
        mins = sum(p.get("minutos") or 0 for p in ps) or 1
        d = sum(p["yo"]["d"] for p in ps)
        con_cs = [p for p in ps if p.get("rol") != "support"]
        m_cs = sum(p.get("minutos") or 0 for p in con_cs)
        return {"n": len(ps), "wr": round(100 * sum(1 for p in ps if p["victoria"]) / len(ps)),
                "kda": round(sum(p["yo"]["k"] + p["yo"]["a"] for p in ps) / max(d, 1), 1),
                "muertes": round(d / len(ps), 1),
                "csmin": round(sum(p["yo"]["cs"] for p in con_cs) / m_cs, 1) if m_cs else None,
                "nota": round(sum(p["veredicto"]["nota"] for p in ps) / len(ps), 1)}
    out = []
    for cid, ps in por.items():
        if len(ps) < 6:
            continue
        k = min(10, len(ps) // 2)
        ahora, antes = res(ps[-k:]), res(ps[-2 * k:-k])
        dn = round(ahora["nota"] - antes["nota"], 1)
        out.append({"id": cid, "nombre": ps[-1]["yo"]["campeon"], "total": len(ps), "k": k,
                    "ahora": ahora, "antes": antes, "todo": res(ps),
                    "tendencia": "sube" if dn >= 0.5 else "baja" if dn <= -0.5 else "igual", "dif_nota": dn})
    return sorted(out, key=lambda x: -x["total"])[:6]


def progreso(alm):
    with alm.lock:
        todas = sorted([p for p in alm.d["partidas"].values() if p.get("datos_h")],
                       key=lambda p: p.get("creacion") or 0)
        animos = dict(alm.d["animo"])
        avisos = dict(alm.d["avisos"])
        rh = list(alm.d.get("rango_hist") or [])
    ult, prev = todas[-20:], todas[-40:-20]

    # Perfil por areas
    def areas_de(ps):
        acc = {}
        for p in ps:
            for k, v in _areas_partida(p).items():
                if v is not None:
                    acc.setdefault(k, []).append(v)
        return {k: round(sum(v) / len(v)) for k, v in acc.items()}

    a_ult, a_prev = areas_de(ult), (areas_de(prev) if len(prev) >= 5 else {})
    dias_aviso = []
    por_dia = Counter(dia_de(p.get("fin_ts") or 0) for p in todas if p.get("cuenta_anti"))
    for dia, av in avisos.items():
        if av.get("motivos"):
            dias_aviso.append(por_dia.get(dia, 0) <= av.get("partidas_al_aviso", 0))
    if dias_aviso:
        a_ult["disciplina"] = round(100 * sum(dias_aviso) / len(dias_aviso))
    detalles = {
        "supervivencia": (lambda: f"{_dec(_prom([p['datos_h']['d'] for p in ult]))} muertes por partida; "
                                  f"{round(100 * _prom([0 if p['datos_h']['muertes_10'] else 1 for p in ult]))}% "
                                  "de partidas sin morir antes del 10"),
        "farmeo": (lambda: f"{_dec(_prom([p['datos_h'].get('csmin') for p in ult if p.get('rol') != 'support']))} "
                           "CS por minuto"),
        "vision": (lambda: f"{_dec(_prom([p['datos_h']['cw'] for p in ult]))} control wards por partida"),
        "linea": (lambda: "de media, " + _signo(_prom([p['datos_h'].get('oro14_diff') for p in ult]), True)
                          + " de oro contra tu rival al minuto 14"),
        "impacto": (lambda: "según tu rol en cada partida"),
        "disciplina": (lambda: f"paraste a tiempo {sum(dias_aviso)} de {len(dias_aviso)} "
                               f"{'día' if len(dias_aviso) == 1 else 'días'} con aviso"),
    }
    perfil = []
    for k, nombre, expl in AREAS:
        v = a_ult.get(k)
        txt = None
        if v is not None:
            try:
                txt = detalles[k]()
            except Exception:
                txt = None
        perfil.append({"clave": k, "nombre": nombre, "explica": expl, "punt": v, "detalle": txt,
                       "cambio": (v - a_prev[k]) if (v is not None and k in a_prev) else None,
                       "nivel": None if v is None else ("Fuerte" if v >= 75 else "En camino" if v >= 50 else "Débil")})

    # Tendencias (ultimas 30)
    serie = [{"id": p["id"], "fecha": p["fecha"], "victoria": p["victoria"], "campeon": p["yo"]["campeon"],
              "muertes": p["datos_h"]["d"], "cs10": p["datos_h"].get("cs10") if p.get("rol") != "support" else None,
              "cw": p["datos_h"]["cw"], "oro14": p["datos_h"].get("oro14_diff"),
              "nota": p["veredicto"]["nota"]} for p in todas[-30:]]

    # LP
    orden_t = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND"]
    orden_d = {"IV": 0, "III": 1, "II": 2, "I": 3}
    lp = []
    for r in rh:
        if r.get("tier") in orden_t:
            valor = orden_t.index(r["tier"]) * 400 + orden_d.get(r.get("division"), 0) * 100 + (r.get("lp") or 0)
            if not lp or lp[-1]["valor"] != valor:
                lp.append({"ts": r["ts"], "valor": valor, "texto": f"{r.get('texto', '')} {r.get('lp', 0)} LP"})

    # Patrones
    patrones = []
    dias = {}
    for p in todas:
        dias.setdefault(dia_de(p.get("fin_ts") or 0), []).append(p)
    tras_d, tras_v, tras_mal, n1, n2, n3 = [], [], [], [], [], []
    for lst in dias.values():
        lst.sort(key=lambda p: p.get("fin_ts") or 0)
        for i, p in enumerate(lst):
            (n1 if i == 0 else n2 if i == 1 else n3).append(p)
            if i:
                anterior = lst[i - 1]
                (tras_v if anterior["victoria"] else tras_d).append(p)
                if (animos.get(anterior["id"]) or {}).get("estado") in ("tilt", "molesto"):
                    tras_mal.append(p)
    if len(tras_d) >= 3 and len(tras_v) >= 3:
        patrones.append({"titulo": "Después de perder",
                         "texto": f"Después de una derrota ganas el {_wr(tras_d)}% ({len(tras_d)} partidas). "
                                  f"Después de una victoria, el {_wr(tras_v)}% ({len(tras_v)}).",
                         "malo": _wr(tras_d) + 10 <= _wr(tras_v)})
    if len(n1) >= 3 and len(n3) >= 3:
        patrones.append({"titulo": "Partidas seguidas",
                         "texto": f"Tu primera partida del día: {_wr(n1)}% de victorias ({len(n1)}). "
                                  + (f"La segunda: {_wr(n2)}% ({len(n2)}). " if len(n2) >= 3 else "")
                                  + f"De la tercera en adelante: {_wr(n3)}% ({len(n3)}).",
                         "malo": _wr(n3) + 10 <= _wr(n1)})
    if len(tras_mal) >= 3:
        patrones.append({"titulo": "Jugar molesto",
                         "texto": f"Cuando sigues jugando después de marcar molesto o tilt ganas el {_wr(tras_mal)}% "
                                  f"({len(tras_mal)} partidas).", "malo": _wr(tras_mal) < 45})
    patrones += _patrones_metricas(todas)
    franjas = [("la mañana", 5, 12), ("la tarde", 12, 19), ("la noche", 19, 24), ("la madrugada", 0, 5)]
    por_franja = {n: [p for p in todas if p.get("creacion") and a <= datetime.fromtimestamp(p["creacion"] / 1000).hour < b]
                  for n, a, b in franjas}
    validas = {n: v for n, v in por_franja.items() if len(v) >= 3}
    if len(validas) >= 2:
        mejor = max(validas, key=lambda n: _wr(validas[n]))
        peor = min(validas, key=lambda n: _wr(validas[n]))
        if _wr(validas[mejor]) - _wr(validas[peor]) >= 10:
            patrones.append({"titulo": "Horario",
                             "texto": f"Ganas más en {mejor} ({_wr(validas[mejor])}% en {len(validas[mejor])} partidas) "
                                      f"y menos en {peor} ({_wr(validas[peor])}% en {len(validas[peor])}).",
                             "malo": False})

    # Insignias
    insignias = []
    if len(ult) >= 5:
        con_tl = [p for p in ult if p["datos_h"].get("con_tl")]
        m10 = _prom([len(p["datos_h"]["muertes_10"]) for p in con_tl])
        if m10 is not None and m10 >= 1:
            insignias.append(("Muere temprano", f"{_dec(m10)} muertes antes del 10 por partida", False))
        elif m10 is not None and m10 <= 0.3:
            insignias.append(("Sobrevive la fase de líneas", f"{_dec(m10)} muertes antes del 10 por partida", True))
        nosup = [p for p in ult if p.get("rol") != "support"]
        if len(nosup) >= 5:
            csm = _prom([p["datos_h"].get("csmin") for p in nosup])
            if csm is not None and csm >= 6:
                insignias.append(("Farmeador", f"{_dec(csm)} CS por minuto", True))
            elif csm is not None and csm < 4.5:
                insignias.append(("Farmeo flojo", f"{_dec(csm)} CS por minuto", False))
        cw = _prom([p["datos_h"]["cw"] for p in ult])
        if cw >= 2:
            insignias.append(("Controla la visión", f"{_dec(cw)} control wards por partida", True))
        tops = [p for p in ult if p.get("rol") == "top"]
        if len(tops) >= 5 and (_prom([p["datos_h"].get("torres_min") for p in tops]) or 0) >= CONFIG["torres_min"][0]:
            insignias.append(("Tira torres", f"{int(_prom([p['datos_h'].get('torres_min') for p in tops]))} "
                                             "de daño a torres por minuto en top", True))
        camps = Counter(p["yo"]["campeon"] for p in ult[-10:])
        if len(camps) >= 4:
            insignias.append(("Pool disperso", f"{len(camps)} campeones distintos en tus últimas 10", False))
        elif camps and camps.most_common(1)[0][1] >= 7:
            c, n = camps.most_common(1)[0]
            insignias.append(("Fiel a su campeón", f"{c}: {n} de tus últimas 10", True))
        if any(pt["titulo"] == "Después de perder" and pt["malo"] for pt in patrones):
            insignias.append(("Se calienta en racha", "pierdes más después de perder", False))
    return {"perfil": perfil, "serie": serie, "lp": lp, "patrones": patrones, "n": len(todas),
            "insignias": [{"nombre": a, "detalle": b, "bueno": c} for a, b, c in insignias],
            "tope_dia": tope_personal(todas), "avance": avance(alm), "campeones": tendencia_campeones(todas),
            "calendario": calendario(todas)}


# =============================================================== REVISION DE MUERTES
# Lo que las estadisticas no ven: POR QUE moriste. Lo decides tu viendo la repeticion.
CAUSAS = {
    "gank": {"nombre": "Me ganquearon sin verlo venir", "tipo": "Fundamentos",
             "consejo": "Antes de pasar de la mitad de tu línea, piensa dónde vio todo el mundo al jungla rival por "
                        "última vez. Si no lo sabes, juega como si estuviera en el arbusto de al lado."},
    "empuje": {"nombre": "Me quedé empujando demasiado lejos", "tipo": "Fundamentos",
               "consejo": "Si tu oleada llegó a su torre y no sabes dónde están su jungla y su mid, vuelve o retrocede. "
                          "Empujar sin información es regalar la vida."},
    "duelo": {"nombre": "Perdí un 1 contra 1 que no tenía que pelear", "tipo": "Campeón y matchup",
              "consejo": "Pelea solo cuando su habilidad principal esté en enfriamiento o tengas ventaja de nivel u "
                         "objetos. Si no, farmea y deja que él se arriesgue."},
    "pelea": {"nombre": "Entré a una pelea con menos aliados", "tipo": "Decisiones",
              "consejo": "Cuenta antes de entrar: si ellos son más o falta alguien de tu equipo, no entres aunque "
                         "parezca fácil."},
    "perseguir": {"nombre": "Perseguí demasiado", "tipo": "Decisiones",
                  "consejo": "Si el rival huye hacia su torre o hacia la niebla, déjalo ir. Una kill no vale tu vida."},
    "solo": {"nombre": "Me atraparon caminando solo por el mapa", "tipo": "Fundamentos",
             "consejo": "Desde el minuto 14, muévete con un aliado o por zonas que tu equipo ve. No cruces solo la "
                        "jungla enemiga ni entres primero a un arbusto sin visión."},
    "ejecucion": {"nombre": "Fallé habilidades o el Flash", "tipo": "Mecánicas",
                  "consejo": "Antes de jugar, 5 minutos en la Herramienta de práctica repitiendo tu combo hasta "
                             "que salga sin pensar."},
    "util": {"nombre": "Muerte útil o inevitable", "tipo": "Sin error",
             "consejo": "Si cambiaste tu vida por un objetivo o por salvar a otro, bien jugado."},
}


def causa_sugerida(m, rival_cid=None):
    """Pista del coach a partir de los datos. La decision final es tuya, viendo la repeticion."""
    temprana = m["ts"] < CONFIG["fin_fase_lineas_min"] * 60000
    if m.get("asistentes") == 0 and m.get("killer_id") and m.get("n_enemigos") == 1 and temprana:
        # 1 contra 1 con tu rival de linea = duelo; si te mato otro (su jungla, su mid) = gank
        return "duelo" if rival_cid is None or m.get("killer_cid") == rival_cid else "gank"
    if temprana and m.get("n_enemigos", 0) >= 2:
        return "empuje" if m.get("zona") == "enemiga" else "gank"
    if not temprana and m.get("sin_equipo"):
        return "solo"
    if not temprana and m.get("n_enemigos", 0) >= 3:
        return "pelea"
    return None


def muertes_clave(p):
    """Las 2 muertes que mas vale la pena revisar: las tempranas primero y la mas cara."""
    ms = p.get("muertes") or []
    fase = CONFIG["fin_fase_lineas_min"] * 60000
    elegidas = [m for m in ms if m["ts"] < fase][:2]
    cara = next((m for m in ms if m.get("mas_cara")), None)
    if cara and cara not in elegidas:
        elegidas = (elegidas[:1] + [cara]) if len(elegidas) >= 2 else elegidas + [cara]
    if not elegidas:
        elegidas = ms[:2]
    return [m["ts"] for m in elegidas]


def stats_revision(alm):
    with alm.lock:
        revs = list((alm.d.get("revision") or {}).values())
    errores = [r for r in revs if r.get("causa") in CAUSAS and r["causa"] != "util"]
    total = len([r for r in revs if r.get("causa") in CAUSAS])
    if not total:
        return {"total": 0, "causas": [], "principal": None}
    c = Counter(r["causa"] for r in errores)
    causas = [{"clave": k, "nombre": CAUSAS[k]["nombre"], "tipo": CAUSAS[k]["tipo"], "n": n,
               "pct": round(100 * n / max(1, len(errores)))} for k, n in c.most_common()]
    principal = None
    if len(errores) >= 5 and causas:
        k = causas[0]["clave"]
        notas = [r.get("nota") for r in errores if r["causa"] == k and r.get("nota")]
        principal = {**causas[0], "consejo": CAUSAS[k]["consejo"], "tu_nota": notas[-1] if notas else None}
    return {"total": total, "errores": len(errores), "causas": causas, "principal": principal,
            "utiles": total - len(errores)}


# =============================================================== ENTRENAMIENTO DE CS
def meta_entreno(alm):
    with alm.lock:
        hist = [x for x in alm.d.get("entrenamientos") or [] if x.get("cs10") is not None]
    meta = CONFIG["entreno_meta_inicial"]
    racha = 0
    for x in hist:   # sube 10 cuando la cumples 2 veces seguidas
        if x["cs10"] >= meta:
            racha += 1
            if racha >= 2 and meta < 90:
                meta, racha = meta + 10, 0
        else:
            racha = 0
    return meta


ROLES_FARMEO = ("top", "mid", "bot")      # roles en los que tu oro sale del ultimo golpe (ni support ni jungla)


def estado_entreno(alm, plan=None):
    """El ejercicio de ultimo golpe y para quien es: solo tiene sentido en un rol que farmea. "principal" dice si
    ese rol es tu rol principal (entonces es tu calentamiento de cada dia) o solo el secundario (queda como opcion)."""
    with alm.lock:
        hist = list(alm.d.get("entrenamientos") or [])
    hoy = dia_de(time.time() * 1000)
    out = {"meta": meta_entreno(alm), "hoy": any(dia_de(x["ts"]) == hoy for x in hist),
           "ultimos": hist[-15:], "total": len(hist)}
    roles = ((plan if plan is not None else plan_actual(alm)) or {}).get("roles") or {}
    pr, se = roles.get("principal"), roles.get("secundario")
    if not pr:                               # todavia sin roles elegidos: se ofrece a todos
        out.update({"aplica": True, "principal": True, "rol": None, "rol_txt": "", "campeon": None, "campeon_id": None})
        return out
    rol = pr if pr in ROLES_FARMEO else se if se in ROLES_FARMEO else None
    pool = ((roles.get("pools") or {}).get(rol) or []) if rol else []
    out.update({"aplica": rol is not None, "principal": pr in ROLES_FARMEO, "rol": rol,
                "rol_txt": ROL_TXT.get(rol or "", ""), "campeon": pool[0]["nombre"] if pool else None,
                "campeon_id": pool[0]["id"] if pool else None})
    return out


class EntrenoVivo:
    """Ejercicio de ultimo golpe en la Herramienta de practica: 10 minutos, sin pelear."""

    def __init__(self, meta):
        self.meta = meta
        self.guardado = False

    def actualizar(self, data, guardar):
        t = float((data.get("gameData") or {}).get("gameTime") or 0)
        ap = data.get("activePlayer") or {}
        yo = _yo_en_vivo(data)
        if not yo:
            return None
        cs = int((yo.get("scores") or {}).get("creepScore") or 0)
        aviso, tono = None, "azul"
        if t < 600:
            esperado = int(self.meta * t / 600)
            estado = f"CS ~{cs}   |   ritmo para {self.meta}: {esperado}   |   faltan {int(600 - t) // 60}:{int(600 - t) % 60:02d}"
        else:
            estado = f"Terminado: ~{cs} CS en 10 minutos (meta {self.meta})"
            if not self.guardado:
                self.guardado = True
                guardar(cs, yo.get("championName", ""))
                ok = cs >= self.meta
                aviso, tono = (f"Ejercicio guardado: ~{cs} CS. " + ("Meta cumplida." if ok else "Otra vez mañana.")), \
                    ("verde" if ok else "rojo")
        return {"modo": "partida", "titulo": "Entrenamiento de CS",
                "regla": f"Último golpe durante 10 minutos: meta {self.meta} CS",
                "estado": estado, "extra": "Sin objetos de daño. Solo último golpe, nada de pelear.",
                "aviso": aviso, "tono": tono}


# Referencias de CS por minuto por rango (guía de dodge.gg, 2026)
REFERENCIA_CS = [("Hierro", 3.0, 4.0), ("Bronce", 4.0, 5.0), ("Plata", 5.0, 6.0), ("Oro", 6.0, 7.0)]


def referencia_rango(alm):
    with alm.lock:
        ps = sorted([p for p in alm.d["partidas"].values() if p.get("datos_h")],
                    key=lambda p: p.get("creacion") or 0)[-20:]
    nosup = [p["datos_h"].get("csmin") for p in ps if p.get("rol") not in ("support", "jungla")]
    csm = _prom(nosup)
    d = _prom([p["datos_h"]["d"] for p in ps])
    nivel = None
    if csm is not None:
        nivel = "Hierro"
        for nombre, lo, hi in REFERENCIA_CS:
            if csm >= lo:
                nivel = nombre
        if csm >= 7:
            nivel = "Oro o más"
    return {"csmin": None if csm is None else round(csm, 1), "muertes": None if d is None else round(d, 1),
            "nivel_cs": nivel, "tabla": [{"rango": n, "de": lo, "a": hi} for n, lo, hi in REFERENCIA_CS],
            "n": len(nosup)}


# =============================================================== GUIA: PLAN DE PARTIDA Y SIGUIENTE PASO
def plan_partida(alm, plan, rol=None, rival_cid=None):
    """Que hacer en la proxima partida, fase por fase, sacado de todo tu historial."""
    with alm.lock:
        todas = sorted([p for p in alm.d["partidas"].values() if p.get("datos_h")],
                       key=lambda p: p.get("creacion") or 0)
        revs = dict(alm.d.get("revision") or {})
        nivel_cs = (alm.d["plan"].get("niveles") or {}).get("cs10", 0)
    rol = rol or plan.get("rol") or ""
    ps = ([p for p in todas if p.get("rol") == rol][-20:] if rol else []) or todas[-20:]
    out = {"rol": rol, "rol_txt": ROL_TXT.get(rol, rol), "n": len(ps), "fases": [], "juega": None,
           "fuerte": None, "rival": None,
           "mision": {k: plan["foco"][k] for k in ("nombre", "regla")} if plan.get("foco") else None}
    if not ps:
        return out
    fase_min = CONFIG["fin_fase_lineas_min"]
    f14, f25 = fase_min * 60000, 25 * 60000
    con_tl = [p for p in ps if p.get("con_timeline")]

    def muertes_entre(p, a, b):
        return [m for m in p.get("muertes") or [] if a <= m["ts"] < b]

    def causa_entre(a, b):
        c, tot = Counter(), 0
        for p in con_tl:
            for m in muertes_entre(p, a, b):
                tot += 1
                r = revs.get(f"{p['id']}:{m['ts']}")
                k = (r or {}).get("causa") or causa_sugerida(m, p["datos_h"].get("rival_id"))
                if k and k != "util":
                    c[k] += 1
        if c and c.most_common(1)[0][1] / max(1, tot) >= 0.35:
            return c.most_common(1)[0][0]
        return None

    # Que jugar en este rol: tu pool (lo elige el coach); si el rol no es de los tuyos, tus mas jugados
    pool = ((plan.get("roles") or {}).get("pools") or {}).get(rol) or []
    if pool:
        out["juega"] = {"campeones": [x["nombre"] for x in pool], "ids": [x["id"] for x in pool],
                        "texto": f"Juega {ROL_TXT.get(rol, rol)} con "
                                 f"{_lista_y([x['nombre'] for x in pool]).replace(' y ', ' o ')}."}
    else:
        del_rol = [s_ for s_ in _pool(todas[-30:]) if s_["rol"] == rol] if rol else []
        if del_rol:
            top = [s_["campeon"] for s_ in del_rol[:3]]
            out["juega"] = {"campeones": top, "ids": [s_["campeon_id"] for s_ in del_rol[:3]],
                            "texto": f"Juega {ROL_TXT.get(rol, rol)} con {_lista_y(top).replace(' y ', ' o ')}."}

    # Fase de lineas
    e_avg = _prom([len(muertes_entre(p, 0, f14)) for p in con_tl])
    cs10 = _prom([p["datos_h"].get("cs10") for p in ps if p.get("rol") != "support"])
    meta = _meta_cs10(nivel_cs)
    if e_avg is not None and e_avg >= 0.8:
        k = causa_entre(0, f14)
        txt = f"Mueres {_dec(e_avg)} veces antes del minuto {fase_min} por partida. "
        txt += (f"Lo que más se repite: {CAUSAS[k]['nombre'].lower()}. {CAUSAS[k]['consejo']}" if k else
                f"Hasta el minuto {fase_min} tu trabajo es farmear y no morir: si dudas de un intercambio, no lo hagas.")
        out["fases"].append({"fase": f"Fase de líneas (0 a {fase_min})", "texto": txt, "prioridad": "alta"})
    elif cs10 is not None and cs10 < meta and rol != "support":
        out["fases"].append({"fase": f"Fase de líneas (0 a {fase_min})", "prioridad": "media",
                             "texto": f"Casi no mueres temprano, bien. Pero llegas al minuto 10 con {round(cs10)} CS de "
                                      f"media y tu meta es {meta}: último golpe a cada súbdito, también bajo tu torre."})
    else:
        out["fases"].append({"fase": f"Fase de líneas (0 a {fase_min})", "prioridad": "bien",
                             "texto": "Tu fase de líneas va bien: no mueres temprano y farmeas. Mantén eso."})

    # Mitad de partida
    con_solo = [p for p in con_tl if "solo_14" in p["datos_h"]]
    solo = _prom([1 if p["datos_h"]["solo_14"] else 0 for p in con_solo]) if len(con_solo) >= 5 else None
    m_avg = _prom([len(muertes_entre(p, f14, f25)) for p in con_tl])
    tor = _prom([p["datos_h"].get("torres_min") for p in ps]) if rol == "top" else None
    if solo is not None and solo >= 0.4:
        consejo = {"support": "Cuando vayas a poner visión, que tu jungla o tu tirador estén cerca, y nunca entres "
                              "primero a un arbusto sin visión: lanza el ward desde fuera.",
                   "top": "Si haces split, mira el minimapa en cada oleada: si no ves a 3 enemigos, no pases del río "
                          "y retírate antes de que lleguen."}.get(
            rol, "Muévete con al menos un aliado o por zonas que tu equipo ve, y no entres primero a la niebla.")
        out["fases"].append({"fase": f"Mitad de partida ({fase_min} a 25)", "prioridad": "alta",
                             "texto": f"En el {round(solo * 100)}% de tus partidas mueres sin tu equipo después del "
                                      f"minuto {fase_min} (nadie de tu equipo estaba en la pelea). " + consejo})
    elif m_avg is not None and m_avg >= 1.5:
        k = causa_entre(f14, f25)
        out["fases"].append({"fase": f"Mitad de partida ({fase_min} a 25)", "prioridad": "media",
                             "texto": f"Mueres {_dec(m_avg)} veces entre el minuto {fase_min} y el 25. " +
                                      (f"Lo que más se repite: {CAUSAS[k]['nombre'].lower()}. {CAUSAS[k]['consejo']}" if k
                                       else "Antes de cada pelea, cuenta cuántos enemigos ves y cuántos aliados tienes cerca.")})
    elif tor is not None and tor < CONFIG["torres_habito_min"]:
        out["fases"].append({"fase": f"Mitad de partida ({fase_min} a 25)", "prioridad": "media",
                             "texto": "Tras la fase de líneas tu trabajo es tirar torres: cuando tu oleada llegue a su "
                                      "torre y no haya pelea cerca, golpéala."})
    else:
        out["fases"].append({"fase": f"Mitad de partida ({fase_min} a 25)", "prioridad": "bien",
                             "texto": "En la mitad de la partida vas bien: pocas muertes y casi nunca te atrapan solo. "
                                      "Sigue moviéndote con tu equipo."})

    # Final
    largas = [p for p in con_tl if p.get("minutos", 0) > 25]
    l_avg = _prom([len(muertes_entre(p, f25, 10 ** 9)) for p in largas]) if len(largas) >= 3 else None
    if l_avg is not None and l_avg >= 1:
        k = causa_entre(f25, 10 ** 9)
        out["fases"].append({"fase": "Final (después del 25)", "prioridad": "alta" if l_avg >= 2 else "media",
                             "texto": f"En tus partidas largas mueres {_dec(l_avg)} veces después del minuto 25, y ahí una "
                                      "muerte puede costar la partida. " +
                                      (f"Lo que más se repite: {CAUSAS[k]['nombre'].lower()}. {CAUSAS[k]['consejo']}" if k
                                       else "Juega detrás de tu equipo y no camines solo por el mapa.")})
    elif len(largas) >= 3:
        out["fases"].append({"fase": "Final (después del 25)", "prioridad": "bien",
                             "texto": "Al final de la partida no regalas muertes. Bien."})

    # Punto fuerte
    acc = {}
    for p in ps:
        for k2, v in _areas_partida(p).items():
            if v is not None:
                acc.setdefault(k2, []).append(v)
    medias = {k2: sum(v) / len(v) for k2, v in acc.items()}
    if medias:
        k2 = max(medias, key=medias.get)
        if medias[k2] >= 70:
            nombre = dict((a, b) for a, b, _ in AREAS).get(k2, k2)
            out["fuerte"] = f"Tu punto fuerte: {nombre.lower()} ({round(medias[k2])} de 100). No lo descuides."

    # Rival conocido (pantalla de carga)
    if rival_cid:
        h = historial_contra(todas, rival_cid)
        out["rival"] = {"historial": h}

    orden = {"alta": 0, "media": 1, "bien": 2}
    prioritaria = min(out["fases"], key=lambda f: orden[f["prioridad"]]) if out["fases"] else None
    out["lo_mas_importante"] = prioritaria if prioritaria and prioritaria["prioridad"] != "bien" else None
    return out


def siguiente_paso(alm, plan, ses):
    """Lo que el coach te pide hacer AHORA."""
    with alm.lock:
        _ps = sorted([p for p in alm.d["partidas"].values() if p.get("datos_h")], key=lambda p: p.get("creacion") or 0)
    ult = _ps[-1] if _ps else None
    if ult:
        sc = sesion_coaching(alm, ult)
        if sc["hallazgos"] and not sc["completa"]:
            n = sum(1 for h in sc["hallazgos"] if "respuesta" not in h)
            return {"tipo": "revisar", "titulo": "Haz la sesión de tu última partida",
                    "texto": f"El coach encontró {len(sc['hallazgos'])} "
                             f"{'error caro' if len(sc['hallazgos']) == 1 else 'errores caros'} y tiene "
                             f"{n} {'pregunta' if n == 1 else 'preguntas'} para ti. Un minuto.",
                    "accion": {"partida": ult["id"], "boton": "Empezar la sesión", "sesion": True}}
    if ses["parada"]:
        return {"tipo": "parar", "titulo": "Para por hoy",
                "texto": ". ".join(m["texto"] for m in ses["motivos"]) +
                         f". Mañana desde las {ses['hora_reinicio']} el contador vuelve a cero.", "accion": None}
    with alm.lock:
        ps = sorted(alm.d["partidas"].values(), key=lambda p: p.get("creacion") or 0)
        revs = dict(alm.d.get("revision") or {})
        animos = dict(alm.d["animo"])
    hoy = dia_de(time.time() * 1000)
    ult = ps[-1] if ps else None
    if ult and dia_de(ult.get("fin_ts") or 0) == hoy:
        pend = [ts for ts in muertes_clave(ult) if f"{ult['id']}:{ts}" not in revs]
        if pend:
            return {"tipo": "revisar",
                    "titulo": f"Revisa {len(pend)} {'muerte' if len(pend) == 1 else 'muertes'} de tu última partida",
                    "texto": "Unos 5 minutos: mira la repetición y elige qué pasó. Sin esto el coach no sabe por qué mueres.",
                    "accion": {"partida": ult["id"], "boton": "Revisar ahora"}}
        if ult.get("cuenta_anti") and not animos.get(ult["id"]):
            return {"tipo": "animo", "titulo": "Marca cómo terminaste tu última partida",
                    "texto": "Con eso el coach decide si sigues jugando hoy.",
                    "accion": {"partida": ult["id"], "boton": "Marcar"}}
    hoy_ps = [p for p in ps if p.get("cuenta_anti") and dia_de(p.get("fin_ts") or 0) == hoy]
    if len(hoy_ps) >= 3 and len(hoy_ps) % 3 == 0:
        falta = 10 - (time.time() * 1000 - (hoy_ps[-1].get("fin_ts") or 0)) / 60000
        if 0 < falta <= 10:
            return {"tipo": "descanso", "titulo": "Descansa 10 minutos",
                    "texto": f"Llevas {len(hoy_ps)} partidas hoy. Levántate, toma agua y vuelve en "
                             f"{max(1, round(falta))} {'minuto' if round(falta) <= 1 else 'minutos'}: jugar una "
                             "partida detrás de otra sin pausa baja tu rendimiento.", "accion": None}
    en = estado_entreno(alm, plan)
    if not en["hoy"] and en["principal"]:        # solo si tu rol principal farmea: a un support no le toca
        con = f"con {en['campeon']}" if en.get("campeon") else "con tu campeón principal"
        return {"tipo": "calentar", "titulo": "Calienta: 10 minutos de último golpe",
                "texto": f"Abre la Herramienta de práctica {con}. Meta: {en['meta']} CS. "
                         "El coach lo sigue y lo guarda solo.", "accion": None}
    regla = (plan.get("foco") or {}).get("regla", "")
    mision = f"Tu misión: {regla[:1].lower() + regla[1:]}." if regla else ""
    rp = plan.get("roles")
    if rp:
        return {"tipo": "jugar", "titulo": f"Busca partida de {rp['principal_txt']} y {rp['secundario_txt']}",
                "texto": f"En la cola pon {rp['principal_txt']} de principal y {rp['secundario_txt']} de secundario. "
                         + mision, "accion": None}
    pp = plan_partida(alm, plan)
    juega = (pp.get("juega") or {}).get("texto") or "Juega tu rol principal."
    return {"tipo": "jugar", "titulo": juega, "texto": mision, "accion": None}


# =============================================================== ANTI-RACHA
def dia_de(ts_ms):
    dt = datetime.fromtimestamp(ts_ms / 1000) - timedelta(hours=CONFIG["dia_empieza_hora"])
    return dt.date().isoformat()


def tope_personal(partidas):
    """Cuantas partidas al dia te convienen, con tus numeros: compara tus primeras partidas del dia con las
    siguientes (un estudio con ~5.000 jugadores de LoL vio que el rendimiento baja con cada partida seguida)."""
    base = CONFIG["tope_partidas_dia"]
    por_dia = {}
    for p in sorted([p for p in partidas if p.get("cuenta_anti") and p.get("fin_ts") and p.get("veredicto")],
                    key=lambda p: p["fin_ts"]):
        por_dia.setdefault(dia_de(p["fin_ts"]), []).append(p)
    filas = [(i, p["victoria"], p["veredicto"]["nota"]) for lst in por_dia.values() for i, p in enumerate(lst, 1)]

    def resumen(fs):
        if not fs:
            return None, None
        return round(100 * sum(1 for f in fs if f[1]) / len(fs)), round(sum(f[2] for f in fs) / len(fs), 1)

    tramos = []
    for a, b, et in ((1, 2, "1ª y 2ª"), (3, 4, "3ª y 4ª"), (5, 6, "5ª y 6ª"), (7, 99, "7ª o más")):
        fs = [f for f in filas if a <= f[0] <= b]
        wr, nota = resumen(fs)
        tramos.append({"tramo": et, "n": len(fs), "wr": wr, "nota": nota})
    mejor = None
    for k in range(3, 9):
        a = [f for f in filas if f[0] <= k]
        b = [f for f in filas if f[0] > k]
        if len(a) < 15 or len(b) < 10:
            continue
        (wa, na), (wb, nb) = resumen(a), resumen(b)
        if wa - wb >= 8 and na - nb >= 0.4 and (mejor is None or (wa - wb) + 10 * (na - nb) > mejor[0]):
            mejor = ((wa - wb) + 10 * (na - nb), k, wa, wb, na, nb)
    if mejor:
        _, k, wa, wb, na, nb = mejor
        return {"tope": k, "fuente": "tus partidas", "tramos": tramos,
                "motivo": f"En tus primeras {k} partidas del día ganas el {wa}% (nota {_dec(na)}); desde la "
                          f"{k + 1}ª, el {wb}% (nota {_dec(nb)})."}
    if len(filas) >= 40 and len([f for f in filas if f[0] > base]) >= 10:
        return {"tope": 8, "fuente": "tus partidas", "tramos": tramos,
                "motivo": f"Tus partidas después de la {base}ª del día rinden igual que las primeras (2 derrotas "
                          "seguidas siguen cortando el día)."}
    return {"tope": base, "fuente": "investigación", "tramos": tramos,
            "motivo": "Es lo que se recomienda para jugar con foco. Con más partidas tuyas, el coach lo ajusta a "
                      "tus números."}


def dato_tilt(partidas, racha_min):
    """Tu % de victorias en la partida que juegas justo despues de 'racha_min' derrotas seguidas el mismo dia,
    contra el resto de tus partidas. None si aun hay pocas."""
    por_dia = {}
    for p in sorted([p for p in partidas if p.get("cuenta_anti") and p.get("fin_ts")], key=lambda p: p["fin_ts"]):
        por_dia.setdefault(dia_de(p["fin_ts"]), []).append(p)
    tras, resto = [], []
    for lst in por_dia.values():
        racha = 0
        for p in lst:
            (tras if racha >= racha_min else resto).append(p["victoria"])
            racha = 0 if p["victoria"] else racha + 1
    if len(tras) < 5 or len(resto) < 5:
        return None
    wt, wr = round(100 * sum(tras) / len(tras)), round(100 * sum(resto) / len(resto))
    return {"n": len(tras), "v": sum(tras), "wr": wt, "wr_resto": wr, "racha": racha_min,
            "texto": f"Tus números: en la partida siguiente a {racha_min} derrotas seguidas ganas el {wt}% "
                     f"({sum(tras)} de {len(tras)}). En el resto de tus partidas, el {wr}%."}


def tope_del_dia(partidas, base):
    """El tope de hoy no es fijo: hasta tu tope juegas normal; desde ahi, mientras hoy no pierdas mas de las que
    ganas (empatado vale si juegas bien: nota media 7 o mas) y tu ultima partida no haya sido claramente peor
    que tu media del dia, te deja una mas (hasta
    'tope_maximo_dia'). Si la forma cae, el tope se queda donde estas. Devuelve (tope, motivo de parar)."""
    n = len(partidas)
    maximo = max(base, int(CONFIG.get("tope_maximo_dia", 7)))
    if n < base:
        return base, ""
    if n >= maximo:
        return maximo, f"es el máximo del día aunque vayas bien"
    v = sum(1 for p in partidas if p.get("victoria"))
    notas = [p["veredicto"]["nota"] for p in partidas if p.get("veredicto")]
    ult = (partidas[-1].get("veredicto") or {}).get("nota")
    media = sum(notas) / len(notas) if notas else None
    # mas derrotas que victorias corta; empatado solo si ademas tu nota media del dia no llega a "bien"
    if 2 * v < n or (2 * v == n and (media is None or media < NOTA_BIEN)):
        return n, f"hoy vas {v}V-{n - v}D"
    if ult is None or ult < NOTA_REGULAR or (media is not None and ult < media - 1):
        return n, "tu última partida fue peor que las de antes"
    return n + 1, ""


def anti_pref(alm):
    """Tu ajuste de la regla anti-racha: {"activa": bool, "derrotas": n}."""
    x = alm.d.get("anti") or {}
    return {"activa": x.get("activa", True) is not False,
            "derrotas": int(x.get("derrotas") or CONFIG["derrotas_seguidas_para_parar"])}


def racha_corta(perdidas, limite):
    """Si las derrotas seguidas de hoy cortan el dia. Al limite solo si en ellas jugaste por debajo de "bien"
    (perder jugando bien no es tilt: suele ser el draft o el equipo); una derrota mas, siempre."""
    racha = len(perdidas)
    if racha < limite:
        return False
    if racha > limite:
        return True
    notas = [(p.get("veredicto") or {}).get("nota") for p in perdidas]
    notas = [x for x in notas if x is not None]
    return not notas or sum(notas) / len(notas) < NOTA_BIEN


def sesion(alm):
    with alm.lock:
        ahora = int(time.time() * 1000)
        hoy = dia_de(ahora)
        partidas = sorted([p for p in alm.d["partidas"].values()
                           if p.get("cuenta_anti") and dia_de(p.get("fin_ts") or 0) == hoy],
                          key=lambda p: p.get("fin_ts") or 0)
        animos = alm.d["animo"]
        n = len(partidas)
        v = sum(1 for p in partidas if p["victoria"])
        racha, perdidas = 0, []
        for p in reversed(partidas):
            if p["victoria"]:
                break
            racha += 1
            perdidas.append(p)
        pref = anti_pref(alm)
        tope_info = tope_personal(list(alm.d["partidas"].values()))
        tope_base = tope_info["tope"]
        tope, tope_por = tope_del_dia(partidas, tope_base)
        lim_derr = pref["derrotas"]
        tilt_dato = dato_tilt(list(alm.d["partidas"].values()), lim_derr)
        tilts = [p for p in partidas if (animos.get(p["id"]) or {}).get("estado") == "tilt"]
        ultimo_animo = None
        for p in reversed(partidas):
            if animos.get(p["id"]):
                ultimo_animo = animos[p["id"]]["estado"]
                break
        actuales = []
        corta = pref["activa"] and racha_corta(perdidas, lim_derr)
        nota_racha = None
        if racha:
            ns = [(p.get("veredicto") or {}).get("nota") for p in perdidas if (p.get("veredicto") or {}).get("nota") is not None]
            nota_racha = round(sum(ns) / len(ns), 1) if ns else None
        if corta:
            actuales.append({"clave": "derrotas", "texto": f"{racha} derrotas seguidas"
                             + (f" con nota media {_dec(nota_racha)}" if nota_racha is not None and racha == lim_derr else "")})
        if pref["activa"] and tilts:
            actuales.append({"clave": "tilt", "texto": f"Marcaste tilt después de la partida con {tilts[-1]['yo']['campeon']}"})
        if pref["activa"] and n >= tope:
            por = tope_por if tope > tope_base or tope_por.startswith("es el") else (
                tope_info["motivo"][:1].lower() + tope_info["motivo"][1:].rstrip(".") if tope_info["fuente"] == "tus partidas" else tope_por)
            actuales.append({"clave": "tope", "texto": f"Llegaste a tu tope de {tope} partidas del día"
                             + (f" ({por})" if por else "")})
        aviso = alm.d["avisos"].get(hoy)
        if actuales and not aviso:
            aviso = {"ts": ahora, "partidas_al_aviso": n, "motivos": [], "visto_clave": ""}
            alm.d["avisos"][hoy] = aviso
        if aviso:
            if actuales and not aviso.get("motivos"):          # vuelve a tocar parar tras haberse levantado
                aviso["ts"], aviso["partidas_al_aviso"] = ahora, n
            previos = {m["clave"]: m for m in aviso.get("motivos", [])}
            cambio = False
            # el tope se mueve con tu forma de hoy: si ya no aplica, deja de pedirte parar (derrotas y tilt se quedan)
            if "tope" in previos and not any(m["clave"] == "tope" for m in actuales):
                del previos["tope"]
                cambio = True
            # las derrotas se quedan aunque luego ganes; se quitan si sigues en la racha pero ya no corta
            # (jugaste bien en ellas o cambiaste el ajuste) o si apagaste la regla
            if "derrotas" in previos and not corta and (racha >= 1 or not pref["activa"]):
                del previos["derrotas"]
                cambio = True
            if not pref["activa"] and previos:
                previos, cambio = {}, True
            for m in actuales:
                if previos.get(m["clave"]) != m:
                    previos[m["clave"]] = m
                    cambio = True
            if cambio:
                aviso["motivos"] = list(previos.values())
                alm.guardar()
        motivos = aviso["motivos"] if aviso else []
        parada = bool(motivos)
        despues = (n - aviso["partidas_al_aviso"]) if aviso else 0
        clave = f"{n}|" + ",".join(sorted(m["clave"] for m in motivos))
        mostrar = parada and aviso.get("visto_clave") != clave
        if parada:
            estado, msg = "parar", "Para por hoy."
        elif pref["activa"] and racha >= lim_derr and racha > 0:
            estado, msg = "ojo", (f"{racha} derrotas seguidas, pero jugaste bien (nota {_dec(nota_racha)}): no es tilt. "
                                  "Sigue si te apetece; si la siguiente sale mal, para.")
        elif pref["activa"] and racha == lim_derr - 1 and racha > 0:
            estado, msg = "ojo", "Una derrota más jugando mal y toca parar por hoy."
        elif n >= tope_base:
            estado, msg = "ojo", (f"Pasaste tu tope de {tope_base}, pero hoy vas {v}V-{n - v}D y jugando bien: "
                                  "te dejo una más. Si pierdes o tu nota baja, para.")
        elif n == tope - 1:
            estado, msg = "ojo", "Te queda una partida antes del tope del día."
        elif ultimo_animo == "molesto":
            estado, msg = "ojo", "Marcaste que terminaste molesto. Si la siguiente sale mal, para."
        else:
            estado, msg = "ok", ("Puedes seguir jugando." if n else "Aún no has jugado hoy.")
        muertes = sum(p["yo"]["d"] for p in partidas)
        return {
            "dia": hoy, "partidas": n, "victorias": v, "derrotas": n - v, "racha_derrotas": racha,
            "tope": tope, "tope_base": tope_base, "tope_info": tope_info, "limite_derrotas": lim_derr, "ultimo_animo": ultimo_animo,
            "anti": pref,
            "estado": estado, "mensaje": msg, "parada": parada, "motivos": motivos,
            "tilt_dato": tilt_dato if (tilt_dato and racha >= max(1, lim_derr - 1)) else None,
            "mostrar_aviso": mostrar, "clave_aviso": clave, "despues_del_aviso": max(0, despues),
            "muertes_prom": round(muertes / n, 1) if n else None,
            "nota_prom": round(sum(p["veredicto"]["nota"] for p in partidas) / n, 1) if n else None,
            "lista": [{"id": p["id"], "campeon": p["yo"]["campeon"], "campeon_id": p["yo"]["campeon_id"],
                       "victoria": p["victoria"], "kda": p["yo"]["kda"], "nota": p["veredicto"]["nota"],
                       "animo": (animos.get(p["id"]) or {}).get("estado")} for p in partidas],
            "hora_reinicio": f"{CONFIG['dia_empieza_hora']}:00",
        }


# =============================================================== MISION EN VIVO
def _yo_en_vivo(data, nombre=""):
    """Encuentra tu jugador en los datos de la partida en vivo (Riot ID, nombre de invocador o nombre)."""
    ap = data.get("activePlayer") or {}
    claves_ap = {x for x in (ap.get("riotId"), ap.get("summonerName"), ap.get("riotIdGameName"),
                             (ap.get("riotId") or "").split("#")[0], nombre) if x}
    for p in data.get("allPlayers") or []:
        claves_p = {x for x in (p.get("riotId"), p.get("summonerName"), p.get("riotIdGameName"),
                                (p.get("riotId") or "").split("#")[0]) if x}
        if claves_ap & claves_p:
            return p
    return None


class EnVivo:
    """Panel de la mision durante la partida.
    Solo muestra TU mision y TUS numeros. No da ordenes segun el estado de la partida ni avisa de
    picos de poder: la politica de Riot para apps de terceros lo prohibe."""

    def __init__(self, mision, rol="", nombre="", rival_nombres=None):
        self.nombre = nombre
        self.m = mision or {}
        self.clave = self.m.get("clave")
        self.nivel = self.m.get("nivel", 0)
        self.rol = rol
        self.rival_nombres = {x.lower() for x in (rival_nombres or []) if x}   # nombre y alias de su campeon
        self.rival_cs10 = None
        self.cs10_mio = None
        self.d_al_14 = None
        self.cs_14 = None
        self.mis_muertes_t = []       # minuto de cada muerte tuya (eventos)
        self.jg_rival = set()
        self.prev_d = None
        self.prev_gold = None
        self.gold_vivo = 0
        self.cw_prev = 0
        self.cw_comprados = 0
        self.d_al_10 = None
        self.cs_meta = _meta_cs10(self.m.get("nivel", 0))
        self.anunciado = set()
        self.eventos_vistos = set()
        self.kills_vivo = []          # (tiempo, nombres que mataron, asistieron o murieron)
        self.pendientes = []          # muertes tuyas desde el 14 que se deciden 15 s despues
        self.solas = 0
        self.res = None               # True / False cuando la mision ya quedo decidida en esta partida

    def _cs_rival(self, data, mi_eq):
        """CS de tu rival de linea (su campeon lo sabe el coach desde la pantalla de carga)."""
        if not self.rival_nombres:
            return None
        for p in data.get("allPlayers") or []:
            if p.get("team") == mi_eq:
                continue
            raw = (p.get("rawChampionName") or "").lower()
            if (p.get("championName") or "").lower() in self.rival_nombres or any(
                    raw.endswith("_" + x) for x in self.rival_nombres):
                return int((p.get("scores") or {}).get("creepScore") or 0)
        return None

    def _jungla_rival(self, data, mi_eq):
        """El jungla rival: el del otro equipo que lleva Aplastar (Smite)."""
        if self.jg_rival:
            return
        for p in data.get("allPlayers") or []:
            if p.get("team") == mi_eq:
                continue
            hechizos = p.get("summonerSpells") or {}
            if any("smite" in ((h or {}).get("rawDisplayName") or "").lower() for h in hechizos.values()):
                self.jg_rival |= {x for x in (p.get("riotIdGameName"), p.get("summonerName"), p.get("riotId"),
                                              (p.get("riotId") or "").split("#")[0]) if x}

    def _una_vez(self, clave):
        if clave in self.anunciado:
            return False
        self.anunciado.add(clave)
        return True

    def actualizar(self, data):
        t = float((data.get("gameData") or {}).get("gameTime") or 0)
        ap = data.get("activePlayer") or {}
        yo = _yo_en_vivo(data, self.nombre)
        if not yo:
            return {"modo": "partida", "titulo": f"Misión: {self.m.get('nombre', '')}",
                    "regla": self.m.get("regla", ""), "estado": "", "extra": "", "aviso": None, "tono": "azul"}
        nombres_yo = {x for x in (yo.get("riotIdGameName"), yo.get("summonerName"), yo.get("riotId"),
                                  (yo.get("riotId") or "").split("#")[0]) if x}
        sc = yo.get("scores") or {}
        d = int(sc.get("deaths") or 0)
        cs = int(sc.get("creepScore") or 0)
        gold = int(ap.get("currentGold") or 0)
        muerto = bool(yo.get("isDead"))
        its = yo.get("items") or []
        cw_now = sum(int(i.get("count") or 1) for i in its if i.get("itemID") == CONTROL_WARD)
        if cw_now > self.cw_prev:
            self.cw_comprados += cw_now - self.cw_prev
        murio = self.prev_d is not None and d > self.prev_d
        if not muerto:
            self.gold_vivo = gold
        mi_eq = yo.get("team")
        aliados = set()
        for p in data.get("allPlayers") or []:
            if p.get("team") == mi_eq:
                aliados |= {x for x in (p.get("riotIdGameName"), p.get("summonerName"), p.get("riotId"),
                                        (p.get("riotId") or "").split("#")[0]) if x}
        aliados -= nombres_yo
        evs = ((data.get("events") or {}).get("Events")) or []
        desde = CONFIG["fin_fase_lineas_min"] * 60
        for e in evs:
            if e.get("EventName") != "ChampionKill":
                continue
            te = float(e.get("EventTime") or 0)
            idx = (e.get("EventID"), round(te, 1), e.get("VictimName"))
            if idx in self.eventos_vistos:
                continue                     # cada evento una sola vez (tambien tras una reconexion)
            self.eventos_vistos.add(idx)
            self.kills_vivo.append((te, {e.get("KillerName"), e.get("VictimName"), *(e.get("Assisters") or [])}))
            if e.get("VictimName") in nombres_yo:
                self.mis_muertes_t.append((te, {e.get("KillerName"), *(e.get("Assisters") or [])}))
            if e.get("VictimName") in nombres_yo and te >= desde:
                self.pendientes.append(te)
        # Cada muerte tuya desde el 14 se decide 15 s despues: si ningun aliado mato, asistio o murio, fue sin tu equipo
        for tm in list(self.pendientes):
            if t - tm >= VENTANA_PELEA_S:
                if not any(abs(tk - tm) <= VENTANA_PELEA_S and (imp & aliados) for tk, imp in self.kills_vivo):
                    self.solas += 1
                self.pendientes.remove(tm)

        aviso, tono, estado = None, "azul", ""
        c = self.clave
        if c == "vivo_10":
            if t < 600:
                self.d_al_10 = d
                estado = f"Muertes antes del 10: {d}   |   faltan {int(600 - t) // 60}:{int(600 - t) % 60:02d}"
                if murio and self._una_vez("fallo"):
                    aviso, tono = "Misión fallada en esta partida.", "rojo"
            else:
                if self.d_al_10 is None:
                    self.d_al_10 = d
                if self.d_al_10 == 0 and self._una_vez("ok"):
                    aviso, tono = "Misión cumplida: llegaste al 10 sin morir.", "verde"
                self.res = self.d_al_10 == 0
                estado = "Cumplida: 0 muertes antes del 10" if self.d_al_10 == 0 else "Fallada en esta partida"
        elif c == "muertes":
            lim = _meta("muertes", self.nivel)
            estado = f"Muertes: {d} de {lim} como máximo"
            if d > lim and self._una_vez("fallo"):
                aviso, tono = "Misión fallada en esta partida.", "rojo"
        elif c == "oro":
            estado = f"Tu oro: {_miles(gold)}"
            if murio and (self.prev_gold or 0) >= CONFIG["oro_sin_gastar"] and self._una_vez("fallo"):
                aviso, tono = f"Moriste con ~{_miles(self.prev_gold)} de oro: misión fallada.", "rojo"
        elif c == "cs10":
            if t < 600:
                esperado = int(self.cs_meta * t / 600)
                estado = f"CS ~{cs}   |   ritmo para {self.cs_meta} al 10: {esperado}"
            else:
                if self._una_vez("cs600"):
                    ok = cs >= self.cs_meta
                    self.res = ok
                    aviso, tono = (f"~{cs} CS al 10: misión {'cumplida' if ok else 'fallada'}.",
                                   "verde" if ok else "rojo")
                estado = f"CS ~{cs}"
        elif c == "solo":
            fm = CONFIG["fin_fase_lineas_min"]
            if t < desde:
                estado = f"Cuenta desde el minuto {fm}"
            else:
                estado = f"Muertes sin tu equipo desde el {fm}: {self.solas}"
            if self.solas and self._una_vez("fallo"):
                aviso, tono = "Moriste sin tu equipo en la pelea: misión fallada.", "rojo"
        elif c == "vivo_14":
            if t < desde:
                self.d_al_14 = d
                faltan = int(desde - t)
                estado = f"Muertes antes del 14: {d}   |   faltan {faltan // 60}:{faltan % 60:02d}"
                if murio and self._una_vez("fallo"):
                    aviso, tono = "Misión fallada en esta partida.", "rojo"
            else:
                if self.d_al_14 is None:
                    self.d_al_14 = d
                if self.d_al_14 == 0 and self._una_vez("ok"):
                    aviso, tono = "Misión cumplida: llegaste al 14 sin morir.", "verde"
                self.res = self.d_al_14 == 0
                estado = "Cumplida: 0 muertes antes del 14" if self.d_al_14 == 0 else "Fallada en esta partida"
        elif c == "cs_rival":
            rcs = self._cs_rival(data, mi_eq)
            if t < 600:
                self.cs10_mio, self.rival_cs10 = cs, rcs
                estado = f"CS ~{cs}" + (f"   |   tu rival ~{rcs}" if rcs is not None else "")
            else:
                if self.cs10_mio is None:
                    self.cs10_mio, self.rival_cs10 = cs, rcs
                if self.rival_cs10 is None:
                    estado = "Se mide al terminar (no encontré a tu rival en la partida)"
                else:
                    ok = self.cs10_mio >= self.rival_cs10
                    self.res = ok
                    if self._una_vez("cs600"):
                        aviso, tono = (f"Al 10: ~{self.cs10_mio} CS contra ~{self.rival_cs10}: misión "
                                       f"{'cumplida' if ok else 'fallada'}.", "verde" if ok else "rojo")
                    estado = f"Al 10: ~{self.cs10_mio} contra ~{self.rival_cs10}"
        elif c == "gank":
            self._jungla_rival(data, mi_eq)
            n = sum(1 for te, imp in self.mis_muertes_t if te < desde and imp & self.jg_rival)
            estado = (f"Muertes con su jungla antes del 14: {n}" if self.jg_rival
                      else "Se mide al terminar (no encontré a su jungla)")
            if n and self._una_vez("fallo"):
                aviso, tono = "Su jungla te pilló: misión fallada en esta partida.", "rojo"
        elif c == "vision":
            ws = float(sc.get("wardScore") or 0)
            meta = _meta("vision", self.nivel, self.rol)
            estado = (f"Visión: {int(ws)} ({_dec(ws / (t / 60), 2)} por minuto; meta {_dec(meta, 2)})" if t > 120
                      else f"Meta: {_dec(meta, 2)} de visión por minuto")
        elif c == "presencia":
            estado = "Se mide al terminar: dónde estabas en cada dragón, Heraldo y Barón"
        elif c == "cs_post":
            if t < desde:
                self.cs_14 = cs
                estado = "Cuenta desde el minuto 14"
            else:
                if self.cs_14 is None:
                    self.cs_14 = cs
                ritmo = (cs - self.cs_14) / max((t - desde) / 60, 0.5)
                estado = f"CS por minuto desde el 14: ~{_dec(ritmo)} (meta {_dec(CONFIG['cs_post_min'])})"
        elif c == "tarde":
            n = sum(1 for te, _ in self.mis_muertes_t if te >= 1500)
            estado = f"Muertes después del 25: {n} (máximo 1)" if t >= 1500 else "Cuenta desde el minuto 25"
            if n > 1 and self._una_vez("fallo"):
                aviso, tono = "Misión fallada en esta partida.", "rojo"
        elif c == "oro_rival":
            estado = "Se mide al terminar: tu oro contra tu rival al minuto 14"
        elif c == "nota":
            estado = f"Se mide al terminar: nota del coach de {_dec(CONFIG['nota_consistencia'])} o más"
        elif c == "tarea":
            estado = (self.m.get("como") or [""])[0]          # tu regla, a la vista mientras juegas
        elif c == "torres":
            estado = "El daño a torres se mide al final de la partida"
        extra = ""
        if self.rol != "support" and t > 120:
            extra = f"CS por minuto: ~{_dec(cs / (t / 60))}"
        self.prev_d, self.prev_gold, self.cw_prev = d, self.gold_vivo, cw_now
        st = "fallo" if ("fallo" in self.anunciado or self.res is False) else "ok" if self.res is True else "curso"
        return {"modo": "partida", "titulo": f"Misión: {self.m.get('nombre', '')}",
                "regla": self.m.get("regla", ""), "estado": estado, "extra": extra, "aviso": aviso, "tono": tono,
                "mision_nombre": self.m.get("nombre", ""), "mision_st": st}


# =============================================================== OBJETIVOS GRANDES EN PARTIDA
# Temporada 2026 (Grieta normal): sin Atakhan; Baron otra vez al 20. Comprobado con las primeras muertes de 25 partidas
# guardadas: dragon 5:41, larvas 8:16, Heraldo 15:32 y Baron 21:47 como muy pronto. Los del Anciano son los de siempre.
OBJ_DRAGON_1, OBJ_DRAGON_RE = 300, 300
OBJ_LARVAS, OBJ_LARVAS_FIN = 480, 885          # una sola tanda de 3; se van a los 14:45
OBJ_HERALDO, OBJ_HERALDO_FIN = 900, 1185       # una vez; se va a los 19:45 para dejar sitio al Baron
OBJ_BARON_1, OBJ_BARON_RE = 1200, 360
OBJ_ANCIANO_RE = 360                           # 6:00 despues del alma (y de cada Anciano)
BUFO_BARON, BUFO_ANCIANO = 180, 150
MODOS_NO_GRIETA = {"ARAM", "KIWI", "CHERRY", "URF", "ARURF", "ONEFORALL", "ULTBOOK", "NEXUSBLITZ", "TUTORIAL",
                   "PRACTICETOOL", "STRAWBERRY", "DOOMBOTSTEEMO", "FIRSTBLOOD", "ODYSSEY", "STARGUARDIAN", "SNOWURF"}


def es_grieta(cola):
    """Si la cola es de la Grieta del Invocador (normal, clasificatoria, Swiftplay...). ARAM, ARAM: Caos, Arena y
    demas modos no: alli no hay lineas, jungla, dragones ni Barones, y la mision, las runas y el draft no aplican.
    Sin datos de la cola se asume Grieta (como antes)."""
    if not cola:
        return True
    modo = str(cola.get("modo") or "").upper()
    mapa = cola.get("mapa")
    if mapa not in (None, 0, 11):
        return False
    return modo not in MODOS_NO_GRIETA


COLAS_SIN_OBJETIVOS = {480}                     # Swiftplay: otros tiempos (Baron al 12, sin larvas ni Heraldo)
DRAGON_ICONO = {"Fire": "dragon_infernal", "Water": "dragon_ocean", "Earth": "dragon_mountain", "Air": "dragon_cloud",
                "Hextech": "dragon_hextech", "Chemtech": "dragon_chemtech", "Elder": "dragon_elder"}
DRAGON_ES = {"Fire": "infernal", "Water": "del océano", "Earth": "de montaña", "Air": "de nubes",
             "Hextech": "hextech", "Chemtech": "quimtech"}
EVENTOS_CONOCIDOS = {"GameStart", "MinionsSpawning", "FirstBlood", "FirstBrick", "ChampionKill", "Multikill", "Ace",
                     "TurretKilled", "InhibKilled", "InhibRespawningSoon", "InhibRespawned", "DragonKill",
                     "HeraldKill", "BaronKill", "HordeKill", "GameEnd"}
AVISO_OBJ = {
    "dragon": {"bot": "Empuja tu oleada y ve al río de abajo con tu jungla. Visión antes de que salga.",
               "support": "Visión en el río de abajo ya, y que tu tirador empuje antes de ir.",
               "jungla": "Junta a mid y bot: que empujen sus oleadas y entrad con visión.",
               "mid": "Empuja tu oleada y baja con tu jungla al río.",
               "top": "Tu equipo irá abajo: empuja tu línea y guarda el Teleport para la pelea.",
               "*": "Empuja tu oleada y ve al río de abajo con tu equipo."},
    "anciano": {"*": "El que lo coge suele ganar: agrupaos con visión y que nadie muera antes de que salga."},
    "larvas": {"top": "Empuja tu oleada y ve arriba con tu jungla: las larvas dan daño contra torres.",
               "jungla": "Ve arriba y llama a top y mid: con la oleada empujada, las larvas son vuestras.",
               "mid": "Empuja tu oleada y sube con tu jungla a por las larvas.",
               "bot": "Tu equipo irá arriba: juega seguro en tu línea y no pases de la mitad.",
               "support": "Tu equipo irá arriba: no os metáis en su torre mientras tanto.",
               "*": "Empuja tu oleada y ve arriba con tu equipo."},
    "heraldo": {"top": "Empuja tu oleada y ve con tu jungla: el Heraldo tira una torre entera de golpe.",
                "jungla": "Llama a top y mid: con el Heraldo se gana una torre gratis.",
                "mid": "Empuja tu oleada y ve con tu jungla al foso de arriba.",
                "bot": "Tu jungla irá arriba: juega seguro en tu línea.",
                "support": "Tu jungla irá arriba: ward en su jungla de abajo y juega seguro.",
                "*": "Empuja tu oleada y ve con tu jungla al foso de arriba."},
    "baron": {"*": "Agrupaos en mid y poned visión cerca del foso. Nadie solo en las líneas laterales."},
}
AVISO_BUFO = {("baron", True): ("Barón vuestro", "Agrupaos y empujad juntos con los súbditos potenciados."),
              ("baron", False): ("Barón suyo", "Defiende bajo tus torres y limpia oleadas. No pelees fuera ni vayas solo."),
              ("anciano", True): ("Anciano vuestro", "Buscad pelea ya: con poca vida sus campeones mueren de golpe."),
              ("anciano", False): ("Anciano suyo", "No peleéis hasta que se acabe: retroceded y defended.")}


BARATIJA_TOTEM, BARATIJA_LENTE, BARATIJA_LEJANA = 3340, 3364, 3363


def prob_vivo(dif_oro, minuto, drag_dif=0, torres_dif=0, bufo=0.0):
    """Probabilidad de ganar en partida (azul = tu equipo), con lo que se ve en el Tab y lo que anuncia el juego:
    ventaja de oro en objetos (pesa menos cuanto mas tarde), dragones, torres y bufos de Baron/Anciano activos
    (bufo: +1 Baron vuestro, -1 suyo; el Anciano cuenta 1,6). Curva propia, aproximada."""
    if minuto < 2:
        return 50
    k = 0.00045 * math.sqrt(15 / max(minuto, 8))
    z = k * dif_oro + 0.10 * drag_dif + 0.06 * torres_dif + 0.55 * bufo
    return max(3, min(97, round(100 / (1 + math.exp(-z)))))


def marcador_vivo(data, mi_team, precio, ob=None):
    """Marcador de equipo con lo que todos ven: oro en objetos (los del Tab: el oro sin gastar no se ve, ni del
    tuyo ni del suyo), kills, torres derribadas y la probabilidad de ganar. None si no se sabe tu equipo."""
    if mi_team not in ("ORDER", "CHAOS"):
        return None
    t = float((data.get("gameData") or {}).get("gameTime") or 0)
    oro, kills = {True: 0, False: 0}, {True: 0, False: 0}
    for pl in data.get("allPlayers") or []:
        mio = pl.get("team") == mi_team
        kills[mio] += int((pl.get("scores") or {}).get("kills") or 0)
        for i in pl.get("items") or []:
            oro[mio] += (precio(i.get("itemID")) or int(i.get("price") or 0)) * int(i.get("count") or 1)
    torres, vistos = {True: 0, False: 0}, set()
    for e in ((data.get("events") or {}).get("Events")) or []:
        if e.get("EventName") != "TurretKilled":
            continue
        idx = e.get("EventID") if e.get("EventID") is not None else e.get("TurretKilled")
        if idx in vistos:
            continue
        vistos.add(idx)
        m = re.match(r"Turret_T([12])_", e.get("TurretKilled") or "")
        if m:                                   # Turret_T1 es de ORDER: si cae, la suma CHAOS
            torres[("CHAOS" if m.group(1) == "1" else "ORDER") == mi_team] += 1
    drag, bufo = (0, 0), 0.0
    if ob:
        drag = tuple(ob.get("dragones") or (0, 0))
        for f in ob.get("fichas") or []:
            b = f.get("bufo")
            if b and t < b["hasta"]:
                bufo += (1 if b["mio"] else -1) * (1.6 if f["clave"] == "anciano" else 1.0)
    dif = oro[True] - oro[False]
    return {"prob": prob_vivo(dif, t / 60, drag[0] - drag[1], torres[True] - torres[False], bufo),
            "oro": [oro[True], oro[False]], "dif": dif, "kills": [kills[True], kills[False]],
            "torres": [torres[True], torres[False]]}


def baratija_aviso(rol, minuto, items):
    """Recordatorio (una vez por partida) de cambiar el Totem por la Lente del Oraculo cuando a tu rol le toca.
    None si ya la cambiaste o aun no toca."""
    ids = {i.get("itemID") for i in items or []}
    if BARATIJA_TOTEM not in ids or ids & {BARATIJA_LENTE, BARATIJA_LEJANA}:
        return None
    if rol == "support" and minuto >= 6:
        return ("Baratija · Lente del Oráculo",
                "Cuando vuelvas a base, cambia el Tótem por la Lente: de support tu trabajo es quitarles la visión.")
    if rol == "jungla" and minuto >= 4:
        return ("Baratija · Lente del Oráculo",
                "En tu próxima vuelta a base, cambia el Tótem por la Lente: limpia sus guardianes antes de cada objetivo.")
    if rol in ("top", "mid", "bot") and minuto >= 15:
        return ("Baratija · Lente del Oráculo",
                "Acabó la fase de líneas: en base cambia el Tótem por la Lente para limpiar visión antes de dragón y Barón.")
    return None


def _seg_txt(seg):
    seg = max(0, int(math.ceil(seg)))
    return f"{seg // 60}:{seg % 60:02d}"


def objetivos_vivo(data, mi_team):
    """Temporizadores de los objetivos grandes con lo que anuncia la partida a todos (Live Client): cuando sale el
    siguiente dragon (o el Anciano), las larvas, el Heraldo y el Baron, quien lleva cuantos dragones y los bufos
    activos. None fuera de la Grieta normal (otros modos tienen otros tiempos: mejor nada que un tiempo falso)."""
    gd = data.get("gameData") or {}
    try:
        mapa = int(gd.get("mapNumber") or 0)
    except (TypeError, ValueError):
        mapa = 0
    if (gd.get("gameMode") or "").upper() != "CLASSIC" or mapa != 11 or mi_team not in ("ORDER", "CHAOS"):
        return None
    t = float(gd.get("gameTime") or 0)
    eq = {}
    for pl in data.get("allPlayers") or []:
        for x in (pl.get("riotIdGameName"), pl.get("summonerName"), pl.get("riotId"), (pl.get("riotId") or "").split("#")[0]):
            if x:
                eq[x] = pl.get("team")

    def mio(e):
        for nombre in [e.get("KillerName"), *(e.get("Assisters") or [])]:
            if nombre in eq:
                return eq[nombre] == mi_team
        return None
    evs = ((data.get("events") or {}).get("Events")) or []
    vistos, dr, anc, bar, her, larvas = set(), [], [], [], [], 0
    for e in sorted(evs, key=lambda x: float(x.get("EventTime") or 0)):
        idx = e.get("EventID") if e.get("EventID") is not None else (e.get("EventName"), e.get("EventTime"))
        if idx in vistos:
            continue
        vistos.add(idx)
        nm, te = e.get("EventName"), float(e.get("EventTime") or 0)
        if nm == "DragonKill":
            if (e.get("DragonType") or "").lower() == "elder":
                anc.append((te, mio(e)))
            else:
                dr.append((te, mio(e), e.get("DragonType") or ""))
        elif nm == "BaronKill":
            bar.append((te, mio(e)))
        elif nm == "HeraldKill":
            her.append((te, mio(e)))
        elif nm == "HordeKill":
            larvas += 1
    nuestros = sum(1 for d in dr if d[1] is True)
    suyos = sum(1 for d in dr if d[1] is False)
    alma, cuenta = None, {True: 0, False: 0}
    for i, d in enumerate(dr):
        if d[1] is not None:
            cuenta[d[1]] += 1
        if cuenta[True] >= 4 or cuenta[False] >= 4 or i >= 6:      # 4 de un equipo (7 en total como mucho)
            alma = (d[0], True if cuenta[True] >= 4 else False if cuenta[False] >= 4 else None)
            break
    punto = None
    if alma is None:
        punto = "ambos" if nuestros == 3 and suyos == 3 else "tuyo" if nuestros == 3 else "suyo" if suyos == 3 else None
    fichas = []
    if alma is None:
        tipo = dr[2][2] if len(dr) >= 3 else ""                 # desde el 3º el dragon es siempre del mismo tipo
        f = {"clave": "dragon", "grupo": "dragon", "nombre": "Dragón" + (f" {DRAGON_ES[tipo]}" if tipo in DRAGON_ES else ""),
             "corto": "Dragón", "ico": DRAGON_ICONO.get(tipo, "dragon"),
             "sale": OBJ_DRAGON_1 if not dr else dr[-1][0] + OBJ_DRAGON_RE,
             "sub": f"{nuestros}–{suyos}", "sub_tono": {"tuyo": "bien", "suyo": "mal", "ambos": "oro"}.get(punto, "")}
    else:
        ultimo = max([alma[0]] + [a[0] for a in anc])
        f = {"clave": "anciano", "grupo": "dragon", "nombre": "Dragón anciano", "corto": "Anciano", "ico": "dragon_elder",
             "sale": ultimo + OBJ_ANCIANO_RE, "sub": f"{nuestros}–{suyos}",
             "sub_tono": "bien" if alma[1] is True else "mal" if alma[1] is False else ""}
        if anc and anc[-1][1] is not None and t - anc[-1][0] < BUFO_ANCIANO:
            f["bufo"] = {"mio": anc[-1][1], "hasta": anc[-1][0] + BUFO_ANCIANO, "desde": anc[-1][0]}
    fichas.append(f)
    if t < OBJ_LARVAS_FIN and larvas < 3:
        fichas.append({"clave": "larvas", "grupo": "larvas", "nombre": "Larvas del vacío", "corto": "Larvas", "ico": "grub",
                       "sale": OBJ_LARVAS, "fin": OBJ_LARVAS_FIN, "sub": f"{larvas}/3" if larvas else "×3", "sub_tono": ""})
    elif t < OBJ_HERALDO_FIN and not her:
        fichas.append({"clave": "heraldo", "grupo": "heraldo", "nombre": "Heraldo", "corto": "Heraldo", "ico": "riftherald",
                       "sale": OBJ_HERALDO, "fin": OBJ_HERALDO_FIN, "sub": "", "sub_tono": ""})
    f = {"clave": "baron", "grupo": "baron", "nombre": "Barón", "corto": "Barón", "ico": "baron",
         "sale": OBJ_BARON_1 if not bar else bar[-1][0] + OBJ_BARON_RE, "sub": "", "sub_tono": ""}
    if bar and bar[-1][1] is not None and t - bar[-1][0] < BUFO_BARON:
        f["bufo"] = {"mio": bar[-1][1], "hasta": bar[-1][0] + BUFO_BARON, "desde": bar[-1][0]}
    fichas.append(f)
    return {"t": t, "fichas": fichas, "dragones": [nuestros, suyos], "punto_alma": punto,
            "alma": None if alma is None else ("tuya" if alma[1] else "suya" if alma[1] is False else "")}


def texto_aviso_objetivo(f, falta, rol, ob):
    """(titulo, texto) del aviso de un objetivo que va a salir, segun tu linea."""
    titulo = f"{f['nombre']} · " + ("ya está" if falta <= 3 else f"sale en {_seg_txt(falta)}")
    tabla = AVISO_OBJ.get(f["clave"]) or {}
    txt = tabla.get(rol) or tabla.get("*") or ""
    if f["clave"] == "dragon" and (ob or {}).get("punto_alma"):
        txt = {"tuyo": "Es vuestro punto de alma: ", "suyo": "Es su punto de alma, que no lo cojan gratis: ",
               "ambos": "Punto de alma para los dos: "}[ob["punto_alma"]] + txt[:1].lower() + txt[1:]
    return titulo, txt


def avisos_objetivos_cfg(pref=None):
    """Lo que elegiste en Ajustes para los objetivos: que avisos, con cuanta antelacion y si suenan."""
    p = pref if pref is not None else Hud._leer_pref()
    av = p.get("avisos") if isinstance(p.get("avisos"), dict) else {}
    try:
        ant = max(15, min(120, int(p.get("antelacion") or 60)))
    except (TypeError, ValueError):
        ant = 60
    return {"avisos": {k: bool(av.get(k, True)) for k in ("dragon", "larvas", "heraldo", "baron")},
            "antelacion": ant, "sonido": bool(p.get("sonido", True)), "timers": bool(p.get("timers", True)),
            "equipo": bool(p.get("equipo", True)), "baratija": bool(p.get("baratija", True))}


_ICO_OBJ = {"fallo": {}, "bajando": set()}


def icono_objetivo(nombre):
    """Ruta del icono del minimapa de un objetivo (CommunityDragon) en la cache. Si aun no esta, lo baja en otro
    hilo y devuelve None (la tarjeta lo pinta sin icono hasta entonces)."""
    if not nombre or not re.fullmatch(r"[a-z_]+", nombre):
        return None
    ruta = CACHE / f"obj_{nombre}.png"
    if ruta.exists():
        return str(ruta)
    if nombre in _ICO_OBJ["bajando"] or time.time() - _ICO_OBJ["fallo"].get(nombre, 0) < 600:
        return None
    _ICO_OBJ["bajando"].add(nombre)

    def bajar():
        try:
            req = urllib.request.Request("https://raw.communitydragon.org/latest/game/assets/ux/minimap/icons/"
                                         f"{nombre}.png", headers={"User-Agent": "coach-lol"})
            with urllib.request.urlopen(req, timeout=8) as r:
                datos = r.read()
            if not datos.startswith(b"\x89PNG"):
                raise ValueError("no es un PNG")
            CACHE.mkdir(parents=True, exist_ok=True)
            tmp = ruta.with_name(ruta.name + ".tmp")
            tmp.write_bytes(datos)
            os.replace(tmp, ruta)
        except Exception:
            _ICO_OBJ["fallo"][nombre] = time.time()
        finally:
            _ICO_OBJ["bajando"].discard(nombre)
    threading.Thread(target=bajar, daemon=True).start()
    return None


def sonar_aviso():
    """Un sonido corto de Windows con cada aviso de objetivo (se quita en Ajustes)."""
    if os.name != "nt":
        return
    try:
        import winsound
        for alias in ("Notification.Default", "SystemAsterisk"):
            try:
                winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                return
            except RuntimeError:
                continue
        raise RuntimeError("ningún sonido de Windows disponible")
    except Exception as e:
        if not _ICO_OBJ.get("sin_sonido"):
            _ICO_OBJ["sin_sonido"] = True
            log(f"Aviso de objetivo sin sonido: {type(e).__name__}: {e}")


# =============================================================== VENTANA FLOTANTE
def _fuentes_privadas():
    """Windows: deja disponibles, solo para este programa, las fuentes de la carpeta 'fuente' (las mismas letras
    que usa la app). Si algo falla se usan las de Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes
        for f in sorted((RECURSOS / "fuente").glob("hud_*.ttf")):
            ctypes.windll.gdi32.AddFontResourceExW(str(f), 0x10, 0)          # FR_PRIVATE
    except Exception:
        pass


class Letras:
    """Las cuatro voces de letra de las ventanitas: cifras (estrecha y gruesa), etiquetas, texto y negrita.
    Usa las fuentes propias si se pudieron cargar; si no, las de Windows que mas se parecen."""
    OPCIONES = {"num": [("CoachLoL Num", "normal"), ("Bahnschrift SemiBold Condensed", "normal"),
                        ("Bahnschrift SemiBold", "normal"), ("Segoe UI", "bold")],
                "eti": [("CoachLoL Eti", "normal"), ("Bahnschrift SemiBold", "normal"), ("Segoe UI", "bold")],
                "txt": [("CoachLoL Txt", "normal"), ("Segoe UI", "normal")],
                "neg": [("CoachLoL Neg", "normal"), ("Segoe UI Semibold", "normal"), ("Segoe UI", "bold")]}

    def __init__(self, root):
        import tkinter.font as tkfont
        self.tkfont, self.root, self._f = tkfont, root, {}
        try:
            hay = {x.lower() for x in tkfont.families(root)}
        except Exception:
            hay = set()
        self.eleccion = {}
        for voz, ops in self.OPCIONES.items():
            self.eleccion[voz] = next(((f, p) for f, p in ops if f.lower() in hay), ops[-1])

    def f(self, voz, px):
        """Fuente de esa voz a 'px' pixeles de alto (objeto Font, para poder medir textos)."""
        k = (voz, int(px))
        if k not in self._f:
            fam, peso = self.eleccion[voz]
            self._f[k] = self.tkfont.Font(root=self.root, family=fam, size=-int(px), weight=peso)
        return self._f[k]

    def t(self, voz, px):
        """Lo mismo como tupla, para los widgets normales."""
        fam, peso = self.eleccion[voz]
        return (fam, -int(px), peso)


def _envolver(fuente, texto, ancho, max_lineas=3):
    """Parte un texto en lineas que caben en 'ancho' pixeles (midiendo con la fuente real). Si no cabe en
    max_lineas, la ultima termina en puntos suspensivos."""
    lineas, actual = [], ""
    for palabra in str(texto or "").split():
        prueba = (actual + " " + palabra).strip()
        if not actual or fuente.measure(prueba) <= ancho:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    if len(lineas) > max_lineas:
        lineas = lineas[:max_lineas]
        ult = lineas[-1]
        while ult and fuente.measure(ult + "…") > ancho:
            ult = ult[:-1].rstrip()
        lineas[-1] = ult + "…"
    return lineas


class Hud:
    """Tarjetas de partida. UNA ventana fija, transparente y que deja pasar los clics: se muestra al empezar la
    partida y no se mueve, no cambia de tamaño ni se oculta hasta que termina. Todo lo que cambia se dibuja
    dentro de un lienzo, actualizando cada texto en su sitio: nada se crea ni se destruye mientras juegas, asi
    que no parpadea ni le quita el foco al juego.
      - mini: tus numeros y el estado de la mision, siempre a la vista;
      - detalle: mision, reto y siguiente objeto, mientras mantienes Tab;
      - objetivos: cuanto falta para el dragon, las larvas o el Heraldo y el Baron, siempre a la vista;
      - avisos: salen solos unos segundos (con icono, entrada corta y una barra que marca cuanto les queda)."""
    CLAVE = "#010203"                     # color que Windows vuelve transparente (lo que no es tarjeta)
    C = {"fondo": "#0A0F18", "borde": "#25314A", "linea": "#1B2538", "tinta": "#F2F5FA", "gris": "#93A0B8",
         "tenue": "#65728B", "bien": "#3DDC97", "mal": "#FF6B7D", "azul": "#5AA9FF", "oro": "#E6C36A"}
    MUESTRA = {"filas": [{"et": "CS/min", "yo": "6,4", "ref": "5,8", "tono": "bien"},
                         {"et": "Oro/min", "yo": "382", "ref": "404", "tono": "mal"},
                         {"et": "KP %", "yo": "58"}, {"et": "KDA", "yo": "3,5", "ref": "2,1", "tono": "bien"},
                         {"et": "CS vs Ahri", "yo": "+12", "ref": "niv 9/8", "tono": "bien"},
                         {"et": "Sube habilidad", "yo": "Q", "ref": "Q › E › W", "tono": "azul"}],
               "tira_ids": [(3020, "ok"), (6655, "ok"), (3089, "sig"), (3157, "pend"), (3135, "pend"), (3165, "pend")],
               "oro_pct": 0.62,
               "ref": "Bronce", "mision_nombre": "No morir solo", "mision_st": "curso",
               "mision": "Desde el minuto 14, 0 muertes sin tu equipo en la pelea",
               "mision_estado": "Muertes sin tu equipo desde el 14: 0",
               "reto": "Participación en kills", "reto_meta": "% de las kills de tu equipo: ≥ 53 %",
               "objeto": "Siguiente: Sombrero de Rabadon · te faltan 420 de oro",
               "obj": [{"clave": "dragon", "corto": "Dragón", "ico": "dragon_infernal", "sale": 1150, "sub": "2–1", "sub_tono": ""},
                       {"clave": "heraldo", "corto": "Heraldo", "ico": "riftherald", "sale": 900, "fin": 1185, "sub": "", "sub_tono": ""},
                       {"clave": "baron", "corto": "Barón", "ico": "baron", "sale": 1200, "sub": "", "sub_tono": ""}],
               "eq": {"prob": 61, "dif": 1840, "kills": [14, 9], "torres": [3, 1]},
               "guia": {"rival": "Ahri", "dato": "Tu campeón gana 47,8 % contra él en Esmeralda+ · tú 1V 2D", "tono": "mal",
                        "tips": ["Desde su nivel 6 tiene la definitiva: respeta más sus entradas.",
                                 "Ahri es mucho más vulnerable sin su definitiva, Impulso espiritual."]}}
    MUESTRA_T = 1140                      # minuto 19:00 en la prueba

    def __init__(self, ventana):
        self.v, self.tk, self.root, self.L = ventana, ventana.tk, ventana.root, ventana.L
        self.pref = self._leer_pref()
        self.esc = float(self.pref.get("escala") or 1.0)
        self.W, self.H = self.e(250), self.e(920)
        self.win = self.tk.Toplevel(self.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=self.CLAVE)
        try:
            self.win.attributes("-alpha", self._alpha())
            if os.name == "nt":
                self.win.attributes("-transparentcolor", self.CLAVE)
        except Exception:
            pass
        self.cv = self.tk.Canvas(self.win, width=self.W, height=self.H, bg=self.CLAVE, highlightthickness=0, bd=0)
        self.cv.pack()
        self.estado = None                 # ultimo estado de partida (None = sin partida)
        self.datos = {}                    # lo que hay dibujado
        self.aviso, self.aviso_hasta, self.aviso_dur = None, 0.0, 8.0
        self.demo_hasta, self.mover, self._demo_ini = 0.0, False, 0.0
        self._obj_anc = None               # (tiempo de partida, reloj) del ultimo dato: el contador corre solo entre medias
        self._obj_img = {}                 # (icono, lado) -> imagen reducida
        self._anim_t, self._anim_d0, self._anim_dx = None, 0, 0
        self._aviso_n, self._aviso_visto = 0, 0  # cada aviso nuevo entra deslizando una sola vez
        self._pb = None                    # (x0, x1, y) de la barra de tiempo del aviso
        self.mapeada = False
        self._vis = {}                     # tarjeta -> visible
        self._img, self._img_ruta = None, None
        self._tira_img = {}                # icono -> imagen reducida para la tira de la build
        self._cache = {}                   # lo ultimo puesto en cada elemento del lienzo
        self._drag = None
        self._ctrl = False                 # Ctrl pulsado con el raton encima: se pueden arrastrar en partida
        self._t_inicio, self._visto_juego, self._t_estilo = 0.0, False, 0.0
        self._construir()
        self.cv.bind("<ButtonPress-1>", self._ini)
        self.cv.bind("<B1-Motion>", self._arrastrar)
        self.cv.bind("<ButtonRelease-1>", self._fin)
        self.root.after(80, self._tic)

    # ---------------------------------------------------------------- preferencias
    def e(self, n):
        return int(round(n * self.esc))

    def _alpha(self):
        try:
            return max(0.45, min(1.0, float(self.pref.get("opacidad", CONFIG.get("hud_opacidad", 0.9)))))
        except Exception:
            return 0.9

    @staticmethod
    def _leer_pref():
        try:
            p = json.loads((DATOS / "ventana.json").read_text(encoding="utf-8"))
            h = p.get("hud") if isinstance(p.get("hud"), dict) else {}
            if "x" not in h and "hx" in p:                 # posicion guardada por la version anterior
                h = dict(h, x=p["hx"], y=p["hy"])
            return h
        except Exception:
            return {}

    def _guardar_pref(self):
        try:
            f = DATOS / "ventana.json"
            p = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
            p["hud"] = self.pref
            p.pop("hx", None), p.pop("hy", None)
            f.write_text(json.dumps(p), encoding="utf-8")
        except Exception:
            pass

    def _pantalla(self):
        """(x, y, ancho, alto) de toda el area de pantallas."""
        if os.name == "nt":
            try:
                import ctypes
                g = ctypes.windll.user32.GetSystemMetrics
                return g(76), g(77), g(78), g(79)
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _pos(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if "x" in self.pref and "y" in self.pref:
            x, y = int(self.pref["x"]), int(self.pref["y"])
        else:
            x, y = self._pos_de(self.pref.get("lugar") or "izq-centro")
        vx, vy, vw, vh = self._pantalla()
        return (max(vx - self.W + 60, min(x, vx + vw - 60)), max(vy, min(y, vy + vh - 80)))

    def _pos_de(self, lugar):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        m = self.e(18)
        lado, alto = (lugar.split("-") + ["centro"])[:2]
        x = m if lado == "izq" else sw - self.W - m
        y = {"arriba": int(sh * 0.06), "centro": int(sh * 0.24), "abajo": int(sh * 0.50)}.get(alto, int(sh * 0.24))
        return x, y

    def configurar(self, cambios):
        """Cambios hechos desde la app: opacidad, tamaño, mini siempre visible, lugar."""
        reconstruir = False
        for k in ("opacidad", "mini", "escala", "lugar", "timers", "avisos", "antelacion", "sonido", "equipo", "baratija"):
            if k in cambios:
                if k == "escala" and float(cambios[k]) != self.esc:
                    reconstruir = True
                self.pref[k] = cambios[k]
        if "lugar" in cambios:
            self.pref.pop("x", None), self.pref.pop("y", None)
        self._guardar_pref()
        try:
            self.win.attributes("-alpha", self._alpha())
        except Exception:
            pass
        if reconstruir:
            self.esc = float(self.pref.get("escala") or 1.0)
            self.W, self.H = self.e(250), self.e(920)
            self.cv.delete("all")
            self.cv.config(width=self.W, height=self.H)
            self._vis, self.datos, self._img_ruta, self._cache = {}, {}, None, {}
            self._construir()
        if self.mapeada:
            x, y = self._pos()
            self.win.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self._dibujar(forzar=True)

    def probar(self, segundos=14, mover=False):
        """Muestra las tarjetas con datos de ejemplo (para verlas y colocarlas sin estar en partida)."""
        self.demo_hasta, self.mover, self._demo_ini = time.time() + segundos, bool(mover), time.time()
        self._dibujar(forzar=True)
        self._actualizar_ventana()
        self._estilo()                      # al colocarlas tienen que recibir el raton

    # ---------------------------------------------------------------- arrastrar (al colocarlas o con Ctrl)
    def _ini(self, ev):
        if self.mover or self._ctrl:
            self._drag = (ev.x_root - self.win.winfo_x(), ev.y_root - self.win.winfo_y())

    def _arrastrar(self, ev):
        if self._drag:
            x, y = ev.x_root - self._drag[0], ev.y_root - self._drag[1]
            self.pref["x"], self.pref["y"] = x, y
            self.win.geometry(f"+{x}+{y}")
            self.demo_hasta = max(self.demo_hasta, time.time() + 8)

    def _fin(self, ev):
        if self._drag:
            self._drag = None
            self._guardar_pref()
            self._ctrl = self._ctrl_encima()
            self._estilo()

    def _ctrl_encima(self):
        """True si mantienes Ctrl con el raton encima de las tarjetas: entonces dejan de pasar los clics al
        juego para que puedas arrastrarlas. Al soltar Ctrl vuelven a dejarlos pasar."""
        if os.name != "nt" or not self.mapeada:
            return False
        try:
            import ctypes
            if not ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000:
                return False
            px, py = self.root.winfo_pointerxy()
            x, y = self.win.winfo_rootx(), self.win.winfo_rooty()
            return x <= px < x + self.W and y <= py < y + self.H
        except Exception:
            return False

    # ---------------------------------------------------------------- lo que llega del coach
    def poner(self, s):
        nueva = self.estado is None
        self.estado = s
        if nueva:
            self._t_inicio, self._visto_juego = time.time(), False
        ob = s.get("objetivos")
        if ob and ob.get("t") is not None:
            self._obj_anc = (float(ob["t"]), time.time())
        if s.get("aviso"):
            self.aviso_dur = float(s.get("aviso_seg") or 8)
            self.aviso = (s["aviso"], s.get("tono", "azul"), s.get("aviso_tit") or "", s.get("aviso_ico") or "")
            self.aviso_hasta = time.time() + self.aviso_dur
            self._aviso_n += 1
        self._dibujar()
        self._actualizar_ventana()

    def quitar(self):
        if self.estado is not None:
            self.estado, self.aviso = None, None
            self._actualizar_ventana()

    # ---------------------------------------------------------------- Windows
    def _hwnd(self):
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.GetParent.argtypes = [wintypes.HWND]
            u.GetParent.restype = wintypes.HWND
            return u.GetParent(wintypes.HWND(self.win.winfo_id())) or None
        except Exception:
            return None

    def _estilo(self):
        """No se activa nunca, no sale en la barra de tareas, deja pasar los clics (menos al colocarla) y va
        siempre encima. Solo toca la ventana si algo de eso se perdio."""
        hwnd = self._hwnd()
        if not hwnd:
            return
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            u.GetWindowLongW.restype = ctypes.c_long
            u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            u.SetWindowLongW.restype = ctypes.c_long
            u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            NOACT, TOOL, PASA, TOPMOST = 0x08000000, 0x00000080, 0x00000020, 0x00000008
            ex = u.GetWindowLongW(hwnd, -20)
            libre = self.mover or self._ctrl or self._drag is not None
            quiero = (ex | NOACT | TOOL | PASA) if not libre else ((ex | NOACT | TOOL) & ~PASA)
            if quiero != ex:
                u.SetWindowLongW(hwnd, -20, quiero)
            if not (ex & TOPMOST) or quiero != ex:
                # HWND_TOPMOST; NOSIZE | NOMOVE | NOACTIVATE | FRAMECHANGED | NOOWNERZORDER
                u.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0020 | 0x0200)
        except Exception:
            pass

    def _tecla(self):
        if os.environ.get("COACH_HUD_SIEMPRE"):
            return True
        if os.name != "nt":
            return False
        try:
            import ctypes
            g = ctypes.windll.user32.GetAsyncKeyState
            return bool(g(int(CONFIG.get("hud_tecla", 0x09))) & 0x8000) and not (g(0x12) & 0x8000)   # sin Alt
        except Exception:
            return False

    def _juego_delante(self):
        """True si la ventana activa es la partida de LoL: asi las tarjetas no se quedan encima de otra cosa
        cuando cambias de ventana. Si en 25 segundos no se reconoce la partida, deja de filtrar (mejor de mas)."""
        if os.name != "nt" or os.environ.get("COACH_HUD_SIEMPRE"):
            return True
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.GetForegroundWindow.restype = wintypes.HWND
            h = u.GetForegroundWindow()
            clase, titulo = ctypes.create_unicode_buffer(128), ctypes.create_unicode_buffer(200)
            u.GetClassNameW(wintypes.HWND(h), clase, 128)
            u.GetWindowTextW(wintypes.HWND(h), titulo, 200)
            es = clase.value == "RiotWindowClass" or titulo.value.startswith("League of Legends (TM)")
            if es:
                self._visto_juego = True
            if not self._visto_juego and time.time() - self._t_inicio > 25:
                return True
            return es
        except Exception:
            return True

    # ---------------------------------------------------------------- ventana y ritmo
    def _actualizar_ventana(self):
        """La ventana solo se muestra al empezar la partida (o una prueba) y se oculta al terminar."""
        hace_falta = self.estado is not None or time.time() < self.demo_hasta
        if hace_falta and not self.mapeada:
            x, y = self._pos()
            self.win.geometry(f"{self.W}x{self.H}+{x}+{y}")
            self.win.deiconify()
            self.mapeada = True
            try:
                self.win.update_idletasks()
            except Exception:
                pass
            self._estilo()
        elif not hace_falta and self.mapeada:
            self.win.withdraw()
            self.mapeada = False

    def _tic(self):
        try:
            ahora = time.time()
            if self.demo_hasta and ahora >= self.demo_hasta:
                self.demo_hasta, self.mover = 0.0, False
                self._dibujar(forzar=True)
                self._actualizar_ventana()
                self._estilo()
            if self.aviso and ahora > self.aviso_hasta:
                self.aviso = None
            if self.mapeada:
                self._tic_vivo(ahora)
                ctrl = self._ctrl_encima()
                if ctrl != self._ctrl and self._drag is None:
                    self._ctrl = ctrl
                    self._estilo()
                if ahora - self._t_estilo > 1.5:
                    self._t_estilo = ahora
                    self._estilo()
                self._visibilidad()
        except Exception as ex:
            if not getattr(self, "_err", False):
                self._err = True
                log(f"Tarjetas de partida: {type(ex).__name__}: {ex}")
        self.root.after(50, self._tic)

    # ---------------------------------------------------------------- lo que se mueve solo
    def _t_juego(self, ahora):
        """Tiempo de partida ahora mismo: el ultimo dato mas lo que paso desde entonces (como mucho 6 s: si el
        coach deja de recibir datos, el contador se para en vez de inventar)."""
        if ahora < self.demo_hasta:
            return self.MUESTRA_T + (ahora - self._demo_ini)
        if not self._obj_anc:
            return None
        t0, ts = self._obj_anc
        return t0 + min(max(0.0, ahora - ts), 6.0)

    def _tic_vivo(self, ahora):
        """Cada 50 ms: los contadores de los objetivos y la barra del aviso. Solo cambia lo que cambia."""
        C, cfg, xy = self.C, self._cfg, self._xy
        if self._cache.get(("v", "obj")):
            tj = self._t_juego(ahora)
            ant = avisos_objetivos_cfg(self.pref)["antelacion"]
            for i, f in enumerate((self.datos.get("obj") or [])[:3]):
                b = f.get("bufo")
                barra = None
                if tj is None:
                    txt, col = "–", C["gris"]
                elif b and tj < b["hasta"]:
                    txt, col = _seg_txt(b["hasta"] - tj), C["bien"] if b["mio"] else C["mal"]
                    barra = col
                elif tj >= f["sale"]:
                    if f.get("fin") and tj >= f["fin"]:
                        txt, col = "–", C["tenue"]
                    else:
                        txt, col = "VIVO", C["bien"]
                        barra = col
                else:
                    falta = f["sale"] - tj
                    txt, col = _seg_txt(falta), C["oro"] if falta <= ant else C["tinta"]
                    barra = C["oro"] if falta <= ant else None
                cfg(self.it[f"ob_t{i}"], text=txt, fill=col)
                if b and tj is not None and tj < b["hasta"]:
                    cfg(self.it[f"ob_s{i}"], text="TUYO" if b["mio"] else "SUYO", fill=col)
                else:
                    cfg(self.it[f"ob_s{i}"], text=f.get("sub") or "",
                        fill={"bien": C["bien"], "mal": C["mal"], "oro": C["oro"]}.get(f.get("sub_tono"), C["gris"]))
                cfg(self.it[f"ob_b{i}"], fill=barra or C["fondo"])
        if self._cache.get(("v", "aviso")) and self._pb and self._anim_t is None:
            demo = ahora < self.demo_hasta
            fin, dur = (self.demo_hasta, max(1.0, self.demo_hasta - self._demo_ini)) if demo else (self.aviso_hasta, self.aviso_dur)
            frac = max(0.0, min(1.0, (fin - ahora) / dur))
            x0, x1, yb = self._pb
            xy(self.it["a_pb1"], x0, yb, x0 + round((x1 - x0) * frac), yb + self.e(3))

    def _animar_aviso(self):
        """Entrada del aviso: se desliza unos pixeles desde la izquierda en 0,22 s (ease-out)."""
        if self._anim_t is None:
            return
        p = min(1.0, (time.time() - self._anim_t) / 0.22)
        quiero = round(self._anim_d0 * (1 - (1 - (1 - p) ** 3)))
        if quiero != self._anim_dx:
            self.cv.move("aviso", quiero - self._anim_dx, 0)
            self._anim_dx = quiero
        if p < 1:
            self.root.after(15, self._animar_aviso)
        else:
            self._anim_t = None

    def _foto_obj(self, ruta, lado):
        k = (ruta, lado)
        if k not in self._obj_img:
            try:
                from fractions import Fraction
                im = self.tk.PhotoImage(file=ruta)
                fr = Fraction(lado, im.width()).limit_denominator(16)
                if fr != 1:
                    im = (im.zoom(fr.numerator) if fr.numerator > 1 else im).subsample(fr.denominator)
                self._obj_img[k] = im
            except Exception:
                return None                                # no se guarda: se reintenta cuando el icono ya este bajado
        return self._obj_img[k]

    # ---------------------------------------------------------------- dibujo
    def _cfg(self, item, **kw):
        """Cambia opciones de un elemento del lienzo solo si son distintas de las que ya tiene."""
        ant = self._cache.setdefault(("c", item), {})
        nuevo = {k: v for k, v in kw.items() if ant.get(k, self) != v}
        if nuevo:
            ant.update(nuevo)
            self.cv.itemconfigure(item, **nuevo)

    def _xy(self, item, *c):
        if self._cache.get(("p", item)) != c:
            self._cache[("p", item)] = c
            self.cv.coords(item, *c)

    def _rr(self, x1, y1, x2, y2, r):
        return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
                x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]

    def _construir(self):
        """Crea una sola vez todo lo que se puede llegar a ver; despues solo se cambian textos, colores y sitios."""
        cv, C, e, L = self.cv, self.C, self.e, self.L
        self.P = e(12)                                   # margen interior
        self.it = {}

        def caja(nombre):
            self.it[nombre] = cv.create_polygon(self._rr(0, 0, self.W - 1, 10, e(9)), smooth=True, fill=C["fondo"],
                                                outline=C["borde"], width=1, tags=(nombre,), state="hidden")

        def texto(clave, tarjeta, voz, px, color, anchor="nw"):
            self.it[clave] = cv.create_text(0, 0, text="", font=L.f(voz, e(px)), fill=color, anchor=anchor,
                                            tags=(tarjeta,), state="hidden", justify="left")
        # --- mini
        caja("mini")
        texto("m_marca", "mini", "eti", 9.5, C["azul"])
        texto("m_ref", "mini", "txt", 10.5, C["tenue"], "ne")
        for i in range(6):
            texto(f"m_et{i}", "mini", "eti", 10.5, C["gris"])
            texto(f"m_yo{i}", "mini", "num", 17, C["tinta"], "ne")
            texto(f"m_rf{i}", "mini", "txt", 12, C["tenue"])
        self.it["m_raya"] = cv.create_line(0, 0, 0, 0, fill=C["linea"], tags=("mini",), state="hidden")
        self.it["m_punto"] = cv.create_oval(0, 0, 0, 0, fill=C["gris"], outline="", tags=("mini",), state="hidden")
        texto("m_mis", "mini", "neg", 11.5, C["tinta"])
        texto("m_st", "mini", "eti", 9.5, C["gris"], "ne")
        # --- objetivos (dragon, larvas o Heraldo, Baron)
        caja("obj")
        for i in range(3):
            self.it[f"ob_i{i}"] = cv.create_image(0, 0, anchor="nw", tags=("obj",), state="hidden")
            self.it[f"ob_o{i}"] = cv.create_oval(0, 0, 0, 0, fill=C["linea"], outline="", tags=("obj",), state="hidden")
            texto(f"ob_l{i}", "obj", "eti", 11, C["gris"], "center")
            texto(f"ob_t{i}", "obj", "num", 17, C["tinta"])
            texto(f"ob_s{i}", "obj", "eti", 9.5, C["gris"])
            self.it[f"ob_b{i}"] = cv.create_rectangle(0, 0, 0, 0, fill=C["fondo"], outline="", tags=("obj",), state="hidden")
            if i:
                self.it[f"ob_d{i}"] = cv.create_line(0, 0, 0, 0, fill=C["linea"], tags=("obj",), state="hidden")
        # --- equipo: probabilidad de ganar, oro en objetos, kills y torres
        caja("eq")
        texto("e_et", "eq", "eti", 9.5, C["gris"])
        texto("e_pct", "eq", "num", 17, C["tinta"], "ne")
        self.it["e_b0"] = cv.create_rectangle(0, 0, 0, 0, fill=C["mal"], outline="", tags=("eq",), state="hidden")
        self.it["e_b1"] = cv.create_rectangle(0, 0, 0, 0, fill=C["azul"], outline="", tags=("eq",), state="hidden")
        self.it["e_m"] = cv.create_line(0, 0, 0, 0, fill=C["fondo"], width=2, tags=("eq",), state="hidden")
        texto("e_oro", "eq", "eti", 10, C["gris"])
        texto("e_k", "eq", "eti", 10, C["gris"], "n")
        texto("e_t", "eq", "eti", 10, C["gris"], "ne")
        # --- aviso
        caja("aviso")
        self.it["a_barra"] = cv.create_rectangle(0, 0, 0, 0, fill=C["azul"], outline="", tags=("aviso",), state="hidden")
        self.it["a_img"] = cv.create_image(0, 0, anchor="nw", tags=("aviso",), state="hidden")
        texto("a_tit", "aviso", "eti", 10.5, C["azul"])
        texto("a_txt", "aviso", "neg", 12.5, C["tinta"])
        self.it["a_pb0"] = cv.create_rectangle(0, 0, 0, 0, fill=C["linea"], outline="", tags=("aviso",), state="hidden")
        self.it["a_pb1"] = cv.create_rectangle(0, 0, 0, 0, fill=C["azul"], outline="", tags=("aviso",), state="hidden")
        # --- mision
        caja("mision")
        texto("mi_et", "mision", "eti", 9.5, C["azul"])
        texto("mi_regla", "mision", "neg", 12.5, C["tinta"])
        texto("mi_est", "mision", "txt", 12, C["gris"])
        # --- reto
        caja("reto")
        texto("r_et", "reto", "eti", 9.5, C["oro"])
        texto("r_nom", "reto", "neg", 12.5, C["tinta"])
        texto("r_meta", "reto", "txt", 12, C["gris"])
        # --- objeto
        caja("objeto")
        self.it["o_img"] = cv.create_image(0, 0, anchor="nw", tags=("objeto",), state="hidden")
        for k in range(6):                                # tu build: comprado (verde), siguiente (azul), despues
            self.it[f"o_r{k}"] = cv.create_rectangle(0, 0, 0, 0, outline=C["borde"], width=2, tags=("objeto",), state="hidden")
            self.it[f"o_i{k}"] = cv.create_image(0, 0, anchor="nw", tags=("objeto",), state="hidden")
        self.it["o_pb0"] = cv.create_rectangle(0, 0, 0, 0, fill=C["linea"], outline="", tags=("objeto",), state="hidden")
        self.it["o_pb1"] = cv.create_rectangle(0, 0, 0, 0, fill=C["azul"], outline="", tags=("objeto",), state="hidden")
        texto("o_txt", "objeto", "neg", 12.5, C["tinta"])
        texto("o_base", "objeto", "neg", 12, C["bien"])
        # --- guia contra tu rival de linea
        caja("guia")
        texto("g_et", "guia", "eti", 9.5, C["mal"])
        texto("g_dato", "guia", "txt", 12, C["gris"])
        texto("g_tips", "guia", "neg", 12, C["tinta"])
        # --- ayuda al colocar
        caja("ayuda")
        texto("y_txt", "ayuda", "neg", 12, C["azul"])

    def _lin(self, voz, px):
        return self.L.f(voz, self.e(px)).metrics("linespace")

    def _dibujar(self, forzar=False):
        """Pone textos y calcula el sitio de cada tarjeta. No toca nada si los datos no cambiaron."""
        demo = time.time() < self.demo_hasta
        h = self.MUESTRA if demo else ((self.estado or {}).get("hud") or {})
        if demo:
            ico_b = CACHE / "obj_baron.png"
            aviso = ("Agrupaos en mid y poned visión cerca del foso. Nadie solo en las líneas laterales.", "oro",
                     "Barón · sale en 1:00", str(ico_b) if ico_b.exists() else "")
        else:
            aviso = self.aviso
        obj = h.get("obj") or []
        if demo:
            obj = [dict(f, ico_ruta=str(CACHE / f"obj_{f['ico']}.png") if (CACHE / f"obj_{f['ico']}.png").exists() else None)
                   for f in obj]
        firma = json.dumps([h, aviso, demo, self.mover, self.pref.get("timers", True), self.pref.get("equipo", True)],
                           sort_keys=True, ensure_ascii=False)
        if firma == self.datos.get("firma") and not forzar:
            return
        cv, C, e, P, W, L = self.cv, self.C, self.e, self.P, self.W, self.L
        it, cfg, xy = self.it, self._cfg, self._xy
        ancho = W - 2 * P
        alto = {}                                          # tarjeta -> alto (0 = no existe ahora)
        hay = {}

        def poner_caja(nombre, y, a, borde=None):
            xy(it[nombre], *self._rr(0, y, W - 1, y + a, e(9)))
            cfg(it[nombre], outline=borde or C["borde"])

        # ---- alturas y textos (las posiciones se ponen despues, de arriba abajo)
        filas = (h.get("filas") or [])[:6]
        fila_h, cab_h = e(25), e(24)
        hay["mini"] = bool(filas)
        tiene_mis = bool(h.get("mision_nombre"))
        alto["mini"] = (P + cab_h + len(filas) * fila_h + (e(8) + self._lin("neg", 11.5) + e(2) if tiene_mis else 0) + P - e(4)) if filas else 0
        # objetivos: alto fijo, para que lo de debajo no se mueva al cambiar los contadores
        obj = obj[:3] if self.pref.get("timers", True) else []
        hay["obj"] = bool(obj)
        alto["obj"] = e(54) if obj else 0
        obj_fotos = [self._foto_obj(f["ico_ruta"], e(30)) if f.get("ico_ruta") else None for f in obj]
        eq = h.get("eq") if self.pref.get("equipo", True) else None
        hay["eq"] = bool(eq)
        alto["eq"] = e(64) if eq else 0
        # aviso: icono a la izquierda (si lo hay), titulo de color, texto y barra de tiempo
        a_foto = self._foto_obj(aviso[3], e(34)) if aviso and len(aviso) > 3 and aviso[3] else None
        a_izq = (e(34) + e(10)) if a_foto else 0
        a_tit = (aviso[2] if aviso and len(aviso) > 2 else "") or ""
        tit_aviso = _envolver(L.f("eti", e(10.5)), a_tit.upper(), ancho - e(8) - a_izq, 1) if a_tit else []
        txt_aviso = _envolver(L.f("neg", e(12.5)), aviso[0], ancho - e(8) - a_izq, 4) if aviso else []
        hay["aviso"] = bool(txt_aviso)
        cuerpo_av = (len(tit_aviso) * (self._lin("eti", 10.5) + e(2)) + len(txt_aviso) * self._lin("neg", 12.5))
        alto["aviso"] = (P + max(cuerpo_av, e(34) if a_foto else 0) + e(10) + P - e(4)) if txt_aviso else 0
        regla = _envolver(L.f("neg", e(12.5)), h.get("mision"), ancho, 3)
        est = _envolver(L.f("txt", e(12)), h.get("mision_estado"), ancho, 2)
        hay["mision"] = bool(regla)
        alto["mision"] = (P + self._lin("eti", 9.5) + e(3) + len(regla) * self._lin("neg", 12.5) +
                          (e(2) + len(est) * self._lin("txt", 12) if est else 0) + P - e(2)) if regla else 0
        rnom = _envolver(L.f("neg", e(12.5)), h.get("reto"), ancho, 2)
        rmeta = _envolver(L.f("txt", e(12)), h.get("reto_meta"), ancho, 2)
        hay["reto"] = bool(rnom)
        alto["reto"] = (P + self._lin("eti", 9.5) + e(3) + len(rnom) * self._lin("neg", 12.5) +
                        (e(2) + len(rmeta) * self._lin("txt", 12) if rmeta else 0) + P - e(2)) if rnom else 0
        ico = h.get("objeto_ico")
        if ico != self._img_ruta:
            self._img_ruta, self._img = ico, None
            if ico:
                try:
                    img = self.tk.PhotoImage(file=ico)
                    f = max(1, round(img.width() / e(34)))
                    self._img = img.subsample(f) if f > 1 else img
                except Exception:
                    self._img = None
            cfg(it["o_img"], image=self._img or "")
        tira = h.get("tira")
        if demo and not tira:
            tira = [{"ico": str(DATOS / "cache" / f"item_{i}.png"), "estado": st} for i, st in h.get("tira_ids") or []
                    if (DATOS / "cache" / f"item_{i}.png").exists()]
        lado = e(32)
        fotos = []
        for x in (tira or [])[:6]:
            k = (x["ico"], lado)
            if k not in self._tira_img:
                self._tira_img[k] = self._foto_obj(x["ico"], lado)      # escala exacta (tambien al 150 %)
            if self._tira_img[k] is not None:
                fotos.append((self._tira_img[k], x.get("estado")))
        tira_h = (lado + e(10)) if fotos else 0
        img_w = (self._img.width() + e(9)) if (self._img and not fotos) else 0
        otxt = _envolver(L.f("neg", e(12.5)), h.get("objeto"), ancho - img_w, 3)
        obase = _envolver(L.f("neg", e(12)), h.get("base"), ancho - img_w, 2)
        hay["objeto"] = bool(otxt)
        barra = e(10) if h.get("oro_pct") is not None else 0
        cuerpo = len(otxt) * self._lin("neg", 12.5) + (e(2) + len(obase) * self._lin("neg", 12) if obase else 0) + barra
        alto["objeto"] = (P + tira_h + max(cuerpo, self._img.height() if (self._img and not fotos) else 0) + P - e(2)) if otxt else 0
        gu = h.get("guia") or {}
        g_dato = _envolver(L.f("txt", e(12)), gu.get("dato"), ancho, 2) if gu else []
        g_tips = []
        for tip in (gu.get("tips") or [])[:3]:
            g_tips += _envolver(L.f("neg", e(12)), "• " + tip, ancho, 2)
        hay["guia"] = bool(g_tips)
        alto["guia"] = (P + self._lin("eti", 9.5) + e(3) + (len(g_dato) * self._lin("txt", 12) + e(4) if g_dato else 0)
                        + len(g_tips) * self._lin("neg", 12) + P - e(2)) if g_tips else 0
        ayuda = _envolver(L.f("neg", e(12)), "Arrástralas adonde quieras. Se guarda solo.", ancho, 2) if (demo and self.mover) else []
        hay["ayuda"] = bool(ayuda)
        alto["ayuda"] = P + len(ayuda) * self._lin("neg", 12) + P - e(2) if ayuda else 0

        # ---- mini (siempre arriba: no se mueve aunque aparezcan las demas)
        y = 0
        if hay["mini"]:
            poner_caja("mini", y, alto["mini"])
            xy(it["m_marca"], P, y + P - e(1))
            cfg(it["m_marca"], text="COACH LOL")
            xy(it["m_ref"], W - P, y + P - e(3))
            cfg(it["m_ref"], text=("tú / " + h["ref"]) if h.get("ref") else "")
            col_ref = W - P - e(46)
            f_ref = L.f("txt", e(12))
            for i in range(6):
                f = filas[i] if i < len(filas) else None
                fy = y + P + cab_h + i * fila_h
                xy(it[f"m_et{i}"], P, fy + e(5))
                xy(it[f"m_yo{i}"], col_ref - e(6), fy - e(1))
                xy(it[f"m_rf{i}"], col_ref, fy + e(4))
                cfg(it[f"m_et{i}"], text=f["et"].upper() if f else "")
                cfg(it[f"m_yo{i}"], text=f["yo"] if f else "",
                    fill={"bien": C["bien"], "mal": C["mal"], "azul": C["azul"]}.get((f or {}).get("tono"), C["tinta"]))
                ref = (_envolver(f_ref, "/ " + f["ref"], W - e(4) - col_ref, 1) or [""])[0] if f and f.get("ref") else ""
                cfg(it[f"m_rf{i}"], text=ref)
            if tiene_mis:
                ry = y + P + cab_h + len(filas) * fila_h + e(3)
                xy(it["m_raya"], P, ry, W - P, ry)
                st = h.get("mision_st") or "curso"
                col = {"ok": C["bien"], "fallo": C["mal"]}.get(st, C["gris"])
                ty = ry + e(7)
                xy(it["m_punto"], P, ty + e(4), P + e(7), ty + e(11))
                cfg(it["m_punto"], fill=col)
                etq = {"ok": "CUMPLIDA", "fallo": "FALLADA"}.get(st, "EN CURSO")
                fst = L.f("eti", e(9.5))
                xy(it["m_st"], W - P, ty + e(2))
                cfg(it["m_st"], text=etq, fill=col)
                cabe = ancho - e(13) - fst.measure(etq) - e(8)
                nom = (_envolver(L.f("neg", e(11.5)), h["mision_nombre"], cabe, 1) or [""])[0]
                xy(it["m_mis"], P + e(13), ty)
                cfg(it["m_mis"], text=nom)
            else:
                xy(it["m_raya"], 0, 0, 0, 0)
                xy(it["m_punto"], 0, 0, 0, 0)
                cfg(it["m_mis"], text="")
                cfg(it["m_st"], text="")
        self._y = {}
        orden = ["mini", "obj", "eq", "aviso", "mision", "guia", "objeto", "reto", "ayuda"]
        for n in orden:
            self._y[n] = None
        self.datos = {"firma": firma, "hay": hay, "alto": alto, "demo": demo,
                      "aviso": aviso, "regla": regla, "est": est, "rnom": rnom, "rmeta": rmeta,
                      "otxt": otxt, "obase": obase, "img_w": img_w, "txt_aviso": txt_aviso, "ayuda": ayuda,
                      "tit_aviso": tit_aviso, "a_foto": a_foto, "a_izq": a_izq, "obj": obj, "obj_fotos": obj_fotos,
                      "fotos": fotos, "tira_h": tira_h, "lado": lado, "oro_pct": h.get("oro_pct"), "eq": eq,
                      "guia": gu, "g_dato": g_dato, "g_tips": g_tips}
        self._vis = {}                                     # obliga a recolocar con la visibilidad actual
        self._visibilidad()

    def _visibilidad(self):
        """Decide que tarjetas se ven ahora y las coloca una debajo de otra. Solo toca el lienzo si cambia algo."""
        d = self.datos
        if not d:
            return
        demo = time.time() < self.demo_hasta
        delante = demo or self._juego_delante()
        tab = demo or (self.estado is not None and self._tecla())
        en_partida = demo or self.estado is not None
        ver = {"mini": en_partida and delante and d["hay"]["mini"] and (demo or tab or self.pref.get("mini", True)),
               "obj": en_partida and delante and d["hay"].get("obj", False),
               "eq": en_partida and delante and d["hay"].get("eq", False),
               "aviso": en_partida and delante and bool(self.aviso or demo) and d["hay"]["aviso"],
               "mision": en_partida and delante and tab and d["hay"]["mision"],
               "reto": en_partida and delante and tab and d["hay"]["reto"],
               "objeto": en_partida and delante and tab and d["hay"]["objeto"],
               "guia": en_partida and delante and tab and d["hay"].get("guia", False),
               "ayuda": demo and d["hay"]["ayuda"]}
        # con Tab se apilan muchas: las que no caben (en el lienzo o hasta el borde de la pantalla) no se pintan
        lim = self.H
        try:
            if self.mapeada:
                vx, vy, vw, vh = self._pantalla()
                lim = max(self.e(200), min(lim, vy + vh - self.win.winfo_y() - self.e(8)))
        except Exception:
            pass
        tab_prio = ("mision", "objeto", "guia", "reto")          # si no caben todas, se quedan por este orden
        alto_y = sum(d["alto"][n] + self.e(6) for n in ver if ver[n] and n not in tab_prio)
        for n in tab_prio:
            if ver.get(n):
                if alto_y + d["alto"][n] > lim:
                    ver[n] = False
                else:
                    alto_y += d["alto"][n] + self.e(6)
        if ver == self._vis:
            return
        entra_aviso = ver["aviso"] and self._aviso_n != self._aviso_visto and not demo
        if ver["aviso"]:
            self._aviso_visto = self._aviso_n
        if self._anim_dx:                                  # se recoloca todo: la entrada a medias se termina ya
            self.cv.move("aviso", -self._anim_dx, 0)
        self._anim_t, self._anim_dx = None, 0
        self._vis = ver
        cv, C, e, P, W, it = self.cv, self.C, self.e, self.P, self.W, self.it
        cfg, xy = self._cfg, self._xy
        y, hueco = 0, e(6)
        for n in ("mini", "obj", "eq", "aviso", "mision", "guia", "objeto", "reto", "ayuda"):
            if not ver[n]:
                if self._cache.get(("v", n)) is not False:
                    self._cache[("v", n)] = False
                    cv.itemconfigure(n, state="hidden")
                continue
            a = d["alto"][n]
            if n == "obj":
                xy(it["obj"], *self._rr(0, y, W - 1, y + a, e(9)))
                fichas, fotos = d.get("obj") or [], d.get("obj_fotos") or []
                k = len(fichas)
                ancho_f = (W - 2 * e(8)) / max(k, 1)
                lado = e(30)
                for i in range(3):
                    if i < k:
                        x0 = round(e(8) + i * ancho_f)
                        ix, iy = x0 + e(6), y + (a - lado) // 2
                        foto = fotos[i] if i < len(fotos) else None
                        if foto is not None:
                            xy(it[f"ob_i{i}"], ix, iy)
                            cfg(it[f"ob_i{i}"], image=foto)
                            xy(it[f"ob_o{i}"], -500, -500, -500, -500)
                            xy(it[f"ob_l{i}"], -500, -500)
                        else:                              # sin icono (aun bajando): circulo con la inicial
                            xy(it[f"ob_i{i}"], -500, -500)
                            xy(it[f"ob_o{i}"], ix, iy, ix + lado, iy + lado)
                            xy(it[f"ob_l{i}"], ix + lado // 2, iy + lado // 2)
                            cfg(it[f"ob_l{i}"], text=(fichas[i].get("corto") or "?")[:1])
                        tx = ix + lado + e(6)
                        xy(it[f"ob_t{i}"], tx, iy - e(3))
                        xy(it[f"ob_s{i}"], tx, iy + e(18))
                        xy(it[f"ob_b{i}"], x0 + e(6), y + a - e(5), round(x0 + ancho_f) - e(6), y + a - e(3))
                        if i:
                            xy(it[f"ob_d{i}"], x0, y + e(12), x0, y + a - e(12))
                    else:
                        for pre in ("ob_i", "ob_l", "ob_t", "ob_s"):
                            xy(it[f"{pre}{i}"], -500, -500)
                        xy(it[f"ob_o{i}"], -500, -500, -500, -500)
                        xy(it[f"ob_b{i}"], -500, -500, -500, -500)
                        if i:
                            xy(it[f"ob_d{i}"], -500, -500, -500, -500)
            elif n == "eq":
                q = d["eq"]
                pct = int(q.get("prob") or 50)
                xy(it["eq"], *self._rr(0, y, W - 1, y + a, e(9)))
                xy(it["e_et"], P, y + P - e(1))
                cfg(it["e_et"], text="PROBABILIDAD DE GANAR")
                xy(it["e_pct"], W - P, y + P - e(6))
                cfg(it["e_pct"], text=f"{pct} %", fill=C["azul"] if pct >= 55 else C["mal"] if pct <= 45 else C["tinta"])
                by, bh = y + P + e(19), e(6)
                corte = round(P + (W - 2 * P) * pct / 100)
                xy(it["e_b0"], P, by, W - P, by + bh)
                xy(it["e_b1"], P, by, corte, by + bh)
                xy(it["e_m"], corte, by - e(1), corte, by + bh + e(1))
                ty = by + bh + e(8)
                dif = int(q.get("dif") or 0)
                oro_txt = ("+" if dif > 0 else "−" if dif < 0 else "±") + _dec(abs(dif) / 1000) + "k"
                xy(it["e_oro"], P, ty)
                cfg(it["e_oro"], text="ORO " + oro_txt, fill=C["bien"] if dif >= 500 else C["mal"] if dif <= -500 else C["gris"])
                k1, k2 = (q.get("kills") or [0, 0])[:2]
                t1, t2 = (q.get("torres") or [0, 0])[:2]
                xy(it["e_k"], W // 2, ty)
                cfg(it["e_k"], text=f"KILLS {k1}–{k2}")
                xy(it["e_t"], W - P, ty)
                cfg(it["e_t"], text=f"TORRES {t1}–{t2}")
            elif n == "aviso":
                tono = d["aviso"][1] if d["aviso"] else "azul"
                col = {"rojo": C["mal"], "verde": C["bien"], "oro": C["oro"]}.get(tono, C["azul"])
                xy(it["aviso"], *self._rr(0, y, W - 1, y + a, e(9)))
                cfg(it["aviso"], outline=col)
                xy(it["a_barra"], e(1), y + e(9), e(4), y + a - e(9))
                cfg(it["a_barra"], fill=col)
                izq = P + e(4)
                if d.get("a_foto") is not None:
                    xy(it["a_img"], izq, y + P - e(1))
                    cfg(it["a_img"], image=d["a_foto"])
                    izq += d["a_izq"]
                else:
                    xy(it["a_img"], -500, -500)
                yy = y + P - e(3)
                xy(it["a_tit"], izq, yy)
                cfg(it["a_tit"], text="\n".join(d.get("tit_aviso") or []), fill=col)
                if d.get("tit_aviso"):
                    yy += self._lin("eti", 10.5) + e(2)
                xy(it["a_txt"], izq, yy)
                cfg(it["a_txt"], text="\n".join(d["txt_aviso"]))
                yb = y + a - P + e(1)
                self._pb = (P + e(4), W - P, yb)
                xy(it["a_pb0"], P + e(4), yb, W - P, yb + e(3))
                xy(it["a_pb1"], P + e(4), yb, W - P, yb + e(3))
                cfg(it["a_pb1"], fill=col)
            elif n == "mision":
                xy(it["mision"], *self._rr(0, y, W - 1, y + a, e(9)))
                yy = y + P - e(1)
                xy(it["mi_et"], P, yy)
                cfg(it["mi_et"], text="MISIÓN")
                yy += self._lin("eti", 9.5) + e(3)
                xy(it["mi_regla"], P, yy)
                cfg(it["mi_regla"], text="\n".join(d["regla"]))
                yy += len(d["regla"]) * self._lin("neg", 12.5) + e(2)
                xy(it["mi_est"], P, yy)
                cfg(it["mi_est"], text="\n".join(d["est"]))
            elif n == "reto":
                xy(it["reto"], *self._rr(0, y, W - 1, y + a, e(9)))
                yy = y + P - e(1)
                xy(it["r_et"], P, yy)
                cfg(it["r_et"], text="RETO ACTIVO")
                yy += self._lin("eti", 9.5) + e(3)
                xy(it["r_nom"], P, yy)
                cfg(it["r_nom"], text="\n".join(d["rnom"]))
                yy += len(d["rnom"]) * self._lin("neg", 12.5) + e(2)
                xy(it["r_meta"], P, yy)
                cfg(it["r_meta"], text="\n".join(d["rmeta"]))
            elif n == "objeto":
                base = bool(d["obase"])
                xy(it["objeto"], *self._rr(0, y, W - 1, y + a, e(9)))
                cfg(it["objeto"], outline=C["bien"] if base else C["borde"])
                fotos, lado = d.get("fotos") or [], d.get("lado") or e(30)
                for k in range(6):
                    if k < len(fotos):
                        im, st = fotos[k]
                        x0, y0, li = P + k * (lado + e(6)), y + P, im.width()
                        xy(it[f"o_i{k}"], x0, y0)
                        cfg(it[f"o_i{k}"], image=im)
                        xy(it[f"o_r{k}"], x0 - e(2), y0 - e(2), x0 + li + e(1), y0 + li + e(1))
                        cfg(it[f"o_r{k}"], outline={"ok": C["bien"], "sig": C["azul"]}.get(st, C["linea"]),
                            width=3 if st == "sig" else 2)
                    else:
                        xy(it[f"o_i{k}"], -500, -500)
                        xy(it[f"o_r{k}"], -500, -500, -500, -500)
                ty = y + P + d.get("tira_h", 0) - e(2)
                if fotos:
                    xy(it["o_img"], -500, -500)
                else:
                    xy(it["o_img"], P, y + P - e(1))
                xy(it["o_txt"], P + d["img_w"], ty)
                cfg(it["o_txt"], text="\n".join(d["otxt"]))
                yb = ty + len(d["otxt"]) * self._lin("neg", 12.5) + e(2)
                xy(it["o_base"], P + d["img_w"], yb)
                cfg(it["o_base"], text="\n".join(d["obase"]))
                if d.get("oro_pct") is not None:
                    yb += (len(d["obase"]) * self._lin("neg", 12) + e(2)) if d["obase"] else 0
                    yb += e(3)
                    x1 = W - P
                    xy(it["o_pb0"], P + d["img_w"], yb, x1, yb + e(5))
                    xy(it["o_pb1"], P + d["img_w"], yb, P + d["img_w"] + (x1 - P - d["img_w"]) * d["oro_pct"], yb + e(5))
                    cfg(it["o_pb1"], fill=C["bien"] if d["oro_pct"] >= 1 else C["azul"])
                else:
                    xy(it["o_pb0"], -500, -500, -500, -500)
                    xy(it["o_pb1"], -500, -500, -500, -500)
            elif n == "guia":
                xy(it["guia"], *self._rr(0, y, W - 1, y + a, e(9)))
                yy = y + P - e(1)
                xy(it["g_et"], P, yy)
                cfg(it["g_et"], text=f"CONTRA {(d['guia'].get('rival') or '').upper()}")
                yy += self._lin("eti", 9.5) + e(3)
                xy(it["g_dato"], P, yy)
                cfg(it["g_dato"], text="\n".join(d["g_dato"]),
                    fill={"bien": C["bien"], "mal": C["mal"]}.get(d["guia"].get("tono"), C["gris"]))
                if d["g_dato"]:
                    yy += len(d["g_dato"]) * self._lin("txt", 12) + e(4)
                xy(it["g_tips"], P, yy)
                cfg(it["g_tips"], text="\n".join(d["g_tips"]))
            elif n == "ayuda":
                xy(it["ayuda"], *self._rr(0, y, W - 1, y + a, e(9)))
                cfg(it["ayuda"], outline=C["azul"])
                xy(it["y_txt"], P, y + P - e(2))
                cfg(it["y_txt"], text="\n".join(d["ayuda"]))
            if self._cache.get(("v", n)) is not True:
                self._cache[("v", n)] = True
                cv.itemconfigure(n, state="normal")
            y += a + hueco
        if ver.get("obj"):
            self._tic_vivo(time.time())
        if entra_aviso:
            self._anim_d0 = self._anim_dx = -e(18)
            self.cv.move("aviso", self._anim_d0, 0)
            self._anim_t = time.time()
            self.root.after(15, self._animar_aviso)


class Ventana:
    """Ventanita siempre encima para la seleccion de campeon y la pantalla de carga (en partida la sustituyen
    las tarjetas de Hud). Solo se toca desde el hilo principal.
    Sin parpadeo: no redibuja si nada cambio, arma el contenido nuevo fuera de pantalla y lo cambia de golpe,
    y no usa transparencia (sobre el cliente de LoL las ventanas transparentes parpadean)."""
    ANCHO = 340
    TEMAS = {
        "claro": {"fondo": "#FFFFFF", "borde": "#C9D2E0", "tinta": "#0F1728", "gris": "#56627A", "linea": "#E3E8F0",
                  "azul": "#1F5FD6", "azul2": "#E8EFFD", "rojo": "#D03A4C", "rojo2": "#FDECEE",
                  "verde": "#0E8A5F", "verde2": "#E2F5EC", "barra": "#1F5FD6", "boton": "#1F5FD6",
                  "oro": "#8A5A00", "oro2": "#FFF3D6", "chip": "#E8EDF5"},
        "oscuro": {"fondo": "#0A0F18", "borde": "#25314A", "tinta": "#F2F5FA", "gris": "#93A0B8", "linea": "#1B2538",
                   "azul": "#5AA9FF", "azul2": "#12203A", "rojo": "#FF6B7D", "rojo2": "#33141C",
                   "verde": "#3DDC97", "verde2": "#0F2A20", "barra": "#5AA9FF", "boton": "#1F6FE5",
                   "oro": "#E6C36A", "oro2": "#2B2410", "chip": "#1A2438"},
    }
    C = TEMAS["oscuro"]

    def __init__(self):
        import tkinter as tk
        self.tk = tk
        _fuentes_privadas()
        self.root = tk.Tk()
        self.root.withdraw()
        self.L = Letras(self.root)
        self.q = queue.Queue()
        self.ordenes = queue.Queue()      # cosas que pide la app (probar o colocar las tarjetas de partida)
        self.win = tk.Toplevel(self.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=self.C["borde"])
        self.marco = None
        self.visible = False
        self.oculta_hasta_cambio = False
        self.ultimo_modo = None
        self.ultimo_estado = None
        self.firma = None
        self._aviso_job = None
        self._lbl_aviso = None
        self._lbl_estado = None
        self._lbl_extra = None
        self._lbl_obj = None
        self._imgs = []
        self._drag = None
        self.al_elegir = None         # lo pone el coach: se llama con la clave de la opcion elegida
        self._abiertos = set()        # apartados plegables abiertos en la seleccion
        self.hud = None
        pref = self._cargar_pref()
        self.pos = pref["pos"]
        self.compacta = pref["compacta"]
        self._scroll, self._sobra, self._geo = 0, 0, None     # desplazamiento si no cabe en la pantalla
        self._lbl_mas = tk.Label(self.win, text="▼  Más abajo: usa la rueda del ratón", anchor="center", pady=4)
        self.win.bind_all("<ButtonPress-1>", self._ini_drag)
        self.win.bind_all("<B1-Motion>", self._mover)
        self.win.bind_all("<ButtonRelease-1>", self._fin_drag)
        self.win.bind_all("<MouseWheel>", self._rueda)
        self.root.after(150, self._procesar)
        self.root.after(3000, self._vigilar)

    # -- preferencias (posicion y tamano)
    def _cargar_pref(self):
        try:
            p = json.loads((DATOS / "ventana.json").read_text(encoding="utf-8"))
            return {"pos": (int(p["x"]), int(p["y"])), "compacta": bool(p.get("compacta", True))}
        except Exception:
            return {"pos": (self.root.winfo_screenwidth() - self.ANCHO - 30, 110), "compacta": True}

    def _guardar_pref(self):
        try:
            (DATOS / "ventana.json").write_text(json.dumps(
                {"x": self.pos[0], "y": self.pos[1], "compacta": self.compacta}), encoding="utf-8")
        except Exception:
            pass

    def _ini_drag(self, e):
        # bind_all tambien recibe los clics de las tarjetas de partida: solo se arrastra si el clic es en esta ventana
        w = str(e.widget)
        if w != str(self.win) and not w.startswith(str(self.win) + "."):
            self._drag = None
            return
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y(), False)

    def _mover(self, e):
        if self._drag:
            self.pos = (e.x_root - self._drag[0], e.y_root - self._drag[1])
            self._drag = (self._drag[0], self._drag[1], True)
            self.win.geometry(f"+{self.pos[0]}+{self.pos[1]}")

    def _fin_drag(self, e):
        movio = self._drag and self._drag[2]
        self._drag = None
        if movio:
            self._guardar_pref()
            self._ajustar()

    # -- que quepa en la pantalla
    def _area(self, x, y):
        """Zona util del monitor en ese punto, sin la barra de tareas: (izq, arriba, der, abajo)."""
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                class MI(ctypes.Structure):
                    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
                u = ctypes.windll.user32
                u.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
                u.MonitorFromPoint.restype = ctypes.c_void_p
                u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                m = u.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)       # el monitor mas cercano
                mi = MI()
                mi.cbSize = ctypes.sizeof(MI)
                if m and u.GetMonitorInfoW(m, ctypes.byref(mi)):
                    r = mi.rcWork
                    return r.left, r.top, r.right, r.bottom
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight() - 48

    def _ajustar(self, ev=None):
        """Tamaño y sitio de la ventanita: si no cabe por abajo, sube; si ni asi cabe, se recorta y lo de
        abajo se ve con la rueda del raton. Tu sitio guardado no cambia."""
        if self.marco is None or (self._drag and self._drag[2]):
            return
        try:
            w = max(self.marco.winfo_reqwidth(), self.ANCHO - 2) + 2
            h = self.marco.winfo_reqheight() + 2
            l, t, r, b = self._area(self.pos[0] + w // 2, self.pos[1] + 20)
            vis = min(h, max(120, b - t - 8))
            x = max(l, min(self.pos[0], r - w))          # siempre dentro de la pantalla (si no, no se ve)
            y = max(t, min(self.pos[1], b - vis))
            self._sobra = max(0, h - vis)
            self._scroll = max(0, min(self._scroll, self._sobra))
            self.marco.place_configure(y=1 - self._scroll, width=w - 2)
            geo = f"{w}x{vis}+{x}+{y}"
            if geo != self._geo:
                self._geo = geo
                self.win.geometry(geo)
            if self._sobra - self._scroll > 4:
                self._lbl_mas.config(bg=self.C["azul2"], fg=self.C["azul"], font=self._f(8, "bold"))
                self._lbl_mas.place(x=1, rely=1.0, y=-1, anchor="sw", width=w - 2)
                self._lbl_mas.lift()
            elif self._lbl_mas.winfo_manager():
                self._lbl_mas.place_forget()
        except Exception:
            pass

    def _rueda(self, e):
        if self.visible and self._sobra > 0:
            self._scroll = max(0, min(self._sobra, self._scroll - int(e.delta / 120 * 48)))
            self._ajustar()

    # -- interfaz publica (cualquier hilo)
    def enviar(self, estado):
        self.q.put(estado)

    def orden(self, nombre, datos=None):
        self.ordenes.put((nombre, datos or {}))

    def _hacer_ordenes(self):
        while True:
            try:
                nombre, datos = self.ordenes.get_nowait()
            except queue.Empty:
                return
            if self.hud is None:
                self.hud = Hud(self)
            if nombre == "hud_cfg":
                self.hud.configurar(datos)
            elif nombre == "hud_probar":
                self.hud.probar(mover=bool(datos.get("mover")))

    def bucle(self):
        self.root.mainloop()

    # -- hilo principal
    def _procesar(self):
        try:
            self._hacer_ordenes()
            ultimo = None
            while True:
                try:
                    x = self.q.get_nowait()       # si llegaron varios, solo importa el ultimo
                except queue.Empty:
                    break
                if x.get("aviso") or x.get("modo") == "oculto":
                    self._pintar(x)
                    ultimo = None
                else:
                    ultimo = x
            if ultimo is not None:
                self._pintar(ultimo)
        except Exception as e:
            # un error al dibujar no puede dejar la ventanita congelada: se anota y se sigue
            self.firma = None
            log(f"Ventanita: {type(e).__name__}: {e}")
        self.root.after(150, self._procesar)

    def _f(self, tam, peso="normal", voz=None):
        """Letra de la ventanita: 'tam' en puntos como antes, con las voces de letra de la app."""
        px = {8: 11, 9: 12.5, 10: 13.5, 11: 15, 12: 16.5, 14: 20, 18: 27}.get(tam, round(tam * 1.38))
        return self.L.t(voz or ("neg" if peso == "bold" else "txt"), px)

    def _lbl(self, texto, tam=10, peso="normal", color=None, bg=None, pady=(0, 0), wrap=None, voz=None):
        caja = bool(bg) and bg != self.C["fondo"]            # los recuadros de color llevan margen interior
        lbl = self.tk.Label(self.marco, text=texto, font=self._f(tam, peso, voz), fg=color or self.C["tinta"],
                            bg=bg or self.C["fondo"], justify="left", anchor="w",
                            wraplength=(wrap or (self.ANCHO - 30)) - (18 if caja else 0),
                            padx=9 if caja else 0, pady=6 if caja else 0)
        lbl.pack(fill="x", pady=pady)
        return lbl

    def _seccion(self, texto, pady=(0, 0), color=None):
        """Titulo pequeño de un apartado."""
        return self._lbl(texto.upper(), 8, color=color or self.C["azul"], pady=pady, voz="eti")

    def _foto(self, ruta, tam):
        """Icono PNG reducido a ~tam px (Tk 8.6 lee PNG sin librerias extra)."""
        if not ruta:
            return None
        try:
            img = self.tk.PhotoImage(file=ruta)
            f = max(1, round(img.width() / tam))
            if f > 1:
                img = img.subsample(f)
            self._imgs.append(img)
            return img
        except Exception:
            return None

    def _fila_ico(self, rutas, texto, tam=34, tam_txt=10, peso="normal", color=None, bg=None, pady=(0, 0), voz=None):
        caja = bool(bg) and bg != self.C["fondo"]
        bg = bg or self.C["fondo"]
        fila = self.tk.Frame(self.marco, bg=bg, padx=9 if caja else 0, pady=6 if caja else 0)
        fila.pack(fill="x", pady=pady)
        n = 0
        for r in (rutas if isinstance(rutas, list) else [rutas]):
            img = self._foto(r, tam)
            if img:
                self.tk.Label(fila, image=img, bg=bg).pack(side="left", padx=(0, 6))
                n += 1
        self.tk.Label(fila, text=texto, font=self._f(tam_txt, peso, voz), fg=color or self.C["tinta"], bg=bg,
                      justify="left", anchor="w", wraplength=self.ANCHO - 30 - n * (tam + 6) - (18 if caja else 0)).pack(
            side="left", fill="x", expand=True)
        return fila

    def _boton(self, padre, texto, accion):
        b = self.tk.Label(padre, text=texto, font=self._f(9, "bold"), fg=self.C["gris"], bg=self.C["fondo"],
                          cursor="hand2", padx=4)
        b.bind("<ButtonRelease-1>", lambda e: accion())
        return b

    def _cabecera(self, texto, color=None):
        fila = self.tk.Frame(self.marco, bg=self.C["fondo"])
        fila.pack(fill="x")
        self.tk.Label(fila, text=texto.upper(), font=self._f(8, voz="eti"), fg=color or self.C["gris"],
                      bg=self.C["fondo"], anchor="w").pack(side="left")
        x = self.tk.Label(fila, text="✕", font=self._f(10), fg=self.C["gris"], bg=self.C["fondo"], cursor="hand2")
        x.pack(side="right")
        x.bind("<ButtonRelease-1>", lambda e: self._cerrar())
        self._boton(fila, "Más ▾" if self.compacta else "Menos ▴", self._alternar).pack(side="right", padx=(0, 8))
        self.tk.Frame(self.marco, bg=self.C["fondo"], width=self.ANCHO - 30, height=1).pack()

    def _pinta_opciones(self, s):
        """Las builds y runas entre las que puedes elegir (se ve tambien con la ventanita en modo compacto)."""
        C = self.C
        if s.get("opciones") or s.get("opciones_nota"):
            self.tk.Frame(self.marco, bg=C["linea"], height=1).pack(fill="x", pady=(9, 7))
            self._seccion("Runas y build: elige cuál usar")
            for o in s.get("opciones") or []:
                fondo = C["verde2"] if o["sel"] else C["fondo"]
                fila = self.tk.Frame(self.marco, bg=fondo, padx=8, pady=5)
                fila.pack(fill="x", pady=(4, 0))
                if o["sel"]:
                    self.tk.Label(fila, text="✓ En uso", font=self._f(9, "bold"), fg=C["verde"], bg=fondo).pack(side="right")
                else:
                    b = self.tk.Label(fila, text="Usar", font=self._f(9, "bold"), fg="#FFFFFF",
                                      bg=C["boton"], cursor="hand2", padx=13, pady=4)
                    b.pack(side="right")
                    b.bind("<ButtonRelease-1>", lambda e, k=o["clave"]: self.al_elegir and self.al_elegir(k))
                col = self.tk.Frame(fila, bg=fondo)
                col.pack(side="left", fill="x", expand=True)
                self.tk.Label(col, text=o["titulo"], font=self._f(9, "bold"), fg=C["tinta"], bg=fondo, justify="left",
                              anchor="w", wraplength=self.ANCHO - 126).pack(fill="x")
                if o["detalle"]:
                    self.tk.Label(col, text=o["detalle"], font=self._f(8), fg=C["gris"], bg=fondo, justify="left",
                                  anchor="w", wraplength=self.ANCHO - 126).pack(fill="x")
            if s.get("opciones_nota"):
                self._lbl(s["opciones_nota"], 9, color=C["gris"], pady=(3, 0))

    # -- seleccion de campeon: primero lo que haces ahi (build y runas), luego la mision y lo demas plegado
    def _clic(self, w, accion):
        """Clic en una fila entera (y en todo lo que tiene dentro)."""
        w.bind("<ButtonRelease-1>", lambda e: accion())
        try:
            w.configure(cursor="hand2")
        except Exception:
            pass
        for h in w.winfo_children():
            self._clic(h, accion)

    def _plegar(self, clave):
        self._abiertos ^= {clave}
        if self.ultimo_estado:
            self.firma = None
            self._pintar(self.ultimo_estado, forzar=True)

    def _pinta_seleccion(self, s, comp):
        C, tk = self.C, self.tk
        cab = s.get("cab") or {}
        fila = tk.Frame(self.marco, bg=C["fondo"])
        fila.pack(fill="x")
        img = self._foto(s.get("pick_icono"), 30)
        if img:
            tk.Label(fila, image=img, bg=C["fondo"]).pack(side="left", padx=(0, 9))
        x = tk.Label(fila, text="✕", font=self._f(10), fg=C["gris"], bg=C["fondo"], cursor="hand2")
        x.pack(side="right", anchor="n")
        x.bind("<ButtonRelease-1>", lambda e: self._cerrar())
        self._boton(fila, "Más" if comp else "Menos", self._alternar).pack(side="right", anchor="n", padx=(0, 8))
        col = tk.Frame(fila, bg=C["fondo"])
        col.pack(side="left", fill="x", expand=True)
        tk.Label(col, text=cab.get("campeon") or "Coach LoL", font=self._f(11, "bold"), fg=C["tinta"], bg=C["fondo"],
                 anchor="w").pack(fill="x")
        sub = " · ".join(t for t in (cab.get("rol"), f"contra {cab['rival']}" if cab.get("rival") else "") if t)
        if sub:
            tk.Label(col, text=sub, font=self._f(8), fg=C["gris"], bg=C["fondo"], anchor="w").pack(fill="x")
        tk.Frame(self.marco, bg=C["linea"], height=1).pack(fill="x", pady=(9, 0))
        # como vas hoy: una banda fina (roja si toca parar, dorada si vas al limite)
        b = s.get("banda")
        if b:
            fg, bg = (C["rojo"], C["rojo2"]) if b.get("tono") == "rojo" else (C["oro"], C["oro2"])
            tk.Label(self.marco, text="●  " + b["texto"], font=self._f(9, "bold"), fg=fg, bg=bg, anchor="w",
                     justify="left", wraplength=self.ANCHO - 46, padx=9, pady=5).pack(fill="x", pady=(8, 0))
        # build y runas
        if s.get("opciones"):
            self._seccion("Build y runas", pady=(11, 3))
            for o in s["opciones"]:
                self._opcion_sel(o, s)
            if s.get("opciones_nota"):
                self._lbl(s["opciones_nota"], 8, color=C["gris"], pady=(4, 0))
            if s.get("runas") and "No pude" in s["runas"]:
                self._lbl(s["runas"], 8, "bold", C["rojo"], pady=(4, 0))
        # la mision y como cumplirla, juntas
        tk.Frame(self.marco, bg=C["linea"], height=1).pack(fill="x", pady=(10, 8))
        self._seccion("Tu misión")
        self._lbl(s.get("regla", ""), 12, "bold", pady=(2, 2))
        for c in (s.get("como") or [])[:1]:
            self._lbl("Cómo: " + c, 9, color=C["gris"], pady=(0, 2))
        if comp:
            return
        tk.Frame(self.marco, height=6, bg=C["fondo"]).pack(fill="x")
        # lo demas, plegado: se abre con un clic y se recuerda
        cuesta = [t for t in (s.get("plan"), s.get("revision")) if t]
        if cuesta:
            self._plegable("cuesta", "Lo que más te cuesta", s.get("plan_corto") or "", cuesta)
        retos = [t.lstrip("• ").strip() for t in (s.get("retos_txt") or "").split("\n")[1:] if t.strip()]
        if retos:
            self._plegable("retos", "Retos", f"{len(retos)} activo{'s' if len(retos) != 1 else ''}", retos)
        pick = [t for t in [s.get("pick")] + list(s.get("matchup") or []) + [s.get("nota_rol"), s.get("pick_web")] if t]
        if pick:
            ok = s.get("pick_ok", True)
            self._plegable("pick", "Tu pick y sus campeones", s.get("pick_corto") or "", pick,
                           color=None if ok else C["rojo"])
        if s.get("dano_txt"):
            self._plegable("dano", "Su daño", s.get("dano_corto") or "", [s["dano_txt"]], iconos=s.get("dano_iconos"))
        tk.Frame(self.marco, bg=C["linea"], height=1).pack(fill="x")

    def _opcion_sel(self, o, s):
        """Una build elegible: toda la fila se pulsa. La que esta en uso enseña sus objetos, runas y hechizos."""
        C, tk = self.C, self.tk
        sel = o.get("sel")
        bg = C["azul2"] if sel else C["fondo"]
        fila = tk.Frame(self.marco, bg=bg, padx=8, pady=6)
        fila.pack(fill="x", pady=(2, 0))
        cv = tk.Canvas(fila, width=14, height=14, bg=bg, highlightthickness=0, bd=0)
        cv.create_oval(1, 1, 13, 13, outline=C["azul"] if sel else C["gris"], width=2)
        if sel:
            cv.create_oval(4, 4, 10, 10, fill=C["azul"], outline="")
        cv.pack(side="left", anchor="n", pady=(2, 0), padx=(0, 8))
        if o.get("wr") is not None:
            tk.Label(fila, text=f"{_dec(o['wr'])}%", font=self._f(11, "bold", voz="num"),
                     fg=C["verde"] if sel else C["gris"], bg=bg).pack(side="right", anchor="n")
        col = tk.Frame(fila, bg=bg)
        col.pack(side="left", fill="x", expand=True)
        tk.Label(col, text=o["titulo"], font=self._f(9, "bold"), fg=C["tinta"], bg=bg, justify="left", anchor="w",
                 wraplength=self.ANCHO - 120).pack(fill="x")
        if o.get("sub"):
            tk.Label(col, text=o["sub"], font=self._f(8), fg=C["gris"], bg=bg, justify="left", anchor="w",
                     wraplength=self.ANCHO - 120).pack(fill="x")
        if sel:
            ics = [x for x in (s.get("build_iconos") or [])]
            if ics:
                f1 = tk.Frame(col, bg=bg)
                f1.pack(fill="x", pady=(6, 0))
                for r in ics[:6]:
                    img = self._foto(r, 24)
                    if img:
                        tk.Label(f1, image=img, bg=bg, bd=0).pack(side="left", padx=(0, 3))
            chips = [t for t in (s.get("hechizos_txt"),) if t]
            if s.get("runas_iconos") or chips:
                f2 = tk.Frame(col, bg=bg)
                f2.pack(fill="x", pady=(4, 0))
                for r in s.get("runas_iconos") or []:
                    img = self._foto(r, 22)
                    if img:
                        tk.Label(f2, image=img, bg=bg, bd=0).pack(side="left", padx=(0, 3))
                for t in chips:
                    tk.Label(f2, text=t, font=self._f(8, "bold"), fg=C["tinta"], bg=C["chip"], padx=5, pady=1).pack(
                        side="left", padx=(3, 0))
            if s.get("hab_corta"):
                tk.Label(col, text="Habilidades: " + s["hab_corta"], font=self._f(8), fg=C["gris"], bg=bg,
                         anchor="w").pack(fill="x", pady=(4, 0))
        else:
            self._clic(fila, lambda k=o["clave"]: self.al_elegir and self.al_elegir(k))

    def _fila_jugador(self, x):
        """Un jugador en la pantalla de carga: icono, campeon, linea, rango y sus chips (rojo = cuidado)."""
        C, tk = self.C, self.tk
        fila = tk.Frame(self.marco, bg=C["fondo"])
        fila.pack(fill="x", pady=(5, 0))
        img = self._foto(x.get("ico"), 26)
        if img:
            tk.Label(fila, image=img, bg=C["fondo"]).pack(side="left", anchor="n", padx=(0, 8))
        col = tk.Frame(fila, bg=C["fondo"])
        col.pack(side="left", fill="x", expand=True)
        l1 = tk.Frame(col, bg=C["fondo"])
        l1.pack(fill="x")
        tk.Label(l1, text=x["nombre"], font=self._f(9, "bold"), fg=C["tinta"], bg=C["fondo"]).pack(side="left")
        if x.get("pos"):
            tk.Label(l1, text=x["pos"], font=self._f(8), fg=C["gris"], bg=C["fondo"]).pack(side="left", padx=(5, 0))
        rango = x.get("rango") or ("…" if x.get("cargando") else "sin rango")
        tk.Label(l1, text=rango, font=self._f(8, "bold"), fg=C["oro"] if x.get("rango") else C["gris"],
                 bg=C["fondo"]).pack(side="right")
        chips = x.get("chips") or []
        for k in range(0, min(len(chips), 4), 2):
            l2 = tk.Frame(col, bg=C["fondo"])
            l2.pack(fill="x", pady=(2, 0))
            for t, tono in chips[k:k + 2]:
                tk.Label(l2, text=t, font=self._f(8, "bold"), fg={"mal": C["rojo"], "bien": C["verde"]}.get(tono, C["gris"]),
                         bg=C["chip"], padx=5, pady=0).pack(side="left", padx=(0, 4))

    def _plegable(self, clave, titulo, resumen, lineas, color=None, iconos=None):
        C, tk = self.C, self.tk
        abierto = clave in self._abiertos
        tk.Frame(self.marco, bg=C["linea"], height=1).pack(fill="x")
        f = tk.Frame(self.marco, bg=C["fondo"], pady=7)
        f.pack(fill="x")
        tk.Label(f, text="▾" if abierto else "▸", font=self._f(9, "bold"), fg=C["gris"], bg=C["fondo"], width=2,
                 anchor="w").pack(side="left")
        tk.Label(f, text=titulo, font=self._f(9, "bold"), fg=C["tinta"], bg=C["fondo"]).pack(side="left")
        if resumen:
            tk.Label(f, text=resumen, font=self._f(8), fg=color or C["gris"], bg=C["fondo"]).pack(side="right")
        self._clic(f, lambda: self._plegar(clave))
        if abierto:
            for t in lineas:
                self._lbl(t, 9, color=C["gris"], pady=(0, 5))
            if iconos:
                self._fila_ico(iconos, "", 24, 9, pady=(0, 6))

    def _alternar(self):
        self.compacta = not self.compacta
        self._guardar_pref()
        if self.ultimo_estado:
            self.firma = None
            self._pintar(self.ultimo_estado, forzar=True)

    def _cerrar(self):
        self.oculta_hasta_cambio = True
        self.visible = False
        self.win.withdraw()

    def _mostrar(self):
        """Solo hace algo cuando estaba oculta. En pantalla completa nunca se muestra durante la partida (eso
        mandaba el juego al escritorio); en 'Sin bordes' _vigilar la mantiene encima sin activarla."""
        if self.visible:
            return
        self._geo = None
        self._ajustar()
        self.win.deiconify()
        self.visible = True
        try:
            self.win.update_idletasks()
        except Exception:
            pass
        self._sin_foco()
        self._encima()

    def _hwnd(self):
        """Ventana real de Windows (la de Tk va dentro de un marco). None fuera de Windows."""
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.GetParent.argtypes = [wintypes.HWND]
            u.GetParent.restype = wintypes.HWND
            return u.GetParent(wintypes.HWND(self.win.winfo_id())) or None
        except Exception:
            return None

    def _sin_foco(self):
        """Windows: la ventanita nunca se activa, ni siquiera al tocarla o arrastrarla. Así el juego no pierde
        el foco (si lo pierde en pantalla completa, se minimiza)."""
        hwnd = self._hwnd()
        if not hwnd:
            return
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            u.GetWindowLongW.restype = ctypes.c_long
            u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            u.SetWindowLongW.restype = ctypes.c_long
            gwl_exstyle, ws_ex_noactivate, ws_ex_toolwindow = -20, 0x08000000, 0x00000080
            ex = u.GetWindowLongW(hwnd, gwl_exstyle)
            if ex & (ws_ex_noactivate | ws_ex_toolwindow) != (ws_ex_noactivate | ws_ex_toolwindow):
                u.SetWindowLongW(hwnd, gwl_exstyle, ex | ws_ex_noactivate | ws_ex_toolwindow)
        except Exception:
            pass

    def _vigilar(self):
        """Solo con el juego en 'Sin bordes' o 'Ventana' (el coach lo marca con 'encima'): si el juego la tapó,
        la vuelve a poner encima sin activarla. Nunca con un juego en pantalla completa."""
        try:
            s = self.ultimo_estado or {}
            if (self.visible and s.get("encima") and self.ultimo_modo in ("partida", "carga")
                    and not d3d_pantalla_completa()):
                self._encima()
        except Exception:
            pass
        self.root.after(3000, self._vigilar)

    def _encima(self):
        """La pone encima sin activarla (no le quita el foco al juego)."""
        hwnd = self._hwnd()
        if hwnd:
            try:
                import ctypes
                from ctypes import wintypes
                u = ctypes.windll.user32
                u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
                # HWND_TOPMOST; SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
                u.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0200)
                return
            except Exception:
                pass
        try:
            self.win.lift()
        except Exception:
            pass

    def _pintar(self, s, forzar=False):
        modo = s.get("modo")
        if modo == "partida" and s.get("hud") and CONFIG.get("hud_partida", True):
            # en partida: tarjetas pequeñas al mantener Tab en vez de la ventana grande
            if self.hud is None:
                self.hud = Hud(self)
            self.hud.poner(s)
            if self.visible:
                self.win.withdraw()
                self.visible = False
            self.ultimo_modo, self.ultimo_estado, self.firma, self._lbl_estado = modo, s, None, None
            return
        if self.hud is not None:
            self.hud.quitar()
        if modo != self.ultimo_modo:
            self.oculta_hasta_cambio = False
        if modo == "oculto" or not modo:
            self.ultimo_modo = modo
            self.firma = None
            if self.visible:
                self.win.withdraw()       # si ya estaba oculta no se toca (nada de llamadas en plena partida)
            self.visible = False
            return
        if self.oculta_hasta_cambio and not forzar:
            return
        if s.get("tema") in self.TEMAS and self.C is not self.TEMAS[s["tema"]]:
            self.C = self.TEMAS[s["tema"]]
            self.win.configure(bg=self.C["borde"])
            self.firma = None
            forzar = forzar or modo == "partida"
        if (modo == "partida" and self.ultimo_modo == "partida" and self._lbl_estado is not None and not forzar
                and s.get("objeto_id") == (self.ultimo_estado or {}).get("objeto_id")
                and s.get("objeto_clave") == (self.ultimo_estado or {}).get("objeto_clave")):
            if self._lbl_obj is not None and self._lbl_obj.cget("text") != s.get("objeto", ""):
                self._lbl_obj.config(text=s.get("objeto", ""))
            # en partida solo cambian textos: se actualizan en su sitio, sin redibujar
            if self._lbl_estado.cget("text") != s.get("estado", ""):
                self._lbl_estado.config(text=s.get("estado", ""))
            if self._lbl_extra is not None and self._lbl_extra.cget("text") != s.get("extra", ""):
                self._lbl_extra.config(text=s.get("extra", ""))
            if s.get("aviso"):
                self._mostrar_aviso(s["aviso"], s.get("tono", "azul"))
            self.ultimo_estado = s
            return
        firma = json.dumps({k: v for k, v in s.items() if k != "aviso"}, sort_keys=True, ensure_ascii=False)
        if firma == self.firma and not forzar:
            return            # nada cambio: no se toca la ventana
        self.firma = firma
        if modo != self.ultimo_modo:
            self._scroll = 0
        self.ultimo_modo = modo
        self.ultimo_estado = s

        # contenido nuevo armado en un marco aparte y cambiado de golpe
        viejo = self.marco
        self._imgs_viejas, self._imgs = self._imgs, []
        self.marco = self.tk.Frame(self.win, bg=self.C["fondo"], padx=14, pady=10)
        if modo != "seleccion":
            self.tk.Frame(self.marco, bg=self.C["barra"], height=3).pack(fill="x", pady=(0, 9))
        self._lbl_aviso = self._lbl_estado = self._lbl_extra = self._lbl_obj = None
        C, comp = self.C, self.compacta
        if modo == "seleccion":
            self._pinta_seleccion(s, comp)
        elif modo == "carga":
            self._cabecera("Plan de partida", C["azul"])
            if s.get("rival"):
                self._fila_ico(s.get("rival_icono"), f"Contra {s['rival']}", 26 if comp else 40,
                               12 if comp else 18, "bold", pady=(3, 3), voz="num")
            if s.get("nota_matchup"):
                self._lbl(s["nota_matchup"], 9, "bold", C["tinta"], bg=C["azul2"], pady=(2, 4))
            if s.get("jungla"):              # su jungla: se ve tambien en compacta
                jg = s["jungla"]
                self._fila_ico(jg.get("ico"), jg["txt"], 24, 9, "bold", C["tinta"],
                               bg=C["rojo2"] if jg.get("alerta") else C["azul2"], pady=(2, 4))
            elif s.get("jungla_pend") and not comp:
                self._lbl("Mirando por dónde suele empezar su jungla…", 8, color=C["gris"], pady=(0, 3))
            if not comp:
                for linea in s.get("rival_info", []):
                    self._lbl(linea, 9, color=C["gris"])
                if s.get("historial"):
                    malo = s.get("historial_malo")
                    self._lbl(s["historial"], 9, "bold", C["rojo"] if malo else C["tinta"],
                              bg=C["rojo2"] if malo else C["azul2"], pady=(6, 0))
                for c in s.get("consejos", [])[:2]:
                    self._lbl("•  " + c, 9, pady=(5, 0))
                self.tk.Frame(self.marco, bg=C["linea"], height=1).pack(fill="x", pady=(10, 7))
                self._seccion("Tu misión")
            self._lbl(s.get("regla", ""), 11, "bold")
            if not comp:
                # primero como cumplir la mision; lo que mas te cuesta (otro tema) va aparte
                for x in s.get("checklist", []):
                    self._lbl("✓  " + x, 9, color=C["gris"], pady=(3, 0))
                if s.get("plan"):
                    self.tk.Frame(self.marco, bg=C["linea"], height=1).pack(fill="x", pady=(10, 7))
                    self._seccion("Además, lo que más te cuesta" + (f" · {s['plan_fase']}" if s.get("plan_fase") else ""))
                    self._lbl(s["plan"], 9)
                eq = s.get("equipos") or {}
                if eq.get("rivales"):
                    self.tk.Frame(self.marco, bg=C["linea"], height=1).pack(fill="x", pady=(10, 7))
                    self._seccion("Rivales")
                    for x in eq["rivales"]:
                        self._fila_jugador(x)
                if eq.get("aliados"):
                    self.tk.Frame(self.marco, bg=C["fondo"], height=8).pack(fill="x")
                    lin, malos = [], 0
                    for x in eq["aliados"]:
                        malos += sum(1 for _, tono in x.get("chips") or [] if tono == "mal")
                        extra = " · ".join([x.get("rango") or ""] + [t for t, _ in x.get("chips") or []]).strip(" ·")
                        lin.append(f"{x['nombre']}{' (' + x['pos'] + ')' if x.get('pos') else ''}"
                                   f"{': ' + extra if extra else (' …' if x.get('cargando') else '')}")
                    self._plegable("aliados", "Tu equipo", f"{malos} a vigilar" if malos else "", lin,
                                   C["rojo"] if malos else None)
                if s.get("dano_txt"):
                    self._fila_ico(s.get("dano_iconos") or [], s["dano_txt"], 26, 9, "bold", C["tinta"],
                                   bg=C["azul2"], pady=(8, 0))
        elif modo == "partida":
            self._cabecera(s.get("titulo", "Misión"), C["azul"])
            self._lbl(s.get("regla", ""), 10 if comp else 11, "bold", pady=(2, 2))
            self._lbl_estado = self._lbl(s.get("estado", ""), 9 if comp else 10, color=C["gris"])
            if not comp:
                self._lbl_extra = self._lbl(s.get("extra", ""), 9, color=C["gris"])
            if s.get("objeto"):
                self.tk.Frame(self.marco, bg=C["linea"], height=1).pack(fill="x", pady=(6, 6))
                if s.get("tira") and not comp:
                    # tu build entera: verde = ya lo tienes, azul = el siguiente, gris = despues
                    tira = self.tk.Frame(self.marco, bg=C["fondo"])
                    tira.pack(fill="x", pady=(0, 5))
                    for x in s["tira"]:
                        img = self._foto(x.get("ico"), 30)
                        if not img:
                            continue
                        col = {"ok": C["verde"], "sig": C["azul"]}.get(x["estado"], C["borde"])
                        celda = self.tk.Frame(tira, bg=C["fondo"])
                        celda.pack(side="left", padx=(0, 5))
                        self.tk.Label(celda, image=img, bg=C["fondo"], highlightthickness=3 if x["estado"] == "sig" else 2,
                                      highlightbackground=col).pack()
                        self.tk.Label(celda, text={"ok": "✓", "sig": "▲"}.get(x["estado"], " "),
                                      font=self._f(8, "bold"), fg=col, bg=C["fondo"]).pack()
                    self._lbl_obj = self._lbl(s["objeto"], 10, "bold")
                    if s.get("hab"):
                        self._lbl(s["hab"], 9, color=C["gris"], pady=(3, 0))
                else:
                    fila = self._fila_ico(s.get("objeto_ico"), s["objeto"], 30, 10, "bold")
                    self._lbl_obj = fila.winfo_children()[-1]
            self._lbl_aviso = self.tk.Label(self.marco, text="", font=self._f(10, "bold"),
                                            bg=C["fondo"], fg=C["tinta"], justify="left", anchor="w",
                                            wraplength=self.ANCHO - 46, padx=8, pady=6)
        self.marco.place(x=1, y=1 - self._scroll, width=self.ANCHO - 2)
        self.marco.bind("<Configure>", self._ajustar)        # si crece (un aviso, otro texto) se reajusta sola
        if viejo is not None:
            viejo.destroy()
        try:
            self.marco.update_idletasks()
        except Exception:
            pass
        self._ajustar()
        self._imgs_viejas = []
        if modo == "partida" and s.get("aviso"):
            self._mostrar_aviso(s["aviso"], s.get("tono", "azul"))
        self._mostrar()

    def _mostrar_aviso(self, texto, tono):
        if self._lbl_aviso is None:
            return
        C = self.C
        fg, bg = {"rojo": (C["rojo"], C["rojo2"]), "verde": (C["verde"], C["verde2"]),
                  "oro": (C["oro"], C["oro2"])}.get(tono, (C["azul"], C["azul2"]))
        self._lbl_aviso.config(text=texto, fg=fg, bg=bg)
        if not self._lbl_aviso.winfo_ismapped():
            self._lbl_aviso.pack(fill="x", pady=(8, 0))
        if self._aviso_job:
            self.root.after_cancel(self._aviso_job)
        self._aviso_job = self.root.after(12000, self._ocultar_aviso)

    def _ocultar_aviso(self):
        self._aviso_job = None
        if self._lbl_aviso is not None:
            try:
                self._lbl_aviso.pack_forget()
            except Exception:
                pass


# =============================================================== COACH (bucle)
class Coach:
    def __init__(self, alm, rec, ventana=None):
        self.lcu = LCU()
        self.alm = alm
        self.rec = rec
        self.ventana = ventana
        self.conectado = False
        self.fase = None
        self.puuid = None
        self.sync_inicial = False
        self.ultima_nueva = None
        self.ultimo_poll_pagina = 0.0
        self.ir_a = None              # (destino, hora): adonde debe ir el panel ya abierto en su siguiente consulta
        self.url = ""
        self._t_sync = 0.0
        self._t_rango = 0.0
        self._sincronizando = False
        self.mision_partida = None
        self.envivo = None
        self._sel_clave = None
        self.carga = None
        self.draft = None             # panel de la seleccion para el dashboard
        self._cola_sel = None         # cola de la seleccion actual ({id, modo, mapa, nombre})
        self._t_aviso = 0.0           # ultimo aviso puesto en las tarjetas (para no pisarlo)
        self._sel_estado = None
        self.plan_jungla, self._aviso_jungla = None, False
        self._obj_avisados, self.cola_partida = set(), None
        self._ev_muestra, self._ev_raros, self._obj_cfg = False, set(), (0.0, None)
        self.rol_partida = ""
        self._hud_reto, self._hud_base, self._hud_guia = None, None, None
        self.repeticion = None
        self.summoner_id = None
        self._runas_clave = None
        self._runas_txt = None
        self._runas_pag = None
        self.rival_partida = None     # campeon de tu rival de linea (pantalla de carga)
        self.build_partida = None     # build de esta partida: la que fijaste o la mas jugada en u.gg
        self._builds = {}             # (campeon, rol) -> build de la web
        self._build_pedidos = set()
        self._build_fallo = {}        # (campeon, rol) -> cuando fallo la ultima vez (para no insistir sin parar)
        self._matchups = {}           # (campeon, rol) -> {rival: (% de victorias, partidas)}
        self._matchups_pidiendo = False
        self._lola = {}               # ("otp"|"gen"|"vs", campeon, rol[, rival]) -> datos de Lolalytics (False = fallo)
        self._lola_ped = {}           # misma clave -> cuando se pidio
        self._opcion_clic = None      # clave elegida a mano en esta seleccion
        self._opcion_clic_champ = None
        self._opcion_puesta = None
        self.build_info = None        # la build en uso con el porque de cada objeto (para el panel)
        self._build_puesta = None
        self._hechizos_puestos = None    # (campeon, hechizos) ya puestos en esta seleccion
        self._build_campeon_vivo = False
        self.pantalla = None          # modo de pantalla del juego: 0 completa, 1 ventana, 2 sin bordes
        self.pantalla_fuente = ""
        self.oculta_partida = False   # en pantalla completa la ventanita no se muestra durante la partida
        self.oculta_motivo = ""       # "ajustes" (se revisa si cambias el modo) o "windows" (fija toda la partida)
        self._t_modo = 0.0
        self._recursos_ok = False
        self._fallos_cliente = 0
        self._ultimo_error = ("", 0.0)

    def _ventana(self, estado):
        if not (self.ventana and CONFIG["ventana_mision"]):
            return
        if self.oculta_partida and self.fase in EN_JUEGO:
            estado = {"modo": "oculto"}     # nada encima de un juego en pantalla completa
        elif estado.get("modo") in ("carga", "partida"):
            # en sin bordes o ventana el juego puede taparla: la ventanita se vuelve a poner encima (sin activarse)
            estado = dict(estado, encima=self.pantalla in (1, 2))
        self._ultimo_estado_v = estado
        self.ventana.enviar(dict(estado, tema=self.alm.d.get("tema") or "oscuro"))

    def tema_cambiado(self):
        """Vuelve a pintar la ventanita con el tema nuevo."""
        e = getattr(self, "_ultimo_estado_v", None)
        if self.ventana and e:
            self.ventana.enviar(dict(e, tema=self.alm.d.get("tema") or "oscuro"))

    # -- conexion
    def _conectar(self):
        if not self.lcu.conectar():
            return
        try:
            yo = self.lcu.get("/lol-summoner/v1/current-summoner")
        except Exception:
            return
        self.puuid = yo.get("puuid")
        self.summoner_id = yo.get("summonerId")
        if not self.puuid:
            return
        nombre = yo.get("gameName") or yo.get("displayName") or "Invocador"
        tag = yo.get("tagLine") or ""
        with self.alm.lock:
            self.alm.d["jugador"] = {"nombre": nombre, "tag": tag, "puuid": self.puuid,
                                     "icono": yo.get("profileIconId"), "nivel": yo.get("summonerLevel")}
        self.conectado = True
        self._fallos_cliente = 0
        log(f"Conectado al cliente como {nombre}#{tag}")
        if not self._recursos_ok:            # nombres e iconos: una vez por sesion
            self.rec.actualizar(self.lcu)
            self._recursos_ok = bool(getattr(self.rec, "campeones", None))
        try:
            fase = self.lcu.get("/lol-gameflow/v1/gameflow-phase", timeout=5)
        except Exception:
            fase = None
        if fase not in EN_JUEGO + ("ChampSelect",):
            # el historial se importa fuera de partida: nunca mientras juegas
            self._actualizar_rango()
            self._sincronizar()

    def _actualizar_rango(self):
        self._t_rango = time.time()
        try:
            r = self.lcu.get("/lol-ranked/v1/current-ranked-stats")
        except Exception:
            return
        q = (r.get("queueMap") or {}).get("RANKED_SOLO_5x5")
        if not q:
            q = next((x for x in r.get("queues") or [] if x.get("queueType") == "RANKED_SOLO_5x5"), None)
        if not q:
            return
        tier = (q.get("tier") or "").upper()
        div = q.get("division") or ""
        texto = "Sin clasificar" if tier in ("", "NONE") else \
            TIERS.get(tier, tier.title()) + ("" if div in ("", "NA") else f" {div}")
        rango = {"tier": tier, "division": div, "lp": q.get("leaguePoints", 0),
                 "victorias": q.get("wins", 0), "derrotas": q.get("losses", 0), "texto": texto}
        with self.alm.lock:
            previo = self.alm.d.get("rango") or {}
            self.alm.d["rango"] = rango
            if any(rango[k] != previo.get(k) for k in ("tier", "division", "lp", "victorias", "derrotas")):
                self.alm.d["rango_hist"].append({"ts": int(time.time() * 1000), **rango})
                self.alm.guardar()

    # -- historial
    def _sincronizar(self):
        if self._sincronizando:
            return
        self._sincronizando = True
        self._t_sync = time.time()
        try:
            # Todo el historial que el cliente quiera dar (por paginas de 20, hasta 100 partidas)
            juegos, vistos = [], set()
            for ini in range(0, 100, 20):
                try:
                    lista = self.lcu.get("/lol-match-history/v1/products/lol/current-summoner/matches"
                                         f"?begIndex={ini}&endIndex={ini + 19}")
                except Exception:
                    break
                pagina = ((lista or {}).get("games") or {}).get("games") or []
                nuevos = [g for g in pagina if g.get("gameId") not in vistos]
                if not nuevos:
                    break
                vistos.update(g.get("gameId") for g in nuevos)
                juegos += nuevos
                conocidos = all(str(g.get("gameId")) in self.alm.d["partidas"] or
                                (CRUDO / f"{g.get('gameId')}.json").exists() for g in nuevos)
                if self.sync_inicial and conocidos:
                    break
            pendientes = []
            for g in juegos:
                gid = str(g.get("gameId"))
                if gid in self.alm.d["partidas"] or (CRUDO / f"{gid}.json").exists():
                    continue
                if g.get("queueId") not in CONFIG["colas_analizadas"]:
                    continue
                if _dur_seg(g.get("gameDuration")) < 300:
                    continue
                pendientes.append(g)
            pendientes.sort(key=lambda g: g.get("gameCreation") or 0)
            if pendientes and not self.sync_inicial:
                log(f"Importando {len(pendientes)} partidas de tu historial...")
            nueva = None
            for g in pendientes:
                gid = str(g.get("gameId"))
                try:
                    juego = self.lcu.get(f"/lol-match-history/v1/games/{gid}")
                except Exception as e:
                    log(f"No pude leer la partida {gid}: {e}")
                    continue
                try:
                    tl = self.lcu.get(f"/lol-match-history/v1/game-timelines/{gid}", timeout=20)
                except Exception:
                    tl = None
                (CRUDO / f"{gid}.json").write_text(json.dumps(
                    {"juego": juego, "timeline": tl, "puuid": self.puuid, "guardado": int(time.time() * 1000)},
                    ensure_ascii=False), encoding="utf-8")
                an = analizar(juego, tl, self.puuid, self.rec, self.alm.rango_txt())
                if not an:
                    continue
                with self.alm.lock:
                    if self.sync_inicial:
                        # la mision que tenias durante esta partida
                        m = self.mision_partida or (plan_actual(self.alm).get("foco") or {})
                        if m.get("clave"):
                            self.alm.d["misiones"][gid] = {"clave": m["clave"], "nivel": m.get("nivel", 0)}
                    self.alm.d["partidas"][gid] = an
                    self.alm.guardar()
                if self.sync_inicial:
                    nueva = gid
                    if self.fase not in EN_JUEGO + ("ChampSelect",):
                        self.mision_partida = None
                    log(f"Partida nueva analizada: {an['yo']['campeon']} "
                        f"{'Victoria' if an['victoria'] else 'Derrota'} - {an['veredicto']['titulo']}")
            if nueva:
                self.ultima_nueva = nueva
                def tras_partida(g=nueva):                 # aparte, para no frenar al coach
                    try:
                        if ia_config()["clave"] or ia_config()["respaldo"]["clave"]:
                            ia_analizar(self.alm, self.rec, g)
                        with self.alm.lock:
                            pp = self.alm.d["partidas"].get(str(g))
                        if pp:
                            asignar_reto(self.alm, self.rec, pp)
                    except Exception as e:
                        log(f"No pude cerrar la partida ({type(e).__name__}: {e}).")
                threading.Thread(target=tras_partida, daemon=True).start()
                self._actualizar_rango()
                # el navegador solo se abre fuera de partida y de la cola: abrirlo encima del juego lo minimiza
                # si la pagina sigue abierta y respondiendo, ella sola enseña la partida nueva; si no responde
                # (ventana minimizada que el navegador dejo dormida) se trae delante esa en vez de abrir otra
                if (time.time() - self.ultimo_poll_pagina > 90 and self.fase not in
                        EN_JUEGO + ("ChampSelect", "Matchmaking", "ReadyCheck")):
                    mostrar_panel(self.url, self, f"partida={nueva}")
            self.sync_inicial = True
        finally:
            self._sincronizando = False

    def _ico(self, tipo, ident):
        if not ident:
            return None
        try:
            return str(CACHE / f"{tipo}_{int(ident)}.png") if self.rec.icono(tipo, ident, self.lcu) else None
        except Exception:
            return None

    # -- seleccion de campeon
    def _rol_habitual(self, champ):
        with self.alm.lock:
            roles = [p.get("rol") for p in self.alm.d["partidas"].values()
                     if p["yo"]["campeon_id"] == champ and p.get("rol")]
        return Counter(roles).most_common(1)[0][0] if roles else ""

    def _leer_cola(self):
        """La cola de la partida (gameflow): id, modo de juego, mapa y nombre."""
        gd = (self.lcu.get("/lol-gameflow/v1/session", timeout=5) or {}).get("gameData") or {}
        q = gd.get("queue") or {}
        return {"id": q.get("id"), "modo": q.get("gameMode"), "mapa": q.get("mapId"),
                "nombre": q.get("description") or q.get("shortName") or q.get("gameMode") or "otro modo"}

    def _seleccion(self):
        rol, champ, elegido, enemigos, ses = "", None, None, [], None
        if self._cola_sel is None:
            try:
                c = self._leer_cola()
                if c.get("modo") or c.get("mapa"):
                    self._cola_sel = c          # si aun no trae la cola, se vuelve a leer en la siguiente vuelta
            except Exception:
                pass
        if self._cola_sel is not None and not es_grieta(self._cola_sel):
            # ARAM, ARAM: Caos, Arena...: sin lineas ni objetivos. Nada de mision, runas, build ni draft de la Grieta
            clave = ("otro_modo", self._cola_sel.get("nombre"))
            if self._sel_clave != clave:
                self._sel_clave = clave
                self.rol_partida, self.mision_partida, self.build_partida, self.draft = "", None, None, None
                self._sel_estado = None
                log(f"Selección en {self._cola_sel.get('nombre')}: el coach no pone misión, runas ni build "
                    "(son para la Grieta) y esta partida no cuenta.")
                self._ventana({"modo": "oculto"})
            return
        try:
            ses = self.lcu.get("/lol-champ-select/v1/session", timeout=5)
            if self.pantalla == 0 and ((ses.get("timer") or {}).get("phase") or "").upper() == "GAME_STARTING":
                # en pantalla completa la ventanita se quita antes de que se abra el juego
                if self._sel_clave != "oculta":
                    self._sel_clave = "oculta"
                    self._ventana({"modo": "oculto"})
                return
            celda = ses.get("localPlayerCellId")
            for m in ses.get("myTeam") or []:
                if m.get("cellId") == celda:
                    # assignedPosition se actualiza si aceptas un cambio de linea con un companero
                    rol = POSICION_LCU.get((m.get("assignedPosition") or "").lower(), "")
                    elegido = m.get("championId") or None
                    champ = elegido or m.get("championPickIntent") or None
            enemigos = [m.get("championId") for m in ses.get("theirTeam") or [] if m.get("championId")]
        except Exception:
            pass
        if not rol and champ:
            rol = self._rol_habitual(champ)      # partidas sin posiciones: el rol en que sueles jugarlo
        self.rol_partida = rol
        plan = plan_actual(self.alm)
        try:
            self._draft(ses, rol, champ, enemigos, plan)
        except Exception as e:
            if not getattr(self, "_draft_err", False):
                self._draft_err = True
                log(f"Selección: no pude preparar el panel ({type(e).__name__}: {e}).")
        s = sesion(self.alm)
        mision = mision_para_rol(plan, rol)
        if self._opcion_clic and self._opcion_clic_champ != elegido:
            self._opcion_clic = None
        self._opcion_clic_champ = elegido
        ops = self._opciones(elegido, rol, enemigos) if elegido else None
        runas_txt = (ops or {}).get("runas_txt")
        build = (ops or {}).get("build")
        self.build_partida = build
        pick_txt = ""
        try:
            pick_txt = self._mejor_pick(rol, [x["id"] for x in ((plan.get("roles") or {}).get("pools") or {}).get(rol) or []],
                                        enemigos)
        except Exception:
            pass
        clave = (rol, champ, tuple(enemigos), (mision or {}).get("clave"), s["parada"], runas_txt,
                 tuple((build or {}).get("orden") or []), (build or {}).get("hab_txt"), pick_txt,
                 json.dumps((ops or {}).get("opciones") or [], ensure_ascii=False))
        if clave == self._sel_clave:
            return
        self._sel_clave = clave
        self.mision_partida = mision
        if not mision:
            return
        estado = {"modo": "seleccion", "regla": mision["regla"], "como": mision["como"],
                  "parada": s["parada"], "motivos": [m["texto"] for m in s["motivos"]], "runas": runas_txt,
                  "tilt_dato": (s.get("tilt_dato") or {}).get("texto")}
        notas = []
        if rol and rol == (plan.get("roles") or {}).get("secundario"):
            notas.append(f"Hoy juegas tu rol secundario ({ROL_TXT.get(rol, rol)}).")
        if mision.get("fuera_de_rol"):
            notas.append("Tu foco no aplica a este rol, así que esta partida trabajas esto.")
        if self.pantalla == 0:
            notas.append("Juegas en pantalla completa: durante la partida esta ventanita se oculta para no sacarte "
                         "del juego. Si quieres verla jugando, pon el juego en Sin bordes.")

        # Que jugar: tu pool del rol de ESTA partida (incluido un cambio de linea)
        todos = (plan.get("pool") or {}).get("todos") or []
        del_rol = [x for x in todos if x["rol"] == rol] if rol else []
        rol_txt = ROL_TXT.get(rol, rol)
        rp = plan.get("roles") or {}
        pool = (rp.get("pools") or {}).get(rol) or []
        pool_ids = [x["id"] for x in pool]
        pool_txt = _lista_y([x["nombre"] for x in pool]).replace(" y ", " o ")
        if rol and rp and rol not in (rp.get("principal"), rp.get("secundario")):
            notas.append(f"Te tocó {rol_txt}, que no es de tus roles ({rp['principal_txt']} y {rp['secundario_txt']}). "
                         "Juega lo más simple que sepas y céntrate en tu misión.")
        if champ:
            nombre = self.rec.campeon(champ)
            mio = next((x for x in (del_rol if rol else todos) if x["campeon_id"] == champ), None)
            hist = f" ({mio['v']}V {mio['d']}D{' de ' + rol_txt if rol else ''})" if mio else ""
            if pool_ids and champ in pool_ids:
                estado["pick"] = f"{nombre}: de tu pool de {rol_txt}{hist}."
                estado["pick_ok"] = True
            elif pool_ids:
                estado["pick"] = f"{nombre} no es de tu pool de {rol_txt}{hist}. Tus campeones: {pool_txt}."
                estado["pick_ok"] = False
            else:
                estado["pick"] = f"{nombre}{' de ' + rol_txt if rol else ''}{hist or ': sin partidas guardadas'}."
                estado["pick_ok"] = bool(mio and mio["v"] >= mio["d"])
        elif pool_ids:
            estado["pick"] = f"De {rol_txt}, tus campeones: {pool_txt}."
            estado["pick_ok"] = True
        elif rol:
            estado["pick"] = f"No tienes campeones fijos para {rol_txt}: elige uno simple y quédate con él."
            estado["pick_ok"] = False
        mu = [x for x in (nota_matchup(self.alm, champ, cid) for cid in enemigos) if x]
        if mu:
            estado["matchup"] = [f"Tu nota contra {self.rec.campeon(x['rival'])}"
                                 + (f" (con {self.rec.campeon(x['yo'])})" if champ and x["yo"] != champ else "")
                                 + f": {x['texto']}" for x in mu[:2]]
        if enemigos:
            with self.alm.lock:
                partidas = list(self.alm.d["partidas"].values())
            vs = []
            for cid in enemigos:
                h = historial_contra(partidas, cid)
                if h:
                    vs.append(f"{self.rec.campeon(cid)} {h['v']}V {h['d']}D")
            if vs:
                notas.append("Tu historial contra sus campeones: " + ", ".join(vs) + ".")
        pp = plan_partida(self.alm, plan, rol)
        if pp.get("lo_mas_importante"):
            estado["plan"] = pp["lo_mas_importante"]["texto"]
        if (mision or {}).get("como"):
            estado["como"] = mision["como"][:1]          # como cumplir la mision: va justo debajo de ella
        rv = stats_revision(self.alm)
        if rv["principal"]:
            estado["revision"] = (f"Tu causa nº1 de muertes: {rv['principal']['nombre'].lower()}. "
                                  + rv["principal"]["consejo"])
        if not estado_entreno(self.alm)["hoy"] and s["partidas"] == 0:
            notas.append("Calentamiento: hoy aún no hiciste tu ejercicio de CS en la Herramienta de práctica.")
        estado["nota_rol"] = " ".join(notas)
        estado["pick_icono"] = self._ico("campeon", champ or (pool_ids[0] if pool_ids else None))
        if runas_txt and self._runas_pag:
            estado["runas_iconos"] = [x for x in (self._ico("runa", self._runas_pag["selectedPerkIds"][0]),
                                                  self._ico("runa", self._runas_pag.get("subStyleId"))) if x]
        if pick_txt:
            estado["pick_web"] = pick_txt
        try:
            act = [r for r in retos_estado(self.alm, self.rec)["retos"]
                   if r["activo"] and r["meta"] is not None and not (rol and rol in (r.get("sin") or []))]
            if act:
                estado["retos_txt"] = "Tus retos en esta partida:\n" + "\n".join("•  " + texto_reto(r) for r in act)
        except Exception:
            pass
        if build and build.get("hab_txt"):
            estado["hab_txt"] = build["hab_txt"]
        if build:
            estado["build_txt"] = build["texto"]
            estado["build_iconos"] = [x for x in (self._ico("item", i) for i in build["orden"][:6]) if x]
        self._con_dano(estado, enemigos, champ)
        self._sel_estado = estado
        # cabecera, banda del dia y resumenes de los apartados plegados
        estado["cab"] = {"campeon": self.rec.campeon(champ) if champ else "Elige campeón",
                         "rol": ROL_TXT.get(rol, rol).capitalize() if rol else "",
                         "rival": self.rec.campeon((ops or {}).get("rival")) if (ops or {}).get("rival") else ""}
        if s["parada"]:
            estado["banda"] = {"tono": "rojo", "texto": "Para por hoy · " + "; ".join(m["texto"] for m in s["motivos"])
                               + (f". {s['tilt_dato']['texto']}" if s.get("tilt_dato") else "")}
        elif s["estado"] == "ojo":
            estado["banda"] = {"tono": "oro", "texto": s["mensaje"]}
        if ops and self.build_info and self.build_info.get("hechizos"):
            estado["hechizos_txt"] = " + ".join(h for h in self.build_info["hechizos"] if h)
        if (ops or {}).get("hab_corta"):
            estado["hab_corta"] = ops["hab_corta"]
        if estado.get("pick"):
            estado["pick_corto"] = "en tu pool" if estado.get("pick_ok", True) else "fuera de tu pool"
        if estado.get("dano_txt"):
            t = estado["dano_txt"].lower()
            estado["dano_corto"] = "físico" if "físico" in t and "mágico" not in t else "mágico" if "mágico" in t and "físico" not in t else ""
        if ops:
            estado["opciones"] = ops["opciones"]
            if ops.get("esperando"):
                estado["opciones_nota"] = "Buscando la build de OTP…"
            elif ops.get("nota"):
                estado["opciones_nota"] = ops["nota"]
            dtx = (ops.get("build") or {}).get("defensa_txt")
            if dtx and estado.get("dano_txt"):
                estado["dano_txt"] = estado["dano_txt"].split(" Por ejemplo:")[0].split(" Casi todo es")[0] + " " + (
                    "Casi todo su daño es " + ("físico" if "daño físico:" in estado["dano_txt"] else "mágico") + ". " + dtx)
                estado["dano_iconos"] = []
        self._ventana(estado)


    def _draft(self, ses, rol, champ, enemigos, plan):
        """Panel de la seleccion para el dashboard (se refresca en cada vuelta, sin pedir nada que bloquee)."""
        if not ses:
            return
        d = draft_equipos(ses)
        nombre = self.rec.campeon
        for f in d["aliados"] + d["rivales"]:
            f["nombre"] = nombre(f["cid"] or f["intento"]) if (f["cid"] or f["intento"]) else ""
        ocupados = set(d["bans_nuestros"] + d["bans_suyos"])
        ocupados |= {f["cid"] for f in d["aliados"] + d["rivales"] if f["cid"]}
        ocupados |= {f["intento"] for f in d["aliados"] if f["intento"] and not f["yo"]}
        mio = next((f for f in d["aliados"] if f["yo"]), None)
        mi_cid = (mio or {}).get("cid") or (mio or {}).get("intento")
        rp = (plan or {}).get("roles") or {}
        pool_plan = [x["id"] for x in (rp.get("pools") or {}).get(rol) or []]
        propios = [x for x in pool_campeones(self.alm) if x["rol"] == rol] if rol else []
        por_cid = {x["cid"]: x for x in propios}
        pool = []
        for cid in pool_plan + [x["cid"] for x in propios if x["n"] >= 2]:
            if cid in [x["cid"] for x in pool]:
                continue
            x = por_cid.get(cid) or {"cid": cid, "nombre": nombre(cid), "n": 0, "v": 0, "wr": None}
            pool.append(dict(x, nombre=x.get("nombre") or nombre(cid)))
        pool = pool[:8]
        lola = rol in LOLA_LINEA
        tabla_de = (lambda c: self._tabla_rivales(c, rol)) if lola else (lambda c: None)
        def gen_de(c, pos):            # datos, {} si Lolalytics no tiene, None mientras se piden
            if not c or pos not in LOLA_LINEA:
                return {}
            g = self._lola_pedir(("gen", c, pos), lambda: lola_build(self.rec, c, pos, "emerald_plus"))
            return None if g is None else (g or {})
        al = [{"cid": f["cid"] or f["intento"], "pos": f["pos"] or (rol if f["yo"] else ""), "nombre": f["nombre"]}
              for f in d["aliados"] if f["cid"] or f["intento"]]
        rv = [{"cid": f["cid"], "pos": f["pos"], "nombre": f["nombre"]} for f in d["rivales"] if f["cid"]]
        pos_r = posiciones_rivales(al, rv, gen_de) if lola else {}
        rival = next((c for c, pos in pos_r.items() if pos == rol), None)
        if lola and enemigos and not rival and not any(a["pos"] == rol for a in al):
            for c in [x["cid"] for x in pool[:3]]:
                rival = self._rival_probable(c, rol, enemigos)
                if rival:
                    break
        with self.alm.lock:
            partidas = list(self.alm.d["partidas"].values())
        sug = draft_sugerencias(pool, tabla_de, rival, ocupados, mi_cid)
        for b in sug["bans"]:
            b["nombre"] = nombre(b["cid"])
            b["motivo"] = f"{nombre(b['base'])} gana solo el {_dec(b['wr'])} % contra él (Esmeralda+)"
        # rivales que mas te ganan en tus partidas (al menos 2 y sin victorias o casi)
        malos = []
        for cid in {(p.get("datos_h") or {}).get("rival_id") for p in partidas if p.get("rol") == rol} - {None}:
            h = historial_contra(partidas, cid)
            if h and h["n"] >= 2 and h["d"] > h["v"] and cid not in ocupados:
                malos.append({"cid": cid, "nombre": nombre(cid), "motivo": f"Tu historial contra él: {h['v']}V {h['d']}D",
                              "hist": True, "orden": h["v"] - h["d"]})
        malos.sort(key=lambda x: x["orden"])
        sug["bans"] = (malos[:2] + [b for b in sug["bans"] if b["cid"] not in {m["cid"] for m in malos[:2]}])[:4]
        riv = None
        if rival:
            h = historial_contra(partidas, rival)
            t = tabla_de(mi_cid) if mi_cid else None
            nm = nota_matchup(self.alm, mi_cid, rival)
            riv = {"cid": rival, "nombre": nombre(rival), "hist": f"{h['v']}V {h['d']}D" if h else "",
                   "vs": round(t[rival][0], 1) if t and rival in t and t[rival][1] >= 100 else None,
                   "nota": (nm or {}).get("texto") or ""}
        contras = []
        tr = tabla_de(rival) if rival else None
        if tr:                       # quien le gana al rival de tu linea (su % contra ellos, el mas bajo primero)
            minimo = max(150, 0.008 * sum(v[1] for v in tr.values()))
            for rid, (wr, n) in sorted(tr.items(), key=lambda kv: kv[1][0]):
                if (n >= minimo and wr < 48.5 and rid not in ocupados
                        and rid not in {x["cid"] for x in sug["picks"] + sug["bans"]}):
                    contras.append({"cid": rid, "nombre": nombre(rid), "wr": round(100 - wr, 1)})
                if len(contras) >= 3:
                    break
        dano_de = lambda c: self.rec.tipo_dano(c)

        def propio_de(c):
            x = por_cid.get(c)
            return {"nombre": nombre(c), "n": (x or {}).get("n", 0), "v": (x or {}).get("v", 0)} if c else None
        prob = prob_draft(al, rv, gen_de, dano_de, propio_de(mi_cid)) if (al or rv) else None
        if prob:
            for f in d["rivales"]:
                f["pos_prob"] = prob["pos_rivales"].get(f["cid"]) or ""
            d["prob"] = {k: prob[k] for k in ("p", "factores", "faltan")}
        if sug["picks"] and rol:
            sin_mi = [a for a in al if a["pos"] != rol]
            for x in sug["picks"]:
                q = prob_draft(sin_mi + [{"cid": x["cid"], "pos": rol, "nombre": x["nombre"]}], rv, gen_de, dano_de,
                               propio_de(x["cid"]))
                x["p"] = q["p"] if q else None
        d.update({"rol": rol, "rol_txt": ROL_TXT.get(rol, rol) if rol else "", "yo_cid": mi_cid,
                  "picks": sug["picks"], "bans_sug": sug["bans"], "rival": riv, "contras": contras,
                  "nombres": {str(x): nombre(x) for x in d["bans_nuestros"] + d["bans_suyos"]},
                  "esperando_lola": lola and any(self._tabla_rivales(x["cid"], rol) is None for x in pool[:4])})
        e = getattr(self, "_sel_estado", None) or {}
        d["coach"] = {k: e.get(k) for k in ("regla", "como", "plan", "runas", "hab_txt", "hab_corta", "build_txt",
                                            "hechizos_txt", "dano_txt", "matchup", "nota_rol", "revision", "opciones",
                                            "opciones_nota", "pick", "pick_ok", "banda") if e.get(k)}
        if self.build_info:
            d["build"] = self.build_info
        self.draft = d

    # -- runas y build
    def _runas(self, champ, rol, enemigos):
        """Aplica runas (fijadas contra el rival > fijadas para el campeon > recomendadas por Riot) y la build."""
        if not champ or not (CONFIG["importar_runas"] or CONFIG["importar_build"]):
            return None
        nombre = self.rec.campeon(champ)
        with self.alm.lock:
            fij = dict((self.alm.d.get("fijados") or {}).get(str(champ)) or {})
        fuente, datos = None, None
        for e in enemigos:
            x = (fij.get("vs") or {}).get(str(e))
            if x:
                fuente, datos = f"fijadas contra {self.rec.campeon(e)}", x
                break
        if not datos and fij.get("general"):
            fuente, datos = f"fijadas para {nombre}", fij["general"]
        clave = (champ, fuente, rol)
        if clave == self._runas_clave:
            return self._runas_txt
        self._runas_clave = clave
        partes = []
        if CONFIG["importar_runas"]:
            runas = (datos or {}).get("runas")
            if not runas:
                runas = self._runas_riot(champ, rol)
                fuente = f"recomendadas por Riot para {ROL_TXT.get(rol, rol)}" if runas else None
            self._runas_pag = runas
            if runas:
                ok = self._poner_pagina(runas, f"Coach: {nombre}")
                partes.append(f"Runas {fuente}: {'aplicadas' if ok else 'no pude aplicarlas'}.")
        self._runas_txt = " ".join(partes) or None
        if self._runas_txt:
            log(f"{nombre}: {self._runas_txt}")
        return self._runas_txt

    # -- runas y build: opciones (fijada, OTP, contra tu rival) y cual esta en uso
    def _lola_pedir(self, clave, fn):
        """Pide datos de Lolalytics aparte (sin frenar al coach). Devuelve lo que haya ya: datos, False o None."""
        if clave in self._lola:
            if self._lola[clave] is not False or time.time() - self._lola_ped.get(clave, 0) < 120:
                return self._lola[clave]
            del self._lola[clave]
        if clave not in self._lola_ped or time.time() - self._lola_ped[clave] > 120:
            self._lola_ped[clave] = time.time()

            def pedir():
                try:
                    r = fn()
                except Exception:
                    r = None
                self._lola[clave] = r or False
            threading.Thread(target=pedir, daemon=True).start()
        return None

    def _tabla_rivales(self, champ, rol):
        """{rival: (% de victorias de tu campeon contra el, partidas)} en tu linea, de Lolalytics (Esmeralda o
        mas). None mientras se pide; {} si no hay datos."""
        gen = self._lola_pedir(("gen", champ, rol), lambda: lola_build(self.rec, champ, rol, "emerald_plus"))
        if gen is None:
            return None
        return {int(k): tuple(v) for k, v in ((gen or {}).get("enemigos") or {}).items()}

    def _rival_probable(self, champ, rol, enemigos):
        """De los rivales ya elegidos, el que juega tu misma linea: el que mas partidas tiene contra tu campeon
        en esa linea. None si aun no se puede saber."""
        tabla = self._tabla_rivales(champ, rol) if enemigos and rol in LOLA_LINEA else None
        if not tabla:
            return None
        vistos = [(e, tabla[e][1]) for e in enemigos if e in tabla and tabla[e][1] >= 200]
        return max(vistos, key=lambda x: x[1])[0] if vistos else None

    def elegir_opcion(self, clave):
        """Clic en "Usar" de la ventanita: se aplica en la siguiente vuelta del coach y queda como preferencia."""
        self._opcion_clic = clave
        if clave in ("otp", "gen", "rival"):
            with self.alm.lock:
                self.alm.d["pref_build"] = clave
            try:
                self.alm.guardar()
            except Exception:
                pass

    def _opciones(self, champ, rol, enemigos):
        """Las builds y runas disponibles para esta partida y la que esta en uso (ya aplicada en el cliente)."""
        nombre = self.rec.campeon(champ)
        with self.alm.lock:
            fij = dict((self.alm.d.get("fijados") or {}).get(str(champ)) or {})
            pref = self.alm.d.get("pref_build") or "otp"
        ops = []
        for e in enemigos or []:
            x = (fij.get("vs") or {}).get(str(e))
            if x and ((x.get("build") or {}).get("orden") or x.get("runas")):
                ops.append({"clave": "fijada", "titulo": f"Tu build fijada contra {self.rec.campeon(e)}", "detalle": "",
                            "runas": x.get("runas"), "build": x.get("build") or {}, "sub": "La que guardaste"})
                break
        if not ops and fij.get("general") and (((fij["general"].get("build") or {}).get("orden")) or fij["general"].get("runas")):
            ops.append({"clave": "fijada", "titulo": "Tu build fijada", "detalle": "",
                        "runas": fij["general"].get("runas"), "build": fij["general"].get("build") or {},
                        "sub": "La que guardaste"})

        def detalle(b, quien):
            if not b.get("total") or b.get("wr_total") is None:
                return ""
            return f"{_miles(b['total'])} partidas de {quien}; ganan el {_dec(b['wr_total'])}%"
        otp = self._lola_pedir(("otp", champ, rol), lambda: lola_build(self.rec, champ, rol, "1trick"))
        gen = self._lola_pedir(("gen", champ, rol), lambda: lola_build(self.rec, champ, rol, "emerald_plus"))
        if otp:
            ops.append({"clave": "otp", "titulo": f"OTP de {nombre}", "detalle": detalle(otp, "jugadores OTP"),
                        "runas": otp.get("runas"), "build": otp, "fuente": "Lolalytics", "wr": otp.get("wr_total"),
                        "sub": f"{_miles(otp['total'])} partidas de jugadores OTP" if otp.get("total") else ""})
        if gen and (gen.get("orden") or gen.get("runas")):
            ops.append({"clave": "gen" if otp else "otp", "titulo": "Más jugada (Esmeralda o más)",
                        "detalle": detalle(gen, "Esmeralda o más"), "runas": gen.get("runas"), "build": gen,
                        "fuente": "Lolalytics", "wr": gen.get("wr_total"),
                        "sub": f"{_miles(gen['total'])} partidas" if gen.get("total") else ""})
        rival = self._rival_probable(champ, rol, enemigos)
        if rival:
            vs = self._lola_pedir(("vs", champ, rol, rival), lambda: lola_vs(self.rec, champ, rol, rival))
            if vs:
                wr_m, n_m = vs.get("wr"), vs.get("n")
                if wr_m is None or not n_m:
                    wr_m, n_m = (self._tabla_rivales(champ, rol) or {}).get(rival) or (None, None)
                det = (f"{_miles(n_m)} partidas contra {self.rec.campeon(rival)}; {nombre} gana el {_dec(wr_m)}%"
                       if wr_m is not None and n_m else "")
                ops.append({"clave": "rival", "titulo": f"Contra {self.rec.campeon(rival)}", "detalle": det,
                            "runas": vs.get("runas"), "build": vs, "fuente": "Lolalytics", "wr": wr_m,
                            "sub": f"{_miles(n_m)} partidas del enfrentamiento" if n_m else ""})
        if not any(o["clave"] == "otp" for o in ops) and (otp is False and gen is False or rol not in LOLA_LINEA):
            web = self._build(champ, rol, [], poner=False)          # ultimo recurso: u.gg + runas de Riot
            if web and web.get("fuente") != "fijada":
                ops.append({"clave": "ugg", "titulo": "Más jugada en u.gg", "detalle": f"{web.get('wr', '?')}% de victorias",
                            "runas": None, "build": web, "fuente": "u.gg", "wr": web.get("wr"), "sub": "u.gg"})
        if not ops:
            return None
        clic = self._opcion_clic if self._opcion_clic in [o["clave"] for o in ops] else None
        orden_pref = [clic, "fijada", pref, "otp", "gen", "rival", "ugg"]
        sel = next(o for c in orden_pref if c for o in ops if o["clave"] == c)
        # build en uso, adaptada al daño de su equipo
        tags = (self.rec.consejos(champ) or {}).get("tags") or []
        de = None
        try:
            de = dano_equipo([self.rec.tipo_dano(c, self.lcu) for c in enemigos or []], tags)
        except Exception:
            pass
        b = sel["build"] or {}
        orden, cambios = adaptar_build(self.rec, b, (de or {}).get("tipo"), otp or gen or None)
        build = None
        defensa_txt = None
        if (de or {}).get("tipo") and sel["clave"] != "ugg":
            defensa_txt = ("Build adaptada: " + "; ".join(cambios) + "." if cambios else
                           "La build no cambia: es lo que compran los jugadores de tu campeón también contra ese daño.")
        if orden:
            build = {"inicio": b.get("inicio") or [], "orden": orden, "fuente": sel["clave"], "defensa_txt": defensa_txt,
                     "texto": sel["titulo"] + (f" ({sel['fuente']})" if sel.get("fuente") else ""),
                     "hab_txt": texto_habilidades(b, self.rec), "hab_corta": " > ".join(b.get("habilidades") or ""),
                     "cambios": cambios}
        runas, runas_txt = sel.get("runas"), None
        if CONFIG["importar_runas"]:
            fuente = sel["titulo"]
            if not runas:
                runas = self._runas_riot(champ, rol)
                fuente = "recomendadas por Riot"
            marca_r = (champ, tuple((runas or {}).get("selectedPerkIds") or []))
            if runas and marca_r != self._runas_clave:
                self._runas_clave = marca_r
                self._runas_ok = self._poner_pagina(runas, f"Coach: {nombre}")
                log(f"{nombre}: runas de \"{fuente}\" {'aplicadas' if self._runas_ok else 'no se pudieron aplicar'}.")
            self._runas_pag = runas
            if runas:
                runas_txt = (f"Runas: {self.rec.runa(runas['selectedPerkIds'][0])} + {self.rec.runa(runas['subStyleId'])}. "
                             + ("Ya están puestas." if getattr(self, "_runas_ok", False) else "No pude ponerlas en el cliente."))
        if build and CONFIG["importar_build"]:
            marca = (champ, sel["clave"], tuple(build["orden"]))
            if marca != self._build_puesta:
                self._build_puesta = marca
                en_tienda = self._poner_items(champ, nombre, build, f"{sel['titulo']} (Coach LoL)"[:60])
                log(f"{nombre}: build \"{sel['titulo']}\": {', '.join(self.rec.item(i) for i in build['orden'])}."
                    + (f" Adaptada: {'; '.join(cambios)}." if cambios else "")
                    + ("" if en_tienda else " No pude ponerla en la tienda del juego."))
            guardar_build_partida(champ, build)
        # hechizos de invocador de la build elegida (las fijadas no los guardan: se usan los de Lolalytics)
        hechizos = b.get("hechizos") or (otp or {}).get("hechizos") or (gen or {}).get("hechizos")
        if hechizos and CONFIG.get("importar_hechizos", True):
            marca_h = (champ, tuple(hechizos))
            if marca_h != self._hechizos_puestos:
                try:
                    if self._poner_hechizos(hechizos):
                        self._hechizos_puestos = marca_h
                        log(f"{nombre}: hechizos de \"{sel['titulo']}\": "
                            f"{' y '.join(self.rec.hechizos.get(str(h), str(h)) for h in hechizos)}.")
                except Exception as e:
                    log(f"{nombre}: no pude poner los hechizos ({type(e).__name__}).")
                    self._hechizos_puestos = marca_h        # no se reintenta en bucle
        pq = b.get("porque") or {}
        self.build_info = {
            "campeon_id": champ, "campeon": nombre, "rol": rol, "titulo": sel["titulo"], "fuente": sel.get("fuente") or "",
            "detalle": sel["detalle"], "cambios": cambios, "runas": self.rec.detalle_runas(runas) if runas else None,
            "habilidades": texto_habilidades(b, self.rec),
            "hechizos": [self.rec.hechizos.get(str(h), "") for h in hechizos or []],
            "opciones": [{"clave": o["clave"], "titulo": o["titulo"], "detalle": o["detalle"], "sel": o is sel} for o in ops],
            "items": [{"id": i, "nombre": self.rec.item(i), "n": (pq.get(str(i)) or {}).get("n"),
                       "wr": (pq.get(str(i)) or {}).get("wr"),
                       "motivo": (pq.get(str(i)) or {}).get("motivo") or ("adaptado al daño de su equipo" if i not in (b.get("orden") or []) else "")}
                      for i in (build or {}).get("orden") or []]}
        return {"opciones": [{"clave": o["clave"], "titulo": o["titulo"], "detalle": o["detalle"],
                              "sel": o is sel, "wr": o.get("wr"), "sub": o.get("sub") or o["detalle"]} for o in ops],
                "rival": rival, "hab_corta": " › ".join(b.get("habilidades") or ""),
                "build": build, "runas_txt": runas_txt, "cambios": cambios,
                "esperando": otp is None or (otp is False and gen is None),
                "nota": ("La que elijas con \"Usar\" pone sus runas y objetos en el cliente y queda como tu preferida."
                         if len(ops) > 1 else "")}

    def _build(self, champ, rol, enemigos, poner=True):
        """La build de esta partida: la que fijaste contra ese rival, la que fijaste para el campeon o, si no hay,
        la mas jugada en u.gg para ese campeon y rol (se pide aparte para no frenar al coach)."""
        if not champ:
            return None
        with self.alm.lock:
            fij = dict((self.alm.d.get("fijados") or {}).get(str(champ)) or {})
        build = None
        for e in enemigos or []:
            x = ((fij.get("vs") or {}).get(str(e)) or {}).get("build")
            if x and x.get("orden"):
                build = dict(x, fuente="fijada", texto=f"Tu build fijada contra {self.rec.campeon(e)}")
                break
        if not build and ((fij.get("general") or {}).get("build") or {}).get("orden"):
            build = dict(fij["general"]["build"], fuente="fijada", texto="Tu build fijada")
        web = self._builds.get((champ, rol))
        if web and not build:
            build = dict(web, texto=f"Build más jugada en u.gg (parche {web.get('parche', '?')}, "
                                    f"{_miles(web['partidas'])} partidas, {web['wr']}% de victorias)")
        if build:
            build["hab_txt"] = texto_habilidades(web, self.rec)
            build["hab_corta"] = " > ".join((web or {}).get("habilidades") or "")
        if not web:
            if ((champ, rol) not in self._build_pedidos and rol in UGG_ROL
                    and time.time() - self._build_fallo.get((champ, rol), 0) > 60):
                self._build_pedidos.add((champ, rol))

                def pedir():
                    b = build_web(champ, rol)
                    if b:
                        self._builds[(champ, rol)] = b
                        log(f"Build de u.gg para {self.rec.campeon(champ)} {ROL_TXT.get(rol, rol)}: "
                            f"{', '.join(self.rec.item(i) for i in b['orden'])}.")
                    else:
                        self._build_fallo[(champ, rol)] = time.time()
                        self._build_pedidos.discard((champ, rol))      # se reintenta pasado un minuto
                threading.Thread(target=pedir, daemon=True).start()
        if build and poner and CONFIG["importar_build"]:
            marca = (champ, build.get("fuente"), tuple(build["orden"]))
            if marca != self._build_puesta:
                self._build_puesta = marca
                self._poner_items(champ, self.rec.campeon(champ), build,
                                  "Build fijada (Coach LoL)" if build["fuente"] == "fijada" else "Build de u.gg (Coach LoL)")
        return build

    def _mejor_pick(self, rol, pool_ids, enemigos):
        """Texto con cual de tus campeones del rol gana mas contra el rival de tu linea (datos de Lolalytics)."""
        if len(pool_ids) < 2 or not enemigos or rol not in LOLA_LINEA:
            return ""
        tablas = {c: self._tabla_rivales(c, rol) or {} for c in pool_ids}
        return mejor_pick(pool_ids, enemigos, tablas, self.rec.campeon)

    def _scout(self, estado, rival, su_lado, ses):
        """En la pantalla de carga: rango, racha y campeon de los 10 (cada uno se pinta al llegar) y como empieza
        su jungla, sacado de sus ultimas partidas de jungla. Todo en segundo plano: el bucle no se para."""
        eq = estado["equipos"]
        filas = [f for f in eq["rivales"] + eq["aliados"] if f["puuid"]]
        rival_puuid = (rival or {}).get("puuid")
        lock = threading.Lock()              # los hilos tocan estado; la ventanita recibe una copia

        def vigente():
            return self.carga is estado

        def pintar():
            if vigente():
                with lock:
                    copia = json.loads(json.dumps(estado, ensure_ascii=False))
                self._ventana(copia)

        def jungla(f, ficha):
            if not ficha.get("jungla"):
                return
            with lock:
                estado["jungla_pend"] = True
            pintar()
            plan = plan_jungla(timelines_jungla(self.lcu, ficha["jungla"], f["puuid"]))
            tp = texto_plan_jungla(plan, su_lado, f["nombre"], self.rol_partida)
            with lock:
                estado.pop("jungla_pend", None)
                if tp and vigente():
                    estado["jungla"] = dict(tp, ico=f["ico"])
                    self.plan_jungla = dict(tp, plan=plan, nombre=f["nombre"], su_lado=su_lado)
            if tp:
                log("Plan de su jungla: " + tp["txt"])
            pintar()

        def muestra():
            # lo que da la LCU en la carga, para afinar (solo una vez; se queda en datos/, que no se publica)
            arch = DATOS / "scout_muestra.json"
            if arch.exists():
                return
            try:
                otro = next(f for f in eq["rivales"] if f["puuid"])
                h = self.lcu.get(f"/lol-match-history/v1/products/lol/{otro['puuid']}/matches?begIndex=0&endIndex=4", timeout=8)
                gs = (h.get("games") or {}).get("games") or []
                tl = self.lcu.get(f"/lol-match-history/v1/game-timelines/{gs[0]['gameId']}", timeout=15) if gs else None
                arch.write_text(json.dumps({"sesion": ses, "historial": h, "timeline": tl}), encoding="utf-8")
            except Exception as e:
                log(f"Scouting: no pude guardar la muestra ({type(e).__name__}: {e}).")

        def pedir():
            threading.Thread(target=muestra, daemon=True).start()
            fichas = {}
            jg = next((f for f in eq["rivales"] if f["pos"] == "jungla" or f["smite"]), None)

            def una(f):
                try:
                    ficha = ficha_jugador(self.lcu, f["puuid"], f["cid"])
                except Exception as e:
                    ficha = {}
                    if not getattr(self, "_ficha_err", False):
                        self._ficha_err = True
                        log(f"Scouting: no pude leer un jugador ({type(e).__name__}: {e}).")
                with lock:
                    fichas[f["puuid"]] = ficha
                    f["rango"] = ficha.get("rango") or ""
                    f["chips"] = etiquetas_jugador(ficha, f["enemigo"])
                    f["cargando"] = False
                    if f["puuid"] == rival_puuid:
                        estado["rival_info"] = lineas_ficha(ficha, f["nombre"]) + list(estado.get("rival_info") or [])
                if f is jg:
                    jungla(f, ficha)
                pintar()
            hilos = [threading.Thread(target=una, args=(f,), daemon=True) for f in filas]
            for t in hilos:
                t.start()
            fin = time.time() + 45
            for t in hilos:
                t.join(max(0.1, fin - time.time()))
            log(f"Scouting: {sum(1 for x in fichas.values() if x.get('n'))} de {len(filas)} jugadores con historial leído"
                f"{'' if jg else '; no sé quién va de jungla, lo busco por Castigo'}.")
            if jg is None and vigente():
                # no se sabe quien va de jungla: el rival que mas partidas recientes juega con Castigo
                cand = [(len(fichas.get(f["puuid"], {}).get("jungla") or []) / max(1, fichas.get(f["puuid"], {}).get("n") or 1), f)
                        for f in eq["rivales"] if f["puuid"] in fichas]
                cand = [c for c in cand if c[0] >= 0.5]
                if cand:
                    f = max(cand, key=lambda c: c[0])[1]
                    jungla(f, fichas[f["puuid"]])
        threading.Thread(target=pedir, daemon=True).start()

    def _con_jungla(self, estado, data):
        """Un aviso unos segundos antes de que su jungla suela aparecer por tu linea."""
        try:
            pj = self.plan_jungla
            if not pj or self._aviso_jungla or not estado or estado.get("modo") != "partida":
                return estado
            if not pj.get("lado_ok"):
                # el lado de cada equipo se confirma con la partida en vivo (ORDER = azul / 100, CHAOS = rojo / 200)
                yo = _yo_en_vivo(data or {}, ((self.alm.d.get("jugador") or {}).get("nombre") or ""))
                real = {"ORDER": 200, "CHAOS": 100}.get((yo or {}).get("team"))
                pj["lado_ok"] = bool(real)
                if real and real != pj.get("su_lado"):
                    log(f"El lado de su jungla no era el que creía ({pj.get('su_lado')} -> {real}): recalculo su plan.")
                    tp = texto_plan_jungla(pj.get("plan"), real, pj.get("nombre") or "Su jungla", self.rol_partida)
                    if not tp:
                        self.plan_jungla = None
                        return estado
                    pj.update(tp, su_lado=real)
            if not pj.get("alerta") or estado.get("aviso"):
                return estado
            t = float(((data or {}).get("gameData") or {}).get("gameTime") or 0)
            lim = (pj.get("minuto") or 3.25) * 60
            if lim - 50 <= t <= lim:
                self._aviso_jungla = True
                return dict(estado, aviso=f"Su jungla suele llegar a tu línea hacia el {_min_seg(pj['minuto'] or 3.25)}: "
                                          "ward en el río y no pases de la mitad.", tono="rojo")
            if t > lim:
                self._aviso_jungla = True
            return estado
        except Exception as e:
            log(f"Plan de su jungla en partida: {type(e).__name__}: {e}")
            self.plan_jungla = None
            return estado

    def _cfg_objetivos(self):
        t, cfg = self._obj_cfg
        if cfg is None or time.time() - t > 5:             # Ajustes se lee como mucho cada 5 s
            cfg = avisos_objetivos_cfg()
            self._obj_cfg = (time.time(), cfg)
        return cfg

    def _muestra_eventos(self, data, t):
        """Para afinar con partidas reales: anota una vez cada evento que no conocia y guarda una muestra de los
        eventos hacia el minuto 21 (solo en datos/, que no se publica)."""
        evs = ((data.get("events") or {}).get("Events")) or []
        for e in evs:
            nm = e.get("EventName")
            if nm and nm not in EVENTOS_CONOCIDOS and nm not in self._ev_raros:
                self._ev_raros.add(nm)
                log(f"Evento de partida que no conocía: {nm} {json.dumps(e, ensure_ascii=False)[:160]}")
        if not self._ev_muestra and t >= 1260:
            self._ev_muestra = True
            arch = DATOS / "eventos_muestra.json"
            if not arch.exists():
                try:
                    arch.write_text(json.dumps({"gameData": data.get("gameData"), "events": evs}, ensure_ascii=False),
                                    encoding="utf-8")
                except Exception:
                    pass

    def _con_objetivos(self, estado, data):
        """Temporizadores de dragon, larvas, Heraldo y Baron, y un aviso antes de que salgan (y cuando alguien
        coge el Baron o el Anciano). Si el hueco de avisos esta ocupado, lo vuelve a intentar en la siguiente vuelta."""
        try:
            if not estado or estado.get("modo") != "partida":
                return estado
            q = self.cola_partida or {}
            if q.get("id") in COLAS_SIN_OBJETIVOS or (q.get("modo") and str(q["modo"]).upper() != "CLASSIC"):
                return estado
            yo = _yo_en_vivo(data, ((self.alm.d.get("jugador") or {}).get("nombre") or ""))
            ob = objetivos_vivo(data, (yo or {}).get("team"))
            if not ob:
                return estado
            self._muestra_eventos(data, ob["t"])
            for f in ob["fichas"]:
                f["ico_ruta"] = icono_objetivo(f["ico"])
            cfg = self._cfg_objetivos()
            estado = dict(estado, objetivos=ob)
            t, hechos, pend = ob["t"], self._obj_avisados, []
            for f in ob["fichas"]:
                b = f.get("bufo")
                if b:
                    clave = ("bufo", f["clave"], int(b["desde"]))
                    if clave not in hechos:
                        if t - b["desde"] > 25:
                            hechos.add(clave)                   # ya paso hace rato (p. ej. el coach se abrio tarde)
                        elif cfg["avisos"].get(f["grupo"], True):
                            tit, txt = AVISO_BUFO[(f["clave"] if f["clave"] == "baron" else "anciano", b["mio"])]
                            pend.append((-1, clave, f, tit + " · " + _seg_txt(b["hasta"] - t), txt,
                                         "verde" if b["mio"] else "rojo"))
                if not cfg["avisos"].get(f["grupo"], True):
                    continue
                falta, clave = f["sale"] - t, (f["clave"], int(f["sale"]))
                if clave in hechos or falta > cfg["antelacion"]:
                    continue
                if falta < -15 or (f.get("fin") and t >= f["fin"]):
                    hechos.add(clave)
                    continue
                tit, txt = texto_aviso_objetivo(f, falta, self.rol_partida, ob)
                pend.append((falta, clave, f, tit, txt, "oro"))
            if pend and not estado.get("aviso"):
                _, clave, f, tit, txt, tono = min(pend, key=lambda x: x[0])
                hechos.add(clave)
                estado = dict(estado, aviso=txt, aviso_tit=tit, aviso_ico=f.get("ico_ruta"), tono=tono, aviso_seg=10)
                self._t_aviso = time.time()
                if cfg["sonido"]:
                    sonar_aviso()
            return estado
        except Exception as e:
            if not getattr(self, "_obj_err", False):
                self._obj_err = True
                log(f"Objetivos en partida: {type(e).__name__}: {e}")
            return estado

    def _con_baratija(self, estado, data):
        """Una vez por partida: cambia el Totem por la Lente del Oraculo cuando a tu rol le toca."""
        try:
            if (not estado or estado.get("modo") != "partida" or estado.get("aviso")
                    or ("baratija",) in self._obj_avisados or not self._cfg_objetivos()["baratija"]
                    or time.time() - self._t_aviso < 15):
                return estado
            yo = _yo_en_vivo(data, ((self.alm.d.get("jugador") or {}).get("nombre") or ""))
            if not yo:
                return estado
            t = float((data.get("gameData") or {}).get("gameTime") or 0)
            av = baratija_aviso(self.rol_partida, t / 60, yo.get("items"))
            if not av:
                return estado
            self._obj_avisados.add(("baratija",))
            self._t_aviso = time.time()
            return dict(estado, aviso=av[1], aviso_tit=av[0], aviso_ico=self._ico("item", BARATIJA_LENTE),
                        tono="azul", aviso_seg=12)
        except Exception as e:
            if not getattr(self, "_bar_err", False):
                self._bar_err = True
                log(f"Aviso de baratija: {type(e).__name__}: {e}")
            return estado

    def _con_dano(self, estado, enemigos, champ):
        """Añade a la ventanita de que tipo es el daño de su equipo y que defensa comprar."""
        try:
            tipos = [self.rec.tipo_dano(c, self.lcu) for c in enemigos]
            tags = ((self.rec.consejos(champ) or {}).get("tags") or []) if champ else []
            de = dano_equipo(tipos, tags)
            if de:
                txt = de["texto"]
                if de["items"]:
                    txt += " Por ejemplo: " + _lista_y([self.rec.item(i) for i in de["items"]]).replace(" y ", " o ") + "."
                estado["dano_txt"] = txt
                estado["dano_iconos"] = [x for x in (self._ico("item", i) for i in de["items"]) if x]
        except Exception:
            pass

    def _con_hud(self, estado, data):
        """Añade los datos de las tarjetas de partida: tus numeros contra el rango de encima del tuyo, la
        mision, tu reto activo, el siguiente objeto y si ya te alcanza el oro para volver a base."""
        try:
            if not estado or estado.get("modo") != "partida" or not CONFIG.get("hud_partida", True):
                return estado
            yo = _yo_en_vivo(data, ((self.alm.d.get("jugador") or {}).get("nombre") or ""))
            if not yo:
                return estado
            ap, sc = data.get("activePlayer") or {}, yo.get("scores") or {}
            t = float((data.get("gameData") or {}).get("gameTime") or 0)
            k, d, a = (int(sc.get(x) or 0) for x in ("kills", "deaths", "assists"))
            cs, oro = int(sc.get("creepScore") or 0), float(ap.get("currentGold") or 0)
            its = yo.get("items") or []
            # oro ganado aproximado: el que llevas mas el valor de lo que tienes comprado
            ganado = oro + sum(((self.rec.items.get(str(i.get("itemID"))) or {}).get("precio") or 0) * int(i.get("count") or 1) for i in its)
            eq_k = sum(int((p.get("scores") or {}).get("kills") or 0) for p in data.get("allPlayers") or []
                       if p.get("team") == yo.get("team"))
            nombre = (yo.get("championName") or "").lower()
            cid = next((int(c) for c, v in self.rec.campeones.items() if v.lower() == nombre), None)
            tier = tier_siguiente((self.alm.d.get("rango") or {}).get("tier"))
            m = medias_tier(self.rec, cid, self.rol_partida, tier.lower()) if cid and self.rol_partida else None
            dur = (m or {}).get("min")
            minutos = t / 60

            def fila(et, valor, ref=None, dec=1):
                f = {"et": et, "yo": "–" if valor is None else _dec(valor, dec) if dec else str(int(valor))}
                if ref is not None and valor is not None:
                    f["ref"] = _dec(ref, dec) if dec else str(int(round(ref)))
                    f["tono"] = "bien" if valor >= ref else "mal"
                return f
            pm = minutos if t >= 120 else None            # antes del minuto 2 los "por minuto" no dicen nada
            filas = []
            if self.rol_partida != "support":
                filas.append(fila("CS/min", cs / pm if pm else None, m["cs"] / dur if m and dur and m.get("cs") else None))
            else:                # de support no se farmea: lo tuyo es la vision (Lolalytics no publica su media)
                filas.append(fila("Visión/min", float(sc.get("wardScore") or 0) / pm if pm else None, None, 2))
            filas.append(fila("Oro/min", ganado / pm if pm else None, m["gold"] / dur if m and dur and m.get("gold") else None, 0))
            filas.append(fila("KP %", (k + a) * 100 / eq_k if eq_k else None, None, 0))
            filas.append(fila("KDA", (k + a) / max(d, 1),
                              (m["kills"] + m["assists"]) / m["deaths"] if m and m.get("deaths") and m.get("kills") is not None else None))
            hud = {"filas": filas, "ref": TIER_ES.get(tier, "") if m and not m.get("general") else ("media general" if m else ""),
                   "mision": estado.get("regla", ""), "mision_estado": estado.get("estado", ""),
                   "mision_nombre": estado.get("mision_nombre", ""), "mision_st": estado.get("mision_st", "curso")}
            ob = estado.get("objetivos")
            try:
                gd = data.get("gameData") or {}
                mv = marcador_vivo(data, yo.get("team"), lambda i: (self.rec.items.get(str(i)) or {}).get("precio") or 0, ob) \
                    if es_grieta({"modo": gd.get("gameMode"), "mapa": gd.get("mapNumber")}) else None
                if mv:
                    hud["eq"] = mv
            except Exception as ex:
                if not getattr(self, "_hud_err3", False):
                    self._hud_err3 = True
                    log(f"Tarjetas de partida (equipo): {type(ex).__name__}: {ex}")
            if ob and ob.get("fichas"):
                hud["obj"] = [{k: f.get(k) for k in ("clave", "corto", "ico_ruta", "sale", "fin", "sub", "sub_tono", "bufo")}
                              for f in ob["fichas"]]
            if self._hud_reto is None:
                rs = [r for r in retos_estado(self.alm, self.rec)["retos"] if r.get("activo")]
                self._hud_reto = rs[0] if rs else {}
            r = self._hud_reto
            if r:
                hud["reto"] = r["nombre"]
                if r.get("meta") is not None:
                    hud["reto_meta"] = f"{r['medida']}: {'≤' if r.get('menor') else '≥'} {_dec(r['meta'])} {r.get('unidad') or ''}".strip()
            if estado.get("objeto"):
                hud["objeto"], hud["objeto_ico"] = estado["objeto"], estado.get("objeto_ico")
            if estado.get("tira"):
                hud["tira"] = [x for x in estado["tira"] if x.get("ico")][:6]
            if estado.get("objeto_id") and estado.get("objeto_falta") is not None:
                precio = ((self.rec.items.get(str(estado["objeto_id"])) or {}).get("precio") or 0)
                if precio:
                    hud["oro_pct"] = round(max(0.0, min(1.0, 1 - estado["objeto_falta"] / precio)), 2)
            try:                 # filas extra: si algo falla aqui, el resto de las tarjetas sigue
                # tu rival de linea, con lo que tambien ves en la tabla del Tab: CS y nivel
                rv = None
                pos = (yo.get("position") or "").upper()
                enem = [x for x in data.get("allPlayers") or [] if x.get("team") != yo.get("team")]
                if pos and pos != "NONE":
                    rv = next((x for x in enem if (x.get("position") or "").upper() == pos), None)
                if not rv and self.rival_partida:
                    nr = (self.rec.campeon(self.rival_partida) or "").lower()
                    rv = next((x for x in enem if (x.get("championName") or "").lower() == nr), None)
                if rv:
                    rsc = rv.get("scores") or {}
                    niv, rniv = int(yo.get("level") or 0), int(rv.get("level") or 0)
                    if self.rol_partida == "support":
                        filas.append({"et": "Nivel vs " + (rv.get("championName") or "rival")[:9], "yo": f"{niv - rniv:+d}",
                                      "ref": f"{niv}/{rniv}", "tono": "bien" if niv >= rniv else "mal"})
                    else:
                        rcs = int(rsc.get("creepScore") or 0)
                        filas.append({"et": "CS vs " + (rv.get("championName") or "rival")[:9], "yo": f"{cs - rcs:+d}",
                                      "ref": f"niv {niv}/{rniv}", "tono": "bien" if cs >= rcs else "mal"})
                # habilidad que toca subir (orden de la build en uso)
                orden_h = [x.strip() for x in ((self.build_partida or {}).get("hab_corta") or "").replace("›", ">").split(">") if x.strip()]
                sube = habilidad_a_subir(ap.get("abilities") or {}, ap.get("level") or yo.get("level"), orden_h)
                if sube:
                    filas.append({"et": "Sube habilidad", "yo": sube, "ref": " › ".join(orden_h) if orden_h else "", "tono": "azul"})
                # guia contra tu rival de linea (fija toda la partida: se calcula una vez)
                if rv and self.rol_partida in LOLA_LINEA:
                    rnom = (rv.get("championName") or "").lower()
                    rcid = next((int(c) for c, v in self.rec.campeones.items() if v.lower() == rnom), None)
                    gk = self._hud_guia or {}
                    if rcid and (gk.get("_k") != (cid, rcid) or (not gk.get("_wr") and time.time() - gk.get("_t", 0) > 120)):
                        tabla = self._tabla_rivales(cid, self.rol_partida) if cid else {}
                        con = self._lola_pedir(("consejos", rcid), lambda: self.rec.consejos(rcid))   # sin frenar el bucle
                        if tabla is not None and con is not None:    # None = aun se piden: siguiente vuelta
                            with self.alm.lock:
                                hist = historial_contra(list(self.alm.d["partidas"].values()), rcid)
                            wr = (tabla or {}).get(rcid)
                            g = guia_enfrentamiento(rv.get("championName"), con or None, wr, hist)
                            self._hud_guia = dict(g or {}, _k=(cid, rcid), _wr=bool(wr), _t=time.time())
                    if (self._hud_guia or {}).get("tips"):
                        hud["guia"] = {k: v for k, v in self._hud_guia.items() if not k.startswith("_")}
            except Exception as e:
                if not getattr(self, "_hud_err2", False):
                    self._hud_err2 = True
                    log(f"Tarjetas de partida (rival/habilidad): {type(e).__name__}: {e}")
            cb = None
            if self.build_partida:
                cb = compra_base(self.rec, self.build_partida["orden"], [i.get("itemID") for i in its], oro)
            if cb:
                hud["objeto_ico"] = self._ico("item", cb["id"])
                if cb["tipo"] == "listo":
                    hud["objeto"], hud["base"] = f"Tu objeto de support terminó su misión", f"Elige {cb['nombre']} en la tienda: es gratis"
                elif cb["tipo"] == "completo":
                    hud["objeto"], hud["base"] = f"Te alcanza para {cb['nombre']}", "Vuelve a base cuando tu oleada esté empujada"
                else:
                    hud["objeto"], hud["base"] = f"Te alcanza para {cb['nombre']} (pieza de {cb['para']})", "Buen momento para volver a base"
                clave = (cb["tipo"], cb["id"])
                if clave != self._hud_base and not estado.get("aviso") and t > 90:
                    estado = dict(estado, aviso=hud["objeto"] + ". " + hud["base"] + ".", tono="verde")
                self._hud_base = clave
            else:
                self._hud_base = None
            return dict(estado, hud=hud)
        except Exception as e:
            if not getattr(self, "_hud_err", False):
                self._hud_err = True
                log(f"Tarjetas de partida: {type(e).__name__}: {e}")
            return estado

    def _con_objeto(self, estado, data):
        """Añade a la ventanita el siguiente objeto de tu build y el oro que te falta."""
        try:
            yo = _yo_en_vivo(data, ((self.alm.d.get("jugador") or {}).get("nombre") or ""))
            if not yo or not estado or estado.get("modo") != "partida":
                return estado
            if not self.build_partida:
                # el coach se abrio con la partida empezada: busca la build por el nombre del campeon
                nombre = (yo.get("championName") or "").lower()
                cid = next((int(k) for k, v in self.rec.campeones.items() if v.lower() == nombre), None)
                # la que elegiste en la seleccion (si el coach se reinicio en partida); si no, la fijada o u.gg
                self.build_partida = leer_build_partida(cid) or self._build(cid, self.rol_partida, [], poner=False)
                if not self.build_partida:
                    return estado
            tengo = [i.get("itemID") for i in yo.get("items") or []]
            oro = float((data.get("activePlayer") or {}).get("currentGold") or 0)
            so = siguiente_objeto(self.rec, self.build_partida["orden"], tengo, oro)
            tira = tira_build(self.rec, self.build_partida["orden"][:6], tengo)
            if self.build_partida.get("hab_corta"):
                estado = dict(estado, hab="Habilidades: " + self.build_partida["hab_corta"])
            estado = dict(estado, tira=[{"ico": self._ico("item", x["id"]), "estado": x["estado"]} for x in tira],
                          objeto_clave="".join(x["estado"][0] for x in tira))
            if not so:
                estado["objeto"] = "Build completa."
            if so:
                estado = dict(estado, objeto_id=so["id"], objeto_ico=self._ico("item", so["id"]), objeto_falta=so["falta"],
                              objeto=(f"Siguiente: {so['nombre']}" if so["falta"] is None else
                                      f"Ya puedes comprar {so['nombre']}" if so["falta"] == 0 else
                                      f"Siguiente: {so['nombre']} · te faltan {_miles(so['falta'])} de oro"))
        except Exception:
            pass
        return estado

    def _runas_riot(self, champ, rol):
        pos = {"top": "top", "jungla": "jungle", "mid": "middle", "bot": "bottom", "support": "utility"}.get(rol, "none")
        for p in (pos, "none"):
            try:
                pags = self.lcu.get(f"/lol-perks/v1/recommended-pages/champion/{champ}/position/{p}/map/11", timeout=5)
            except Exception:
                continue
            for pg in pags or []:
                ids = [x.get("id") if isinstance(x, dict) else x for x in pg.get("perks") or []]
                ids = [x for x in ids if x]
                if pg.get("primaryPerkStyleId") and len(ids) >= 9:
                    return {"primaryStyleId": pg["primaryPerkStyleId"], "subStyleId": pg.get("secondaryPerkStyleId"),
                            "selectedPerkIds": ids[:9]}
        return None

    def _poner_pagina(self, runas, nombre):
        cuerpo = {"name": nombre[:25], "primaryStyleId": runas["primaryStyleId"], "subStyleId": runas["subStyleId"],
                  "selectedPerkIds": runas["selectedPerkIds"], "current": True}
        try:
            for pg in self.lcu.get("/lol-perks/v1/pages") or []:
                if (pg.get("name") or "").startswith("Coach:") and pg.get("isDeletable", True) and pg.get("id"):
                    self.lcu.delete(f"/lol-perks/v1/pages/{pg['id']}")
        except Exception:
            pass
        try:
            self.lcu.post("/lol-perks/v1/pages", cuerpo)
            return True
        except Exception:
            pass
        try:   # sin espacio para otra pagina: se usa la pagina actual
            cur = self.lcu.get("/lol-perks/v1/currentpage")
            if cur and cur.get("id") and cur.get("isEditable", True):
                self.lcu.put(f"/lol-perks/v1/pages/{cur['id']}", {**cur, **cuerpo, "id": cur["id"]})
                return True
        except Exception:
            pass
        return False

    def _poner_hechizos(self, hechizos):
        """Pone los 2 hechizos de invocador en la selección de campeón. El que ya tengas puesto (por ejemplo Flash)
        se queda en su misma tecla, D o F; solo cambia el otro. Devuelve True si ya quedaron puestos."""
        hs = [int(h) for h in hechizos or [] if h]
        if len(hs) != 2 or hs[0] == hs[1]:
            return False
        ses = self.lcu.get("/lol-champ-select/v1/session", timeout=5)
        celda = ses.get("localPlayerCellId")
        yo = next((m for m in ses.get("myTeam") or [] if m.get("cellId") == celda), None)
        if not yo:
            return False
        actual = [yo.get("spell1Id"), yo.get("spell2Id")]
        if sorted(actual) == sorted(hs):
            return True
        nuevo = [h if h in hs else None for h in actual]              # lo que ya coincide no se mueve de tecla
        resto = [h for h in hs if h not in nuevo]
        nuevo = [h if h is not None else resto.pop(0) for h in nuevo]
        self.lcu.patch("/lol-champ-select/v1/session/my-selection", {"spell1Id": nuevo[0], "spell2Id": nuevo[1]})
        return True

    def _poner_items(self, champ, nombre, build, titulo="Build fijada (Coach LoL)"):
        if not self.summoner_id:
            return False
        uid = f"coach-lol-{champ}"
        try:
            ruta = f"/lol-item-sets/v1/item-sets/{self.summoner_id}/sets"
            data = self.lcu.get(ruta) or {}
            sets = [x for x in data.get("itemSets") or [] if x.get("uid") != uid]
            bloques = []
            if build.get("inicio"):
                bloques.append({"type": "Inicio", "items": [{"id": str(i), "count": 1} for i in build["inicio"]]})
            bloques.append({"type": titulo,
                            "items": [{"id": str(i), "count": 1} for i in build["orden"]]})
            sets.append({"associatedChampions": [champ], "associatedMaps": [11], "blocks": bloques, "map": "any",
                         "mode": "any", "preferredItemSlots": [], "sortrank": 0, "startedFrom": "blank",
                         "title": f"Coach: {nombre}", "type": "custom", "uid": uid})
            data["itemSets"] = sets
            self.lcu.put(ruta, data)
            return True
        except Exception:
            return False

    # -- pantalla de carga: plan de partida (los nombres ya son visibles)
    def _carga(self):
        if self.carga is not None:
            return
        self.carga = {}
        yo_eq, rival, sus_campeones, sus_jugadores = None, None, [], []
        mios, suyos, su_lado, ses = [], [], None, None
        try:
            ses = self.lcu.get("/lol-gameflow/v1/session", timeout=5)
            gd = ses.get("gameData") or {}
            self.cola_partida = {"id": (gd.get("queue") or {}).get("id"), "modo": (gd.get("queue") or {}).get("gameMode"),
                                 "mapa": (gd.get("queue") or {}).get("mapId")}
            if ((gd.get("queue") or {}).get("gameMode") or "").upper() == "PRACTICETOOL":
                return
            if not es_grieta(self.cola_partida):
                return                 # ARAM y otros modos: sin plan de partida ni jungla rival
            t1, t2 = gd.get("teamOne") or [], gd.get("teamTwo") or []
            for eq, otro, lado_otro in ((t1, t2, 200), (t2, t1, 100)):
                yo = next((x for x in eq if x.get("puuid") and x.get("puuid") == self.puuid), None)
                if yo:
                    yo_eq = yo
                    su_lado = lado_otro
                    sus_campeones = [x.get("championId") for x in otro if x.get("championId")]
                    sus_jugadores = [{"puuid": x.get("puuid"), "championId": x.get("championId")} for x in otro
                                     if x.get("puuid") and x.get("championId")]
                    mios = [x for x in eq if x is not yo]
                    suyos = list(otro)
                    pos = (yo.get("selectedPosition") or "").lower()
                    if pos and pos not in ("none", "fill"):
                        rival = next((x for x in otro if (x.get("selectedPosition") or "").lower() == pos), None)
                        self.rol_partida = POSICION_LCU.get(pos, self.rol_partida)
                    break
            # diagnostico: que trae la sesion en la carga (una copia en datos/, que no se publica, y una linea en el log)
            log(f"Carga: {len(t1)}+{len(t2)} jugadores en la sesión; te encontré: {'sí' if yo_eq else 'no'}; "
                f"rivales con puuid: {sum(1 for x in suyos if x.get('puuid'))}/{len(suyos)}; "
                f"posición: {(yo_eq or {}).get('selectedPosition') or '-'}; rival: {self.rec.campeon((rival or {}).get('championId')) or '-'}.")
            arch = DATOS / "sesion_muestra.json"
            if not arch.exists():
                arch.write_text(json.dumps({"puuid_yo": self.puuid, "sesion": ses}, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log(f"Carga: no pude leer la sesión ({type(e).__name__}: {e}).")
        plan = plan_actual(self.alm)
        mision = self.mision_partida or mision_para_rol(plan, self.rol_partida)
        self.mision_partida = mision
        estado = {"modo": "carga", "regla": (mision or {}).get("regla", ""), "checklist": []}
        pp = plan_partida(self.alm, plan, self.rol_partida)
        if pp.get("lo_mas_importante"):
            estado["plan"] = pp["lo_mas_importante"]["texto"]
            estado["plan_fase"] = pp["lo_mas_importante"].get("fase") or ""
        if self.rol_partida == "support":
            estado["checklist"].append("Objeto de support antes de salir de base.")
        if (mision or {}).get("como"):
            estado["checklist"].append(mision["como"][0])
        if rival and rival.get("championId"):
            cid = rival["championId"]
            nombre = self.rec.campeon(cid)
            estado["rival"] = nombre
            estado["rival_icono"] = self._ico("campeon", cid)
            info = []
            con = self.rec.consejos(cid)
            if con:
                info.append(f"Hace daño {con['dano']}.")
                estado["consejos"] = con["contra"]
            estado["rival_info"] = info          # lo de su historial llega aparte (_scout), sin parar el bucle
            with self.alm.lock:
                h = historial_contra(list(self.alm.d["partidas"].values()), cid)
            if h:
                estado["historial"] = texto_historial(h, nombre)
                estado["historial_malo"] = h["d"] > h["v"]
            self.rival_partida = cid
            nm = nota_matchup(self.alm, (yo_eq or {}).get("championId"), cid)
            if nm:
                estado["nota_matchup"] = f"Tu nota contra {nombre}: {nm['texto']}"
        self._con_dano(estado, sus_campeones, (yo_eq or {}).get("championId"))
        dtx = (self.build_partida or {}).get("defensa_txt")
        if dtx and estado.get("dano_txt"):
            estado["dano_txt"] = estado["dano_txt"].split(" Por ejemplo:")[0].split(" después de tu primer")[0].rstrip(":") + ". " + dtx
            estado["dano_iconos"] = []
        def fila(x, enemigo):
            cid = x.get("championId")
            return {"puuid": x.get("puuid"), "cid": cid, "nombre": self.rec.campeon(cid) or "?",
                    "ico": self._ico("campeon", cid), "pos": POS_CORTA.get((x.get("selectedPosition") or "").upper(), ""),
                    "enemigo": enemigo, "cargando": bool(x.get("puuid")), "chips": [],
                    "smite": SMITE in (x.get("spell1Id"), x.get("spell2Id"))}
        orden = {"top": 0, "jungla": 1, "mid": 2, "adc": 3, "support": 4, "": 5}
        estado["equipos"] = {"rivales": sorted([fila(x, True) for x in suyos if x.get("championId")], key=lambda f: orden[f["pos"]]),
                             "aliados": sorted([fila(x, False) for x in mios if x.get("championId")], key=lambda f: orden[f["pos"]])}
        self.carga = estado
        self._ventana(json.loads(json.dumps(estado, ensure_ascii=False)))     # los hilos de _scout tocan estado
        if any(f["puuid"] for f in estado["equipos"]["rivales"] + estado["equipos"]["aliados"]):
            self._scout(estado, rival, su_lado, ses)

    # -- partida en vivo
    def _guardar_entreno(self, cs, campeon):
        with self.alm.lock:
            meta = meta_entreno(self.alm)
            self.alm.d.setdefault("entrenamientos", []).append(
                {"ts": int(time.time() * 1000), "cs10": cs, "campeon": campeon, "meta": meta})
            self.alm.guardar()
        log(f"Entrenamiento de CS guardado: ~{cs} CS en 10 minutos (meta {meta}).")

    def _en_vivo(self):
        try:
            data = partida_en_vivo()
        except Exception:
            return
        if not self.oculta_partida and d3d_pantalla_completa():
            # Windows dice que el juego esta en pantalla completa exclusiva: nada encima, toda la partida
            self.oculta_partida, self.oculta_motivo = True, "windows"
            log("Windows indica que el juego está en pantalla completa: la ventanita se oculta durante "
                "la partida. Para verla jugando, pon el juego en 'Sin bordes'.")
            self._ventana({"modo": "oculto"})
        elif self.oculta_partida and self.oculta_motivo == "ajustes" and time.time() - self._t_modo > 15:
            # si cambiaste a 'Sin bordes' en plena partida, la ventanita vuelve sin esperar a la siguiente
            self._t_modo = time.time()
            modo, fuente = modo_pantalla(self.lcu)
            if modo in (1, 2) and not d3d_pantalla_completa():
                self.pantalla, self.pantalla_fuente = modo, fuente
                self.oculta_partida, self.oculta_motivo = False, ""
                log(f"Ahora el juego está en '{NOMBRE_MODO[modo]}' ({fuente}): la ventanita vuelve.")
        if ((data.get("gameData") or {}).get("gameMode") or "").upper() == "PRACTICETOOL":
            if not isinstance(self.envivo, EntrenoVivo):
                self.envivo = EntrenoVivo(meta_entreno(self.alm))
            estado = self.envivo.actualizar(data, self._guardar_entreno)
            if estado:
                self._ventana(estado)
            return
        if self.envivo is None:
            gd = data.get("gameData") or {}
            if not es_grieta({"modo": gd.get("gameMode"), "mapa": gd.get("mapNumber")}):
                self.mision_partida, self.rol_partida = None, ""      # ARAM y otros modos: sin mision
            elif not self.mision_partida:
                plan = plan_actual(self.alm)
                self.mision_partida = mision_para_rol(plan, self.rol_partida)
            rv = self.rival_partida
            self._hud_reto, self._hud_base, self._hud_guia = None, None, None
            self.envivo = EnVivo(self.mision_partida, self.rol_partida,
                                 ((self.alm.d.get("jugador") or {}).get("nombre") or ""),
                                 [self.rec.campeon(rv), (getattr(self.rec, "alias", {}) or {}).get(str(rv))] if rv else None)
        estado = self._con_objeto(self.envivo.actualizar(data), data)
        estado = self._con_hud(self._con_baratija(self._con_objetivos(self._con_jungla(estado, data), data), data), data)
        t = float((data.get("gameData") or {}).get("gameTime") or 0)
        if self.carga and t < 75:
            return      # sigue mostrando el plan de partida durante el primer minuto
        if estado:
            self._ventana(estado)

    def _tick(self):
        try:
            fase = self.lcu.get("/lol-gameflow/v1/gameflow-phase", timeout=5)
            self._fallos_cliente = 0
        except Exception:
            # mientras juegas el cliente puede tardar en responder: un fallo suelto no es una desconexion
            self._fallos_cliente += 1
            if self._fallos_cliente < 3:
                return
            self.conectado = False
            self.fase = None
            self._ventana({"modo": "oculto"})
            log("Se perdió la conexión con el cliente. Reintentando...")
            return
        previa, self.fase = self.fase, fase
        if fase != previa:
            if (previa is not None and fase in ("Matchmaking", "ChampSelect")
                    and previa not in ("Matchmaking", "ChampSelect", "ReadyCheck")
                    and CONFIG["abrir_aviso_al_buscar_partida"] and sesion(self.alm)["parada"]):
                log("Buscas partida con el aviso de parada activo. Abriendo el aviso.")
                mostrar_panel(self.url, self, "aviso")
            if fase == "ChampSelect" or (fase in EN_JUEGO and previa not in EN_JUEGO):
                self.pantalla, self.pantalla_fuente = modo_pantalla(self.lcu)
            if fase in EN_JUEGO and previa not in EN_JUEGO:
                self.oculta_partida = self.pantalla == 0
                self.oculta_motivo = "ajustes" if self.oculta_partida else ""
                self._t_modo = time.time()
                if self.oculta_partida:
                    log(f"Modo de pantalla: Pantalla completa ({self.pantalla_fuente}). Durante la partida la "
                        "ventanita se oculta para no sacarte del juego. Para verla jugando, pon el juego en "
                        "'Sin bordes'.")
                    self._ventana({"modo": "oculto"})
                elif self.pantalla in (1, 2):
                    log(f"Modo de pantalla: {NOMBRE_MODO[self.pantalla]} ({self.pantalla_fuente}). "
                        "La ventanita se queda encima del juego.")
                else:
                    log("No pude leer el modo de pantalla del juego: la ventanita se muestra y se oculta sola "
                        "si Windows indica pantalla completa.")
            if fase not in EN_JUEGO:
                self.oculta_partida, self.oculta_motivo = False, ""
            if fase == "ChampSelect":
                self._sel_clave = None
                self._opcion_clic = None
                self._build_puesta = None
                self._hechizos_puestos = None
                self._runas_clave = None
                self._runas_txt = None
                self.carga = None
                self.rival_partida = None
                self.plan_jungla, self._aviso_jungla = None, False
                self._obj_avisados, self.cola_partida, self._ev_muestra = set(), None, False
                self._cola_sel = None
            if fase not in ("ChampSelect", "GameStart", "InProgress", "Reconnect"):
                self._ventana({"modo": "oculto"})
                self.envivo = None
                self.carga = None
            if fase in ("EndOfGame", "PreEndOfGame", "WaitingForStats", "None", "Lobby") and previa in (
                    "InProgress", "WaitingForStats", "PreEndOfGame", "EndOfGame", "Reconnect"):
                self._t_sync = 0
        if fase == "ChampSelect":
            self._seleccion()
            return
        if fase in ("InProgress", "Reconnect"):
            if self.carga is None and fase == "InProgress" and self.envivo is None:
                self._carga()
            self._en_vivo()
            return
        if fase == "GameStart":
            self._carga()
            return
        if time.time() - self._t_sync > 20:
            self._sincronizar()
        if time.time() - self._t_rango > 120:
            self._actualizar_rango()

    def bucle(self):
        avisado = False
        while True:
            try:
                if not self.conectado:
                    self._conectar()
                    if not self.conectado and not avisado:
                        log("Esperando a que abras el cliente de LoL...")
                        avisado = True
                    if self.conectado:
                        avisado = False
                else:
                    self._tick()
            except Exception as e:
                # un error del coach no corta la conexion (antes forzaba una reconexion y un reimporte
                # del historial en plena partida); se anota una vez por minuto como mucho
                msg = f"{type(e).__name__}: {e}"
                if msg != self._ultimo_error[0] or time.time() - self._ultimo_error[1] > 60:
                    log(f"Error: {msg}")
                    self._ultimo_error = (msg, time.time())
            if self.fase in ("InProgress", "Reconnect"):
                time.sleep(2)
            elif self.fase == "ChampSelect":
                time.sleep(3)
            else:
                time.sleep(5 if self.conectado else 10)


# =============================================================== SERVIDOR WEB
def crear_handler(coach):
    alm, rec = coach.alm, coach.rec
    html_path = RECURSOS / "dashboard.html"

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, tipo="application/json; charset=utf-8", cache=False):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json_body(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                return {}

        def do_GET(self):
            ruta = urllib.parse.urlparse(self.path).path
            if ruta in ("/", "/index.html"):
                return self._send(200, html_path.read_bytes(), "text/html; charset=utf-8")
            if ruta == "/fuente/archivo.woff2":
                return self._send(200, (RECURSOS / "fuente" / "archivo.woff2").read_bytes(), "font/woff2", cache=True)
            if ruta == "/api/ping":
                return self._send(200, {"app": "coach-lol", "v": VERSION, "huella": _HUELLA})
            if ruta == "/api/diagnostico":
                return self._send(200, {"texto": diagnostico_soporte(coach), "feedback": REPO_WEB + "/issues/new"})
            if ruta == "/api/estado":
                coach.ultimo_poll_pagina = time.time()
                ir, coach.ir_a = coach.ir_a, None
                ir = ir[0] if ir and time.time() - ir[1] < 120 else None
                plan = plan_actual(alm)
                with alm.lock:
                    lista = sorted(alm.d["partidas"].values(), key=lambda p: p.get("creacion") or 0, reverse=True)
                    resumen = []
                    for p in lista:
                        m = mision_de_partida(alm, p, plan)
                        resumen.append({"id": p["id"], "fecha": p["fecha"], "cola": p["cola"],
                                        "puesto": p.get("puesto"),
                                        "premios": next((x["premios"] for x in p.get("puestos") or [] if x.get("yo")), []),
                                        "victoria": p["victoria"], "duracion": p["duracion"],
                                        "campeon": p["yo"]["campeon"], "campeon_id": p["yo"]["campeon_id"],
                                        "rival": (p.get("rival") or {}).get("campeon"), "rol": p.get("rol", ""),
                                        "kda": p["yo"]["kda"], "nota": p["veredicto"]["nota"],
                                        "k": p["yo"].get("k"), "d": p["yo"].get("d"), "a": p["yo"].get("a"),
                                        "cs": p["yo"].get("cs"), "rival_id": (p.get("rival") or {}).get("campeon_id"),
                                        "items": [i for i in p["yo"].get("items") or []
                                                  if i.get("id") not in NO_BUILD][:6],
                                        "nivel": p["veredicto"]["nivel"], "st": resumen_stats(p),
                                        "mision_ok": (m["ok"] if m and m["aplica"] else None),
                                        "mision_registrada": bool(m and m["registrada"]),
                                        "animo": (alm.d["animo"].get(p["id"]) or {}).get("estado")})
                    jugador, rango = alm.d.get("jugador"), alm.d.get("rango")
                    ult = lista[:20]
                    cab = None
                    if ult:
                        dd = sum(p["yo"]["d"] for p in ult)
                        camp = Counter(p["yo"]["campeon_id"] for p in ult).most_common(1)[0][0]
                        pst = [p["puesto"] for p in ult if p.get("puesto")]
                        cab = {"n": len(ult), "campeon_id": camp, "campeon": rec.campeon(camp),
                               "wr": round(100 * sum(1 for p in ult if p["victoria"]) / len(ult)),
                               "kda": round(sum(p["yo"]["k"] + p["yo"]["a"] for p in ult) / max(dd, 1), 1),
                               "nota": round(sum(p["veredicto"]["nota"] for p in ult) / len(ult), 1),
                               "puesto": round(sum(pst) / len(pst), 1) if pst else None,
                               "total": len(lista),
                               "v_total": sum(1 for p in lista if p["victoria"]),
                               "wr_total": round(100 * sum(1 for p in lista if p["victoria"]) / len(lista))}
                        # (v_total y wr_total salen de la misma lista; un 49,5% se redondea a 50)
                    tema = alm.d.get("tema") or "oscuro"
                    hp = Hud._leer_pref()
                    hud_pref = dict(avisos_objetivos_cfg(hp), **{"opacidad": float(hp.get("opacidad", CONFIG.get("hud_opacidad", 0.9))),
                                "mini": bool(hp.get("mini", True)), "escala": float(hp.get("escala") or 1.0),
                                "lugar": hp.get("lugar") or ("a mano" if "x" in hp else "izq-centro"),
                                "disponible": bool(coach.ventana) and bool(CONFIG.get("hud_partida", True))})
                    fijados = []
                    for cid, f in (alm.d.get("fijados") or {}).items():
                        entradas = ([("", f["general"])] if f.get("general") else []) + list((f.get("vs") or {}).items())
                        for rid, x in entradas:
                            fijados.append({"campeon": rec.campeon(cid), "campeon_id": int(cid),
                                            "rival": rec.campeon(rid) if rid else None, "rival_id": int(rid) if rid else None,
                                            "origen": x.get("origen", ""), "runas": rec.texto_runas(x.get("runas")),
                                            "runas_det": rec.detalle_runas(x.get("runas")),
                                            "items": [{"id": i, "nombre": rec.item(i)}
                                                      for i in ((x.get("build") or {}).get("orden") or [])]})
                retos_todos = retos_estado(alm, rec)["retos"]
                return self._send(200, {
                    "conectado": coach.conectado, "fase": coach.fase,
                    "fase_texto": FASES.get(coach.fase or "", "Conectado") if coach.conectado else "Cliente cerrado",
                    "jugador": jugador, "rango": rango, "sesion": sesion(alm), "plan": plan,
                    "partidas": resumen, "ultima_nueva": coach.ultima_nueva, "fijados": fijados,
                    "revision": stats_revision(alm), "entreno": estado_entreno(alm, plan),
                    "avance": avance(alm), "cabecera": cab, "tema": tema, "hud": hud_pref, "version": VERSION,
                    "ir": ir,
                    "actualizacion": {"novedades": novedades_actualizacion(), "pendiente": _ACTU["nueva"],
                                      "notas": _ACTU["notas"], "aplicando": _ACTU["aplicando"], "error": _ACTU["error"]},
                    "notas": {"bien": NOTA_BIEN, "regular": NOTA_REGULAR},
                    "ia": {"activa": bool(ia_config()["clave"] or ia_config()["respaldo"]["clave"]),
                           "gemini": bool(ia_config()["clave"]),
                           "respaldo": IA_OTROS.get(ia_config()["respaldo"]["prov"], ("",))[0] if ia_config()["respaldo"]["clave"] else "",
                           "respaldo_fin": ia_config()["respaldo"]["clave"][-4:] if ia_config()["respaldo"]["clave"] else "",
                           "gemini_fin": ia_config()["clave"][-4:] if ia_config()["clave"] else "",
                           "modelo": ia_config()["modelo"] or _IA_MODELOS["ok"] or ""},
                    "retos_activos": [r for r in retos_todos if r["activo"]],
                    # retos superados (activos o no) + tareas superadas: el dashboard lanza confeti si sube
                    "logros": sum(r.get("superados") or 0 for r in retos_todos) + ((avance(alm) or {}).get("n_superadas") or 0),
                    "build_info": coach.build_info if coach.fase in EN_JUEGO + ("ChampSelect",) else None,
                    "draft": coach.draft if coach.fase == "ChampSelect" else None,
                    "ahora": siguiente_paso(alm, plan, sesion(alm)), "proxima": plan_partida(alm, plan),
                })
            if ruta == "/api/draft":
                return self._send(200, {"fase": coach.fase, "draft": coach.draft if coach.fase == "ChampSelect" else None})
            if ruta == "/api/novedades":
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                txt, mejor = "", ()
                for f in (DIR / "LEEME.txt", Path(getattr(sys, "_MEIPASS", DIR)) / "LEEME.txt"):
                    try:   # el del exe puede ser mas nuevo que el instalado al lado (o al reves)
                        t = f.read_text(encoding="utf-8-sig")
                        top = (novedades_leeme(t, maximo=1) or [{"v": "0"}])[0]["v"]
                        if _version_num(top) > mejor:
                            txt, mejor = t, _version_num(top)
                    except Exception:
                        pass
                desde = (q.get("desde") or [""])[0] or None
                lista = novedades_leeme(txt, desde=desde, hasta=VERSION, maximo=60 if desde else 6)
                return self._send(200, {"actual": VERSION, "desde": desde, "lista": lista})
            if ruta == "/api/retos":
                return self._send(200, retos_estado(alm, rec))
            if ruta == "/api/campeones":
                return self._send(200, {"pool": pool_campeones(alm)})
            if ruta == "/api/campeon":
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                try:
                    cid = int((q.get("c") or ["0"])[0])
                except ValueError:
                    cid = 0
                rol = (q.get("r") or [""])[0]
                f = ficha_campeon(alm, rec, cid, rol) if cid and rol in LOLA_LINEA else None
                return self._send(200 if f else 404, f or {"error": "Sin partidas con ese campeón en esa línea"})
            if ruta == "/api/progreso":
                out = progreso(alm)
                out["referencia"] = referencia_rango(alm)
                # las metas que se dibujan en las tendencias son las mismas con las que se pone el semaforo
                out["metas"] = {"muertes": CONFIG["muertes"][0], "cs10": CONFIG["cs10_niveles"][0], "oro14": 0,
                                "nota": NOTA_BIEN}
                out["fin_lineas"] = CONFIG["fin_fase_lineas_min"]
                with alm.lock:
                    ult = sorted([p for p in alm.d["partidas"].values() if p.get("muertes")],
                                 key=lambda p: p.get("creacion") or 0)[-30:]
                mapa = []
                for p in ult:
                    for m in p["muertes"]:
                        if m.get("x") is None:
                            continue
                        x, y = m["x"], m["y"]
                        if p.get("equipo") == 200:      # siempre con tu base abajo a la izquierda
                            x, y = 14870 - x, 14980 - y
                        mapa.append({"x": x, "y": y, "min": m["min"], "campeon": p["yo"]["campeon"],
                                     "fase": "temprana" if m["ts"] < CONFIG["fin_fase_lineas_min"] * 60000
                                     else "media" if m["ts"] < 25 * 60000 else "final"})
                out["mapa"] = mapa
                out["entreno"] = estado_entreno(alm, plan_actual(alm))
                return self._send(200, out)
            m = re.match(r"^/api/partida/(\d+)$", ruta)
            if m and m.group(1) not in _TIEMPO:
                try:                       # el minuto a minuto sale del archivo crudo (se calcula una vez)
                    crudo = json.loads((CRUDO / f"{m.group(1)}.json").read_text(encoding="utf-8"))
                    _TIEMPO[m.group(1)] = minuto_a_minuto(crudo.get("juego") or {}, crudo.get("timeline") or {},
                                                         crudo.get("puuid"), rec)
                except Exception:
                    _TIEMPO[m.group(1)] = None
            if m:
                plan = plan_actual(alm)
                with alm.lock:
                    p = alm.d["partidas"].get(m.group(1))
                    if not p:
                        return self._send(404, {"error": "no existe"})
                    out = {k: v for k, v in p.items() if k != "datos_h"}
                    out["animo"] = (alm.d["animo"].get(p["id"]) or {}).get("estado")
                    out["de_hoy"] = p.get("cuenta_anti") and dia_de(p.get("fin_ts") or 0) == dia_de(time.time() * 1000)
                    out["mision"] = mision_de_partida(alm, p, plan)
                    out["sesion"] = sesion_coaching(alm, p)
                    out["retos"] = retos_de_partida(alm, rec, p)
                    out["ia"] = (alm.d.get("ia") or {}).get(p["id"])
                    if p.get("obj_support"):
                        ts = [q["obj_support"]["t2_min"] for q in alm.d["partidas"].values()
                              if (q.get("obj_support") or {}).get("t2_min") and q["id"] != p["id"]]
                        if len(ts) >= 3:
                            out["obj_support"] = dict(p["obj_support"], media=_mmss(sum(ts) / len(ts) * 60000), n=len(ts))
                    out["runas_txt"] = rec.texto_runas(p.get("runas"))
                    out["runas_det"] = rec.detalle_runas(p.get("runas"))
                    revs = alm.d.get("revision") or {}
                    claves = muertes_clave(p)
                    out["muertes"] = [dict(m, sugerida=causa_sugerida(m, (p.get("datos_h") or {}).get("rival_id")), clave_rev=m["ts"] in claves,
                                           causa=(revs.get(f"{p['id']}:{m['ts']}") or {}).get("causa"),
                                           nota_rev=(revs.get(f"{p['id']}:{m['ts']}") or {}).get("nota"))
                                      for m in p.get("muertes") or []]
                    out["causas"] = {k: {"nombre": v["nombre"], "tipo": v["tipo"]} for k, v in CAUSAS.items()}
                    out["fin_lineas_ms"] = CONFIG["fin_fase_lineas_min"] * 60000
                    out["tiempo"] = _TIEMPO.get(p["id"])
                    rv_id = (p.get("rival") or {}).get("campeon_id")
                    nm = alm.d.get("matchups", {}).get(f"{p['yo']['campeon_id']}:{rv_id}") if rv_id else None
                    out["nota_matchup"] = (nm or {}).get("texto", "")
                    if p.get("build"):
                        out["build_items"] = [{"id": i, "nombre": rec.item(i)} for i in p["build"]["orden"]]
                    fij = (alm.d.get("fijados") or {}).get(str(p["yo"]["campeon_id"])) or {}
                    rid = str((p.get("rival") or {}).get("campeon_id"))
                    out["fijado"] = {"general": (fij.get("general") or {}).get("partida") == p["id"],
                                     "vs": ((fij.get("vs") or {}).get(rid) or {}).get("partida") == p["id"]}
                return self._send(200, out)
            m = re.match(r"^/img/(campeon|item|runa|perfil|splash)/(\d+)$", ruta)
            if m:
                data = rec.icono(m.group(1), m.group(2), coach.lcu)
                if data:
                    return self._send(200, data, "image/png", cache=True)
                return self._send(404, b"", "image/png")
            return self._send(404, {"error": "ruta"})

        def do_POST(self):
            ruta = urllib.parse.urlparse(self.path).path
            body = self._json_body()
            if ruta == "/api/salir":
                self._send(200, {"ok": True})
                log("Coach cerrado desde la ventana.")
                threading.Timer(0.4, lambda: os._exit(0)).start()
                return
            if ruta == "/api/actualizar":
                if coach.fase in EN_JUEGO + ("ChampSelect",):
                    return self._send(200, {"ok": False, "msg": "Actualiza cuando termine la partida."})
                ok, msg = actualizar_ahora()
                return self._send(200, {"ok": ok, "msg": msg})
            if ruta == "/api/abrir-feedback":
                webbrowser.open(REPO_WEB + "/issues/new")
                return self._send(200, {"ok": True})
            if ruta == "/api/sesion":
                ok = responder_sesion(alm, str(body.get("id", "")), body.get("hallazgo"), body.get("opcion"))
                return self._send(200 if ok else 400, {"ok": ok})
            if ruta == "/api/animo":
                gid, estado = str(body.get("id", "")), body.get("estado")
                if estado not in ("bien", "molesto", "tilt") or gid not in alm.d["partidas"]:
                    return self._send(400, {"error": "datos"})
                with alm.lock:
                    alm.d["animo"][gid] = {"estado": estado, "ts": int(time.time() * 1000)}
                    alm.guardar()
                return self._send(200, {"ok": True, "sesion": sesion(alm)})
            if ruta == "/api/fijar":
                gid, modo = str(body.get("id", "")), body.get("modo")
                with alm.lock:
                    p = alm.d["partidas"].get(gid)
                    if not p or modo not in ("general", "vs") or not (p.get("runas") or p.get("build")):
                        return self._send(400, {"ok": False})
                    cid = str(p["yo"]["campeon_id"])
                    rv = p.get("rival") or {}
                    entrada = {"runas": p.get("runas"), "build": p.get("build"), "partida": p["id"],
                               "origen": f"{p['fecha'][:10]}, {'victoria' if p['victoria'] else 'derrota'} "
                                         f"contra {rv.get('campeon', '-')}", "ts": int(time.time() * 1000)}
                    f = alm.d.setdefault("fijados", {}).setdefault(cid, {})
                    if modo == "general":
                        f["general"] = entrada
                    elif rv.get("campeon_id"):
                        f.setdefault("vs", {})[str(rv["campeon_id"])] = entrada
                    alm.guardar()
                coach._runas_clave = None
                return self._send(200, {"ok": True})
            if ruta == "/api/ia_clave":
                clave = str(body.get("clave", "")).strip()
                antes = ia_config()
                ia_guardar(clave, str(body.get("modelo", "")).strip())
                if not clave:
                    return self._send(200, {"ok": True, "msg": "Clave borrada. El coach sigue sin IA."})
                try:
                    _, modelo = _ia_pedir_gemini(ia_config(), "Responde solo: listo", "Responde con una sola palabra.")
                    return self._send(200, {"ok": True, "msg": "Clave guardada y comprobada: la IA ya funciona."})
                except RuntimeError as e:
                    ia_guardar(antes["clave"], antes["modelo"])      # una clave que no funciona no se guarda
                    return self._send(200, {"ok": False, "msg": str(e)})
            if ruta == "/api/ia_respaldo":
                prov, clave = str(body.get("prov", "")), str(body.get("clave", "")).strip()
                cfg = ia_config()
                if not clave:
                    ia_guardar(cfg["clave"], cfg["modelo"], {"prov": "", "clave": ""})
                    return self._send(200, {"ok": True, "msg": "Respaldo quitado."})
                if prov not in IA_OTROS:
                    return self._send(200, {"ok": False, "msg": "Elige Groq u OpenRouter."})
                try:
                    _, modelo = ia_pedir_abierto(prov, clave, "Responde solo: listo", "Responde con una sola palabra.")
                except RuntimeError as e:
                    return self._send(200, {"ok": False, "msg": str(e)})
                ia_guardar(cfg["clave"], cfg["modelo"], {"prov": prov, "clave": clave})
                return self._send(200, {"ok": True, "msg": "Respaldo guardado y comprobado."})
            if ruta == "/api/reto_auto":
                with alm.lock:
                    ps = sorted([p for p in alm.d["partidas"].values() if p.get("datos_h")], key=lambda p: p.get("creacion") or 0)
                if not ps:
                    return self._send(200, {"ok": False, "msg": "Aún no hay partidas para elegir un reto."})
                if retos_estado(alm, rec)["activos"] >= RETOS_MAX:
                    return self._send(200, {"ok": False, "msg": f"Ya tienes {RETOS_MAX} retos activos. Deja uno primero."})
                c = asignar_reto(alm, rec, ps[-1], forzar=True)
                return self._send(200, {"ok": bool(c), "msg": "" if c else "Ahora mismo no hay un reto que te convenga más que los que ya tienes."})
            if ruta == "/api/sesion_texto":
                ok, msg = ia_sesion_texto(alm, str(body.get("id", "")), str(body.get("clave", "")), str(body.get("texto", "")))
                return self._send(200, {"ok": ok, "msg": msg})
            if ruta == "/api/ia":
                gid, forzar = str(body.get("id", "")), bool(body.get("forzar"))
                if (IA_TRABAJOS.get(gid) or {}).get("estado") != "en_curso":
                    IA_TRABAJOS[gid] = {"estado": "en_curso", "msg": ""}
                    IA_PASO["txt"] = "Preparando los datos…"

                    def trabajo():
                        try:
                            r, err = ia_analizar(alm, rec, gid, forzar)
                            if err:
                                log(f"IA: {err}")
                            # al usuario, una frase clara; el detalle tecnico se queda en el log
                            msg = ("La IA no acepta tu clave. Revísala en la pantalla IA." if err and "clave" in err.lower()
                                   else "La IA está muy ocupada ahora mismo. Prueba otra vez en un minuto." if err else "")
                            IA_TRABAJOS[gid] = {"estado": "ok" if r else "error", "msg": msg}
                        except Exception as e:
                            IA_TRABAJOS[gid] = {"estado": "error", "msg": "No se pudo escribir el análisis. Prueba otra vez en un minuto."}
                            log(f"IA: falló el análisis de {gid} ({type(e).__name__}: {e}).")
                    threading.Thread(target=trabajo, daemon=True).start()
                return self._send(200, {"ok": True, "en_curso": True})
            if ruta == "/api/ia_estado":
                t = IA_TRABAJOS.get(str(body.get("id", ""))) or {"estado": "nada", "msg": ""}
                return self._send(200, dict(t, paso=IA_PASO["txt"]))
            if ruta == "/api/reto":
                clave, activar = str(body.get("clave", "")), bool(body.get("activar"))
                with alm.lock:
                    token = None if activar else guardar_deshacer("retos", clave, (alm.d.get("retos") or {}).get(clave))
                ok, msg = activar_reto(alm, rec, clave, activar)
                return self._send(200, {"ok": ok, "msg": msg, "deshacer": token if ok else None})
            if ruta == "/api/hud":
                # ajustes de las tarjetas de partida y botones "Probar" / "Colocar"
                if not coach.ventana and body.get("accion"):
                    return self._send(200, {"ok": False, "msg": "La ventanita del coach no está abierta."})
                cambios = {}
                try:
                    if "opacidad" in body:
                        cambios["opacidad"] = max(0.45, min(1.0, float(body["opacidad"])))
                    if "escala" in body:
                        cambios["escala"] = max(0.85, min(1.5, float(body["escala"])))
                except (TypeError, ValueError):
                    return self._send(200, {"ok": False, "msg": "Valor no válido."})
                if "mini" in body:
                    cambios["mini"] = bool(body["mini"])
                if body.get("lugar") in ("izq-arriba", "izq-centro", "izq-abajo", "der-arriba", "der-centro", "der-abajo"):
                    cambios["lugar"] = body["lugar"]
                for k in ("timers", "sonido", "equipo", "baratija"):
                    if k in body:
                        cambios[k] = bool(body[k])
                if isinstance(body.get("avisos"), dict):
                    cambios["avisos"] = {k: bool(body["avisos"].get(k, True)) for k in ("dragon", "larvas", "heraldo", "baron")}
                if body.get("antelacion") in (30, 45, 60, 90):
                    cambios["antelacion"] = int(body["antelacion"])
                if cambios and coach.ventana:
                    coach.ventana.orden("hud_cfg", cambios)
                elif cambios:                     # sin ventanita: se guarda igual para la proxima vez
                    try:
                        f = DATOS / "ventana.json"
                        pv = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
                        hp = dict(pv.get("hud") if isinstance(pv.get("hud"), dict) else {}, **cambios)
                        if "lugar" in cambios:
                            hp.pop("x", None), hp.pop("y", None)
                        pv["hud"] = hp
                        f.write_text(json.dumps(pv), encoding="utf-8")
                    except Exception as e:
                        log(f"Ajustes de las tarjetas: no pude guardarlos ({type(e).__name__}: {e}).")
                        return self._send(200, {"ok": False, "msg": "No pude guardar el cambio. Prueba otra vez."})
                if body.get("accion") in ("probar", "mover"):
                    coach.ventana.orden("hud_probar", {"mover": body["accion"] == "mover"})
                return self._send(200, {"ok": True})
            if ruta == "/api/tema":
                with alm.lock:
                    alm.d["tema"] = "oscuro" if body.get("tema") == "oscuro" else "claro"
                    alm.guardar()
                coach.tema_cambiado()
                return self._send(200, {"ok": True})
            if ruta == "/api/opcion":
                coach.elegir_opcion(str(body.get("clave", "")))
                return self._send(200, {"ok": True})
            if ruta == "/api/deshacer":
                token = str(body.get("token", ""))
                ok, msg = deshacer(alm, token)
                return self._send(200, {"ok": ok, "msg": msg, "reintentar": not ok and token in _DESHACER})
            if ruta == "/api/desfijar":
                cid, rid = str(body.get("campeon_id", "")), body.get("rival_id")
                with alm.lock:
                    f = (alm.d.get("fijados") or {}).get(cid)
                    token = guardar_deshacer("fijados", cid, f)
                    if f:
                        if rid:
                            (f.get("vs") or {}).pop(str(rid), None)
                        else:
                            f.pop("general", None)
                        if not f.get("general") and not f.get("vs"):
                            alm.d["fijados"].pop(cid, None)
                        alm.guardar()
                return self._send(200, {"ok": True, "deshacer": token})
            if ruta == "/api/matchup":
                # libreta de enfrentamientos: tu nota para la proxima vez contra ese rival
                try:
                    yo_c, rv_c = int(body.get("yo")), int(body.get("rival"))
                except (TypeError, ValueError):
                    return self._send(400, {"ok": False})
                texto = " ".join(str(body.get("texto") or "").split())[:280]
                with alm.lock:
                    mu = alm.d.setdefault("matchups", {})
                    if texto:
                        mu[f"{yo_c}:{rv_c}"] = {"texto": texto, "yo": yo_c, "rival": rv_c,
                                                "ts": int(time.time() * 1000)}
                    else:
                        mu.pop(f"{yo_c}:{rv_c}", None)
                    alm.guardar()
                return self._send(200, {"ok": True})
            if ruta == "/api/revision":
                gid, ts, causa = str(body.get("id", "")), body.get("ts"), body.get("causa")
                if gid not in alm.d["partidas"] or causa not in CAUSAS:
                    return self._send(400, {"ok": False})
                with alm.lock:
                    alm.d.setdefault("revision", {})[f"{gid}:{int(ts)}"] = {
                        "causa": causa, "nota": str(body.get("nota") or "")[:300], "ts": int(time.time() * 1000)}
                    alm.guardar()
                return self._send(200, {"ok": True, "revision": stats_revision(alm)})
            if ruta == "/api/repeticion":
                gid, seg = str(body.get("id", "")), float(body.get("segundo") or 0)
                if not coach.conectado:
                    return self._send(200, {"ok": False, "msg": "Abre el cliente de LoL para ver la repetición."})
                if coach.fase in ("ChampSelect", "GameStart", "InProgress", "Reconnect"):
                    return self._send(200, {"ok": False, "msg": "Estás en partida. Mira la repetición cuando termines."})
                try:
                    ok, msg = abrir_repeticion(coach.lcu, gid, seg)
                except Exception as e:
                    ok, msg = False, f"No pude abrir la repetición ({e})."
                return self._send(200, {"ok": ok, "msg": msg})
            if ruta == "/api/anti":
                with alm.lock:
                    x = dict(alm.d.get("anti") or {})
                    if "activa" in body:
                        x["activa"] = bool(body["activa"])
                    if body.get("derrotas") in (2, 3, 4):
                        x["derrotas"] = int(body["derrotas"])
                    alm.d["anti"] = x
                    alm.guardar()
                return self._send(200, {"ok": True})
            if ruta == "/api/aviso-visto":
                with alm.lock:
                    s = sesion(alm)
                    aviso = alm.d["avisos"].get(s["dia"])
                    if aviso:
                        aviso["visto_clave"] = s["clave_aviso"]
                        alm.guardar()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "ruta"})

    return H


_RELEVO = {"hubo": False}      # este coach ha sustituido a uno de otra version


def _huella_codigo():
    """Marca de los archivos de codigo (fecha y tamano): cambia al editar coach.py o dashboard.html
    aunque VERSION siga igual, para que un coach viejo en memoria no se quede sirviendo cosas antiguas."""
    partes = []
    for f in (DIR / "coach.py", RECURSOS / "dashboard.html"):
        try:
            st = f.stat()
            partes.append(f"{int(st.st_mtime)}-{st.st_size}")
        except Exception:
            partes.append("0")
    return "|".join(partes)


_HUELLA = _huella_codigo()


# =============================================================== ACTUALIZACIONES
# Al abrir, el coach mira version.json en GitHub; si hay una version mayor baja los archivos de codigo (nunca toca
# la carpeta datos), comprueba que coach.py compila, guarda copia de los actuales y se reinicia con lo nuevo.
REPO_RAW = "https://raw.githubusercontent.com/DuqueR/coach-lol-releases/main"
REPO_WEB = "https://github.com/DuqueR/coach-lol-releases"
_ACTU = {"nueva": None, "notas": "", "error": "", "info": None, "local": False, "aplicando": False}   # lo ve el dashboard


def _version_num(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except Exception:
        return (0,)


def _bajar(ruta, timeout=15):
    req = urllib.request.Request(f"{REPO_RAW}/{ruta}", headers={"User-Agent": "coach-lol", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def buscar_actualizacion():
    """Devuelve el contenido de version.json si hay una version mayor que la actual; si no, None."""
    if os.environ.get("COACH_SIN_ACTUALIZAR") or (DIR / ".git").exists():   # copia de desarrollo: no se pisa
        return None
    try:
        info = json.loads(_bajar("version.json", timeout=5).decode("utf-8"))
    except Exception as e:
        log(f"Actualizaciones: no pude consultar GitHub ({type(e).__name__}).")
        return None
    return info if _version_num(info.get("version")) > _version_num(VERSION) else None


def aplicar_actualizacion(info):
    """Baja todos los archivos a memoria, valida y solo entonces los escribe. True si quedo actualizado."""
    nuevos = {}
    try:
        for ruta in info.get("archivos") or []:
            if ".." in ruta or ruta.startswith(("/", "\\")) or ruta.split("/")[0].lower() == "datos":
                raise ValueError(f"ruta no permitida: {ruta}")
            nuevos[ruta] = _bajar(ruta)
        if "coach.py" not in nuevos:
            raise ValueError("version.json no incluye coach.py")
        compile(nuevos["coach.py"].decode("utf-8"), "coach.py", "exec")
    except Exception as e:
        _ACTU["error"] = f"No pude bajar la versión {info.get('version')}: {e}"
        log(f"Actualizaciones: {_ACTU['error']}")
        return False
    copia = DATOS / "respaldo" / f"v{VERSION}"
    for ruta, contenido in nuevos.items():
        destino = DIR / ruta
        try:
            if destino.exists():
                (copia / ruta).parent.mkdir(parents=True, exist_ok=True)
                (copia / ruta).write_bytes(destino.read_bytes())
            destino.parent.mkdir(parents=True, exist_ok=True)
            tmp = destino.with_name(destino.name + ".nuevo")
            tmp.write_bytes(contenido)
            os.replace(tmp, destino)
        except Exception as e:
            _ACTU["error"] = f"No pude escribir {ruta}: {e}"
            log(f"Actualizaciones: {_ACTU['error']}")
            return False
    try:
        (DATOS / "actualizado.json").write_text(json.dumps({"de": VERSION, "a": str(info.get("version")),
                                                            "notas": info.get("notas", ""), "ts": time.time()},
                                                           ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    log(f"Actualizado de v{VERSION} a v{info.get('version')}. Copia de la anterior en {copia}.")
    return True


def _reiniciar():
    env = {k: v for k, v in os.environ.items() if k != "COACH_DELEGADO"}
    args = [sys.executable] if CONGELADO else [sys.executable, str(DIR / "coach.py")]
    subprocess.Popen(args, cwd=str(DIR), env=env, close_fds=True)
    os._exit(0)


def version_en_disco():
    """Copia de desarrollo: si el coach.py de la carpeta es mas nuevo que el que corre, basta reiniciar."""
    try:
        m = re.search(r'^VERSION = "([^"]+)"', (DIR / "coach.py").read_text(encoding="utf-8"), re.M)
        if m and _version_num(m.group(1)) > _version_num(VERSION):
            notas = ""
            try:
                notas = json.loads((DIR / "version.json").read_text(encoding="utf-8")).get("notas", "")
            except Exception:
                pass
            return {"version": m.group(1), "notas": notas}
    except Exception:
        pass
    return None


def vigilar_actualizaciones(espera=60, cada=1200):
    """Con el coach abierto, mira cada 20 minutos si hay version nueva (en GitHub o, en la copia de desarrollo,
    en la carpeta). No la aplica sola: el dashboard enseña el boton Actualizar."""
    def bucle():
        time.sleep(espera)
        while True:
            try:
                dev = os.environ.get("COACH_SIN_ACTUALIZAR") or (DIR / ".git").exists()
                info = version_en_disco() if dev else buscar_actualizacion()
                if info and not _ACTU["aplicando"]:
                    if _ACTU["nueva"] != str(info.get("version")):
                        log(f"Actualizaciones: hay una versión nueva (v{info.get('version')}).")
                    _ACTU.update(nueva=str(info.get("version")), notas=info.get("notas", ""), info=info,
                                 local=bool(dev), error="")
            except Exception as e:
                log(f"Actualizaciones: no pude revisar ({type(e).__name__}).")
            time.sleep(cada)
    threading.Thread(target=bucle, daemon=True).start()


def actualizar_ahora():
    """Boton Actualizar: baja y aplica la version nueva (o solo reinicia en la copia de desarrollo).
    Devuelve (ok, mensaje); si ok, el coach se reinicia en un momento."""
    if _ACTU["aplicando"]:
        return True, "Ya se está actualizando."
    if not _ACTU["nueva"]:
        return False, "No hay ninguna versión nueva."
    _ACTU["aplicando"] = True
    if not _ACTU["local"]:
        info = _ACTU["info"] or buscar_actualizacion()
        if not info or not aplicar_actualizacion(info):
            _ACTU["aplicando"] = False
            return False, _ACTU["error"] or "No pude descargar la versión nueva. Inténtalo en un rato."
    else:
        try:
            (DATOS / "actualizado.json").write_text(json.dumps({"de": VERSION, "a": _ACTU["nueva"], "notas": _ACTU["notas"],
                                                                "ts": time.time()}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    log(f"Actualizando a v{_ACTU['nueva']} desde el dashboard: reinicio.")
    threading.Timer(0.8, _reiniciar).start()
    return True, f"Actualizando a la versión {_ACTU['nueva']}…"


NOV_ARREGLO = ("arregl", "bien contad", "sin mezclas", "un solo coach", "fallo", "error", "roto", "ya salta", "no se abr")
NOV_MEJORA = ("más ", "mejor", "pulid", "justo", "justa", "clara", "rápid", "limpi")


def novedades_leeme(txt, desde=None, hasta=None, maximo=6):
    """Las secciones "Lo nuevo en la vX: titulo" del LEEME, de la mas nueva a la mas vieja, con sus puntos.
    desde (excluida) y hasta (incluida) acotan por version. tipo: nuevo, mejora o arreglo."""
    out, cur = [], None
    lineas = txt.splitlines()
    subraya = re.compile(r"^\s*([-=])\1{3,}\s*$")
    for i, linea in enumerate(lineas):
        m = re.match(r"^Lo nuevo en la v([\d.]+)(?:\s*a\s*v[\d.]+)?\s*:?\s*(.*)$", linea.strip())
        if m:
            cur = {"v": m.group(1), "titulo": m.group(2).strip(), "puntos": []}
            out.append(cur)
            continue
        if subraya.match(linea):
            continue
        if i + 1 < len(lineas) and subraya.match(lineas[i + 1]):
            cur = None        # otra cabecera subrayada ("Versiones anteriores"...): se acabo la seccion
            continue
        if cur is None or not linea.strip():
            continue
        p = re.match(r"^(?:-|\d+\.)\s+(.*)$", linea)
        if p:
            cur["puntos"].append(p.group(1).strip())
        elif linea.startswith(" ") and cur["puntos"]:
            cur["puntos"][-1] += " " + linea.strip()
        elif not cur["puntos"] and not cur["titulo"]:
            cur["titulo"] = linea.strip()
        else:
            cur["puntos"].append(linea.strip())
    filas = []
    for x in out:
        v = _version_num(x["v"])
        if (desde and v <= _version_num(desde)) or (hasta and v > _version_num(hasta)):
            continue
        t = x["titulo"].lower()
        x["tipo"] = "arreglo" if any(k in t for k in NOV_ARREGLO) else "mejora" if any(k in t for k in NOV_MEJORA) else "nuevo"
        x["titulo"] = (x["titulo"][:1].upper() + x["titulo"][1:]) if x["titulo"] else f"Versión {x['v']}"
        filas.append(x)
    filas.sort(key=lambda x: _version_num(x["v"]), reverse=True)
    return filas[:maximo]


def novedades_actualizacion():
    """Lo que se muestra una vez tras actualizar (dura 1 dia)."""
    try:
        d = json.loads((DATOS / "actualizado.json").read_text(encoding="utf-8"))
        if d.get("a") == VERSION and time.time() - (d.get("ts") or 0) < 86400:
            return d
    except Exception:
        pass
    return None


def diagnostico_soporte(coach=None):
    """Texto para pegar al pedir ayuda: version, sistema y el final del log, sin claves."""
    import platform
    lineas = [f"Coach LoL v{VERSION} ({'exe' if CONGELADO else 'python'}) · huella {_HUELLA}",
              f"Windows {platform.version()} · Python {platform.python_version()}",
              f"Conectado al cliente: {bool(coach and coach.conectado)} · fase: {getattr(coach, 'fase', None)}"]
    try:
        log_txt = (DATOS / "coach.log").read_text(encoding="utf-8", errors="ignore").splitlines()[-60:]
    except Exception:
        log_txt = ["(sin log)"]
    claves = [ia_config()["clave"], ia_config()["respaldo"]["clave"]]
    texto = "\n".join(lineas + ["", "--- últimas líneas del log ---"] + log_txt)
    for c in claves:
        if c:
            texto = texto.replace(c, "[clave]")
    return re.sub(r"(AIza[\w-]{20,}|gsk_\w{20,}|sk-or-[\w-]{20,}|RGAPI-[\w-]{20,})", "[clave]", texto)


def guardar_build_partida(champ, build):
    """Guarda la build elegida en la seleccion: si el coach se reinicia en plena partida, sigue usando esa."""
    try:
        f = DATOS / "build_partida.json"
        nuevo = json.dumps({"champ": champ, "t": time.time(), "build": build}, ensure_ascii=False)
        viejo = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        if viejo.get("champ") != champ or viejo.get("build") != build or time.time() - float(viejo.get("t") or 0) > 600:
            f.write_text(nuevo, encoding="utf-8")
    except Exception:
        pass


def leer_build_partida(champ, horas=3):
    try:
        d = json.loads((DATOS / "build_partida.json").read_text(encoding="utf-8"))
        if (champ and d.get("champ") == champ and time.time() - float(d.get("t") or 0) < horas * 3600
                and (d.get("build") or {}).get("orden")):
            return d["build"]
    except Exception:
        pass
    return None


def _ventanas_del_panel():
    """Las ventanas del panel abiertas: Chrome o Edge en modo aplicacion con el titulo exacto del panel."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes
        u, hs = ctypes.windll.user32, []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cada(h, _):
            if u.IsWindowVisible(h):
                t, c = ctypes.create_unicode_buffer(200), ctypes.create_unicode_buffer(100)
                u.GetWindowTextW(h, t, 200)
                u.GetClassNameW(h, c, 100)
                if t.value == "Coach LoL" and c.value.startswith("Chrome_WidgetWin"):
                    hs.append(h)
            return True

        u.EnumWindows(cada, 0)
        return hs
    except Exception:
        return []


def _traer_al_frente(h):
    try:
        import ctypes
        u = ctypes.windll.user32
        if u.IsIconic(h):
            u.ShowWindow(h, 9)                       # SW_RESTORE
        u.keybd_event(0x12, 0, 0, 0)                 # un Alt suelto: Windows deja traer la ventana delante
        u.keybd_event(0x12, 0, 2, 0)
        u.SetForegroundWindow(h)
    except Exception:
        pass


def mostrar_panel(url, coach=None, destino=""):
    """Enseña el panel sin abrir otra ventana si ya hay una: la trae delante y le pide ir a 'destino'
    (lo recoge en su siguiente /api/estado). Solo si no hay ninguna abre una nueva."""
    hs = _ventanas_del_panel()
    if coach is not None:
        coach.ir_a = (destino, time.time()) if destino and (hs or time.time() - coach.ultimo_poll_pagina < 75) else None
    if hs:
        _traer_al_frente(hs[0])
        return
    if coach is not None and time.time() - coach.ultimo_poll_pagina < 75:
        return                                       # abierto en una pestaña normal del navegador
    abrir_app(url + (f"/#{destino}" if destino else ""))


_TIEMPO = {}                 # partida -> minuto a minuto (de su archivo crudo)


def _cerrar_ventanas_del_panel():
    """Cierra las ventanas del panel que dejo abiertas el coach anterior: seguirian mostrando la interfaz vieja.
    Solo las ventanas de aplicacion del navegador (Chrome o Edge) cuyo titulo es exactamente el del panel."""
    if os.name != "nt":
        return 0
    hs = _ventanas_del_panel()
    try:
        import ctypes
        for h in hs:
            ctypes.windll.user32.PostMessageW(h, 0x0010, 0, 0)          # WM_CLOSE
    except Exception:
        return 0
    return len(hs)


_MUTEX = {"h": None}


def _instancia_unica(espera=0.0):
    """Un solo coach a la vez (dos ponen dos ventanitas y aplican runas dos veces). Candado de Windows que se
    suelta solo al cerrarse el proceso; espera unos segundos por si el anterior se esta cerrando (reinicio)."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        if _MUTEX["h"] is None:
            k32.CreateMutexW.restype = ctypes.c_void_p
            k32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
            k32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
            _MUTEX["h"] = k32.CreateMutexW(None, False, r"Local\CoachLoL_unico")
        fin = time.time() + espera
        while True:
            r = k32.WaitForSingleObject(_MUTEX["h"], 300)
            if r in (0, 0x80):              # libre, o el anterior murio sin soltarlo
                return True
            if time.time() >= fin:
                return False
    except Exception as e:
        log(f"No pude comprobar si ya hay un coach abierto ({type(e).__name__}).")
        return True


def _puerto_libre(inicio):
    import socket
    for p in range(inicio, inicio + 20):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/ping", timeout=1) as r:
                d = json.loads(r.read().decode())
                if d.get("app") == "coach-lol":
                    if d.get("v") == VERSION and d.get("huella", _HUELLA) == _HUELLA:
                        return p, True
                    # hay abierto un coach de otra version: se le pide cerrarse y este ocupa su lugar
                    log("Había un coach de otra versión abierto: lo cierro y abro este.")
                    _RELEVO["hubo"] = True
                    try:
                        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{p}/api/salir", data=b"{}", method="POST",
                                               headers={"Content-Type": "application/json"}), timeout=2).read()
                    except Exception:
                        pass
                    time.sleep(1.5)
        except Exception:
            pass
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", p))
            s.close()
            return p, False
        except OSError:
            s.close()
    raise RuntimeError("No encontré un puerto libre")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=" * 56)
    print(f"  COACH LOL v{VERSION}  -  tu plan para salir de Hierro")
    print("=" * 56)
    if not _instancia_unica(0):
        # ya hay otro coach: si es esta misma version se trae su panel; si es otra, se le pide cerrarse y se espera
        puerto, ya_corre = _puerto_libre(CONFIG["puerto"])
        if ya_corre:
            mostrar_panel(f"http://127.0.0.1:{puerto}")
            return
        if not _instancia_unica(20):
            log("Ya hay un coach abierto que no se cierra: no abro otro.")
            return
    puerto, ya_corre = _puerto_libre(CONFIG["puerto"])
    url = f"http://127.0.0.1:{puerto}"
    if ya_corre:
        mostrar_panel(url)         # ya estaba abierto: se trae delante su ventana (o se abre si la cerraste)
        return
    info = buscar_actualizacion()
    if info:
        log(f"Hay una versión nueva del coach (v{info.get('version')}): la descargo.")
        if aplicar_actualizacion(info):
            _reiniciar()
        _ACTU["nueva"], _ACTU["notas"] = str(info.get("version")), info.get("notas", "")
    rec = Recursos()
    _REC["rec"] = rec
    alm = Almacen()
    n = alm.reanalizar(rec)
    if n:
        log(f"{n} partidas guardadas analizadas con el sistema nuevo.")
    ventana = None
    if CONFIG["ventana_mision"]:
        try:
            ventana = Ventana()
        except Exception as e:
            log(f"Sin ventana flotante ({e}). La misión se verá solo en el navegador.")
    coach = Coach(alm, rec, ventana)
    if ventana:
        ventana.al_elegir = coach.elegir_opcion
    coach.url = url
    srv = ThreadingHTTPServer(("127.0.0.1", puerto), crear_handler(coach))
    threading.Thread(target=coach.bucle, daemon=True).start()
    vigilar_actualizaciones()
    log(f"Dashboard en {url}")
    relevo = _RELEVO["hubo"] and _cerrar_ventanas_del_panel()
    if relevo:
        time.sleep(0.6)            # la ventana vieja se cierra antes de abrir la nueva
    if CONFIG["abrir_navegador_al_iniciar"]:
        if relevo:
            abrir_app(url)
        else:
            mostrar_panel(url)     # si quedo abierta una ventana del panel, se reconecta sola: no se abre otra
    try:
        if ventana:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            ventana.bucle()
        else:
            srv.serve_forever()
    except KeyboardInterrupt:
        log("Coach cerrado.")


def _arranque():
    """El .exe usa el coach.py de su carpeta si esta: asi actualizar es copiar archivos, sin rehacer el .exe."""
    f = DIR / "coach.py"
    if CONGELADO and not os.environ.get("COACH_DELEGADO") and f.exists():
        try:
            codigo = compile(f.read_text(encoding="utf-8"), str(f), "exec")
            os.environ["COACH_DELEGADO"] = "1"
        except Exception:
            codigo = None
        if codigo:
            try:
                exec(codigo, {"__name__": "__main__", "__file__": str(f)})
                return
            except ImportError as e:              # el coach.py nuevo pide algo que este .exe no trae
                log(f"El .exe es antiguo para este coach.py ({e}): ejecuta CREAR_EXE.bat. Uso la versión del .exe.")
    main()


if __name__ == "__main__":
    try:
        _arranque()
    except Exception:
        import traceback
        log("El coach se cerró por un error:\n" + traceback.format_exc())
        raise
