# -*- coding: utf-8 -*-
"""
ESTILO LIGHTROOM para el ajuste combinado / VSO App (22-11-2026).

Imita el boton "Automatico" de Lightroom Classic (version 16.0.1, proceso 15.4) en fotos JPG.
Se aprendio de 219 fotos de Victor (22-11-2026): 40 en Desktop\\Pruebas con Lightroom y 179 en
Desktop\\Pruebas con Lightroom 2 (la 114 quedo fuera: tenia balance de blancos Automatico). Cada JPG
que exporto Lightroom trae escritos los controles que eligio su Automatico, asi que se aprendieron
por separado:

1. predecir(): que controles pondria el Automatico (exposicion, altas luces, sombras, negros,
   intensidad y saturacion; blancos y contraste casi no cambian y van fijos) a partir de medidas
   del histograma y del color de la foto (regresion ridge, validada dejando cada foto fuera).
2. revelar(): como aplica Lightroom esos controles (exposicion en luz lineal, altas luces y
   sombras segun la luz de la zona en 3 tamanos, color segun croma, tono, luz y cuanto se aclaro).
   Ajustado con todos los pixeles de las 219 fotos; las curvas son suaves y los grises no se tinen
   (croma 0 queda 0).

Lightroom NO toca el balance de blancos en el Automatico ("Como se tomo"): este estilo tampoco.

Los numeros del modelo estan en estilo_lightroom.npz (junto a este archivo). Los programas con que
se ajusto y midio, el informe y las laminas estan en propuesta 2026-11-22 estilo lightroom\\.

Medido con el programa real y fotos que el modelo no vio: diferencia de color con Lightroom,
mediana dE2000:
  - modelo de 40 fotos (LR40) en las 179 fotos nuevas de la tanda 2: 2,91;
  - este modelo (LR219), validacion cruzada en 5 partes: 2,63 en la tanda 2 y 2,65 en las 219.
  El ajuste combinado de siempre: 4,73; la foto sin tocar: 4,50 (tanda 2).
Programas y mediciones: propuesta 2026-11-22 estilo lightroom\\programa (aprender220.py, cv_correr.py,
medir220.py, exp_cara.py).
"""
import json
from pathlib import Path

import cv2
import numpy as np

ARCHIVO = Path(__file__).with_name("estilo_lightroom.npz")
VERSION_MODELO = "LR219-2026-11-23-a-tu-gusto"   # va en la firma del EXIF: si cambia el modelo, se rehacen

_M = None
W = np.array([0.2126, 0.7152, 0.0722], np.float32)
_LIN8 = np.where(np.arange(256) / 255.0 <= 0.04045, np.arange(256) / 255.0 / 12.92,
                 ((np.arange(256) / 255.0 + 0.055) / 1.055) ** 2.4).astype(np.float32)
LADO_BASE = 600        # tamano al que se calculo la luz de cada zona al aprender (filtro guiado)
LADO_MEDIDAS = 450     # tamano al que se miden las fotos para predecir los controles


def modelo():
    global _M
    if _M is None:
        z = np.load(ARCHIVO, allow_pickle=False)
        m = {k: z[k] for k in z.files}
        m["meta"] = json.loads(str(m["meta"]))
        _M = m
    return _M


# ---------------------------------------------------------------- conversiones de luz
def a_lineal(u8):
    # cv2.LUT da exactamente los mismos numeros que _LIN8[u8], unas 3 veces mas rapido (24-11-2026)
    if u8.dtype == np.uint8 and u8.ndim in (2, 3) and (u8.ndim == 2 or u8.shape[2] <= 4):
        return cv2.LUT(np.ascontiguousarray(u8), _LIN8)
    return _LIN8[u8]


_pool = None
FILAS = 32  # filas de cada franja (como por_franjas de ajuste_combinado: caben en la cache)


def _por_franjas(funcion, alto, filas=FILAS):
    """Corre funcion(slice de filas) en franjas a la vez, en 4 hilos. Solo para calculos pixel a
    pixel: el resultado es identico a hacerlo de una vez (24-11-2026: antes revelar() y
    blanco_limpio() usaban un solo nucleo y eran la mitad del tiempo de cada foto)."""
    global _pool
    if _pool is None:
        from concurrent.futures import ThreadPoolExecutor
        _pool = ThreadPoolExecutor(max_workers=4)
    cortes = list(range(0, alto, filas)) + [alto]
    if len(cortes) <= 2:
        funcion(slice(0, alto))
        return
    list(_pool.map(lambda i: funcion(slice(cortes[i], cortes[i + 1])), range(len(cortes) - 1)))


def a_srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


def Y_a_v(Y):
    """Luz lineal -> L*/100 (puede pasar de 1 si la exposicion sube)."""
    Y = np.maximum(Y, 0)
    return np.where(Y > 0.008856, 1.16 * np.cbrt(Y) - 0.16, Y * 9.033).astype(np.float32)


