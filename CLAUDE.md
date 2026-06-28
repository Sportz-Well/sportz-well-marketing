# CLAUDE.md
## Source of truth for anyone (including future Claude sessions) working on this codebase.
## Read this first. Always.

---

## Product Vision — Three Phases

**Phase 1 (COMPLETE + IN PRODUCTION):**
Internal AI-powered social media content pipeline for SWPI (Sportz-Well Performance
Intelligence). Single client, deployed on Streamlit Cloud, founder operates manually.
In production since June 5, 2026. First LinkedIn posts live.

**Phase 2 (after 2026-06-19):**
Onboard external clients. First candidate: Saviour Rescuevator (fire evacuation lifts).
Schema supports multi-tenancy — add rows, don't fork code.
Do NOT start until SWPI has been in production for at least 2 weeks (gate: June 19, 2026).

**Phase 3 (future):**
SaaS product. Meta Graph API, multi-user auth, billing. Not before Phase 2 stable.

---

## The Product

An AI-powered social media content pipeline for SWPI — a monthly AI-driven player
development platform for grassroots cricket academies (U10-U17 players in Indian cities).

- **Primary buyers:** Academy directors and head coaches (B2B institutional sale)
- **CTA:** Book a demo at sportz-well.com
- **Live URL:** https://swpi-marketing.streamlit.app
- **GitHub:** https://github.com/Sportz-Well/sportz-well-marketing (public)
- **V1 posting model:** App does NOT post automatically. Drafts → copy-paste into
  Meta Business Suite (FB/IG) and LinkedIn directly.
- **LinkedIn rule:** Post body contains NO SWPI mention. First comment posted
  immediately after publishing contains SWPI product mention + sportz-well.com.
- **V2 (later):** Direct API posting via Meta Graph API after Meta App Review.

---

## Stack

- **Language:** Python 3.11+
- **UI:** Streamlit (non-technical founder — fastest way to ship a working UI)
- **Database:** PostgreSQL on Supabase (project: kkepmacwjfuoczbbfroi — Seoul region)
- **AI:** Anthropic Python SDK, wrapped in `services/anthropic_client.py`
- **Model:** `claude-sonnet-4-6` — Claude Sonnet 4.6 by Anthropic
- **Web search:** Built-in Anthropic web search tool (used by Researcher agent only)
- **Research cost:** ~₹30 per topic (6 items) | ~₹60/week | ~₹240/month
- **Environment:** Windows, PowerShell, VS Code, virtual env at `.venv`
- **Run command:** `streamlit run ui/app.py` from project root
- **Deploy:** Push to master branch → Streamlit Cloud auto-deploys in ~2 minutes
- **Secrets:** ANTHROPIC_API_KEY and DATABASE_URL in Streamlit Cloud Secrets

---

## Critical API Conventions

`ask_with_usage()` in `services/anthropic_client.py`:
- Takes: `system_prompt` (not `system`) and `user_prompt` (not `user`)
- Returns: dict with keys `text`, `input_tokens`, `output_tokens`, `web_searches`, `error`
- NEVER unpack as a tuple — this bug has been hit before

`get_active_product()` in `services/brand_context.py`:
- Returns dict with `product_id` (NOT `id`) and `product_name` (NOT `name`)
- Every page and agent must use these exact keys

**PostgreSQL rules (all agents):**
- No `INSERT OR REPLACE INTO` → use `INSERT INTO ... ON CONFLICT ... DO UPDATE`
- No `datetime('now')` → use `datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")`
- No `import sqlite3` anywhere → use `except Exception:` not `except sqlite3.OperationalError:`
- `?` placeholders auto-convert to `%s` in `services/database.py`

**INR display rule (all pages):**
- Import `format_cost_inr` from `services/page_utils`
- `USD_TO_INR = 95` constant lives in `services/page_utils.py`
- Never display raw USD to the user — always convert via `format_cost_inr(usd)`

---

## Architecture — Seven Agents + Scheduler

One app, one database, one UI. Seven modules coordinate via database rows:

```
Researcher   → research_items table
Strategist   → story_angles table
Copywriter   → drafts table
Editor       → editor_reviews table
Media        → media_briefs table (ZERO API COST — template-based)
Scheduler    → schedule table
Orchestrator → calls all agents, no own table
```

**Key principle:** No hardcoded brand content anywhere in agent code. Everything
brand-specific lives in the `brand_profiles` table, keyed by client.

---

