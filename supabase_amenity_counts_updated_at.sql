-- Existing Supabase projects may have amenity_counts without this timestamp.
-- The app sends updated_at with each successful OSM count upsert.
alter table public.amenity_counts
    add column if not exists updated_at timestamptz not null default now();