def v_a_Y(v):
    v = np.maximum(v, 0)
    return np.where(v > 0.08, ((v + 0.16) / 1.16) ** 3, v / 9.033).astype(np.float32)


# ---------------------------------------------------------------- 1. predecir los controles
def achicar(u8, lado):
    h, w = u8.shape[:2]
    k = lado / max(h, w)
    if k >= 1:
        return u8
    return cv2.resize(u8, (round(w * k), round(h * k)), interpolation=cv2.INTER_AREA)


_G_CACHE = {}
_PCTS_V = (1, 5, 10, 25, 50, 75, 90, 95, 99, 99.5, 99.9)


def _gauss_peso(h, w):
    """Pesos gaussianos centrados normalizados para medidas() (cacheados por tamano)."""
    res = _G_CACHE.get((h, w))
    if res is None:
        yy = ((np.arange(h, dtype=np.float64) / h - 0.5) / 0.3) ** 2
        xx = ((np.arange(w, dtype=np.float64) / w - 0.5) / 0.3) ** 2
        g = np.exp(-(yy[:, None] + xx[None, :]) * 0.5)
        g = g / g.sum()
        if len(_G_CACHE) < 32:
            _G_CACHE[(h, w)] = g
        res = g
    return res


def _medidas_preparadas(u8):
    """Precalcula lin, Y0, pesos g y croma una sola vez para m0 y m1 en predecir()."""
    lin = a_lineal(u8)
    Y0 = lin @ W
    h, w = Y0.shape
    g = _gauss_peso(h, w)
    # Croma solo depende de la foto original (no cambia con E): evita convertir a_srgb(lin) dos veces
    lab = cv2.cvtColor(u8.astype(np.float32) * np.float32(1.0 / 255.0), cv2.COLOR_RGB2LAB)
    C = np.hypot(lab[..., 1], lab[..., 2])
    c_stats = {
        "Cmean": float(C.mean()),
        "Cp90": float(np.percentile(C, 90)),
        "C30": float((C > 30).mean()),
        "C50": float((C > 50).mean()),
    }

    def evaluar(E=None):
        Y = Y0 if E is None else (Y0 * np.float32(2.0 ** E))
        v = Y_a_v(Y)
        lg = np.log2(np.maximum(Y, np.float32(2.0 ** -12)))
        ps = np.percentile(v, _PCTS_V)
        f = dict(c_stats)
        f["vmean"] = float(v.mean())
        f["vmed"] = float(ps[4])
        f["lgmean"] = float(lg.mean())
        f["lgmed"] = float(np.median(lg))
        f["vcen"] = float((v * g).sum())
        f["lgcen"] = float((lg * g).sum())
        f["Ymean"] = float(Y.mean())
        f["rms"] = float(np.sqrt((v * v).mean()))
        for idx, p in ((0, 1), (1, 5), (2, 10), (3, 25), (5, 75), (6, 90), (7, 95), (8, 99), (9, 99.5), (10, 99.9)):
            f["p%s" % p] = float(ps[idx])
        for t in (0.05, 0.1, 0.2):
            f["bajo%s" % t] = float((v < t).mean())
        for t in (0.8, 0.9, 0.95, 1.0, 1.1):
            f["alto%s" % t] = float((v > t).mean())
        f["std"] = float(v.std())
        f["lgstd"] = float(lg.std())
        return f

    return evaluar


def medidas(u8, E=None):
    """Las mismas medidas que se usaron para aprender (no cambiar sin volver a ajustar)."""
    return _medidas_preparadas(u8)(E)


def _ridge(m, pre, x):
    return float(np.r_[1.0, (x - m[pre + "_mu"]) / m[pre + "_sd"]] @ m[pre + "_c"])


def predecir(u8):
    """Controles que pondria el Automatico de Lightroom (en sus mismas unidades)."""
    m = modelo()
    meta = m["meta"]
    chica = achicar(achicar(u8, 900), LADO_MEDIDAS)   # igual que al aprender (900 y luego 450)
    ev = _medidas_preparadas(chica)
    m0 = ev(None)
    rangos = dict(zip(meta["K"], m["rangos"]))
    E = _ridge(m, "E", np.array([m0[k] for k in meta["SUB_E"]]))
    E = float(np.clip(E, *rangos["Exposure2012"]))
    m1 = ev(E)
    s = {"Exposure2012": E, "Whites2012": float(m["Wh_const"]), "Contrast2012": float(m["Co_const"])}
    for corto, k, sub in (("Hi", "Highlights2012", "SUB_T"), ("Sh", "Shadows2012", "SUB_T"),
                          ("Bl", "Blacks2012", "SUB_T"), ("Vib", "Vibrance", "SUB_C"), ("Sat", "Saturation", "SUB_C")):
        x = np.array([m0[q] for q in meta[sub]] + [m1[q] for q in meta[sub]])
        s[k] = float(np.clip(_ridge(m, corto, x), *rangos[k]))
    return s


