# CLAUDE.md
## Source of truth for anyone (including future Claude sessions) working on this codebase.
## Read this first. Always. Completely. Before touching anything.

---

## Who You Are Working With

**Jitendra Sonu Jagdale** — non-technical founder. Mumbai cricketer, MCA Match
Observer, Shardashram alumnus. Building a billion-dollar company. Decisive, moves
fast, respects straight talk. Does NOT want to be coddled. If an idea is weak, say
so directly.

**Your role in every session:** CTO co-founder, friend, and mentor.
- Be patient. Give step-by-step instructions for every task he runs.
- Never sugarcoat. Test everything until you both agree it is bulletproof.
- Maximize every chat — no padding, no repetition.
- Jitendra is non-technical. Never assume he knows what a command does. Explain it.
- He thinks in weeks and tasks, not pipeline stages. Always frame things his way.

**Your working relationship:** Claude and Jitendra have worked together across
multiple sessions. Claude designed the entire architecture, built every agent, fixed
every production bug, wrote all documentation, and acts as the technical brain.
Jitendra executes, tests, makes business calls, and runs all terminal commands.
This is a genuine co-founder dynamic — the trust is earned, the directness is mutual.

---

## Working Rules — Non-Negotiable, Every Session

1. **Plan-and-paste mode:** Claude plans and delivers complete files. Jitendra runs
   all PowerShell commands himself. Never give instructions that require him to
   write or modify code manually.
2. **Whole files only:** Any change to an existing file = recode the WHOLE file as
   a downloadable artifact. Never inline partial code snippets in chat.
3. **New files:** Label clearly "NEW FILE", deliver whole file as artifact.
4. **Maximum 2 files per session.** No exceptions without explicit agreement.
5. **Always request the real current file** before editing. Never reconstruct from
   memory. Jitendra pastes the file → Claude reviews → Claude delivers updated version.
6. **Always provide a git commit message** after every file change.
7. **Always provide PowerShell commands** step by step with plain-English explanation.
8. **End every session** with exactly 2 options for next steps + recommendation with
   clear reasoning.
9. **Verify saves** with `Get-Content path\to\file.py | Select-Object -Last 20`
   before committing. "Nothing to commit, working tree clean" often means the file
   wasn't saved to the correct path — not that it was already committed.
10. **No PDF files** — .md only for all documents.
11. **Full file path always:** e.g. `C:\Users\Dell\sportz-well-marketing\agents\scheduler.py`
12. **Parameterised SQL always.** Never string concatenation in queries.
13. **Confirm features before building.** No surprises.
14. **If app crashes with circular import:** fix directly on GitHub.com browser
    editor, not locally.
15. **PowerShell encoding rule:** Never use `Add-Content` to append to `.py` files.
    Always use the full downloadable artifact method.

---

## Product Vision — Three Phases

**Phase 1 (COMPLETE + IN PRODUCTION):**
Internal AI-powered social media content pipeline for SWPI. Single client, deployed
on Streamlit Cloud, founder operates manually. Live since June 2026.

**Phase 2 (next — gated until stable):**
Onboard external clients. First candidate: Saviour Rescuevator (fire evacuation lifts).
Schema supports multi-tenancy — add rows, don't fork code.
Gate: SWPI must be in stable production for at least 2 weeks first.

**Phase 3 (future):**
SaaS product. Meta Graph API, multi-user auth, billing. Not before Phase 2 stable.

---

## The Product

An AI-powered social media content pipeline for SWPI — a monthly AI-driven player
development platform for grassroots cricket academies (U10–U17 players in Indian cities).

- **Primary buyers:** Academy directors and head coaches (B2B institutional sale)
- **CTA:** Book a demo at sportz-well.com
- **Live URL:** https://swpi-marketing.streamlit.app
- **GitHub:** https://github.com/Sportz-Well/sportz-well-marketing (public)
- **V1 posting model:** App does NOT post automatically. Drafts → copy-paste into
  Meta Business Suite (FB/IG) and LinkedIn directly.
- **LinkedIn rule:** Post body contains NO SWPI mention (thought leadership only).
  First comment posted immediately after = SWPI product mention + sportz-well.com.
- **V2 (later):** Direct API posting via Meta Graph API after Meta App Review.

---

## Stack

- **Language:** Python 3.11+
- **UI:** Streamlit (non-technical founder — fastest way to ship a working UI)
- **Database:** PostgreSQL on Supabase (Seoul region)
- **AI:** Anthropic Python SDK, wrapped in `services/anthropic_client.py`
- **Model:** `claude-sonnet-4-6` — set in anthropic_client.py, never hardcode elsewhere
- **Web search:** Built-in Anthropic web search tool (Researcher agent only)
- **Environment:** Windows, PowerShell, VS Code, virtual env at `.venv`
- **Run command:** `streamlit run ui/app.py` from project root
- **Deploy:** Push to master branch → Streamlit Cloud auto-deploys in ~2 minutes
- **Secrets:** ANTHROPIC_API_KEY and DATABASE_URL in Streamlit Cloud Secrets only