## Repository Layout (current state as of 2026-06-28)

```
agents/
  researcher.py    ✅ BCCI/IPL hard cap at 4/10; sqlite3 refs removed
  strategist.py    ✅
  copywriter.py    ✅ duplicate functions removed (delete_draft_permanently,
                      get_editor_review_status each now defined exactly once)
  editor.py        ✅ sqlite3 refs removed
  media.py         ✅ ZERO COST — template-based, no API calls
  scheduler.py     ✅
db/
  schema.sql       ✅ canonical schema
  init_db.py       ✅ creates DB, auto-migrates
ui/
  app.py           ✅ warm slate theme (#0f172a bg, #1e293b cards, #334155 borders)
  pages/
    1_Brand_Brain.py    ✅
    2_Research.py       ✅ INR display throughout; Researcher spend card (Today/Month/All time)
    3_Strategy.py       ✅ week picker on Story Angles Library; auto-hide completed angles;
                           delete buttons with cascade; Strategy spend card in Tab C
    4_Drafts.py         ✅ delete buttons on every card; Copywriter spend card;
                           warm slate colours; format_cost_inr throughout
    5_Editor.py         ✅ bulk "Review All Unreviewed" button; full draft content shown
                           in Tab A alongside issues (no more back-and-forth to Drafts)
    6_Media.py          ⚠️  MISSING: no "hide posted drafts" toggle — posted media briefs
                           still visible. Fix is NEXT PRIORITY.
    7_Calendar.py       ✅
    8_Orchestrator.py   ✅ INR display; consolidated spend dashboard (all agents)
services/
  anthropic_client.py   ✅
  database.py           ✅ PostgreSQL wrapper with ? → %s auto-conversion
  brand_context.py      ✅
  url_validator.py      ✅
  source_preferences.py ✅
  page_utils.py         ✅ warm slate theme CSS; USD_TO_INR=95; format_cost_inr() helper
tests/
  test_editor_parser.py ✅ 18 smoke tests, all passing
```

---

## Theme — Warm Slate Palette (applied 2026-06-28)

All pages now use warm slate. The old cold near-black palette is gone.

| Element | Colour |
|---|---|
| App background | `#0f172a` |
| Cards / containers | `#1e293b` |
| Borders | `#334155` |
| Primary text | `#f1f5f9` |
| Muted text / labels | `#94a3b8` |
| Captions | `#64748b` |
| Gold accent | `#f5a623` (unchanged) |
| Font | Rajdhani (headings) + Inter (body) |

Home page (`app.py`) has CSS hardcoded directly (does not use `init_page()`).
All inner pages use `init_page()` from `services/page_utils.py`.

---

## What Was Done — Session 2026-06-28

### UX overhaul (Option A)

**`services/page_utils.py`** — cold dark palette replaced with warm slate. Applied globally
to all inner pages via `init_page()`.

**`ui/app.py`** — home page CSS updated to match inner pages. Previous CSS used cold `#080810`
background. Now uses `#0f172a` and full warm slate palette.

**`ui/pages/5_Editor.py`**
- Bulk "Review All Unreviewed" button with progress bar (Tab A top)
- Full draft content display in Tab A — headline, body, CTA, hashtags shown when you
  select a draft. Copy helpers embedded. No more going back to Drafts page to read the post.
- `format_cost_inr` throughout
- `review_draft` and `rereview_draft` moved to top-level imports

**`ui/pages/3_Strategy.py`**
- Week picker on Story Angles Library — defaults to current week
- Auto-hide completed angles (all drafts posted) — "Show completed" checkbox to reveal
- Delete button 🗑️ on every angle card — arm/confirm pattern, cascade deletes
- Restore button on rejected angles
- `_get_strategy_spend()` + spend card at bottom of Tab C
- `_delete_angle_permanently()` function (cascade: schedule → media_briefs →
  editor_reviews → drafts → story_angle)

**`ui/pages/4_Drafts.py`**
- Delete button 🗑️ on every draft card — arm/confirm, cascade via `delete_draft_permanently()`
- `_get_copywriter_spend()` + spend card at bottom of Generate tab
- Warm slate colours in `_render_body()` and `STATUS_BADGE`
- `format_cost_inr` throughout

**`ui/pages/2_Research.py`** — full INR display; spend card shows Today/Month/All time
for Researcher agent only (was showing all agents combined).

**`ui/pages/8_Orchestrator.py`** — INR display; consolidated spend dashboard showing
Today/Month/All time + per-agent breakdown in expandable section.

