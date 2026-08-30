-- ==============================================================================
-- 03_bodies.sql: Celestial Bodies (Stars, Planets, Barycentres) Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS bodies (
    system_id64 BIGINT,
    id64 BIGINT PRIMARY KEY,
    bodyid BIGINT,
    name TEXT,
    type TEXT,
    subtype TEXT,
    distancetoarrival DOUBLE PRECISION,
    orbitalperiod DOUBLE PRECISION,
    semimajoraxis DOUBLE PRECISION,
    orbitaleccentricity DOUBLE PRECISION,
    orbitalinclination DOUBLE PRECISION,
    argofperiapsis DOUBLE PRECISION,
    meananomaly DOUBLE PRECISION,
    ascendingnode DOUBLE PRECISION,
    rotationalperiod DOUBLE PRECISION,
    rotationalperiodtidallylock BOOLEAN,
    axialtilt DOUBLE PRECISION,
    surfacetemperature DOUBLE PRECISION,
    radius DOUBLE PRECISION,
    islandable BOOLEAN,
    gravity DOUBLE PRECISION,
    earthmasses DOUBLE PRECISION,
    surfacepressure DOUBLE PRECISION,
    volcanismtype TEXT,
    atmospheretype TEXT,
    terraformingstate TEXT,
    reservelevel TEXT,
    mainstar BOOLEAN,
    age INTEGER,
    spectralclass TEXT,
    luminosity TEXT,
    absolutemagnitude DOUBLE PRECISION,
    solarmasses DOUBLE PRECISION,
    solarradius DOUBLE PRECISION,
    atmospherecomposition JSONB,
    solidcomposition JSONB,
    materials JSONB,
    parents JSONB,
    timestamps JSONB,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc')
);

-- Documentation
COMMENT ON TABLE bodies IS
  'One row per surveyed celestial body (planet, star, or barycentre). '
  'Flattened from the bodies[] array inside each system object in galaxy.json. '
  'id64 is globally unique across the entire galaxy. '
  'Star-only columns (mainStar, age, spectralClass, luminosity, absoluteMagnitude, solarMasses, solarRadius) '
  'are NULL for planets and barycentres. '
  'Planet-only columns (isLandable, gravity, earthMasses, radius, surfacePressure, volcanismType, '
  'atmosphereType, terraformingState, reserveLevel, atmosphereComposition, solidComposition, materials) '
  'are NULL for stars and barycentres.';

COMMENT ON COLUMN bodies.system_id64 IS
  'Foreign reference to systems.id64 — the system this body belongs to.';

COMMENT ON COLUMN bodies.id64 IS
  'Globally unique 64-bit Galactic Celestial ID of the body. Primary key. '
  'Deterministically computed as (system_id64 << 9) | (bodyId & 0x1FF), congruent with Spansh and EDSM canonical standards. '
  'Source field: bodies[].id64.';

COMMENT ON COLUMN bodies.bodyid IS
  'Frontier system-local integer index of the body within its system (0-511). '
  'Used to resolve parent references and composite body ID64 calculations. Source field: bodies[].bodyId.';

COMMENT ON COLUMN bodies.name IS
  'Name of the celestial body (e.g. "Sol A", "Earth", "Sol 5 a"). Source field: bodies[].name.';

COMMENT ON COLUMN bodies.type IS
  'High-level classification of the body. Enum: Planet, Star, Barycentre. Source field: bodies[].type.';

COMMENT ON COLUMN bodies.subType IS
  'Detailed subtype of the body. '
  'Planet subtypes include: Ammonia world, Earth-like world, High metal content world, Rocky body, etc. '
  'Star subtypes include: G (White-Yellow) Star, Neutron Star, Black Hole, White Dwarf (DA) Star, etc. '
  'Source field: bodies[].subType.';

COMMENT ON COLUMN bodies.distancetoarrival IS
  'Distance from the system arrival point (main star) to this body, in light-seconds (ls). '
  'Source field: bodies[].distanceToArrival.';

COMMENT ON COLUMN bodies.orbitalperiod IS
  'Orbital period of the body around its parent, in days. Source field: bodies[].orbitalPeriod.';

COMMENT ON COLUMN bodies.semimajoraxis IS
  'Semi-major axis of the body''s orbit, in kilometres. Source field: bodies[].semiMajorAxis.';

COMMENT ON COLUMN bodies.orbitaleccentricity IS
  'Orbital eccentricity (0.0 = circular, <1.0 = elliptical). Source field: bodies[].orbitalEccentricity.';

COMMENT ON COLUMN bodies.orbitalinclination IS
  'Orbital inclination relative to the reference plane, in degrees. Source field: bodies[].orbitalInclination.';

COMMENT ON COLUMN bodies.argofperiapsis IS
  'Argument of periapsis (0–360 degrees). Source field: bodies[].argOfPeriapsis.';

COMMENT ON COLUMN bodies.meananomaly IS
  'Mean anomaly at epoch (0–360 degrees). Source field: bodies[].meanAnomaly.';

COMMENT ON COLUMN bodies.ascendingnode IS
  'Longitude of the ascending node (-180 to 180 degrees). Source field: bodies[].ascendingNode.';

COMMENT ON COLUMN bodies.rotationalperiod IS
  'Sidereal rotational period of the body, in days. Negative values indicate retrograde rotation. '
  'Source field: bodies[].rotationalPeriod.';

