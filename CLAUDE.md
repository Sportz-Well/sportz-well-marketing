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

**Last updated:** 2026-05-22 (Angle 10 fix + UX cleanup session)

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
- ✅ Prompt 5 — Copywriter agent + Drafts page:
  - `agents/copywriter.py` — generates platform-specific drafts from approved story angles.
  - Public API: `count_draft_stats`, `get_angle_draft_coverage`, `get_approved_angles`,
    `get_drafts_library`, `update_draft_content`, `update_draft_status`,
    `write_drafts_for_all_approved`, `write_drafts_for_angle`.
  - `drafts` table populated. Do not assume sequential IDs — regeneration creates new rows.
  - Drafts page (`ui/pages/4_Drafts.py`) — three tabs:
    - Tab 1 (Generate Drafts): live counters; "Generate ALL" + single-angle picker; regenerate checkbox.
    - Tab 2 (Drafts Library): filters by status/platform/angle; grouped by angle; per-draft card
      with headline, body, CTA, hashtags, carousel, reel script, image brief, timestamps; Approve/Reject/Edit.
    - Tab 3 (Pipeline Overview): status breakdown, platform split, per-angle coverage progress bar.
  - Cost note in UI: ~₹4–10 per angle (2 variants per target platform, single API call).
- ✅ Editor agent (`agents/editor.py`) — fourth agent in the pipeline:
  - V1 flag-only: identifies issues against an explicit ruleset, never rewrites.
  - 10 checks: 8 hard (HYPE_WORD, URL_FORMAT, CAPTION_TOO_LONG/SHORT, HASHTAG_COUNT_LOW/HIGH,
    PROOF_POINT_LINEAGE_DRIFT, HINGLISH_UNCALLED, MISSING_REQUIRED_FIELD, CROSS_VARIANT_DUPLICATION)
    and 2 soft (GENERIC_HOOK, WEAK_CTA_BUILDUP).
  - Robust JSON parser with 4 strategies; Strategy 4 uses raw_decode for self-correction pattern.
  - Public API: `review_draft()`, `rereview_draft()`, `get_last_run_info()`,
    `count_unreviewed_drafts()`, `count_reviews_total()`.
  - Parser smoke tests: 18 tests in `tests/test_editor_parser.py`, all passing.
- ✅ Editor UI page (`ui/pages/5_Editor.py`) — three tabs (Review / Library / Pipeline Overview).
- ✅ Prompt 5.5 — Copywriter tuning (see dedicated section below).
- ✅ Angle 10 content fix (2026-05-22) — see dedicated section below.
- ✅ UX improvements (2026-05-22):
  - Draft cards now show `created_at` and `updated_at` timestamps (`ui/pages/4_Drafts.py`).
  - Home page now shows "N drafts awaiting Editor review" warning widget using
    `count_unreviewed_drafts()` from `agents/editor.py`.
- ✅ DB cleanup (2026-05-22): dropped redundant index `idx_editor_reviews_draft_review`
  (redundant with `sqlite_autoindex` created by the `UNIQUE(draft_id, review_number)` constraint).

---

### Prompt 5.5 — Copywriter tuning (2026-05-21): CROSS_VARIANT_DUPLICATION eliminated ✅

**Problem statement:** Editor's Pipeline Overview showed 6 of 13 hard issues (46%) were
`CROSS_VARIANT_DUPLICATION`. The Copywriter was generating IG and FB variants with
byte-identical or near-paraphrase hooks.

**Root cause analysis:** Four contributing factors identified.
  1. All variants generated in a single API call → model anchors on first hook.
  2. Soft differentiation suggestion with no forcing function.
  3. No structural enforcement — no JSON field requiring declared differentiation strategy.
  4. Sibling drafts not shown as reference points.

