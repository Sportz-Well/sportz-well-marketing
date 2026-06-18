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

## Repository Layout (current state as of 2026-06-18)

```
agents/
  researcher.py    ✅ BCCI/IPL hard cap at 4/10; sqlite3 refs removed
  strategist.py    ✅
  copywriter.py    ✅ delete_draft_permanently + get_editor_review_status present
  editor.py        ✅ sqlite3 refs removed
  media.py         ✅ ZERO COST — template-based, no API calls
  scheduler.py     ✅
db/
  schema.sql       ✅ canonical schema
  init_db.py       ✅ creates DB, auto-migrates
ui/
  app.py           ✅ premium dark theme (Rajdhani, #080810, #f5a623)
  pages/
    1_Brand_Brain.py    ✅
    2_Research.py       ⚠️  cost display still shows USD — fix pending
    3_Strategy.py       ✅ LinkedIn added throughout; INR costs; subtitle fixed
    4_Drafts.py         ✅ 2-tab week-native redesign (Weekly Drafts + Generate)
    5_Editor.py         ✅ LinkedIn filter; posted drafts hidden; sqlite3 removed
    6_Media.py          ✅ zero-cost template prompts
    7_Calendar.py       ✅
    8_Orchestrator.py   ✅
services/
  anthropic_client.py   ✅
  database.py           ✅ PostgreSQL wrapper with ? → %s auto-conversion
  brand_context.py      ✅
  url_validator.py      ✅
  source_preferences.py ✅
  page_utils.py         ✅ USD_TO_INR=95 + format_cost_inr() helper added
tests/
  test_editor_parser.py ✅ 18 smoke tests, all passing
```

---

## What Was Done — Session 2026-06-18

### 1. Editor page (5_Editor.py + agents/editor.py)
- LinkedIn added to `_PLATFORM_BADGE` dict and platform filter dropdown
- Posted drafts now hidden by default — "Show posted drafts" checkbox to reveal
- `import sqlite3` removed from both files
- All `except sqlite3.OperationalError` → `except Exception` (3 places in each)
- All cost display switched to ₹ via `format_cost_inr()`

### 2. Drafts page — complete redesign (4_Drafts.py)
- **5 tabs → 2 tabs only:** Weekly Drafts + Generate
- Week picker dropdown (defaults to current week, navigate backwards)
- Platform filter: All / LinkedIn / Facebook / Instagram
- Posted drafts invisible automatically (no toggle needed)
- Rejected drafts invisible automatically
- Single unified card per draft — status badge adapts to state
- Status badges: 📅 Scheduled | ✅ Approved | 🟢 Editor Clean | 🚩 Needs Fix | ⏳ Not Reviewed
- Action buttons adapt to status (Approve/Reject/Edit as appropriate)
- Generate tab unchanged

### 3. page_utils.py — INR helper
- `USD_TO_INR: int = 95` constant added
- `format_cost_inr(usd: float) -> str` helper added
- Returns `₹2.57` style strings for all cost display

### 4. Strategy page (3_Strategy.py)
- Subtitle updated: "LinkedIn, Instagram & Facebook"
- `_PLATFORM_BADGE` dict: LinkedIn added
- Platform filter dropdown: LinkedIn added
- Filter logic: LinkedIn = exact match; Instagram/Facebook = includes "both"
- Pipeline Overview: 4-column platform breakdown including LinkedIn
- All USD cost displays → `format_cost_inr()`
- Import: `from services.page_utils import init_page, format_cost_inr`

### 5. Researcher agent (agents/researcher.py)
- `import sqlite3` removed
- BCCI scoring cap added to system prompt:
  **IPL / national team / BCCI content hard-capped at relevance_score 4**
  regardless of source quality or recency
- All `except sqlite3.OperationalError` → `except Exception`

