-- ==============================================================================
-- 17_engineers.sql: Planetary & Station Engineer Workshops Reference Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS engineers (
    system_id64 BIGINT NOT NULL,
    body_id64 BIGINT,
    market_id BIGINT,
    engineer_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    engineer_type TEXT NOT NULL, -- 'Ship' | 'OnFoot'
    specialties JSONB NOT NULL DEFAULT '{}'::jsonb,
    permit_required TEXT,
    referral_from TEXT,
    unlock_requirement TEXT,
    max_grade INTEGER NOT NULL DEFAULT 5,
    region TEXT NOT NULL DEFAULT 'Core Bubble',
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (engineer_id)
);

-- Documentation
COMMENT ON TABLE engineers IS
  'Reference dataset for Horizons ship engineers and Odyssey on-foot engineers. '
  'Contains workshop base locations, system/body/market bindings, engineering disciplines, progression unlock requirements, and max modification grades. '
  'Sourced from static reference data (db_setup/data/engineers.yaml) for initial and slowly changing update deployments.';

COMMENT ON COLUMN engineers.system_id64 IS
  'Deterministic 64-bit galactic ID of the star system where the engineer resides. FK -> systems.id64.';

COMMENT ON COLUMN engineers.body_id64 IS
  'Deterministic 64-bit ID of the planetary body housing the surface workshop: (system_id64 << 9) | (bodyId & 0x1FF). FK -> bodies.id64.';

COMMENT ON COLUMN engineers.market_id IS
  'Frontier market/station ID of the engineer workshop base. FK -> stations.market_id.';

COMMENT ON COLUMN engineers.engineer_id IS
  'Frontier numeric identifier for the engineer (e.g. 300100 for Felicity Farseer). Primary key.';

COMMENT ON COLUMN engineers.name IS
  'Full name of the engineer (e.g. "Felicity Farseer", "Domino Green").';

COMMENT ON COLUMN engineers.engineer_type IS
  'Classification of modifications offered: "Ship" (Horizons) or "OnFoot" (Odyssey).';

COMMENT ON COLUMN engineers.specialties IS
  'JSONB key-value mapping of major and minor equipment categories to max engineering grade (e.g. {"major": {"frame_shift_drive": 5}, "minor": {"thrusters": 3}}).';

COMMENT ON COLUMN engineers.permit_required IS
  'System permit required to enter the workshop system (e.g. "Sirius", "Alioth", "Shinrarta Dezhra") or NULL if no permit required.';

COMMENT ON COLUMN engineers.referral_from IS
  'Preceding engineer who provides the referral/introduction or "Public" if known publicly from start.';

COMMENT ON COLUMN engineers.unlock_requirement IS
  'Requirements, commodities, or donations required to unlock engineering services (e.g. "1x Meta-Alloy", "25x Modular Terminals").';

COMMENT ON COLUMN engineers.max_grade IS
  'Maximum engineering modification grade available across all specialties (typically 5).';

COMMENT ON COLUMN engineers.region IS
  'Galactic region of the workshop: "Core Bubble", "Colonia", etc.';

COMMENT ON COLUMN engineers.update_dtm IS
  'UTC timestamp when this engineer record was last updated or seeded.';