# L* de la cara principal que se acepta (proteger_cara). 22-11-2026 (219 fotos, exp_cara.py): Lightroom
# NO sube las caras oscuras (en exterior y contraluz las deja oscuras: subirlas a 52 daba las peores
# fotos, p. ej. cara 35 en Lightroom y 51 aqui), asi que ya no se suben (CARA_BAJO 0). Las quemadas
# si las baja (52 de 65 caras sobre 70); techo 72: la foto 4 de Victor queda igual que en LR40-b.
# 23-11-2026 (propuesta «a tu gusto», aprobada por Victor): las caras quedan entre 60 y 72 (le gustan
# las caras claras, como en el VSO de siempre).
CARA_BAJO, CARA_ALTO = 60.0, 72.0


def _revelar_chica_nueva(lin, Y, s, ab_cache, roi=None):
    """Evalua la luminancia nueva (0..1) en la copia chica (500 px) reutilizando bases del filtro guiado
    para el mismo E y saltando todo el calculo de color/remap (L* no depende del paso de color)."""
    m = modelo()
    KN = m["KN"].astype(np.float64)
    nb = 1 + len(m["RADIOS"])
    Cl = m["coef_luz"].reshape(len(m["meta"]["CONTROLES"]), nb, len(KN))
    c = _controles_luz(s)
    curvas = [_tabla_curva(KN, c @ Cl[:, j, :]) for j in range(nb)]
    E = float(s["Exposure2012"])
    E_key = round(E, 6)
    ab_v = ab_cache.get(E_key)
    if ab_v is None:
        g = np.float32(2.0 ** E)
        Yg = Y * g
        v = np.where(Yg <= 2.2, _leer(_YV, Yg), Y_a_v(Yg)) if E > 1.25 else _leer(_YV, Yg)
        vb = np.minimum(v, 1.4)
        lado = max(Y.shape)
        eps = float(m["EPS"])
        bases = []
        for rad in m["RADIOS"]:
            r = max(1, round(float(rad) * lado))
            mu, mm = _cajas(vb, r), _cajas(vb * vb, r)
            a = (mm - mu * mu) / (mm - mu * mu + eps)
            b = mu - a * mu
            a, b = _cajas(a, r), _cajas(b, r)
            bases.append(a * vb + b)
        ab_v = (v, bases)
        ab_cache[E_key] = ab_v
    v, bases = ab_v
    if roi is not None:
        y0, y1, x0, x1 = roi
        vf = v[y0:y1, x0:x1]
        nueva = vf + _leer(curvas[0], vf)
        for j, b_j in enumerate(bases, start=1):
            nueva += _leer(curvas[j], b_j[y0:y1, x0:x1])
        lin_r, Y_r = lin[y0:y1, x0:x1], Y[y0:y1, x0:x1]
    else:
        nueva = v + _leer(curvas[0], v)
        for j, b_j in enumerate(bases, start=1):
            nueva += _leer(curvas[j], b_j)
        lin_r, Y_r = lin, Y
    if E > 1.25:
        sobre = np.maximum(nueva - 0.85, 0.0)
        nueva = np.where(nueva <= 0.85, nueva, 0.85 + 0.15 * (1.0 - np.exp(-sobre / 0.15)))
    np.clip(nueva, 0, 1, out=nueva)
    return nueva, lin_r, Y_r


def _L_exacto_desde_nueva(nueva, lin_r, Y_r):
    sc = _leer(_VY, nueva) / np.maximum(Y_r, 1e-6)
    lmax = np.maximum(np.maximum(lin_r[..., 0], lin_r[..., 1]), lin_r[..., 2])
    sc /= np.maximum(lmax * sc, 1.0)
    rgb = _leer(_SR, lin_r * sc[..., None])
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[..., 0]


