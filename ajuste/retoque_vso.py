# -*- coding: utf-8 -*-
"""
RETOQUES DIRECTOS de VSO App (tipo Lightroom), 2026-11-19.

Se aplican ENCIMA del ajuste combinado automatico, solo desde el panel con controles
(panel_controles.py). El modo rapido (clic derecho, .bat de siempre) no pasa por aqui y las fotos
salen identicas. Con todos los retoques en 0 no se cambia nada.

Retoques (cada uno de -100 a +100, 0 = sin cambio):
  exposicion   aclara u oscurece toda la foto (hasta 1,5 pasos), con las luces suavizadas en vez
               de quemarse de golpe
  contraste    curva S: mas o menos diferencia entre claros y oscuros (negro y blanco quedan fijos)
  altas_luces  - recupera cielos y ropa blanca; + los hace brillar mas
  sombras      + levanta lo oscuro (pelo, ropa negra, fondos); - lo hunde
  temperatura  - mas frio (azul); + mas calido (amarillo). El negro sigue negro
  saturacion   - menos color (-100 = blanco y negro); + mas color

Sombras y altas luces actuan sobre la "base" de la foto (filtro guiado del ajuste combinado):
cambian la luz sin aplanar la textura (pelo, telas) ni dejar halos en los bordes. El tamano del
filtro va en proporcion a la foto, asi la vista previa chica se parece a la foto entera.

Para el lote: instalar_en_motor() hace que ajuste_combinado.mejorar() aplique el retoque despues
del ajuste, y que la firma del EXIF lo incluya (asi un lote cortado se retoma bien). Los valores
viajan en la variable de entorno VSO_RETOQUE, que heredan los procesos que ajustan las fotos.
"""
import json
import os

import cv2
import numpy as np
from PIL import Image

CLAVES = ("exposicion", "contraste", "altas_luces", "sombras", "temperatura", "matiz", "saturacion")
VARIABLE = "VSO_RETOQUE"


def limpio(valores):
    """Solo los retoques distintos de 0, como enteros. {} = sin retoque."""
    return {k: int(round(valores.get(k, 0))) for k in CLAVES if int(round(valores.get(k, 0)))}


def _a_lineal(u):
    return np.where(u <= 0.04045, u / 12.92, ((u + 0.055) / 1.055) ** 2.4).astype(np.float32)


# La foto es de 8 bits: solo hay 256 valores posibles. Se pasan a luz lineal una vez y despues se
# buscan en esta tabla (antes se calculaba la potencia 2,4 de cada pixel: ~1 s por foto de 11,6 MP)
_LINEAL = _a_lineal(np.arange(256, dtype=np.float32) / 255.0)


def _a_srgb(l):
    l = np.clip(l, 0, 1)
    return np.where(l <= 0.0031308, l * 12.92, 1.055 * np.power(l, 1 / 2.4) - 0.055).astype(np.float32)


def _hombro(y, desde=0.75):
    """Hasta 'desde' igual; arriba se acerca a 1 suave, sin cortar de golpe (no quema)."""
    sobre = np.maximum(y - desde, 0)
    return np.where(y <= desde, y, desde + (1 - desde) * (1 - np.exp(-sobre / (1 - desde))))


