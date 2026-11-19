"""
AJUSTE COMBINADO (2026-10-24): el motor de mejorar_fotos.py (version del 2026-10-18, MD5 b39cb31d...)
con el manejo del color del ajuste de Claude, y los arreglos que salieron de la comparacion de Claude,
Codex, Antigravity y la prueba a ciegas de Victor. Cambios respecto de mejorar_fotos.py:
  - Color segun la foto (color_natural, v2 del 2026-10-24): los colores apagados y normales suben como
    en el motor original, y solo los muy intensos (fondos morados, bandas, magentas) se calman
    (hasta x0,76; rojos x0,88).
  - Balance: despues del balance por la ropa, si los grises de la foto siguen con dominante se corrige
    el 60% (como en el ajuste de Claude), con ganancia por canal: el negro sigue negro (corregir_dominante).
  - Caras: desde 2026-11-18 todas las detecta YuNet (de frente, de perfil, inclinadas o agachadas en
    la uncion). El detector antiguo (Haar), que veia "caras" en ladrillos, cuellos y el telon, se quito;
    sin YuNet no se detectan caras (la exposicion se hace con el brillo de toda la foto).
  - Caras algo mas luminosas (minimo L* 58 en vez de 54), sombras algo menos levantadas (el pelo
    quedaba muy luminoso) y ojos con enfoque mas suave (se veian "pegados").
  - Una foto danada o rara no detiene el lote: se informa y se sigue con las demas.
  - Etapa 1 del PLAN DE MEJORAS (2026-10-25, las fotos salen identicas): un lote cortado se retoma
    sin rehacer lo hecho (--rehacer para forzar), se guarda sin dejar JPG a medias, avisa si falta
    YuNet, si hay fotos repetidas o subcarpetas sin ajustar, elige solo cuantas fotos a la vez, sigue
    aunque se caiga un proceso y corre YuNet una sola vez por foto.
  - Punto 8 (2026-10-26): los ojos y la boca se ubican con los 5 puntos de YuNet (ojos, nariz y
    comisuras), no en una posicion fija de la caja de la cara; el detector de ojos antiguo queda solo
    para las caras sin esos puntos (si falta YuNet).
  - Adobe RGB (2026-11-18): las fotos en Adobe RGB (la Nikon D5300 graba asi, sin perfil) se pasan a
    sRGB al leerlas; antes se trataban como sRGB y salian apagadas. Las demas salen identicas.

Uso:
    python ajuste_combinado.py "C:\\ruta\\a\\la\\carpeta"
    python ajuste_combinado.py foto1.jpg foto2.jpg "otra carpeta" --simultaneas 3

Nunca toca los originales: guarda las fotos en <carpeta>\\combinadas\\
(misma resolucion, mismo nombre, JPG calidad 95, conserva EXIF).
Lo que sigue es la descripcion del motor original (los pasos 1, 3, 5 y los ojos cambiaron como arriba).

Pasos que aplica a cada foto:
  1. Balance de blancos con la ropa clara bajo las caras (camisas, albas, blusas);
     si no hay, con zonas neutras de la foto. Corrige solo en parte, enfria los
     blancos crema y casi nunca calienta (una camisa celeste no entibia la foto).
     En una serie (fotos seguidas con la misma camara y la misma luz) se usa el
     blanco de las fotos vecinas, asi todas quedan parejas (--serie no: cada una sola).
  2. Niveles automaticos suaves (negros y blancos) sin quemar luces.
  3. Exposicion guiada por las caras: si las caras principales estan oscuras o
     quemadas se corrige para ellas; si estan bien, no se cambia (aunque el fondo
     sea muy claro u oscuro). Sin caras, se usa el brillo de toda la foto.
     Aclara las sombras medias y modera las luces, sin tocar el negro ni el blanco
     puros (la foto impresa conserva negros profundos y blancos limpios). Aunque la
     foto se aclare mucho, el casi negro (ropa negra, pelo) no se vuelve gris.
  4. Contraste local suave para dar volumen sin efecto HDR ni halo: respeta los bordes
     (persona contra fondo) y es mas fuerte en fotos planas que en fotos de sol fuerte.
     (Hasta 2026-11-12 era CLAHE, que dejaba una aureola clara alrededor del pelo.)
  5. Vibrancia: satura los colores apagados, protege la piel y los ya saturados.
  6. Enfoque: realza bordes sin realzar el grano y sin halos (contornos blancos)
     alrededor de los bordes fuertes (nivel ajustable con --enfoque).
  7. Colores muy saturados (casullas rojas, fondos morados): si al aclarar se salen
     de lo que el RGB puede mostrar, se aclaran menos en vez de recortarse (sin rojo
     plano tipo coral, conservan los pliegues).
  Piel: en las caras detectadas (y su cuello) aplica menos contraste/enfoque/
     saturacion y empareja el enrojecimiento, para no realzar manchas en la cara.
     Los ojos quedan fuera de esa proteccion: reciben el enfoque completo, y los
     labios no se emparejan con la piel (conservan su rojo).
  0. Antes de todo, mide el ruido de la foto. Si tiene grano (ISO alto, interiores,
     noche) lo reduce automaticamente; si esta limpia no hace nada (no cuesta tiempo).
"""
import argparse
import ctypes
import hashlib
import io
import os
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps

EXTENSIONES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# --- Adobe RGB -> sRGB (2026-11-18) ---------------------------------------------------------------
# La Nikon D5300 graba en Adobe RGB sin perfil: el EXIF dice "espacio de color sin calibrar" (65535) y
# el indice de interoperabilidad "R03". Tratadas como sRGB, salen apagadas. Se convierten al leerlas
# (colorimetrico relativo, como Photoshop: los dos espacios son D65, asi que es una matriz).
_ADOBE_A_XYZ = np.array([[0.5767309, 0.1855540, 0.1881852],
                         [0.2973769, 0.6273491, 0.0752741],
                         [0.0270343, 0.0706872, 0.9911085]])
_XYZ_A_SRGB = np.array([[3.2404542, -1.5371385, -0.4985314],
                        [-0.9692660, 1.8760108, 0.0415560],
                        [0.0556434, -0.2040259, 1.0572252]])
ADOBE_A_SRGB = (_XYZ_A_SRGB @ _ADOBE_A_XYZ).astype(np.float32)
_ADOBE_LINEAL = ((np.arange(256) / 255.0) ** (563 / 256)).astype(np.float32)  # gamma de Adobe RGB
_SRGB_NIVELES = 4096
_s = np.arange(_SRGB_NIVELES) / (_SRGB_NIVELES - 1)
_SRGB_CODIFICA = np.round(255 * np.where(_s <= 0.0031308, 12.92 * _s,
                                         1.055 * np.power(_s, 1 / 2.4) - 0.055)).astype(np.uint8)
del _s


def es_adobe_rgb(im):
    """True si la foto esta en Adobe RGB: perfil incrustado "Adobe RGB", o sin perfil con el EXIF de
    la camara en "sin calibrar" (65535) y sin el indice R98 (sRGB)."""
    icc = im.info.get("icc_profile")
    if icc:
        try:
            desc = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc)))
        except Exception:
            return False
        return "adobe rgb" in desc.lower()
    try:
        ex = im.getexif()
        if ex.get_ifd(0x8769).get(0xA001) != 0xFFFF:
            return False
        try:
            indice = str(ex.get_ifd(0xA005).get(1, "")).strip().upper()
        except Exception:
            indice = ""
        return indice != "R98"
    except Exception:
        return False


def adobe_a_srgb(u8):
    """Pasa un arreglo RGB uint8 de Adobe RGB a sRGB (por franjas: poca RAM con fotos de 24 MP)."""
    salida = np.empty_like(u8)
    for y in range(0, u8.shape[0], 512):
        lin = _ADOBE_LINEAL[u8[y:y + 512]] @ ADOBE_A_SRGB.T
        np.clip(lin, 0.0, 1.0, out=lin)
        salida[y:y + 512] = _SRGB_CODIFICA[(lin * (_SRGB_NIVELES - 1) + 0.5).astype(np.uint16)]
    return salida


def perfil_srgb():
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
# Detector de caras YuNet (modelo de OpenCV, 227 KB) junto a este archivo. Es opcional:
# si falta, el script funciona igual (solo se usa cuando los otros detectores no ven a nadie).
MODELO_YUNET = Path(__file__).with_name("face_detection_yunet_2023mar.onnx")


TONOS = 4096  # resolucion de las tablas de tonos
PIE = 0.30  # bajo este brillo (L* 30; hasta 2026-11-13 era 0.20: el pelo negro quedaba gris) el aclarado se reduce de a poco: el negro sigue negro
PIE_ESCENARIO = 0.40  # pie con fondo negro de escenario y caras con flash (Santa Marta 13-11-2026)
ESCENARIO_CARA = 0.45  # caras al menos asi de claras: el flash las ilumino, lo oscuro es el fondo
ROSADO_A = 4.5  # ropa clara con a* mayor (y mayor que 0,8 b*) es rosada, no blanca
SOMBRA_TIBIA = 3.0  # sombra aclarada con b* sobre esto (pelo cafe) conserva su color; bajo -1 (fria, morada) se neutraliza como antes
PIEL_COLOR = 0.6  # cuanto sube el color de la piel aclarada (0 = nada)
GRIS_DESDE = 40  # la dominante se mide en grises desde L* 40 (un fondo negro calido no es un muro gris)
SOMBRAS_K = 0.85  # cuanto se levantan las sombras medias (el motor original usaba 1,05: pelo muy luminoso)
# Color segun la foto (prueba a ciegas 2: en fotos de color normal Victor eligio el color vivo del motor
# original; en las de colores muy intensos, la version calmada). Los colores normales y apagados suben con
# la vibrancia del motor original (0,42 x 1,1, como con su --fuerza 1.1); desde croma INTENSO_DESDE los
# colores se van calmando y desde INTENSO_HASTA quedan en COLOR_FUERTE (rojos y naranjos en COLOR_ROJO:
# un rojo muy rebajado se ve salmon)
VIBRANCIA = 0.462
INTENSO_DESDE, INTENSO_HASTA = 35.0, 65.0
COLOR_FUERTE, COLOR_ROJO = 0.76, 0.88
# Dominante que queda en los grises despues del balance por la ropa: se corrige una fraccion, hacia
# un gris apenas tibio (a* 0, b* +1). La fria (azulada) y la verdosa se corrigen bien (foto 7 de la
# prueba a ciegas); la calida casi nada: en una iglesia con luz calida, quitarla dejaba la foto fria y
# los muros beige parecen grises (foto 6, donde Victor eligio la del motor original, que la conserva)
FRACCION_FRIA, FRACCION_CALIDA, TOPE_DOMINANTE, GRIS_OBJETIVO = 0.6, 0.2, 4.0, (0.0, 1.0)
# Desde este valor (0..1 por canal) esa correccion se apaga: el blanco puro queda sin tinte. Medido en 195
# fotos del Carmen y El Pilar (2026-10-25): con 0,94 el blanco de camara (255) no cambia en ninguna (antes en
# 108) y los tonos claros (piel con luz, muros) se siguen corrigiendo como los grises; empezar mas abajo no
# limpiaba mas los blancos, solo dejaba los tonos claros sin corregir
LUCES_DESDE = 0.94
YUNET_SOLA = 0.85  # desde esta confianza una cara de YuNet cuenta aunque su centro no parezca piel
OJOS_ENFOQUE = 0.6  # parte del enfoque extra que reciben los ojos (el motor original daba 1: "pegados")


def muestra(arr):
    """Version reducida (1 de cada 4 pixeles por lado) para medir estadisticas rapido."""
    return np.ascontiguousarray(arr[::4, ::4])


_franjas = ThreadPoolExecutor(max_workers=4)


def por_franjas(funcion, alto, partes=4):
    """Corre funcion(filas) en franjas horizontales a la vez (numpy usa un solo nucleo
    por operacion; asi se usan varios). Solo para calculos pixel a pixel, sin vecinos:
    el resultado es identico a hacerlo de una vez."""
    cortes = np.linspace(0, alto, partes + 1).astype(int)
    list(_franjas.map(lambda i: funcion(slice(cortes[i], cortes[i + 1])), range(partes)))