def proteger_cara(u8, s, cara, _pack500=None):
    """Como hace Lightroom: una cara quemada se baja (una oscura se subiria si CARA_BAJO > 0; desde
    LR219 no se sube: ver arriba de CARA_BAJO). Origen (22-11-2026, foto 4 de
    Victor: la cara del orador quedaba en L* 84 con 23 % al tope; Lightroom la deja en 66). En las
    40 fotos, el Automatico deja la cara bajo 80 en 39 y baja SIEMPRE las caras que vienen quemadas;
    el imitador solo no lo lograba. Se corrige la exposicion mirando la cara principal (cara = x, y,
    ancho, alto en pixeles de u8), con las altas luces al maximo aprendido y algo mas de sombras para
    que el fondo no se hunda. Medido sin ver cada foto: la cara queda a 2,8 L* de la de Lightroom
    (mediana), y la foto 4 a +3,4 (antes +16,6); el parecido general no cambia."""
    if cara is None:
        return s, None
    if _pack500 is not None:
        chica, lin5, Y5, ab_cache = _pack500
    else:
        chica = achicar(u8, 500)
        lin5 = a_lineal(chica)
        Y5 = lin5 @ W
        ab_cache = {}
    k = chica.shape[1] / u8.shape[1]
    x, y, w, h = [float(v) * k for v in cara[:4]]
    cx, cy = x + w / 2, y + h / 2
    y0, y1 = max(0, int(cy - 0.4 * h)), min(chica.shape[0], int(cy + 0.4 * h) + 1)
    x0, x1 = max(0, int(cx - 0.35 * w)), min(chica.shape[1], int(cx + 0.35 * w) + 1)
    if y1 - y0 < 2 or x1 - x0 < 2:
        return s, None
    roi = (y0, y1, x0, x1)

    def luz_cara(t):
        nv, lr, Yr = _revelar_chica_nueva(lin5, Y5, t, ab_cache, roi=roi)
        return float(np.median(_L_exacto_desde_nueva(nv, lr, Yr)))

    s = dict(s)
    L = luz_cara(s)
    antes, pasos = L, 0
    if L > CARA_ALTO:
        s["Highlights2012"] = min(s["Highlights2012"], -80.0)
        while L > CARA_ALTO and s["Exposure2012"] > -1.0 and pasos < 20:
            s["Exposure2012"] -= 0.1
            s["Shadows2012"] = min(66.0, s["Shadows2012"] + 3.0)
            pasos += 1
            L = luz_cara(s)
    elif L < CARA_BAJO:
        while L < CARA_BAJO and s["Exposure2012"] < 1.0 and pasos < 20:
            s["Exposure2012"] += 0.1
            pasos += 1
            L = luz_cara(s)
    return s, (antes, L) if pasos else None


def escalar(s, fuerza=1.0, luz=1.0, contraste=1.0, color=1.0):
    """Los controles de VSO (fuerza, luz, contraste, color; 1 = normal) multiplican a los de
    Lightroom. Con todo en 1 quedan tal cual."""
    m = modelo()
    rangos = dict(zip(m["meta"]["K"], m["rangos"]))
    t = dict(s)
    for k, f in (("Exposure2012", fuerza * luz), ("Highlights2012", fuerza * luz), ("Shadows2012", fuerza * luz),
                 ("Whites2012", fuerza * contraste), ("Blacks2012", fuerza * contraste),
                 ("Vibrance", fuerza * color), ("Saturation", fuerza * color)):
        lo, hi = rangos[k]
        t[k] = float(np.clip(s[k] * f, min(lo, 0.0), max(hi, 0.0)))
    return t


# ---------------------------------------------------------------- 2. revelar como Lightroom
def _controles_luz(s):
    E = float(np.clip(s["Exposure2012"], -1.2, 1.4))
    return np.array([1.0, max(E, 0.0), min(E, 0.0), s["Highlights2012"] / 100, s["Shadows2012"] / 100,
                     s["Whites2012"] / 100, s["Blacks2012"] / 100], np.float32)


def ganancias_wb(temperatura=0.0, matiz=0.0):
    """Ganancias RGB en luz lineal para temperatura (-1..1: frio..calido) y matiz (-1..1: verde..magenta),
    conservando la luminosidad (Y). None si ambos son 0."""
    if not temperatura and not matiz:
        return None
    g = np.array([
        (1.0 + 0.30 * temperatura) * (1.0 + 0.14 * matiz),
        (1.0 + 0.04 * temperatura) * (1.0 - 0.24 * matiz),
        (1.0 - 0.30 * temperatura) * (1.0 + 0.14 * matiz),
    ], np.float32)
    g = np.maximum(g, 0.25)
    g /= (W[0] * g[0] + W[1] * g[1] + W[2] * g[2])
    return g


def aplicar_retoques_controles(s, retoques):
    """Aplica exposicion, altas_luces y sombras de Pro (-100..+100) directo sobre los controles de Lightroom
    antes de revelar (sin doble cuantizacion a 8 bits). Devuelve (s_nuevo, wb, fuerza_blanco)."""
    if not retoques:
        return s, None, 1.0
    t = dict(s)
    e = retoques.get("exposicion", 0) / 100.0
    h = retoques.get("altas_luces", 0)
    sh = retoques.get("sombras", 0)
    temp = retoques.get("temperatura", 0) / 100.0
    mat = retoques.get("matiz", 0) / 100.0
    if e:
        t["Exposure2012"] = float(np.clip(t["Exposure2012"] + 1.5 * e, -2.5, 2.5))
    if h:
        t["Highlights2012"] = float(np.clip(t["Highlights2012"] + h, -120.0, 100.0))
    if sh:
        t["Shadows2012"] = float(np.clip(t["Shadows2012"] + sh, -100.0, 120.0))
    wb = ganancias_wb(temp, mat)
    # Si el usuario oscurece a proposito (exposicion o altas luces negativas), blanco_limpio cede paso
    # para que pueda recuperar camisas, vestidos o fondos muy brillantes
    fuerza_blanco = float(np.clip(1.0 + min(0.0, e / 0.6) + min(0.0, (h / 100.0) / 0.6), 0.0, 1.0))
    return t, wb, fuerza_blanco


