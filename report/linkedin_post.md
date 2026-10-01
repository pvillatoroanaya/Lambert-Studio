🚀 From a university assignment to a mission-design studio

The assignment: a ground station sees a satellite twice, 2.5 hours apart. From those two sightings, find its full orbit. That's Lambert's problem, the same mathematics used to plan every interplanetary mission.

I kept going, and built Lambert Studio:

🛰️ Real satellites (CelesTrak) and asteroid close approaches (NASA/JPL) in 3D
🪐 Planet positions from NASA/JPL's DE440s ephemeris
🔥 A manoeuvre planner with propellant budgets
🧭 A gravity-assist optimiser with up to four flybys and a cinematic mission playback
⚡ Ion-engine spirals, moon tours and a Learn tab with self-checking challenges

The latest step was accuracy. Earth orbits now feel the gravity field to degree 6, the Moon and Sun, sunlight pressure with Earth's shadow and the NRLMSIS atmosphere. Routes are re-flown with every planet pulling at once, and small course corrections keep them on target, like a real navigation team.

What that showed me about time:
• The same 420 km orbit decays 23× faster at solar maximum than at solar minimum
• A geostationary satellite tilts ~0.95° per year on its own, inside the 0.75–0.95° real operators see
• The same Earth–Mars trip needs almost 2× the launch energy in one window than in another
• Voyager's route, flown uncorrected in real gravity, crashes into Jupiter. 4 m/s of corrections fix it
A simulation answers for a date, not forever.

The part I'm proudest of: the route optimiser is never told the real dates. It found Mariner 10's Venus flyby within 1.6 days, Voyager's launch within 2.2 days and Cassini's Earth flyby within 4 hours.

Everything is checked by 136 automated validation checks and 58 tests, against textbook examples and against history. Biggest lesson: verify everything, and be honest about what the model leaves out.

Built in Python (NumPy, SciPy, Skyfield) with a Three.js interface, developed with Claude Code as an AI pair-programming assistant, with every step directed, run and checked by me.

Full report and slides below 👇

#AerospaceEngineering #OrbitalMechanics #Python #SpaceExploration #EngineeringStudent #NASA
