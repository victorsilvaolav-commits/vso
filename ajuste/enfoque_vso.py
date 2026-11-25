# -*- coding: utf-8 -*-
"""
ENFOCAR FOTO en VSO App (24-11-2026, pedido de Victor: «que se pudieran enfocar las fotos»).

Es la MISMA receta que usa el programa de los cuadros (script para cuadros\\muestras\\enfocar_retrato.py, version
del 12-11-2026, aprobada por Victor; memoria enfocar-foto), copiada aqui para que VSO App no dependa de layout.py ni
de los archivos de los cuadros. Comprobado contra ese programa: mismo resultado pixel a pixel (ver INFORME.md de la
propuesta 2026-11-24 revision y enfocar).

Que hace (resumen de enfocar_retrato.py):
  - Busca la cara MAS GRANDE (YuNet) y mide cuanto esta desenfocada en los bordes de los ojos.
  - Richardson-Lucy sobre la luminosidad, con la fuerza de esa medida (1,2 a 2,2 px), 15 iteraciones.
  - Enfoca solo lo que sobresale del grano de la piel de esa cara (ojos, pestanas, cejas, labios, pelo): la piel
    lisa no se toca. Solo dentro del alumno (silueta GrabCut sin el contorno): el fondo queda igual.
  - Tope de halos gradual y orejas un poco menos rojas (como en los cuadros).

DIFERENCIA CON LOS CUADROS (24-11-2026): VSO App enfoca solo el interior de la cara (ver INTERIOR_*); la receta de
los cuadros enfocaba tambien el contorno y dejaba una linea «dibujada» en la mandibula.

Lo que se sabe de esta receta (memoria enfocar-foto):
  - Solo la cara principal: en caras chicas (escenario, ~240 px) la receta deja bordes duros, «dibujados» (la version
    rapida que enfocaba todas se rechazo el 19-11-2026).
  - En fotos que Victor ya edito en Lightroom «se ven peor»: se avisa (no se prohibe: en Pro la decide el).
  - Tarda: GrabCut (~5-7 s en una foto de 11 MP) es lo mas lento. Por eso en VSO App va solo a pedido, foto por foto.
"""
import math
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

RECETA = "E2026-11-24r"  # va en la firma del EXIF de las fotos enfocadas (si cambia la receta, se rehacen)


def firma_receta(suave=False):
    """Etiqueta corta de la receta para la firma EXIF (distingue normal y suave)."""
    return RECETA + ("s" if suave else "")

# 24-11-2026, mirado al 100 % en fotos rapidas (29.11.25 IMG_4286, 19.11.25 IMG_1681, Santo Tomas IMG_4979): la receta
# de los cuadros tal cual enfoca tambien el CONTORNO de la cara (mandibula y mejillas contra el pelo o el fondo) y ahi
# queda una linea clara «dibujada», la misma molestia que Victor rechazo el 19-11-2026. Bajar el tope de halos (0,015 y
# 0,008) no la quita: no es halo, es el borde mismo enfocado. Por eso VSO App enfoca solo el INTERIOR de la cara (una
# elipse de 0,40 x 0,46 caras, difuminada): ojos, cejas, nariz y boca quedan igual de nitidos que con la receta de los
# cuadros y el contorno queda como estaba. receta="cuadros" hace la de los cuadros tal cual (para comparar).
INTERIOR_ANCHO, INTERIOR_ALTO, INTERIOR_CENTRO = 0.40, 0.46, 0.47

SIGMA, ITER, MEZCLA, TOPE = 1.8, 15, 0.85, 0.04
MEZCLA_SUAVE = 0.5
BASE = 1.45
SIGMA_MIN, SIGMA_MAX = 1.2, 2.2
YA_NITIDA = 0.8
MUY_DESENFOCADA = 2.6
PIEL_A, PIEL_B = 1.0, 3.0

_YUNET = Path(__file__).with_name("face_detection_yunet_2023mar.onnx")
_modelo = []
_hilo = threading.local()


