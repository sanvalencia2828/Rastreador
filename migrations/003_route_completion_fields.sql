-- Fields required when a planned route is started and completed.

ALTER TABLE routes ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
ALTER TABLE visits ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'mobile';