### 6. Content — week of Jun 16–21
- 6 posts scheduled in Calendar across LinkedIn, Facebook, Instagram
- 2 LinkedIn posts from prior week marked as Posted (Jun 8 + Jun 12)
- Research run: 2 new topics completed (12 new items in library)
  - "AI and biochemical analysis in sports performance India" (6 items)
  - "Data driven coaching grassroots sports India academy" (6 items)

---

## Pending Tasks — Priority Order

### 🔴 DO FIRST in next session

**1. Strategy → Generate cycle for week of Jun 23 (LinkedIn only)**
- Research library has 20 items ready
- Run Strategy with editorial focus: "LinkedIn only — B2B professional angles for academy directors and head coaches"
- Approve 3-4 LinkedIn angles only
- Generate drafts → Editor → Approve → Schedule for Jun 23 onwards

**2. Fix Instagram drafts #7 and #8**
- Both flagged CAPTION_TOO_SHORT (~62–66 words, needs 80–130)
- Fix in app: Drafts → Weekly Drafts → find them → Edit → add 2 sentences → Save
- Go to Editor → Re-review → confirm Clean

### 🟡 NEXT CODE SESSION

**3. Delete button on Drafts weekly cards (4_Drafts.py)**
- 🗑️ button on each card with inline "Are you sure?" confirmation
- Permanently deletes draft + cascades to editor_reviews, media_briefs, schedule
- Calls existing `delete_draft_permanently(draft_id)` in copywriter.py
- Jitendra's requirement: individual delete per card, not bulk

**4. Research page INR display (2_Research.py)**
- Still shows `$0.31` — needs `format_cost_inr()` throughout
- Quick fix, 1 file, ~15 minutes

### 🔵 AFTER JUNE 19 GATE

**5. Sample SWPI academy report + LinkedIn showcase post**
- SWPI's product is a monthly player development report for academies
- A sample report posted on LinkedIn is the strongest sales tool
- Shows academy directors exactly what they'd get
- Requires: design work + LinkedIn post draft
- Not started yet

**6. External client onboarding (Saviour Rescuevator)**
- Fire safety / evacuation lifts industry
- Pricing: Starter ₹12,000–18,000/month, Full Suite ₹38,000/month, ₹8,000 one-time setup
- Gated: no earlier than June 19, 2026
- Process: add new product row in Brand Brain → fill brand voice → run agents

**7. Newsletter and Blog pages (Phase 2)**
- Weekly newsletter + fortnightly blog
- Deferred until 2 weeks of stable production use
- New agents: blog_writer.py, newsletter_writer.py

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

**No duplicate openers:** Instagram + Facebook angles cannot share identical hook lines.

---

## Weekly Content Rhythm (locked in)

| Day | Task |
|-----|------|
| Sunday | Research 2 new topics |
| Monday | Strategy → approve angles → Generate drafts |
| Tuesday | Editor review → fix flagged → Approve |
| Tuesday–Saturday | Post from Calendar → Mark Posted immediately after |

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

## Budget (all-time as of 2026-06-18)

| Session | Cost |
|---------|------|
| All sessions to 2026-05-23 | ~$2.00 |
| 2026-06-12 (Drafts redesign) | ~$0.00 |
| 2026-06-14 (LinkedIn + fixes) | ~$0.00 |
| 2026-06-18 (Today — code fixes) | ~$0.00 |
| 2026-06-18 (Research — 2 topics) | ~$0.63 |
| **Total all-time** | **~$7.34 (~₹697)** |

Weekly running cost: ~₹200/week (~₹800/month)
Cost per published post: ~₹27

---

## Known Issues / Watch List

- **2_Research.py:** Cost display still shows USD — fix pending (next session)
- **Instagram drafts #7 and #8:** Still flagged CAPTION_TOO_SHORT — fix in app
- **Strategist intermittent JSON parse failure:** Large research libraries (20+ items).
  Workaround: re-run — succeeds on retry. Fix before Phase 2.
- **Circular import risk:** Never import `page_utils` from within `page_utils` itself.
  Hit once on 2026-06-18 — fixed via GitHub.com direct edit.

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