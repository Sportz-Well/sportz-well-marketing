# CLAUDE.md

This file is the source of truth for anyone (including future Claude sessions) working on this codebase. Read it first.

---

## Product Vision — Three Phases

**Phase 1 (COMPLETE):** Internal AI-powered social media content pipeline for SWPI (Sportz-Well Performance Intelligence). Single client, runs locally, founder operates it manually.

**Phase 2 (NEXT):** Onboard SW-Travel as second client. Gen Z travel brand on Instagram. Schema already supports multi-tenancy — add rows, don't fork code. Do NOT start until SWPI has been used end-to-end in production for at least 2 weeks.

**Phase 3 (FUTURE):** Package as a SaaS product for other brands. Requires Meta Graph API integration for direct posting, multi-user auth, billing. Not before Phase 2 is stable.

---

## Product (Phase 1)

A web app that helps a brand plan, draft, and schedule social media content.

- **First client:** Sportz-Well, an Indian sports performance brand.
- **Flagship product:** SWPI (Sportz-Well Performance Intelligence App).
- **V1 platforms:** Instagram and Facebook.
- **V1 posting model:** The app does **not** post automatically. It generates drafts, schedules them on an internal calendar, and the user copy-pastes into Meta Business Suite.
- **V2 (later):** Direct API posting via Meta Graph API, after Meta App Review.
- **Multi-tenant:** V1 is single-client (Sportz-Well), but the schema already supports multiple clients — additional brands are onboarded by adding rows, not by forking code.

---

## Stack

- **Language:** Python 3.11+
- **UI:** Streamlit (chosen because the product owner is non-technical — fastest way to ship a working UI)
- **Database:** SQLite (file at `data/app.db`, created from `db/schema.sql`)
- **AI:** Anthropic Python SDK, wrapped in `services/anthropic_client.py`
- **Model:** `claude-sonnet-4-6` (set in `services/anthropic_client.py` — never hardcode elsewhere)
- **Environment:** Windows, PowerShell, VS Code, virtual env at `.venv`
- **Run command:** `streamlit run ui/app.py` from project root
- **Package management:** `uv` if available, otherwise `pip` + `requirements.txt`

---

## Critical API Convention

`ask_with_usage()` in `services/anthropic_client.py` takes:
- `system_prompt` (not `system`)
- `user_prompt` (not `user`)
- Returns a **dict** with keys: `text`, `input_tokens`, `output_tokens`, `web_searches`, `error`
- **Never unpack as a tuple.** This bug has been hit once — don't repeat it.

`get_active_product()` in `services/brand_context.py` returns a dict with:
- `product_id` (NOT `id`)
- `product_name` (NOT `name`)
- Every page and agent must use these keys. `product["id"]` will throw a KeyError.

---

## Architecture: one app, six agents + scheduler

One app, one database, one UI. Inside, seven specialized modules coordinate:

1. **Researcher** — gathers signals (news, trends, athlete content, science updates) relevant to the brand.
2. **Strategist** — turns research into story angles tied to brand positioning.
3. **Copywriter** — drafts platform-specific posts from story angles.
4. **Editor** — reviews drafts for voice, accuracy, and brand guardrails.
5. **Media** — turns each draft's image_brief into a shoot-ready photography creative brief.
6. **Scheduler** — places approved drafts on the content calendar.
7. **Orchestrator** — runs the full pipeline (Research → Strategy → Drafts → Editor → Media) in one click.

Each agent is its own module under `agents/`. They share the database (handoff is via DB rows, not in-memory state) and share the Anthropic client wrapper in `services/`.

---

## Build conventions

- **No hardcoded brand content.** Never put Sportz-Well's voice, USPs, positioning, "do not say" rules, or any brand-specific copy in Python files. Everything brand-specific lives in the `brand_profiles` table, keyed by client. Code reads the brand profile from the database at runtime.
- **Database is the handoff layer between agents.** Researcher writes to `research_items`, Strategist reads them and writes `story_angles`, Copywriter reads angles and writes `drafts`, Media reads drafts and writes `media_briefs`, etc.
- **Models:** Default to the latest Sonnet model ID (currently `claude-sonnet-4-6`) via the wrapper in `services/anthropic_client.py`. Don't hardcode model strings throughout the codebase.
- **Secrets:** API keys live only in `.env` (gitignored). `.env.example` documents what's needed.
- **`ask_with_usage()` signature:** Takes `system_prompt` and `user_prompt` as keyword args. Returns a dict with keys: `text`, `input_tokens`, `output_tokens`, `web_searches`, `error`. Never unpack as a tuple.

---

## Repository layout

