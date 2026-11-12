/* =========================================================
   MI MIRADA · 8 fotos que se ordenan al bajar (según el boceto de Víctor)
   Cada foto sale de un costado (1 izquierda, 2 derecha, 3 izquierda…),
   sube en arco, se muestra en grande al centro y luego baja a su lugar.
   Lugar final, en una "mesa" de 100 de ancho × 46 de alto:
     fila de arriba (formas chicas y curvas):   2  5  6  1
     fila de abajo  (formas más grandes):       4  7  8  3
   x, y, w, h = posición y tamaño · r = curvas de las esquinas (%) · g = giro final
   ========================================================= */
(function () {
  const sec = document.querySelector('.mirada');
  if (!sec) return;
  const escena = sec.querySelector('.escena');
  const mesa = sec.querySelector('.mesa');
  const piezas = [...mesa.querySelectorAll('.pieza')];

  const LUGAR = {
    1: { x: 82, y: 3,  w: 12, h: 12, r: [9, 9, 9, 9, 9, 9, 9, 9], g: 4, fila: 1 },               // cuadrado chico
    2: { x: 8,  y: 2,  w: 15, h: 15, r: [58, 42, 50, 46, 48, 56, 44, 52], g: -3, fila: 1 },     // mancha redonda
    3: { x: 81, y: 21, w: 19, h: 21, r: [6, 80, 12, 8, 6, 100, 30, 8], g: 2, fila: 2 },        // forma curva
    4: { x: 0,  y: 20, w: 19, h: 22, r: [48, 52, 5, 46, 50, 46, 5, 52], g: -2, fila: 2 },      // redonda con una punta
    5: { x: 31, y: 0,  w: 14, h: 14, r: [50, 50, 50, 50, 50, 50, 50, 50], g: 0, fila: 1 },     // círculo
    6: { x: 57, y: 2,  w: 15, h: 14, r: [50, 50, 46, 46, 44, 44, 56, 56], g: 3, fila: 1 },     // piedra
    7: { x: 24, y: 21, w: 24, h: 22, r: [3, 3, 24, 3, 3, 3, 24, 3], g: -1, fila: 2 },          // rectángulo
    8: { x: 52, y: 22, w: 26, h: 21, r: [3, 3, 3, 3, 3, 3, 3, 3], g: 1.5, fila: 2 },           // rectángulo ancho
  };
  const R_GRANDE = [2, 2, 2, 2, 2, 2, 2, 2];

  const N = piezas.length;
  const PASO = 1;        // una foto nueva por cada "paso" de scroll
  const DURA = 1.6;      // cada foto dura 1,6 pasos (se traslapan un poco)
  const TOTAL = (N - 1) * PASO + DURA;
  const VH_POR_PASO = 55; // alto de scroll (en % de pantalla) por paso
  const quieta = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const suave = (t) => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  const sale = (t) => 1 - Math.pow(1 - t, 3);
  const curva = (a, c, b, t) => (1 - t) * (1 - t) * a + 2 * (1 - t) * t * c + t * t * b;
  const radio = (r) => `${r[0]}% ${r[1]}% ${r[2]}% ${r[3]}% / ${r[4]}% ${r[5]}% ${r[6]}% ${r[7]}%`;

  piezas.forEach((p) => p.classList.add('fila-' + LUGAR[p.dataset.n].fila));

  if (quieta) sec.classList.add('quieta');
  else sec.style.height = `calc(100svh + ${Math.round(TOTAL * VH_POR_PASO)}svh)`;

  function pintar() {
    const E = escena.getBoundingClientRect();
    const M = mesa.getBoundingClientRect();
    const ox = M.left - E.left, oy = M.top - E.top;   // la mesa dentro de la escena
    const u = M.width / 100;

    // avance: empieza un poco antes de que la escena quede fija
    let P = TOTAL;
    if (!quieta) {
      const r = sec.getBoundingClientRect();
      const antes = E.height * .45;
      // termina antes del final, para que se vea un momento todo ordenado
      const rango = sec.offsetHeight - E.height + antes - E.height * .4;
      P = clamp((antes - r.top) / rango) * TOTAL;
    }

    let completas = 0;
    piezas.forEach((p, i) => {
      const L = LUGAR[p.dataset.n];
      const a = parseFloat(p.dataset.a) || 1.3;
      const izq = i % 2 === 0;
      let t = clamp((P - i * PASO) / DURA);
      if (t > .999) t = 1;   // evita que el redondeo deje la última foto en 0,99999

      // lugar final (en px, coordenadas de la escena)
      const fw = L.w * u, fh = L.h * u, fx = ox + L.x * u + fw / 2, fy = oy + L.y * u + fh / 2;
      // tamaño grande al centro
      // grande: casi toda la pantalla, bajo el encabezado (68 px)
      const gh = Math.min(E.height - 68 - 36, E.width * .92 / a);
      const gw = gh * a, gx = E.width / 2, gy = 68 + (E.height - 68) / 2;
      // salida desde el costado, abajo
      const sw = gw * .5, sh = gh * .5;
      const sx = izq ? -sw * .7 : E.width + sw * .7, sy = E.height * .82;

      let cx, cy, w, h, giro, rad, op = 1, sombra;
      if (t <= 0) { p.style.visibility = 'hidden'; p.classList.remove('puesta', 'activa'); return; }
      p.style.visibility = 'visible';

      if (t < .42) {                       // sale del costado y sube en arco
        const k = sale(t / .42);
        cx = curva(sx, lerp(sx, gx, .65), gx, k);
        cy = curva(sy, E.height * .42, gy, k);
        w = lerp(sw, gw, k); h = lerp(sh, gh, k);
        giro = lerp(izq ? -14 : 14, 0, k);
        rad = R_GRANDE; op = clamp(t / .08); sombra = k;
      } else if (t < .58) {                // se muestra en grande
        const k = (t - .42) / .16;
        cx = gx; cy = gy - Math.sin(k * Math.PI) * 8;
        w = gw; h = gh; giro = 0; rad = R_GRANDE; sombra = 1;
      } else {                             // baja y se ordena
        const k = suave((t - .58) / .42);
        cx = curva(gx, fx, fx, k);
        cy = curva(gy, gy, fy, k);
        w = lerp(gw, fw, k); h = lerp(gh, fh, k);
        giro = lerp(0, L.g, k);
        rad = R_GRANDE.map((v, j) => lerp(v, L.r[j], k));
        sombra = 1 - k;
      }

      p.style.left = (cx - w / 2 - ox) + 'px';
      p.style.top = (cy - h / 2 - oy) + 'px';
      p.style.width = w + 'px';
      p.style.height = h + 'px';
      p.style.transform = `rotate(${giro}deg)`;
      p.style.opacity = op;
      p.style.setProperty('--sombra', sombra);
      p.firstElementChild.style.borderRadius = radio(rad);
      p.style.zIndex = t < 1 ? 20 + i : 1;
      p.classList.toggle('activa', t > 0 && t < 1);
      p.classList.toggle('puesta', t >= 1);
      if (t >= 1) completas++;
    });
    escena.classList.toggle('completa', completas === N);
  }

  let pendiente = false;
  const pedir = () => { if (!pendiente) { pendiente = true; requestAnimationFrame(() => { pendiente = false; pintar(); }); } };
  addEventListener('scroll', pedir, { passive: true });
  addEventListener('resize', pedir);
  pintar();
})();