**Fix (3 iterations, all committed):**

  1. **Commit `3864570`:** Two new required JSON fields per draft: `hook_strategy`
     (question_hook | scenario_hook | statement_hook | story_hook | framework_hook) and
     `perspective_focus` (coach_pov | parent_pov | player_pov | academy_pov). Python
     validates sibling variants on same platform declare different values for both.
     Declaration fields are validation-only — dropped before persistence, no DB schema change.

  2. **Commit `76e2f03`:** Banned literal unescaped double-quote characters inside body
     string values (root cause of parse failures). Named alternatives: single quotes for
     dialogue, em-dash for emphasis. Parser Strategy 4 ported from Editor as belt-and-braces.

**Empirical result (8 drafts):**
- CROSS_VARIANT_DUPLICATION: 0/4 hard issues (0%) ← was 6/13 (46%)
- Clean rate: 5/8 drafts (63%) ← was 1/8 (12%)

---

### Angle 10 content fix (2026-05-22): PROOF_POINT_LINEAGE_DRIFT eliminated ✅

**Problem statement:** All draft attempts for angle 10 ("What the Achrekar Academy Taught
About Structured Development") were flagged for PROOF_POINT_LINEAGE_DRIFT. The model kept
writing phrases like "Our founder trained in that environment" or "SWPI was designed from
within that same philosophy."

**Root cause:** Three problems in angle 10's `story_angles` data (not in agent code):
  1. `angle_description` contained "The founder trained in that environment." — treated as
     a fact to honour.
  2. `proof_points_used` was a personal-lineage statement formatted as a proof point:
     "Founder trained at Shardashram under Ramakant Achrekar alongside Sachin Tendulkar".
  3. `editorial_brief` said "philosophical, not name-dropping" but proof point contradicted it.

**Fix (all data edits via Strategy page UI + one-shot scripts, $0 API cost):**
  1. Deleted "The founder trained in that environment." sentence from `angle_description`.
  2. Replaced `proof_points_used` with: "Structured, documented, evidence-based coaching
     methodology — where every session has a purpose and every correction has a record."
  3. Added two hard rules to `editorial_brief`:
     - "Hard rule: do not state or imply that the founder personally trained at Shardashram
       or with Achrekar. Frame all Shardashram/Achrekar references as institutional history."
     - "Hard rule: do not write any sentence that frames SWPI as designed from, built upon,
       or inspired by the Shardashram philosophy. SWPI's methodology stands on its own."

**Result:** Both new drafts (#25, #26) passed Editor with 0 hard, 0 soft issues. ✅

---

## Copywriter agent internals (`agents/copywriter.py`)

**Note:** This section documents the agent as of Prompt 5.5. Review the source file if
behaviour has changed since.

### System prompt structure

The Copywriter system prompt has four main sections injected at runtime:

1. **Brand context block** — injected via `build_brand_context_prompt(product_id)`.
   Contains voice, proof points, do/don't rules, CTA guidance. Never hardcoded.

2. **Platform rules block** — per-platform word limits, hashtag counts, format constraints:
   - Instagram single_image: 150–220 words body, 8–15 hashtags
   - Facebook: 80–150 words body, 3–5 hashtags
   - Carousel and Reel formats have their own structural requirements.

3. **Variant differentiation rules** (added Prompt 5.5):
   - Hard rule: sibling variants on the same platform MUST declare different `hook_strategy`
     AND different `perspective_focus`.
   - Five hook strategies: question_hook, scenario_hook, statement_hook, story_hook, framework_hook.
   - Four perspective focuses: coach_pov, parent_pov, player_pov, academy_pov.
   - Cross-platform soft warning if any (hook, perspective) combination repeats across all 4 drafts.

4. **JSON format rules** (added Prompt 5.5):
   - Explicit ban on double-quote characters inside string field values.
   - Named alternatives: single quotes for dialogue, em-dash (—) for emphasis.
   - "Output your final JSON once — no revisions, no prose" to prevent self-correction pattern.

### JSON output schema (per draft)

```json
{
  "drafts": [
    {
      "platform": "instagram",
      "variant_number": 1,
      "hook_strategy": "statement_hook",
      "perspective_focus": "coach_pov",
      "headline": "...",
      "body": "...",
      "cta_line": "...",
      "hashtags": ["#tag1", "#tag2"],
      "image_brief": "...",
      "carousel_slides": null,
      "reel_script": null
    }
  ]
}
```

`hook_strategy` and `perspective_focus` are validated in Python then dropped before DB insert.
`carousel_slides` and `reel_script` are null for single_image format; populated for their
respective formats.

### Robust JSON parser (4 strategies)

  1. Direct `json.loads()` on the raw response.
  2. Strip markdown fences (` ```json ` / ` ``` `) then `json.loads()`.
  3. Remove trailing commas before `]` or `}`, then `json.loads()`.
  4. `re.finditer(r'\{[\s\r\n]*"drafts"')` + `JSONDecoder.raw_decode()` — handles the
     model self-correction pattern (two JSON blocks with reasoning prose between them).

### Variant differentiation validation

After parsing, Python checks:
- For each platform: all variants must have distinct `hook_strategy` values.
- For each platform: all variants must have distinct `perspective_focus` values.
- Violation → hard error returned; drafts NOT saved; caller sees an error message.
- Cross-platform: soft warning (logged, not blocking) if any (hook, perspective) pair repeats
  across all drafts.

### Spend tracking

Every call logged to both `data/api_log.csv` and `api_log` DB table with
`agent = 'copywriter'`. Visible in Drafts page Tab 3 and Editor spend section.

---

## TODOs and known minor issues

- **Drafts agent documentation** — now documented above. ✅
- **Drafts page timestamps** — now showing on draft cards. ✅
- **Home page unreviewed drafts widget** — now live. ✅
- **Drop redundant index** — done. ✅
- **`batch_review_remaining.py` implicit retry behaviour:** `review_draft()` returns a cached
  review if one already exists, so re-running on already-reviewed drafts is safe. On *new*
  drafts with prior failures it silently re-triggers the API. Investigate or add a
  `force=False` guard before next batch use.
- **Editor reviews for old drafts #1–12 are orphan rows** — the old drafts were deleted by
  regeneration. Reviews still in `editor_reviews` table; harmless but slightly noisy in
  Pipeline Overview's all-time issue-code histogram. Cleanup can wait.
- **HINGLISH_UNCALLED monitor:** Draft #19 used "maidan" without the angle's editorial brief
  explicitly allowing it. Editor caught correctly. Low frequency (1 instance), isolated.
  Monitor — don't act yet.

## Next steps (2026-05-22 onwards)

**Priority 1: Prompt 7 — Media agent + Media page (~2-3 hour session)**

Build the Media agent that takes draft `image_brief` fields as input and produces structured
media suggestions for each draft. Follow the same pattern as previous agents:

  - `agents/media.py` with public API matching the precedent
  - `ui/pages/6_Media.py` with three tabs (Run / Library / Pipeline Overview)
  - api_log integration for spend tracking
  - Failed-response logging
  - Match Editor's robust JSON parser (4 strategies)

**Priority 2: Prompt 8 — Scheduler agent + Calendar page (~2-3 hour session)**

Places approved drafts on an internal content calendar. V1 is internal only — no Meta API.

**Priority 3: Prompt 9 — Orchestrator page (~3-5 hour session)**

One-click full pipeline: Research → Strategy → Drafts → Editor → Schedule.

## Budget

- **2026-05-18:** ~₹10 net
- **2026-05-20:** ~$0.03
- **2026-05-21 (Prompt 5.5):** ~$0.35
- **2026-05-22 (Angle 10 fix + UX cleanup):** ~$0.10 (Editor re-reviews during angle 10
  fix iterations: ~$0.023 × 4 reviews = ~$0.09; no API cost for data edits or UX changes)
- **Editor agent all-time (as of 2026-05-22):** ~$0.62 across ~23 calls.
  Average cost per call: ~$0.027.
- **Total all-time: ~$1.00**