def _suave(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def aplicar_contraste_lab(lab, contraste):
    """Curva S sobre L* (0..100) en float32 dentro del revelado estilo Lightroom (negro y blanco fijos)."""
    c = contraste / 100.0
    if not c:
        return
    try:
        import vso_motor_nativo as _vmn
        if _vmn.disponible():
            _vmn.contraste_lab(lab, contraste)
            return
    except Exception:
        pass
    from ajuste_combinado import por_franjas

    def franja(f):
        Lf = lab[f, :, 0] / 100.0
        S = Lf * Lf * (3.0 - 2.0 * Lf)
        lab[f, :, 0] = np.clip(Lf + c * 0.85 * (S - Lf), 0.0, 1.0) * 100.0
    por_franjas(franja, lab.shape[0])


def aplicar_saturacion_a_rgb(lab, saturacion):
    """Aplica saturacion (-100..+100) en float32 Lab y convierte a RGB float32:
    - negativa: desaturacion pareja en Lab (-100 = blanco y negro);
    - positiva: vibrancia protegida (protege piel, colores ya muy saturados, negros y blancos) con freno
      de gama suave en sRGB, sin cuantizacion intermedia a 8 bits."""
    sat = saturacion / 100.0
    if not sat:
        return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    from ajuste_combinado import mascara_piel, por_franjas
    if sat < 0:
        k_desat = np.float32(max(0.0, 1.0 + sat))

        def franja_neg(f):
            lab[f, :, 1:] *= k_desat
        por_franjas(franja_neg, lab.shape[0])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)

    piel_sat = mascara_piel(lab, paso=4)
    ab_orig = lab[..., 1:].copy()

    def franja_pos(f):
        Lf = lab[f, :, 0] / 100.0
        af, bf = lab[f, :, 1], lab[f, :, 2]
        croma = np.sqrt(af * af + bf * bf)
        peso_sat = (np.clip((croma - 2.0) / 6.0, 0.0, 1.0)
                    * np.clip(1.0 - croma / 75.0, 0.15, 1.0)
                    * np.clip((Lf - 0.10) / 0.12, 0.0, 1.0)
                    * np.clip((0.96 - Lf) / 0.08, 0.0, 1.0)
                    * (1.0 - 0.72 * piel_sat[f]))
        fac = 1.0 + 0.85 * sat * peso_sat
        lab[f, :, 1] = af * fac
        lab[f, :, 2] = bf * fac
    por_franjas(franja_pos, lab.shape[0])
    del piel_sat
    rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    # Freno de gama suave: los pixeles que se salgan de sRGB vuelven lo justo hacia el color previo
    vuelta = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    err = np.abs(vuelta[..., 1:] - lab[..., 1:]).sum(axis=2)
    ys, xs = np.nonzero(err > 1.5)
    if ys.size:
        L_p = lab[ys, xs, 0:1]
        ab_0 = ab_orig[ys, xs]
        ab_1 = lab[ys, xs, 1:]
        bajo = np.zeros(len(ys), np.float32)
        alto = np.ones(len(ys), np.float32)
        for _ in range(5):
            tm = (bajo + alto) * 0.5
            p_lab = np.concatenate([L_p, ab_0 + tm[:, None] * (ab_1 - ab_0)], axis=1)[:, None, :]
            v_lab = cv2.cvtColor(cv2.cvtColor(p_lab, cv2.COLOR_LAB2RGB), cv2.COLOR_RGB2LAB)
            cabe = np.abs(v_lab[:, 0, 1:] - p_lab[:, 0, 1:]).sum(axis=1) <= 1.0
            bajo = np.where(cabe, tm, bajo)
            alto = np.where(cabe, alto, tm)
        p_ok = np.concatenate([L_p, ab_0 + bajo[:, None] * (ab_1 - ab_0)], axis=1)[:, None, :]
        rgb[ys, xs] = cv2.cvtColor(p_ok, cv2.COLOR_LAB2RGB)[:, 0, :]
    del ab_orig, vuelta
    return rgb


def retocar(img, valores):
    """img: PIL RGB. Devuelve otra PIL RGB con los retoques (camino de respaldo para estilo='vso';
    en estilo='lightroom' los retoques entran directo al revelado en mejorar_lightroom)."""
    v = {k: x / 100.0 for k, x in limpio(valores).items()}
    if not v:
        return img
    from ajuste_combinado import filtro_guiado, mascara_piel, por_franjas
    import estilo_lightroom as elr
    u8 = np.asarray(img.convert("RGB"))

    # 1) Temperatura, matiz y exposicion en luz lineal (como en la camara): ganancias por canal
    t, mat, e = v.get("temperatura", 0.0), v.get("matiz", 0.0), v.get("exposicion", 0.0)
    if t or mat or e:
        lin = _LINEAL[u8]
        g = elr.ganancias_wb(t, mat)
        rgb = np.empty_like(lin)

        def franja(f):
            x = lin[f]
            if g is not None:
                x = x * g
            if e:
                Y = x @ np.array([0.2126, 0.7152, 0.0722], np.float32)
                Y2 = _hombro(Y * 2.0 ** (1.5 * e)) if e > 0 else Y * 2.0 ** (1.5 * e)
                x = x * (Y2 / np.maximum(Y, 1e-6))[..., None]
            rgb[f] = _a_srgb(x)
        por_franjas(franja, lin.shape[0])
        del lin
    else:
        rgb = u8.astype(np.float32) / 255.0

    # 2) Luz y color en Lab (L 0..100, a y b alrededor de 0)
    lab = cv2.cvtColor(np.clip(rgb, 0, 1), cv2.COLOR_RGB2LAB)
    del rgb
    L = lab[..., 0] / 100.0
    h, s = v.get("altas_luces", 0.0), v.get("sombras", 0.0)
    c, sat = v.get("contraste", 0.0), v.get("saturacion", 0.0)
    base = filtro_guiado(L, max(2, round(max(L.shape) / 90)), 0.012) if h or s else None
    piel_sat = mascara_piel(lab, paso=4) if sat > 0 else None
    ab_orig = lab[..., 1:].copy() if sat > 0 else None
    k_desat = max(0.0, 1 + sat)

    def franja(f):
        Lf = L[f]
        if base is not None:
            b = base[f]
            nueva = b.copy()
            if s:
                peso = 1 - _suave(b, 0.0, 0.55)               # solo lo oscuro
                nueva += (s * 0.32 * peso * (0.62 - b)) if s > 0 else (s * 0.60 * peso * b)
            if h:
                peso = _suave(b, 0.40, 0.90)                  # solo lo claro
                nueva += (h * 0.40 * peso * (1.0 - b)) if h > 0 else (h * 0.55 * peso * (b - 0.30))
            Lf = np.clip(nueva + (Lf - b), 0, 1)
        if c:
            S = Lf * Lf * (3 - 2 * Lf)                        # curva S con negro y blanco fijos
            Lf = np.clip(Lf + c * 0.85 * (S - Lf), 0, 1)
        lab[f, :, 0] = Lf * 100.0
        if sat < 0:
            lab[f, :, 1:] *= k_desat
        elif sat > 0:
            # Vibrancia protegida (2026-11-22): protege piel, colores ya muy saturados, negros y blancos
            af, bf = lab[f, :, 1], lab[f, :, 2]
            croma = np.sqrt(af * af + bf * bf)
            peso_sat = (np.clip((croma - 2.0) / 6.0, 0.0, 1.0)
                        * np.clip(1.0 - croma / 75.0, 0.15, 1.0)
                        * np.clip((Lf - 0.10) / 0.12, 0.0, 1.0)
                        * np.clip((0.96 - Lf) / 0.08, 0.0, 1.0)
                        * (1.0 - 0.72 * piel_sat[f]))
            fac = 1.0 + 0.85 * sat * peso_sat
            lab[f, :, 1] = af * fac
            lab[f, :, 2] = bf * fac
    por_franjas(franja, lab.shape[0])
    del L, base, piel_sat
    rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    if sat > 0 and ab_orig is not None:
        # Freno de gama suave: los pixeles que se salgan de sRGB vuelven lo justo hacia el color previo
        vuelta = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        err = np.abs(vuelta[..., 1:] - lab[..., 1:]).sum(axis=2)
        ys, xs = np.nonzero(err > 1.5)
        if ys.size:
            L_p = lab[ys, xs, 0:1]
            ab_0 = ab_orig[ys, xs]
            ab_1 = lab[ys, xs, 1:]
            bajo = np.zeros(len(ys), np.float32)
            alto = np.ones(len(ys), np.float32)
            for _ in range(5):
                tm = (bajo + alto) * 0.5
                p_lab = np.concatenate([L_p, ab_0 + tm[:, None] * (ab_1 - ab_0)], axis=1)[:, None, :]
                v_lab = cv2.cvtColor(cv2.cvtColor(p_lab, cv2.COLOR_LAB2RGB), cv2.COLOR_RGB2LAB)
                cabe = np.abs(v_lab[:, 0, 1:] - p_lab[:, 0, 1:]).sum(axis=1) <= 1.0
                bajo = np.where(cabe, tm, bajo)
                alto = np.where(cabe, alto, tm)
            p_ok = np.concatenate([L_p, ab_0 + bajo[:, None] * (ab_1 - ab_0)], axis=1)[:, None, :]
            rgb[ys, xs] = cv2.cvtColor(p_ok, cv2.COLOR_LAB2RGB)[:, 0, :]
        del ab_orig, vuelta
    del lab
    salida = np.empty(rgb.shape, np.uint8)

    def franja(f):
        salida[f] = (np.clip(rgb[f], 0, 1) * 255 + 0.5).astype(np.uint8)
    por_franjas(franja, rgb.shape[0])
    return Image.fromarray(salida)