---

## Critical API Conventions — Read Before Touching Any Agent

### Anthropic wrapper
`ask_with_usage()` in `services/anthropic_client.py`:
- Takes: `system_prompt=` and `user_prompt=` (NOT `system=` / `user=`)
- Returns: dict with keys `text`, `input_tokens`, `output_tokens`, `web_searches`, `error`
- **NEVER unpack as a tuple** — this bug has been hit before

### Brand context
`get_active_product()` in `services/brand_context.py`:
- Returns dict with `product_id` (NOT `id`) and `product_name` (NOT `name`)
- Every page and agent must use these exact keys

### PostgreSQL rules — CRITICAL (all agents)

These SQLite-only patterns are **broken** in production on Supabase:

| ❌ BROKEN (SQLite only) | ✅ CORRECT (PostgreSQL) |
|------------------------|------------------------|
| `import sqlite3` | Don't import sqlite3 at all |
| `conn.row_factory = sqlite3.Row` | Don't use row_factory |
| `row["column_name"]` dict access | `row[0]`, `row[1]` positional access |
| `cursor.lastrowid` | `RETURNING id` in INSERT, then `.fetchone()[0]` |
| `cursor.description` | Do not use — AttributeError in production |
| `INSERT OR REPLACE INTO` | `INSERT INTO ... ON CONFLICT ... DO UPDATE` |
| `datetime('now')` | `datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")` |

**Use `?` placeholders** — `services/database.py` auto-converts to `%s` for psycopg2.

**Row access pattern (proven working in production):**
```python
rows = conn.execute(
    "SELECT id, name, status FROM my_table WHERE product_id = ?",
    (product_id,)
).fetchall()
for r in rows:
    my_id     = r[0]
    my_name   = r[1]
    my_status = r[2]
```

**INSERT with returned ID:**
```python
result = conn.execute(
    "INSERT INTO my_table (col1, col2) VALUES (?, ?) RETURNING id",
    (val1, val2)
).fetchone()
conn.commit()
new_id = result[0]
```

### INR display rule
Always display costs in INR, never raw USD:
```python
from services.page_utils import format_cost_inr
st.metric("Cost", format_cost_inr(cost_usd))
```
`USD_TO_INR = 95` lives in `services/page_utils.py`.

---

## Architecture — Seven Agents + Scheduler

One app, one database, one UI. Seven modules coordinate via database rows:

```
Researcher   → research_items table
Strategist   → story_angles table
Copywriter   → drafts table
Editor       → editor_reviews table
Media        → media_briefs table (ZERO API COST — template-based)
Scheduler    → schedule table + post_performance table
Orchestrator → calls all agents, no own table
```

**Key principle:** No hardcoded brand content anywhere in agent code. Everything
brand-specific lives in the `brand_profiles` table, keyed by client.

---

## Repository Layout (current state as of 2026-06-30)

```
agents/
  researcher.py    ✅ Live
  strategist.py    ✅ Live
  copywriter.py    ✅ Live
  editor.py        ✅ Live
  media.py         ✅ ZERO COST — template-based, no API calls
  scheduler.py     ✅ FULLY REWRITTEN 2026-06-30:
                      - sqlite3 bugs removed throughout
                      - cursor.description dependency removed
                      - New: record_performance(), get_performance_for_draft(),
                        get_latest_performance_for_draft()
db/
  schema.sql       ✅ post_performance table added 2026-06-30
  init_db.py       ✅ creates DB, auto-migrates
ui/
  app.py           ✅ REDESIGNED 2026-06-30: "This Week" command centre
                      (Mon–Sun week grid, plain-English to-do list, week stats)
  pages/
    1_Brand_Brain.py    ✅
    2_Research.py       ✅ INR display throughout
    3_Strategy.py       ✅ Week picker, auto-hide completed, delete buttons
    4_Drafts.py         ✅ Delete buttons, spend card, warm slate
    5_Editor.py         ✅ Bulk review, full draft content inline
    6_Media.py          ✅ FIXED 2026-06-30: "Hide posted drafts" toggle added
    7_Calendar.py       ✅ UPDATED 2026-06-30: Engagement logging UI on posted
                           entries (likes/comments/shares → post_performance table)
    8_Orchestrator.py   ✅ INR display, consolidated spend dashboard
services/
  anthropic_client.py   ✅
  database.py           ✅ PostgreSQL wrapper with ? → %s auto-conversion
  brand_context.py      ✅
  url_validator.py      ✅
  source_preferences.py ✅
  page_utils.py         ✅ warm slate theme CSS; USD_TO_INR=95; format_cost_inr()
tests/
  test_editor_parser.py ✅ 18 smoke tests, all passing
CLAUDE.md                ✅ this file
TECH_REFERENCE_FOR_AI_AGENTS.md  ✅ added 2026-06-30 (tech stack doc for agents)
SWPI_Content_Strategy_Audit_2026-06-29.md  ✅ strategic audit doc
```