```
agents/
  researcher.py    ✅ Prompt 3
  strategist.py    ✅ Prompt 4
  copywriter.py    ✅ Prompt 5
  editor.py        ✅ Prompt 6
  media.py         ✅ Prompt 7
  scheduler.py     ✅ Prompt 8
db/
  schema.sql       ✅ canonical schema — single source of truth
  init_db.py       ✅ creates data/app.db; auto-migrates schema
ui/
  app.py           ✅ Streamlit Home page
  pages/
    1_Brand_Brain.py     ✅ Prompt 2
    2_Research.py        ✅ Prompt 3
    3_Strategy.py        ✅ Prompt 4
    4_Drafts.py          ✅ Prompt 5
    5_Editor.py          ✅ Prompt 6
    6_Media.py           ✅ Prompt 7
    7_Calendar.py        ✅ Prompt 8
    8_Orchestrator.py    ✅ Prompt 9
services/
  anthropic_client.py     ✅ thin Anthropic SDK wrapper
  database.py             ✅ shared SQLite connection helper
  brand_context.py        ✅ brand context API — all agents use this
  url_validator.py        ✅ URL validation for researcher
  source_preferences.py   ✅ domain allowlist/downrank for researcher
data/                     # local SQLite DB lives here (gitignored)
tests/
  test_editor_parser.py   ✅ 18 smoke tests, all passing
.env.example
requirements.txt
```

---

## Brand data model (Prompt 2)

Two-tier hierarchy — organisation owns products, products have phases:

- `organizations` — parent company (Sportz-Well). `social_active = 0` in Phase 1.
- `products` — the social-media-active entity (SWPI). `is_active_client = 1` for V1.
- `product_phases` — rollout plan. Phase 1 active; Phases 2 & 3 planned.
- `brand_profiles` — JSON blob per product. Keys: audience, voice, topics, proof points, CTA.
- `partner_brands` — affiliated brands to mention. Empty in Phase 1 but schema is ready.
- `content_rules` — configurable rules keyed by `rule_key`. Vision-hint quota lives here.

---

## Brand context API

`services/brand_context.py` is the **single source of truth** for all agents:

| Function | Returns |
|---|---|
| `get_active_product()` | Product + org + active phase dict, or None |
| `get_brand_profile(product_id)` | Parsed JSON dict (includes split proof-point lists) |
| `get_content_rules(product_id)` | `{rule_key: rule_value}` dict |
| `get_active_partner_brands(org_id)` | List of active partner brand dicts |
| `build_brand_context_prompt(product_id)` | Agent-ready system prompt fragment (str) |

**Every future agent MUST call `build_brand_context_prompt()` and inject it into its Claude system prompt. Never hardcode brand content in agent code.**

---

## Current status — Phase 1 COMPLETE (2026-05-23)

All 8 modules built and tested end-to-end.

- ✅ Prompt 1 — Scaffold: folders, `.gitignore`, `.env.example`, `requirements.txt`, `README.md`
- ✅ Prompt 2 — Brand Brain: two-tier schema, brand profile JSON, SWPI seeded with Phase 1 profile
- ✅ Prompt 3 — Researcher agent + Research page (URL validation, geography mix, quality threshold, source bias)
- ✅ Prompt 3.5 — Researcher tuning (4 fixes: URL validation, geography, quality threshold, source bias)
- ✅ Prompt 4 — Strategist agent + Strategy page (vision-hint quota, sparing proof-point quota, CTA distribution)
- ✅ Prompt 5 — Copywriter agent + Drafts page (2 variants per platform, robust JSON parser)
- ✅ Prompt 5.5 — Copywriter tuning (CROSS_VARIANT_DUPLICATION eliminated: 46% → 0%)
- ✅ Prompt 6 — Editor agent + Editor page (10 checks: 8 hard, 2 soft; 18 parser smoke tests)
- ✅ Prompt 7 — Media agent + Media Studio page (photography creative briefs, ~$0.018/brief)
- ✅ Prompt 8 — Scheduler agent + Calendar page (schedule/reschedule/mark posted, pipeline overview)
- ✅ Prompt 9 — Orchestrator page (full pipeline runner + individual stage runner)

---

## DB Tables (complete)

| Table | Owner | Status |
|-------|-------|--------|
| organizations | Brand Brain | ✅ |
| products | Brand Brain | ✅ |
| product_phases | Brand Brain | ✅ |
| brand_profiles | Brand Brain | ✅ |
| partner_brands | Brand Brain | ✅ |
| content_rules | Brand Brain | ✅ |
| research_items | Researcher | ✅ |
| api_log | All agents | ✅ |
| story_angles | Strategist | ✅ |
| drafts | Copywriter | ✅ |
| editor_reviews | Editor | ✅ |
| media_briefs | Media | ✅ |
| schedule | Scheduler | ✅ |

---

## Known issues / watch list

- **Strategist intermittent JSON parse failure:** Occurs occasionally when research library is large (16+ items). Model returns valid JSON but parser fails on edge cases. Workaround: re-run Strategy — it succeeds on retry. Fix before Phase 2.
- **`batch_review_remaining.py` implicit retry:** `review_draft()` returns cached review if one exists. Safe to re-run but silently re-triggers API on new drafts with prior failures. Add `force=False` guard before next batch use.
- **Orphan editor_reviews rows:** Old drafts #1–12 deleted by regeneration but their `editor_reviews` rows remain. Harmless noise in Pipeline Overview histogram. Cleanup later.
- **HINGLISH_UNCALLED monitor:** Draft #19 used "maidan" once without explicit brief permission. Editor caught it. 1 instance, isolated. Monitor — don't act yet.

