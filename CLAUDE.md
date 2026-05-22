# CLAUDE.md

This file is the source of truth for anyone (including future Claude sessions) working on this codebase. Read it first.

## Product

A web app that helps a brand plan, draft, and schedule social media content.

- **First client:** Sportz-Well, an Indian sports performance brand.
- **Flagship product:** SWPI (Sportz-Well Performance Intelligence App).
- **V1 platforms:** Instagram and Facebook.
- **V1 posting model:** The app does **not** post automatically. It generates drafts, schedules them on an internal calendar, and the user copy-pastes into Meta Business Suite.
- **V2 (later):** Direct API posting via Meta Graph API, after Meta App Review.
- **Multi-tenant later:** V1 is single-client (Sportz-Well), but the schema already supports multiple clients — additional brands will be onboarded by adding rows, not by forking code.

## Stack

- **Language:** Python 3.11+
- **UI:** Streamlit (chosen because the product owner is non-technical and Streamlit is the fastest way to ship a working UI)
- **Database:** SQLite (file at `data/app.db`, created from `db/schema.sql`)
- **AI:** Anthropic Python SDK, wrapped in `services/anthropic_client.py`
- **Package management:** `uv` if available, otherwise `pip` + `requirements.txt`

## Architecture: one app, five agents

One app, one database, one UI. Inside, five specialized AI agents coordinate:

1. **Researcher** — gathers signals (news, trends, athlete content, science updates) relevant to the brand.
2. **Strategist** — turns research into story angles tied to brand positioning.
3. **Copywriter** — drafts platform-specific posts from story angles.
4. **Editor** — reviews drafts for voice, accuracy, and brand guardrails.
5. **Scheduler** — places approved drafts on the calendar.

Each agent is its own module under `agents/`. They share the database (handoff is via DB rows, not in-memory state) and share the Anthropic client wrapper in `services/`.

## Build conventions

- **One module per prompt.** We add agents and features incrementally. Don't pre-build agents or stub them — wait for the prompt that adds each one.
- **No hardcoded brand content.** Never put Sportz-Well's voice, USPs, positioning, "do not say" rules, or any brand-specific copy in Python files. Everything brand-specific lives in the `brand_profiles` table, keyed by client. Code reads the brand profile from the database at runtime.
- **Database is the handoff layer between agents.** Researcher writes to `research_items`, Strategist reads them and writes `story_angles`, Copywriter reads angles and writes `drafts`, etc.
- **Models:** Default to the latest Sonnet model ID (currently `claude-sonnet-4-6`) via the wrapper in `services/anthropic_client.py`. Don't hardcode model strings throughout the codebase.
- **Secrets:** API keys live only in `.env` (gitignored). `.env.example` documents what's needed.

## Repository layout

```
agents/      # one file per agent, added incrementally
db/
  schema.sql       # canonical schema — single source of truth
  init_db.py       # creates data/app.db; auto-migrates old Prompt-1 schema
ui/
  app.py           # Streamlit Home page
  pages/
    1_Brand_Brain.py     # Brand Brain module (four tabs)
    2_Research.py        # Research module (Prompt 3)
    3_Strategy.py        # Strategy module (Prompt 4)
    4_Drafts.py          # Drafts module (Prompt 5)
    5_Editor.py          # Editor module (Prompt 6)
    6_Media.py           # placeholder — Prompt 7
    7_Calendar.py        # placeholder — Prompt 8
    8_Orchestrator.py    # placeholder — Prompt 9
services/
  anthropic_client.py   # thin Anthropic SDK wrapper
  database.py           # shared SQLite connection helper (get_connection())
  brand_context.py      # brand context API — all agents use this
data/                   # local SQLite DB lives here (gitignored)
tests/                  # pytest-based tests; pytest.ini at root configures pythonpath
.env.example            # template — copy to .env, paste real key
requirements.txt
```

## Brand data model (Prompt 2)

Two-tier hierarchy — organisation owns products, products have phases:

- `organizations` — parent company (Sportz-Well). `social_active = 0` in Phase 1.
- `products` — the social-media-active entity (SWPI). `is_active_client = 1` for V1.
- `product_phases` — rollout plan. Phase 1 active; Phases 2 & 3 planned.
- `brand_profiles` — JSON blob per product. Keys: audience, voice, topics, proof points, CTA.
- `partner_brands` — affiliated brands to mention. Empty in Phase 1 but schema is ready.
- `content_rules` — configurable rules keyed by `rule_key`. Vision-hint quota lives here.