def _cajas(I, r):
    return cv2.boxFilter(I, -1, (2 * r + 1, 2 * r + 1))


def _bases_chicas(u8, E, wb=None):
    """Coeficientes (a, b) del filtro guiado a LADO_BASE px (sin agrandar a tamano completo).
    El motor nativo los interpola bilinealmente fila a fila en cache L1 (ahorra ~600 MB de RAM)."""
    m = modelo()
    chica = achicar(u8, LADO_BASE)
    lin_c = a_lineal(chica)
    if wb is not None:
        lin_c = lin_c * wb
    v = np.minimum(Y_a_v((lin_c @ W) * 2.0 ** E), 1.4)
    lado = max(chica.shape[:2])
    eps = float(m["EPS"])
    ab = []
    for rad in m["RADIOS"]:
        r = max(1, round(float(rad) * lado))
        mu, mm = _cajas(v, r), _cajas(v * v, r)
        a = (mm - mu * mu) / (mm - mu * mu + eps)
        b = mu - a * mu
        ab.append((np.ascontiguousarray(_cajas(a, r), np.float32),
                   np.ascontiguousarray(_cajas(b, r), np.float32)))
    return ab


def _bases(u8, E, forma, wb=None):
    """Luz de cada zona (filtro guiado a 600 px, como al aprender), llevada al tamano completo con
    el truco del filtro guiado rapido (se agrandan sus coeficientes a y b, no la base): los bordes
    quedan nitidos y no hay halos."""
    ab_chicas = _bases_chicas(u8, E, wb=wb)
    ab = []
    for a, b in ab_chicas:
        if forma != a.shape:
            a = cv2.resize(a, (forma[1], forma[0]), interpolation=cv2.INTER_LINEAR)
            b = cv2.resize(b, (forma[1], forma[0]), interpolation=cv2.INTER_LINEAR)
        ab.append((a, b))
    return ab


_COLOR_BASIS = None


def _color_tablas(s):
    """Tablas del cambio de croma para estos controles: (croma x tono), (croma x luz) y, para lo que
    se aclaro la zona, (croma). Se leen con interpolacion lineal (cv2.remap), igual que las curvas
    del modelo (que son lineales por tramos), pero mucho mas rapido que evaluarlas pixel a pixel."""
    global _COLOR_BASIS
    m = modelo()
    KC, KL, NH = m["KC"], m["KL"], int(m["NH"])
    nk, nfh, nfl = len(KC), 1 + 2 * NH, len(KL)
    cc = m["coef_color"]
    c = np.array([1.0, s["Vibrance"] / 100, s["Saturation"] / 100])
    nb = nk * (nfh + nfl)
    w = sum(c[i] * cc[i * nb:(i + 1) * nb] for i in range(3))
    WA = w[:nk * nfh].reshape(nk, nfh)
    WB = w[nk * nfh:].reshape(nk, nfl)
    if _COLOR_BASIS is None:
        cs = np.linspace(0, 1, N_CROMA)
        fc = _sombreros(cs, KC)
        hs = np.linspace(0, 2 * np.pi, N_TONO)
        fh = np.stack([np.ones_like(hs)] + [fn(k * hs) for k in range(1, NH + 1) for fn in (np.cos, np.sin)], -1)
        ls = np.linspace(0, 1, N_LUZ)
        fl = _sombreros(ls, KL)
        D = cc[3 * nb:3 * nb + nk]
        D2 = cc[3 * nb + nk:3 * nb + 2 * nk]
        T_d_fija = np.ascontiguousarray(np.stack([fc @ D, fc @ D2], -1), np.float32)
        _COLOR_BASIS = (fc, fh.T.copy(), fl.T.copy(), T_d_fija)
    fc, fhT, flT, T_d = _COLOR_BASIS
    T_tono = (fc @ WA @ fhT).astype(np.float32)          # N_CROMA x N_TONO
    T_luz = (fc @ WB @ flT).astype(np.float32)           # N_CROMA x N_LUZ
    return T_tono, T_luz, T_d


N_CROMA, N_TONO, N_LUZ = 401, 361, 101


def _sombreros(x, kn):
    h = float(kn[1] - kn[0])
    return np.clip(1 - np.abs(np.asarray(x)[..., None] - kn) / h, 0, None)


def _tabla_curva(nudos, valores, n=16384):
    """Curva lineal por tramos -> tabla fina sobre [nudos[0], nudos[-1]] (se lee al mas cercano:
    con 16384 niveles el error es < 0,0002 de L*/100)."""
    x = np.linspace(nudos[0], nudos[-1], n)
    return np.interp(x, nudos, valores).astype(np.float32), float(nudos[0]), (n - 1) / float(nudos[-1] - nudos[0])