---

## Budget (all-time as of 2026-05-23)

| Session | Cost |
|---------|------|
| 2026-05-18 | ~₹10 |
| 2026-05-20 | ~$0.03 |
| 2026-05-21 (Prompt 5.5) | ~$0.35 |
| 2026-05-22 (Angle 10 fix + UX) | ~$0.10 |
| 2026-05-23 (Prompt 7 — Media) | ~$0.16 |
| 2026-05-23 (Prompt 8 — Calendar) | ~$0.00 (zero API cost) |
| 2026-05-23 (Prompt 9 — Orchestrator) | ~$0.00 (zero API cost) |
| 2026-05-23 (End-to-end test run) | ~$0.70 |
| **Total all-time** | **~$2.00** |

---

## Next steps

**Immediate (this week):**
Deploy to Streamlit Cloud (free tier). Half-day effort. See SOP document for deployment steps.

**Phase 2 (after 2 weeks of SWPI production use):**
Onboard SW-Travel as second client. Gen Z travel brand, Instagram-first. Schema supports it — add a new product row in Brand Brain. Brand voice, content rules, and proof points will be completely different from SWPI — fill them in carefully before running any agents.

**Phase 3 (future):**
SaaS packaging. Requires: Meta Graph API for direct posting, multi-user authentication, billing, proper hosting (not Streamlit Cloud). Not before Phase 2 is stable.

---

## Copywriter agent internals (`agents/copywriter.py`)

### System prompt structure

1. **Brand context block** — injected via `build_brand_context_prompt(product_id)`.
2. **Platform rules block** — per-platform word limits, hashtag counts, format constraints.
3. **Variant differentiation rules** — hook_strategy + perspective_focus enforcement.
4. **JSON format rules** — double-quote ban, single-quote alternatives.

### Variant differentiation (Prompt 5.5)

Five hook strategies: `question_hook | scenario_hook | statement_hook | story_hook | framework_hook`
Four perspective focuses: `coach_pov | parent_pov | player_pov | academy_pov`

Sibling variants on same platform MUST declare different values for BOTH fields. Validated in Python, dropped before DB insert.

### Robust JSON parser (4 strategies)

1. Direct `json.loads()`
2. Strip markdown fences → `json.loads()`
3. Remove trailing commas → `json.loads()`
4. `re.finditer(r'\{[\s\r\n]*"drafts"')` + `JSONDecoder.raw_decode()` — handles self-correction pattern

---

## Media agent internals (`agents/media.py`)

### Public API

| Function | Does |
|---|---|
| `generate_media_brief(draft_id, force=False)` | Generate 1 brief; cached if exists and force=False |
| `generate_all_pending(product_id, force=False)` | Run on all drafts without a brief |
| `get_media_library(product_id, status_filter, platform_filter)` | Returns briefs joined with draft + angle info |
| `get_brief_for_draft(draft_id)` | Returns the brief dict for a draft, or None |
| `update_brief_status(brief_id, status)` | Set pending / approved / rejected |
| `count_media_stats(product_id)` | Coverage and status counts |
| `get_last_run_info()` | Metadata from last generate call |

Empirical cost: ~$0.018 per brief. `props`, `color_palette`, `do_not` stored as JSON arrays (TEXT column).

---

## Scheduler agent internals (`agents/scheduler.py`)

### Public API

| Function | Does |
|---|---|
| `schedule_draft(draft_id, scheduled_for)` | Schedule an approved draft |
| `unschedule(schedule_id)` | Remove from schedule |
| `reschedule(schedule_id, new_datetime)` | Change scheduled time |
| `mark_as_posted(schedule_id)` | Set posted_at to now |
| `get_scheduled_drafts(start_date, end_date)` | Calendar view for date range |
| `get_pipeline_summary(product_id)` | Approved: scheduled vs unscheduled counts |
| `get_approved_unscheduled_drafts(product_id)` | Drafts ready to schedule |

Zero API cost — pure DB logic.

---

## Working rules for future Claude sessions

1. **Plan-and-paste mode:** Claude plans, Jitendra runs commands in PowerShell on Windows.
2. **Any changes to existing files:** Recode the WHOLE file as a downloadable artifact. Never copy-paste code inline in chat.
3. **New files:** Label clearly "NEW FILE", deliver whole file as artifact.
4. **One task at a time.** No scope creep.
5. **Two files at a time maximum.**
6. **Always ask for the real current file** before editing. Never reconstruct from memory.
7. **Commit message required** after every file save.
8. **End of every session:** Give 2 options for next steps and recommend which one and why.