---

## Theme — Warm Slate Palette

All pages use warm slate. No cold dark colours.

| Element | Colour |
|---|---|
| App background | `#0f172a` |
| Cards / containers | `#1e293b` |
| Borders | `#334155` |
| Primary text | `#f1f5f9` |
| Muted text | `#94a3b8` |
| Captions | `#64748b` |
| Gold accent | `#f5a623` |
| Font | Rajdhani (headings) + Inter (body) |

Home page (`app.py`) has CSS hardcoded directly. All inner pages use `init_page()`
from `services/page_utils.py`.

---

## DB Tables (complete as of 2026-06-30)

| Table | Owner |
|-------|-------|
| organizations | Brand Brain |
| products | Brand Brain |
| product_phases | Brand Brain |
| brand_profiles | Brand Brain |
| partner_brands | Brand Brain |
| content_rules | Brand Brain |
| research_items | Researcher |
| api_log | All agents |
| story_angles | Strategist |
| drafts | Copywriter |
| editor_reviews | Editor |
| media_briefs | Media |
| schedule | Scheduler |
| post_performance | Scheduler ← NEW 2026-06-30 |

---

## What Was Completed — Session 2026-06-29 to 2026-06-30

### Code shipped
- **Home page redesign** (`app.py`): Replaced pipeline dashboard with "This Week"
  command centre — Mon–Sun week grid, numbered to-do list, week stats
- **Media page fix** (`6_Media.py`): Added "Hide posted drafts" toggle (default ON)
- **Performance feedback loop** (full stack):
  - `schema.sql`: New `post_performance` table
  - `scheduler.py`: Completely rewritten — fixed all sqlite3/Postgres bugs;
    added `record_performance()`, `get_performance_for_draft()`,
    `get_latest_performance_for_draft()`
  - `7_Calendar.py`: Engagement logging UI on every posted entry
- **TECH_REFERENCE_FOR_AI_AGENTS.md**: Created — technical onboarding doc

### Documents created
- `SWPI_Content_Strategy_Audit_2026-06-29.md` — devil's advocate review of the app
  vs. market, 3 pros, 3 cons, virality feature roadmap, platform expansion analysis

### Content published (2026-06-30)
- 3 posts published: 1 LinkedIn, 1 Facebook, 1 Instagram
- First SWPI brand page post live on Facebook
- Personal launch posts drafted for Jitendra's personal FB + Instagram

### Key learning from this session
`cursor.description` is not supported by this app's PostgreSQL wrapper
(`services/database.py`). Any function that builds dicts from rows must use
explicit positional mapping — never rely on cursor metadata. This was confirmed
by a production `AttributeError` on the Calendar page, fixed same session.

---

## Pending Tasks — Priority Order

### 🔴 FIRST TASK FOR NEW CHAT (see below)

**Feature #2 — Trend Signals research mode in Researcher agent**

The Strategic Audit confirmed that SWPI currently finds *relevant* content but
not *high-performing* content. The simple, legal fix is to extend the existing
Researcher agent (which already runs real web search) to support a second query
mode: instead of searching for news/studies, it searches for viral discourse —
e.g. "cricket coaching post going viral India LinkedIn 2026."

Why this is the right next build:
- Reuses existing Researcher infrastructure — near-zero new build cost
- ToS-clean (web search, not platform scraping)
- Directly addresses the "virality gap" Con #2 from the audit
- Does NOT require the performance feedback loop to be mature yet

Files likely touched: `agents/researcher.py`, `ui/pages/2_Research.py`
Always ask for real current files before editing.

---

### 🟡 AFTER TREND SIGNALS

**Feature #3 — Swipe File / Inspiration Board**
A new page where Jitendra pastes a URL or describes a post he saw go viral in his
feed. The system extracts the structural pattern (hook type, format, emotional angle,
length) and stores it as a reusable "inspiration tag" the Strategist can reference.
This is legal, doesn't copy content, and turns Jitendra's own scrolling time into
structured pipeline input.

**Feature #4 — Carousel format support in Copywriter + Media**
Static single-image posts are the lowest-performing format on Instagram and
Facebook in 2026. Carousels dominate reach. This is Con #3 from the audit.
Medium-high effort but the biggest format gap.