# ---------------------------------------------------------------- caras (igual que layout.caras_yunet / yunet)
def caras_yunet(im):
    """Todas las caras que ve YuNet (filas x, y, ancho, alto, ojos...) en la foto llevada a 1000 px de ancho, y el
    factor. Igual que layout.caras_yunet (mismo achique, mismo umbral 0,6), sin la memoria de busquedas."""
    rgb = im if im.mode == "RGB" else im.convert("RGB")
    o8 = np.asarray(rgb)
    h, w = o8.shape[:2]
    f = 1000.0 / w
    a = cv2.cvtColor(cv2.resize(o8, (1000, max(1, int(h * f))), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR)
    if not hasattr(_hilo, "det"):
        if not _modelo:
            _modelo.append(np.frombuffer(_YUNET.read_bytes(), np.uint8))  # en memoria: OpenCV no abre rutas con tilde
        _hilo.det = cv2.FaceDetectorYN.create("onnx", _modelo[0], np.zeros(0, np.uint8), (a.shape[1], a.shape[0]), 0.6)
    _hilo.det.setInputSize((a.shape[1], a.shape[0]))
    _, fs = _hilo.det.detect(a)
    return [] if fs is None else [x.copy() for x in fs], f


def yunet(im, caras=None):
    fs, f = caras_yunet(im) if caras is None else caras
    if not fs: return None
    r = max(fs, key=lambda r: r[2] * r[3])
    (x1, y1), (x2, y2) = sorted([tuple(r[4:6]), tuple(r[6:8])])
    return math.degrees(math.atan2(y2 - y1, x2 - x1)), (r[0] + r[2] / 2) / f, (r[1] + r[3] / 2) / f, r[2] / f


def alumno_grabcut(im, ancho=900, y=None):
    """Mascara 0-1 de la persona (pelo, cuerpo y brazos) con GrabCut desde la cara (copia de layout.alumno_grabcut)."""
    if y is None: y = yunet(im)
    if not y: return None
    k = ancho / im.width
    a = cv2.cvtColor(np.asarray(im.convert("RGB").resize((ancho, max(1, int(im.height * k))))), cv2.COLOR_RGB2BGR)
    h, w = a.shape[:2]; cx, cy, cw = y[1] * k, y[2] * k, y[3] * k
    m = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    m[:int(max(0, cy - 1.3 * cw)), :] = cv2.GC_BGD
    m[:int(cy + 0.6 * cw), :int(max(0, cx - 1.4 * cw))] = cv2.GC_BGD
    m[:int(cy + 0.6 * cw), int(min(w, cx + 1.4 * cw)):] = cv2.GC_BGD
    m[int(max(0, cy - cw)):, int(max(0, cx - 1.9 * cw)):int(min(w, cx + 1.9 * cw))] = cv2.GC_PR_FGD
    m[int(max(0, cy - 0.4 * cw)):int(cy + 0.5 * cw), int(max(0, cx - 0.35 * cw)):int(cx + 0.35 * cw)] = cv2.GC_FGD
    m[int(cy + 1.2 * cw):, int(max(0, cx - 0.6 * cw)):int(cx + 0.6 * cw)] = cv2.GC_FGD
    cv2.setRNGSeed(0)
    try: cv2.grabCut(a, m, None, np.zeros((1, 65)), np.zeros((1, 65)), 6, cv2.GC_INIT_WITH_MASK)
    except cv2.error: return None
    s = ((m == cv2.GC_FGD) | (m == cv2.GC_PR_FGD)).astype(np.uint8)
    hsv = cv2.cvtColor(a, cv2.COLOR_BGR2HSV)
    follaje = (hsv[..., 0] >= 26) & (hsv[..., 0] <= 50) & (hsv[..., 1] > 50) & (hsv[..., 2] > 70)
    follaje[int(max(0, cy + 1.3 * cw)):, :] = False
    follaje[int(max(0, cy + 0.9 * cw)):int(max(0, cy + 1.3 * cw)), int(max(0, cx - 1.1 * cw)):int(cx + 1.1 * cw)] = False
    follaje[int(max(0, cy - 0.75 * cw)):int(cy + 0.8 * cw), int(max(0, cx - 0.45 * cw)):int(cx + 0.45 * cw)] = False
    s[follaje] = 0
    s = cv2.morphologyEx(s, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, et = cv2.connectedComponents(s)
    if n > 1: s = (et == et[min(h - 1, int(cy)), min(w - 1, int(cx))]).astype(np.uint8)
    return s.astype(np.float32)


_CACHE_LR = {}


def editada_lightroom(ruta):
    """True si la foto ya la edito Victor en Lightroom o Camera Raw (copia de layout.editada_lightroom). Las que
    ajusto VSO tambien dicen «estilo lightroom» en el EXIF: esas no cuentan (VSO enfoca el original)."""
    try:
        p = Path(ruta)
        st = p.stat()
        clave = (str(p), st.st_mtime_ns, st.st_size)
        if clave in _CACHE_LR:
            return _CACHE_LR[clave]
        with Image.open(ruta) as im:
            sw = str(im.getexif().get(0x0131, ""))
            xmp = im.info.get("xmp") or b""
    except OSError:
        return False
    if isinstance(xmp, str):
        xmp = xmp.encode("utf-8", "ignore")
    res = False if sw.startswith("ajuste_combinado.py") else (
        "lightroom" in sw.lower() or "camera raw" in sw.lower() or b"crs:" in xmp or b"Lightroom" in xmp
    )
    if len(_CACHE_LR) < 512:
        _CACHE_LR[clave] = res
    return res


# ---------------------------------------------------------------- receta (copia de enfocar_retrato.py)
def richardson_lucy(L, sigma=None, it=None):
    sigma = SIGMA if sigma is None else sigma
    conv = lambda x: cv2.GaussianBlur(x, (0, 0), sigma)
    est = L.copy()
    for _ in range(ITER if it is None else it):
        est = est * conv(L / np.maximum(conv(est), 1e-4))
    return est


def cara_puntos(im, caras=None):
    fs, f = caras_yunet(im) if caras is None else caras
    if not fs: return None
    r = max(fs, key=lambda r: r[2] * r[3]) / f
    return dict(x=r[0], y=r[1], w=r[2], h=r[3], ojo1=(r[4], r[5]), ojo2=(r[6], r[7]), nariz=(r[8], r[9]),
                boca1=(r[10], r[11]), boca2=(r[12], r[13]))


def mejillas(c):
    r = 0.085 * c["w"]; ps = []
    for o, b in ((c["ojo1"], c["boca1"]), (c["ojo2"], c["boca2"])):
        mx, my = (o[0] + b[0]) / 2, (o[1] + b[1]) / 2
        ps.append((mx + 0.25 * (mx - c["nariz"][0]), my, r))
    return ps


def recorte(a, p):
    x, y, r = p
    return a[max(0, int(y - r)):int(y + r), max(0, int(x - r)):int(x + r)]


def desenfoque(L255, c):
    cx, cy, fw = c["x"] + c["w"] / 2, c["y"] + c["h"] / 2, c["w"]
    g = L255[int(max(0, cy - 0.4 * fw)):int(cy + 0.1 * fw), int(max(0, cx - 0.5 * fw)):int(cx + 0.5 * fw)]
    d = cv2.medianBlur(np.clip(g, 0, 255).astype(np.uint8), 3).astype(np.float32)
    gm = np.hypot(cv2.Sobel(d, cv2.CV_32F, 1, 0), cv2.Sobel(d, cv2.CV_32F, 0, 1)) / 8.0
    k = np.ones((15, 15), np.uint8)
    paso = cv2.dilate(d, k) - cv2.erode(d, k)
    top = gm > np.percentile(gm, 98)
    return float(np.median(paso[top] / (gm[top] * math.sqrt(2 * math.pi) + 1e-6)))


def tope_suave(e, L, T):
    k = np.ones((3, 3), np.uint8)
    lo, hi = cv2.erode(L, k), cv2.dilate(L, k)
    e = np.where(e > hi, hi + T * np.tanh((e - hi) / T), e)
    return np.where(e < lo, lo - T * np.tanh((lo - e) / T), e)


def silueta_y_dentro(im, y, W, H, cw):
    sil = cv2.resize(alumno_grabcut(im, y=y), (W, H), interpolation=cv2.INTER_LINEAR)
    borde = max(3, int(round(0.025 * cw)))
    dentro = cv2.erode((sil > 0.5).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=borde).astype(np.float32)
    dentro = cv2.GaussianBlur(dentro, (0, 0), max(2.0, 0.017 * cw))
    return sil, dentro


def _cambio(L, c, sigma):
    try:
        import vso_motor_nativo as _vmn
        if _vmn.disponible():
            e = _vmn.richardson_lucy_y_tope(L, sigma, ITER, TOPE)
        else:
            e = tope_suave(richardson_lucy(L, sigma, ITER), L, TOPE)
    except Exception:
        e = tope_suave(richardson_lucy(L, sigma, ITER), L, TOPE)
    g = cv2.GaussianBlur(np.hypot(cv2.Sobel(L, cv2.CV_32F, 1, 0), cv2.Sobel(L, cv2.CV_32F, 0, 1)), (0, 0), 2)
    gp = [x for x in (recorte(g, p) for p in mejillas(c)) if x.size]
    ref = float(np.percentile(min(gp, key=lambda x: float(np.median(x))), 90))
    t = np.clip((g - PIEL_A * ref) / ((PIEL_B - PIEL_A) * ref + 1e-9), 0, 1)
    detalle = t * t * (3 - 2 * t)
    return (e - L) * detalle


def preparar(im, minimo=None):
    """Igual que enfocar_retrato.preparar (sin `mientras`). None si no hay cara."""
    from concurrent.futures import ThreadPoolExecutor
    o8 = np.asarray(im); o = o8.astype(np.float32); H, W = o.shape[:2]
    caras = caras_yunet(im)
    c = cara_puntos(im, caras)
    if c is None: return None
    cw = c["w"]
    lab = cv2.cvtColor(o / 255.0, cv2.COLOR_RGB2Lab); L = lab[..., 0] / 100.0
    medida = desenfoque(L * 255.0, c)
    exceso = math.sqrt(max(medida * medida - BASE * BASE, 0.0))
    sigma = float(np.clip(exceso, SIGMA_MIN, SIGMA_MAX))
    p = dict(o=o, o8=o8, c=c, lab=lab, L=L, medida=medida, exceso=exceso, sigma=sigma, sil=None, dentro=None, caja=None)
    if minimo is not None and exceso < minimo:
        return p
    y = yunet(im, caras)
    with ThreadPoolExecutor(1) as hilo:
        silueta = hilo.submit(silueta_y_dentro, im, y, W, H, cw)
        p["cambio"] = _cambio(L, c, sigma)
        sil, dentro = silueta.result()
    filas, cols = np.flatnonzero(dentro.any(axis=1)), np.flatnonzero(dentro.any(axis=0))
    p.update(dentro=dentro, sil=sil,
             caja=(filas[0], filas[-1] + 1, cols[0], cols[-1] + 1) if filas.size else None)
    return p


def aplicar(p, mezcla, sin_orejas=False):
    o, c, lab, L = p["o"], p["c"], p["lab"], p["L"]; H, W = o.shape[:2]
    out = p["o8"].copy()
    if p["caja"] is not None:
        y0, y1, x0, x1 = p["caja"]; z = np.s_[y0:y1, x0:x1]
        if "_rgb0" not in p: p["_rgb0"] = cv2.cvtColor(lab[z], cv2.COLOR_Lab2RGB)
        lab2 = lab[z].copy(); lab2[..., 0] = np.clip(L[z] + p["cambio"][z] * mezcla, 0, 1) * 100.0
        delta = (cv2.cvtColor(lab2, cv2.COLOR_Lab2RGB) - p["_rgb0"]) * 255.0
        out[z] = np.rint(np.clip(o[z] + delta * p["dentro"][z][..., None], 0, 255)).astype(np.uint8)
    if sin_orejas: return out, 0
    cw = c["w"]; cx, cy = c["x"] + cw / 2, c["y"] + c["h"] / 2
    y0, y1 = max(0, int(cy - 0.40 * cw) - 30), min(H, int(cy + 0.40 * cw) + 31)
    x0, x1 = max(0, int(cx - 0.80 * cw) - 30), min(W, int(cx + 0.80 * cw) + 31)
    if y0 >= y1 or x0 >= x1: return out, 0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    lado = (np.abs(xx - cx) > 0.40 * cw) & (np.abs(xx - cx) < 0.80 * cw) & (np.abs(yy - cy) < 0.40 * cw)
    rec = out[y0:y1, x0:x1]
    hsv = cv2.cvtColor(rec, cv2.COLOR_RGB2HSV).astype(np.float32)
    rojo = ((hsv[..., 0] < 10) | (hsv[..., 0] > 170)) & (hsv[..., 1] > 90)
    n = int((lado & rojo).sum())
    if n:
        m = cv2.GaussianBlur((lado & rojo).astype(np.float32), (0, 0), 6)
        hsv[..., 1] *= 1 - 0.40 * m
        conv = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2RGB)
        out[y0:y1, x0:x1] = np.where((m > 0.004)[..., None], conv, rec)
    return out, n


# ---------------------------------------------------------------- lo que usa VSO App
def _recorte_cara(c, W, H):
    """Rectangulo (x0, y0, x1, y1) con margen suficiente para la elipse interior, la medicion de ojos,
    las mejillas y las 15 pasadas de Richardson-Lucy, sin procesar el resto de la foto."""
    cx, cy, fw, fh = c["x"] + c["w"] / 2.0, c["y"] + c["h"] / 2.0, c["w"], c["h"]
    cy_e = c["y"] + fh * INTERIOR_CENTRO
    sig_m = 0.06 * fw
    pad = max(48, int(round(0.12 * fw)))
    xs = [cx - INTERIOR_ANCHO * fw - 4.0 * sig_m, cx + INTERIOR_ANCHO * fw + 4.0 * sig_m,
          cx - 0.5 * fw - 12.0, cx + 0.5 * fw + 12.0]
    ys = [cy_e - INTERIOR_ALTO * fh - 4.0 * sig_m, cy_e + INTERIOR_ALTO * fh + 4.0 * sig_m,
          cy - 0.4 * fw - 12.0, cy + 0.1 * fw + 12.0]
    for mx, my, mr in mejillas(c):
        xs += [mx - mr - 12.0, mx + mr + 12.0]
        ys += [my - mr - 12.0, my + mr + 12.0]
    x0 = max(0, int(math.floor(min(xs))) - pad)
    x1 = min(W, int(math.ceil(max(xs))) + pad)
    y0 = max(0, int(math.floor(min(ys))) - pad)
    y1 = min(H, int(math.ceil(max(ys))) + pad)
    return x0, y0, x1, y1


def _desplazar_cara(c, x0, y0):
    return dict(x=c["x"] - x0, y=c["y"] - y0, w=c["w"], h=c["h"],
                ojo1=(c["ojo1"][0] - x0, c["ojo1"][1] - y0), ojo2=(c["ojo2"][0] - x0, c["ojo2"][1] - y0),
                nariz=(c["nariz"][0] - x0, c["nariz"][1] - y0),
                boca1=(c["boca1"][0] - x0, c["boca1"][1] - y0), boca2=(c["boca2"][0] - x0, c["boca2"][1] - y0))


def mascara_interior(alto, ancho, c, escala=1.0):
    """Mascara 0..1 del interior de la cara (la misma elipse difuminada que enfoca receta='interior').
    Se usa tambien en ajuste_combinado para no volver a enfocar dos veces la misma zona."""
    x, y, w, h = c["x"] * escala, c["y"] * escala, c["w"] * escala, c["h"] * escala
    sig = max(1.0, 0.06 * w)
    if sig >= 6.0 and alto >= 64 and ancho >= 64:
        sh, sw = max(16, alto // 4), max(16, ancho // 4)
        sx, sy = sw / float(ancho), sh / float(alto)
        ms = np.zeros((sh, sw), np.float32)
        cv2.ellipse(ms, (int(round((x + w / 2) * sx)), int(round((y + h * INTERIOR_CENTRO) * sy))),
                    (max(1, int(round(INTERIOR_ANCHO * w * sx))), max(1, int(round(INTERIOR_ALTO * h * sy)))),
                    0, 0, 360, 1.0, -1)
        ms = cv2.GaussianBlur(ms, (0, 0), sig * sx)
        return cv2.resize(ms, (ancho, alto), interpolation=cv2.INTER_LINEAR)
    m = np.zeros((alto, ancho), np.float32)
    cv2.ellipse(m, (int(x + w / 2), int(y + h * INTERIOR_CENTRO)),
                (max(1, int(INTERIOR_ANCHO * w)), max(1, int(INTERIOR_ALTO * h))), 0, 0, 360, 1.0, -1)
    return cv2.GaussianBlur(m, (0, 0), sig)


def medir(img):
    """Medida rapida, sin enfocar (no hace la silueta ni convierte la foto entera): dict(cara, exceso px, estado)
    o None si no hay cara. estado: «nitida» (no conviene enfocar), «blanda» o «muy» (el enfoque no alcanza)."""
    im = img.convert("RGB")
    o8 = np.asarray(im); H, W = o8.shape[:2]
    c = cara_puntos(im)
    if c is None:
        return None
    x0, y0, x1, y1 = _recorte_cara(c, W, H)
    c_loc = _desplazar_cara(c, x0, y0)
    lab = cv2.cvtColor(o8[y0:y1, x0:x1].astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)
    medida = desenfoque(lab[..., 0] * 2.55, c_loc)
    e = math.sqrt(max(medida * medida - BASE * BASE, 0.0))
    return dict(cara=c, exceso=e, estado="nitida" if e < YA_NITIDA else ("muy" if e > MUY_DESENFOCADA else "blanda"))


def solo_interior(p):
    """La preparacion limitada al interior de la cara (ver INTERIOR_*): fuera de la elipse no cambia nada."""
    c = p["c"]; H, W = p["L"].shape
    m = mascara_interior(H, W, c)
    q = dict(p)
    q["dentro"] = p["dentro"] * m
    filas, cols = np.flatnonzero(q["dentro"].any(axis=1)), np.flatnonzero(q["dentro"].any(axis=0))
    q["caja"] = (filas[0], filas[-1] + 1, cols[0], cols[-1] + 1) if filas.size else None
    q.pop("_rgb0", None)
    return q


def _enfocar_interior_rapido(im, suave=False, caras=None):
    """Enfoque limitado al interior de la cara calculado solo sobre el recorte facial (sin GrabCut ni
    Richardson-Lucy en el resto de la foto: < 0,3 s en vez de 5-12 s, mismos pixeles en la cara)."""
    o8 = np.asarray(im); H, W = o8.shape[:2]
    c = cara_puntos(im, caras)
    if c is None:
        return im, None
    x0, y0, x1, y1 = _recorte_cara(c, W, H)
    c_loc = _desplazar_cara(c, x0, y0)
    rec8 = o8[y0:y1, x0:x1]
    rec = rec8.astype(np.float32)
    lab = cv2.cvtColor(rec * np.float32(1.0 / 255.0), cv2.COLOR_RGB2Lab)
    L = np.ascontiguousarray(lab[..., 0] * np.float32(0.01), np.float32)
    medida = desenfoque(L * np.float32(255.0), c_loc)
    exceso = math.sqrt(max(medida * medida - BASE * BASE, 0.0))
    sigma = float(np.clip(exceso, SIGMA_MIN, SIGMA_MAX))
    cambio = _cambio(L, c_loc, sigma)
    m = mascara_interior(y1 - y0, x1 - x0, c_loc)
    mezcla = MEZCLA_SUAVE if suave else MEZCLA
    rgb0 = cv2.cvtColor(lab, cv2.COLOR_Lab2RGB)
    lab2 = lab.copy()
    lab2[..., 0] = np.clip(L + cambio * mezcla, 0, 1) * 100.0
    delta = (cv2.cvtColor(lab2, cv2.COLOR_Lab2RGB) - rgb0) * 255.0
    out = o8.copy()
    out[y0:y1, x0:x1] = np.rint(np.clip(rec + delta * m[..., None], 0, 255)).astype(np.uint8)
    return Image.fromarray(out), dict(exceso=exceso, sigma=sigma, cara=c, tam=(W, H), suave=bool(suave))


def enfocar(img, suave=False, receta="interior", caras=None):
    """(foto enfocada PIL RGB, info) — siempre enfoca (la decision ya la tomo Victor en Pro).
    receta: «interior» (la de VSO App: ojos, cejas, nariz y boca, rapida sobre el recorte facial)
            o «cuadros» (enfocar_retrato.py tal cual).
    info: dict(exceso, sigma, cara, tam, suave) o None si no encontro la cara (devuelve la foto tal cual)."""
    im = img if img.mode == "RGB" else img.convert("RGB")
    if receta == "interior":
        return _enfocar_interior_rapido(im, suave=suave, caras=caras)
    p = preparar(im)
    if p is None:
        return im, None
    out, _ = aplicar(p, MEZCLA_SUAVE if suave else MEZCLA)
    H, W = p["o8"].shape[:2]
    return Image.fromarray(out), dict(exceso=p["exceso"], sigma=p["sigma"], cara=p["c"], tam=(W, H), suave=bool(suave))