COMMENT ON COLUMN bodies.rotationalperiodtidallylock IS
  'TRUE if the body is tidally locked to its parent (rotational period equals orbital period). '
  'Source field: bodies[].rotationalPeriodTidallyLocked.';

COMMENT ON COLUMN bodies.axialtilt IS
  'Axial tilt of the body, in radians. Source field: bodies[].axialTilt.';

COMMENT ON COLUMN bodies.surfacetemperature IS
  'Surface temperature of the body in Kelvin. Applies to both stars and planets. '
  'Source field: bodies[].surfaceTemperature.';

COMMENT ON COLUMN bodies.radius IS
  'Planets only. Equatorial radius of the planet in kilometres. Source field: bodies[].radius.';

COMMENT ON COLUMN bodies.islandable IS
  'Planets only. TRUE if the planet surface can be landed on in-game. Source field: bodies[].isLandable.';

COMMENT ON COLUMN bodies.gravity IS
  'Planets only. Surface gravity as a ratio of Earth''s gravity (1.0 = 9.81 m/s²). '
  'Source field: bodies[].gravity.';

COMMENT ON COLUMN bodies.earthmasses IS
  'Planets only. Mass of the planet as a ratio of Earth''s mass. Source field: bodies[].earthMasses.';

COMMENT ON COLUMN bodies.surfacepressure IS
  'Planets only. Atmospheric surface pressure in Earth atmospheres (atm). '
  'Source field: bodies[].surfacePressure.';

COMMENT ON COLUMN bodies.volcanismtype IS
  'Planets only. Type of volcanism present on the planet surface. '
  'Enum: No volcanism, Rocky Magma, Water Geysers, Carbon Dioxide Geysers, Major Metallic Magma, etc. '
  'Source field: bodies[].volcanismType.';

COMMENT ON COLUMN bodies.atmospheretype IS
  'Planets only. Dominant atmosphere composition/density label. '
  'Enum: No atmosphere, Nitrogen, Carbon dioxide, Ammonia, Water, Oxygen, etc. (50+ values). '
  'Source field: bodies[].atmosphereType.';

COMMENT ON COLUMN bodies.terraformingstate IS
  'Planets only. Terraforming status. Enum: Not terraformable, Terraformable, Terraforming, Terraformed. '
  'Source field: bodies[].terraformingState.';

COMMENT ON COLUMN bodies.reservelevel IS
  'Planets only. Mining reserve level of the planet or its rings. '
  'Enum: Depleted, Low, Common, Major, Pristine. Source field: bodies[].reserveLevel.';

COMMENT ON COLUMN bodies.mainstar IS
  'Stars only. TRUE if this is the primary/arrival star of the system. Source field: bodies[].mainStar.';

COMMENT ON COLUMN bodies.age IS
  'Stars only. Age of the star in millions of solar years. Source field: bodies[].age.';

COMMENT ON COLUMN bodies.spectralclass IS
  'Stars only. Stellar spectral classification code (e.g. G2, K5, DA0, N0). '
  'Follows the MKK system with white dwarf and exotic variants. Source field: bodies[].spectralClass.';

COMMENT ON COLUMN bodies.luminosity IS
  'Stars only. Yerkes luminosity class of the star (e.g. V = main sequence, Ia = supergiant, VII = white dwarf). '
  'Source field: bodies[].luminosity.';

COMMENT ON COLUMN bodies.absolutemagnitude IS
  'Stars only. Absolute magnitude of the star (lower = brighter). Source field: bodies[].absoluteMagnitude.';

COMMENT ON COLUMN bodies.solarmasses IS
  'Stars only. Mass of the star as a ratio of Sol''s mass. Source field: bodies[].solarMasses.';

COMMENT ON COLUMN bodies.solarradius IS
  'Stars only. Radius of the star as a ratio of Sol''s radius. Source field: bodies[].solarRadius.';

COMMENT ON COLUMN bodies.atmospherecomposition IS
  'Planets only. JSONB object mapping element/compound name to percentage share (e.g. {"Nitrogen": 78.0}). '
  'GIN-indexed for element membership queries. Source field: bodies[].atmosphereComposition.';

COMMENT ON COLUMN bodies.solidcomposition IS
  'Planets only. JSONB object mapping solid material name to percentage share (e.g. {"Rock": 70.0, "Metal": 30.0}). '
  'GIN-indexed for material queries. Source field: bodies[].solidComposition.';

COMMENT ON COLUMN bodies.materials IS
  'Planets only. JSONB object mapping mineable material name to percentage yield '
  '(e.g. {"Iron": 18.5, "Germanium": 2.1}). GIN-indexed for material presence queries. '
  'Source field: bodies[].materials.';

COMMENT ON COLUMN bodies.parents IS
  'JSONB array of parent body references. Each element is an object with a single key-value pair '
  'mapping the parent type ("Star", "Planet", "Barycentre", "Null") to the parent''s bodyId. '
  'Example: [{"Star": 0}, {"Planet": 3}]. Source field: bodies[].parents.';

COMMENT ON COLUMN bodies.timestamps IS
  'JSONB object mapping individual field names to their last-updated UTC timestamp strings. '
  'Allows field-level change tracking within a body record. Source field: bodies[].timestamps.';

COMMENT ON COLUMN bodies.update_dtm IS
  'UTC timestamp of when this celestial body record was last updated by the Spansh ingest pipeline or live EDDN stream.';