**`agents/copywriter.py`** — duplicate `delete_draft_permanently` and
`get_editor_review_status` definitions removed. Each now defined exactly once.

---

## Pending Tasks — Priority Order

### 🔴 DO FIRST in next session

**1. Media page — add "hide posted drafts" toggle (`6_Media.py`)**
- Posted media briefs are still visible in the Image Prompt Library
- Simple filter: "Show posted" checkbox (default OFF), same pattern as Editor Tab B
- This is the immediate UX relief needed — founder spent a whole day confused by this
- One file, ~30 minutes

**2. Complete the content cycle for week of Jun 23–28**
- Strategy was run June 23 (9 angles proposed, ₹7.84)
- Some angles may be approved, drafts may be pending
- Full cycle: Strategy Angles Library → approve → Generate → Editor bulk review →
  Approve → Schedule → Post

### 🟡 NEXT CODE SESSION

**3. Home page redesign — "This Week" command centre (`ui/app.py`)**
- Replace current status dashboard with a task-based weekly view
- Show: angles needing approval this week, drafts needing review, posts scheduled
- "Invisible pipeline" — user thinks in tasks, not pipeline stages
- One clear screen: "here is what to do today"

**4. Strategy spend card (already done in 3_Strategy.py — verify live)**

### 🔵 AFTER JUNE 19 GATE

**5. Sample SWPI academy report + LinkedIn showcase post**
- Strongest B2B sales tool — shows academy directors what they'd receive monthly
- Requires design work + LinkedIn post draft

**6. External client onboarding (Saviour Rescuevator)**
- Pricing: Starter ₹12,000–18,000/month, Full Suite ₹38,000/month, ₹8,000 setup
- Gated: no earlier than June 19, 2026
- Process: add new product row in Brand Brain → fill brand voice → run agents

**7. Newsletter and Blog pages (Phase 2)**
- Deferred until 2 weeks of stable production use

---

## Content Strategy Rules (non-negotiable)

**LinkedIn posting rule:**
Post body = NO SWPI mention (thought leadership only).
First comment posted immediately after = SWPI product mention + sportz-well.com.

**Platform audiences:**
- LinkedIn: academy directors, head coaches, B2B operators
- Facebook: parents 30–50, decision-makers for their child's academy
- Instagram: young cricketers U10–U17 and emotionally invested parents

**BCCI/IPL/national team:** Hard-capped at 4/10 in Researcher. Off-target for grassroots.

**Coaches are primary customer:** Content must never alienate academy directors or
coaches. Any angle that frames coaches negatively must be rewritten.

**Institutional framing:** Shardashram/Achrekar/Tendulkar referenced as philosophy
and heritage only. Never as personal credentials or lineage claims.

---

## Weekly Content Rhythm (locked in)

| Day | Task |
|-----|------|
| Sunday | Research 2 new topics |
| Monday | Strategy → approve angles → Generate drafts |
| Tuesday | Editor review → fix flagged → Approve |
| Tuesday–Saturday | Post from Calendar → Mark Posted immediately after |

---

## UX Audit Findings (2026-06-28) — Devil's Advocate Assessment

**Root problem:** App was built around pipeline stages, not the founder's weekly workflow.
User thinks "I need to post something this week." App says "which pipeline stage are you on?"

