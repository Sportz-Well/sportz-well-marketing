-- Canonical schema for the Sportz-Well Marketing Studio.
-- db/init_db.py reads this file to create data/app.db on first run.
-- JSON columns are stored as TEXT and parsed by the application layer.
-- IMPORTANT: After editing this file, run `python db/init_db.py` to apply.

PRAGMA foreign_keys = ON;

-- ─── BRAND STRUCTURE ────────────────────────────────────────────────────────

-- Parent company level. V1 has one row (Sportz-Well).
CREATE TABLE IF NOT EXISTS organizations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    description   TEXT,
    website       TEXT,
    social_active INTEGER NOT NULL DEFAULT 0,   -- 1 = active on social media
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Products owned by an organisation. V1 has one active client (SWPI).
-- Only one row should have is_active_client = 1 at a time.
CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id  INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name             TEXT    NOT NULL,           -- short name, e.g. "SWPI"
    full_name        TEXT,                       -- "Sportz-Well Performance Intelligence"
    one_liner        TEXT,                       -- ≤200 chars positioning statement
    description      TEXT,
    website          TEXT,
    social_active    INTEGER NOT NULL DEFAULT 0,
    is_active_client INTEGER NOT NULL DEFAULT 0, -- only one product active at a time
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Rollout phases for a product. SWPI has three (grassroots, multi-sport, IFT).
CREATE TABLE IF NOT EXISTS product_phases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    phase_number INTEGER NOT NULL,
    name         TEXT    NOT NULL,
    description  TEXT,
    focus        TEXT,                           -- one-line focus statement
    status       TEXT    NOT NULL DEFAULT 'planned',  -- planned | active | complete
    activated_at TEXT,
    UNIQUE(product_id, phase_number)
);

-- Full brand profile for a product, stored as a single JSON blob.
-- Keys: primary_buyer, secondary_buyer, end_user, geography,
--       voice_adjectives (list), tone_dos (list), tone_donts (list),
--       topics_owned (list), topics_avoided (list),
--       proof_points_regular (list), proof_points_sparing (list),
--       primary_cta, cta_url, sales_cycle_type
CREATE TABLE IF NOT EXISTS brand_profiles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   INTEGER NOT NULL UNIQUE REFERENCES products(id) ON DELETE CASCADE,
    profile_data TEXT    NOT NULL DEFAULT '{}',
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Partner brands Sportz-Well affiliates with. Empty in Phase 1.
CREATE TABLE IF NOT EXISTS partner_brands (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id  INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name             TEXT    NOT NULL,
    category         TEXT,
    description      TEXT,
    website          TEXT,
    mention_guidance TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Configurable rules per product.
-- Examples: vision_hint_frequency, vision_hint_instruction, cta_priority
CREATE TABLE IF NOT EXISTS content_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    rule_key    TEXT    NOT NULL,
    rule_value  TEXT    NOT NULL,
    description TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(product_id, rule_key)
);

-- ─── PIPELINE TABLES (wired up in later prompts) ────────────────────────────

