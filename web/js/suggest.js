/* Recommended values for the input panels.

   Every suggestion is a real-world reference (NASA / ESA facilities,
   flown engines, flown spacecraft, textbook standards). Clicking one
   fills in the fields and shows where the numbers come from. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);

  /* Geodetic (WGS-84) -> Earth-fixed (ECEF) coordinates [km]. */
  function ecef(latDeg, lonDeg, hMeters) {
    const a = 6378.137, f = 1 / 298.257223563, e2 = f * (2 - f);
    const lat = latDeg * LS.DEG, lon = lonDeg * LS.DEG, h = hMeters / 1000;
    const N = a / Math.sqrt(1 - e2 * Math.sin(lat) ** 2);
    return [(N + h) * Math.cos(lat) * Math.cos(lon), (N + h) * Math.cos(lat) * Math.sin(lon),
      (N * (1 - e2) + h) * Math.sin(lat)];
  }

  /* Insert a row of suggestion chips before/after an element.
     items: [{label, note, apply()}] */
  function chips(anchor, where, title, items) {
    const box = document.createElement('div');
    box.className = 'suggest';
    box.innerHTML = `<div class="sg-title">${title}</div><div class="chips"></div><p class="sg-note" hidden></p>`;
    const row = box.querySelector('.chips'), note = box.querySelector('.sg-note');
    items.forEach((it) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = it.label;
      b.title = it.note || '';
      b.addEventListener('click', () => {
        row.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
        it.apply();
        note.innerHTML = it.note || '';
        note.hidden = !it.note;
      });
      row.appendChild(b);
    });
    anchor.insertAdjacentElement(where, box);
    return box;
  }
  const set = (vals) => Object.entries(vals).forEach(([id, v]) => { $(id).value = v; });
  const fmtKm = (v) => v.toFixed(3);

  /* ---------------- Orbit tab ---------------- */

  const STATIONS = [
    { label: 'Assignment station', xyz: [1344.143, 6068.601, 1429.311],
      note: 'The station given in the assignment (about 13° N, 77.5° E, spherical Earth).' },
    { label: 'Goldstone DSS-14 (NASA DSN)', xyz: [-2353.621251, -4641.341542, 3677.052370],
      note: 'NASA Deep Space Network, 70 m antenna DSS-14, Goldstone, California — 35.426° N, 116.890° W, 1,002 m. Earth-fixed coordinates as published by JPL (accurate to about 15 cm).' },
    { label: 'Madrid DSS-63 (NASA DSN)', xyz: [4849.092647, -360.180569, 4115.109113],
      note: 'NASA Deep Space Network, 70 m antenna DSS-63, Robledo de Chavela, Spain — 40.431° N, 4.248° W, 866 m. Coordinates as published by JPL.' },
    { label: 'Canberra DSS-43 (NASA DSN)', xyz: [-4460.894585, 2682.361554, -3674.748580],
      note: 'NASA Deep Space Network, 70 m antenna DSS-43, Tidbinbilla, Australia — 35.402° S, 148.981° E, 690 m. Coordinates as published by JPL. The three DSN complexes are about 120° apart in longitude, so a deep-space probe is always in view of one of them.' },
    { label: 'Kennedy Space Center', geo: [28.5729, -80.6490, 3],
      note: 'NASA Kennedy Space Center, Florida — 28.57° N, 80.65° W. Launch site of Apollo, the Shuttle and Artemis.' },
    { label: 'Kourou (ESA)', geo: [5.2515, -52.8047, 14],
      note: 'ESA Kourou station, French Guiana — 5.25° N, 52.80° W. Close to the equator, ideal for launches to geostationary orbit.' },
    { label: 'Svalbard (KSAT)', geo: [78.2297, 15.4078, 500],
      note: 'SvalSat, Norway — 78.23° N, 15.41° E. So far north that it sees every pass of polar-orbiting satellites.' },
  ];
  chips($('st-more'), 'beforebegin', 'Real ground stations', STATIONS.map((s) => ({
    label: s.label,
    note: s.note + (s.geo ? ' Converted to Earth-fixed coordinates with the WGS-84 ellipsoid (approximate site position).' : '') +
      ' <b>Note:</b> the observations below were measured from the assignment station; with another station they describe a different satellite.',
    apply: () => {
      const p = s.xyz || ecef(...s.geo);
      set({ 'st-x': fmtKm(p[0]), 'st-y': fmtKm(p[1]), 'st-z': fmtKm(p[2]) });
    },
  })));

  const obsHelp = document.createElement('p');
  obsHelp.className = 'hint';
  obsHelp.innerHTML = '<b>Reading the observations:</b> azimuth is measured clockwise from north (90° = east); elevation is the ' +
    'angle above the horizon (90° = straight overhead); range is the straight-line distance. Typical ranges: low Earth orbit ' +
    '500–2,500 km, GPS ≈ 20,000–25,000 km, geostationary ≈ 36,000–41,000 km.';
  $('o2-rng').closest('.grid3').insertAdjacentElement('afterend', obsHelp);

  /* ---------------- Maneuver tab ---------------- */

  const ORBITS = [
    ['LEO 300 km', 300, 'A typical low parking orbit, where rockets usually release their payload.'],
    ['ISS 420 km', 420, 'The International Space Station flies at about 400–420 km.'],
    ['Sun-sync. 700 km', 700, 'Typical altitude of Earth-observation satellites (e.g. Landsat 9 at 705 km).'],
    ['GPS 20,200 km', 20200, 'GPS satellites orbit at 20,200 km: two revolutions per day.'],
    ['GEO 35,786 km', 35786, 'Geostationary orbit: one revolution per sidereal day, so the satellite hangs over one spot on the equator.'],
    ['Moon distance', 378000, 'The Moon is on average 384,400 km from Earth\'s centre, which is about 378,000 km altitude (this planner ignores the Moon\'s own gravity).'],
  ];
  chips($('mv-alt1').closest('.grid2'), 'beforebegin', 'Start from', ORBITS.map(([l, v, n]) => ({
    label: l, note: n, apply: () => set({ 'mv-alt1': v }) })));
  chips($('mv-alt1').closest('.grid2'), 'beforebegin', 'Go to', ORBITS.map(([l, v, n]) => ({
    label: l, note: n, apply: () => set({ 'mv-alt2': v }) })));
  chips($('mv-altb-l'), 'beforebegin', 'Launch site → starting inclination', [
    ['Cape Canaveral 28.5°', 28.5, 'Launching due east puts a rocket in an orbit inclined by the site\'s latitude: 28.5° from Florida.'],
    ['Kourou 5.2°', 5.2, 'ESA\'s Kourou is near the equator: almost no plane change needed to reach geostationary orbit.'],
    ['Baikonur 51.6°', 51.6, 'Launches from Baikonur go to 51.6° (the ISS inclination) for range-safety reasons.'],
    ['Vandenberg 97.8°', 97.8, 'Polar and Sun-synchronous orbits are launched southward from Vandenberg, California.'],
  ].map(([l, v, n]) => ({ label: l, note: n, apply: () => set({ 'mv-i1': v }) })));

  chips($('mv-mass').closest('.grid2'), 'afterend', 'Engine (sets Isp)', [
    ['Hydrazine thruster', 230, 'Monopropellant hydrazine (e.g. Aerojet MR-106): Isp ≈ 230 s. Simple and reliable; used for small corrections.'],
    ['Bipropellant R-4D', 312, 'MMH/NTO engine used on the Apollo service module and many satellites: Isp ≈ 312 s.'],
    ['Merlin Vacuum', 348, 'SpaceX Falcon 9 upper stage (kerosene/oxygen): Isp ≈ 348 s.'],
    ['RL10 (Centaur)', 465, 'Hydrogen/oxygen upper stage that launched Voyager, Cassini and New Horizons: Isp ≈ 465 s.'],
    ['Ion engine NSTAR', 3100, 'NASA Dawn / Deep Space 1 ion engine: Isp ≈ 3,100 s. Its thrust is tiny, so real burns last months; this planner treats burns as instantaneous, so the propellant figure is an ideal lower bound.'],
  ].map(([l, v, n]) => ({ label: l, note: n, apply: () => set({ 'mv-isp': v }) })));
  chips($('mv-mass').closest('.grid2'), 'afterend', 'Spacecraft (sets mass)', [
    ['CubeSat 6U', 12, 'A 6U CubeSat: about 10 × 20 × 30 cm and up to ≈12 kg.'],
    ['Small satellite', 150, 'A typical small Earth-observation satellite: ≈100–200 kg.'],
    ['GPS III', 3880, 'A GPS III navigation satellite: ≈3,880 kg at launch.'],
    ['GEO comsat', 6000, 'A large geostationary communications satellite: ≈5,000–7,000 kg at launch.'],
  ].map(([l, v, n]) => ({ label: l, note: n, apply: () => set({ 'mv-mass': v }) })));

  /* ---------------- Perturb tab ---------------- */

  chips($('pt-more'), 'beforebegin', 'Spacecraft (sets drag data)', [
    ['ISS', [2.2, 1600, 420000], 'International Space Station: ≈420,000 kg; ≈1,600 m² average cross-section with its solar arrays (an estimate: the real value changes with array orientation).'],
    ['Hubble', [2.2, 60, 11110], 'Hubble Space Telescope: 11,110 kg at launch; ≈60 m² average cross-section, an estimate (13.2 m long, 4.2 m wide, plus solar arrays).'],
    ['Starlink v1.5', [2.2, 10, 306], 'SpaceX Starlink v1.5: ≈306 kg; the ≈10 m² cross-section is an estimate for flying edge-on to reduce drag.'],
    ['CubeSat 3U', [2.2, 0.03, 4], 'A 3U CubeSat: ≈4 kg, 10 × 10 × 30 cm, so ≈0.03 m² in its worst orientation.'],
  ].map(([l, [cd, a, m], n]) => ({
    label: l,
    note: n + ' Cd = 2.2 is the standard drag coefficient for satellites (Vallado).',
    apply: () => { set({ 'pt-cd': cd, 'pt-area': a, 'pt-mass': m }); if (!$('pt-atm').value) $('pt-atm').value = 'msis'; },
  })));

  /* ---------------- Mission tab ---------------- */

  const suggestBox = document.createElement('div');
  suggestBox.className = 'suggest';
  suggestBox.innerHTML = `<div class="sg-title">Not sure which dates?</div>
    <button type="button" class="ghost wide" id="m-suggest">Suggest the next launch window</button>
    <p class="sg-note" id="m-suggest-note" hidden></p>`;
  $('m-dd').closest('.grid2').insertAdjacentElement('afterend', suggestBox);
  $('m-suggest').addEventListener('click', async () => {
    const dep = $('m-dep').value, arr = $('m-arr').value, note = $('m-suggest-note');
    try {
      const s = await LS.busy(`Searching the next ${dep} → ${arr} launch window…`, $('m-suggest'),
        () => LS.api('/api/suggest_window', { dep, arr, after: LS.fmtDate(new Date()) }));
      set({ 'm-dd': s.departure_iso.slice(0, 10), 'm-ad': s.arrival_iso.slice(0, 10),
        'p-d0': s.window_iso.dep_start, 'p-d1': s.window_iso.dep_end,
        'p-a0': s.window_iso.arr_start, 'p-a1': s.window_iso.arr_end });
      note.innerHTML = `Best opportunity in the next ${LS.fmt(s.synodic_days / 365.25, 1)} years (one synodic period):
        depart <b>${s.departure_iso.slice(0, 10)}</b>, ${LS.fmt(s.tof_days, 0)}-day flight, launch energy
        C₃ = ${LS.fmt(s.c3, 1)} km²/s², total Δv ${LS.fmt(s.total_dv, 2)} km/s. Found by solving
        ${s.searched.toLocaleString('en-US')} Lambert problems. The porkchop window has been centred on it.`;
      note.hidden = false;
      await LS.views.mission.refresh();
    } catch (e) {
      note.textContent = e.message;
      note.hidden = false;
    }
  });
  chips($('m-dep').closest('.grid2'), 'afterend', 'Popular trips', [
    ['Earth → Mars', ['Earth', 'Mars'], 'The most-flown interplanetary trip. Windows open every ≈26 months (e.g. Perseverance, July 2020).'],
    ['Earth → Venus', ['Earth', 'Venus'], 'Windows every ≈19 months. Flights take only ≈4–6 months.'],
    ['Earth → Jupiter', ['Earth', 'Jupiter'], 'Windows every ≈13 months, but a direct trip needs a very powerful launch; real missions use flybys (see Gravity-assist route).'],
    ['Mars → Earth', ['Mars', 'Earth'], 'The return leg of a sample-return mission.'],
  ].map(([l, [d, a], n]) => ({ label: l, note: n + ' Press “Suggest the next launch window” for dates.',
    apply: () => set({ 'm-dep': d, 'm-arr': a }) })));

  /* ---------------- Gravity-assist route builder ---------------- */

  chips($('r-max').closest('.grid2'), 'afterend', 'Typical trip times', [
    ['0.6 y · inner planets', 0.6, 'Mariner 10 reached Mercury about 5 months after launch.'],
    ['3.5 y · Saturn, fast', 3.5, 'Voyager 1 reached Saturn in just over 3 years thanks to Jupiter.'],
    ['6.5 y · Jupiter via VEEGA', 6.5, 'Galileo took 6 years, looping past Venus and Earth twice.'],
    ['10 y · Uranus', 10, 'Voyager 2 reached Uranus 8.4 years after launch.'],
  ].map(([l, v, n]) => ({ label: l, note: n, apply: () => set({ 'r-max': v }) })));
})();