**Specific UX failures identified:**
1. Media page shows all briefs including posted — no filter. Immediate fix needed.
2. Draft IDs (#13, #14, #31, #32) are meaningless identifiers with no context.
3. V1 vs V2 of same angle look nearly identical in all list views.
4. No single screen showing "what is active this week."
5. Calendar page has minimal operational value for manual copy-paste workflow.
6. Strategy Angles Library accumulated 24+ angles from multiple runs with no time separation.

**Fixes already shipped:**
- Week picker on Strategy (shows only this week's angles)
- Week picker on Drafts (shows only this week's drafts)
- Delete buttons on angles and drafts
- Auto-hide completed angles
- Editor shows full draft content inline

**Fixes still needed:**
- Media page: hide posted filter
- Home page: This Week command centre
- Calendar: collapse into Drafts as a tab (Phase 2 UX)

**Jasper comparison:**
Jasper wins on simplicity — task-first, invisible system. Our app wins on content quality —
research-grounded, brand-voice enforced, platform-specific rules, quality gate. The goal is
to keep the quality ceiling and make the UX as invisible as Jasper's.

---

## DB Tables

| Table           | Owner        |
|----------------|--------------|
| organizations   | Brand Brain  |
| products        | Brand Brain  |
| product_phases  | Brand Brain  |
| brand_profiles  | Brand Brain  |
| partner_brands  | Brand Brain  |
| content_rules   | Brand Brain  |
| research_items  | Researcher   |
| api_log         | All agents   |
| story_angles    | Strategist   |
| drafts          | Copywriter   |
| editor_reviews  | Editor       |
| media_briefs    | Media        |
| schedule        | Scheduler    |

---

## Media Agent — Zero Cost (permanent)

The Media agent makes ZERO API calls. Template function wraps
`visual_photography_note` (or `image_brief` as fallback) with tool-specific
style and platform aspect ratio. Instant. Free.

Platform aspect ratios auto-injected:
- Instagram → Firefly: 4:5 | ChatGPT: Tall | Gemini: Portrait
- Facebook  → Firefly: 1:1 | ChatGPT: Square | Gemini: Square
- LinkedIn  → Firefly: 16:9 | ChatGPT: Widescreen | Gemini: Landscape

Image generation tools (confirmed subscriptions):
Adobe Firefly ✅ | ChatGPT Free/DALL-E 3 ✅ | Google Gemini Pro ✅
Midjourney ❌ | Runway ❌

---

## Budget (all-time as of 2026-06-28)

| Session | Cost |
|---------|------|
| All sessions to 2026-05-23 | ~$2.00 |
| 2026-06-12 (Drafts redesign) | ~$0.00 |
| 2026-06-14 (LinkedIn + fixes) | ~$0.00 |
| 2026-06-18 (code fixes + research) | ~$0.63 |
| 2026-06-23 (Strategy run) | ~₹7.84 |
| 2026-06-28 (code sessions) | ~$0.00 |
| **Total all-time** | **~$7.34 (~₹697)** |

Weekly running cost: ~₹200/week (~₹800/month)
Cost per published post: ~₹27

---

## Known Issues / Watch List

- **6_Media.py:** No "hide posted drafts" toggle — NEXT FIX PRIORITY
- **Strategist intermittent JSON parse failure:** Large research libraries (20+ items).
  Workaround: re-run — succeeds on retry.
- **Circular import risk:** Never import `page_utils` from within `page_utils` itself.
  Hit once on 2026-06-18 — fixed via GitHub.com direct edit.
- **LinkedIn post body violation:** SWPI appeared in post body on one published post.
  Editor should catch this — monitor every future draft before publishing.

---

## Deployment Details

- **Live URL:** https://swpi-marketing.streamlit.app
- **Platform:** Streamlit Community Cloud (free tier)
- **GitHub:** https://github.com/Sportz-Well/sportz-well-marketing (public)
- **API key:** Stored in Streamlit Cloud Secrets (never in code or GitHub)
- **Auto-deploy:** Push to `master` → live in ~2 minutes
- **Sleep:** App sleeps after inactivity, wakes in 15–30 seconds
- **Emergency fix:** Edit files directly on GitHub.com when circular import or
  crash prevents the app loading locally

---

## Working Rules for Future Claude Sessions

1. Plan-and-paste mode: Claude plans, Jitendra runs in PowerShell on Windows.
2. Changes to existing files: Recode WHOLE file as downloadable artifact. Never inline.
3. New files: Label "NEW FILE", deliver whole file as artifact.
4. One task at a time. No scope creep.
5. Two files max per session (tightly coupled exception only).
6. Always ask for real current file before editing. Never reconstruct from memory.
7. Commit message required after every file save.
8. End every session: give 2 options for next steps + recommendation with reason.
9. Always state full file path: `C:\Users\Dell\sportz-well-marketing\path\to\file.py`
10. No PDF files — .md only for documents.
11. Windows PowerShell commands only.
12. Parameterised SQL always (`?` placeholders). Never string concatenation.
13. Confirm features before building. No surprises.
14. After saving files, always verify with `Get-Content ... | Select-Object -Last 20`
    before committing. "Nothing to commit" means the file wasn't saved to the right path.
15. If app crashes with circular import: fix directly on GitHub.com, not locally.
16. Claude acts as CTO co-founder, friend, and mentor. No sugarcoating. If an idea is
    weak, say so directly. Test everything until both agree it is bulletproof.
17. Maximum two files per session — this rule protects against scope creep and errors.
    Never deliver 3 files in one session without explicit agreement.