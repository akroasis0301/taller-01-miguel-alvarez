"""
verificar_casos.py - recalcula con Python cada respuesta esperada de datos/casos.csv.

Es la segunda fuente independiente: tu calculadora (o tus manos) escribieron
respuesta_esperada; aqui se recalcula desde la columna expresion_python y se
comparan. Si algo no coincide, el script termina con codigo 1.

Uso:  python verificar_casos.py
"""
import ast
import csv
import operator
import sys
from pathlib import Path

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def evaluar(expr: str) -> float:
    """Evalua solo numeros y + - * / (nada de eval() abierto)."""
    def _ev(n):
        if isinstance(n, ast.Expression):
            return _ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            return OPS[type(n.op)](_ev(n.left), _ev(n.right))
        raise ValueError(f"expresion no permitida: {expr!r}")
    return _ev(ast.parse(expr, mode="eval"))


def main() -> int:
    ruta = Path(__file__).resolve().parents[2] / "datos" / "casos.csv"
    with open(ruta, newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    errores = 0
    ids = [f["id"] for f in filas]
    if len(ids) != len(set(ids)):
        print("ERROR: ids duplicados")
        errores += 1
    for f in filas:
        calculado = evaluar(f["expresion_python"])
        esperado = int(f["respuesta_esperada"])
        ok = abs(calculado - esperado) < 1e-9 and float(calculado).is_integer()
        print(f"{f['id']:>3}  {f['expresion_python']:<16} = {calculado:<12g} esperado {esperado:<10} {'OK' if ok else 'ERROR'}")
        errores += 0 if ok else 1
    n_princ = sum(f["tipo"] == "principal" for f in filas)
    n_cont = sum(f["tipo"] == "contaminado" for f in filas)
    n_ext = sum(f["tipo"] == "contaminado_dificil" for f in filas)
    print(f"\nprincipales: {n_princ} (minimo 10)   contaminados: {n_cont} (exactamente 3 en la Parte 4.b)   extension de 4.b: {n_ext}")
    if n_princ < 10 or n_cont != 3:
        print("ERROR: conteo de casos fuera de lo que pide el taller")
        errores += 1
    print("\nTODO CORRECTO" if errores == 0 else f"\n{errores} PROBLEMA(S)")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
