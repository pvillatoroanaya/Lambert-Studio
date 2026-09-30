🚀 From a university assignment to a mission-design studio

The assignment: a ground station sees a satellite twice, 2.5 hours apart. From those two sightings, find its full orbit. That's Lambert's problem, the same mathematics used to plan every interplanetary mission.

I kept going, and built Lambert Studio:

🛰️ Real satellites from CelesTrak and asteroid close approaches from NASA/JPL, in 3D
🪐 Planet positions from NASA/JPL's DE440s ephemeris
🔥 A manoeuvre planner (Hohmann, bi-elliptic, plane changes) with propellant budgets
🌍 Realistic orbit prediction with Earth's J2 bulge and atmospheric drag
🧭 A gravity-assist optimiser with up to four flybys, and a cinematic playback of each mission

The part I'm proudest of: the route optimiser is never told the real dates. Given only the planets and a launch period, it found:
• Mariner 10's Venus flyby within 1.6 days
• Voyager's launch within 2.2 days
• Cassini's Earth flyby within 4 hours

Everything is checked by 103 automated validation checks and 27 pytest tests, against textbook examples (Curtis) and against history.

Biggest lesson: verify everything. A wider search turned Cassini's route from "worse than flying direct" into the historical one, and a trajectory that returns to exactly the same point breaks Lambert's problem entirely.

Built in Python (NumPy, SciPy, Skyfield) with a Three.js interface, developed with Claude Code as an AI pair-programming assistant, with every step directed, run and checked by me.

Full write-up in the document below 👇

#AerospaceEngineering #OrbitalMechanics #Python #SpaceExploration #EngineeringStudent #NASA