-- Raw research the Researcher agent collects. Strategist reads from here.
CREATE TABLE IF NOT EXISTS research_items (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id           INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    topic                TEXT,
    source_url           TEXT,
    title                TEXT,                -- legacy column kept for compat
    source_title         TEXT,               -- preferred column name
    source_published_date TEXT,              -- nullable; YYYY-MM-DD when available
    summary              TEXT,
    full_text            TEXT,
    relevance_score      INTEGER,            -- 1-10, brand-fit score (auto-reduced 3pts if URL broken)
    relevance_reason     TEXT,              -- one-sentence explanation of score
    url_status           TEXT DEFAULT 'unchecked', -- ok | broken | redirected | timeout | unchecked
    final_url            TEXT,               -- URL after following redirects (may differ from source_url)
    source_geography     TEXT,               -- India | UK | Australia | USA | Global | Unknown
    fetched_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_research_items_product ON research_items(product_id);
CREATE INDEX IF NOT EXISTS idx_research_items_topic   ON research_items(topic);

-- API call log — every agent logs here for spend tracking.
-- CSV mirror at data/api_log.csv for user-facing visibility.
CREATE TABLE IF NOT EXISTS api_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL DEFAULT (datetime('now')),
    agent         TEXT    NOT NULL,      -- e.g. 'researcher', 'strategist'
    action        TEXT,                 -- topic or action description
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    web_searches  INTEGER NOT NULL DEFAULT 0,
    est_cost_usd  REAL    NOT NULL DEFAULT 0.0,
    notes         TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_log_timestamp ON api_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_api_log_agent     ON api_log(agent);

-- Story angles produced by the Strategist from one or more research items.
-- source_research_ids and proof_points_used are JSON arrays.
-- status: 'proposed' | 'approved' | 'rejected' | 'edited'
CREATE TABLE IF NOT EXISTS story_angles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    title               TEXT    NOT NULL,       -- legacy; mirrors angle_title
    angle               TEXT    NOT NULL,       -- legacy; mirrors angle_description
    theme               TEXT,                  -- cluster theme label
    angle_title         TEXT,                  -- short punchy title (≤10 words)
    angle_description   TEXT,                  -- 2-3 sentence post premise
    editorial_brief     TEXT,                  -- 1-paragraph brief for the Copywriter
    platform_fit        TEXT,                  -- 'instagram' | 'facebook' | 'both'
    phase_tag           TEXT,                  -- 'phase_1' | 'phase_2_hint' | 'phase_3_hint' | 'founder_credibility' | 'evergreen'
    funnel_stage        TEXT,                  -- 'awareness' | 'consideration' | 'demo_pitch'
    content_format      TEXT,                  -- 'single_image' | 'carousel' | 'video_script' | 'text_post' | 'reel_script'
    cta_strength        TEXT,                  -- 'hard_cta' | 'soft_cta' | 'no_cta'
    source_research_ids TEXT,                  -- JSON array of research_items.id
    proof_points_used   TEXT,                  -- JSON array of proof point strings
    status              TEXT    NOT NULL DEFAULT 'proposed',
    user_notes          TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_story_angles_product ON story_angles(product_id);
-- idx_story_angles_status is created by db/init_db.py migration after the status column exists

-- Platform-specific drafts produced by the Copywriter from a story angle.
-- hashtags, carousel_slides, reel_script, proof_points_used are JSON TEXT.
-- status: 'draft' | 'approved' | 'rejected' | 'edited'
CREATE TABLE IF NOT EXISTS drafts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    story_angle_id      INTEGER NOT NULL REFERENCES story_angles(id),
    product_id          INTEGER NOT NULL,
    platform            TEXT    NOT NULL,        -- 'instagram' | 'facebook'
    variant_number      INTEGER NOT NULL,        -- 1 or 2
    content_format      TEXT    NOT NULL,        -- single_image | carousel | text_post | reel_script | video_script
    headline            TEXT,                    -- opening hook line
    body                TEXT    NOT NULL,        -- full caption body
    cta_line            TEXT,                    -- null when cta_strength = 'no_cta'
    hashtags            TEXT,                    -- JSON array of strings
    carousel_slides     TEXT,                    -- JSON array of slide objects; null unless carousel
    reel_script         TEXT,                    -- JSON object; null unless reel_script
    image_brief         TEXT,                    -- 1-2 sentences for the Media agent
    proof_points_used   TEXT,                    -- JSON array; subset of angle's proof_points_used
    word_count          INTEGER,
    char_count          INTEGER,
    status              TEXT    NOT NULL DEFAULT 'draft',
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    UNIQUE(story_angle_id, platform, variant_number)
);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);
CREATE INDEX IF NOT EXISTS idx_drafts_angle  ON drafts(story_angle_id);

-- Editor reviews produced by the Editor agent for each Copywriter draft.
-- issues_json and suggestions_json are JSON arrays (see agents/editor.py for shapes).
-- verdict: 'clean' | 'flagged' | 'blocked' ('blocked' reserved for V2; V1 never emits it)
-- review_number increments per draft; old reviews are never deleted.
CREATE TABLE IF NOT EXISTS editor_reviews (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id            INTEGER NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    review_number       INTEGER NOT NULL,
    verdict             TEXT    NOT NULL CHECK (verdict IN ('clean', 'flagged', 'blocked')),
    issues_json         TEXT    NOT NULL,
    suggestions_json    TEXT    NOT NULL DEFAULT '[]',
    raw_model_response  TEXT,
    model_input_tokens  INTEGER NOT NULL,
    model_output_tokens INTEGER NOT NULL,
    cost_usd            REAL    NOT NULL,
    reviewed_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_editor_reviews_draft_id     ON editor_reviews(draft_id);
CREATE INDEX IF NOT EXISTS idx_editor_reviews_draft_review ON editor_reviews(draft_id, review_number);

-- Calendar entries owned by the Scheduler.
-- posted_manually = 1 in V1 (user copy-pastes into Meta Business Suite).
CREATE TABLE IF NOT EXISTS schedule (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id        INTEGER NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    scheduled_for   TEXT    NOT NULL,   -- ISO 8601 datetime
    posted_at       TEXT,               -- null until posted
    posted_manually INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_schedule_scheduled_for ON schedule(scheduled_for);