def blanco_ropa(m, caras, paso=4):
    """Color de la ropa clara bajo las caras (camisas, albas, blusas): (L, a*, b*).
    Solo se busca en el pecho de cada persona (asi no cuentan caminos de tierra,
    muros beige ni ventanas) y se usa la mitad mas clara (el blanco, no lo gris). La piel
    que parece ropa clara (escote con flash, manos) no cuenta (piel_del_escote).
    m: muestra uint8 (1 de cada 'paso' pixeles). None si no hay suficiente; False si lo
    claro del pecho era casi todo piel (no hay ropa blanca: no sirve buscar otras caras)."""
    if not caras:
        return None
    zona = np.zeros(m.shape[:2], bool)
    for x, y, w, h, _ in caras:
        x0, x1 = int((x - 0.25 * w) / paso), int((x + 1.25 * w) / paso)
        y0, y1 = int((y + 1.2 * h) / paso), int((y + 3.5 * h) / paso)
        zona[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    lab = cv2.cvtColor(m.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    ok = zona & (L > 60) & (np.sqrt(a * a + b * b) < 16) & (m.max(axis=2) < 250)
    if ok.sum() < 0.002 * ok.size:
        return None
    ropa = ok & ~piel_del_escote(lab, caras, paso)
    if ropa.sum() < 0.25 * ok.sum():  # lo claro del pecho era casi todo piel: no hay ropa blanca
        return False
    # Ropa rosada o lila (vestido de la profesora, corbata rosada) no es blanco: con ella el balance
    # le quitaba el rosado a toda la foto (Santa Marta, licenciatura 13-11-2026: a* +6..+9)
    ropa &= ~((a > ROSADO_A) & (a > 0.8 * b))
    if ropa.sum() < 0.002 * ok.size:
        return None
    claros = ropa & (L >= np.median(L[ropa]))
    return float(np.median(L[claros])), float(np.median(a[claros])), float(np.median(b[claros]))


def piel_del_escote(lab, caras, paso):
    """True donde lo que parece ropa clara bajo una cara es piel. El escote aclarado por el
    flash (L* ~90, a* ~6, b* ~12) pasaba por blanco crema y enfriaba la foto (la cara
    quedaba gris). Se reconoce comparandolo con la piel de su propia cara (mejillas): mismo
    tono y al menos la mitad de su croma. Un alba o blusa crema bajo luz calida tiene el
    mismo tono, pero su cara es mucho mas saturada (alba ~0.3 de su croma, escote 0.5..0.8).
    - En el escote (bajo el menton, al ancho de la cara): tono +-22 grados y croma >= 0.5
      de la cara; los bordes (algo menos parecidos) se suman si tocan esa piel segura.
    - En el resto del pecho (manos en la cadera, hombros), mas estricto: +-18 y >= 0.65;
      con 0.5 se iban blusas y blazers crema de la iglesia.
    Solo con caras de color de piel creible (croma >= 14, no quemadas): el detector antiguo
    (Haar, hasta 2026-11-17) a veces veia una "cara" en el alba misma."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    piel = np.zeros(lab.shape[:2], bool)
    for x, y, w, h, _ in caras:
        mejillas = lab[max(0, int((y + 0.35 * h) / paso)):max(0, int((y + 0.8 * h) / paso)),
                       max(0, int((x + w / 4) / paso)):max(0, int((x + 3 * w / 4) / paso))]
        if mejillas.size == 0:
            continue
        L_cara, a_cara, b_cara = np.median(mejillas.reshape(-1, 3), axis=0)
        croma_cara = float(np.hypot(a_cara, b_cara))
        if croma_cara < 14 or L_cara > 82:
            continue
        y0, x0 = max(0, int((y + 1.2 * h) / paso)), max(0, int((x - 0.25 * w) / paso))
        pecho = (slice(y0, max(0, int((y + 3.5 * h) / paso))), slice(x0, max(0, int((x + 1.25 * w) / paso))))
        croma = np.hypot(a[pecho], b[pecho])
        tono_cara = np.degrees(np.arctan2(b_cara, a_cara))
        giro = np.abs((np.degrees(np.arctan2(b[pecho], a[pecho])) - tono_cara + 180) % 360 - 180)
        clara = (L[pecho] > 60) & (croma >= 9)
        piel[pecho] |= clara & (giro < 18) & (croma >= 0.65 * croma_cara)
        # el escote, dentro del pecho
        escote = (slice(0, max(0, int((y + 2.6 * h) / paso)) - y0),
                  slice(max(0, int(x / paso)) - x0, max(0, int((x + w) / paso)) - x0))
        croma, giro, Le = croma[escote], giro[escote], L[pecho][escote]
        segura = (Le > 60) & (croma >= 9) & (giro < 22) & (croma >= 0.5 * croma_cara)
        if not segura.any():
            continue
        parecida = segura | ((Le > 60) & (croma >= 6) & (giro < 35) & (croma >= 0.35 * croma_cara))
        _, grupos = cv2.connectedComponents(parecida.astype(np.uint8), connectivity=8)
        tocan = np.unique(grupos[segura])
        piel[pecho][escote] |= np.isin(grupos, tocan[tocan > 0])
    return piel


def medir_blanco(u8, m, caras, paso=4):
    """Blanco de referencia de la foto: ((L, a*, b*) o None, de_ropa).
    Primero con la ropa clara de las personas; si no hay, con pixeles casi neutros y
    claros de toda la foto (saturacion baja estricta: en fotos sobreexpuestas los
    colores lavados, ej. fondo morado, casi parecen grises y no deben contar como blanco).
    m: muestra de u8 (1 de cada 'paso' pixeles)."""
    blanco = blanco_ropa(m, caras, paso)
    # (hasta 2026-11-17 habia un segundo intento con el detector Haar de perfiles; YuNet ya ve esas caras)
    if blanco is None:  # segundo: todas las caras de YuNet, tambien las dudosas, con su caja tal cual
        blanco = blanco_ropa(m, caras_principales(detectar_caras_yunet(u8)), paso)
    # False: habia pecho claro, pero era piel. Otras caras serian las mismas personas: no se reintenta
    blanco = blanco or None
    de_ropa = blanco is not None
    if blanco is None:
        hsv = cv2.cvtColor(m, cv2.COLOR_RGB2HSV)
        sat = hsv[..., 1] / 255.0
        val = hsv[..., 2] / 255.0
        mascara = (sat < 0.12) & (val > 0.45) & (val < 0.97)
        if mascara.mean() >= 0.01:  # con menos del 1% neutro no se arriesga
            rgb = m.astype(np.float32) / 255.0
            medio = cv2.cvtColor(rgb[mascara].mean(axis=0)[None, None, :], cv2.COLOR_RGB2LAB)[0, 0]
            blanco = tuple(float(v) for v in medio)
    return blanco, de_ropa


def tablas_color(u8, fuerza_balance, fuerza_niveles, caras=(), blanco_serie=None, gris_serie=None):
    """Balance de blancos + niveles como una tabla por canal (0..255 -> 0..1).

    Las medidas se hacen sobre una muestra; despues aplicar la tabla a toda la foto
    es casi instantaneo. blanco_serie: ((L, a*, b*), de_ropa) comun a la serie (modo
    serie); si viene, no se mide el blanco de esta foto. gris_serie: dominante comun a la
    serie (ver corregir_dominante).
    """
    m = muestra(u8)
    blanco, de_ropa = blanco_serie if blanco_serie is not None else medir_blanco(u8, m, caras)
    tablas = tablas_balance(m, blanco, de_ropa, fuerza_balance, fuerza_niveles)
    return corregir_dominante(m, tablas, fuerza_balance / 0.88, gris_serie)


def tablas_balance(m, blanco, de_ropa, fuerza_balance, fuerza_niveles):
    """Primera pasada: balance de blancos con el blanco de referencia y niveles, como tablas por
    canal (0..255 -> 0..1). m: muestra uint8 de la foto."""
    rgb = m.astype(np.float32) / 255.0
    ganancia = np.ones(3, dtype=np.float32)
    if blanco is not None:
        # Se acerca el blanco a uno apenas calido (a* +1, b* +3: natural en interiores),
        # solo en parte. Enfriar un blanco crema se permite hasta 5 de b*; calentar casi
        # nada: una camisa celeste o una ventana no deben entibiar toda la foto.
        # Calentar aun menos si el blanco es dudoso: sin ropa bajo las caras (el detector
        # de respaldo suele tomar ventanas azuladas) o si la "ropa clara" es azulada
        # (b* < -5: camisa celeste, mezclilla, chaqueta lila o rosada; una camisa blanca
        # de dia nublado queda en -4..-6). Si es azulada tampoco se le quita mucho
        # magenta: con una chaqueta rosada eso verdea la foto.
        L_b, a_b, b_b = blanco
        k = 0.65 * fuerza_balance
        azulado = de_ropa and b_b < -5.0
        tope = 1.0 if de_ropa and not azulado else 0.5
        da = float(np.clip(k * (1.0 - a_b), -1.0 if azulado else -2.5, tope))
        db = float(np.clip(k * (3.0 - b_b), -5.0, tope))
        par = np.array([[[L_b, a_b, b_b]], [[L_b, a_b + da, b_b + db]]], dtype=np.float32)
        antes, despues = cv2.cvtColor(par, cv2.COLOR_LAB2RGB)[:, 0]
        ganancia = np.clip(despues / np.maximum(antes, 1e-4), 0.85, 1.15).astype(np.float32)
    rgb = np.clip(rgb * ganancia, 0, 1)

    # Niveles: negros y blancos
    negro, blanco = np.percentile(rgb.mean(axis=2), [0.1, 99.7])
    negro = min(negro, 0.02)    # solo el 0,1% mas oscuro y poco: no empastar negros
    blanco = max(blanco, 0.85)  # no quemar si la foto ya es oscura

    x = np.arange(256, dtype=np.float32) / 255.0
    tablas = []
    for g in ganancia:
        y = np.clip(x * g, 0, 1)
        estirado = np.clip((y - negro) / (blanco - negro), 0, 1)
        tablas.append(y + (estirado - y) * fuerza_niveles)
    return [t.astype(np.float32) for t in tablas]


def medir_dominante(m, tablas):
    """Color (L*, a*, b*) de las zonas casi grises de la foto (muros, cemento, camisas en sombra)
    despues de las tablas, o None si casi no hay grises. m: muestra uint8 de la foto."""
    rgb = np.stack([tablas[c][m[..., c]] for c in range(3)], axis=-1)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    gris = (np.sqrt(a * a + b * b) < 10) & (L > GRIS_DESDE) & (L < 90)
    if gris.mean() < 0.01:  # casi sin grises: no se arriesga
        return None
    return float(np.median(L[gris])), float(np.median(a[gris])), float(np.median(b[gris]))


def corregir_dominante(m, tablas, fuerza=1.0, gris_serie=None):
    """Segunda pasada de balance (la del ajuste de Claude, que en la comparacion quito la dominante
    en 21 de 23 fotos): si despues del balance por la ropa las zonas casi grises de la foto (muros,
    cemento, camisas en sombra) siguen con dominante, se corrige una parte (FRACCION_FRIA si es fria
    o verdosa, FRACCION_CALIDA si es calida o magenta; como maximo TOPE_DOMINANTE). Asi se entibia
    la luz azulada de la sombra, que el balance por la ropa casi nunca calienta. Va como ganancia por
    canal y normalizada: el negro sigue negro (el ajuste de Claude la sumaba en Lab y tenia las
    sombras) y ningun canal sube (no quema blancos).
    - Las luces mas altas no se tocan (punto 5 del plan, 2026-10-25): la primera pasada ya deja
      blanco el blanco (255,255,254) y esta lo volvia crema (hasta 255,245,237) en la mitad de las
      fotos. La correccion se apaga de a poco desde LUCES_DESDE hasta el blanco puro.
    - gris_serie (punto 6): en una serie se usa la dominante mediana de las fotos vecinas (plan_serie)
      en vez de la de esta foto. Medida foto a foto, cambiaba segun el encuadre (cuanto muro gris
      salia): dos fotos seguidas con la misma luz diferian hasta 5 en el gris.
    m: muestra uint8 de la foto; tablas: las 3 tablas 0..255 -> 0..1 ya calculadas."""
    medida = gris_serie if gris_serie is not None else medir_dominante(m, tablas)
    if medida is None:
        return tablas
    L_m, a_m, b_m = medida
    exceso_a, exceso_b = a_m - GRIS_OBJETIVO[0], b_m - GRIS_OBJETIVO[1]
    fr_a = FRACCION_FRIA if exceso_a < 0 else FRACCION_CALIDA  # verdosa / magenta
    fr_b = FRACCION_FRIA if exceso_b < 0 else FRACCION_CALIDA  # azulada / calida
    da = float(np.clip(-fr_a * fuerza * exceso_a, -TOPE_DOMINANTE, TOPE_DOMINANTE))
    db = float(np.clip(-fr_b * fuerza * exceso_b, -TOPE_DOMINANTE, TOPE_DOMINANTE))
    if abs(da) < 0.6 and abs(db) < 0.6:  # dominante leve: se deja
        return tablas
    par = np.array([[[L_m, a_m, b_m]], [[L_m, a_m + da, b_m + db]]], dtype=np.float32)
    antes, despues = cv2.cvtColor(par, cv2.COLOR_LAB2RGB)[:, 0]
    g = despues / np.maximum(antes, 1e-4)
    g = np.clip(g / g.max(), 0.80, 1.0)
    salida = []
    for t, gi in zip(tablas, g):
        r = np.clip((t - LUCES_DESDE) / (1.0 - LUCES_DESDE), 0, 1)
        apagado = r * r * (3 - 2 * r)  # 0 bajo LUCES_DESDE, 1 en el blanco puro
        salida.append(np.clip(t * (gi + (1.0 - gi) * apagado), 0, 1).astype(np.float32))
    return salida


def sombras_luces(L, sombras, luces):
    """L en 0..1. Aclara las sombras MEDIAS y modera las luces altas, pero el negro
    (0) y el blanco (1) quedan fijos: la foto conserva todo el rango del papel."""
    # Sombras: maximo efecto cerca de L*25; casi nada en el negro profundo
    L = L + sombras * SOMBRAS_K * L ** 1.25 * (1 - L) ** 3
    # Luces: baja un poco los altos (L*60..90) sin tocar el blanco puro
    L = L - luces * 0.35 * L ** 3 * (1 - L)
    return np.clip(L, 0, 1)


def gamma_global(media, luz):
    """Exposicion sin caras: lleva el brillo medio de toda la foto hacia ~0.48."""
    if media <= 0.01 or media >= 0.99:  # foto casi negra o casi blanca: no hay nada que llevar
        return 1.0
    gamma = np.clip(np.log(0.48) / np.log(media), 0.75, 1.25)
    return float(1 + (gamma - 1) * 0.5 * luz)


def curva_tonos(L, gamma, luz, contraste, pie=PIE):
    """Exposicion (gamma) + sombras/luces (luz) + curva S (contraste).
    L puede ser cualquier arreglo."""
    L_entrada = L
    L = np.clip(L ** gamma, 0, 1)
    L = sombras_luces(L, sombras=luz, luces=luz)
    # Curva S suave en medios tonos (da "punch" sin quemar extremos). En la mitad
    # oscura actua a la mitad, para no volver a hundir las sombras que se aclararon.
    s_curva = 0.10 * contraste * (L - 0.5) * (1 - np.abs(2 * L - 1))
    L = np.clip(L + np.where(L < 0.5, 0.5 * s_curva, s_curva), 0, 1)
    # Pie de la curva: al aclarar una foto oscura, la gamma subia el casi negro
    # (ropa negra, pelo, bancas) a gris oscuro: L*8 quedaba en 23. Bajo L* 20 el cambio
    # se aplica de a poco (0 en el negro, completo desde L* 20): ahi sigue negro y las
    # sombras medias y las caras se aclaran igual que antes.
    r = np.clip(L_entrada / pie, 0, 1)
    return L_entrada + (L - L_entrada) * (r * r * (3 - 2 * r))


def tabla_tonos(gamma, luz, contraste, pie=PIE):
    """La curva completa como tabla de luminancia (rapida de aplicar)."""
    return curva_tonos(np.linspace(0, 1, TONOS, dtype=np.float32), gamma, luz, contraste, pie).astype(np.float32)


# ---------------------------------------------------------------------------
# Exposicion guiada por las caras
# ---------------------------------------------------------------------------
_hilo = threading.local()  # un detector por hilo (el balance por serie mide varias fotos a la vez con hilos)
CARA_MIN, CARA_MAX = 0.58, 0.75  # brillo (L*/100) normal de una cara (el motor original usaba 0.54)
# Cara / ropa clara de su pecho en una piel clara o media bien expuesta (medido en 124
# caras: mediana 0.70, cuartil bajo 0.61). Bajo esto, la piel es mas morena.
REL_CLARA = 0.62
# Centro tipico de cada ojo dentro de la caja de la cara (fraccion de ancho y alto;
# medido con el detector de ojos en 171 caras: variacion de +-0.04)
OJOS = ((0.31, 0.385), (0.675, 0.39))
BOCA = (0.48, 0.77)  # centro tipico de la boca (medido por color en 110 caras: +-0.07)


# Caja de YuNet -> caja con la forma de las del detector antiguo (Haar), con la que se calibraron todas las
# cifras que miden desde la cara (pecho de 1,2 a 3,5 altos bajo ella, mejillas, cuello, OJOS, BOCA...).
# Medido el 2026-11-18 en 715 caras de 394 fotos (Carmen, El Pilar, La Matriz, UCM, Santo Tomas, Nikon):
# la de Haar es un cuadrado 1,236 veces el ancho de YuNet (0,957 su alto), con el centro 0,018 altos mas arriba
HAAR_ANCHO, HAAR_ALTO, HAAR_SUBE = 1.236, 0.957, 0.018
YUNET_DUDOSA = 0.35  # bajo YUNET_SOLA, la cara cuenta solo si su centro es piel en mas de esta parte
DE_FRENTE = 0.25     # y si esta de frente: la nariz a menos de esta parte de la distancia entre los ojos del medio


def detectar_caras(u8):
    """Caras [(x, y, ancho, alto, peso)] en coordenadas de la foto completa, todas de YuNet (desde el
    2026-11-18 ya no se usa el detector Haar, el que veia "caras" en ladrillos, cuellos y el telon).
    - Confianza >= YUNET_SOLA: cuentan siempre (asi entraban antes las que Haar no veia).
    - Confianza 0,7 a YUNET_SOLA: solo con color de piel en el centro, el mismo filtro que se le
      pasaba a las de Haar (estas son las que antes entraban como "Haar confirmada por YuNet").
    Cada caja se lleva a la forma de las de Haar (HAAR_*). Lista vacia si falta YuNet."""
    esc, filas = yunet_crudo(u8)
    if filas is None:
        return []
    alto, ancho = u8.shape[:2]
    piel = None
    salida = []
    for f in filas:
        x, y, w, h, conf = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14])
        if w < 24 or h < 24:
            continue
        lado = (HAAR_ANCHO * w + HAAR_ALTO * h) / 2           # en la copia de 1000 px
        cx, cy = x + w / 2, y + h / 2 - HAAR_SUBE * h
        if conf < YUNET_SOLA:
            # Dudosa: cuenta solo de frente (la nariz cerca del medio de los ojos), como las que veia Haar.
            # De lado o mirando abajo (el sacerdote dando la comunion), su caja toma pelo canoso, lentes y
            # cuello blanco, parece una cara muy clara y oscurecia toda la foto (_DSC0798, 0809, 0823)
            ojo1, ojo2, nariz = (float(f[4]), float(f[5])), (float(f[6]), float(f[7])), float(f[8])
            entre_ojos = abs(ojo2[0] - ojo1[0])
            if entre_ojos < 0.25 * w or abs(nariz - (ojo1[0] + ojo2[0]) / 2) > DE_FRENTE * entre_ojos:
                continue
            if piel is None:
                peq = cv2.resize(u8, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA)
                piel = mascara_piel(cv2.cvtColor(peq.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB), paso=1)
            c0, c1 = max(0, int(cx - lado / 4)), max(0, int(cx + lado / 4))
            f0, f1 = max(0, int(cy - lado / 4)), max(0, int(cy + lado / 4))
            centro = piel[f0:f1, c0:c1]
            if centro.size == 0 or centro.mean() <= YUNET_DUDOSA:
                continue
        x0, y0 = max(0, int((cx - lado / 2) / esc)), max(0, int((cy - lado / 2) / esc))
        x1, y1 = min(ancho, int((cx + lado / 2) / esc)), min(alto, int((cy + lado / 2) / esc))
        if x1 - x0 >= 8 and y1 - y0 >= 8:
            salida.append((x0, y0, x1 - x0, y1 - y0, float((x1 - x0) * (y1 - y0))))
    return salida


def iou(a, b):
    """Interseccion sobre union de dos cajas (x, y, ancho, alto, ...)."""
    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return ix * iy / float(a[2] * a[3] + b[2] * b[3] - ix * iy + 1e-9)


CONFIRMA_IOU = 0.1  # superposicion minima para asociar una cara con su deteccion de YuNet (puntos_caras)


def crear_yunet():
    """El detector YuNet, o None si falta el modelo o esta version de OpenCV no lo trae."""
    if not MODELO_YUNET.exists() or not hasattr(cv2, "FaceDetectorYN"):
        return None
    try:
        return cv2.FaceDetectorYN.create(
            "onnx", np.frombuffer(MODELO_YUNET.read_bytes(), np.uint8), np.zeros(0, np.uint8),
            (320, 320), 0.7, 0.3, 5000)  # desde bytes: OpenCV no abre rutas con "ñ" (diseños)
    except cv2.error:
        return None


def yunet_crudo(u8):
    """(escala, filas de YuNet) de la foto, en una copia de 1000 px; filas None si no ve caras o no
    hay detector. Se calcula una sola vez por foto (la usan detectar_caras, puntos_caras y
    medir_blanco); olvidar_yunet() suelta la foto guardada."""
    if not hasattr(_hilo, "yunet"):
        _hilo.yunet = crear_yunet()
    guardada = getattr(_hilo, "yunet_foto", None)
    if guardada is not None and guardada[0] is u8:
        return guardada[1], guardada[2]
    esc = 1000.0 / max(u8.shape[:2])
    caras = None
    if _hilo.yunet is not None:
        peq = cv2.resize(u8, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA)
        _hilo.yunet.setInputSize((peq.shape[1], peq.shape[0]))
        _, caras = _hilo.yunet.detect(cv2.cvtColor(peq, cv2.COLOR_RGB2BGR))
    _hilo.yunet_foto = (u8, esc, caras)
    return esc, caras


def olvidar_yunet():
    """Suelta la foto que guarda yunet_crudo (asi no queda ocupando memoria hasta la siguiente)."""
    _hilo.yunet_foto = None


def detectar_caras_yunet(u8):
    """Todas las caras [(x, y, ancho, alto, peso)] que ve YuNet, con su caja tal cual (sin filtro de
    piel ni de confianza). Lista vacia si no esta el modelo o esta version de OpenCV no lo trae."""
    esc, caras = yunet_crudo(u8)
    if caras is None:
        return []
    return [(int(x / esc), int(y / esc), int(w / esc), int(h / esc), float(w * h / esc / esc))
            for x, y, w, h in caras[:, :4] if w > 0 and h > 0]


def puntos_caras(u8, caras):
    """Ojos y comisuras de cada cara segun YuNet, en coordenadas de la foto: una lista paralela a
    'caras' con {"ojos": (izq, der), "boca": (izq, der)} (cada punto (x, y), de izquierda a derecha
    en la foto) o None. Se usa la deteccion de YuNet que mas se superpone con la cara (la caja de la
    cara es la de YuNet llevada a la forma antigua). Queda None si YuNet no esta, si no hay una que coincida
    o si los puntos no tienen forma de cara (ojos muy juntos o separados, boca fuera de lugar):
    entonces esa cara usa la posicion tipica, como antes."""
    esc, filas = yunet_crudo(u8)
    salida = []
    for cara in caras:
        x, y, w, h = cara[:4]
        mejor, fila = CONFIRMA_IOU, None
        for f in (filas if filas is not None else ()):
            caja = (f[0] / esc, f[1] / esc, f[2] / esc, f[3] / esc)
            if caja[2] > 0 and caja[3] > 0 and iou(cara, caja) >= mejor:
                mejor, fila = iou(cara, caja), f
        if fila is None:
            salida.append(None)
            continue
        p = [(float(fila[i]) / esc, float(fila[i + 1]) / esc) for i in range(4, 14, 2)]
        ojos = tuple(sorted(p[:2]))
        boca = tuple(sorted(p[3:5]))
        d = np.hypot(ojos[1][0] - ojos[0][0], ojos[1][1] - ojos[0][1])  # distancia entre los ojos
        medio_ojos = ((ojos[0][0] + ojos[1][0]) / 2, (ojos[0][1] + ojos[1][1]) / 2)
        medio_boca = ((boca[0][0] + boca[1][0]) / 2, (boca[0][1] + boca[1][1]) / 2)
        bajada = np.hypot(medio_boca[0] - medio_ojos[0], medio_boca[1] - medio_ojos[1])
        dentro = all(x - 0.15 * w <= px <= x + 1.15 * w and y - 0.15 * h <= py <= y + 1.15 * h for px, py in p)
        if dentro and 0.2 * w <= d <= 0.8 * w and 0.6 * d <= bajada <= 1.8 * d:
            salida.append({"ojos": ojos, "boca": boca})
        else:
            salida.append(None)
    return salida


def caras_principales(caras):
    """Para la exposicion: las caras chicas del fondo no cuentan (se ignoran las
    menores a 1/4 del ancho de la cara mas grande; el resto pesa segun su area)."""
    if not caras:
        return []
    mayor = max(c[2] for c in caras)
    return [c for c in caras if c[2] >= mayor / 4]


def zona_caras(alto, ancho, caras, paso):
    """0..1 alrededor de cada cara detectada: cara, frente, menton y cuello.
    'paso' es la reduccion de la imagen donde se dibuja (coordenadas / paso)."""
    zona = np.zeros((alto, ancho), np.float32)
    for x, y, w, h, _ in caras:
        x, y, w, h = x / paso, y / paso, w / paso, h / paso
        cx = int(x + w / 2)
        cv2.ellipse(zona, (cx, int(y + 0.55 * h)), (int(0.75 * w), int(0.95 * h)), 0, 0, 360, 1.0, -1)
        cv2.ellipse(zona, (cx, int(y + 1.30 * h)), (int(0.45 * w), int(0.45 * h)), 0, 0, 360, 1.0, -1)
    return cv2.GaussianBlur(zona, (0, 0), max(1.0, np.mean([c[2] for c in caras]) / paso / 8))


def zona_ojos(u8, caras, puntos):
    """Ojos de cada cara frontal: [(y0, y1, x0, x1, mascara 0..1)], un recorte por cara.
    Ahi el enfoque va completo: la mascara de piel (difuminada, y el iris cafe tiene
    tono de piel) les quitaba la mitad. Van donde YuNet puso los ojos ('puntos' de
    puntos_caras), con la elipse del tamano del ojo y girada como la cabeza. Sin esos
    puntos se buscan con el detector de ojos en la mitad superior de la cara; si no lo
    encuentra (ojos cerrados, lentes, cara chica) se usa la posicion tipica. La elipse
    es justa (ojo y pestanas): ojeras y patas de gallo siguen protegidas."""
    alto, ancho = u8.shape[:2]
    zonas = []
    for (x, y, w, h, _), p in zip(caras, puntos):
        if p is not None:
            (ax, ay), (bx, by) = p["ojos"]
            d = np.hypot(bx - ax, by - ay)
            giro = float(np.degrees(np.arctan2(by - ay, bx - ax)))
            # ojo y pestanas: medio ancho 0,24 y medio alto 0,14 de la distancia entre ojos (lo mismo que
            # la elipse de antes en una cara tipica, pero sin depender de como corto la caja el detector)
            ejes = (max(1, int(0.24 * d)), max(1, int(0.14 * d)))
            suave = max(1.0, 0.055 * d)
            margen = ejes[0] + 3 * suave
            y0, y1 = max(0, int(min(ay, by) - margen)), min(alto, int(max(ay, by) + margen) + 1)
            x0, x1 = max(0, int(ax - margen)), min(ancho, int(bx + margen) + 1)
            if y1 <= y0 or x1 <= x0:
                continue
            m = np.zeros((y1 - y0, x1 - x0), np.float32)
            for cx, cy in p["ojos"]:
                cv2.ellipse(m, (int(round(cx - x0)), int(round(cy - y0))), ejes, giro, 0, 360, 1.0, -1)
            zonas.append((y0, y1, x0, x1, cv2.GaussianBlur(m, (0, 0), suave)))
            continue
        if not hasattr(_hilo, "ojo"):
            _hilo.ojo = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
        centros = [(x + fx * w, y + fy * h) for fx, fy in OJOS]
        e = 200.0 / w  # la mitad superior de la cara a 200 px de ancho
        rec = u8[y:y + 5 * h // 8, x:x + w]
        gris = cv2.equalizeHist(cv2.cvtColor(
            cv2.resize(rec, None, fx=e, fy=e, interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY))
        mejor = [0.1, 0.1]  # solo detecciones cerca de la posicion tipica (no cejas ni lentes)
        for ex, ey, ew, eh in _hilo.ojo.detectMultiScale(gris, 1.1, 5, minSize=(20, 20)):
            cx, cy = x + (ex + ew / 2) / e, y + (ey + eh / 2) / e
            lado = 0 if cx < x + w / 2 else 1
            tx, ty = x + OJOS[lado][0] * w, y + OJOS[lado][1] * h
            dist = max(abs(cx - tx) / w, abs(cy - ty) / h)
            if dist < mejor[lado]:
                mejor[lado], centros[lado] = dist, (cx, cy)
        suave = max(1.0, 0.025 * w)
        y0, y1 = max(0, int(y + 0.2 * h)), min(alto, int(y + 0.6 * h))
        x0, x1 = max(0, int(x + 0.05 * w)), min(ancho, int(x + 0.95 * w))
        if y1 <= y0 or x1 <= x0:
            continue
        m = np.zeros((y1 - y0, x1 - x0), np.float32)
        for cx, cy in centros:
            cv2.ellipse(m, (int(cx - x0), int(cy - y0)), (max(1, int(0.11 * w)), max(1, int(0.065 * h))),
                        0, 0, 360, 1.0, -1)
        zonas.append((y0, y1, x0, x1, cv2.GaussianBlur(m, (0, 0), suave)))
    return zonas


def zona_labios(lab, caras, puntos):
    """Labios de cada cara frontal: [(y0, y1, x0, x1, mascara 0..1, (a, b) de la piel)].
    Se buscan por color (mas rojos que las mejillas de esa misma cara) solo cerca de
    la boca: asi no cuentan la nariz, granitos lejanos ni cosas rojas del fondo. Se
    queda con las manchas grandes (labio de arriba y de abajo). Primero se busca entre
    las comisuras que vio YuNet ('puntos' de puntos_caras) y, si ahi no aparece una boca,
    en la posicion tipica como antes (YuNet a veces pone las comisuras algo altas, y en
    una sonrisa la piel rojiza bajo la nariz agranda la mancha): medido el 2026-10-26 en
    446 caras, asi se encuentran mas labios que con cualquiera de las dos sola."""
    alto, ancho = lab.shape[:2]
    zonas = []
    for (x, y, w, h, _), p in zip(caras, puntos):
        if w < 60:  # cara muy chica: no se distingue la boca
            continue
        # Piel de referencia: las dos mejillas
        mej = np.concatenate([lab[int(y + 0.45 * h):int(y + 0.62 * h), int(x + fx0 * w):int(x + fx1 * w)].reshape(-1, 3)
                              for fx0, fx1 in ((0.18, 0.35), (0.65, 0.82))])
        if len(mej) == 0:
            continue
        croma = np.sqrt(mej[:, 1] ** 2 + mej[:, 2] ** 2)
        tono = np.degrees(np.arctan2(mej[:, 2], mej[:, 1]))
        mej = mej[(tono > 20) & (tono < 80) & (croma > 8) & (croma < 50) & (mej[:, 0] > 25)]
        if len(mej) < 50:
            continue
        L_ref, a_ref, b_ref = (float(v) for v in np.median(mej, axis=0))
        t_ref = float(np.degrees(np.arctan2(b_ref, a_ref)))
        lugares = []  # (centro de la boca, recuadro donde buscar)
        if p is not None:
            # el centro de los labios queda 0,016 del alto de la cara bajo el medio de las comisuras
            # (mediana de 211 caras); el recuadro es el de antes, pero alrededor de esa boca
            (ax, ay), (bx, by) = p["boca"]
            cx, cy = (ax + bx) / 2, (ay + by) / 2 + 0.016 * h
            lugares.append(((cx, cy), (int(cy - 0.11 * h), int(cy + 0.13 * h), int(cx - 0.22 * w), int(cx + 0.26 * w))))
        lugares.append(((x + BOCA[0] * w, y + BOCA[1] * h),
                        (int(y + 0.66 * h), int(y + 0.90 * h), int(x + 0.26 * w), int(x + 0.74 * w))))
        for (boca_x, boca_y), (y0, y1, x0, x1) in lugares:
            y0, y1, x0, x1 = max(0, y0), min(alto, y1), max(0, x0), min(ancho, x1)
            if y1 - y0 < 4 or x1 - x0 < 4:
                continue
            L, a, b = (lab[y0:y1, x0:x1, c] for c in range(3))
            tono = np.degrees(np.arctan2(b, a))
            rojo = (a - a_ref > 2.0) & (t_ref - tono > 2.0) & (L > 15)
            # cerca del centro de la boca
            yy, xx = np.ogrid[y0:y1, x0:x1]
            rojo &= ((xx - boca_x) / (0.18 * w)) ** 2 + ((yy - boca_y) / (0.08 * h)) ** 2 < 1
            n, etiquetas, datos, _ = cv2.connectedComponentsWithStats(rojo.astype(np.uint8), 8)
            if n < 2:
                continue
            areas = datos[1:, cv2.CC_STAT_AREA]
            if areas.max() < 0.0015 * w * h:  # casi nada rojo: labios no visibles (mano, bigote)
                continue
            grandes = 1 + np.flatnonzero(areas >= 0.25 * areas.max())
            m = np.isin(etiquetas, grandes)
            # Forma de boca: ancha, baja, compacta, centrada, no mas clara que las mejillas y
            # no muy grande. Si no (mejilla rojiza, nariz, cara de lado, oreja, mano o madera
            # tomada por cara), se prueba el otro lugar o esa cara queda como antes.
            ys, xs = np.nonzero(m)
            ancho_b, alto_b = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
            if not (ancho_b >= 1.8 * alto_b and 0.15 * w <= ancho_b <= 0.4 * w and alto_b <= 0.14 * h
                    and m.sum() >= 0.35 * ancho_b * alto_b and m.sum() <= 0.04 * w * h
                    and abs(x0 + xs.mean() - boca_x) <= 0.07 * w
                    and np.median(L[m]) <= L_ref + 2.0):
                continue
            m = m.astype(np.float32)
            m = cv2.GaussianBlur(cv2.dilate(m, None), (0, 0), max(1.0, 0.012 * w))
            zonas.append((y0, y1, x0, x1, m, (a_ref, b_ref)))
            break
    return zonas


def brillo_caras(L0, caras):
    """Brillo (L*/100) de cada cara, medido en mejillas/nariz (sin pelo ni fondo)."""
    return [float(np.median(L0[y + int(h * 0.35):y + int(h * 0.8), x + w // 4:x + 3 * w // 4]))
            for x, y, w, h, _ in caras]


def minimo_por_piel(lab, caras, brillos):
    """Brillo minimo (L*/100) al que se lleva cada cara. Una piel morena bien expuesta
    queda bajo L* 54 y no hay que aclarar toda la foto por ella. Se reconoce comparando
    la cara con la ropa clara de su pecho: una foto oscura oscurece las dos por igual,
    una piel morena no. Solo en caras grandes (retratos: en grupos la ropa bajo una
    cara suele ser el alba de otro) y con esa ropa bien expuesta (en un contraluz sale
    oscura). Una cara a la sombra con la camisa al sol tambien queda sin aclarar,
    como estaba en el original."""
    alto, ancho = lab.shape[:2]
    minimos = []
    for (x, y, w, h, _), brillo in zip(caras, brillos):
        minimo = CARA_MIN
        if w >= 0.07 * max(alto, ancho):
            zona = (slice(max(0, int(y + 1.2 * h)), min(alto, int(y + 3.5 * h)), 4),
                    slice(max(0, int(x - 0.25 * w)), min(ancho, int(x + 1.25 * w)), 4))
            L, a, b = lab[zona][..., 0], lab[zona][..., 1], lab[zona][..., 2]
            ok = (L > 60) & (np.sqrt(a * a + b * b) < 16)  # quemada tambien cuenta: la foto no esta oscura
            if ok.sum() >= 0.2 * w * h / 16:  # ropa clara de verdad, no solo el cuello
                L_ropa = float(np.median(L[ok & (L >= np.median(L[ok]))]))
                if L_ropa >= 80:
                    minimo = CARA_MIN * float(np.clip(100 * brillo / L_ropa / REL_CLARA, 0.6, 1.0))
        minimos.append(minimo)
    return np.array(minimos, dtype=np.float32)


def gamma_por_caras(caras, brillos, luz, contraste, gamma_fondo, area_foto, minimos=CARA_MIN, pie=PIE):
    """Elige la exposicion para que las caras (ya con la curva normal aplicada) queden
    en un brillo normal. Si ya lo estan, no se cambia la exposicion.
    minimos: brillo minimo de cada cara (mas bajo en pieles morenas, ver minimo_por_piel)."""
    f = np.array(brillos, dtype=np.float32)
    pesos = np.array([c[4] for c in caras], dtype=np.float32)
    con_curva = curva_tonos(f, 1.0, luz, contraste, pie)
    objetivo = con_curva + min(1.0, 0.75 * luz) * (np.clip(con_curva, minimos, CARA_MAX) - con_curva)
    gammas = np.linspace(0.70, 1.30, 121, dtype=np.float32)
    salida = curva_tonos(f[None, :], gammas[:, None], luz, contraste, pie)
    error = ((salida - objetivo[None, :]) ** 2 * pesos[None, :]).sum(axis=1)
    g_caras = float(gammas[np.argmin(error)])
    # Confianza: si las caras son muy chicas en la foto, pesa tambien la foto completa
    confianza = min(1.0, pesos.sum() / area_foto / 0.003)
    return float(np.exp(confianza * np.log(g_caras) + (1 - confianza) * np.log(gamma_fondo))), confianza


def color_natural(lab, cantidad, piel):
    """Color segun la foto: los colores apagados y normales suben con la vibrancia del motor original
    (como en mejorar_fotos.py: casi nada en los ya saturados, los casi grises, las sombras profundas, los
    blancos y la piel), y solo los muy intensos (fondos morados, bandas, magentas; croma desde
    INTENSO_DESDE) se calman, hasta COLOR_FUERTE (rojos y naranjos hasta COLOR_ROJO). La piel casi no
    cambia en ningun caso. cantidad: 1 = normal, 0 = nada. El tono de cada color no cambia: solo su intensidad."""
    def franja(f):
        L, a, b = lab[f, :, 0], lab[f, :, 1], lab[f, :, 2]
        croma = np.sqrt(a * a + b * b)
        # 1) vibrancia del motor original
        peso = (np.clip((croma - 3.0) / 7.0, 0, 1)            # casi grises: nada
                * np.clip(1.0 - croma / 80.0, 0, 1) ** 1.5    # ya saturados: poco
                * np.clip((L - 15.0) / 20.0, 0, 1)            # sombras profundas: nada
                * np.clip((97.0 - L) / 10.0, 0, 1)            # blancos: nada
                * (1.0 - np.clip((L - 65.0) / 15.0, 0, 1)      # blancos tenidos (camisas
                   * np.clip((16.0 - croma) / 6.0, 0, 1))      # crema): no amarillearlos
                * (1.0 - 0.85 * piel[f])                      # piel: casi nada
                * (1.0 - np.clip((45.0 - L) / 15.0, 0, 1)     # casi negros (ropa oscura, telas
                   * np.clip((16.0 - croma) / 6.0, 0, 1)))     # negras): su tinte no se sube
        factor = 1.0 + VIBRANCIA * cantidad * peso
        # 2) los muy intensos se calman (la piel casi nada). Solo se calcula donde hay color intenso
        # (croma > INTENSO_DESDE, poca parte de la foto): el tono (arctan2) era lo mas lento
        intenso = croma > INTENSO_DESDE
        if intenso.any():
            ai, bi = a[intenso], b[intenso]
            t = np.clip((croma[intenso] - INTENSO_DESDE) / (INTENSO_HASTA - INTENSO_DESDE), 0, 1)
            t = t * t * (3 - 2 * t)
            rojo = np.clip(1.0 - np.abs(np.degrees(np.arctan2(bi, ai)) - 35.0) / 45.0, 0, 1)
            alto = COLOR_FUERTE + (COLOR_ROJO - COLOR_FUERTE) * rojo
            baja = 1.0 + (alto - 1.0) * cantidad * (1.0 - 0.8 * piel[f][intenso])
            factor[intenso] = factor[intenso] * (1 - t) + baja * t
        lab[f, :, 1] = a * factor
        lab[f, :, 2] = b * factor
    por_franjas(franja, lab.shape[0])


def sombras_neutras(lab, L_antes):
    """Ropa oscura y telas negras que se aclararon. En la foto original ya tienen un tinte frio o
    morado (reflejo de un fondo morado, luz de sombra) que no se nota porque estan oscuras; al
    aclararlas el negro quedaba gris azul-morado (confirmacion La Matriz, IMG_1483 y IMG_1492). Ahi
    el tinte baja en la misma proporcion en que se aclararon (al cubo y medio), solo en los casi
    grises (croma < 18) que eran oscuros (L* < 45): los colores reales y lo que ya era claro no
    cambian. L_antes: luminancia 0..1 antes de aclarar."""
    def franja(f):
        L, a, b = lab[f, :, 0] / 100.0, lab[f, :, 1], lab[f, :, 2]
        croma = np.sqrt(a * a + b * b)
        peso = np.clip((18.0 - croma) / 8.0, 0, 1) * np.clip((0.45 - L_antes[f]) / 0.20, 0, 1)
        # Solo tintes frios o morados (b* bajo): el cafe del pelo (b* +5..+10) es su color, no un
        # reflejo; quitarlo dejaba el pelo gris ceniza (primera comunion La Merced 14-11-2026)
        peso *= np.clip((SOMBRA_TIBIA - b) / 4.0, 0, 1)
        baja = np.clip(L_antes[f] / np.maximum(L, 1e-3), 0.4, 1.0) ** 1.5
        factor = 1.0 - peso * (1.0 - baja)
        lab[f, :, 1] = a * factor
        lab[f, :, 2] = b * factor
    por_franjas(franja, lab.shape[0])


def color_piel_aclarada(lab, L_antes, piel):
    """Piel que se aclaro: su color sube un poco con la luz (si no, una cara morena aclarada
    queda palida, 'lavada': primera comunion La Merced 14-11-2026, cara L* 44 -> 57 con el
    mismo croma). Factor (L despues / L antes) ** PIEL_COLOR, como maximo +20 %."""
    def franja(f):
        sube = np.clip(lab[f, :, 0] / 100.0 / np.maximum(L_antes[f], 1e-3), 1.0, 1.35) ** PIEL_COLOR
        factor = 1.0 + (np.minimum(sube, 1.2) - 1.0) * piel[f]
        lab[f, :, 1] *= factor
        lab[f, :, 2] *= factor
    por_franjas(franja, lab.shape[0])


NUCLEO_RUIDO = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)


def medir_ruido(u8):
    """Nivel de ruido (desviacion en niveles 0..255), medido en 9 recortes a tamano
    completo y solo en zonas lisas, para que los bordes no cuenten como ruido."""
    gris = cv2.cvtColor(u8, cv2.COLOR_RGB2GRAY)
    alto, ancho = gris.shape
    t = min(400, alto // 3, ancho // 3)
    valores, respaldo = [], []
    for fy in (0.2, 0.5, 0.8):
        for fx in (0.2, 0.5, 0.8):
            y, x = int(alto * fy - t / 2), int(ancho * fx - t / 2)
            g8 = gris[y:y + t, x:x + t]
            g = g8.astype(np.float32)
            resp = np.abs(cv2.filter2D(g, -1, NUCLEO_RUIDO))
            grad = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
            # Respaldo (como antes): todo el recorte; sirve si no quedan pixeles limpios
            lisas = grad <= np.percentile(grad, 40)
            if lisas.any():
                respaldo.append(resp[lisas].mean())
            # Los pixeles quemados (blanco/negro puro) no tienen ruido medible: si se
            # contaran como "lisos" el ruido saldria mas bajo de lo real (o NaN si el
            # recorte entero esta quemado, como un cielo blanco)
            validos = cv2.erode(((g8 > 4) & (g8 < 251)).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            if validos.mean() < 0.05:
                continue
            lisas = validos & (grad <= np.percentile(grad[validos], 40))
            if lisas.sum() >= 100:
                valores.append(resp[lisas].mean())
    if not valores:
        valores = respaldo
    if not valores:  # foto entera plana: no hay ruido que medir
        return 0.0
    return float(np.sqrt(np.pi / 2) / 6 * np.median(valores))


def quitar_ruido(u8, sigma):
    """Quita manchas de color (siempre, es casi gratis) y el grano de la luminancia.
    Grano leve: filtro bilateral (rapido). Grano fuerte: NL-means (~1 s mas por foto)."""
    lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB)
    L, a, b = cv2.split(lab)
    radio_color = max(u8.shape[:2]) / 1000.0
    a = cv2.GaussianBlur(a, (0, 0), radio_color)
    b = cv2.GaussianBlur(b, (0, 0), radio_color)
    if sigma < 3.0:
        L = cv2.bilateralFilter(L, 7, sigma * 3.5, 5)
        metodo = "leve"
    else:
        L = cv2.fastNlMeansDenoising(L, None, h=sigma * 1.15, templateWindowSize=5, searchWindowSize=11)
        metodo = "fuerte"
    return cv2.cvtColor(cv2.merge([L, a, b]), cv2.COLOR_LAB2RGB), metodo


def filtro_guiado(I, radio, eps):
    """Suavizado que respeta bordes (He et al.): las variaciones chicas (grano,
    poros) se van a la textura, los bordes fuertes se quedan en la base.
    A diferencia de un desenfoque comun, no crea halos al levantar sombras."""
    caja = (2 * radio + 1, 2 * radio + 1)
    media = cv2.boxFilter(I, -1, caja)
    media2 = cv2.boxFilter(I * I, -1, caja)
    a, b = np.empty_like(I), np.empty_like(I)

    def franja(f):
        var = media2[f] - media[f] * media[f]
        a[f] = var / (var + eps)
        b[f] = media[f] - a[f] * media[f]
    por_franjas(franja, I.shape[0])
    del media, media2
    a, b = cv2.boxFilter(a, -1, caja), cv2.boxFilter(b, -1, caja)
    salida = np.empty_like(I)

    def franja(f):
        salida[f] = a[f] * I[f] + b[f]
    por_franjas(franja, I.shape[0])
    return salida


def limitar_halos(L_nueva, L_antes, margen):
    """Control de sobreimpulso: el enfoque no puede pasar del valor mas claro/oscuro
    de los vecinos (5x5) mas un margen chico. Evita contornos blancos/negros."""
    nucleo = np.ones((5, 5), np.uint8)
    techo = cv2.dilate(L_antes, nucleo)
    piso = cv2.erode(L_antes, nucleo)
    salida = np.empty_like(L_nueva)

    def franja(f):
        salida[f] = np.minimum(np.maximum(L_nueva[f], piso[f] - margen), techo[f] + margen)
    por_franjas(franja, salida.shape[0])
    return salida


def tono_de_piel(lab, paso=4, amplio=False):
    """0..1 por color de piel en la muestra (1 de cada 'paso' pixeles), sin difuminar ni ampliar.
    amplio: acepta tambien la piel rosada (tono desde 0 grados, no 10) y la morena o en sombra (L* desde
    15, no 25). Solo para proteger del color las caras detectadas (punto 10, IMG_1500): con la luz del
    telon morado la piel quedaba en tono 15-25 y casi la mitad de la cara no contaba como piel, asi que
    la vibrancia la enrojecia. Fuera de las caras no sirve: tomaria ropa roja, madera y fondos."""
    m = np.ascontiguousarray(lab[::paso, ::paso])
    L, a, b = m[..., 0], m[..., 1], m[..., 2]
    croma = np.sqrt(a * a + b * b)
    tono = np.degrees(np.arctan2(b, a))
    tono_min, L_min = (0, 15) if amplio else (10, 25)
    return (np.clip((tono - tono_min) / 10, 0, 1) * np.clip((80 - tono) / 15, 0, 1)
            * np.clip((croma - 6) / 6, 0, 1) * np.clip((50 - croma) / 10, 0, 1)
            * np.clip((L - L_min) / 10, 0, 1) * np.clip((95 - L) / 5, 0, 1))


def mascara_piel(lab, paso=4, caras=None, peso=None):
    """0..1 donde hay tonos de piel (calculada en una muestra y ampliada: es rapida).
    Si se pasan 'caras', solo cuenta la piel alrededor de ellas: sin esto, ropa
    beige/rosada, pelo castano, madera y paredes tambien parecian piel.
    peso: tono_de_piel(lab, paso) ya calculado (mejorar lo usa para dos mascaras)."""
    if peso is None:
        peso = tono_de_piel(lab, paso)
    if caras is not None:
        peso = peso * zona_caras(peso.shape[0], peso.shape[1], caras, paso) if caras else peso * 0
    peso = cv2.GaussianBlur(peso.astype(np.float32), (0, 0), 2)
    if paso == 1:
        return peso
    return cv2.resize(peso, (lab.shape[1], lab.shape[0]), interpolation=cv2.INTER_LINEAR)


def suavizar_piel(lab, piel, tam, labios=()):
    """Empareja el enrojecimiento/manchas de la piel suavizando solo el COLOR
    (canales a/b), no la luz: los detalles (poros, ojos, pelo) quedan igual.
    Los labios ('labios' de zona_labios) no se tocan, y para la piel vecina cuentan
    como piel normal: si no, el suavizado les quitaba hasta un tercio del rojo frente
    a la piel (labios finos) y tenia de rojo el contorno."""
    radio = tam / 300.0
    # Solo en el rectangulo donde hay piel (afuera la mascara vale 0 y no cambia nada);
    # el desenfoque se calcula con un margen de su alcance (4 sigma) para que sea igual
    filas = np.flatnonzero(piel.max(axis=1) > 0)
    if filas.size == 0:
        return
    cols = np.flatnonzero(piel.max(axis=0) > 0)
    y0, y1, x0, x1 = filas[0], filas[-1] + 1, cols[0], cols[-1] + 1
    m = int(np.ceil(4 * radio)) + 2
    Y0, X0 = max(0, y0 - m), max(0, x0 - m)
    zona = lab[Y0:min(lab.shape[0], y1 + m), X0:min(lab.shape[1], x1 + m)]
    adentro = (slice(y0 - Y0, y1 - Y0), slice(x0 - X0, x1 - X0))
    p = piel[y0:y1, x0:x1]
    cortes = []  # cada zona de labios recortada al rectangulo de la piel (con margen)
    for ly0, ly1, lx0, lx1, ml, ref in labios:
        cy0, cy1, cx0, cx1 = max(ly0, Y0), min(ly1, Y0 + zona.shape[0]), max(lx0, X0), min(lx1, X0 + zona.shape[1])
        if cy1 > cy0 and cx1 > cx0:
            cortes.append((cy0, cy1, cx0, cx1, ml[cy0 - ly0:cy1 - ly0, cx0 - lx0:cx1 - lx0], ref))
    if cortes:
        p = p.copy()
        for cy0, cy1, cx0, cx1, ml, _ in cortes:
            py0, py1, px0, px1 = max(cy0, y0), min(cy1, y1), max(cx0, x0), min(cx1, x1)
            if py1 > py0 and px1 > px0:
                p[py0 - y0:py1 - y0, px0 - x0:px1 - x0] *= 1.0 - ml[py0 - cy0:py1 - cy0, px0 - cx0:px1 - cx0]
    for c in (1, 2):
        fuente = zona[..., c]
        if cortes:  # para el desenfoque, los labios se reemplazan por el color de la piel
            fuente = fuente.copy()
            for cy0, cy1, cx0, cx1, ml, ref in cortes:
                parte = fuente[cy0 - Y0:cy1 - Y0, cx0 - X0:cx1 - X0]
                parte += (ref[c - 1] - parte) * ml
        suave = cv2.GaussianBlur(fuente, (0, 0), radio)[adentro]
        canal = lab[y0:y1, x0:x1, c]
        lab[y0:y1, x0:x1, c] = canal + (suave - canal) * (0.6 * p)
    # Baja un poco el rojo de la piel (canal a) para que no se vea encendida
    lab[y0:y1, x0:x1, 1] -= 1.0 * p * np.clip(lab[y0:y1, x0:x1, 1] / 20.0, 0, 1)


LOCAL_RADIO = 1 / 120.0   # alcance del contraste local (fraccion del lado mayor)
LOCAL_BORDE = 0.06        # saltos de luz mayores que esto son "bordes": no se exageran (sin halo)
LOCAL_FUERZA = 0.9        # cuanto se refuerzan los cambios de luz medianos
LOCAL_TOPE = 0.05         # maximo que el contraste local mueve un pixel (5 L*)


def contraste_local(base, tam):
    """Da volumen (pliegues, telas, modelado de la cara) sin halo. Reemplaza al CLAHE
    (2026-11-13), que ecualizaba por teselas y dejaba una aureola clara alrededor de
    pelo oscuro contra follaje/fondos claros, y aclaraba u oscurecia mitades de foto.
    Aqui se separa la luz grande con un filtro que respeta bordes: los bordes fuertes
    (persona contra fondo) quedan en la parte grande y no se exageran; solo se
    refuerzan las variaciones medianas. Mas fuerte en fotos planas (nubladas, sombra),
    casi nada en fotos de sol fuerte que ya tienen contraste de sobra."""
    p2, p98 = np.percentile(muestra(base), [2, 98])
    rango = float(p98 - p2)
    plana = float(np.clip((0.97 - rango) / 0.20, 0.25, 1.0))  # 1 = foto plana, 0.25 = sol fuerte
    grande = filtro_guiado(base, max(4, round(tam * LOCAL_RADIO)), LOCAL_BORDE ** 2)
    cambio = np.empty_like(base)
    k = LOCAL_FUERZA * plana

    def franja(f):
        cambio[f] = np.clip((base[f] - grande[f]) * k, -LOCAL_TOPE, LOCAL_TOPE)
    por_franjas(franja, base.shape[0])
    return cambio


def enfocar(L, tam, enfoque, umbral, menos=None):
    """Mascara de enfoque que ignora detalles mas chicos que 'umbral' (el grano)
    y, desde nivel 1.5, suma 'claridad' (contraste de bordes medianos)."""
    radio = tam / 2000.0
    antes = L
    suave = cv2.GaussianBlur(L, (0, 0), radio)
    L = np.empty_like(antes)

    def franja(f):
        detalle = antes[f] - suave[f]
        # Peso 0 para variaciones del tamano del ruido, 1 para bordes reales
        peso = np.clip((np.abs(detalle) - umbral) / umbral, 0, 1)
        if menos is not None:  # menos enfoque en la piel
            peso = peso * menos[f]
        L[f] = antes[f] + detalle * peso * (0.6 * enfoque)
    por_franjas(franja, L.shape[0])
    if enfoque > 1.0:
        suave = cv2.GaussianBlur(L, (0, 0), tam / 250.0)

        def claridad(f):
            medio = L[f] - suave[f]
            if menos is not None:
                medio = medio * menos[f]
            L[f] = L[f] + medio * (0.12 * (enfoque - 1.0))
        por_franjas(claridad, L.shape[0])
    # Sin halos: maximo ~1,5% (unos 4 niveles) mas alla de los vecinos
    return limitar_halos(L, antes, 0.015)


def ajustar_gama(lab, u8, tablas, tam, piel):
    """Colores muy saturados (casullas rojas, fondos morados) que al aclarar o con la
    vibrancia se salen de lo que el RGB puede mostrar. Recortar cada canal los deja
    planos, sin pliegues y tipo coral; en vez de eso se deshace solo la parte del cambio
    que sobra (acercando ese color al de la foto original), suave en el espacio.
    El color original (con balance y niveles) se recalcula solo en los pixeles que se
    usan, con las mismas tablas: asi no hay que guardar toda la foto en RGB."""
    def rgb_orig(ys, xs):
        return np.ascontiguousarray(tablas[u8[ys, xs], np.arange(3)][:, None, :])

    # El mapa de cuanto aclarar se calcula a media resolucion (despues se suaviza igual)
    lab_p = np.ascontiguousarray(lab[::2, ::2])
    error = np.abs(cv2.cvtColor(cv2.cvtColor(lab_p, cv2.COLOR_LAB2RGB), cv2.COLOR_RGB2LAB) - lab_p).sum(axis=2)
    croma = np.sqrt(lab_p[..., 1] ** 2 + lab_p[..., 2] ** 2)  # OpenCV recorta a 0..1: error = lo perdido
    fuera = (error > 1.5) & (croma > 25) & (piel[::2, ::2] < 0.5)
    if not fuera.any():
        return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    ys, xs = np.nonzero(fuera)
    nuevo = lab_p[ys, xs][:, None, :]
    orig = cv2.cvtColor(rgb_orig(2 * ys, 2 * xs), cv2.COLOR_RGB2LAB)
    bajo = np.zeros(len(ys), np.float32)
    alto = np.ones(len(ys), np.float32)
    for _ in range(6):  # busqueda binaria: cuanto del cambio cabe
        t = (bajo + alto) / 2
        prueba = orig + t[:, None, None] * (nuevo - orig)
        vuelta = cv2.cvtColor(cv2.cvtColor(prueba, cv2.COLOR_LAB2RGB), cv2.COLOR_RGB2LAB)
        cabe = np.abs(vuelta - prueba).sum(axis=(1, 2)) <= 1.0
        bajo = np.where(cabe, t, bajo)
        alto = np.where(cabe, alto, t)
    # menos ajuste en colores poco saturados (reflejos de piel: ahi recortar no se nota)
    mapa = np.ones(lab_p.shape[:2], np.float32)
    mapa[ys, xs] = 1 - (1 - bajo) * np.clip((croma[ys, xs] - 25) / 15, 0, 1)
    r = max(1, round(tam / 400))
    mapa = cv2.erode(mapa, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    mapa = cv2.GaussianBlur(mapa, (0, 0), r / 3)
    mapa = cv2.resize(mapa, (lab.shape[1], lab.shape[0]), interpolation=cv2.INTER_LINEAR)
    # solo en colores saturados que no son piel: caras y blancos vecinos no se tocan (sin halo)
    rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    ys, xs = np.nonzero(mapa < 0.999)
    color = lab[ys, xs]
    croma = np.sqrt(color[:, 1] ** 2 + color[:, 2] ** 2)
    deshacer = (1 - mapa[ys, xs]) * np.clip((croma - 25) / 15, 0, 1) * (1 - piel[ys, xs])
    cambia = deshacer > 0  # el resto (poco saturado o piel) queda igual: no se recalcula
    if not cambia.any():
        return rgb
    ys, xs, color, deshacer = ys[cambia], xs[cambia], color[cambia], deshacer[cambia]
    orig = cv2.cvtColor(rgb_orig(ys, xs), cv2.COLOR_RGB2LAB)[:, 0, :]
    color += deshacer[:, None] * (orig - color)
    rgb[ys, xs] = cv2.cvtColor(color[:, None, :], cv2.COLOR_LAB2RGB)[:, 0, :]
    return rgb


def mejorar(img, fuerza=1.0, calidez=0.0, enfoque=1.0, ruido="auto", luz=1.0, contraste=1.0, color=1.0,
            blanco_serie=None, gris_serie=None):
    """Devuelve (imagen_mejorada, texto con lo que se hizo con el ruido).
    'fuerza' multiplica a los tres controles: luz, contraste y color.
    blanco_serie, gris_serie: blanco y dominante comunes de la serie (ver plan_serie); si no, se
    miden en la foto."""
    luz, contraste, color = fuerza * luz, fuerza * contraste, fuerza * color
    u8 = np.asarray(img.convert("RGB"))

    # 0. Ruido
    sigma = medir_ruido(u8)
    info = f"ruido {sigma:.1f}"
    if ruido == "si" or (ruido == "auto" and sigma >= 1.5):
        u8, metodo = quitar_ruido(u8, max(sigma, 1.5))
        info += f" -> reducido ({metodo})"
        sigma_restante = sigma * 0.35
    else:
        sigma_restante = sigma

    # 1-2. Balance de blancos + niveles
    caras = detectar_caras(u8)
    tablas = np.stack(tablas_color(u8, 0.88 * fuerza, 0.6 * contraste, caras,
                                   (blanco_serie, True) if blanco_serie else None, gris_serie), axis=-1)  # 256 x 3
    puntos = puntos_caras(u8, caras)  # ojos y boca de cada cara (para el enfoque y los labios)
    olvidar_yunet()  # YuNet ya no se usa en esta foto

    # 3. Exposicion, sombras/luces y curva S sobre la luminancia.
    # Se separa la luz ("base") de la textura fina (grano, poros) y la curva solo
    # aclara la base: asi levantar sombras no multiplica el grano (se notaba al imprimir).
    # (Para ahorrar memoria, cada arreglo grande se borra apenas deja de usarse.)
    lab = cv2.cvtColor(cv2.LUT(u8, tablas[None]), cv2.COLOR_RGB2LAB)  # L 0..100
    tam = max(img.size)
    L0 = lab[..., 0] / 100.0
    media = float(np.median(muestra(L0)))
    gamma = gamma_global(media, luz)
    principales = caras_principales(caras)
    pie = PIE
    if principales:
        brillos = brillo_caras(L0, principales)
        # Escenario con fondo negro (telon, muro oscuro) y las caras bien iluminadas por el flash:
        # lo oscuro es el fondo, no falta de luz. Levantarlo lo dejaba gris (Santa Marta 13-11-2026:
        # fondo L* 21 -> 27). Ahi el negro se protege hasta mas arriba.
        if float(np.median(brillos)) >= ESCENARIO_CARA:
            m = muestra(L0)
            arriba = float((m[: int(0.45 * m.shape[0])] < 0.30).mean())
            fondo = float(np.clip((arriba - 0.40) / 0.20, 0, 1))
            if fondo > 0:
                pie = PIE + (PIE_ESCENARIO - PIE) * fondo
                info += f", fondo oscuro {fondo:.0%}"
        gamma, _ = gamma_por_caras(principales, brillos, luz, contraste, gamma, L0.size,
                                   minimo_por_piel(lab, principales, brillos), pie)
        info += f", {len(caras)} cara{'s' if len(caras) > 1 else ''}"
    luz_base = filtro_guiado(L0, max(2, round(tam / 1000.0)), 0.025 ** 2)
    tabla = tabla_tonos(gamma, luz, contraste, pie)
    textura, sombra_orig, base = np.empty_like(L0), np.empty_like(L0), np.empty_like(L0)

    def franja(f):
        textura[f] = L0[f] - luz_base[f]
        sombra_orig[f] = np.clip((0.30 - luz_base[f]) / 0.20, 0, 1)  # lo que estaba oscuro antes de aclarar
        base[f] = tabla[cv2.multiply(luz_base[f], TONOS - 1.0).round().astype(np.int16)]
    por_franjas(franja, L0.shape[0])
    L_antes = luz_base  # para sombras_neutras (la luz sin textura: el grano no cuenta)
    del L0

    # Piel y sombras: ahi se atenua el grano/poros (solo las variaciones chicas,
    # los bordes y detalles grandes quedan igual) y se aplica menos contraste y enfoque
    # Piel solo en las caras detectadas (y su cuello); para la vibrancia se usa
    # tambien el tono de piel en toda la foto (manos, brazos, caras de perfil)
    peso_piel = tono_de_piel(lab)
    piel = mascara_piel(lab, caras=caras, peso=peso_piel)
    tono_piel = mascara_piel(lab, peso=peso_piel)
    del peso_piel
    # Para el color (paso 6): en las caras, tambien la piel rosada o morena (ver tono_de_piel)
    piel_color = (np.maximum(piel, mascara_piel(lab, caras=caras, peso=tono_de_piel(lab, amplio=True)))
                  if caras else piel)
    delicado = np.empty_like(base)

    def franja(f):
        oscuro = np.clip((0.35 - base[f]) / 0.25, 0, 1)
        delicado[f] = np.maximum(piel[f], oscuro)
        textura[f] *= 1.0 - 0.5 * delicado[f] * np.exp(-(textura[f] / 0.02) ** 2)
    por_franjas(franja, base.shape[0])
    suavizar_piel(lab, piel, tam, zona_labios(lab, caras, puntos))
    # Sombras: al aclararlas aparece ruido de color (puntos de colores); se suaviza
    # solo el color (a/b) ahi, el detalle de luz queda intacto
    radio_c = tam / 1500.0
    for c in (1, 2):
        suave = cv2.GaussianBlur(lab[..., c], (0, 0), radio_c)

        def franja(f):
            canal = lab[f, :, c]
            lab[f, :, c] = canal + (suave[f] - canal) * (0.9 * sombra_orig[f])
        por_franjas(franja, lab.shape[0])
    del suave, sombra_orig

    # 4. Contraste local suave (calculado sobre la base: da volumen sin realzar grano)
    cambio = contraste_local(base, tam)
    L = np.empty_like(base)

    def franja(f):
        extremos = np.clip(np.minimum(base[f], 1.0 - base[f]) / 0.12, 0, 1)  # protege negro y blanco
        L[f] = base[f] + textura[f] + cambio[f] * (0.5 * contraste * (1.0 - 0.7 * piel[f]) * extremos)
    por_franjas(franja, base.shape[0])
    del base, cambio, textura

    # 5. Enfoque: solo bordes reales; casi nada en piel y sombras, algo mas en los ojos
    if enfoque > 0:
        for y0, y1, x0, x1, ojos in zona_ojos(u8, caras, puntos):
            delicado[y0:y1, x0:x1] *= 1.0 - OJOS_ENFOQUE * ojos
        umbral = max(0.010, 2.0 * sigma_restante / 255.0)
        L = enfocar(L, tam, enfoque, umbral, 1.0 - 0.85 * delicado)
    del delicado

    def franja(f):
        lab[f, :, 0] = np.clip(L[f], 0, 1) * 100.0
    por_franjas(franja, L.shape[0])
    del L

    # 6. Color natural (en Lab, con la luz final). Antes, el tinte de los negros aclarados baja
    sombras_neutras(lab, L_antes)
    color_piel_aclarada(lab, L_antes, piel)
    del L_antes
    color_natural(lab, color, np.maximum(piel_color, 0.8 * tono_piel))
    del piel_color
    # 7. Colores fuera de gama (rojos saturados): sin recorte plano
    rgb = ajustar_gama(lab, u8, tablas, tam, np.maximum(piel, tono_piel))
    np.clip(rgb, 0, 1, out=rgb)

    if calidez:
        rgb *= np.array([1 + 0.04 * calidez, 1 + 0.01 * calidez, 1 - 0.04 * calidez], dtype=np.float32)
    return Image.fromarray(cv2.convertScaleAbs(rgb, alpha=255.0)), info


def comparacion(antes, despues, destino):
    a, d = antes.copy(), despues.copy()
    a.thumbnail((1200, 1200))
    d.thumbnail((1200, 1200))
    lienzo = Image.new("RGB", (a.width + d.width + 20, max(a.height, d.height)), "white")
    lienzo.paste(a, (0, 0))
    lienzo.paste(d, (a.width + 20, 0))
    parcial = destino.with_name(destino.name + ".parcial")  # como la foto: sin archivos a medias
    lienzo.save(parcial, format="JPEG", quality=88)
    os.replace(parcial, destino)


MARCA = "ajuste_combinado.py"  # se guarda en el EXIF para no ajustar dos veces la misma foto
TAG_SOFTWARE = 0x0131
# Version de como salen las fotos: se guarda en el EXIF junto a los ajustes. Subirla cuando un cambio
# del script cambie el resultado, asi las fotos hechas con la version anterior se vuelven a ajustar.
VERSION = "2026-11-18c"  # 2026-11-18c: juntadas la version de este PC (18-11: Adobe RGB, piel rosada protegida, fuera Haar) y la del otro computador (14-11: escenario oscuro, ropa rosada, pelo con su color y piel aclarada); 2026-11-13: contraste local sin halo (fuera CLAHE); 2026-10-26: ojos y boca con los puntos de YuNet (punto 8); 2026-10-25: puntos 5 y 6


def ya_mejorada(img):
    return str(img.getexif().get(TAG_SOFTWARE, "")).startswith(MARCA)


def firma(args):
    """Texto que va en el EXIF de cada foto ajustada: herramienta, version y todos los ajustes."""
    return (f"{MARCA} {VERSION} fuerza {args.fuerza} luz {args.luz} contraste {args.contraste} "
            f"color {args.color} enfoque {args.enfoque} calidez {args.calidez} ruido {args.ruido} serie {args.serie}")


def ya_hecha(foto, salida, args):
    """True si <salida>\\<foto>.jpg ya es esa foto ajustada con esta version y estos ajustes: un lote
    cortado se retoma sin rehacer lo que ya estaba (antes, arrastrar otra vez la carpeta rehacia todo
    y sobrescribia). Un archivo de otra version, con otros ajustes o cortado se vuelve a hacer."""
    destino = salida / (foto.stem + ".jpg")
    if args.comparar and not (salida / "comparar" / (foto.stem + "_antes_despues.jpg")).exists():
        return False
    try:
        with open(destino, "rb") as arch:  # un JPG completo termina con FF D9
            arch.seek(-2, os.SEEK_END)
            if arch.read(2) != b"\xff\xd9":
                return False
        with Image.open(destino) as im:
            if es_adobe_rgb(im):  # hecha antes del 2026-11-18 sin pasar a sRGB: se rehace
                return False
            return str(im.getexif().get(TAG_SOFTWARE, "")) == firma(args)
    except (OSError, ValueError):
        return False


SALIDAS = {"combinadas", "ajustadas claude", "mejoradas", "comparar"}  # carpetas de resultados, no de fotos


def juntar_fotos(rutas, nombre_salida, avisos=None):
    """Acepta carpetas y/o fotos sueltas. Devuelve [(foto, carpeta_de_salida)].
    Solo toma las fotos que estan directamente en cada carpeta; si tiene subcarpetas con fotos, avisa
    (no entra solo: suelen ser selecciones o copias de las mismas fotos)."""
    lista, vistas, sin_ajustar = [], set(), []
    for r in rutas:
        r = Path(r)
        if r.is_dir():
            fotos = sorted(f for f in r.iterdir() if f.is_file() and f.suffix.lower() in EXTENSIONES)
            for sub in sorted(d for d in r.iterdir() if d.is_dir()):
                if sub.name.lower() in SALIDAS | {nombre_salida.lower()}:
                    continue
                n = sum(1 for f in sub.iterdir() if f.is_file() and f.suffix.lower() in EXTENSIONES)
                if n:
                    sin_ajustar.append(f"{sub.name} ({n} foto{'s' if n > 1 else ''})")
        elif r.is_file() and r.suffix.lower() in EXTENSIONES:
            fotos = [r]
        else:
            print(f"Se omite (no es foto ni carpeta): {r}")
            if avisos is not None:
                avisos.append(f"se omitió {r.name}: no es foto ni carpeta")
            continue
        for f in fotos:
            clave = str(f.resolve()).lower()
            if clave not in vistas:
                vistas.add(clave)
                lista.append((f, f.parent / nombre_salida))
    if sin_ajustar:
        print("OJO: estas subcarpetas tienen fotos que NO se van a ajustar (arrástralas aparte si las quieres): "
              + ", ".join(sin_ajustar))
        if avisos is not None:
            avisos.append("subcarpetas sin ajustar (arrástralas aparte si las quieres): " + ", ".join(sin_ajustar))
    return lista


def repetidas(fotos):
    """Grupos de fotos con el mismo contenido, ej. "IMG_1339.JPG" e "IMG_1339 - copia.JPG" (si se
    imprimen, salen dos veces). Solo se comparan las del mismo tamano: es rapido."""
    por_tamano = {}
    for f, _ in fotos:
        try:
            por_tamano.setdefault(f.stat().st_size, []).append(f)
        except OSError:
            pass
    grupos = []
    for mismas in por_tamano.values():
        if len(mismas) > 1:
            por_md5 = {}
            for f in mismas:
                try:
                    por_md5.setdefault(hashlib.md5(f.read_bytes()).hexdigest(), []).append(f)
                except OSError:
                    pass
            grupos += [g for g in por_md5.values() if len(g) > 1]
    return grupos


def falta_yunet():
    """Por que no se puede usar YuNet (falta el modelo u OpenCV no lo carga), o None si esta bien."""
    if not MODELO_YUNET.exists():
        return f"no esta el archivo {MODELO_YUNET.name} junto al programa"
    if crear_yunet() is None:
        return f"esta version de OpenCV ({cv2.__version__}) no puede usar {MODELO_YUNET.name}"
    return None


def memoria_total_gb():
    """RAM fisica del PC en GB (None si no se puede saber)."""
    class Estado(ctypes.Structure):
        _fields_ = [("largo", ctypes.c_ulong), ("carga", ctypes.c_ulong)] + [
            (n, ctypes.c_ulonglong) for n in ("total", "libre", "pag_total", "pag_libre",
                                              "virt_total", "virt_libre", "virt_ext")]
    try:
        e = Estado()
        e.largo = ctypes.sizeof(Estado)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e)):
            return e.total / 2 ** 30
    except (AttributeError, OSError):  # no es Windows
        pass
    return None


def a_toda_velocidad():
    """Pide a Windows que este proceso use los nucleos rapidos aunque su ventana este minimizada.
    En procesadores con nucleos rapidos y de ahorro (este notebook: Intel de 12a generacion),
    Windows 11 manda a los de ahorro los programas con la ventana minimizada: medido 2026-11-17 con
    30 fotos, 43 s con la consola a la vista y 78-83 s minimizada. Se llama en el programa y en cada
    proceso que ajusta fotos. Si Windows no lo permite, no pasa nada."""
    class Estado(ctypes.Structure):
        _fields_ = [("version", ctypes.c_ulong), ("control", ctypes.c_ulong), ("estado", ctypes.c_ulong)]
    try:
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
        e = Estado(1, 0x1, 0)   # PROCESS_POWER_THROTTLING_EXECUTION_SPEED apagado = siempre rapido
        k.SetProcessInformation(k.GetCurrentProcess(), 4, ctypes.byref(e), ctypes.sizeof(e))
    except (AttributeError, OSError):  # no es Windows o es uno antiguo
        pass


def cuantas_a_la_vez(fotos):
    """Cuantas fotos a la vez (1 a 3), cada una en su proceso, segun la RAM y los nucleos del PC.
    Cada proceso ocupa ~0,35 GB + 0,08 GB por megapixel (medido 2026-10-25: 10,6 MP 1,2 GB; 24 MP
    2,2 GB) y se dejan 4,5 GB para Windows y los demas programas: en un PC de 8 GB, 2 fotos de 24 MP
    agotaban la RAM, el PC paginaba y tardaban 10..40% MAS que de a una (medido 2026-10-11).
    En este PC (16 GB, 12 hilos) da 3, lo que antes se fijaba en el .bat."""
    megapixeles = 0.0
    for f, _ in fotos:
        try:
            with Image.open(f) as im:  # solo lee la cabecera
                megapixeles = max(megapixeles, im.size[0] * im.size[1] / 1e6)
        except OSError:
            pass
    total = memoria_total_gb() or 8.0
    por_ram = int((total - 4.5) / (0.35 + 0.08 * megapixeles))
    return max(1, min(3, (os.cpu_count() or 2) // 2, por_ram))


# ---------------------------------------------------------------------------
# Modo serie: las fotos seguidas con la misma luz llevan el mismo balance de blancos
# ---------------------------------------------------------------------------
# Antes cada foto se corregia sola, con la ropa clara de esa foto: en una serie con el
# mismo flash y el mismo fondo una salia enfriada y la siguiente entibiada, segun la
# ropa de cada persona (o la piel de un escote tomada por camisa blanca: la cara salia
# gris). Ahora el blanco de cada foto es la mediana del de sus vecinas (la serie): el
# error de una foto no pesa y las fotos con la misma luz quedan parejas.
SERIE_VECINAS = 5     # fotos a cada lado que forman la serie de una foto
SERIE_PAUSA = 10.0    # minutos sin fotos: empieza otra serie
SERIE_SALTO_EV = 3.0  # cambio brusco de exposicion (adentro/afuera): otra luz, otra serie
SERIE_MINIMO = 3      # fotos con ropa clara necesarias para usar la serie


def datos_serie(ruta):
    """Hora, camara, flash y exposicion de una foto (solo lee la cabecera EXIF), o None
    si ya esta mejorada o no se puede leer."""
    try:
        with Image.open(ruta) as im:
            ex = im.getexif()
            if str(ex.get(TAG_SOFTWARE, "")).startswith(MARCA):
                return None
            i = ex.get_ifd(0x8769)
            N, t, iso = (float(i[k]) if i.get(k) else None for k in (0x829D, 0x829A, 0x8827))
            return dict(hora=str(i.get(0x9003) or "") or None, modelo=str(ex.get(0x0110, "")),
                        flash=int(i.get(0x9209) or 0) & 1,
                        ev=float(np.log2(N * N / t / (iso / 100))) if N and t and iso else None)
    except (OSError, ValueError, ZeroDivisionError):
        return None


def series(datos):
    """Indices de las fotos agrupados en series: misma camara, en orden de hora, sin
    pausas largas ni cambios bruscos de exposicion. Las fotos sin hora quedan fuera."""
    con_hora = sorted((i for i, d in enumerate(datos) if d and d["hora"]),
                      key=lambda i: (datos[i]["modelo"], datos[i]["hora"]))
    grupos, prev = [], None
    for i in con_hora:
        d = datos[i]
        nueva = prev is None or d["modelo"] != prev["modelo"]
        if not nueva:
            try:
                minutos = (time.mktime(time.strptime(d["hora"], "%Y:%m:%d %H:%M:%S"))
                           - time.mktime(time.strptime(prev["hora"], "%Y:%m:%d %H:%M:%S"))) / 60
            except ValueError:
                minutos = 1e9
            nueva = minutos > SERIE_PAUSA or (d["ev"] is not None and prev["ev"] is not None
                                              and abs(d["ev"] - prev["ev"]) > SERIE_SALTO_EV)
        if nueva:
            grupos.append([])
        grupos[-1].append(i)
        prev = d
    return grupos


def vecinas(grupo, j, datos):
    """Las fotos de la serie alrededor de grupo[j] (ella incluida) con el mismo estado de
    flash: con y sin flash la luz puede ser otra."""
    mismo = [i for i in grupo if datos[i]["flash"] == datos[grupo[j]]["flash"]]
    k = mismo.index(grupo[j])
    return mismo[max(0, k - SERIE_VECINAS):k + SERIE_VECINAS + 1]


def blanco_rapido(ruta):
    """medir_blanco sobre una copia chica de la foto (el JPG se decodifica ya reducido:
    rapido y con poca RAM). (None, False) si no se puede leer."""
    try:
        with Image.open(ruta) as im:
            adobe = es_adobe_rgb(im)
            im.draft("RGB", (im.size[0] // 4, im.size[1] // 4))  # ~1000 px con fotos de 10 MP
            u8 = np.ascontiguousarray(np.asarray(ImageOps.exif_transpose(im).convert("RGB")))
        if adobe:
            u8 = adobe_a_srgb(u8)
    except OSError:
        return None, False
    try:
        return medir_blanco(u8, u8, detectar_caras(u8), paso=1)
    finally:
        olvidar_yunet()


def gris_rapido(ruta, blanco, fuerza_balance, fuerza_niveles):
    """medir_dominante sobre una copia chica de la foto, despues de la primera pasada con el blanco
    de la serie. None si no se puede leer o casi no tiene grises."""
    try:
        with Image.open(ruta) as im:
            adobe = es_adobe_rgb(im)
            im.draft("RGB", (im.size[0] // 4, im.size[1] // 4))
            m = np.ascontiguousarray(np.asarray(ImageOps.exif_transpose(im).convert("RGB")))
        if adobe:
            m = adobe_a_srgb(m)
    except OSError:
        return None
    return medir_dominante(m, tablas_balance(m, blanco, True, fuerza_balance, fuerza_niveles))


def plan_serie(fotos, a_la_vez=2, fuerza_balance=0.88, fuerza_niveles=0.66, avance=None):
    """Para cada foto [(ruta, salida)]: (blanco de la serie, cuantas fotos lo dieron, dominante de
    la serie o None) o None si no tiene serie (se corrige como siempre, con lo de esa foto).
    La dominante (punto 6 del plan) se mide en cada foto ya balanceada con el blanco de su serie, y
    cada una lleva la mediana de sus vecinas, igual que el blanco. fuerza_balance y fuerza_niveles:
    las mismas que usa mejorar (0,88 x fuerza y 0,6 x contraste).
    avance(hecho, total): se llama cada vez que se termina de medir una foto (para la ventana animada;
    no cambia nada de lo que se mide)."""
    datos = [datos_serie(f) for f, _ in fotos]
    grupos = [g for g in series(datos) if len(g) >= SERIE_MINIMO]
    medibles = [i for g in grupos for i in g]
    cuenta = dict(hecho=0, total=2 * len(medibles))   # dos pasadas: blanco y dominante
    candado = threading.Lock()

    def contar(funcion):
        def medir(i):
            try:
                return funcion(i)
            finally:
                if avance:
                    with candado:
                        cuenta["hecho"] += 1
                        hecho, total = cuenta["hecho"], cuenta["total"]
                    try:
                        avance(hecho, total)
                    except Exception:
                        pass
        return medir

    blancos = [None] * len(fotos)
    with ThreadPoolExecutor(max_workers=2 * a_la_vez) as pool:
        for i, b in zip(medibles, pool.map(contar(lambda i: blanco_rapido(fotos[i][0])), medibles)):
            blancos[i] = b
    plan = [None] * len(fotos)
    for g in grupos:
        for j, i in enumerate(g):
            ropa = [blancos[v][0] for v in vecinas(g, j, datos) if blancos[v][1]]  # solo ropa bajo caras
            if len(ropa) >= SERIE_MINIMO:
                plan[i] = (tuple(float(x) for x in np.median(ropa, axis=0)), len(ropa))
    con_blanco = [i for i in medibles if plan[i]]
    with candado:
        cuenta["total"] = len(medibles) + len(con_blanco)
    grises = [None] * len(fotos)
    with ThreadPoolExecutor(max_workers=2 * a_la_vez) as pool:
        for i, d in zip(con_blanco, pool.map(contar(
                lambda i: gris_rapido(fotos[i][0], plan[i][0], fuerza_balance, fuerza_niveles)), con_blanco)):
            grises[i] = d
    for g in grupos:
        for j, i in enumerate(g):
            if plan[i]:
                medidas = [grises[v] for v in vecinas(g, j, datos) if grises[v] is not None]
                gris = tuple(float(x) for x in np.median(medidas, axis=0)) if len(medidas) >= SERIE_MINIMO else None
                plan[i] = plan[i] + (gris,)
    return plan


def procesar_foto(trabajo):
    """Ajusta y guarda una foto (corre en un proceso aparte). trabajo: (foto, carpeta de salida,
    opciones, (blanco de la serie, n, dominante de la serie) o None). Devuelve (foto, destino o None si ya estaba ajustada o
    "error", segundos, texto). Una foto danada o rara no detiene el lote (en mejorar_fotos.py un JPG
    corrupto terminaba el programa y dejaba sin hacer las fotos que venian despues)."""
    f, salida, args, plan = trabajo
    try:
        inicio = time.time()
        original = Image.open(f)
        if ya_mejorada(original):
            return f, None, 0.0, ""
        salida.mkdir(exist_ok=True)
        icc = original.info.get("icc_profile")
        adobe = es_adobe_rgb(original)
        img = ImageOps.exif_transpose(original)  # endereza segun la camara
        if adobe:  # se ajusta y se guarda en sRGB, con su perfil y el EXIF diciendo sRGB
            img = Image.fromarray(adobe_a_srgb(np.asarray(img.convert("RGB"))))
            icc = perfil_srgb()
        blanco_serie, n, gris_serie = plan or (None, 0, None)
        resultado, info = mejorar(img, args.fuerza, args.calidez, args.enfoque, args.ruido,
                                  args.luz, args.contraste, args.color, blanco_serie, gris_serie)
        if blanco_serie:
            info += f", balance de serie ({n} fotos)"
        destino = salida / (f.stem + ".jpg")
        exif_obj = original.getexif()
        exif_obj[0x0112] = 1  # orientacion ya aplicada
        exif_obj[TAG_SOFTWARE] = firma(args)
        if adobe:
            exif_obj.get_ifd(0x8769)[0xA001] = 1  # espacio de color: sRGB
            try:
                interop = exif_obj.get_ifd(0xA005)
                if interop:
                    interop[1] = "R98"
            except Exception:
                pass
        opciones = {"quality": 95, "subsampling": 0, "exif": exif_obj.tobytes()}
        if icc:
            opciones["icc_profile"] = icc
        # Se guarda con otro nombre y se renombra al final: si se cierra la ventana a mitad de
        # camino no queda un JPG a medias con el nombre de la foto
        parcial = destino.with_name(destino.name + ".parcial")
        try:
            resultado.save(parcial, format="JPEG", **opciones)
            os.replace(parcial, destino)
        finally:
            if parcial.exists():
                parcial.unlink()
        if args.comparar:
            (salida / "comparar").mkdir(exist_ok=True)
            comparacion(img, resultado, salida / "comparar" / (f.stem + "_antes_despues.jpg"))
        return f, destino, time.time() - inicio, info
    except Exception as e:
        return f, "error", 0.0, f"{type(e).__name__}: {e}"


def main():
    p = argparse.ArgumentParser(description="Ajuste combinado de color e iluminacion de fotos rapidas.")
    p.add_argument("rutas", nargs="+", help="Carpetas y/o fotos sueltas (se pueden mezclar)")
    p.add_argument("--fuerza", type=float, default=1.0,
                   help="Intensidad general 0..1.5 (default 1); multiplica a luz, contraste y color")
    # luz y contraste 1,1 por defecto: lo que hacia mejorar_fotos.py con --fuerza 1.1 (su .bat)
    p.add_argument("--luz", type=float, default=1.1,
                   help="Exposicion de caras, aclarar sombras, moderar luces (0 = no tocar, 1.1 = normal)")
    p.add_argument("--contraste", type=float, default=1.1,
                   help="Curva S, contraste local y puntos negro/blanco (0 = no tocar, 1.1 = normal)")
    p.add_argument("--color", type=float, default=1.0,
                   help="Cuanto suben los colores apagados y se calman los muy intensos (0 = no tocar, 1 = normal)")
    p.add_argument("--calidez", type=float, default=0.0, help="Tono calido -1 (frio) .. 1 (calido). Default 0")
    p.add_argument("--enfoque", type=float, default=1.0,
                   help="0 = sin enfoque, 1 = normal, 2 = fuerte, 3 = maximo (fotos algo blandas)")
    p.add_argument("--ruido", choices=["auto", "si", "no"], default="auto",
                   help="auto = solo si la foto tiene grano (default); si = siempre; no = nunca")
    p.add_argument("--salida", default="combinadas", help="Nombre de la subcarpeta de salida")
    p.add_argument("--comparar", action="store_true", help="Guarda tambien un antes/despues en <salida>\\comparar")
    p.add_argument("--simultaneas", type=int, default=0,
                   help="Fotos procesadas a la vez (default: automatico, de 1 a 3 segun la RAM y los nucleos)")
    p.add_argument("--serie", choices=["si", "no"], default="si",
                   help="si = las fotos seguidas con la misma luz llevan el mismo balance de blancos "
                        "(default); no = cada foto con su propio balance")
    p.add_argument("--rehacer", action="store_true",
                   help="Ajusta de nuevo tambien las fotos que ya estan hechas en <salida> (por defecto se saltan)")
    p.add_argument("--sin-ventana", action="store_true",
                   help="Solo la consola, sin la ventana animada")
    args = p.parse_args()
    a_toda_velocidad()

    # La ventana animada (ventana_vso.py) va en otro proceso: si no abre, se cierra o falla, el lote
    # sigue igual en la consola. No cambia nada de como se ajustan las fotos.
    pantalla = None
    if not args.sin_ventana:
        try:
            import ventana_vso
            pantalla = ventana_vso.Pantalla()
            pantalla.abrir()
        except Exception as e:
            print(f"(La ventana animada no se pudo abrir: {type(e).__name__}. Sigue en la consola.)")
            pantalla = None

    def avisar(**datos):
        if pantalla:
            pantalla.enviar(**datos)

    sin_yunet = falta_yunet()
    aviso_yunet = (f"OJO: {sin_yunet}. Sin el detector no se ve ninguna cara: las fotos se ajustan con el "
                   f"brillo de toda la foto y las caras pueden quedar oscuras. Copia ese archivo a la carpeta "
                   f"del programa.") if sin_yunet else None
    if aviso_yunet:
        print(aviso_yunet + "\n")
    avisos_inicio = []
    fotos = juntar_fotos(args.rutas, args.salida, avisos_inicio)
    if not fotos:
        if pantalla:
            pantalla.cerrar()
        sys.exit("No encontré fotos en lo que se arrastró.")
    dobles = repetidas(fotos)
    if args.rehacer:
        hechas_antes = set()
    else:
        hechas_antes = {f for f, salida in fotos if ya_hecha(f, salida, args)}
    if hechas_antes:
        print(f"{len(hechas_antes)} de {len(fotos)} fotos ya estaban ajustadas en '{args.salida}' con estos "
              f"mismos ajustes: se saltan (--rehacer para hacerlas de nuevo).")
    pendientes = [(f, salida) for f, salida in fotos if f not in hechas_antes]
    a_la_vez = args.simultaneas if args.simultaneas > 0 else cuantas_a_la_vez(pendientes or fotos)
    plan = [None] * len(fotos)
    medir = bool(pendientes and args.serie != "no" and len(fotos) >= SERIE_MINIMO)
    if sin_yunet:
        avisos_inicio.append("falta el detector de caras: no se ve ninguna cara y pueden quedar oscuras")
    avisar(e="inicio", total=len(fotos), ya=len(hechas_antes), medir=medir, avisos=avisos_inicio)
    # La serie se mide con TODAS las fotos (tambien las ya hechas): asi un lote retomado da lo mismo
    # que si se hubiera hecho de una vez
    if medir:
        inicio = time.time()
        try:
            plan = plan_serie(fotos, a_la_vez, 0.88 * args.fuerza, 0.6 * args.fuerza * args.contraste,
                              avance=lambda hecho, total: avisar(e="medida", hecho=hecho, total=total))
            print(f"Balance por serie: {sum(1 for x in plan if x)} de {len(fotos)} fotos ({time.time() - inicio:.0f} s)")
        except Exception as e:  # una foto rara no debe impedir ajustar las demas: cada una con su balance
            print(f"Balance por serie no disponible ({type(e).__name__}): cada foto con su propio balance")
    plan_de = {f: x for (f, _), x in zip(fotos, plan)}

    # Cada foto va en su propio proceso: con hilos (como en mejorar_fotos.py) las fotos "a la vez"
    # se turnaban el interprete de Python y 3 a la vez rendian poco mas que una
    if pendientes:
        print(f"{len(pendientes)} foto{'s' if len(pendientes) > 1 else ''}, {a_la_vez} a la vez")
    avisar(e="ajustar", a_la_vez=a_la_vez, en_vuelo=min(a_la_vez, len(pendientes)))
    inicio_total = time.time()
    hechas, omitidas, errores, carpetas = 0, 0, [], set()
    trabajos = [(f, salida, args, plan_de[f]) for f, salida in pendientes]
    contador = [0]
    en_vuelo = [0]

    def informar(f, destino, segundos, info):
        nonlocal hechas, omitidas
        contador[0] += 1
        n = f"[{contador[0]}/{len(pendientes)}] {f.name}"
        if destino is None:
            omitidas += 1
            print(f"{n}  (ya estaba ajustada, se omite)")
        elif destino == "error":
            errores.append(f.name)
            print(f"{n}  NO SE PUDO AJUSTAR ({info})")
        else:
            hechas += 1
            carpetas.add(destino.parent)
            print(f"{n} -> {destino.parent.name}\\{destino.name}  ({segundos:.1f} s, {info})")
        faltan = len(pendientes) - contador[0]
        avisar(e="foto", ok=destino != "error", nombre=f.name, en_vuelo=min(en_vuelo[0], faltan))

    # Si un proceso se cae de golpe (ej. sin memoria), Python da por perdidas TODAS las fotos que
    # faltaban. Esas se retoman de a una; si vuelve a caerse, la culpable es la primera sin terminar.
    # En la primera vuelta cada foto se cuenta apenas termina (as_completed), asi el avance no va a
    # saltos; en la vuelta de rescate se sigue el orden, que es lo que identifica a la culpable
    ronda, cayo = 0, False
    while trabajos:
        caidas = []
        en_vuelo[0] = a_la_vez if ronda == 0 else 1
        with ProcessPoolExecutor(max_workers=a_la_vez if ronda == 0 else 1, initializer=a_toda_velocidad) as pool:
            futuros = [pool.submit(procesar_foto, t) for t in trabajos]
            if ronda == 0:
                de_cual = {fut: n for n, fut in enumerate(futuros)}
                orden = as_completed(futuros)
            else:
                orden = futuros
            for fut in orden:
                t = trabajos[de_cual[fut]] if ronda == 0 else trabajos[futuros.index(fut)]
                try:
                    informar(*fut.result())
                except BrokenProcessPool:
                    caidas.append(t)
                except Exception as e:
                    informar(t[0], "error", 0.0, f"{type(e).__name__}: {e}")
        if ronda == 0:
            caidas.sort(key=lambda t: trabajos.index(t))
        if caidas and ronda > 0:
            informar(caidas[0][0], "error", 0.0, "el programa se cae con esta foto")
            caidas = caidas[1:]
        elif caidas:
            cayo = True
            print(f"Se cayó un proceso: las {len(caidas)} fotos que faltaban se hacen de a una.")
            avisar(e="caida", faltan=len(caidas))
        trabajos, ronda = caidas, ronda + 1

    total = time.time() - inicio_total
    if hechas or not hechas_antes:
        print(f"\nListo. {hechas} fotos en {total:.0f} s" + (f" ({total / hechas:.1f} s por foto)" if hechas else ""))
    else:
        print("\nListo. No había fotos nuevas que ajustar.")
    if omitidas:
        print(f"{omitidas} fotos omitidas porque ya estaban ajustadas.")
    if errores:
        print(f"{len(errores)} fotos NO se pudieron ajustar (archivo dañado o ilegible): {', '.join(errores)}")
    for c in sorted(carpetas):
        print(f"Guardadas en: {c}")
    avisos_fin = list(avisos_inicio)
    for grupo in dobles:
        carpetas_g = {f.parent for f in grupo}
        nombres = [f"{f.parent.name}\\{f.name}" if len(carpetas_g) > 1 else f.name for f in grupo]
        print(f"OJO, fotos repetidas (son la misma; si las imprimes salen dos veces): {' = '.join(nombres)}")
        avisos_fin.append("fotos repetidas (si las imprimes salen dos veces): " + " = ".join(f.name for f in grupo))
    if aviso_yunet:
        print(aviso_yunet)
    if not carpetas and hechas_antes:      # nada nuevo: el boton abre la carpeta donde ya estaban
        carpetas = {salida for f, salida in fotos if f in hechas_antes}
    if pantalla:
        mostro = pantalla.terminar(hechas=hechas, segundos=total, ya=len(hechas_antes),
                                   carpetas=[str(c) for c in sorted(carpetas)], errores=errores, caido=cayo,
                                   avisos=avisos_fin, omitidas=omitidas)
        if mostro and not pantalla.mirar_consola:
            sys.exit(3)                    # el .bat entiende que no hace falta "presione una tecla"
        pantalla.mostrar_consola()
    if errores:
        sys.exit(1)


if __name__ == "__main__":
    main()
