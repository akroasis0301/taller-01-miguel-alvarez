# Taller 01 — Foundation Models: Comparación, Decodificación y Razonamiento

MMIA 6013 · IA Generativa y Agentes · Universidad San Francisco de Quito.

Tarea elegida: **problemas de aritmética con respuesta entera única** (10 casos principales + 3 contaminados para la
Parte 4.b). Instrucción y casos en inglés (GPT-2 solo conoce inglés, así su fallo en 0.c no puede atribuirse al idioma);
el informe va en español.

## Estructura

| Ruta | Qué es |
|---|---|
| `notebooks/parte0_gpt2.ipynb` … `parte4_razonamiento.ipynb` | Los cinco cuadernos del taller (Partes 0 a 4). Ya vienen ejecutados, con sus salidas guardadas |
| `src/taller_01_miguel_alvarez/tallerlib.py` | Utilidades compartidas: registro crudo, costos, casos, prompt base, GPT-2 |
| `src/taller_01_miguel_alvarez/verificar_casos.py` | Recalcula cada respuesta esperada con Python (segunda fuente independiente) |
| `src/taller_01_miguel_alvarez/verificar_entorno.py` | Revisa librerías, `.env` y Ollama, y hace 1 llamada mínima por modelo |
| `datos/casos.csv` | Los 13 casos con su respuesta esperada y la expresión que la recalcula |
| `fuentes/modelos/modelos-2026-1.json` | Tabla semestral de modelos (precios y fecha de verificación por fila) |
| `resultados/resultados.csv` y `.jsonl` | **Archivo crudo: una fila por llamada (1593 filas).** Las tablas del informe salen de aquí |
| `resultados/*.csv` | Tablas derivadas de cada parte |
| `figuras/` | Gráficas generadas por los cuadernos |
| `informe/Taller01_Informe.pdf` | Informe final |
| `pyproject.toml`, `uv.lock`, `requirements.txt` | Entorno reproducible (uv); `requirements.txt` es la misma lista fijada para quien use pip |

## Cómo correrlo (uv)

Requisitos: [uv](https://docs.astral.sh/uv/) y Python 3.13 (uv lo instala si falta).

```bash
uv sync                                   # crea .venv con las versiones exactas de uv.lock
uv run python -m taller_01_miguel_alvarez.verificar_casos   # debe terminar en TODO CORRECTO
```

Con pip en lugar de uv: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && pip install -e .`

### Abrir los cuadernos en VS Code

1. Abre **esta carpeta** (la raíz del repo, la que contiene `pyproject.toml`) como carpeta de trabajo. Si abres una
   carpeta superior, VS Code no encuentra el `.venv`.
2. Abre un cuaderno de `notebooks/` → arriba a la derecha **Select Kernel** → **Python Environments** → `.venv (Python 3.13.x)`.
   Si no aparece: `Cmd+Shift+P` → *Python: Select Interpreter* → *Enter interpreter path* → `.venv/bin/python`.
3. Ejecuta los cuadernos **en orden 0 → 4**.

### Credenciales (solo Partes 1 a 4)

```bash
cp .env.example .env      # y reemplaza AQUI PON TU API KEY por tu clave de OpenAI
```

Ninguna clave va en el código, en los cuadernos, en capturas ni en el repositorio. El `.env` está en `.gitignore`.
Las Partes 1–4 también aceptan la clave como variable de entorno `OPENAI_API_KEY`. Para el modelo local de la
Parte 2 (qwen3:1.7b) hace falta Ollama con `ollama pull qwen3:1.7b`. Comprobación rápida:
`uv run python -m taller_01_miguel_alvarez.verificar_entorno`.

## Importante antes de re-ejecutar

- Cada cuaderno **borra y vuelve a generar** las filas de su parte en `resultados/resultados.csv` (así no se duplican).
  Re-ejecutar vuelve a llamar a la API (≈ 0.03 USD en total) y **sobrescribe los resultados** que cita el informe;
  como los modelos no son 100 % deterministas, las cifras pueden variar un poco.
  Para solo revisar, no hace falta ejecutar nada: las salidas ya están guardadas en los cuadernos.
- La Parte 0 descarga GPT-2 (~500 MB) la primera vez y corre en CPU en 1–2 minutos.
- La fila `propietario_balanceado` (Anthropic) de la tabla semestral no se ejecutó (sin clave); queda documentado en el informe.
