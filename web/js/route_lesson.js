/* The "why this route" lesson shown with the route suggestions: a plain-
   language explanation of how the recommended trip works, why it beats
   flying straight there, why the launch dates matter, and which real
   missions did the same thing. Written for someone curious about space,
   not for an engineer: few numbers, each one explained. */
'use strict';

(function () {
  const f = (x, d) => LS.fmt(x, d);
  const G0_ISP = 9.80665 * 320 / 1000;     // exhaust speed of a typical chemical engine [km/s]
  const years = (d) => d / 365.25;
  const dur = (days) => {
    if (days < 60) return `${f(days, 0)} days`;
    if (days < 700) return `${f(days / 30.44, 0)} months`;
    return `${f(years(days), 1)} years`;
  };
  const fmtDate = (iso) => new Date(iso + 'T00:00:00Z').toLocaleDateString('en-GB',
    { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
  const ORDER = ['Mercury', 'Venus', 'Earth', 'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune'];
  const outward = (a, b) => ORDER.indexOf(b) > ORDER.indexOf(a);
  const GIANT = new Set(['Jupiter', 'Saturn', 'Uranus', 'Neptune']);
  const ORBIT_SPEED = { Mercury: 47.4, Venus: 35.0, Earth: 29.8, Mars: 24.1,
    Jupiter: 13.1, Saturn: 9.7, Uranus: 6.8, Neptune: 5.4 };   // mean, km/s (NASA fact sheets)

  /* Real missions that flew the same kind of route (dates from NASA/ESA). */
  const MISSIONS = {
    'Earth-Mars': 'Every recent Mars rover flew this way: Curiosity (launched Nov 2011, landed Aug 2012) and Perseverance (launched Jul 2020, landed Feb 2021, a 7-month trip). They launched in the windows that open every 26 months.',
    'Earth-Venus': 'Magellan (1989) and ESA\'s Venus Express (Nov 2005 → Apr 2006, about 5 months) flew straight to Venus like this.',
    'Earth-Mercury': 'No mission has done this: stopping at Mercury directly costs so much fuel that every real Mercury mission uses flybys instead.',
    'Earth-Venus-Mercury': 'Mariner 10 (1973–74) flew exactly this route. Its Venus flyby in February 1974 was the first gravity assist ever used by a spacecraft.',
    'Earth-Venus-Venus-Mercury': 'MESSENGER (2004) used one Earth flyby, two Venus flybys and three Mercury flybys before entering orbit in 2011. ESA/JAXA\'s BepiColombo (2018) uses one Earth, two Venus and six Mercury flybys, arriving in 2026.',
    'Earth-Venus-Mars': 'No mission has flown it yet, but Venus flybys on the way to Mars appear in NASA studies of crewed Mars missions: in some years they make the trip cheaper or shorter.',
    'Earth-Jupiter': 'Pioneer 10 (1972) and New Horizons (2006, on its way to Pluto) flew straight to Jupiter. It takes a very powerful rocket: New Horizons left Earth faster than any spacecraft before it.',
    'Earth-Mars-Jupiter': 'NASA\'s Europa Clipper (launched Oct 2024) flew past Mars in March 2025 and flies past Earth in December 2026, reaching Jupiter in 2030.',
    'Earth-Venus-Earth-Jupiter': 'ESA\'s JUICE (launched April 2023) flies a longer version of this chain (Earth and Moon, Venus, then Earth twice) and reaches Jupiter in July 2031.',
    'Earth-Venus-Earth-Earth-Jupiter': 'This is Galileo\'s route: launched Oct 1989, Venus in Feb 1990, Earth in Dec 1990 and again Dec 1992, Jupiter in Dec 1995. It was chosen after the Challenger accident, when Galileo lost its powerful upper stage and had to borrow the speed from the planets instead. ESA\'s JUICE (2023) is flying almost the same chain today.',
    'Earth-Saturn': 'No mission has flown straight to Saturn: the launch would need a rocket far bigger than normal.',
    'Earth-Jupiter-Saturn': 'Pioneer 11 and Voyager 1 and 2 (1977) all used Jupiter to reach Saturn. Voyager 1 got there in just over 3 years.',
    'Earth-Venus-Earth-Saturn': 'Cassini–Huygens (1997) flew a longer version of this: Venus twice, then Earth, then Jupiter, arriving at Saturn in 2004.',
    'Earth-Jupiter-Uranus': 'Studies for NASA\'s Uranus Orbiter and Probe, the top priority of the 2022 planetary decadal survey, favour a launch in the early 2030s with a Jupiter flyby, exactly like this.',
    'Earth-Jupiter-Saturn-Uranus': 'Voyager 2 is the only spacecraft ever to visit Uranus (January 1986), using Jupiter and Saturn in a rare alignment of the outer planets that happens about once every 175 years.',
    'Earth-Jupiter-Saturn-Neptune': 'Voyager 2 reached Neptune in August 1989, 12 years after launch, after Jupiter, Saturn and Uranus flybys. It is still the only visit to Neptune.',
    'Earth-Jupiter-Neptune': 'Several NASA studies of a Neptune orbiter use a single Jupiter flyby like this; it is the cheapest way to cross such a huge distance in a reasonable time.',
    'Mars-Earth': 'This is how samples would come home: the Mars Sample Return plans use this type of transfer for the Earth Return Orbiter.',
  };

  /* One sentence: the idea behind the route. */
  function idea(o) {
    const seq = o.seq, dep = seq[0], arr = seq[seq.length - 1], mid = seq.slice(1, -1);
    if (!mid.length) {
      return outward(dep, arr)
        ? `Take the simplest path: one arc around the Sun that leaves ${dep} and climbs out to ${arr}, arriving just as ${arr} gets there.`
        : `Take the simplest path: one arc around the Sun that leaves ${dep} and falls inward to ${arr}, arriving just as ${arr} gets there.`;
    }
    const uniq = [...new Set(mid)];
    if (!outward(dep, arr)) {
      return `Going toward the Sun, the problem is <b>too much speed</b>, not too little. The ${uniq.join(' and ')} ` +
        `flyby${mid.length > 1 ? 's act' : ' acts'} as a free brake, so the spacecraft can drop in to ${arr} without burning huge amounts of fuel.`;
    }
    if (mid[0] === 'Venus') {
      return `It sounds backwards: to go <b>out</b> to ${arr}, the spacecraft first falls <b>in</b> toward Venus. ` +
        `Venus, and then Earth${mid.filter((p) => p === 'Earth').length > 1 ? ' twice' : ''}, fling it back out faster each time, ` +
        'like a pinball gaining speed off the bumpers, until it has enough energy to reach ' + arr + '.';
    }
    if (GIANT.has(mid[0])) {
      return `Use ${mid[0]}, ${mid[0] === 'Jupiter' ? 'the heaviest planet in the solar system' : 'a giant planet'}, ` +
        `as a slingshot: its gravity whips the spacecraft onward to ${arr} far faster than any rocket could on its own.`;
    }
    return `Fly past ${uniq.join(' and ')} on the way: ${mid.length > 1 ? 'their' : 'its'} gravity gives a kick ` +
      `for free, so the rocket has to provide less of the speed needed to reach ${arr}.`;
  }

  /* The trip, step by step. */
  function steps(o, data) {
    const seq = o.seq, dep = seq[0], arr = seq[seq.length - 1];
    const out = [];
    const up = outward(dep, seq[1]);
    const gentle = o.c3 < 20;
    out.push(`<b>Launch from ${dep}.</b> The spacecraft already moves with ${dep} around the Sun at about
      ${f(ORBIT_SPEED[dep], 0)} km/s; the rocket only adds a little on top. It fires ${up ? '<b>forward</b>, along'
      : '<b>backward</b>, against'} ${dep}'s motion so the spacecraft ${up ? 'swings out, away from' : 'slows down and falls in toward'} the Sun.
      ${gentle ? 'Only a gentle push is needed.' : 'This takes a big push: the rocket does most of the work on this route.'}`);
    o.flybys.forEach((fb, k) => {
      const L = o.legs[k];
      const again = seq[k] === fb.planet;
      let cruise = `Coast for ${dur(L.days)}`;
      if (again) cruise += ` on an orbit that brings it back to ${fb.planet} — the previous flyby aimed it so the two would meet again`;
      else if (L.revs) cruise += ', looping once around the Sun on the way';
      const low = fb.altitude_radii < 1.5;
      const pass = low ? 'skimming low over the planet' : `passing at about ${f(fb.altitude_radii, 1)} times the planet's radius`;
      const effect = fb.gain >= 0
        ? `it leaves <b>${f(fb.gain, 1)} km/s faster</b> around the Sun, with no fuel burned`
        : `it leaves <b>${f(-fb.gain, 1)} km/s slower</b> around the Sun: the planet has worked as a brake`;
      const burn = fb.dv > 0.05 ? ` (plus a small ${f(fb.dv, 2)} km/s engine burn at closest approach)` : '';
      out.push(`${cruise}. <b>${fb.planet} flyby${again ? ' (again)' : ''}:</b> ${pass}, the spacecraft's path is bent by
        ${f(fb.turn_deg, 0)}°, and ${effect}${burn}.`);
    });
    const Llast = o.legs[o.legs.length - 1];
    let arrive = `Coast for ${dur(Llast.days)}${Llast.revs ? ', looping around the Sun on the way' : ''}, then <b>arrive at ${arr}</b>
      ${dur(o.tof_days)} after launch.`;
    if (o.capture_dv != null) {
      arrive += GIANT.has(arr)
        ? ` A braking burn of ${f(o.capture_dv, 1)} km/s lets ${arr}'s gravity capture it into a long, looping orbit.`
        : ` A braking burn of ${f(o.capture_dv, 1)} km/s slows it enough for ${arr}'s gravity to capture it into orbit.`;
    } else {
      arrive += ' It flies past without stopping, so no braking fuel is needed.';
    }
    out.push(arrive);
    return `<ol class="steps">${out.map((s) => `<li>${s}</li>`).join('')}</ol>`;
  }

  /* How much of the spacecraft must be propellant (rocket equation). */
  function massRatio(dv) { return Math.exp(dv / G0_ISP); }

  function whyNotDirect(o, direct, dep) {
    const mid = o.seq.slice(1, -1);
    if (!mid.length) {
      return `<p>For this trip, adding a flyby does not pay off in these years: the planets that could help are in the wrong
        places, or too small to bend the path usefully. The direct flight is cheaper <i>and</i> simpler.</p>`;
    }
    if (!direct) return '';
    const saved = direct.total_dv - o.total_dv;
    if (saved <= 0.05) {
      return `<p>Here the flyby saves almost nothing compared with flying straight there
        (${f(direct.total_dv, 1)} km/s), but the route is still recommended because of its timing.</p>`;
    }
    const mr1 = massRatio(direct.total_dv), mr2 = massRatio(o.total_dv);
    const where = dep === 'Earth' ? 'in orbit around Earth' : `in orbit around ${dep}`;
    return `<p>Flying straight there would need <b>${f(saved, 1)} km/s more</b> speed from the engines. That sounds small, but
      rockets pay for speed exponentially (this is the <i>rocket equation</i>): with a typical chemical engine, every
      tonne that reaches ${o.seq[o.seq.length - 1]} needs about <b>${f(mr1, 0)} tonnes</b> ${where} on the direct route, but only
      <b>${f(mr2, 0)} tonnes</b> on this one${mr1 / mr2 > 1.6 ? ` — ${f(mr1 / mr2, 1)} times lighter at launch` : ''}.
      ${o.c3 < direct.c3 * 0.5 ? 'The launch itself is also much gentler, so a smaller, cheaper rocket can do it.' : ''}
      That is often the difference between a mission that can be built and one that can't.</p>`;
  }

  function whyDates(o, data) {
    const dep = o.seq[0], arr = o.seq[o.seq.length - 1];
    const syn = data.synodic_days;
    const width = (new Date(o.window_iso[1]) - new Date(o.window_iso[0])) / 86400000 + 1;
    const synText = syn > 700 ? `${f(years(syn), 1)} years` : `${f(syn / 30.44, 0)} months`;
    let t = `<p>The spacecraft isn't aimed at where ${arr} is at launch, but at where it <b>will be</b> when the spacecraft
      gets there — like a quarterback throwing to where the receiver is running. That only works when the planets are in the
      right positions, and ${dep} and ${arr} return to the same positions only once every <b>${synText}</b>.
      This opportunity stays open for about <b>${f(width, 0)} days</b>; launching outside it costs much more fuel.</p>`;
    if (o.seq.length > 2) {
      t += `<p>A flyby route is even pickier: <i>every</i> planet on the chain must be in the right place at the right moment.
        That is why good flyby opportunities come less often, and why space agencies plan missions around them years in advance.</p>`;
    }
    return t;
  }

  function tradeoff(o, cheapest, fastest) {
    const parts = [];
    if (cheapest && cheapest !== o) {
      parts.push(`The cheapest route found (${cheapest.seq.join(' → ')}) saves ${f(o.total_dv - cheapest.total_dv, 1)} km/s more,
        but takes ${dur(cheapest.tof_days)} instead of ${dur(o.tof_days)}.`);
    }
    if (fastest && fastest !== o && fastest.tof_days < o.tof_days - 30) {
      parts.push(`The fastest (${fastest.seq.join(' → ')}) arrives ${dur(o.tof_days - fastest.tof_days)} sooner but
        needs ${f(fastest.total_dv - o.total_dv, 1)} km/s more.`);
    }
    if (!parts.length) return '';
    return `<p>Every mission trades fuel against time. A longer trip means more years of operating the spacecraft and the
      team, and more time for things to fail, so this recommendation counts each extra year as roughly the cost of 0.25 km/s.
      ${parts.join(' ')}</p>`;
  }

  const ANALOGY = `<div class="analogy"><b>How can a planet give speed for free?</b> Picture a tennis ball thrown at an
    oncoming train. Seen from the train, the ball bounces off at the same speed it arrived. But seen from the platform, it
    comes back much faster, because it picked up the train's own speed. In a flyby the planet is the train and gravity does the
    bouncing (without touching). Seen from the planet, the spacecraft leaves exactly as fast as it came, only in a new
    direction; seen from the Sun, it has gained (or lost) speed. The planet pays for it, slowing down by an amount far too
    tiny to ever measure.</div>`;

  /* Which rocket each option needs (launchers.js), in words. */
  function rocket(best, direct, mass) {
    if (!LS.launch || !LS.launch.data || best.seq[0] !== 'Earth') return '';
    const say = (c3) => {
      const s = c3 <= 100 ? LS.launch.smallest(c3, mass) : null;
      return s ? `at least a <b>${s}</b>` : '<b>more than any single rocket in the dataset can give</b>';
    };
    const mine = say(best.c3);
    let t = `<p>For a ${f(mass, 0)} kg spacecraft, the launch (C₃ = ${f(best.c3, 0)} km²/s²) needs ${mine}.`;
    if (direct && direct !== best) {
      const theirs = say(direct.c3);
      if (theirs !== mine) t += ` Flying direct (C₃ = ${f(direct.c3, 0)}) would need ${theirs}.`;
    }
    return t + ` The bigger the launch energy, the less mass a rocket can send: launch energy is expensive.</p>`;
  }

  LS.routeLesson = function (best, ctx) {
    const { cheapest, fastest, direct, data } = ctx;
    const mass = ctx.mass || 2000;
    const key = best.seq.join('-');
    const missions = MISSIONS[key];
    const hasFlyby = best.seq.length > 2;
    return `<div class="why lesson">
      <div class="t">Why this route is recommended</div>
      <div class="headline">${best.seq.join(' → ')} · launch ${fmtDate(best.iso[0])}
        <span>(window ${fmtDate(best.window_iso[0])} – ${fmtDate(best.window_iso[1])}) · trip ${dur(best.tof_days)}</span></div>
      <h5>The idea</h5><p>${idea(best)}</p>
      <h5>How the trip works</h5>${steps(best, data)}
      ${hasFlyby ? ANALOGY : ''}
      <h5>${hasFlyby ? 'Why not fly straight there?' : 'Why not use a flyby?'}</h5>${whyNotDirect(best, direct, best.seq[0])}
      ${rocket(best, direct, mass) ? `<h5>Which rocket?</h5>${rocket(best, direct, mass)}` : ''}
      <h5>Why these dates?</h5>${whyDates(best, data)}
      ${tradeoff(best, cheapest, fastest) ? `<h5>The trade-off</h5>${tradeoff(best, cheapest, fastest)}` : ''}
      ${missions ? `<h5>Real missions that did this</h5><p>${missions}</p>` : ''}
      <p class="glossary"><b>Δv</b> (“delta-v”) is the total change of speed the engines must provide: the fuel budget of a
        mission. <b>km/s</b>: kilometres per second (a rifle bullet flies at about 1 km/s).${hasFlyby
          ? ' Press <b>Play</b> on a route to watch each flyby up close.' : ''}</p>
    </div>`;
  };

  /* Short facts shown while the search runs. */
  LS.routeTips = [
    'A gravity assist can change a spacecraft\'s speed by several km/s without burning a gram of fuel.',
    'Mariner 10 made the first ever gravity assist, at Venus, in February 1974.',
    'Voyager 2 used a planetary alignment that repeats only about every 175 years to visit all four giant planets.',
    'Getting into orbit around Mercury takes more Δv than flying to Pluto: the hard part is shedding Earth\'s 30 km/s around the Sun.',
    'Galileo flew past Earth twice on its way to Jupiter after losing its powerful upper stage.',
    'Earth and Mars line up for a cheap trip only once every 26 months, so Mars missions launch in bursts.',
    'Parker Solar Probe uses seven Venus flybys to fall ever closer to the Sun.',
    'Launching toward the outer planets, the rocket fires forward along Earth\'s orbit; toward Venus or Mercury, it fires backward.',
  ];
})();
