"""
tallerlib.py - utilidades compartidas del Taller 01 (MMIA 6013, USFQ).
"""
from __future__ import annotations

import csv
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]      # raiz del repositorio (donde estan datos/, resultados/, .env)
RUTA_TABLA = RAIZ / "fuentes" / "modelos" / "modelos-2026-1.json"
RUTA_CASOS = RAIZ / "datos" / "casos.csv"
DIR_RESULTADOS = RAIZ / "resultados"
RUTA_CSV = DIR_RESULTADOS / "resultados.csv"
RUTA_JSONL = DIR_RESULTADOS / "resultados.jsonl"
DIR_FIGURAS = RAIZ / "figuras"

GPT2_ID = "openai-community/gpt2"

# Columnas del archivo crudo. Las nueve que pide el taller (modelo, parametros,
# corrida, tokens de entrada/salida/razonamiento, latencia, salida, acierto) mas
# costo, fecha y algunas de contexto que hacen reproducible cada fila.
COLUMNAS = [
    "fecha_utc",
    "parte",            # 0a, 0b, 0c, 1, 2a, 2b, 3, 4a, 4b ...
    "modelo_id",        # id de la fila de la tabla semestral
    "modelo",           # nombre real del modelo
    "backend",          # openai | ollama | transformers
    "parametros",       # JSON con lo que se envio
    "caso",             # id del caso (F1, M2...) o etiqueta del prefijo
    "variante",         # variante de prompt / sonda / nivel, segun la parte
    "corrida",          # 0, 1, 2...
    "tokens_entrada",
    "tokens_salida",    # total generado, razonamiento incluido
    "tokens_razonamiento",
    "latencia_s",
    "salida",
    "prediccion",       # numero extraido de la salida (solo si hay esperado)
    "esperado",
    "acierto",          # 1 / 0 / vacio si no se puntua
    "costo_usd",
    "error",            # mensaje literal si la llamada fallo
    "nota",
]

