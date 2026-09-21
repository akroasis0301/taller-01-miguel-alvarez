"""
verificar_entorno.py - comprueba el entorno ANTES de gastar nada.

  python verificar_entorno.py                 # revisa todo y hace 1 llamada minima a cada modelo de la Parte 1
  python verificar_entorno.py --sin-llamadas  # solo revisa librerias, .env y Ollama

Nunca imprime el valor de una clave: solo si existe y si es utilizable.
"""
import argparse
import importlib
import os
import sys

import tallerlib as tl


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-llamadas", action="store_true")
    args = ap.parse_args()
    problemas = 0

    print(f"Python {sys.version.split()[0]}  |  carpeta de trabajo: {tl.RAIZ.name}/")
    print("\n1) Librerias")
    for m in ["numpy", "pandas", "matplotlib", "requests", "openai", "torch", "transformers"]:
        try:
            mod = importlib.import_module(m)
            print(f"   {m:<13} OK  {getattr(mod, '__version__', '')}")
        except Exception as e:
            print(f"   {m:<13} FALTA  ({type(e).__name__})  -> pip install {m}")
            problemas += 1

    print("\n2) Credenciales (solo se dice si existen, nunca su valor)")
    cargadas = tl.cargar_env()
    print(f"   .env en la raiz del repo: {'si' if (tl.RAIZ / '.env').exists() else 'NO'}   variables leidas de ahi: {cargadas}")
    ok_key = tl.hay_clave("OPENAI_API_KEY")
    print(f"   OPENAI_API_KEY utilizable: {'si' if ok_key else 'NO (falta o es el marcador de ejemplo)'}")
    problemas += 0 if ok_key else 1

    print("\n3) Ollama")
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    if not host.startswith("http"):
        host = "http://" + host
    try:
        import requests

        nombres = [m["name"] for m in requests.get(f"{host}/api/tags", timeout=5).json().get("models", [])]
        print(f"   servidor responde en {host}; modelos descargados: {nombres}")
        objetivo = tl.fila_modelo("open_weight_pequeno")["modelo"]
        if objetivo in nombres:
            print(f"   {objetivo}: presente")
        else:
            print(f"   {objetivo}: NO esta -> ollama pull {objetivo}")
            problemas += 1
    except Exception as e:
        print(f"   Ollama NO responde en {host} ({type(e).__name__}). Abre la app de Ollama o ejecuta: ollama serve")
        problemas += 1

    if not args.sin_llamadas:
        print("\n4) Llamada minima a cada modelo de la Parte 1 (no se guarda en resultados.csv)")
        prompt = tl.construir_prompt("Calculate 2 + 2")
        for mid in tl.MODELOS_PARTE1:
            try:
                fila = tl.llamar(mid, prompt, tl.PARAMS_PARTE1[mid], parte="smoke", caso="2+2",
                                 esperado=4, registrar_fila=False)
            except Exception as e:
                print(f"   {mid:<24} FALLO: {tl._limpiar_secretos(str(e))}")
                problemas += 1
                continue
            if fila["error"]:
                print(f"   {mid:<24} ERROR: {fila['error'][:300]}")
                problemas += 1
            else:
                print(f"   {mid:<24} salida={fila['salida'].strip()!r:<8} acierto={fila['acierto']} "
                      f"tokens(in/out/razon)={fila['tokens_entrada']}/{fila['tokens_salida']}/{fila['tokens_razonamiento']} "
                      f"latencia={fila['latencia_s']}s costo={fila['costo_usd']} USD")

    print("\nRESULTADO:", "todo listo" if problemas == 0 else f"{problemas} problema(s) por resolver")
    return 0 if problemas == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