**Feature #5 — Performance-weighted angle scoring in Strategist**
Once `post_performance` has 4–6 weeks of real data, the Strategist can weight new
angle proposals toward patterns that historically performed better. Depends on
Feature #1 (feedback loop, now complete) having real data first.

---

### 🔵 DEFERRED (do not start yet)

**Sample SWPI academy report for LinkedIn showcase**
Strongest B2B sales tool — shows academy directors what they'd receive monthly.
Requires design work + LinkedIn post. Deferred until platform content rhythm stable.

**External client onboarding (Saviour Rescuevator)**
Pricing: Starter ₹12,000–18,000/month, Full Suite ₹38,000/month, ₹8,000 setup.
Gated: no earlier than 2 weeks of stable SWPI production use.

**WhatsApp Business (platform expansion)**
Non-obvious highest B2B leverage — Indian academy directors respond to WhatsApp
faster than LinkedIn InMail. This is a sales channel, not a content channel.
Build as a broadcast/outreach tool, not a posting pipeline.

**Newsletter and Blog pages**
Deferred until 2 weeks of stable social pipeline use. Reuses existing Researcher.

**X/Twitter**
Enormous Indian cricket conversation on X. Add after LinkedIn is mature.

**YouTube Shorts**
Requires carousel/video format support first (Feature #4). Don't add platform
before fixing the format problem.

---

## Content Strategy Rules (non-negotiable)

**LinkedIn posting rule:**
Post body = NO SWPI mention (thought leadership only).
First comment posted immediately after = SWPI product mention + sportz-well.com.

**Platform audiences:**
- LinkedIn: academy directors, head coaches, B2B operators
- Facebook: parents 30–50, decision-makers for their child's academy
- Instagram: young cricketers U10–U17 and emotionally invested parents

**Coach-first framing:** Content must never alienate academy directors or coaches.
Any angle that frames coaches negatively must be rejected or rewritten.

**BCCI/IPL/national team:** Hard-capped at 4/10 in Researcher. Off-target for
grassroots academies.

**Institutional framing:** Shardashram/Achrekar/Tendulkar referenced as philosophy
and heritage only. Never as personal credentials or lineage claims.

---

## Weekly Content Rhythm (locked in)

| Day | Task |
|-----|------|
| Sunday | Research 2 new topics |
| Monday | Strategy → approve angles → Generate drafts |
| Tuesday | Editor review → fix flagged → Approve |
| Tuesday–Saturday | Post from Calendar → Mark Posted → Log engagement numbers |

---

## Budget (all-time as of 2026-06-30)

| Period | Cost |
|--------|------|
| All sessions to 2026-05-23 | ~$2.00 |
| 2026-06-12 to 2026-06-28 | ~$0.73 |
| 2026-06-29 to 2026-06-30 (this session) | ~$0.00 (no API runs) |
| **Total all-time** | **~$7.34 (~₹697)** |

Weekly running cost: ~₹200/week (~₹800/month)
Cost per published post: ~₹27

---

## Deployment Details

- **Live URL:** https://swpi-marketing.streamlit.app
- **Platform:** Streamlit Community Cloud (free tier)
- **GitHub:** https://github.com/Sportz-Well/sportz-well-marketing (public)
- **API key:** Stored in Streamlit Cloud Secrets (never in code or GitHub)
- **Auto-deploy:** Push to `master` → live in ~2 minutes
- **Sleep:** App sleeps after inactivity, wakes in ~30 seconds
- **Manual reboot:** Streamlit Cloud dashboard → Manage app → Reboot
  (needed when auto-deploy triggers but app doesn't restart cleanly)

---

## Known Issues / Watch List

- **Strategist intermittent JSON parse failure:** Large research libraries (20+ items).
  Workaround: re-run — succeeds on retry.
- **`services/database.py` is a black box:** We have never seen this file's
  actual content. Two bugs in this session were caused by incorrect assumptions
  about its row-access behaviour. If any new agent produces unexpected
  `AttributeError` or row-access issues, request this file immediately rather
  than patching around the symptoms a third time.
- **Scheduled post dates in the past:** Several schedule entries have
  `scheduled_for` dates that have already passed. These show in Calendar View
  but show 0 in "Next 7 Days." Not a code bug — real posts were scheduled
  manually with past dates and should be marked Posted or unscheduled.

---

## How to Start the New Session

1. Read this document fully. Not skimmable — every section matters.
2. Say: "I've read CLAUDE.md. I understand the full context. The first task
   is Feature #2 — Trend Signals research mode. Ready when you are. Please
   paste `agents/researcher.py` so I can see the real current file."
3. Wait for Jitendra to paste the real file before writing any code.
4. Follow the working rules above on every task, every time.

---

*End of handover. Don't guess. Don't reconstruct from memory. Ask for real files.*
*Companion doc: TECH_REFERENCE_FOR_AI_AGENTS.md in the repository root.*