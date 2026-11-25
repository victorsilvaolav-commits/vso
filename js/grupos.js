/* Fotos "combinadas": dentro de una categoría, las fotos parecidas se juntan en un montón.
   Se ve una sola foto (la primera de la lista) con las otras asomándose detrás; al tocarla se abren todas en grande.

   - GRUPOS[categoría] = lista de montones. Cada foto se escribe con su nombre dentro de fotos/<categoría>/, sin .jpg.
     La primera foto de cada lista es la que se ve arriba del montón.
   - Las fotos que no están en ningún montón siguen saliendo sueltas, como antes.
   - EXTRA[categoría] = fotos nuevas que se suman a una categoría sin tocar js/datos.js (que se genera con un script). */
window.EXTRA = {
  'estrellas-y-luna': ['de-cerca/cielo-completo', 'IMG_4466-3']
};

window.GRUPOS = {
  'estrellas-y-luna': [
    { titulo: 'Las estrellas', fotos: ['18105486979207280', 'de-cerca/cielo-completo', '18175778587002262', '18091365019527219', '17908517093438538', '17932374104057846', '17881453529351249', '17900400832765119'] },
    { titulo: 'Fases de la luna', fotos: ['18040015615284034', '17939011180673960', '18057805906742002', '17919423989058910', 'IMG_4466-3', '17867706734266398','17997798665226784', '18142533457114535'] },
    { titulo: 'La luna en el paisaje', fotos: ['18181964785071664', '17961303803038928', '17967306703404131', '18197498002038032'] },
    { titulo: 'Eclipses', fotos: ['17998935712445946', '18018333131563531'] }
  ],
  'animales': [
    { titulo: 'Abejas', fotos: ['18092450149758296', '17900119354671143', '18120675064194060', '18137999857088075', '18181301443049705'] },
    { titulo: 'Gatos', fotos: ['17906070361861797', '18043956958975744', '18230718466027203', '18173219533184315'] },
    { titulo: 'Arañas', fotos: ['17858092010621560', '18240560320066581', '17888278853428711'] }
  ],
  // Un montón por cada matrimonio
  'matrimonios': [
    { titulo: 'Matrimonio en el jardín', fotos: ['36-matrimonio-novios-bailando', '34-matrimonio-brindis', '35-matrimonio-baile-pista', '37-matrimonio-grupo-jardin'] },
    { titulo: 'Matrimonio de noche', fotos: ['29-matrimonio-foto-grupal', '31-matrimonio-libreta-pareja', '28-matrimonio-fiesta-novio'] },
    { titulo: 'Ceremonia bajo el arco', fotos: ['32-matrimonio-altar-jardin', '33-matrimonio-libreta-registro'] },
    { titulo: 'Ceremonia en el campo', fotos: ['30-matrimonio-ceremonia-campo'] }
  ]
};