Pipeline tables (`research_items`, `story_angles`, `drafts`, `schedule`) use `product_id`
(renamed from Prompt-1's `client_id`) and are wired up in later prompts.

## Brand context API

`services/brand_context.py` is the **single source of truth** for all agents:

| Function | Returns |
|---|---|
| `get_active_product()` | Product + org + active phase dict, or None |
| `get_brand_profile(product_id)` | Parsed JSON dict (includes split proof-point lists) |
| `get_content_rules(product_id)` | `{rule_key: rule_value}` dict |
| `get_active_partner_brands(org_id)` | List of active partner brand dicts |
| `build_brand_context_prompt(product_id)` | Agent-ready system prompt fragment (str) |

**Every future agent MUST call `build_brand_context_prompt()` and inject it into its
Claude system prompt. Never hardcode brand content in agent code.**

## Current status

**Last updated:** 2026-05-21 (Copywriter tuning + empirical verification of CROSS_VARIANT_DUPLICATION fix)

- ✅ Project scaffold (Prompt 1): folders, `.gitignore`, `.env.example`, `requirements.txt`, `README.md`.
- ✅ `services/anthropic_client.py` — thin wrapper exposing `ask()`, `ask_with_usage()`, and `ask_with_web_search()`.
- ✅ Multi-page Streamlit app: `ui/app.py` is the Home page; `ui/pages/` holds all module pages.
- ✅ Two-tier brand schema: `organizations → products → product_phases`, plus `brand_profiles`, `partner_brands`, `content_rules`.
- ✅ `db/init_db.py` auto-detects and migrates the old Prompt-1 schema on first run.
- ✅ `services/database.py` — shared `get_connection()` helper.
- ✅ `services/brand_context.py` — full brand context API ready for all agents.
- ✅ Brand Brain page (`ui/pages/1_Brand_Brain.py`):
  - Tab A: read-only overview of org, product, phases, voice, rules, partners.
  - Tab B: edit form (all brand fields, saves atomically).
  - Tab C: partner brands table with add / edit / delete.
  - Tab D: one-button seed of Sportz-Well + SWPI with full Phase 1 profile.
- ✅ SWPI seeded with complete Phase 1 brand profile, 3 phases, and content rules including the vision-hint quota (`rare_1_in_20`).
- ✅ Vision-hint quota stored as `content_rules.rule_key = 'vision_hint_frequency'` — enforced by the Strategist agent.
- ✅ Researcher agent (`agents/researcher.py`) — first agent that calls the Anthropic API:
  - Reads brand context before searching; scores relevance 1–10 against SWPI owned/avoided topics.
  - Web search via `ask_with_web_search()` using `web_search_20250305` server-side tool.
  - Saves structured items to `research_items` (topic, source_title, source_published_date, summary, relevance_score, relevance_reason).
  - Every API call logged to `data/api_log.csv` AND `api_log` DB table for spend tracking.
- ✅ `research_items` table migrated: added `source_title`, `source_published_date`, `relevance_score`, `relevance_reason`.
- ✅ `api_log` table added: timestamp, agent, action, input_tokens, output_tokens, web_searches, est_cost_usd, notes.
- ✅ Research page (`ui/pages/2_Research.py`) — three tabs:
  - Tab A: cost warning + topic input + run button + recent topics.
  - Tab B: library with topic/score/sort filters, expander per item, two-click delete.
  - Tab C: month spend, all-time spend, agent breakdown, last 20 calls.
- ✅ Home page updated: "Recent Research" widget shows last 3 items; Research listed as ✅ Ready.
- ✅ Prompt 3.5 — Researcher tuning (four fixes):
  - **URL validation** (`services/url_validator.py`): HEAD→GET fallback, 5 concurrent workers; broken/timeout items saved but score auto-reduced 3pts; ⚠️ badge in UI
  - **Geography mix** (`GEOGRAPHY_OPTIONS` in researcher.py): Indian-heavy (3:2) default; 5 options surfaced as selectbox in Tab A; `source_geography` column on every item; 🌍 badge + filter in Tab B
  - **Quality threshold**: `min_relevance` param (default 7); model returns only items at/above threshold; rejection count + summary surfaced in success banner
  - **Source bias** (`services/source_preferences.py`): PREFERRED_DOMAINS (+1 tiebreaker) and DOWNRANK_DOMAINS (−2 penalty); soft nudges injected into system prompt; never a hard filter
  - All four controls tunable in the UI — no code changes needed to adjust behavior
- ✅ Prompt 4 — Strategist agent (`agents/strategist.py`):
  - Reads all eligible research_items (filtered by min_relevance, default 7) for the active product.
  - Calls Anthropic API (pure reasoning, no web search) via `ask_with_usage()`.
  - Clusters research into 2–5 themes; proposes 2–4 story angles per theme.
  - Vision-hint quota enforced: ≤ 1 in 20 angles may use phase_2_hint or phase_3_hint; excess capped with warnings.
  - Sparing proof-point quota enforced: ≤ 1 in 10 angles; excess stripped with warnings.
  - CTA distribution target: ~20% hard_cta, ~40% soft_cta, ~40% no_cta (model-side, with UI sanity check).
  - Each angle tagged: platform_fit, phase_tag, funnel_stage, content_format, cta_strength, source_research_ids, proof_points_used.
  - JSON parsed robustly: strips markdown fences, removes trailing commas, falls back to clean error.
  - Saves to `story_angles` table with status=proposed. Logs spend to api_log.
- ✅ `story_angles` table fully extended with 13 new columns (migrated by `db/init_db.py`).
- ✅ Strategy page (`ui/pages/3_Strategy.py`) — three tabs:
  - Tab A: research-items-available counter (live), min relevance + max angles sliders, optional focus input, run button.
  - Tab B: angles grouped by theme; filters by status/platform/phase/funnel; Approve/Reject/Edit buttons; inline edit form; Sources and Editorial Brief expanders.
  - Tab C: pipeline counts by status, platform breakdown, phase-tag distribution with quota check, CTA distribution with overload warning.
- ✅ Home page: "Approved angles ready for drafting" widget added; Strategy listed as ✅ Ready.
- ✅ Prompt 5 — Copywriter agent + Drafts page (documentation thin — agent module not deeply reviewed yet):
  - `agents/copywriter.py` — generates platform-specific drafts from approved story angles.
  - Public API observed via `ui/pages/4_Drafts.py` imports: `count_draft_stats`,
    `get_angle_draft_coverage`, `get_approved_angles`, `get_drafts_library`,
    `update_draft_content`, `update_draft_status`, `write_drafts_for_all_approved`,
    `write_drafts_for_angle`.
  - `drafts` table populated; as of 2026-05-21 contains 8 active draft rows (IDs 13–20 —
    earlier IDs 1–12 superseded by today's regeneration work; do not assume sequential IDs).
  - Drafts page (`ui/pages/4_Drafts.py`) — three tabs:
    - Tab 1 (Generate Drafts): live counters for approved / drafted / waiting angles;
      "Generate ALL waiting angles" button + "Generate for single angle" picker; regenerate
      checkbox to overwrite existing drafts.
    - Tab 2 (Drafts Library): status / platform / angle filters; grouped by angle; per-draft
      card with headline, body (read-only text area), CTA, hashtags, carousel slides expander,
      reel script expander, image brief; Approve / Reject / Edit action row with inline edit form.
    - Tab 3 (Pipeline Overview): status breakdown (draft/approved/rejected/edited), platform
      split, per-angle coverage progress bar with target of 2 drafts/platform (4 if "both").
  - Cost note in UI: ~₹4–10 per angle (2 variants per target platform, single API call).
  - **Detailed agent internals (prompt strategy, quota handling, edge cases) not yet documented
    in this file** — flesh out in a future session.
- ✅ Editor agent (`agents/editor.py`) — fourth agent in the pipeline:
  - V1 flag-only: identifies issues against an explicit ruleset, never rewrites or suggests
    replacement text. `suggestions_json` always stored as `'[]'`.
  - Reads draft + source angle + sibling variants; constructs a single JSON payload as the user
    message. NULL or unparseable `hashtags` raises a hard error rather than masking it (would
    manufacture a false `HASHTAG_COUNT_LOW` flag).
  - Public API: `review_draft(draft_id)` returns the latest cached review for free if one
    exists, else hits the API. `rereview_draft(draft_id)` always hits the API and inserts a
    new review row with `review_number = previous_max + 1`.
  - 10 checks total: 8 hard (HYPE_WORD, URL_FORMAT, CAPTION_TOO_LONG/SHORT, HASHTAG_COUNT_LOW/HIGH,
    PROOF_POINT_LINEAGE_DRIFT, HINGLISH_UNCALLED, MISSING_REQUIRED_FIELD, CROSS_VARIANT_DUPLICATION)
    and 2 soft (GENERIC_HOOK, WEAK_CTA_BUILDUP). Issue schema: code, severity, field, evidence,
    message. Verdict computed in Python (clean if no issues, flagged otherwise) — never trusted
    from the model.
  - Atomic `review_number` allocation: MAX query + INSERT in the same connection to avoid races.
  - Robust JSON parser with 4 strategies; Strategy 4 uses `re.finditer(r'\{[\s\r\n]*"issues"')`
    plus `JSONDecoder.raw_decode` to handle the model self-correction pattern (two JSON blocks
    with reasoning prose between).
  - Issue validation: enforces required keys (code/severity/field/evidence/message), validates
    severity ∈ {hard, soft}, validates field ∈ {hook, body, cta_line, hashtags, image_brief,
    headline, overall}. Dropped issues are logged to `data/editor_failed_responses.log` and
    printed to stderr — nothing silently discarded.
  - `editor_reviews` schema: `UNIQUE(draft_id, review_number)` enforced via table-recreation
    migration (SQLite does not support ALTER TABLE ADD CONSTRAINT).
  - Operational tooling: `scripts/recover_editor_log.py` parses
    `data/editor_failed_responses.log` and reconstructs reviews from logged raw responses;
    imports `_parse_editor_json` and `_validate_issues` directly from `agents/editor.py`
    (no copy-paste duplication).
  - Parser smoke tests persisted: 18 tests in `tests/test_editor_parser.py`, all passing.
    `pytest.ini` configured at project root with `pythonpath = .` so tests can import
    `agents.editor` cleanly.
  - System prompt preventive fix shipped: one-line "Output your final JSON once — no revisions,
    no prose" instruction added to stop self-correction prose at the source. Parser Strategy 4
    remains as belt-and-braces.
- ✅ Editor UI page (`ui/pages/5_Editor.py`) — Prompt 6 UI integration, shipped 2026-05-20:
  - Three tabs matching the Strategy precedent.
  - **Tab A (Review Draft):** draft picker (unreviewed-first sort), status banner showing
    review count and latest verdict, two-button pattern:
    `Review (cached if exists)` calls `review_draft()` and is free for already-reviewed drafts;
    `Re-review (force new API call)` calls `rereview_draft()` and always hits the API
    (~$0.03 per call). Issues rendered as red/yellow-bordered cards grouped by severity.
  - **Tab B (Reviews Library):** four filters (verdict, platform, issues, sort); one expander
    per draft showing the latest review's issues inline; nested `📜 Full review history`
    sub-expander shows every review in chronological order with verdict, timestamp, cost, and
    full issue list (audit trail built-in). Per-draft Re-review button.
  - **Tab C (Pipeline Overview):** review coverage (total / reviewed / unreviewed / total
    reviews), verdict distribution with clean-rate percentage, issue severity breakdown,
    top-10 issue codes ranked by frequency, drafts-re-reviewed warning, and Editor spend
    ticker (today / this month / all time / total calls / average cost per call / recent
    20 Editor calls expander with per-call status and notes).
  - Three new public helpers added to `agents/editor.py` for UI/dashboard consumption:
    `get_last_run_info(product_id)`, `count_unreviewed_drafts(product_id)`,
    `count_reviews_total(product_id)`. Pattern matches Strategy: small counters in the agent
    module (Home page can consume them later); bigger presentation queries stay as `_`
    private helpers in the UI page.
- ✅ Home page (`ui/app.py`) updated 2026-05-20: Drafts and Editor now listed as ✅ Ready;
  Media / Calendar / Orchestrator still ⏭ Prompt 7/8/9.

### Prompt 5.5 — Copywriter tuning (2026-05-21): CROSS_VARIANT_DUPLICATION eliminated ✅

**Problem statement (yesterday's signal):** Editor's Pipeline Overview showed 6 of 13 hard
issues (46%) were `CROSS_VARIANT_DUPLICATION`. The Copywriter was generating IG and FB variants
with byte-identical or near-paraphrase hooks.

**Root cause analysis:** Four contributing factors identified.
  1. All variants (up to 4 for platform_fit=both) generated in a single API call → the model
     anchors on its first hook while writing subsequent ones, even with abstract differentiation
     instructions in the prompt.
  2. The original "Variant Differentiation" prompt section was a soft suggestion with no
     forcing function. The model could claim it differentiated when it didn't.
  3. No structural enforcement — no JSON field requiring the model to *declare* its
     differentiation strategy.
  4. Sibling drafts weren't shown to the model as concrete reference points to differ from.

**Fix (took 3 iterations, all committed):**

  1. **Commit `3864570` — Differentiation rules + declarations** (`agents/copywriter.py`):
     Rewrote the "Variant Differentiation" section as a hard rule. Two new required JSON
     fields per draft: `hook_strategy` (one of `question_hook` | `scenario_hook` |
     `statement_hook` | `story_hook` | `framework_hook`) and `perspective_focus` (one of
     `coach_pov` | `parent_pov` | `player_pov` | `academy_pov`). Python validates that
     sibling variants on the same platform declare different values for both fields.
     Cross-platform soft warning if any (hook, perspective) combination repeats across all
     4 drafts. Declaration fields are validation-only — dropped before persistence,
     no DB schema change.

  2. **Commit `76e2f03` — JSON parse failure root-caused and fixed**: First test
     generation after fix 1 returned valid JSON but failed to parse. Diagnostic script
     (`scripts/_diagnose_copywriter_parse.py`, since deleted per convention) pinpointed
     the issue: model wrote literal unescaped double-quote characters inside body string
     values (e.g., `"He's doing well"` inside a body field). Fix: explicit ban on double
     quotes inside any JSON string field, with named alternatives — single quotes for
     dialogue, em-dash framing for emphasis. Stripped instructional double quotes from
     the prompt's own examples to prevent pattern-mimicking.

  3. **Parser Strategy 4 ported from Editor** (also in `76e2f03`): Added
     `re.finditer(r'\{[\s\r\n]*"drafts"')` + `JSONDecoder.raw_decode()` as a 4th parsing
     strategy, mirroring the Editor's robust parser. Belt-and-braces in case the
     double-quote ban ever leaks.

**Empirical verification — 8 newly-generated drafts regenerated 2026-05-21:**

| Draft  | Angle               | Verdict     | Hard issues |
|--------|---------------------|-------------|-------------|
| #13 IG V1 | 1 (WhatsApp)     | 🚩 Flagged  | 1 (CAPTION_TOO_LONG by 4 words) |
| #14 IG V2 | 1 (WhatsApp)     | ✅ Clean    | 0 |
| #15 FB V1 | 1 (WhatsApp)     | ✅ Clean    | 0 |
| #16 FB V2 | 1 (WhatsApp)     | ✅ Clean    | 0 |
| #17 FB V1 | 7 (KIRTI)        | ✅ Clean    | 0 |
| #18 FB V2 | 7 (KIRTI)        | ✅ Clean    | 0 |
| #19 IG V1 | 10 (Achrekar)    | 🚩 Flagged  | 2 (PROOF_POINT_LINEAGE_DRIFT + HINGLISH_UNCALLED "maidan") |
| #20 IG V2 | 10 (Achrekar)    | 🚩 Flagged  | 1 (PROOF_POINT_LINEAGE_DRIFT) |

**Results vs. baseline (pre-fix pipeline-wide):**
- CROSS_VARIANT_DUPLICATION: **0 / 4 hard issues (0%)** ← previously 6 / 13 (46%)
- Clean rate: **5 / 8 drafts (63%)** ← previously 1 / 8 (12%)
- Total cost for the patch + verification: ~$0.35 (3 regenerations + 8 Editor reviews + 1 failed call)

**The Copywriter patch is fully validated.** Both within-platform AND cross-platform
differentiation now work — all 4 drafts on angle 1 used 4 distinct (hook_strategy,
perspective_focus) combinations.

Every future prompt should end by updating this section.

## Key signals for next session

**Signal 1 — Angle 10 has a content problem, not a Copywriter problem.**
Both Instagram V1 and V2 of angle 10 (Achrekar / Structured Development) violated
PROOF_POINT_LINEAGE_DRIFT with phrases like "Our founder trained inside that culture."
Three regenerations (yesterday + today V1 + today V2) all produced personal-lineage
claims about the founder. The Copywriter system prompt already has the institutional-only
rule. The root cause is almost certainly in angle 10's `editorial_brief` or
`proof_points_used` field in `story_angles` — those are pulling the model toward the
violation. **Fix is in Strategy page (edit the angle), not in `agents/copywriter.py`.**
Cheap, fast, no API cost. Verify by regenerating angle 10's drafts after the angle edit.

**Signal 2 — HINGLISH_UNCALLED surfaced.** Draft #19 used "maidan" without the angle's
editorial brief explicitly allowing it. Editor caught correctly. Low frequency (1/8 drafts),
isolated to one draft on angle 10. Monitor — don't act yet.

## TODOs and known minor issues

- **Drafts page: timestamp display on each draft card** — user requested 2026-05-20 and
  again 2026-05-21. Currently shows draft body, hashtags, image brief, action buttons —
  no `created_at` or `updated_at` visible. Data exists in DB. UI gap. Small fix (~15 min
  in `ui/pages/4_Drafts.py`).
- **Drafts agent documentation thin:** The Prompt 5 section above lists what's visible
  through imports and UI behaviour. A future session should review `agents/copywriter.py`
  directly and document the prompt strategy, quota handling, and edge cases — especially
  now that the system prompt has grown substantially with Prompt 5.5 additions.
- **Drop redundant index:** `idx_editor_reviews_draft_review` on `(draft_id, review_number)`
  is redundant with the `sqlite_autoindex` created by the new `UNIQUE` constraint. Drop it
  in a future schema cleanup pass.
- **`batch_review_remaining.py` implicit retry behaviour:** `review_draft()` returns a cached
  review if one already exists, so re-running on already-reviewed drafts is safe. On *new*
  drafts with prior failures it silently re-triggers the API. Investigate or add a
  `force=False` guard before next batch use.
- **Home page widget for unreviewed drafts:** `count_unreviewed_drafts(product_id)` now
  exists in `agents/editor.py` but is not yet consumed by the Home page. Small UX
  improvement, low priority.
- **Editor reviews for old drafts #1–12 are now orphan rows** — the old drafts were deleted
  by today's regeneration. Reviews still in `editor_reviews` table; harmless but slightly
  noisy in Pipeline Overview's all-time issue-code histogram. Cleanup can wait for a future
  schema-cleanup pass.

## Next steps (2026-05-22 onwards)

**Priority 1: Fix angle 10's editorial brief to eliminate PROOF_POINT_LINEAGE_DRIFT.**

This is a 15-minute, $0 fix in the Strategy page UI. Open angle 10 in the Story Angles
Library, edit the `editorial_brief` and/or `proof_points_used` field to remove anything
that's pulling the model toward personal-lineage framing of the founder. Then regenerate
angle 10's drafts via Drafts page and re-review with Editor. Success criterion: PROOF_POINT_LINEAGE_DRIFT
drops to 0 on the new drafts.

**Priority 2: Prompt 7 — Media agent + Media page.**

Build the Media agent that takes draft `image_brief` fields as input and produces structured
media suggestions for each draft. ~2-3 hour session of plan-and-paste. Follow the same pattern
established by the Researcher/Strategist/Copywriter/Editor agents:

  - `agents/media.py` with public API matching the precedent
  - `ui/pages/6_Media.py` with three tabs (Run / Library / Pipeline Overview)
  - api_log integration for spend tracking
  - Failed-response logging
  - Match Editor's robust JSON parser (4 strategies)

**Secondary backlog (do these between/around Prompts 7-9):**
- Drafts page timestamp display (see TODO above) — 15 min UX win, user has flagged twice.
- Document the Copywriter agent's internals in CLAUDE.md (currently thin) — Prompt 5.5
  added substantial system-prompt content that deserves explicit documentation.
- Prompt 8 — Scheduler agent + Calendar page.
- Prompt 9 — Orchestrator page (run full pipeline end-to-end with one click).
- Home page widget: "Drafts awaiting review" using `count_unreviewed_drafts()`.
- Drop the redundant `idx_editor_reviews_draft_review` index.

## Budget

- **2026-05-18:** ~₹10 net (₹16 gross across 7 API calls; ~₹6 recovered by parsing the
  two failed responses from the log and inserting reviews manually rather than re-running
  the API).
- **2026-05-20:** ~$0.03 (one Re-review test of draft #1 during Editor UI smoke-test).
- **2026-05-21 (Prompt 5.5):** ~$0.35 total across the day:
  - First failed regeneration of angle 1 (JSON parse failure): ~$0.05
  - Second successful regeneration of angle 1 (4 drafts): ~$0.10
  - Regeneration of angle 7 (2 drafts): ~$0.05
  - Regeneration of angle 10 (2 drafts): ~$0.05
  - Editor reviews of drafts #13–20: ~$0.21 total ($0.0224 + $0.0273 + $0.0230 + $0.0212
    + $0.0209 + $0.0208 + $0.0266 + $0.0297)
- **Editor agent all-time (as of 2026-05-21):** ~$0.52 across ~19 calls. Average cost
  per call: ~$0.0274. Visible in Editor → Pipeline Overview → Editor spend section.