_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Registro crudo (una fila por llamada)
# --------------------------------------------------------------------------
def _completar(fila: dict) -> dict:
    f = {c: fila.get(c, "") for c in COLUMNAS}
    if not f["fecha_utc"]:
        f["fecha_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(f["parametros"], (dict, list)):
        f["parametros"] = json.dumps(f["parametros"], ensure_ascii=False, sort_keys=True)
    return f


def _asegurar_esquema() -> None:
    """Si resultados.csv tiene una cabecera vieja (otras columnas), lo reescribe
    desde el .jsonl con la cabecera actual. Se llama con _LOCK tomado."""
    if not RUTA_CSV.exists():
        return
    with open(RUTA_CSV, newline="", encoding="utf-8") as fh:
        cabecera = next(csv.reader(fh), [])
    if cabecera == COLUMNAS:
        return
    filas = leer_filas()
    with open(RUTA_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(filas)


def registrar(fila: dict) -> dict:
    """Agrega UNA fila a resultados.csv y resultados.jsonl. Seguro con hilos."""
    f = _completar(fila)
    DIR_RESULTADOS.mkdir(exist_ok=True)
    with _LOCK:
        _asegurar_esquema()
        nuevo = not RUTA_CSV.exists()
        with open(RUTA_CSV, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNAS)
            if nuevo:
                w.writeheader()
            w.writerow(f)
        with open(RUTA_JSONL, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(f, ensure_ascii=False) + "\n")
    return f


def leer_filas() -> list[dict]:
    if not RUTA_JSONL.exists():
        return []
    with open(RUTA_JSONL, encoding="utf-8") as fh:
        return [json.loads(linea) for linea in fh if linea.strip()]


def reemplazar_partes(partes: set[str]) -> int:
    """Borra del archivo crudo las filas de esas partes (para poder re-ejecutar
    un cuaderno sin duplicar). No toca las filas de otras partes.
    Devuelve cuantas filas se eliminaron."""
    filas = leer_filas()
    if not filas:
        return 0
    quedan = [f for f in filas if f["parte"] not in partes]
    borradas = len(filas) - len(quedan)
    if borradas:
        with _LOCK:
            with open(RUTA_CSV, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=COLUMNAS)
                w.writeheader()
                w.writerows(quedan)
            with open(RUTA_JSONL, "w", encoding="utf-8") as fh:
                for f in quedan:
                    fh.write(json.dumps(f, ensure_ascii=False) + "\n")
    return borradas


def reevaluar_filas(parte: str, extractores: dict | None = None) -> dict:
    """Recalcula prediccion y acierto de las filas de una parte a partir de la SALIDA CRUDA
    ya guardada, sin llamar a ninguna API. Sirve cuando se corrige el verificador (extractor):
    la respuesta del modelo no cambia, cambia como la leemos.
    - extractores: {variante: funcion(texto)}; sin entrada -> extraer_entero.
    - Solo toca filas sin error y con respuesta esperada.
    - Si el acierto cambia, la fila conserva el valor original en nota (auditable).
    Es idempotente: una segunda pasada no cambia nada. Devuelve un resumen."""
    extractores = extractores or {}
    filas = leer_filas()
    res = {"revisadas": 0, "cambiadas": 0, "de_0_a_1": 0, "de_1_a_0": 0}
    hubo_cambio = False
    for f in filas:
        if f["parte"] != parte or f["error"] or f["esperado"] in ("", None):
            continue
        res["revisadas"] += 1
        pred = (extractores.get(f["variante"]) or extraer_entero)(f["salida"])
        nuevo = int(pred is not None and pred == int(f["esperado"]))
        pred_txt = "" if pred is None else pred
        if str(pred_txt) != str(f["prediccion"]) or str(nuevo) != str(f["acierto"]):
            hubo_cambio = True
            viejo = f["acierto"]
            if str(nuevo) != str(viejo):
                res["cambiadas"] += 1
                res["de_0_a_1" if nuevo == 1 else "de_1_a_0"] += 1
                if "reevaluado" not in (f["nota"] or ""):
                    f["nota"] = (str(f["nota"] or "") + f" reevaluado: acierto_original={viejo}").strip()
            f["prediccion"], f["acierto"] = pred_txt, nuevo
    if hubo_cambio:
        with _LOCK:
            with open(RUTA_CSV, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=COLUMNAS)
                w.writeheader()
                w.writerows(filas)
            with open(RUTA_JSONL, "w", encoding="utf-8") as fh:
                for f in filas:
                    fh.write(json.dumps(f, ensure_ascii=False) + "\n")
    return res


# --------------------------------------------------------------------------
# Tabla semestral de modelos (precios SIEMPRE desde el archivo, con su fecha)
# --------------------------------------------------------------------------
def cargar_tabla() -> dict[str, dict]:
    if not RUTA_TABLA.exists():
        raise FileNotFoundError(f"No encuentro la tabla de modelos en {RUTA_TABLA}")
    with open(RUTA_TABLA, encoding="utf-8") as fh:
        datos = json.load(fh)
    return {m["id"]: m for m in datos["modelos"]}


def fila_modelo(modelo_id: str) -> dict:
    tabla = cargar_tabla()
    if modelo_id not in tabla:
        raise KeyError(f"modelo_id desconocido: {modelo_id!r}. Validos: {sorted(tabla)}")
    return tabla[modelo_id]


def costo_usd(modelo_id: str, tokens_entrada: int, tokens_salida: int) -> float:
    """(tokens de entrada x precio de entrada + tokens de salida x precio de salida) / 1e6.
    Los tokens de razonamiento ya vienen dentro de tokens_salida."""
    fila = fila_modelo(modelo_id)
    pe = fila["precio_entrada_usd_por_millon"]
    ps = fila["precio_salida_usd_por_millon"]
    if pe is None or ps is None:
        raise ValueError(f"La fila {modelo_id} no tiene precio")
    return (tokens_entrada * pe + tokens_salida * ps) / 1_000_000


# --------------------------------------------------------------------------
# Casos verificables y prompt base
# --------------------------------------------------------------------------
def cargar_casos(tipo: str | None = None) -> list[dict]:
    """Lee datos/casos.csv. tipo = 'principal' | 'contaminado' | None (todos)."""
    with open(RUTA_CASOS, newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    for f in filas:
        f["respuesta_esperada"] = int(f["respuesta_esperada"])
    if tipo:
        filas = [f for f in filas if f["tipo"] == tipo]
    return filas


# La instruccion EXACTA que se usa en las Partes 1 a 4 (y que la Parte 0.c le da a GPT-2).
# Va en INGLES a proposito: GPT-2 solo conoce ingles y asi su fallo en 0.c no se puede
# atribuir al idioma. El informe sigue en espanol.
INSTRUCCION = (
    "Solve the arithmetic problem. Reply with the final integer only: "
    "no thousands separators, no decimals, no explanation."
)


def construir_prompt(enunciado: str) -> str:
    return f"{INSTRUCCION}\n\nProblem: {enunciado}\nAnswer:"


_NUM = re.compile(r"-?\d{1,3}(?:[. ,\u00a0]\d{3})+(?:[.,]\d+)?|-?\d+(?:[.,]\d+)?")


def extraer_entero(texto: str):
    """Toma el ULTIMO numero del texto.
    - '5.021.952', '5,021,952' y '5 021 952' -> 5021952 (separadores de miles)
    - '731.0' -> 731 (decimal entero)
    - '413.41' -> 413.41 (decimal real: quedara como respuesta incorrecta)
    - sin numeros -> None"""
    if not texto:
        return None
    candidatos = _NUM.findall(texto)
    if not candidatos:
        return None
    s = candidatos[-1].replace("\u00a0", " ").strip()
    if re.fullmatch(r"-?\d{1,3}(?:[. ,]\d{3})+", s):
        return int(re.sub(r"[. ,]", "", s))
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    try:
        v = float(s.replace(",", "."))
    except ValueError:
        return None
    return int(v) if v.is_integer() else v


def primer_entero(texto: str):
    """Como extraer_entero, pero toma el PRIMER numero del texto (util para leer lo que va
    justo despues de una etiqueta como 'Answer:', aunque le sigan simbolos de LaTeX)."""
    m = _NUM.search(texto or "")
    return extraer_entero(m.group(0)) if m else None


# --------------------------------------------------------------------------
# Parte 0: GPT-2 local (transformers). torch/transformers se importan aqui
# dentro para que el resto del modulo funcione sin ellos.
# --------------------------------------------------------------------------
def versiones() -> dict:
    import numpy
    import torch
    import transformers

    return {
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "numpy": numpy.__version__,
    }


def cargar_gpt2():
    """Descarga (la primera vez, ~500 MB) y carga GPT-2 base en CPU."""
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(GPT2_ID)
    model = AutoModelForCausalLM.from_pretrained(GPT2_ID)
    model.eval()
    return tok, model


def logits_siguiente_token(tok, model, prefijo: str, con_bos: bool = False):
    """UN solo paso hacia adelante: devuelve los logits (numpy float64) del
    siguiente token despues de prefijo. Con con_bos=True se antepone el token
    <|endoftext|> (con el que GPT-2 se entreno para separar documentos)."""
    import torch

    enc = tok(prefijo, return_tensors="pt")
    ids = enc["input_ids"]
    if con_bos:
        bos = torch.tensor([[tok.bos_token_id]], dtype=ids.dtype)
        ids = torch.cat([bos, ids], dim=1)
    with torch.no_grad():
        salida = model(input_ids=ids, attention_mask=torch.ones_like(ids))
    return salida.logits[0, -1].double().numpy()


def generar(tok, model, prefijo: str, *, semilla: int = 0, max_new_tokens: int = 30, **gen_kwargs) -> dict:
    """Envuelve model.generate con semilla fijada y cronometro.
    gen_kwargs se pasan tal cual (do_sample, temperature, top_k, top_p...)."""
    import torch

    enc = tok(prefijo, return_tensors="pt")
    n_in = int(enc["input_ids"].shape[1])
    torch.manual_seed(semilla)
    t0 = time.perf_counter()
    with torch.no_grad():
        out = model.generate(
            **enc,
            max_new_tokens=max_new_tokens,
            pad_token_id=tok.eos_token_id,
            **gen_kwargs,
        )
    lat = time.perf_counter() - t0
    nuevos = out[0, n_in:].tolist()
    return {
        "ids": nuevos,
        "texto": tok.decode(nuevos),
        "tokens_entrada": n_in,
        "tokens_salida": len(nuevos),
        "latencia_s": round(lat, 4),
    }


def registrar_generacion_local(parte: str, prefijo_etiqueta: str, g: dict, params: dict,
                               corrida: int = 0, nota: str = "") -> dict:
    """Registra una generacion de GPT-2 en el archivo crudo, con costo cero."""
    return registrar({
        "parte": parte,
        "modelo_id": "base_local",
        "modelo": GPT2_ID,
        "backend": "transformers",
        "parametros": params,
        "caso": prefijo_etiqueta,
        "corrida": corrida,
        "tokens_entrada": g["tokens_entrada"],
        "tokens_salida": g["tokens_salida"],
        "tokens_razonamiento": 0,
        "latencia_s": g["latencia_s"],
        "salida": g["texto"],
        "costo_usd": 0.0,
        "nota": nota,
    })


def fraccion_ngramas_repetidos(ids: list[int], n: int = 4) -> float:
    """Medida simple de degeneracion: que fraccion de los n-gramas de la salida
    ya habia aparecido antes. Cerca de 0 = texto variado; cerca de 1 = bucle."""
    if len(ids) < n + 1:
        return 0.0
    vistos, repetidos, total = set(), 0, 0
    for i in range(len(ids) - n + 1):
        g = tuple(ids[i:i + n])
        total += 1
        if g in vistos:
            repetidos += 1
        vistos.add(g)
    return repetidos / total


# ==========================================================================
# Partes 1 a 4: llamadas a modelos (OpenAI por API, Ollama en local)
# ==========================================================================
import os  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from functools import lru_cache  # noqa: E402

MARCADOR_KEY = "AQUI PON TU API KEY"


# ---- Credenciales: se leen de variables de entorno o de un .env (excluido por .gitignore)
def cargar_env(ruta: Path | None = None) -> list[str]:
    """Lee un .env sencillo (CLAVE=valor) y pone en os.environ las variables que
    aun no estan definidas. Devuelve SOLO los nombres cargados, nunca los valores."""
    ruta = Path(ruta) if ruta else RAIZ / ".env"
    cargadas: list[str] = []
    if not ruta.exists():
        return cargadas
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        if linea.startswith("export "):
            linea = linea[len("export "):]
        nombre, _, valor = linea.partition("=")
        nombre, valor = nombre.strip(), valor.strip().strip('"').strip("'")
        if nombre and valor and nombre not in os.environ:
            os.environ[nombre] = valor
            cargadas.append(nombre)
    return cargadas


def hay_clave(nombre: str) -> bool:
    """True si la variable existe y no es el marcador de ejemplo. No imprime nada."""
    valor = os.environ.get(nombre, "").strip()
    return bool(valor) and valor != MARCADOR_KEY


_SECRETO = re.compile(r"(s[k]-[A-Za-z0-9_\-\*\.]{3,}|Bearer\s+[A-Za-z0-9_\-\.]+)")


def _limpiar_secretos(texto: str) -> str:
    """Los mensajes de error de autenticacion pueden traer la clave enmascarada.
    Nada que parezca una clave llega al archivo crudo."""
    return _SECRETO.sub("[clave-oculta]", texto)


def _describir_error(e: Exception) -> str:
    codigo = getattr(e, "status_code", None)
    mensaje = getattr(e, "message", None) or str(e)
    cuerpo = getattr(e, "body", None)
    txt = f"{type(e).__name__} | codigo={codigo} | mensaje={mensaje}"
    if cuerpo:
        txt += f" | cuerpo={cuerpo}"
    return _limpiar_secretos(txt)


# ---- OpenAI (Responses API)
_CLIENTE_OPENAI = None
_CLIENTE_LOCK = threading.Lock()


def _cliente_openai():
    global _CLIENTE_OPENAI
    with _CLIENTE_LOCK:
        if _CLIENTE_OPENAI is None:
            cargar_env()
            if not hay_clave("OPENAI_API_KEY"):
                raise RuntimeError(
                    "Falta OPENAI_API_KEY: ponla en un archivo .env en la raiz del repositorio "
                    "o exporta la variable de entorno (el valor de ejemplo no sirve)."
                )
            from openai import OpenAI

            _CLIENTE_OPENAI = OpenAI(max_retries=2, timeout=180.0)
        return _CLIENTE_OPENAI


def _llamar_openai(fila: dict, prompt: str, params: dict) -> dict:
    """params admitidos: temperature, top_p, max_output_tokens, effort
    (-> reasoning.effort), text_format (-> text.format, para JSON/esquema) y
    extra_body (parametros que el SDK no conoce, p. ej. top_k para la sonda 2.a)."""
    cliente = _cliente_openai()
    kw = {"model": fila["modelo"], "input": prompt}
    for k in ("temperature", "top_p", "max_output_tokens"):
        if params.get(k) is not None:
            kw[k] = params[k]
    if params.get("effort") is not None:
        kw["reasoning"] = {"effort": params["effort"]}
    if params.get("text_format") is not None:
        kw["text"] = {"format": params["text_format"]}
    if params.get("extra_body"):
        kw["extra_body"] = params["extra_body"]

    t0 = time.perf_counter()
    try:
        resp = cliente.responses.create(**kw)
    except Exception as e:  # el mensaje literal es parte del entregable de la Parte 2.a
        return {"error": _describir_error(e), "latencia_s": round(time.perf_counter() - t0, 4)}
    lat = time.perf_counter() - t0

    u = getattr(resp, "usage", None)
    det = getattr(u, "output_tokens_details", None)
    nota = ""
    estado = getattr(resp, "status", "completed")
    if estado != "completed":
        motivo = getattr(getattr(resp, "incomplete_details", None), "reason", None)
        nota = f"status={estado} motivo={motivo}"
    return {
        "salida": getattr(resp, "output_text", "") or "",
        "tokens_entrada": getattr(u, "input_tokens", None),
        "tokens_salida": getattr(u, "output_tokens", None),
        "tokens_razonamiento": getattr(det, "reasoning_tokens", None),
        "latencia_s": round(lat, 4),
        "nota": nota,
    }


# ---- Ollama (local, /api/chat)
_TOKENIZADORES_HF = {"qwen3:1.7b": "Qwen/Qwen3-1.7B", "gpt-oss:20b": "openai/gpt-oss-20b"}


@lru_cache(maxsize=4)
def _tokenizador_hf(nombre_hf: str):
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(nombre_hf)


def _contar_tokens_razonamiento(modelo_ollama: str, pensamiento: str, contenido: str, eval_count):
    """Tokens del campo thinking de /api/chat. Devuelve (n, metodo).
    Exacto con el tokenizador del modelo si esta disponible; si no, estimado
    repartiendo eval_count por caracteres (queda anotado en la columna nota)."""
    nombre_hf = _TOKENIZADORES_HF.get(modelo_ollama)
    if nombre_hf:
        try:
            tok = _tokenizador_hf(nombre_hf)
            return len(tok.encode(pensamiento, add_special_tokens=False)), "tokenizador_hf"
        except Exception:
            pass
    total = len(pensamiento) + len(contenido)
    if eval_count and total:
        return round(eval_count * len(pensamiento) / total), "proporcion_caracteres"
    return None, "sin_dato"


def _llamar_ollama(fila: dict, prompt: str, params: dict) -> dict:
    """params admitidos: temperature, top_p, top_k, num_predict, seed, think
    (bool o low|medium|high), format (esquema JSON), options_extra (dict libre,
    p. ej. una clave mal escrita para la sonda de control) y timeout_s."""
    import requests

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    if not host.startswith("http"):
        host = "http://" + host
    opciones = {k: params[k] for k in ("temperature", "top_p", "top_k", "num_predict", "seed")
                if params.get(k) is not None}
    opciones.update(params.get("options_extra") or {})
    cuerpo = {"model": fila["modelo"], "messages": [{"role": "user", "content": prompt}],
              "stream": False, "options": opciones}
    if params.get("think") is not None:
        cuerpo["think"] = params["think"]
    if params.get("format") is not None:
        cuerpo["format"] = params["format"]

    nota = ""
    t0 = time.perf_counter()
    try:
        r = requests.post(f"{host}/api/chat", json=cuerpo, timeout=params.get("timeout_s", 600))
        if r.status_code == 400 and "think" in cuerpo and "think" in r.text.lower():
            cuerpo.pop("think")
            nota = "think_no_soportado_por_el_modelo(reintento_sin_think);"
            r = requests.post(f"{host}/api/chat", json=cuerpo, timeout=params.get("timeout_s", 600))
    except Exception as e:
        return {"error": _describir_error(e), "latencia_s": round(time.perf_counter() - t0, 4)}
    lat = time.perf_counter() - t0
    if r.status_code != 200:
        return {"error": _limpiar_secretos(f"HTTP {r.status_code}: {r.text[:500]}"), "latencia_s": round(lat, 4)}

    d = r.json()
    msg = d.get("message") or {}
    contenido = msg.get("content") or ""
    pensamiento = msg.get("thinking") or ""
    tout = d.get("eval_count")
    razon = 0
    if pensamiento:
        razon, metodo = _contar_tokens_razonamiento(fila["modelo"], pensamiento, contenido, tout)
        nota += f"razonamiento_contado_por={metodo};"
    nota += f"ollama_total_s={(d.get('total_duration') or 0) / 1e9:.3f};carga_s={(d.get('load_duration') or 0) / 1e9:.3f}"
    return {
        "salida": contenido,
        "tokens_entrada": d.get("prompt_eval_count"),
        "tokens_salida": tout,
        "tokens_razonamiento": razon,
        "latencia_s": round(lat, 4),
        "nota": nota,
    }


_BACKENDS = {"openai": ("openai", _llamar_openai), "ollama": ("ollama", _llamar_ollama)}


# ---- Punto de entrada unico: llamar()
def es_solo_entero(texto: str) -> bool:
    """True si la salida es exactamente un entero (respeta el formato pedido)."""
    return bool(re.fullmatch(r"\s*-?\d+\s*", texto or ""))


def llamar(modelo_id: str, prompt: str, params: dict | None = None, *, parte: str, caso: str = "",
           variante: str = "", corrida: int = 0, esperado=None, extractor=None,
           registrar_fila: bool = True, nota: str = "") -> dict:
    """Llama al modelo modelo_id (id de la tabla semestral), calcula acierto y
    costo, y (por defecto) agrega UNA fila a resultados.csv/.jsonl. Devuelve la fila."""
    params = dict(params or {})
    fila_tabla = fila_modelo(modelo_id)
    proveedor = fila_tabla["proveedor"]
    if proveedor not in _BACKENDS:
        raise NotImplementedError(f"Sin backend para el proveedor {proveedor!r} (fila {modelo_id})")
    backend_nombre, fn = _BACKENDS[proveedor]
    res = fn(fila_tabla, prompt, params)

    error = res.get("error", "")
    tin, tout = res.get("tokens_entrada"), res.get("tokens_salida")
    salida = res.get("salida", "")
    costo = 0.0
    if not error and tin is not None and tout is not None:
        costo = costo_usd(modelo_id, tin, tout)

    prediccion, acierto = "", ""
    if esperado is not None:
        prediccion = (extractor or extraer_entero)(salida) if not error else None
        acierto = int(prediccion is not None and prediccion == esperado)
        prediccion = "" if prediccion is None else prediccion

    fila = {
        "parte": parte, "modelo_id": modelo_id, "modelo": fila_tabla["modelo"], "backend": backend_nombre,
        "parametros": params, "caso": caso, "variante": variante, "corrida": corrida,
        "tokens_entrada": "" if tin is None else tin,
        "tokens_salida": "" if tout is None else tout,
        "tokens_razonamiento": "" if res.get("tokens_razonamiento") is None else res["tokens_razonamiento"],
        "latencia_s": res.get("latencia_s", ""), "salida": salida, "prediccion": prediccion,
        "esperado": "" if esperado is None else esperado, "acierto": acierto,
        "costo_usd": round(costo, 8), "error": error,
        "nota": (nota + " " + res.get("nota", "")).strip(),
    }
    return registrar(fila) if registrar_fila else _completar(fila)


# ---- Lotes con freno de costo
def _clave_tarea(parte, modelo_id, params, caso, variante, corrida) -> tuple:
    return (str(parte), modelo_id, json.dumps(params or {}, sort_keys=True, ensure_ascii=False),
            str(caso), str(variante), str(corrida))


def correr_lote(tareas: list[dict], hilos: int = 1, max_usd: float | None = None,
                omitir_hechas: bool = False, mostrar: bool = True) -> list[dict]:
    """Ejecuta una lista de tareas (cada una: kwargs de llamar()).
    - hilos=1: secuencial (latencia limpia). hilos>1: en paralelo (barridos).
    - max_usd: si el costo acumulado de ESTE lote lo supera, se detiene y avisa.
    - omitir_hechas: salta las tareas que ya tienen una fila sin error (reanudar)."""
    hechas = set()
    if omitir_hechas:
        for f in leer_filas():
            if not f["error"]:
                hechas.add((str(f["parte"]), f["modelo_id"], f["parametros"], str(f["caso"]),
                            str(f["variante"]), str(f["corrida"])))
    pendientes = []
    for t in tareas:
        k = _clave_tarea(t["parte"], t["modelo_id"], t.get("params"), t.get("caso", ""),
                         t.get("variante", ""), t.get("corrida", 0))
        if k not in hechas:
            pendientes.append(t)
    if mostrar:
        print(f"Tareas: {len(tareas)} | ya hechas (omitidas): {len(tareas) - len(pendientes)} | por correr: {len(pendientes)}")

    acumulado = {"usd": 0.0, "parar": False}
    lock = threading.Lock()
    filas: list[dict] = []
    total = len(pendientes)

    def _una(i_t):
        i, t = i_t
        if acumulado["parar"]:
            return None
        kw = {k: v for k, v in t.items() if k not in ("modelo_id", "prompt", "params")}
        fila = llamar(t["modelo_id"], t["prompt"], t.get("params"), **kw)
        with lock:
            acumulado["usd"] += float(fila["costo_usd"] or 0)
            if max_usd is not None and acumulado["usd"] > max_usd and not acumulado["parar"]:
                acumulado["parar"] = True
                if mostrar:
                    print(f"*** FRENO: costo acumulado {acumulado['usd']:.4f} USD > max_usd={max_usd}. Se detiene el lote.")
            if mostrar:
                marca = "ERROR" if fila["error"] else ("ok" if fila["acierto"] == 1 else ("x" if fila["acierto"] == 0 else "-"))
                print(f"[{i + 1}/{total}] {fila['modelo_id']:<24} {str(fila['caso']):<4} {marca:<5} "
                      f"{fila['latencia_s']}s  {fila['costo_usd']} USD  -> {str(fila['salida'])[:40]!r}"
                      + (f"  {fila['error'][:120]}" if fila['error'] else ""))
        return fila

    if hilos <= 1:
        resultados = [_una(x) for x in enumerate(pendientes)]
    else:
        with ThreadPoolExecutor(max_workers=hilos) as ex:
            resultados = list(ex.map(_una, enumerate(pendientes)))
    filas = [f for f in resultados if f is not None]
    if mostrar:
        print(f"Listo: {len(filas)} llamadas registradas | costo del lote: {acumulado['usd']:.4f} USD")
    return filas


# ---- Configuracion de la Parte 1 (compartida con los scripts de las otras partes)
# Tres ranuras del taller: grande / economico / open-weight local.
# Sin clave de Anthropic, la ranura "grande" la cubre la fila de razonamiento de OpenAI
# (asi lo propone el enunciado en 'Alternativas para las tres ranuras').
RANURAS_PARTE1 = {
    "openai_razonamiento": "propietario grande (fila de razonamiento de OpenAI)",
    "propietario_economico": "propietario economico para produccion",
    "open_weight_pequeno": "open-weight local (Ollama)",
}
MODELOS_PARTE1 = list(RANURAS_PARTE1)
PARAMS_PARTE1 = {
    # La fila de razonamiento no admite temperature (se comprueba en 2.a): esfuerzo por defecto.
    "openai_razonamiento": {"max_output_tokens": 16000},
    "propietario_economico": {"temperature": 0, "max_output_tokens": 100},
    "open_weight_pequeno": {"temperature": 0, "think": False, "num_predict": 100},
}
