/* Página "Ajustar fotos": la interfaz. El ajuste lo hace js/ajustar-motor.js en otro hilo
   (ajuste_combinado.py corriendo dentro del navegador). Las fotos no salen del computador. */
(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const ACEPTA = /\.(jpe?g|png|tiff?)$/i;
  const JSZIP = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';

  const zona = $('.zona'), elegir = $('#elegir'), lista = $('.lista-fotos');
  const motorEl = $('.motor'), motorBarra = $('.motor-barra i'), motorTexto = $('.motor-texto');
  const acciones = $('.acciones'), resumen = $('.resumen');
  const bDetener = $('[data-detener]'), bSeguir = $('[data-seguir]'), bZip = $('[data-zip]'), bLimpiar = $('[data-limpiar]');
  const panel = $('.panel-comparar'), comp = $('.panel-comparar .comparador');

  const fotos = [];          // {clave, archivo, nombre, mp, estado, inicio, blob, salida, segundos, info, el, urlDespues}
  let motor = null, motorListo = false, enEspera = [], contador = 0, midiendo = false;
  let elegida = null, urlAntes = null;

  /* ---------- Elegir o soltar fotos ---------- */
  $('[data-elegir]').addEventListener('click', (e) => { e.stopPropagation(); elegir.click(); });
  zona.addEventListener('click', (e) => { if (e.target !== elegir) elegir.click(); });
  elegir.addEventListener('change', () => { agregar(elegir.files); elegir.value = ''; });
  let arrastres = 0;
  addEventListener('dragenter', (e) => { if (tieneArchivos(e)) { arrastres++; zona.classList.add('encima'); } });
  addEventListener('dragleave', () => { if (--arrastres <= 0) { arrastres = 0; zona.classList.remove('encima'); } });
  addEventListener('dragover', (e) => { if (tieneArchivos(e)) e.preventDefault(); });
  addEventListener('drop', (e) => {
    if (!tieneArchivos(e)) return;
    e.preventDefault(); arrastres = 0; zona.classList.remove('encima');
    agregar(e.dataTransfer.files);
  });
  function tieneArchivos(e) { return e.dataTransfer && [...e.dataTransfer.types].includes('Files'); }

  function megapixelesElegidos() { return +document.querySelector('input[name="tam"]:checked').value; }

  function agregar(archivos) {
    const nuevas = [], rechazadas = [];
    for (const a of archivos) {
      if (!ACEPTA.test(a.name)) { rechazadas.push(a.name); continue; }
      const f = { clave: 'f' + (++contador), archivo: a, nombre: a.name.replace(/[\\/:*?"<>|]/g, '_'), mp: 0, estado: 'espera' };
      f.el = tarjeta(f);
      lista.appendChild(f.el);
      miniatura(a).then(({ url, mp }) => { f.mp = mp; f.el.querySelector('.mini img').src = url; f.urlMini = url; })
        .catch(() => { /* sin miniatura (ej. TIFF): igual se ajusta */ });
      fotos.push(f); nuevas.push(f);
    }
    if (rechazadas.length) {
      alert('Estas no se pueden ajustar (solo JPG, PNG o TIFF):\n' + rechazadas.join('\n') +
        (rechazadas.some((n) => /\.hei[cf]$/i.test(n)) ? '\n\nLas fotos HEIC del iPhone hay que pasarlas antes a JPG.' : ''));
    }
    if (nuevas.length) { acciones.hidden = false; enviar(nuevas); }
    actualizar();
  }

  /* ---------- Motor ---------- */
  function crearMotor() {
    motorListo = false;
    motor = new Worker('js/ajustar-motor.js?v=1', { type: 'module' });
    motor.onmessage = (e) => recibir(e.data);
    motor.onerror = (e) => {
      e.preventDefault();
      if (!motorListo) return falla(e.message || 'error al cargar');
      const actual = fotos.find((f) => f.estado === 'ajustando');
      roto(actual ? actual.clave : null, e.message);
    };
    motorEl.hidden = false; motorEl.classList.remove('falla');
    cargando('Preparando', 0.03);
  }

  function enviar(lote) {
    lote.forEach((f) => { f.estado = 'espera'; pintar(f); });
    if (!motor) crearMotor();
    if (!motorListo) { enEspera.push(...lote); return; }
    const megapixeles = megapixelesElegidos();
    lote.forEach((f) => { f.tope = megapixeles; });
    Promise.all(lote.map((f) => f.archivo.arrayBuffer())).then((datos) => {
      if (!motor) return;
      motor.postMessage({
        tipo: 'lote', megapixeles,
        fotos: lote.map((f, i) => ({ clave: f.clave, nombre: f.nombre, datos: datos[i] })),
      }, datos);
    }).catch(() => lote.forEach((f) => { f.estado = 'error'; f.info = 'no se pudo leer el archivo'; pintar(f); }));
  }

  function recibir(m) {
    const f = m.clave && fotos.find((x) => x.clave === m.clave);
    switch (m.tipo) {
      case 'carga': cargando(m.paso, m.avance); break;
      case 'listo':
        motorListo = true;
        cargando('Listo', 1);
        setTimeout(() => { if (motorListo) motorEl.hidden = true; }, 900);
        if (m.sinDetector) console.warn('Ajuste sin detector de caras:', m.sinDetector);
        if (enEspera.length) { const l = enEspera; enEspera = []; enviar(l); }
        break;
      case 'falla': falla(m.texto); break;
      case 'midiendo': midiendo = true; actualizar(); break;
      case 'serie': midiendo = false; actualizar(); break;
      case 'empieza':
        if (!f) break;
        f.estado = 'ajustando'; f.inicio = performance.now(); pintar(f); actualizar();
        break;
      case 'foto':
        if (!f) break;
        f.segundos = m.segundos; f.info = m.info;
        if (m.estado === 'lista') {
          f.blob = new Blob([m.datos], { type: 'image/jpeg' });
          f.salida = m.ruta.split('/').pop();
          f.estado = 'lista';
          f.urlDespues = URL.createObjectURL(f.blob);
          miniatura(f.blob).then(({ url }) => { if (f.urlMini) URL.revokeObjectURL(f.urlMini); f.urlMini = url; f.el.querySelector('.mini img').src = url; }).catch(() => {});
          if (!elegida) mostrar(f);
        } else {
          f.estado = m.estado === 'ya' ? 'ya' : 'error';
        }
        pintar(f); actualizar();
        break;
      case 'roto': roto(m.clave, m.texto); break;
    }
  }

  function cargando(paso, avance) {
    motorBarra.style.width = Math.round(avance * 100) + '%';
    motorTexto.textContent = avance >= 1 ? 'Listo para ajustar' :
      `${paso}… (solo la primera vez descarga unos 20 MB; después queda guardado en tu navegador)`;
  }

  function falla(texto) {
    if (motor) motor.terminate();
    motor = null; motorListo = false;
    motorEl.hidden = false; motorEl.classList.add('falla');
    motorTexto.textContent = 'No se pudo preparar el ajuste. Revisa tu conexión a internet y vuelve a intentarlo.';
    console.error('Ajuste:', texto);
    fotos.filter((f) => f.estado === 'espera' || f.estado === 'ajustando').forEach((f) => { f.estado = 'detenida'; pintar(f); });
    enEspera = [];
    actualizar();
  }

  // Python se cayó con una foto (casi siempre por memoria): esa queda con error y las que faltaban
  // siguen en un motor nuevo
  function roto(clave, texto) {
    console.error('Ajuste:', texto);
    if (motor) motor.terminate();
    motor = null; motorListo = false;
    const f = clave && fotos.find((x) => x.clave === clave);
    if (f) {
      f.estado = 'error';
      f.info = 'al navegador no le alcanzó la memoria' + (megapixelesElegidos() ? '' : ': prueba con el modo rápido');
      pintar(f);
    }
    const faltan = fotos.filter((x) => x.estado === 'espera' || x.estado === 'ajustando');
    if (faltan.length) enviar(faltan); else actualizar();
  }

  /* ---------- Detener, seguir, descargar, limpiar ---------- */
  bDetener.addEventListener('click', () => {
    if (motor) motor.terminate();
    motor = null; motorListo = false; enEspera = []; motorEl.hidden = true;
    fotos.filter((f) => f.estado === 'espera' || f.estado === 'ajustando').forEach((f) => { f.estado = 'detenida'; pintar(f); });
    actualizar();
  });
  bSeguir.addEventListener('click', () => enviar(fotos.filter((f) => f.estado === 'detenida')));

  bZip.addEventListener('click', async () => {
    const listas = fotos.filter((f) => f.estado === 'lista');
    if (listas.length === 1) return bajar(listas[0].blob, listas[0].salida);
    bZip.disabled = true; const antes = bZip.textContent; bZip.textContent = 'Preparando…';
    try {
      await cargarScript(JSZIP);
      const zip = new JSZip(), usados = new Set();
      for (const f of listas) {
        let n = f.salida, k = 2;
        while (usados.has(n.toLowerCase())) n = f.salida.replace(/(\.\w+)$/, ` (${k++})$1`);
        usados.add(n.toLowerCase());
        zip.file(n, f.blob);
      }
      bajar(await zip.generateAsync({ type: 'blob', compression: 'STORE' }), 'fotos ajustadas.zip');
    } catch (e) {
      alert('No se pudo armar el archivo .zip. Descárgalas una por una.');
    }
    bZip.textContent = antes; actualizar();
  });

  bLimpiar.addEventListener('click', () => {
    const pendientes = fotos.some((f) => f.estado === 'espera' || f.estado === 'ajustando');
    const sinBajar = fotos.some((f) => f.estado === 'lista' && !f.bajada);
    if ((pendientes || sinBajar) && !confirm('¿Quitar todas las fotos de la página? Las ajustadas que no descargaste se pierden.')) return;
    if (pendientes) { if (motor) motor.terminate(); motor = null; motorListo = false; enEspera = []; motorEl.hidden = true; }
    cerrarPanel();
    fotos.forEach((f) => { if (f.urlMini) URL.revokeObjectURL(f.urlMini); if (f.urlDespues) URL.revokeObjectURL(f.urlDespues); });
    fotos.length = 0; lista.innerHTML = ''; acciones.hidden = true;
  });

  function bajar(blob, nombre) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = nombre;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    fotos.forEach((f) => { if (f.blob === blob || nombre.endsWith('.zip')) f.bajada = true; });
  }

  function cargarScript(src) {
    return new Promise((ok, no) => {
      if (window.JSZip) return ok();
      const s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = no;
      document.head.appendChild(s);
    });
  }

  addEventListener('beforeunload', (e) => {
    if (fotos.some((f) => f.estado === 'espera' || f.estado === 'ajustando' || (f.estado === 'lista' && !f.bajada))) {
      e.preventDefault(); e.returnValue = '';
    }
  });

  /* ---------- Tarjetas y resumen ---------- */
  const TEXTO = { espera: 'En espera', ajustando: 'Ajustando', lista: 'Lista', ya: 'Ya estaba ajustada con este programa', error: 'No se pudo ajustar', detenida: 'Detenida' };

  function tarjeta(f) {
    const li = document.createElement('li');
    li.className = 'foto-aj';
    li.innerHTML = `
      <button type="button" class="mini visor" disabled><img alt=""><span class="sello">Ajustando</span></button>
      <div class="pie-foto"><span class="nombre"></span><span class="estado"></span><a class="bajar" href="#" hidden>Descargar</a></div>`;
    li.querySelector('.nombre').textContent = f.archivo.name;
    li.querySelector('.nombre').title = f.archivo.name;
    li.querySelector('.mini img').alt = f.archivo.name;
    li.querySelector('.mini').addEventListener('click', () => { if (f.estado === 'lista') mostrar(f); });
    li.querySelector('.bajar').addEventListener('click', (e) => { e.preventDefault(); bajar(f.blob, f.salida); });
    return li;
  }

  function pintar(f) {
    const el = f.el;
    el.dataset.estado = f.estado;
    const hecha = f.estado === 'lista';
    el.querySelector('.mini').disabled = !hecha;
    el.querySelector('.mini').setAttribute('aria-label', hecha ? `Comparar antes y después de ${f.archivo.name}` : f.archivo.name);
    el.querySelector('.sello').textContent = hecha ? 'Comparar' : 'Ajustando';
    el.querySelector('.bajar').hidden = !hecha;
    let t = TEXTO[f.estado];
    if (f.estado === 'ajustando') t += ' · ' + reloj((performance.now() - f.inicio) / 1000);
    if (hecha) t += ' · ' + reloj(f.segundos);
    if (f.estado === 'error' && f.info) t += ` (${f.info})`;
    el.querySelector('.estado').textContent = t;
  }

  function reloj(s) {
    s = Math.max(0, Math.round(s));
    return s < 60 ? `${s} s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} min`;
  }

  // Tiempo que falta: con lo que tardaron las fotos ya hechas en ESTE computador (segundos por megapíxel)
  function quedan() {
    const efectivos = (f) => {
      const mp = f.mp || 12, tope = f.tope === undefined ? megapixelesElegidos() : f.tope;
      return tope ? Math.min(mp, tope) : mp;
    };
    const hechas = fotos.filter((f) => f.estado === 'lista' && f.mp && f.segundos);
    if (!hechas.length) return null;
    const ritmo = hechas.reduce((s, f) => s + f.segundos / efectivos(f), 0) / hechas.length;
    let s = 0;
    for (const f of fotos) {
      const mp = efectivos(f);
      if (f.estado === 'espera') s += mp * ritmo;
      if (f.estado === 'ajustando') s += Math.max(5, mp * ritmo - (performance.now() - f.inicio) / 1000);
    }
    return s;
  }

  function actualizar() {
    const n = (e) => fotos.filter((f) => f.estado === e).length;
    const listas = n('lista'), faltan = n('espera') + n('ajustando'), detenidas = n('detenida');
    const otras = n('ya') + n('error');
    let t;
    if (!fotos.length) t = '';
    else if (faltan && midiendo) t = `Midiendo la luz de las ${faltan} fotos para que las de una misma serie queden parejas…`;
    else if (faltan) {
      const s = quedan();
      t = `<b>${listas} de ${listas + faltan}</b> listas` + (s ? ` · quedan unos ${reloj(s)}` : ' · calculando el tiempo con la primera foto…');
    } else t = `<b>${listas} ${listas === 1 ? 'foto lista' : 'fotos listas'}</b>` + (listas ? '. Toca una para comparar el antes y el después.' : '');
    if (detenidas) t += ` · ${detenidas} detenida${detenidas > 1 ? 's' : ''}`;
    if (otras && !faltan) t += ` · ${otras} sin ajustar`;
    resumen.innerHTML = t;
    bDetener.hidden = !faltan;
    bSeguir.hidden = !detenidas || !!faltan;
    bZip.disabled = !listas;
    bZip.textContent = listas > 1 ? `Descargar todas (${listas})` : 'Descargar';
  }
  setInterval(() => {
    const f = fotos.find((x) => x.estado === 'ajustando');
    if (f) { pintar(f); actualizar(); }
  }, 1000);

  /* ---------- Miniaturas ---------- */
  function miniatura(blob) {
    return new Promise((ok, no) => {
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => {
        const lado = 520, k = Math.min(1, lado / Math.min(img.naturalWidth, img.naturalHeight));
        const c = document.createElement('canvas');
        c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        const mp = img.naturalWidth * img.naturalHeight / 1e6;
        URL.revokeObjectURL(url);
        c.toBlob((b) => b ? ok({ url: URL.createObjectURL(b), mp }) : no(), 'image/jpeg', 0.85);
      };
      img.onerror = () => { URL.revokeObjectURL(url); no(); };
      img.src = url;
    });
  }

  /* ---------- Antes y después ---------- */
  function mostrar(f) {
    if (elegida) elegida.el.classList.remove('elegida');
    elegida = f; f.el.classList.add('elegida');
    if (urlAntes) URL.revokeObjectURL(urlAntes);
    urlAntes = URL.createObjectURL(f.archivo);
    const antes = $('.antes', comp), despues = $('.despues', comp);
    comp.classList.remove('solo-despues');
    antes.onerror = () => comp.classList.add('solo-despues');   // ej. TIFF: el navegador no lo muestra
    antes.src = urlAntes;
    despues.onload = () => comp.style.setProperty('--r', despues.naturalWidth / despues.naturalHeight);
    despues.src = f.urlDespues;
    $('.panel-nombre').textContent = f.salida;
    const bajarP = $('[data-bajar]');
    bajarP.href = f.urlDespues; bajarP.download = f.salida;
    bajarP.onclick = () => { f.bajada = true; };
    $('.panel-info').textContent = `Ajustada en ${reloj(f.segundos)}` + (f.info && f.info.includes('reducido') ? ' · se le quitó el grano' : '') +
      (f.info && f.info.includes('serie') ? ' · balance de blancos parejo con su serie' : '');
    const abrir = panel.hidden;
    panel.hidden = false;
    poner(abrir ? 100 : 50);
    if (abrir) { panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); animar(); }
  }
  function cerrarPanel() {
    panel.hidden = true;
    if (elegida) elegida.el.classList.remove('elegida');
    elegida = null;
  }
  $('[data-cerrar]').addEventListener('click', cerrarPanel);

  const perilla = $('.perilla', comp), rA = $('.r-antes', comp), rD = $('.r-despues', comp);
  let p = 50, arrastrando = false, toque = null;
  function poner(v) {
    p = Math.max(0, Math.min(100, v));
    comp.style.setProperty('--p', p + '%');
    rA.style.opacity = p > 12 ? 1 : 0; rD.style.opacity = p < 88 ? 1 : 0;
    perilla.setAttribute('aria-valuenow', Math.round(100 - p));
  }
  function animar() {   // al abrir: la línea pasa de la original hacia la mitad, para que se note el cambio
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return poner(50);
    const t0 = performance.now();
    const paso = (t) => {
      if (arrastrando) return;
      const k = Math.min(1, (t - t0) / 1100), e = 1 - Math.pow(1 - k, 3);
      poner(100 - 50 * e);
      if (k < 1) requestAnimationFrame(paso);
    };
    requestAnimationFrame(paso);
  }
  const desdeX = (x) => { const r = comp.getBoundingClientRect(); poner((x - r.left) / r.width * 100); };
  const empezar = (e) => { arrastrando = true; toque = null; try { comp.setPointerCapture(e.pointerId); } catch (_) {} desdeX(e.clientX); };
  comp.addEventListener('pointerdown', (e) => { if (e.pointerType === 'touch') toque = { x: e.clientX, y: e.clientY }; else empezar(e); });
  comp.addEventListener('pointermove', (e) => {
    if (arrastrando) return desdeX(e.clientX);
    if (!toque) return;
    const dx = Math.abs(e.clientX - toque.x), dy = Math.abs(e.clientY - toque.y);
    if (dx > 8 && dx > dy) empezar(e); else if (dy > 8) toque = null;
  });
  comp.addEventListener('pointerup', (e) => { if (toque) desdeX(e.clientX); toque = null; arrastrando = false; });
  comp.addEventListener('pointercancel', () => { toque = null; arrastrando = false; });
  perilla.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); poner(p + (e.key === 'ArrowLeft' ? -5 : 5)); }
  });
})();