def texto(valores):
    """Para la firma del EXIF: ' retoque-lr exposicion 20 matiz -10' o ''."""
    v = limpio(valores)
    return (" retoque-lr " + " ".join(f"{k} {x}" for k, x in v.items())) if v else ""


def preparar_lote(valores):
    """En el programa que lanza el lote: deja los retoques en la variable de entorno (la heredan
    los procesos que ajustan) y los instala en este proceso."""
    v = limpio(valores)
    if v:
        os.environ[VARIABLE] = json.dumps(v)
    else:
        os.environ.pop(VARIABLE, None)
    instalar_en_motor()


def instalar_en_motor():
    """Si hay retoques en VSO_RETOQUE, en el estilo Lightroom entran directo al revelado (sin doble
    cuantizacion a 8 bits) y se anotan en la firma del EXIF. Sin la variable no hace nada."""
    import sys
    try:
        v = limpio(json.loads(os.environ.get(VARIABLE, "") or "{}"))
    except ValueError:
        v = {}
    if not v:
        return
    import ajuste_combinado as motor
    objetivos = [motor]
    mod_main = sys.modules.get("__main__")
    if mod_main is not None and mod_main is not motor and getattr(mod_main, "MARCA", None) == motor.MARCA:
        objetivos.append(mod_main)
    for mod in objetivos:
        if getattr(mod, "_retoque_vso", None) == v:
            continue
        original_mejorar = getattr(mod, "_mejorar_sin_retoque", mod.mejorar)
        original_firma = getattr(mod, "_firma_sin_retoque", mod.firma)
        mod._mejorar_sin_retoque, mod._firma_sin_retoque = original_mejorar, original_firma

        def _crear_mejorar(orig):
            def mejorar(*a, **k):
                estilo = k.get("estilo", a[11] if len(a) > 11 else "lightroom")
                if estilo == "lightroom" and "retoques" not in k:
                    return orig(*a, **k, retoques=v)
                resultado, info = orig(*a, **k)
                return retocar(resultado, v), info + ", retoque"
            return mejorar

        mod.mejorar = _crear_mejorar(original_mejorar)
        mod.firma = (lambda orig_f: (lambda args: orig_f(args) + texto(v)))(original_firma)
        mod._retoque_vso = v