def _leer(tabla, x):
    t, x0, k = tabla
    i = (x - np.float32(x0)) * np.float32(k) + np.float32(0.5)
    np.clip(i, 0, len(t) - 1, out=i)
    return t[i.astype(np.int32)]


# Conversiones de luz con tablas (en vez de potencias pixel a pixel): error < 0,0003
_YV = (Y_a_v(np.linspace(0, 2.2, 65536)).astype(np.float32), 0.0, 65535 / 2.2)
_VY = (v_a_Y(np.linspace(0, 1.0, 16384)).astype(np.float32), 0.0, 16383.0)
_SR = (a_srgb(np.linspace(0, 1.0, 16384)).astype(np.float32), 0.0, 16383.0)


def revelar(u8, s, filas=FILAS, wb=None):
    """Foto (RGB uint8, tamano completo) revelada con los controles s. Devuelve Lab float32
    (L 0..100) y la luz original (L*/100), para las mascaras de VSO.
    wb: ganancias RGB lineales (temperatura/matiz de Pro), o None (camino identico a VSO 1.2)."""
    m = modelo()
    KN = m["KN"].astype(np.float64)
    nb = 1 + len(m["RADIOS"])
    Cl = m["coef_luz"].reshape(len(m["meta"]["CONTROLES"]), nb, len(KN))
    c = _controles_luz(s)
    curvas = [_tabla_curva(KN, c @ Cl[:, j, :]) for j in range(nb)]
    E = float(s["Exposure2012"])
    alto, ancho = u8.shape[:2]
    ab = _bases(u8, E, (alto, ancho), wb=wb)
    T_tono, T_luz, T_d = _color_tablas(s)
    lab = np.empty((alto, ancho, 3), np.float32)
    v_orig = np.empty((alto, ancho), np.float32)
    g = np.float32(2.0 ** E)
    extra_alto = E > 1.25  # solo si Pro empujo la exposicion mas alla de lo aprendido
    kc, kh, kl = np.float32((N_CROMA - 1) / 100.0), np.float32((N_TONO - 1) / (2 * np.pi)), np.float32((N_LUZ - 1) / 100.0)
    T_d1, T_d2 = T_d[:, :1].T.copy(), T_d[:, 1:].T.copy()

    def franja(f):
        lin = a_lineal(u8[f])
        if wb is not None:
            lin = lin * wb
        Y = lin @ W
        v0 = _leer(_YV, Y)
        v_orig[f] = v0
        Yg = Y * g
        if extra_alto:
            v = np.where(Yg <= 2.2, _leer(_YV, Yg), Y_a_v(Yg))
        else:
            v = _leer(_YV, Yg)
        nueva = v + _leer(curvas[0], v)
        vb = np.minimum(v, 1.4)
        for j, (a, b) in enumerate(ab, start=1):
            nueva += _leer(curvas[j], a[f] * vb + b[f])
        if extra_alto:
            # hombro suave en luces altas cuando Pro empuja exposicion muy arriba (evita corte brusco)
            sobre = np.maximum(nueva - 0.85, 0.0)
            nueva = np.where(nueva <= 0.85, nueva, 0.85 + 0.15 * (1.0 - np.exp(-sobre / 0.15)))
        np.clip(nueva, 0, 1, out=nueva)
        sc = _leer(_VY, nueva) / np.maximum(Y, 1e-6)
        # Si un canal pasa del tope (azul intenso o piel muy clara al aclarar), se baja todo el pixel
        # parejo: conserva el tono. Recortar solo ese canal volvia lavanda/morado el azul (foto 4)
        lmax = np.maximum(np.maximum(lin[..., 0], lin[..., 1]), lin[..., 2])
        sc /= np.maximum(lmax * sc, 1.0)
        rgb = _leer(_SR, lin * sc[..., None])
        tira = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        # color: cambio de croma segun croma, tono, luz y cuanto se aclaro la zona
        C, h = cv2.cartToPolar(tira[..., 1], tira[..., 2])
        fila_c = np.minimum(C, 100.0) * kc
        dC = cv2.remap(T_tono, h * kh, fila_c, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        dC += cv2.remap(T_luz, tira[..., 0] * kl, fila_c, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        dlum = nueva - v0
        ic = np.minimum(fila_c.astype(np.int32), N_CROMA - 2)
        wc = fila_c - ic
        td1 = T_d[ic, 0] * (1.0 - wc) + T_d[ic + 1, 0] * wc
        td2 = T_d[ic, 1] * (1.0 - wc) + T_d[ic + 1, 1] * wc
        dC += td1 * dlum + td2 * np.abs(dlum)
        Cn = C * np.float32(0.01)
        k2 = np.maximum(Cn + dC, 0) / np.maximum(Cn, 1e-4)
        tira[..., 1] *= k2
        tira[..., 2] *= k2
        lab[f] = tira
    _por_franjas(franja, alto, filas)
    return lab, v_orig


def texto(s):
    return ("Lightroom auto: expo {:+.2f}, altas {:+.0f}, sombras {:+.0f}, negros {:+.0f}, intensidad {:+.0f}"
            .format(s["Exposure2012"], s["Highlights2012"], s["Shadows2012"], s["Blacks2012"], s["Vibrance"]))


# ---------------------------------------------------------------------------------------------------
# PROPUESTA «A TU GUSTO» CORREGIDA (aprobada por Victor el 23-11-2026; laminas en Desktop\Pruebas con
# Lightroom 2\06, 07, 08 y 09). Encima del Automatico de Lightroom: caras claras, negros firmes, blancos
# limpios y sin quemar, grupos sin aclarar de mas. Probado en las 219 fotos de la tanda 2 con
# variante_correr.py (propuesta5) y en las camisas blancas del Juan Terrier 4F.
ALTAS_X = 0.5          # las altas luces se bajan la mitad de lo que diria Lightroom
NEGROS_MAS = -15.0     # negros mas profundos
NEGROS_SUBIDA = 30.0   # negros que se restan por cada paso (EV) que se sube la exposicion por la cara
BLANCOS_LIM = 0.5      # % maximo de la foto en L* 99 o mas (o 1,2 veces lo que ya venia quemado)
GRUPO_MAX = 0.3        # en fotos de grupo (3 caras o mas, cara < 7 % del ancho) la cara sube la foto 0,3 EV como maximo
BLANCO_LIMPIO = 3.0    # lo que ya era blanco y sin color no baja mas de 3 puntos de L* (camisas blancas)


def _paso(x, a, b):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def controles(u8, caras):
    """Controles finales del estilo: los del Automatico de Lightroom (predecir) con el gusto de Victor.
    caras: las de detectar_caras (x, y, ancho, alto, ...) en pixeles de u8. Devuelve (controles, cambio)
    como proteger_cara (cambio = (cara antes, cara despues) o None)."""
    s0 = dict(predecir(u8))
    s0["Highlights2012"] *= ALTAS_X
    s0["Blacks2012"] += NEGROS_MAS
    # Compartir copia de 500 px, luz lineal y cache de bases entre proteger_cara y el freno de blancos
    chica = achicar(u8, 500)
    lin5 = a_lineal(chica)
    Y5 = lin5 @ W
    ab_cache = {}
    pack500 = (chica, lin5, Y5, ab_cache)

    cara = max(caras, key=lambda c: c[2] * c[3]) if caras else None
    s1, cambio = proteger_cara(u8, s0, cara, _pack500=pack500)
    sube = s1["Exposure2012"] - s0["Exposure2012"]
    if cara is not None and sube > GRUPO_MAX and float(cara[2]) < 0.07 * u8.shape[1] and len(caras) >= 3:
        # foto de grupo: no se aclara la foto entera para subir una cara chica (amigos 27 del 4F)
        s1 = dict(s1)
        s1["Exposure2012"] = s0["Exposure2012"] + GRUPO_MAX
        sube = GRUPO_MAX
        cambio = None
    if sube > 0:
        s1 = dict(s1)
        s1["Blacks2012"] = max(-100.0, s1["Blacks2012"] - NEGROS_SUBIDA * sube)
    # freno a los blancos quemados: primero altas luces, despues blancos
    lim = max(BLANCOS_LIM, 1.2 * float((chica.min(-1) >= 253).mean() * 100))

    def quemado(t):
        nv, lr, Yr = _revelar_chica_nueva(lin5, Y5, t, ab_cache, roi=None)
        cand = nv >= 0.98
        if not cand.any():
            return 0.0
        nv_c = nv[cand]
        sc = _leer(_VY, nv_c) / np.maximum(Yr[cand], 1e-6)
        lr_c = lr[cand]
        lmax = np.maximum(np.maximum(lr_c[:, 0], lr_c[:, 1]), lr_c[:, 2])
        sc /= np.maximum(lmax * sc, 1.0)
        rgb_c = _leer(_SR, lr_c * sc[:, None])
        L_c = cv2.cvtColor(rgb_c[None, :, :], cv2.COLOR_RGB2LAB)[0, :, 0]
        return float((L_c >= 99.0).sum() * 100.0 / nv.size)

    q, pasos = quemado(s1), 0
    while q > lim and pasos < 12:
        s1 = dict(s1)
        if s1["Highlights2012"] > -100.0:
            s1["Highlights2012"] = max(-100.0, s1["Highlights2012"] - 20.0)
        elif s1["Whites2012"] > -50.0:
            s1["Whites2012"] -= 10.0
        else:
            break
        pasos += 1
        q = quemado(s1)
    return s1, cambio


def _desenfocar_caras(m, sigma, cajas):
    """Igual que cv2.GaussianBlur(m, (0, 0), sigma) para la mascara de caras (todo 1 salvo las
    elipses en 0), pero desenfocando solo el rectangulo que rodea las caras: lejos de ellas el
    resultado es el mismo numero en todas partes. Con un desenfoque de ~40 px en la foto entera se
    iban ~0,75 s por foto. El recorte empieza y termina en columnas multiplo de 64 (asi OpenCV suma
    igual que con la foto entera): probado con 60 mascaras al azar y las fotos del lote de prueba,
    numeros identicos (24-11-2026)."""
    alto, ancho = m.shape
    r = (int(round(sigma * 8 + 1)) | 1) // 2 + 2      # radio del nucleo de OpenCV para float32, con margen
    lado = 4 * r + 8
    lejos = cv2.GaussianBlur(np.ones((lado, lado), np.float32), (0, 0), sigma)[lado // 2, lado // 2]
    x0, y0 = min(c[0] for c in cajas), min(c[1] for c in cajas)
    x1, y1 = max(c[2] for c in cajas), max(c[3] for c in cajas)
    ix0, iy0, ix1, iy1 = max(0, x0 - r), max(0, y0 - r), min(ancho, x1 + r), min(alto, y1 + r)
    if ix0 >= ix1 or iy0 >= iy1:
        return cv2.GaussianBlur(m, (0, 0), sigma)
    cx0, cy0 = max(0, ix0 - r) // 64 * 64, max(0, iy0 - r)
    cx1, cy1 = min(ancho, -(-(ix1 + r) // 64) * 64), min(alto, iy1 + r)
    if (cx1 - cx0) * (cy1 - cy0) > 0.8 * alto * ancho:   # caras por toda la foto: no se gana nada
        return cv2.GaussianBlur(m, (0, 0), sigma)
    salida = np.full_like(m, lejos)
    b = cv2.GaussianBlur(np.ascontiguousarray(m[cy0:cy1, cx0:cx1]), (0, 0), sigma)
    salida[iy0:iy1, ix0:ix1] = b[iy0 - cy0:iy1 - cy0, ix0 - cx0:ix1 - cx0]
    return salida


def blanco_limpio(u8, lab, caras, ancho_caras, fuerza=1.0):
    """Despues de revelar: lo que en la foto original ya era blanco y sin color (camisas, muros) no queda
    mas de BLANCO_LIMPIO puntos de L* bajo el original, para que no se vuelva gris. Nunca toca la piel:
    ni las caras (elipse algo mas grande que la caja; en la propuesta 4 la 123 quedo con manchas) ni piel
    suelta (tono calido). ancho_caras: ancho de la foto donde se buscaron las caras."""
    if fuerza <= 0.0:
        return lab
    # 24-11-2026: lo pixel a pixel va en franjas, en varios nucleos (mismos numeros que antes)
    alto, ancho = u8.shape[:2]
    k = ancho / float(ancho_caras)
    m = np.ones((alto, ancho), np.float32)
    cajas = []
    for c in caras or []:
        x, y, cw, ch = [float(v) * k for v in c[:4]]
        centro, ejes = (int(x + cw / 2), int(y + ch / 2)), (max(1, int(0.75 * cw)), max(1, int(0.85 * ch)))
        cv2.ellipse(m, centro, ejes, 0, 0, 360, 0.0, -1)
        cajas.append((centro[0] - ejes[0] - 2, centro[1] - ejes[1] - 2, centro[0] + ejes[0] + 3, centro[1] + ejes[1] + 3))
    if caras:
        m = _desenfocar_caras(m, max(1.0, 0.01 * ancho), cajas)
    Lo = np.empty((alto, ancho), np.float32)
    w = np.empty((alto, ancho), np.float32)

    def franja(f):
        o = cv2.cvtColor(np.ascontiguousarray(u8[f]), cv2.COLOR_RGB2LAB).astype(np.float32)  # L 0..255, a/b +128
        Lo[f] = o[..., 0] * (100.0 / 255.0)
        ao, bo = o[..., 1] - 128.0, o[..., 2] - 128.0
        Co = np.hypot(ao, bo)
        wf = _paso(Lo[f], 80.0, 92.0) * (1.0 - _paso(Co, 8.0, 16.0))
        ang = np.degrees(np.arctan2(bo, ao))
        piel = _paso(Co, 4.0, 8.0) * _paso(ang, 15.0, 30.0) * (1.0 - _paso(ang, 70.0, 85.0))
        wf *= (1.0 - piel) * m[f]
        w[f] = wf
    _por_franjas(franja, alto)
    w = cv2.GaussianBlur(w, (0, 0), 1.5)
    f_esc = np.float32(fuerza)

    def franja(f):
        lab[f, :, 0] += (w[f] * f_esc) * np.maximum(0.0, (Lo[f] - BLANCO_LIMPIO) - lab[f, :, 0])
    _por_franjas(franja, alto)
    return lab
