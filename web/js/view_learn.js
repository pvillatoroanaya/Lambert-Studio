/* Learn: guided lessons (text + interactive diagram + quiz + "try it in
   the app"), and challenges that are checked automatically while you use
   the rest of the app. Progress is remembered in this browser. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const W = LS.learnWidgets;
  const KEY = 'lambert-studio-learn';

  const view = { id: 'learn', title: 'Learn', subtitle: 'Orbital mechanics, one idea at a time: read, play, then try it for real' };
  LS.views.learn = view;

  /* ---------------- progress (per browser) ---------------- */

  let progress = { done: {}, quiz: {}, challenges: {} };
  try { progress = Object.assign(progress, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) { /* private mode */ }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(progress)); } catch (e) { /* ignore */ } };

  /* ---------------- navigation helpers for "Try it" ---------------- */

  async function goto(id, after) {
    await LS.setView(id);
    if (after) setTimeout(after, 150);
  }
  function missionRoute(presetText) {
    goto('mission', () => {
      const b = document.querySelector('.ctl[data-for="mission"] .seg button[data-m="route"]');
      if (b) b.click();
      if (presetText) {
        setTimeout(() => {
          const p = [...document.querySelectorAll('#r-presets .preset')].find((x) => x.textContent.includes(presetText));
          if (p) p.click();
        }, 400);
      }
    });
  }

  /* ---------------- the lessons ---------------- */

  const LESSONS = [
    {
      id: 'orbit', title: 'What is an orbit?', mins: 4, widget: 'cannon',
      intro: `An orbit is not "floating" in space. The International Space Station is pulled down by Earth's gravity almost
        as strongly as you are (about 90% as much). It is <b>falling</b>, all the time. It just moves sideways so fast that
        the ground curves away beneath it before it can hit.`,
      body: `<p>Isaac Newton imagined a cannon on a very tall mountain. Fire the ball slowly and it falls nearby. Fire it faster
        and it lands further away. Fire it at just the right speed and it falls around the whole Earth and comes back to
        the cannon: that is a circular orbit. Faster still, and the orbit becomes a stretched ellipse; fast enough, and the
        ball never comes back (escape speed).</p>`,
      after: `<p>Everything in this app, from satellites to Voyager, is this same idea: an object falling around a much more
        massive body, with just the right sideways speed.</p>`,
      tries: [['See a real orbit in the Orbit tab', () => goto('orbit')]],
      quiz: [
        { q: 'Why doesn\'t the ISS fall down?', options: ['There is no gravity at 400 km', 'It is falling, but moves sideways fast enough to keep missing the Earth',
          'The thin air up there holds it up'], a: 1,
          why: 'Gravity at 400 km is about 90% of what it is on the ground. The ISS falls continuously; its 7.7 km/s sideways speed makes it fall around the Earth.' },
        { q: 'You fire the cannon a little faster than circular speed. What happens?', options: ['It escapes forever',
          'It goes into an ellipse that climbs higher on the other side of Earth', 'It crashes'], a: 1,
          why: 'Between circular speed and escape speed the path is an ellipse; the extra speed lets it climb higher on the far side before falling back.' },
      ],
    },
    {
      id: 'kepler', title: 'Faster when closer: Kepler\'s laws', mins: 4, widget: 'kepler',
      intro: `In 1609–1619 Johannes Kepler found three rules that every orbit obeys. They are the reason mission designers can
        predict where a spacecraft will be years ahead.`,
      body: `<ol><li><b>Orbits are ellipses</b>, with the Sun (or planet) at one focus, not at the centre.</li>
        <li><b>Equal areas in equal times:</b> the line from the Sun to the planet sweeps equal areas in equal times, so the
          planet is fastest when it is closest.</li>
        <li><b>Bigger orbits take longer:</b> the period depends only on the orbit's size (period² ∝ size³). Mars' orbit is
          1.52× Earth's, so its year is 1.52<sup>1.5</sup> = 1.88 Earth years.</li></ol>`,
      after: `<p>This is also why a spacecraft slows down as it climbs away from a planet and speeds up as it falls back,
        which is why engines are fired at particular points of an orbit.</p>`,
      tries: [],
      quiz: [
        { q: 'Where on its orbit does a planet move fastest?', options: ['At the far point', 'At the closest point', 'Speed is the same everywhere'], a: 1,
          why: 'Equal areas in equal times: close to the Sun the swept triangle is short and fat, so the planet must cover more distance in the same time.' },
        { q: 'Two orbits have the same size (long axis) but one is much more stretched. Their periods are…',
          options: ['The same', 'Longer for the stretched one', 'Shorter for the stretched one'], a: 0,
          why: 'Kepler\'s third law: the period depends only on the semi-major axis, not on how stretched the orbit is.' },
      ],
    },
    {
      id: 'hohmann', title: 'Changing orbits: the Hohmann transfer', mins: 5, widget: 'hohmann',
      intro: `To move to a bigger orbit you do not point at it and fire. You <b>speed up</b> along your direction of motion:
        that stretches your orbit into an ellipse whose far point touches the target orbit. Half an orbit later, at that far
        point, you speed up again to round it off.`,
      body: `<p>This two-burn trip, found by Walter Hohmann in 1925, is the cheapest way between two circular orbits in most
        cases. The surprise: after both burns you are moving <b>slower</b> than when you started, because higher orbits are
        slower (Kepler again). Speeding up made you higher, and being higher made you slower.</p>`,
      after: `<p>Geostationary satellites (35,786 km up, one lap per day, so they seem to hang still over one spot) are
        placed this way.</p>`,
      tries: [['Plan LEO → GEO in the Maneuver tab', () => goto('maneuver')]],
      quiz: [
        { q: 'After a Hohmann transfer to a higher circular orbit, the spacecraft is moving…', options: ['Faster than before', 'Slower than before', 'At the same speed'], a: 1,
          why: 'Circular orbital speed is √(μ/r): the bigger the orbit, the slower. Both burns add speed, but climbing costs more speed than they add.' },
        { q: 'Where is the second burn made?', options: ['Immediately after the first', 'At the far point of the transfer ellipse, half an orbit later', 'Anywhere'], a: 1,
          why: 'The transfer ellipse touches the target orbit only at its far point, so that is where the orbit is rounded off.' },
      ],
    },
    {
      id: 'rocket', title: 'The rocket equation: why every km/s counts', mins: 5, widget: 'rocket',
      intro: `A rocket pushes itself forward by throwing mass backward. In 1903 Konstantin Tsiolkovsky worked out the
        consequence: the mass you need grows <b>exponentially</b> with the change of speed (Δv) you want.`,
      body: `<p><b>m<sub>start</sub> / m<sub>end</sub> = e<sup>Δv / v<sub>exhaust</sub></sup></b>. With a chemical engine
        (exhaust at ~3 km/s), 3 km/s of Δv means 63% of the spacecraft is propellant; 6 km/s means 86%; 9 km/s means 95%.
        That is why Δv is the "currency" of spaceflight, why mission designers use gravity assists wherever they can, and
        why rockets are mostly fuel tank.</p>
        <p>The launch itself is described by the <b>launch energy C₃</b>: the square of the speed left over after escaping
        Earth. The higher C₃, the less mass a given rocket can send.</p>`,
      after: `<div id="lesson-launch-chart" class="lesson-chart"></div>
        <p class="hint">Mass each rocket can send away from Earth, by launch energy (NASA Launch Services Program planning
        curves, via A. P. Girija's 2023 dataset). Mars needs C₃ ≈ 8–16; Jupiter directly ≈ 75–85.</p>`,
      tries: [['See which rocket each route needs (Mission tab)', () => missionRoute()]],
      quiz: [
        { q: 'Doubling the Δv of a chemical mission roughly…', options: ['Doubles the propellant needed', 'Multiplies the starting mass by far more than two', 'Makes no difference'], a: 1,
          why: 'The mass ratio is e^(Δv/ve): doubling Δv squares the mass ratio (e.g. 2.7 becomes 7.4).' },
        { q: 'Why can a small rocket launch a spacecraft to Jupiter using Venus and Earth flybys, when going direct needs a huge one?',
          options: ['Flybys make the spacecraft lighter', 'The flybys provide speed the rocket would otherwise have to give, so the launch energy C₃ is much lower', 'Venus refuels it'], a: 1,
          why: 'A lower C₃ at launch means the rocket can carry much more mass; the planets supply the rest of the speed.' },
      ],
      onShow: () => launchChart(),
    },
    {
      id: 'windows', title: 'Launch windows: aiming at a moving target', mins: 4, widget: 'windows',
      intro: `You cannot launch to Mars whenever you like. The trip takes months, and Mars keeps moving, so you aim at where
        Mars <b>will be</b> when you arrive, like a quarterback throwing to where the receiver is running.`,
      body: `<p>For the cheapest trip, Mars must be about 44° ahead of Earth at launch. Earth, on its faster inner track, laps
        Mars once every 780 days, so this geometry (the <b>launch window</b>) comes back only every 26 months. That is why
        Mars missions launch in bursts: Curiosity in November 2011, Perseverance, Hope and Tianwen-1 all in July 2020.</p>`,
      after: `<p>The porkchop plot in the Mission tab maps every combination of launch and arrival date: its dark "eye" is the
        window.</p>`,
      tries: [['Make a porkchop plot (Mission tab)', () => goto('mission')]],
      quiz: [
        { q: 'How often do cheap launch windows to Mars open?', options: ['Every year', 'About every 26 months', 'Every 11 years'], a: 1,
          why: 'Earth laps Mars every 780 days (the synodic period), so the same geometry returns every ~26 months.' },
        { q: 'At launch, you aim the spacecraft…', options: ['At Mars', 'At where Mars will be when you arrive', 'Straight away from the Sun'], a: 1,
          why: 'Mars moves about 136° along its orbit during a 259-day Hohmann-like trip.' },
      ],
    },
    {
      id: 'lambert', title: 'Lambert\'s problem: the heart of this app', mins: 5, widget: 'lambert',
      intro: `Given two positions and the time to fly between them, which orbit connects them? This is <b>Lambert's
        problem</b> (Johann Lambert, 1761), and it is what this app solves thousands of times per second.`,
      body: `<p>In the Orbit tab it turns two radar observations of a satellite into its full orbit. In the Mission tab it
        connects Earth on a launch date with Mars on an arrival date. The answer depends strongly on the time: too short
        and the path must be very fast (a hyperbola); longer and it becomes a gentle ellipse.</p>
        <p>Solving it means finding the orbit whose flight time matches exactly: the app uses Curtis' universal-variable
        method with a guaranteed-to-converge search.</p>`,
      after: `<p>Slide the arrival point and the flight time: some combinations are cheap, most are expensive. A porkchop plot
        is simply this, repeated for every pair of dates.</p>`,
      tries: [['Solve the assignment orbit (Orbit tab)', () => goto('orbit')]],
      quiz: [
        { q: 'What does Lambert\'s problem give you?', options: ['The time between two positions', 'The orbit (and velocities) that connects two positions in a given time', 'The position of a planet'], a: 1,
          why: 'Inputs: two positions and a flight time. Output: the orbit and the velocities at both ends.' },
      ],
    },
    {
      id: 'flyby', title: 'Gravity assists: the flyby sandbox', mins: 6, widget: 'sandbox',
      intro: `How can a planet give a spacecraft speed for free? <b>Relative to the planet</b>, the spacecraft leaves exactly
        as fast as it arrived: gravity only turns its direction. But the planet is moving around the Sun, so that turn can
        add (or remove) some of the planet's own speed.`,
      body: `<p>Think of a tennis ball thrown at an oncoming train: seen from the train, it bounces back at the same speed; seen
        from the platform, it comes back much faster. Play with the sandbox below: the <b>velocity triangle</b> on the right
        is how engineers see it. The planet's velocity (orange) plus the spacecraft's velocity relative to the planet (blue
        before, green after) gives its speed around the Sun (grey before, white after). The flyby can only rotate the
        blue arrow into the green one, keeping its length.</p>`,
      after: `<p>Try: pass close <b>behind</b> Jupiter to gain the most; pass <b>in front</b> of Venus to brake. Heavy planets
        and slow, close passes bend the path most. Mariner 10 used the first real gravity assist, at Venus, in 1974.</p>
        <p><b>Simple model vs real gravity.</b> Routes are designed with <i>patched conics</i>: only one body pulls at a time.
        Flown in the real solar system (every planet and the Moon pulling at once), the same launch misses its target by
        tens or hundreds of thousands of kilometres, or even hits the planet. Navigators aim the launch with the full model
        and make small <b>trajectory-correction manoeuvres</b>. Open a route in the Mission tab and press <i>Check in full
        solar-system gravity</i> to see it done.</p>`,
      tries: [['Watch Voyager\'s Jupiter flyby', () => missionRoute('Voyager')]],
      quiz: [
        { q: 'Relative to the planet, after a (fuel-free) flyby the spacecraft is…', options: ['Faster', 'Slower', 'Exactly as fast as before, in a new direction'], a: 2,
          why: 'In the planet\'s frame, gravity is conservative: the spacecraft climbs out of the same "well" it fell into.' },
        { q: 'To gain speed around the Sun, you pass…', options: ['Behind the planet (the side it moves away from)', 'In front of it', 'It does not matter'], a: 0,
          why: 'Passing behind, the planet\'s gravity pulls you forward along its direction of motion.' },
      ],
    },
    {
      id: 'arrival', title: 'Arriving: capture and moon tours', mins: 5, widget: null,
      intro: `Reaching a planet is only half the job: to stay, the spacecraft must brake, because it arrives much faster than an
        orbit allows. And braking costs fuel, lots of it.`,
      body: `<p><b>Capture:</b> the braking burn is made at the closest point, where the spacecraft moves fastest. A change of
        speed there changes the orbit's energy the most (the <b>Oberth effect</b>), so a small burn is enough to be caught
        into a huge, loose orbit.</p>
        <p><b>Moon tours:</b> then the moons take over. Each flyby of a big moon bends the path and reshapes the orbit, free
        of charge. Choosing orbits that bring the spacecraft back to the same moon (resonances) lets designers repeat this
        dozens of times. Galileo, Cassini (127 Titan flybys) and JUICE all do it.</p>
        <p><b>The Tisserand graph</b> (in the Arrival tab) is the map of every orbit each moon can give at each relative speed:
        tours "climb down" it, hopping between moons, until they can arrive gently at the target moon.</p>`,
      after: '',
      tries: [['Plan JUICE\'s tour to Ganymede (Arrival tab)', () => goto('arrival')]],
      quiz: [
        { q: 'Why is the capture burn made at the closest point to the planet?', options: ['The planet\'s atmosphere helps', 'The spacecraft is fastest there, so the burn changes its energy the most (Oberth effect)', 'Only there can the engine be pointed'], a: 1,
          why: 'Energy change ≈ v × Δv, so the same Δv does most where v is largest.' },
        { q: 'JUICE takes 3.5 years touring Jupiter\'s moons before orbiting Ganymede because…', options: ['It needs time to take photos', 'The tour slows it down relative to Ganymede, so the final braking burn is small', 'Ganymede is hard to find'], a: 1,
          why: 'In the example tour, entering Ganymede orbit on the first pass would cost ~4.9 km/s; after the tour, ~1.2 km/s.' },
      ],
    },
    {
      id: 'ion', title: 'Ion engines: the tortoise wins', mins: 4, widget: 'ion',
      intro: `An ion engine uses electricity (from solar panels) to accelerate charged xenon atoms to 20–40 km/s, ten times
        faster than a chemical exhaust. The push is tiny, about the weight of two sheets of paper, but it never stops.`,
      body: `<p>By the rocket equation, faster exhaust means far less propellant. Dawn carried 425 kg of xenon and changed its
        speed by about 11 km/s in total: with chemical propellant that would have needed a spacecraft many times bigger.
        The price is time: months or years of continuous thrust, spiralling slowly outward.</p>`,
      after: `<p>Surprise: an ion spacecraft pushing <i>forward</i> to climb to a higher orbit ends up moving <i>slower</i>, for
        the same reason as in the Hohmann lesson. See it in the Ion tab's chart.</p>`,
      tries: [['Fly Dawn\'s spiral (Ion tab)', () => goto('lowthrust')]],
      quiz: [
        { q: 'Ion engines save propellant because…', options: ['Xenon is light', 'Their exhaust is about 10× faster than a chemical engine\'s', 'They only work in space'], a: 1,
          why: 'Propellant needed depends on Δv / v_exhaust; a 10× faster exhaust means far less propellant for the same Δv.' },
      ],
    },
    {
      id: 'uncert', title: 'How sure are we? Orbit determination', mins: 4, widget: 'errors',
      intro: `The orbit you solve in the Orbit tab comes from two measurements, and every measurement has errors. How much do
        small errors matter?`,
      body: `<p>An angle error of 0.01° is tiny, but 17,000 km away it moves the satellite by 3 km sideways. That changes the
        computed orbit's size, and therefore its period, by a few seconds. A few seconds per lap sounds harmless, but it adds
        up: each orbit the prediction slips further ahead or behind. After a week it can be hundreds of kilometres off.</p>
        <p>That is why tracking networks (like NASA's Deep Space Network) measure again and again, and why the Orbit tab can
        re-solve your orbit 3,000 times with random errors (a Monte Carlo study) to show the real uncertainty.</p>`,
      after: '',
      tries: [['Run the uncertainty study (Orbit tab)', () => goto('orbit', () => { $('mc-box').open = true; $('btn-mc').click(); })]],
      quiz: [
        { q: 'A small error in the orbit\'s size mostly makes the prediction wrong…', options: ['Up and down', 'Along the orbit (ahead or behind), growing every lap', 'Sideways, out of the orbit plane'], a: 1,
          why: 'Size sets the period; a period error accumulates as an along-track drift each orbit.' },
      ],
    },
  ];

  /* ---------------- challenges ---------------- */

  const AU = 1.495978707e8;
  const CHALLENGES = [
    { id: 'geo', title: 'Geostationary on a budget', goal: 'Transfer from a 300 km orbit to geostationary altitude (35,786 km) for less than 4.0 km/s.',
      hint: 'Maneuver tab. Where you launch from matters: look at the inclinations.', event: 'maneuver',
      check: ({ plan, req }) => Math.abs(+req.alt2 - 35786) < 50 && +req.alt1 <= 350 && plan.total_dv < 4.0 },
    { id: 'mars', title: 'Mars in a hurry', goal: 'Find a direct Earth → Mars transfer that takes 200 days or less with launch energy C₃ below 15 km²/s².',
      hint: 'Mission tab → Direct transfer: make a porkchop plot and look along its fast (short-trip) edge.', event: 'transfer',
      check: (t) => t.departure === 'Earth' && t.arrival === 'Mars' && t.tof_days <= 200 && t.c3 < 15 },
    { id: 'jupiter', title: 'Jupiter on a shoestring', goal: 'Find a route from Earth to Jupiter that needs less than 5 km/s in total.',
      hint: 'Mission tab → Gravity-assist route → Suggest routes.', event: 'route',
      check: (r) => r.seq[0] === 'Earth' && r.seq[r.seq.length - 1] === 'Jupiter' && r.total_dv < 5 && r.feasible },
    { id: 'juno', title: 'Juno\'s trick', goal: 'Compute Juno\'s route, with its burn in deep space.', hint: 'Mission tab → Gravity-assist route → the Juno example.',
      event: 'route', check: (r) => !!r.dsm },
    { id: 'sling', title: 'Slingshot master', goal: 'In the flyby sandbox, gain at least 10 km/s in a single flyby.',
      hint: 'Only a giant planet can do it. Pass close, behind it.', event: 'sandbox', check: (r) => r && r.gain >= 10 },
    { id: 'brake', title: 'Free brakes', goal: 'In the flyby sandbox, lose at least 5 km/s in a single flyby.',
      hint: 'Pass in front of the planet.', event: 'sandbox', check: (r) => r && r.gain <= -5 },
    { id: 'moon', title: 'Moon hopper', goal: 'End a moon tour in orbit around a moon with a final braking burn below 1.2 km/s.',
      hint: 'Arrival tab: try the examples, or add a second moon to the flybys.', event: 'tour-result',
      check: (t) => t.insertion_dv !== null && t.insertion_dv < 1.2 },
    { id: 'ion', title: 'Patience pays', goal: 'Reach Mars\' orbit (1.52 AU or beyond) with an ion engine in under 400 days, using less than 25% of the mass as propellant.',
      hint: 'Ion tab: more thrust shortens the trip; a higher Isp saves propellant.', event: 'lowthrust-result',
      check: (r) => r.body === 'Sun' && r.r2 >= 1.52 * AU && r.duration / 86400 < 400 && r.propellant / r.mass < 0.25 },
    { id: 'track', title: 'Tracking pro', goal: 'Keep the one-week prediction error of the assignment orbit below 100 km.',
      hint: 'Orbit tab → How certain is this orbit? What if the sensors were better?', event: 'mc-result',
      check: (r) => r.per_orbit[r.per_orbit.length - 1].along_std < 100 },
    { id: 'navigator', title: 'Navigator', goal: 'Fly a gravity-assist route in full solar-system gravity with less than 10 m/s of course corrections.',
      hint: 'Mission tab → a route → Check in full solar-system gravity. Clean designs need the least correcting.',
      event: 'nbody', check: (v) => v.encounters.length >= 2 && v.tcm_total < 0.010 },
    { id: 'weather', title: 'Space weather', goal: 'Show an orbit decaying at least 3 times faster at solar maximum than at solar minimum.',
      hint: 'Perturb tab: the two "same orbit at solar minimum / maximum" examples, 30 days each.', event: 'perturb-result',
      check: (r) => {
        const s = r.summary;
        if (s.atmosphere !== 'msis' || s.days_run < 20) return false;
        // Orbit-averaged size at the start and the end (the instantaneous
        // value wobbles by ~10 km every orbit because of J2).
        const n = Math.max(1, Math.floor(r.a.length / 20));
        const avg = (arr) => arr.reduce((x, y) => x + y, 0) / arr.length;
        weatherRates[s.activity] = (avg(r.a.slice(0, n)) - avg(r.a.slice(-n))) / s.days_run;
        return weatherRates.low > 0 && weatherRates.high > 3 * weatherRates.low;
      } },
    { id: 'quiz', title: 'Quiz master', goal: 'Answer every quiz question in the lessons correctly.', event: 'quiz',
      check: () => allQuiz() },
  ];

  const weatherRates = {};

  function allQuiz() {
    return LESSONS.every((L) => L.quiz.every((_, k) => progress.quiz[`${L.id}-${k}`] === true));
  }

  function complete(ch) {
    if (progress.challenges[ch.id]) return;
    progress.challenges[ch.id] = Date.now();
    save();
    renderSide();
    LS.status(`Challenge complete: ${ch.title}!`, 'ok');
    const t = document.createElement('div');
    t.className = 'ch-toast';
    t.innerHTML = `<b>Challenge complete</b><span>${ch.title}</span>`;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }

  const events = [...new Set(CHALLENGES.map((c) => c.event))];
  events.forEach((ev) => LS.on(ev, (data) => {
    CHALLENGES.filter((c) => c.event === ev).forEach((c) => {
      try { if (c.check(data)) complete(c); } catch (e) { /* malformed data: ignore */ }
    });
  }));

  /* ---------------- rendering ---------------- */

  let current = null, running = null;

  function renderSide() {
    const nDone = LESSONS.filter((L) => progress.done[L.id]).length;
    const nCh = CHALLENGES.filter((c) => progress.challenges[c.id]).length;
    $('learn-progress').innerHTML = `<div class="lp"><i style="width:${(100 * nDone / LESSONS.length).toFixed(0)}%"></i></div>
      <span>${nDone} of ${LESSONS.length} lessons · ${nCh} of ${CHALLENGES.length} challenges</span>`;
    $('learn-lessons').innerHTML = LESSONS.map((L, k) => `<button class="lesson-btn${current === L.id ? ' on' : ''}${progress.done[L.id] ? ' done' : ''}" data-id="${L.id}">
      <i>${progress.done[L.id] ? '✓' : k + 1}</i><span><b>${L.title}</b><small>${L.mins} min${L.widget ? ' · interactive' : ''}</small></span></button>`).join('');
    $('learn-lessons').querySelectorAll('.lesson-btn').forEach((b) => b.addEventListener('click', () => open(b.dataset.id)));
    $('learn-challenges').innerHTML = CHALLENGES.map((c) => `<div class="ch${progress.challenges[c.id] ? ' done' : ''}">
      <i>${progress.challenges[c.id] ? '✓' : '○'}</i><span><b>${c.title}</b><small>${c.goal}</small>
      ${progress.challenges[c.id] ? '' : `<em>Hint: ${c.hint || ''}</em>`}</span></div>`).join('');
  }

  function open(id) {
    if (running) { running.stop(); running = null; }
    current = id;
    const k = LESSONS.findIndex((L) => L.id === id);
    const L = LESSONS[k];
    const next = LESSONS[k + 1];
    $('learn-page').innerHTML = `<article class="lesson">
      <div class="kicker">Lesson ${k + 1} of ${LESSONS.length} · ${L.mins} min</div>
      <h1>${L.title}</h1>
      <p class="lead">${L.intro}</p>
      ${L.body}
      ${L.widget ? '<div class="widget" id="lesson-widget"></div>' : ''}
      ${L.after}
      ${L.tries.length ? `<div class="tries">${L.tries.map((t, i) => `<button class="try" data-i="${i}">▶ ${t[0]}</button>`).join('')}</div>` : ''}
      <h2>Check yourself</h2>
      <div class="quiz">${L.quiz.map((q, qi) => quizHtml(L, q, qi)).join('')}</div>
      <div class="lesson-nav">
        ${k > 0 ? `<button class="ghost" id="lesson-prev">← ${LESSONS[k - 1].title}</button>` : '<span></span>'}
        ${next ? `<button class="primary" id="lesson-next">Next: ${next.title} →</button>` : '<button class="primary" id="lesson-next">Finish ✓</button>'}
      </div></article>`;
    $('learn-page').scrollTop = 0;
    if (L.widget) {
      running = W[L.widget]($('lesson-widget'), L.widget === 'sandbox' ? (r) => LS.emit('sandbox', r) : undefined);
    }
    $('learn-page').querySelectorAll('.try').forEach((b) => b.addEventListener('click', () => L.tries[+b.dataset.i][1]()));
    $('learn-page').querySelectorAll('.quiz .opt').forEach((b) => b.addEventListener('click', () => answer(L, b)));
    if ($('lesson-prev')) $('lesson-prev').onclick = () => open(LESSONS[k - 1].id);
    $('lesson-next').onclick = () => {
      progress.done[L.id] = true; save();
      if (next) open(next.id); else { renderSide(); $('learn-page').scrollTop = 0; }
    };
    if (L.onShow) L.onShow();
    renderSide();
    try { localStorage.setItem(`${KEY}-last`, id); } catch (e) { /* ignore */ }
  }

  function quizHtml(L, q, qi) {
    const state = progress.quiz[`${L.id}-${qi}`];
    return `<div class="q" data-q="${qi}"><p><b>${qi + 1}.</b> ${q.q}</p>
      ${q.options.map((o, oi) => `<button class="opt${state !== undefined && oi === q.a ? ' right' : ''}" data-q="${qi}" data-o="${oi}">${o}</button>`).join('')}
      <p class="why"${state === undefined ? ' hidden' : ''}>${state === true ? '✓ Correct. ' : state === false ? '✗ Not quite. ' : ''}${q.why}</p></div>`;
  }

  function answer(L, b) {
    const qi = +b.dataset.q, oi = +b.dataset.o, q = L.quiz[qi];
    const box = b.closest('.q');
    const ok = oi === q.a;
    if (progress.quiz[`${L.id}-${qi}`] !== true) progress.quiz[`${L.id}-${qi}`] = ok;
    save();
    box.querySelectorAll('.opt').forEach((x, i) => {
      x.classList.toggle('right', i === q.a);
      x.classList.toggle('wrong', i === oi && !ok);
    });
    const why = box.querySelector('.why');
    why.hidden = false;
    why.innerHTML = `${ok ? '✓ Correct. ' : '✗ Not quite. '}${q.why}`;
    LS.emit('quiz', null);
    renderSide();
  }

  async function launchChart() {
    try {
      const d = await LS.launch.load();
      const colors = ['#8d95a8', '#5eb3e6', '#7fb8ff', '#e3cc6a', '#7fcf9f', '#eea55a', '#ffd27a', '#ea7f7f', '#e56f6f', '#e9ecf3'];
      Plotly.react('lesson-launch-chart', d.order.map((n, k) => ({
        x: d.curves[n].map((p) => p[0]), y: d.curves[n].map((p) => p[1]), name: n, type: 'scatter', mode: 'lines',
        line: { color: colors[k % colors.length], width: 2 } })), LS.plotLayout({
        margin: { l: 56, r: 12, t: 38, b: 42 },
        xaxis: { title: { text: 'launch energy C₃ (km²/s²)', font: { size: 11 } }, gridcolor: 'rgba(255,255,255,0.06)', color: '#8d95a8' },
        yaxis: { title: { text: 'mass it can launch (kg)', font: { size: 11 } }, gridcolor: 'rgba(255,255,255,0.06)', color: '#8d95a8' },
      }), LS.plotConfig);
    } catch (e) { /* chart is optional */ }
  }

  view.init = function () {
    $('learn-reset').addEventListener('click', () => {
      if (!$('learn-reset').dataset.sure) {
        $('learn-reset').dataset.sure = '1';
        $('learn-reset').textContent = 'Click again to erase progress';
        setTimeout(() => { delete $('learn-reset').dataset.sure; $('learn-reset').textContent = 'Reset progress'; }, 3000);
        return;
      }
      progress = { done: {}, quiz: {}, challenges: {} };
      save();
      open(current || LESSONS[0].id);
    });
    let last = null;
    try { last = localStorage.getItem(`${KEY}-last`); } catch (e) { /* ignore */ }
    open(LESSONS.some((L) => L.id === last) ? last : LESSONS[0].id);
  };
  view.show = () => { if (current && !running) open(current); };
  view.hide = () => { if (running) { running.stop(); running = null; } };
  LS.learn = { lessons: LESSONS, challenges: CHALLENGES, open, progress: () => progress };

  renderSide.call(null);
})();
