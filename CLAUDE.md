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

**Last updated:** 2026-05-20 (Prompt 6 UI integration + spend ticker)

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
  - `drafts` table populated; 8 drafts exist in DB (IDs 1, 2, 3, 4, 5, 6, 11, 12 — IDs 7–10
    do not exist, gap from prior deletions; do not assume sequential IDs).
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
  - All 8 drafts reviewed: 7 flagged, 1 clean (draft #11, Kirti FB V1 — first clean draft in
    the system).
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
  - Smoke-tested end-to-end on 2026-05-20: cached-review path returns free instantly; live
    Re-review of draft #1 produced Review #3 at $0.0302 and surfaced a new `HASHTAG_COUNT_HIGH`
    issue (`#mumbaicricket` duplicate at indexes 2 and 6) that the previous two reviews missed.
    Re-reviews can produce genuine new findings — not purely defensive.
- ✅ Home page (`ui/app.py`) updated 2026-05-20: Drafts and Editor now listed as ✅ Ready;
  Media / Calendar / Orchestrator still ⏭ Prompt 7/8/9.

Every future prompt should end by updating this section.

## Key signal for next session

**`CROSS_VARIANT_DUPLICATION` is the #1 issue code** — 6 occurrences across 13 hard issues
flagged by the Editor so far (46%). The Copywriter is generating Instagram and Facebook
variants of the same story angle with hooks that are byte-identical or near-identical
paraphrases. This is the systemic gap the Editor was built to expose. Surfaced in the
Editor's Pipeline Overview tab on 2026-05-20.

## TODOs and known minor issues

- **Drafts agent documentation thin:** The Prompt 5 section above lists what's visible
  through imports and UI behaviour. A future session should review `agents/copywriter.py`
  directly and document the prompt strategy, quota handling, and edge cases.
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

## Next steps (2026-05-21 onwards)

**Priority: Copywriter tuning to address `CROSS_VARIANT_DUPLICATION`.**

The Editor's Pipeline Overview surfaced a clear signal: 6 of 13 hard issues are
`CROSS_VARIANT_DUPLICATION`. The Copywriter is generating Instagram and Facebook variants
of the same story angle with hooks that are byte-identical or near-identical paraphrases.
This is exactly the systemic gap the Editor was built to expose.

1. **Investigate root cause** (~30 min) — Read `agents/copywriter.py` and the system prompt.
   Determine whether duplication is a prompt issue (no explicit "vary the hook meaningfully
   between variants" instruction) or a structural issue (e.g., both variants generated in the
   same API call sharing context).

2. **Patch the Copywriter** (~45 min) — Add explicit variant-differentiation rules to the
   system prompt. Likely something like: "Each variant must lead with a different angle —
   different hook noun, different opening verb, different rhetorical mode (question vs.
   statement vs. story-opener). Variants on different platforms should differ further in
   length, hashtag mix, and tone."

3. **Regenerate one angle's drafts and verify** (~30 min) — Pick one approved angle that
   currently has duplicated variants, regenerate its drafts with the patched Copywriter,
   run the Editor on the new drafts. If `CROSS_VARIANT_DUPLICATION` count drops to zero for
   that angle, the fix works.

4. **Decide on backfill strategy** — Either regenerate all existing drafts (clean slate,
   throws away $X of past work) or accept that historical drafts have the issue but new ones
   won't (cheaper, but pipeline overview metrics stay noisy for a while).

**Secondary, when Copywriter tuning is done:**
- Continue to Prompt 7 (Media agent) or Prompt 8 (Scheduler), whichever provides more
  end-to-end value.
- Home page widget: "Drafts awaiting review" using `count_unreviewed_drafts()` — small UX
  improvement, low priority.
- Drop the redundant `idx_editor_reviews_draft_review` index in a future schema cleanup pass.
- Document the Copywriter agent's internals in CLAUDE.md (currently thin).

## Budget

- **2026-05-18:** ~₹10 net (₹16 gross across 7 API calls; ~₹6 recovered by parsing the
  two failed responses from the log and inserting reviews manually rather than re-running
  the API).
- **2026-05-20:** ~$0.03 (one Re-review test of draft #1 during Editor UI smoke-test).
- **Editor agent all-time (as of 2026-05-20):** $0.3089 across 11 calls. Average cost per
  call: $0.0281. Visible in Editor → Pipeline Overview → Editor spend section.