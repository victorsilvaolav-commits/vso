/* Motor de la página "Ajustar fotos".
   Corre ajuste/ajuste_combinado.py (el mismo programa del PC, sin cambios) dentro del navegador con
   Pyodide (Python hecho WebAssembly), en un hilo aparte para que la página no se congele.
   Las fotos se leen y se ajustan aquí mismo: no se suben a ningún lado.
   Es un worker de tipo módulo (import): con importScripts algunos navegadores no cargan Pyodide. */
import { loadPyodide } from 'https://cdn.jsdelivr.net/pyodide/v314.0.8/full/pyodide.mjs';

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v314.0.8/full/';
// VSO App 1.4 (25-11-2026): el estilo Lightroom y sus ayudantes, mas el modelo de puntos de la cara
const ARCHIVOS = ['ajuste_combinado.py', 'web_ajuste.py', 'face_detection_yunet_2023mar.onnx',
  'estilo_lightroom.py', 'estilo_lightroom.npz', 'enfoque_vso.py', 'retoque_vso.py',
  'face_landmarks_detector.tflite'];

let py = null, web = null, trabajando = false;
const cola = [];
const texto = (e) => String((e && e.message) || e);

const listo = (async () => {
  postMessage({ tipo: 'carga', paso: 'Descargando Python', avance: 0.08 });
  py = await loadPyodide({ indexURL: PYODIDE });
  postMessage({ tipo: 'carga', paso: 'Descargando OpenCV y el detector de caras', avance: 0.4 });
  const [, ...datos] = await Promise.all([
    py.loadPackage(['numpy', 'opencv-python', 'pillow'], { messageCallback: () => {} }),
    ...ARCHIVOS.map((n) => fetch('../ajuste/' + n, { cache: 'no-cache' }).then((r) => {
      if (!r.ok) throw new Error('no se pudo descargar ' + n);
      return r.arrayBuffer();
    })),
  ]);
  postMessage({ tipo: 'carga', paso: 'Preparando el ajuste', avance: 0.9 });
  py.FS.mkdirTree('/ajuste');
  py.FS.mkdirTree('/entrada');
  ARCHIVOS.forEach((n, i) => py.FS.writeFile('/ajuste/' + n, new Uint8Array(datos[i])));
  py.runPython("import sys; sys.path.insert(0, '/ajuste')");
  web = py.pyimport('web_ajuste');
  postMessage({ tipo: 'listo', version: web.version(), sinDetector: web.sin_detector() });
})();
listo.catch((e) => postMessage({ tipo: 'falla', texto: texto(e) }));

onmessage = (e) => {
  if (e.data.tipo !== 'lote') return;
  cola.push(e.data);
  if (!trabajando) trabajar();
};

async function trabajar() {
  trabajando = true;
  try { await listo; } catch (_) { trabajando = false; return; }
  while (cola.length) {
    const lote = cola.shift();
    for (const f of lote.fotos) {
      py.FS.mkdirTree('/entrada/' + f.clave);
      py.FS.writeFile('/entrada/' + f.clave + '/' + f.nombre, new Uint8Array(f.datos));
      f.datos = null;
    }
    const claves = lote.fotos.map((f) => f.clave);
    // Balance por serie: las fotos seguidas con la misma luz quedan parejas (como en el PC)
    if (claves.length >= 3) postMessage({ tipo: 'midiendo', total: claves.length });
    let enSerie = 0;
    try { enSerie = web.planear(JSON.stringify(claves)); } catch (_) { /* cada una con su balance */ }
    postMessage({ tipo: 'serie', enSerie, total: claves.length });

    for (const clave of claves) {
      postMessage({ tipo: 'empieza', clave });
      try {
        if (lote.megapixeles) web.reducir(clave, lote.megapixeles);
        const r = JSON.parse(web.ajustar(clave));
        if (r.estado === 'lista') {
          const bytes = py.FS.readFile(r.ruta);
          postMessage({ tipo: 'foto', clave, ...r, datos: bytes.buffer }, [bytes.buffer]);
        } else {
          postMessage({ tipo: 'foto', clave, ...r });
        }
      } catch (err) {
        // Python se cayó (casi siempre por memoria): este motor ya no sirve, la página crea otro
        postMessage({ tipo: 'roto', clave, texto: texto(err).slice(-400) });
        return;
      } finally {
        try { web.limpiar(clave); } catch (_) { /* nada */ }
      }
    }
  }
  trabajando = false;
}
