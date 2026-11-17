/* CUADROS DE GENERACIÓN · cuadro 3D con el modelo real del marco de pino (hecho en Blender,
   el mismo de la web de Silva Fotografías). Las miniaturas cambian el diseño impreso sin recargar el modelo.
   El visor (~270 KB) y el modelo (~700 KB) se piden solo cuando la sección se acerca. */
(function () {
  const mv = document.getElementById('cuadro3d');
  if (!mv) return;
  const botones = [...document.querySelectorAll('.cuadros-miniaturas button')];

  // Abierta con doble clic (file://) el navegador no deja leer cuadro.glb ni las impresiones:
  // se usa una copia que va dentro de img/cuadros/3d/solo-local.js (lo genera armar_cuadros.py).
  const LOCAL = location.protocol === 'file:';
  const cargarVisor = () => {
    if (document.getElementById('mvScript')) return;
    const s = document.createElement('script');
    s.type = 'module'; s.id = 'mvScript';
    s.src = 'https://cdn.jsdelivr.net/npm/@google/model-viewer@4.0.0/dist/model-viewer.min.js';
    if (!LOCAL) return document.head.append(s);
    const d = document.createElement('script');
    d.src = 'img/cuadros/3d/solo-local.js';
    d.onload = () => { mv.setAttribute('src', window.CUADRO3D_LOCAL.glb); document.head.append(s); };
    document.head.append(d);
  };
  if (LOCAL) mv.removeAttribute('src');   // sin esto el visor intenta leer el .glb y falla
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { cargarVisor(); io.disconnect(); } }, { rootMargin: '900px 0px' });
    io.observe(mv);
  } else cargarVisor();

  // Pone el diseño n (img/cuadros/3d/impresion-n.jpg) en la impresión del cuadro
  const texturas = {};
  let pedido = null;   // el último diseño elegido: si una textura llega tarde, no pisa a la más nueva
  async function ponerDiseno(n) {
    pedido = n;
    if (!mv.model) return;
    const mat = mv.model.getMaterialByName('Impresion');
    if (!mat) return;
    const url = LOCAL ? window.CUADRO3D_LOCAL['impresion-' + n] : 'img/cuadros/3d/impresion-' + n + '.jpg';
    texturas[n] = texturas[n] || mv.createTexture(url, 'image/jpeg');
    let tex;
    try { tex = await texturas[n]; } catch (e) { delete texturas[n]; return; }   // si falla, se reintenta al volver a elegirlo
    if (pedido !== n) return;
    mat.pbrMetallicRoughness.baseColorTexture.setTexture(tex);
  }

  // El modelo trae un diseño de 2025: apenas carga se cambia por el diseño elegido (el 1 de partida).
  // Además del evento "load" se revisa cada medio segundo, porque en pestañas en segundo plano el evento se atrasa.
  let inicial = false;
  const ponerInicial = () => {
    if (inicial || !mv.loaded || !mv.model) return;
    inicial = true;
    const elegido = botones.find(b => b.getAttribute('aria-pressed') === 'true');
    ponerDiseno(elegido ? elegido.dataset.n : '1');
  };
  mv.addEventListener('load', ponerInicial);
  const revisar = setInterval(() => { ponerInicial(); if (inicial) clearInterval(revisar); }, 500);

  botones.forEach(b => b.addEventListener('click', () => {
    if (b.getAttribute('aria-pressed') === 'true') return;
    botones.forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    ponerDiseno(b.dataset.n);
  }));
})();
