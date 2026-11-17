/* INTRO · puntos sueltos (estrellas) → luna → diafragma de lente → letras VSO.
   Cada figura es "algo que hago": observar el cielo, enfocar con la cámara, diseñar.
   Las letras se toman de los mismos trazos del logo oficial, por eso calzan exacto. */
(function () {
  const intro = document.querySelector('.intro');
  if (!intro) return;
  const canvas = intro.querySelector('canvas');
  const ctx = canvas.getContext('2d');
  const svg = intro.querySelector('.logo-intro');
  const rotulo = intro.querySelector('.rotulo');
  const VB = svg.viewBox.baseVal;
  const CX = 300, CY = 180;                // centro del encuadre en unidades del logo
  const COLOR = '#1A2129';
  const letras = ['lg-V', 'lg-S', 'lg-O'].map(id => new Path2D(document.querySelector(`#${id} path`).getAttribute('d')));

  // Línea de tiempo (ms)
  const FASES = [
    { forma: 'estrellas', ini: 0,    dur: 700,  rotulo: '' },
    { forma: 'luna',      ini: 700,  dur: 1300, rotulo: 'Observar' },
    { forma: 'diafragma', ini: 2600, dur: 1200, rotulo: 'Enfocar' },
    { forma: 'letras',    ini: 4400, dur: 1300, rotulo: 'Diseñar' }
  ];
  const FIN = 6000;

  let W = 0, H = 0, dpr = 1, N = 0, puntos = [], formas = {}, t0 = 0, raf = 0, faseActual = -1, terminado = false;
  const azar = (a, b) => a + Math.random() * (b - a);
  const suave = (x) => x <= 0 ? 0 : x >= 1 ? 1 : x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;

  function medir() {
    const r = canvas.getBoundingClientRect();
    W = r.width; H = r.height; dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    const s = svg.getBoundingClientRect();
    const k = s.width / VB.width;
    return { k, ox: s.left - r.left - VB.x * k, oy: s.top - r.top - VB.y * k };
  }

  // Dibuja una figura en un lienzo aparte y devuelve los píxeles rellenos
  function muestrear(dibujar, m, objetivo) {
    const c = document.createElement('canvas');
    c.width = Math.ceil(W); c.height = Math.ceil(H);
    const g = c.getContext('2d', { willReadFrequently: true });
    g.setTransform(m.k, 0, 0, m.k, m.ox, m.oy);
    g.fillStyle = '#000'; g.strokeStyle = '#000';
    dibujar(g);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    let total = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 128) total++;
    const paso = Math.max(1, Math.sqrt(total / (objetivo || 1500)));
    const pts = [];
    for (let y = paso / 2; y < c.height; y += paso)
      for (let x = paso / 2; x < c.width; x += paso) {
        const xi = x | 0, yi = y | 0;
        if (d[(yi * c.width + xi) * 4 + 3] > 128) pts.push([x + azar(-.3, .3) * paso, y + azar(-.3, .3) * paso]);
      }
    return { pts, total };
  }

  const FIGURAS = {
    luna(g) {
      g.beginPath(); g.arc(CX, CY, 84, 0, Math.PI * 2); g.fill();
      g.globalCompositeOperation = 'destination-out';
      g.beginPath(); g.arc(CX + 38, CY - 22, 76, 0, Math.PI * 2); g.fill();
    },
    diafragma(g) {
      // anillo exterior + abertura hexagonal + aspas, todo en línea para que se lea con puntos
      const R = 92, v = [];
      for (let i = 0; i < 6; i++) { const a = i * Math.PI / 3 + .3; v.push([CX + 36 * Math.cos(a), CY + 36 * Math.sin(a)]); }
      g.lineWidth = 9; g.beginPath(); g.arc(CX, CY, R, 0, Math.PI * 2); g.stroke();
      g.lineWidth = 6; g.lineJoin = 'round';
      g.beginPath(); v.forEach((p, i) => i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])); g.closePath(); g.stroke();
      g.save(); g.beginPath(); g.arc(CX, CY, R, 0, Math.PI * 2); g.clip();
      for (let i = 0; i < 6; i++) {           // aspas: prolongación de cada lado del hexágono hasta el anillo
        const a = v[i], b = v[(i + 1) % 6];
        const dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy);
        g.beginPath(); g.moveTo(b[0], b[1]); g.lineTo(b[0] + dx / l * 120, b[1] + dy / l * 120); g.stroke();
      }
      g.restore();
    },
    letras(g) { letras.forEach(p => g.fill(p)); }
  };

  // Ordena por ángulo alrededor del centro para que la transformación gire y no se cruce al azar
  function ajustar(pts, n, c) {
    const out = pts.slice();
    for (let i = out.length - 1; i > 0; i--) { const j = Math.random() * (i + 1) | 0; [out[i], out[j]] = [out[j], out[i]]; }
    while (out.length < n) out.push(out[Math.random() * pts.length | 0].slice());
    out.length = n;
    return out.sort((a, b) => Math.atan2(a[1] - c[1], a[0] - c[0]) - Math.atan2(b[1] - c[1], b[0] - c[0]));
  }

  function preparar() {
    const m = medir();
    const c = [m.ox + CX * m.k, m.oy + CY * m.k];
    const l = muestrear(FIGURAS.letras, m, 1e9);           // primero solo cuenta píxeles
    const nuevoN = Math.max(1400, Math.min(3200, Math.round(l.total / 2.2)));
    const reiniciar = nuevoN !== N || !puntos.length;
    N = nuevoN;
    formas = {
      centro: c,
      letras: ajustar(muestrear(FIGURAS.letras, m, N).pts, N, c),
      luna: ajustar(muestrear(FIGURAS.luna, m, N).pts, N, c),
      diafragma: ajustar(muestrear(FIGURAS.diafragma, m, N).pts, N, c),
      estrellas: ajustar(Array.from({ length: N }, () => [azar(0, W), azar(0, H)]), N, c)
    };
    if (reiniciar) {
      puntos = formas.estrellas.map(([x, y]) => ({ x, y, x0: x, y0: y, r: azar(.5, 1.7), tw: azar(0, 6.28), d: Math.random() }));
    }
  }

  // Destino de cada punto en un momento dado (el diafragma gira mientras se forma)
  function destino(forma, i, t) {
    const p = formas[forma][i];
    if (forma !== 'diafragma') return p;
    const a = .9 * suave((t - FASES[2].ini) / 1700) - .9;
    const [cx, cy] = formas.centro, dx = p[0] - cx, dy = p[1] - cy;
    return [cx + dx * Math.cos(a) - dy * Math.sin(a), cy + dx * Math.sin(a) + dy * Math.cos(a)];
  }

  const LENTO = +new URLSearchParams(location.search).get('lento') || 1;   // ?lento=5 para revisar en cámara lenta
  function cuadro(ahora) {
    const t = (ahora - t0) / LENTO;
    let f = 0;
    for (let i = 0; i < FASES.length; i++) if (t >= FASES[i].ini) f = i;
    if (f !== faseActual) {                       // al empezar una fase, se guarda el punto de partida
      faseActual = f;
      puntos.forEach(p => { p.x0 = p.x; p.y0 = p.y; });
      rotulo.textContent = FASES[f].rotulo;
      rotulo.classList.toggle('visible', !!FASES[f].rotulo);
    }
    const fase = FASES[f];
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = COLOR;
    const base = f === 0 ? 0 : .95;
    for (let i = 0; i < N; i++) {
      const p = puntos[i];
      if (f > 0) {
        const k = suave((t - fase.ini - p.d * 350) / (fase.dur - 350));
        const [tx, ty] = destino(fase.forma, i, t);
        p.x = p.x0 + (tx - p.x0) * k; p.y = p.y0 + (ty - p.y0) * k;
        p.r += (base - p.r) * .08;
      }
      let a = 1;
      if (f === 0) a = Math.min(1, t / 500) * (.55 + .45 * Math.sin(t / 180 + p.tw));
      ctx.globalAlpha = a;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.2832); ctx.fill();
    }
    ctx.globalAlpha = 1;
    if (t >= FASES[3].ini + FASES[3].dur - 100) { rotulo.classList.remove('visible'); }
    if (t >= FIN) return terminar();
    raf = requestAnimationFrame(cuadro);
  }

  function terminar() {
    cancelAnimationFrame(raf);
    clearTimeout(esperaTamano); esperaTamano = null;
    terminado = true;
    rotulo.classList.remove('visible');
    intro.classList.add('final');
    canvas.style.transition = 'opacity .5s'; canvas.style.opacity = 0;
  }

  // ¿Ya tienen tamaño el lienzo y el logo? (abierta en segundo plano o dentro de algo oculto pueden medir 0)
  const tieneTamano = () => {
    const r = canvas.getBoundingClientRect(), s = svg.getBoundingClientRect();
    return r.width >= 1 && r.height >= 1 && s.width >= 1;
  };
  let esperaTamano = null;

  function iniciar() {
    cancelAnimationFrame(raf);
    clearTimeout(esperaTamano); esperaTamano = null;
    if (!tieneTamano()) {                      // espera a tener tamaño en vez de romperse
      terminado = false;
      esperaTamano = setTimeout(() => { esperaTamano = null; if (!terminado) iniciar(); }, 200);
      return;
    }
    terminado = false; faseActual = -1; puntos = [];
    intro.classList.remove('final');
    canvas.style.transition = 'none'; canvas.style.opacity = 1;
    try { preparar(); } catch (e) { return terminar(); }   // si algo falla, se muestra el logo final igual
    t0 = performance.now();
    raf = requestAnimationFrame(cuadro);
  }

  intro.querySelector('.saltar').addEventListener('click', terminar);
  intro.querySelector('.repetir').addEventListener('click', iniciar);
  let espera;
  addEventListener('resize', () => {
    clearTimeout(espera);
    espera = setTimeout(() => {
      if (terminado || esperaTamano || !tieneTamano()) return;
      const t = performance.now() - t0;
      try { preparar(); } catch (e) { return terminar(); }
      faseActual = -1; t0 = performance.now() - t;
    }, 150);
  });

  // Para revisar una figura quieta desde la consola: introVer('diafragma')
  window.introVer = (forma) => {
    cancelAnimationFrame(raf); preparar();
    canvas.style.transition = 'none'; canvas.style.opacity = 1; intro.classList.remove('final');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H); ctx.fillStyle = COLOR;
    formas[forma].forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, .95, 0, 6.2832); ctx.fill(); });
    return N;
  };

  if (matchMedia('(prefers-reduced-motion: reduce)').matches) terminar();
  else requestAnimationFrame(() => { if (!terminado) iniciar(); });
})();
