/* Comportamiento común: menú, comparador antes/después, visor de fotos, tarjetas. */
(function () {
  const P = window.PORTAFOLIO || [];
  const foto = (f) => `fotos/${f}.jpg`;
  const flecha = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 12h15M13 6l6 6-6 6"/></svg>';
  const params = new URLSearchParams(location.search);
  const catActual = document.body.dataset.pagina === 'categoria' ? params.get('c') : null;

  /* ---------- Encabezado y menú ---------- */
  const cab = document.querySelector('.encabezado');
  if (cab) {
    const sub = cab.querySelector('.submenu');
    sub.innerHTML = P.map(c => `<a href="categoria.html?c=${c.id}"${c.id === catActual ? ' aria-current="page"' : ''}>${c.titulo}<small>${c.fotos.length ? c.fotos.length : 'pronto'}</small></a>`).join('');
    const desp = cab.querySelector('.desplegar');
    const btn = desp.querySelector('button');
    if (catActual) desp.classList.add('activo');
    btn.addEventListener('click', (e) => { e.stopPropagation(); const a = desp.classList.toggle('abierto'); btn.setAttribute('aria-expanded', a); });
    if (matchMedia('(hover: hover)').matches) {
      desp.addEventListener('mouseenter', () => { if (innerWidth > 760) desp.classList.add('abierto'); });
      desp.addEventListener('mouseleave', () => { if (innerWidth > 760) desp.classList.remove('abierto'); });
    }
    document.addEventListener('click', (e) => { if (!desp.contains(e.target)) desp.classList.remove('abierto'); });
    const bm = cab.querySelector('.boton-menu');
    bm.addEventListener('click', () => { const a = document.body.classList.toggle('menu-abierto'); bm.setAttribute('aria-expanded', a); });
    cab.querySelectorAll('.menu a').forEach(a => a.addEventListener('click', () => document.body.classList.remove('menu-abierto')));

    // En la portada, el encabezado aparece al pasar la intro
    const intro = document.querySelector('.intro');
    if (intro) {
      const revisar = () => cab.classList.toggle('oculto', scrollY < intro.offsetHeight * .6 && !document.body.classList.contains('menu-abierto'));
      addEventListener('scroll', revisar, { passive: true }); revisar();
    }
  }

  /* ---------- Aparecer al hacer scroll ---------- */
  const io = 'IntersectionObserver' in window ? new IntersectionObserver((es) => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('visto'); io.unobserve(e.target); } }), { rootMargin: '0px 0px -8% 0px' }) : null;
  const observar = (el) => io ? io.observe(el) : el.classList.add('visto');

  /* ---------- Comparador antes / después ---------- */
  function comparador(el) {
    const perilla = el.querySelector('.perilla');
    const rA = el.querySelector('.r-antes'), rD = el.querySelector('.r-despues');
    let p = 100, manual = false, quieto = 0, arrastrando = false;
    const quieta = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const poner = (v) => {
      p = Math.max(0, Math.min(100, v));
      el.style.setProperty('--p', p + '%');
      rA.style.opacity = p > 12 ? 1 : 0; rD.style.opacity = p < 88 ? 1 : 0;
      perilla.setAttribute('aria-valuenow', Math.round(100 - p));
    };
    const desdeX = (x) => { const r = el.getBoundingClientRect(); poner((x - r.left) / r.width * 100); };
    el.addEventListener('pointerdown', (e) => { arrastrando = true; manual = true; el.setPointerCapture(e.pointerId); desdeX(e.clientX); });
    el.addEventListener('pointermove', (e) => { if (arrastrando) desdeX(e.clientX); });
    const soltar = () => { arrastrando = false; quieto = performance.now(); };
    el.addEventListener('pointerup', soltar); el.addEventListener('pointercancel', soltar);
    perilla.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); manual = true; quieto = performance.now(); poner(p + (e.key === 'ArrowLeft' ? -5 : 5)); }
    });
    // Animación automática tipo video: original → editada → original
    // cada tramo termina en t (ms) y va de "desde" a "hasta" (% de la línea)
    const ciclo = [[0], [1400, 100, 100], [3000, 100, 0], [5800, 0, 0], [7400, 0, 100]];
    const total = 7400; let t0 = null, visible = true;
    const ease = (x) => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
    if ('IntersectionObserver' in window) new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(el);
    function cuadro(t) {
      if (manual && !arrastrando && t - quieto > 4000) { manual = false; t0 = null; }
      if (!manual && visible && !quieta) {
        if (t0 === null) { // retoma desde la posición actual
          t0 = t - (p > 50 ? 0 : 3000);
        }
        const k = (t - t0) % total;
        for (let i = 1; i < ciclo.length; i++) {
          if (k <= ciclo[i][0]) {
            const [ta] = ciclo[i - 1], [tb, a, b] = ciclo[i];
            poner(a + (b - a) * ease((k - ta) / (tb - ta)));
            break;
          }
        }
      }
      requestAnimationFrame(cuadro);
    }
    poner(quieta ? 50 : 100);
    requestAnimationFrame(cuadro);
  }
  const htmlComparador = (c) => `
    <div class="comparador visor" aria-label="Comparación antes y después: ${c.titulo}">
      <img class="antes" src="${foto(c.antes)}" alt="${c.titulo}, foto original" draggable="false">
      <img class="despues" src="${foto(c.despues)}" alt="${c.titulo}, fotomontaje terminado" draggable="false">
      <span class="rotulo-img r-antes">Original</span><span class="rotulo-img r-despues">Editada</span>
      <span class="divisor"></span>
      <span class="perilla" role="slider" tabindex="0" aria-label="Deslizar para comparar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 6l-6 6 6 6M15 6l6 6-6 6"/></svg>
      </span>
    </div>`;
  document.querySelectorAll('[data-comparador]').forEach(box => {
    const c = P.find(x => x.id === box.dataset.comparador);
    if (!c || !c.comparar) return;
    box.innerHTML = htmlComparador(c.comparar);
    comparador(box.firstElementChild);
  });

  /* ---------- Tarjetas de categoría (portada) ---------- */
  const lista = document.querySelector('.categorias');
  if (lista) {
    lista.innerHTML = P.map(c => c.fotos.length ? `
      <a class="tarjeta aparece" href="categoria.html?c=${c.id}">
        <div class="marco visor"><div class="recorte"><img src="${foto(c.portada || c.fotos[0].f)}" alt="" loading="lazy"></div></div>
        <div class="info"><h3>${c.titulo}</h3><span class="cuenta">${c.fotos.length} ${c.fotos.length === 1 ? 'foto' : 'fotos'}</span></div>
      </a>` : `
      <div class="tarjeta pronto aparece">
        <div class="marco visor"><div class="recorte"><span>Próximamente</span></div></div>
        <div class="info"><h3>${c.titulo}</h3><span class="cuenta">En proceso</span></div>
      </div>`).join('');
  }

  /* ---------- Página de categoría ---------- */
  if (document.body.dataset.pagina === 'categoria') {
    const i = Math.max(0, P.findIndex(x => x.id === catActual));
    const c = P[i];
    document.title = `${c.titulo} · Víctor Silva`;
    const port = c.portada || (c.fotos[0] && c.fotos[0].f);
    const portada = document.querySelector('.portada-cat');
    portada.innerHTML = `
      ${port ? `<div class="fondo" style="background-image:url('${foto(port)}')"></div>` : ''}
      <div class="contenedor">
        <div>
          <span class="etiqueta">Portafolio · ${String(i + 1).padStart(2, '0')}</span>
          <h1>${c.titulo}</h1>
          <p>${c.bajada}</p>
          ${c.fotos.length ? `<a class="boton" href="#galeria">Ver galería ${flecha}</a>` : ''}
        </div>
        ${port ? `<div class="foto visor"><img src="${foto(port)}" alt="${c.titulo}"></div>` : ''}
      </div>`;
    const gal = document.querySelector('#galeria .contenedor');
    let html = '';
    if (c.comparar) html += `
      <div class="bloque-comparar aparece">
        <div>
          <span class="etiqueta">Antes y después</span>
          <h2 class="titulo-seccion">${c.comparar.titulo}</h2>
          <p class="texto-suave">Arrastra la línea para comparar la foto original con el fotomontaje terminado.</p>
        </div>
        <div data-comp></div>
      </div>`;
    const figura = (f, k) => `
          <figure class="aparece"><button class="visor" data-k="${k}" aria-label="Ver foto ${k + 1} en grande"><img src="${foto(f.f)}" alt="${f.t || c.titulo + ' ' + (k + 1)}" loading="lazy"></button>${f.t ? `<figcaption>${f.t}</figcaption>` : ''}</figure>`;
    // Fotos "juntas": cada par va en una fila, una al lado de la otra, antes de la galería
    const pares = {};
    c.fotos.forEach((f, k) => { if (f.par !== undefined) (pares[f.par] = pares[f.par] || []).push(figura(f, k)); });
    html += Object.values(pares).map(p => `<div class="juntas">${p.join('')}</div>`).join('');
    html += c.fotos.length
      ? `<div class="galeria">${c.fotos.map((f, k) => f.par === undefined ? figura(f, k) : '').join('')}</div>`
      : `<p class="vacio">Esta categoría está en proceso. Pronto habrá fotos aquí.</p>`;
    gal.innerHTML = html;
    const comp = gal.querySelector('[data-comp]');
    if (comp) { comp.innerHTML = htmlComparador(c.comparar); comparador(comp.firstElementChild); }
    gal.querySelectorAll('[data-k]').forEach(b => b.addEventListener('click', () => abrirVisor(c.fotos.map(f => ({ f: f.f, t: f.t || c.titulo })), +b.dataset.k)));

    const ant = P[(i - 1 + P.length) % P.length], sig = P[(i + 1) % P.length];
    document.querySelector('.navegacion-cat').innerHTML = `
      <a href="categoria.html?c=${ant.id}"><small>← Anterior</small><b>${ant.titulo}</b></a>
      <a href="categoria.html?c=${sig.id}"><small>Siguiente →</small><b>${sig.titulo}</b></a>`;
  }

  /* ---------- Visor de fotos (lightbox) ---------- */
  let vis, fotosV = [], kV = 0, ultimoFoco = null;
  function crearVisor() {
    vis = document.createElement('div');
    vis.className = 'visor-fotos'; vis.setAttribute('role', 'dialog'); vis.setAttribute('aria-modal', 'true'); vis.setAttribute('aria-label', 'Foto ampliada');
    vis.innerHTML = `
      <div class="barra"><span class="contador"></span><button class="cerrar">Cerrar ✕</button></div>
      <div class="centro">
        <img alt="">
        <button class="flecha ant" aria-label="Foto anterior"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M15 5l-7 7 7 7"/></svg></button>
        <button class="flecha sig" aria-label="Foto siguiente"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M9 5l7 7-7 7"/></svg></button>
      </div>
      <div class="titulo"></div>`;
    document.body.appendChild(vis);
    vis.querySelector('.cerrar').onclick = cerrarVisor;
    vis.querySelector('.ant').onclick = () => mover(-1);
    vis.querySelector('.sig').onclick = () => mover(1);
    vis.querySelector('.centro').addEventListener('click', (e) => { if (e.target.classList.contains('centro')) cerrarVisor(); });
    let x0 = null;
    vis.addEventListener('touchstart', (e) => { x0 = e.touches[0].clientX; }, { passive: true });
    vis.addEventListener('touchend', (e) => { if (x0 === null) return; const d = e.changedTouches[0].clientX - x0; if (Math.abs(d) > 50) mover(d < 0 ? 1 : -1); x0 = null; });
    document.addEventListener('keydown', (e) => {
      if (!vis.classList.contains('abierto')) return;
      if (e.key === 'Escape') cerrarVisor();
      if (e.key === 'ArrowLeft') mover(-1);
      if (e.key === 'ArrowRight') mover(1);
    });
  }
  function pintar() {
    const f = fotosV[kV];
    const img = vis.querySelector('.centro img');
    img.src = foto(f.f); img.alt = f.t;
    vis.querySelector('.titulo').textContent = f.t;
    vis.querySelector('.contador').textContent = `${String(kV + 1).padStart(2, '0')} / ${String(fotosV.length).padStart(2, '0')}`;
    vis.querySelectorAll('.flecha').forEach(b => b.hidden = fotosV.length < 2);
  }
  function abrirVisor(lista, k) {
    if (!vis) crearVisor();
    fotosV = lista; kV = k; ultimoFoco = document.activeElement; pintar();
    vis.classList.add('abierto'); document.body.style.overflow = 'hidden';
    vis.querySelector('.cerrar').focus();
  }
  function cerrarVisor() { vis.classList.remove('abierto'); document.body.style.overflow = ''; if (ultimoFoco) ultimoFoco.focus(); }
  function mover(d) { kV = (kV + d + fotosV.length) % fotosV.length; pintar(); }

  document.querySelectorAll('.aparece').forEach(observar);
  const anio = document.querySelector('[data-anio]'); if (anio) anio.textContent = new Date().getFullYear();
})();
