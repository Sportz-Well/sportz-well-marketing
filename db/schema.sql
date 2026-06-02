-- Canonical schema for the Sportz-Well Marketing Studio — PostgreSQL (Supabase) edition.
-- db/init_db.py reads this file and applies it (idempotent — CREATE IF NOT EXISTS throughout).
-- JSON columns are stored as TEXT and parsed by the application layer.

-- ─── BRAND STRUCTURE ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS organizations (
    id            SERIAL  PRIMARY KEY,
    name          TEXT    NOT NULL UNIQUE,
    description   TEXT,
    website       TEXT,
    social_active INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS products (
    id               SERIAL  PRIMARY KEY,
    organization_id  INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name             TEXT    NOT NULL,
    full_name        TEXT,
    one_liner        TEXT,
    description      TEXT,
    website          TEXT,
    social_active    INTEGER NOT NULL DEFAULT 0,
    is_active_client INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS product_phases (
    id           SERIAL  PRIMARY KEY,
    product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    phase_number INTEGER NOT NULL,
    name         TEXT    NOT NULL,
    description  TEXT,
    focus        TEXT,
    status       TEXT    NOT NULL DEFAULT 'planned',
    activated_at TEXT,
    UNIQUE(product_id, phase_number)
);

CREATE TABLE IF NOT EXISTS brand_profiles (
    id           SERIAL  PRIMARY KEY,
    product_id   INTEGER NOT NULL UNIQUE REFERENCES products(id) ON DELETE CASCADE,
    profile_data TEXT    NOT NULL DEFAULT '{}',
    updated_at   TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS partner_brands (
    id               SERIAL  PRIMARY KEY,
    organization_id  INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name             TEXT    NOT NULL,
    category         TEXT,
    description      TEXT,
    website          TEXT,
    mention_guidance TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS content_rules (
    id          SERIAL  PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    rule_key    TEXT    NOT NULL,
    rule_value  TEXT    NOT NULL,
    description TEXT,
    created_at  TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    UNIQUE(product_id, rule_key)
);

-- ─── PIPELINE TABLES ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS research_items (
    id                    SERIAL  PRIMARY KEY,
    product_id            INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    topic                 TEXT,
    source_url            TEXT,
    title                 TEXT,
    source_title          TEXT,
    source_published_date TEXT,
    summary               TEXT,
    full_text             TEXT,
    relevance_score       INTEGER,
    relevance_reason      TEXT,
    url_status            TEXT    DEFAULT 'unchecked',
    final_url             TEXT,
    source_geography      TEXT,
    fetched_at            TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_research_items_product ON research_items(product_id);
CREATE INDEX IF NOT EXISTS idx_research_items_topic   ON research_items(topic);

CREATE TABLE IF NOT EXISTS api_log (
    id            SERIAL  PRIMARY KEY,
    timestamp     TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    agent         TEXT    NOT NULL,
    action        TEXT,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    web_searches  INTEGER NOT NULL DEFAULT 0,
    est_cost_usd  REAL    NOT NULL DEFAULT 0.0,
    notes         TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_log_timestamp ON api_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_api_log_agent     ON api_log(agent);

CREATE TABLE IF NOT EXISTS story_angles (
    id                  SERIAL  PRIMARY KEY,
    product_id          INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    title               TEXT    NOT NULL,
    angle               TEXT    NOT NULL,
    theme               TEXT,
    angle_title         TEXT,
    angle_description   TEXT,
    editorial_brief     TEXT,
    platform_fit        TEXT,
    phase_tag           TEXT,
    funnel_stage        TEXT,
    content_format      TEXT,
    cta_strength        TEXT,
    source_research_ids TEXT,
    proof_points_used   TEXT,
    status              TEXT    NOT NULL DEFAULT 'proposed',
    user_notes          TEXT,
    created_at          TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    updated_at          TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_story_angles_product ON story_angles(product_id);
CREATE INDEX IF NOT EXISTS idx_story_angles_status  ON story_angles(status);

CREATE TABLE IF NOT EXISTS drafts (
    id                  SERIAL  PRIMARY KEY,
    story_angle_id      INTEGER NOT NULL REFERENCES story_angles(id),
    product_id          INTEGER NOT NULL,
    platform            TEXT    NOT NULL,
    variant_number      INTEGER NOT NULL,
    content_format      TEXT    NOT NULL,
    headline            TEXT,
    body                TEXT    NOT NULL,
    cta_line            TEXT,
    hashtags            TEXT,
    carousel_slides     TEXT,
    reel_script         TEXT,
    image_brief         TEXT,
    proof_points_used   TEXT,
    word_count          INTEGER,
    char_count          INTEGER,
    status              TEXT    NOT NULL DEFAULT 'draft',
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    UNIQUE(story_angle_id, platform, variant_number)
);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);
CREATE INDEX IF NOT EXISTS idx_drafts_angle  ON drafts(story_angle_id);

CREATE TABLE IF NOT EXISTS editor_reviews (
    id                  SERIAL  PRIMARY KEY,
    draft_id            INTEGER NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    review_number       INTEGER NOT NULL,
    verdict             TEXT    NOT NULL CHECK (verdict IN ('clean', 'flagged', 'blocked')),
    issues_json         TEXT    NOT NULL,
    suggestions_json    TEXT    NOT NULL DEFAULT '[]',
    raw_model_response  TEXT,
    model_input_tokens  INTEGER NOT NULL,
    model_output_tokens INTEGER NOT NULL,
    cost_usd            REAL    NOT NULL,
    reviewed_at         TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_editor_reviews_draft_id     ON editor_reviews(draft_id);
CREATE INDEX IF NOT EXISTS idx_editor_reviews_draft_review ON editor_reviews(draft_id, review_number);

CREATE TABLE IF NOT EXISTS media_briefs (
    id                  SERIAL  PRIMARY KEY,
    draft_id            INTEGER NOT NULL UNIQUE REFERENCES drafts(id) ON DELETE CASCADE,
    product_id          INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    shot_type           TEXT    NOT NULL,
    subject             TEXT    NOT NULL,
    setting             TEXT    NOT NULL,
    time_of_day         TEXT    NOT NULL,
    lighting_mood       TEXT    NOT NULL,
    props               TEXT    NOT NULL DEFAULT '[]',
    composition_notes   TEXT    NOT NULL,
    color_palette       TEXT    NOT NULL DEFAULT '[]',
    wardrobe_notes      TEXT,
    do_not              TEXT    NOT NULL DEFAULT '[]',
    caption_sync_note   TEXT    NOT NULL,
    raw_model_response  TEXT,
    model_input_tokens  INTEGER NOT NULL DEFAULT 0,
    model_output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd            REAL    NOT NULL DEFAULT 0.0,
    status              TEXT    NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at          TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    updated_at          TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_media_briefs_product ON media_briefs(product_id);
CREATE INDEX IF NOT EXISTS idx_media_briefs_draft   ON media_briefs(draft_id);
CREATE INDEX IF NOT EXISTS idx_media_briefs_status  ON media_briefs(status);

CREATE TABLE IF NOT EXISTS schedule (
    id              SERIAL  PRIMARY KEY,
    draft_id        INTEGER NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    scheduled_for   TEXT    NOT NULL,
    posted_at       TEXT,
    posted_manually INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_schedule_scheduled_for ON schedule(scheduled_for);