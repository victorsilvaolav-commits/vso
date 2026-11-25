"""Puente entre la página "Ajustar fotos" (Python dentro del navegador, con Pyodide) y
ajuste_combinado.py, que se usa TAL CUAL, sin cambiarle nada: las fotos salen igual que en el PC.

Para poner en la página una versión nueva del ajuste: copiar a esta carpeta (vso/ajuste/) los
archivos del programa que usa el ajuste (desde VSO App 1.4, 25-11-2026: ajuste_combinado.py,
estilo_lightroom.py y .npz, enfoque_vso.py, retoque_vso.py y los modelos .onnx/.tflite; la lista
está en js/ajustar-motor.js) y subirlos. El motor nativo (vso_motor_nativo.py y sus DLL) NO va:
son de Windows; sin él el ajuste usa su camino de respaldo, que da la misma foto.

Lo único distinto del PC: en el navegador no hay hilos ni procesos, así que lo que el script hace
"a la vez" (las franjas de cada foto y la medición de la serie) se hace de a uno. El resultado es
el mismo (el script ya dice que las franjas dan lo mismo hechas de una vez), solo que más lento.
"""
import argparse
import concurrent.futures
import json
import shutil
from concurrent.futures import Future
from pathlib import Path

from PIL import Image

import ajuste_combinado as ac


class _DeAUno:
    """Reemplaza al ThreadPoolExecutor del script: hace cada tarea en orden, sin hilos."""

    def __init__(self, *args, **kwargs):
        pass

    def map(self, funcion, *iterables):
        return [funcion(*a) for a in zip(*iterables)]

    def submit(self, funcion, *args, **kwargs):
        fut = Future()
        try:
            fut.set_result(funcion(*args, **kwargs))
        except BaseException as e:
            fut.set_exception(e)
        return fut

    def shutdown(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


ac.ThreadPoolExecutor = _DeAUno
ac._franjas = _DeAUno()
# estilo_lightroom.py y enfoque_vso.py (VSO 1.4) importan ThreadPoolExecutor adentro de sus funciones:
# se reemplaza también en concurrent.futures para que lo tomen de a uno.
concurrent.futures.ThreadPoolExecutor = _DeAUno


def _ajustes_por_defecto():
    """Los mismos ajustes que usa el .bat (los valores por defecto de main() del script): se leen
    del propio script, así si cambian allá cambian aquí."""
    class _Listo(Exception):
        pass

    original = argparse.ArgumentParser.parse_args
    leidos = {}

    def leer(self, args=None, namespace=None):
        leidos["args"] = original(self, ["foto.jpg"])
        raise _Listo

    argparse.ArgumentParser.parse_args = leer
    try:
        ac.main()
    except _Listo:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original
    args = leidos["args"]
    # Lo que main() completa justo después de leer las opciones (VSO 1.4): el ajuste es siempre el
    # estilo Lightroom y en la web no se elige ninguna foto para "Enfocar" (eso es del modo Pro).
    args.estilo = "lightroom"
    args.enfocar_claves = {}
    return args


ARGS = _ajustes_por_defecto()
ENTRADA = Path("/entrada")
_planes = {}


def _foto(clave):
    """Cada foto va en su propia carpeta (/entrada/<clave>/<nombre>): dos fotos con el mismo
    nombre no chocan, y la ajustada queda en /entrada/<clave>/combinadas/."""
    carpeta = ENTRADA / clave
    return next(p for p in carpeta.iterdir() if p.is_file())


def version():
    return ac.VERSION


def sin_detector():
    """Texto del problema si YuNet no se puede usar (o "" si está todo bien)."""
    return ac.falta_yunet() or ""


def planear(claves_json):
    """Balance por serie (fotos seguidas con la misma luz): se mide con todas las fotos del lote,
    igual que en el PC. Devuelve cuántas fotos quedaron con el balance de su serie."""
    claves = json.loads(claves_json)
    fotos = [(_foto(c), ENTRADA / c / ARGS.salida) for c in claves]
    plan = [None] * len(fotos)
    # Igual que main(): con el estilo Lightroom (VSO 1.4) no hay balance por serie
    if ARGS.serie != "no" and len(fotos) >= ac.SERIE_MINIMO and ARGS.estilo != "lightroom":
        try:
            plan = ac.plan_serie(fotos, 1, 0.88 * ARGS.fuerza, 0.6 * ARGS.fuerza * ARGS.contraste)
        except Exception:
            plan = [None] * len(fotos)  # una foto rara no impide ajustar las demás
    for c, p in zip(claves, plan):
        _planes[c] = p
    return sum(1 for p in plan if p)


def reducir(clave, megapixeles):
    """Modo rápido: achica la foto a unos 'megapixeles' antes de ajustarla (conserva el EXIF y el
    perfil de color, así el ajuste la trata igual). True si la achicó."""
    f = _foto(clave)
    with Image.open(f) as im:
        ancho, alto = im.size
        if ancho * alto <= megapixeles * 1e6:
            return False
        k = (megapixeles * 1e6 / (ancho * alto)) ** 0.5
        nuevo = (max(1, round(ancho * k)), max(1, round(alto * k)))
        exif, icc = im.info.get("exif"), im.info.get("icc_profile")
        im.draft("RGB", nuevo)  # JPG: se decodifica ya reducido (más rápido y con menos memoria)
        chica = im.convert("RGB") if im.mode not in ("RGB", "L") else im.copy()
    chica = chica.resize(nuevo, Image.LANCZOS)
    opciones = {"quality": 98, "subsampling": 0}
    if exif:
        opciones["exif"] = exif
    if icc:
        opciones["icc_profile"] = icc
    destino = f.with_suffix(".jpg")
    chica.save(destino, format="JPEG", **opciones)
    if destino != f:
        f.unlink()
    return True


def limpiar(clave):
    """Borra la foto y su ajustada de la memoria del navegador."""
    shutil.rmtree(ENTRADA / clave, ignore_errors=True)


def ajustar(clave):
    """Ajusta una foto con procesar_foto del script (el mismo JPG calidad 95, EXIF y perfil de
    color que en el PC). Devuelve JSON: estado ("lista", "ya" o "error"), ruta, segundos, info."""
    f = _foto(clave)
    # Devuelve 4 valores, o 5 cuando la foto se ajustó (VSO 1.3+: el quinto es la revisión de Pro)
    _, destino, segundos, info = ac.procesar_foto((f, ENTRADA / clave / ARGS.salida, ARGS, _planes.pop(clave, None)))[:4]
    if destino is None:
        estado, ruta = "ya", ""
    elif destino == "error":
        estado, ruta = "error", ""
    else:
        estado, ruta = "lista", str(destino)
    return json.dumps(dict(estado=estado, ruta=ruta, segundos=round(segundos, 1), info=info))
