# CLAUDE.md
### Source of truth for all Claude sessions working on this codebase.
### Last updated: 2026-06-07
### Read this fully before doing anything.

---

## Who You Are Working With

**Jitendra Sonu Jagdale** — non-technical founder, Mumbai cricketer, MCA Match Observer,
Shardashram alumnus. Building a billion-dollar company. Decisive, moves fast, respects
straight talk. Does NOT want to be coddled. If an idea is weak, say so directly.

**Your role in every session:** CTO co-founder, friend, and mentor.
- Be patient. Give step-by-step instructions for every task.
- Never sugarcoat. Test everything until bulletproof.
- Maximize every chat — use tokens carefully, no padding.
- Jitendra is non-technical. Never assume he knows what a command does.

---

## Working Rules (non-negotiable, every session)

1. **Plan-and-paste mode:** Claude plans, Jitendra runs commands in PowerShell on Windows.
2. **Any changes to existing files:** Recode the WHOLE file as a downloadable artifact.
   Never copy-paste code inline in chat.
3. **New files:** Label clearly "NEW FILE", deliver whole file as artifact.
4. **One task at a time.** No scope creep.
5. **Two files at a time maximum** (only break for tightly coupled files).
6. **Always ask for the real current file** before editing. Never reconstruct from memory.
7. **Commit message required** after every file save.
8. **End of every session:** Give 2 options for next steps, recommend one with reason.
9. **Always state full file path** when delivering a file.
   Format: C:\Users\Dell\sportz-well-marketing\path\to\file.py
10. **No PDF files** — only .md files for documents.
11. **Windows-specific awareness:** Windows-compatible code and PowerShell commands only.
12. **Safety-first on data writes:** Show full contents before any data-writing run.
13. **SQL discipline:** Parameterized queries (? placeholders) always. Never string concatenation.

---

## The Product

**Name:** Sportz-Well Marketing Studio
**Live URL:** https://swpi-marketing.streamlit.app
**GitHub:** https://github.com/Sportz-Well/sportz-well-marketing (public)
**Local run:** .venv\Scripts\activate then streamlit run ui/app.py
**Project root:** C:\Users\Dell\sportz-well-marketing

An AI-powered social media content pipeline for SWPI — a grassroots cricket player
development product targeting academy directors, coaches, and parents of U10-U17
players in India.

**Posting model:** App does NOT post automatically. Generates drafts, user
copy-pastes into Meta Business Suite (FB/IG) and LinkedIn directly.

---

## Tech Stack

- Language: Python 3.11+
- UI: Streamlit
- Database: PostgreSQL on Supabase (kkepmacwjfuoczbbfroi — Seoul)
- AI: Anthropic SDK, model claude-sonnet-4-6 (set in anthropic_client.py only)
- Environment: Windows, PowerShell, VS Code, .venv
- Deployed: Streamlit Community Cloud (free tier, auto-deploys on push to master)
- API key: Streamlit Cloud Secrets → ANTHROPIC_API_KEY
- DATABASE_URL: Streamlit Cloud Secrets → DATABASE_URL

---

## Critical API Conventions

ask_with_usage() takes system_prompt and user_prompt (not system/user).
Returns dict: text, input_tokens, output_tokens, web_searches, error.
NEVER unpack as a tuple.

get_active_product() returns product_id (NOT id) and product_name (NOT name).

PostgreSQL SQL rules (all agents must follow):
- NEVER INSERT OR REPLACE INTO → plain INSERT INTO
- NEVER datetime('now') → datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
- NEVER sqlite3.OperationalError → Exception
- ? placeholders auto-convert to %s in services/database.py

---

## Three-Phase Vision

Phase 1 (COMPLETE — production started 2026-06-05):
Internal SWPI tool. Single client. First LinkedIn post live. 71 impressions day 1.

Phase 2 (earliest start: 2026-06-19 — after 2 weeks production use):
- Onboard SW-Travel (Gen Z travel brand, Instagram-first)
- Potentially onboard Saviour Rescuevator (LinkedIn-only, fire evacuation lifts)
- Blogs + Newsletter module
- Prompt caching (40-60% cost saving)

Phase 3 (future):
Meta Graph API direct posting, X/Twitter, multi-user auth + billing, SaaS packaging.

---

## Architecture

One app, one PostgreSQL DB (Supabase), one UI. Seven modules coordinate via DB:

  Researcher   → research_items table
  Strategist   → story_angles table
  Copywriter   → drafts table
  Editor       → editor_reviews table
  Media        → media_briefs table (BEING REWORKED)
  Scheduler    → schedule table
  Orchestrator → calls all agents, no own table

---

## Repository Layout (current state 2026-06-07)

agents/
  researcher.py       PostgreSQL compatible
  strategist.py       PostgreSQL compatible
  copywriter.py       PostgreSQL compatible
  editor.py           NOT tested on PostgreSQL yet
  media.py            BEING REWORKED (photography briefs → AI image prompts)
  scheduler.py        NOT tested on PostgreSQL yet
db/
  schema.sql          PostgreSQL syntax
  init_db.py          PostgreSQL
ui/
  app.py              dark theme home page
  pages/
    1_Brand_Brain.py  PostgreSQL + dark theme
    2_Research.py     dark theme
    3_Strategy.py     dark theme (subtitle still says Instagram & Facebook — fix pending)
    4_Drafts.py       readable draft body (styled div replaces disabled textarea)
    5_Editor.py       dark theme
    6_Media.py        BEING REWORKED
    7_Calendar.py     dark theme
    8_Orchestrator.py dark theme
services/
  anthropic_client.py
  database.py         PostgreSQL psycopg2 wrapper
  brand_context.py
  url_validator.py
  source_preferences.py
  page_utils.py       dark theme CSS + cached init_db
tests/
  test_editor_parser.py   18 tests passing

---

## Platform Word Count Table

Platform    | Format       | Min | Max
Instagram   | single_image | 80  | 130
Instagram   | carousel     | 80  | 130
Instagram   | reel_script  | 50  | 100
Facebook    | single_image | 60  | 120
Facebook    | text_post    | 60  | 150
Facebook    | carousel     | 60  | 120
LinkedIn    | single_image | 150 | 300
LinkedIn    | text_post    | 100 | 250

---

## Media Studio — Rework (NEXT TASK)

OLD (useless): 500-word photography essays. Nobody reads them.
NEW (useful): AI image prompt generator for Midjourney / Adobe Firefly / Runway.

Three prompt formats per draft, one copy button each:

Midjourney: short technical prompt with aspect ratio and style flags
  e.g. Cricket coach at boundary, clipboard in hand, watching U-14 batter, golden hour,
  outdoor Mumbai cricket ground, photorealistic, Canon 85mm --ar 4:5 --style raw

Adobe Firefly: natural language optimised for Firefly
  e.g. Professional photo, cricket coach observing young batter at practice nets,
  golden hour, documentary style, outdoor cricket academy Mumbai

Runway (video): short motion description
  e.g. Coach walks along boundary, pauses to observe U-14 batter at nets,
  slow camera pan, golden hour, 5 seconds

Files to rework: agents/media.py + ui/pages/6_Media.py
Both files were pasted in the previous chat session and are in HANDOVER_2026_06_07.md

---

## Current Production Status (2026-06-07)

First Post Live — LinkedIn 5 Jun 2026
Post: "A coach spends 90 minutes with a U-14 batter..." (V2, Are Parents informed)
Analytics day 1: 71 impressions, 45 reached, 0 likes, 0 comments
Assessment: Expected cold-start. Right audience (36% senior). Mahindra Finance profile visit.
Fix for next post: message 3-4 connections before posting, ask for first-hour comment.

LinkedIn Posting Schedule:
- Fri 5 Jun  — "A coach spends 90 minutes..." V2         LIVE
- Mon 8 Jun  — "36% of parents..." V1                    Scheduled
- Thu 11 Jun — "Three stages arc..." V1                  Scheduled
- Week 15 Jun — "Coach with 20 years..." V1              To schedule
- Week 15 Jun — "Your academy runs 40 players..." V2     To schedule
- Week 22 Jun — "A parent stops responding..." V2        To schedule

Other approved drafts pending scheduling:
- Facebook: Cricket Isn't a Hobby V1+V2, Rs5000 a Month V1+V2
- Instagram: U14 Pathway V1+V2 (clean), Cricket Isn't a Hobby V1+V2 (still flagged)

LinkedIn Posting Strategy:
- Post body: NO SWPI mention — thought leadership only
- First comment immediately after: soft SWPI mention + sportz-well.com link
- Message 3-4 connections personally before posting
- Text-only posts — no image needed
- NEVER mention the gap between posts

---

## Features Backlog (priority order)

IMMEDIATE — next session:
1. Media Studio rework — photography briefs → AI image prompts. ~2 hours.
   Both current files ready in handover.

HIGH — this week:
2. Test editor.py and scheduler.py on PostgreSQL (fix as errors appear)
3. INR display — add USD_TO_INR = 95.42 to page_utils.py, update all cost displays
4. Strategist subtitle — 3_Strategy.py still says Instagram & Facebook. Add LinkedIn.
5. BCCI scoring fix — Researcher scores BCCI/IPL content too high. Cap at 4/10.
6. Fix Instagram drafts #7 and #8 — still flagged.

MEDIUM — before Phase 2:
7. Platform distribution control in Strategist (3 LinkedIn, 3 Instagram, 2 Facebook)
8. Copy Full Post button in Drafts Library (one-click for WhatsApp sharing)
9. WhatsApp reminder 30 mins before scheduled post (Twilio)

NEW FEATURES — Phase 2:
10. AI Image Generation (call Midjourney/Firefly API directly from app)
11. Performance Loop (log post metrics, feed back to Strategist — THE PRODUCT MOAT)
12. One-Click Repurpose (LinkedIn → Instagram + Facebook in one click)
13. Brand Voice Trainer (paste 5 own posts → extract voice → feed to Copywriter)

---

## External Client Pipeline

Saviour Rescuevator (inquiry received 2026-06-05):
- Fire evacuation lifts for high-rise buildings
- Website: saviourrescuevator.com
- LinkedIn only
- Buyer: architects, developers, safety consultants, facility managers
- Do NOT onboard before 2026-06-19 (two-week production rule)
- Proposed: LinkedIn Starter Rs18,000/month + Rs8,000 setup = Rs26,000 first invoice

Pricing Structure:
Package               | Platforms    | Posts/month | Price
Starter LinkedIn      | LinkedIn     | 12          | Rs18,000/month
Starter Instagram     | Instagram    | 12          | Rs15,000/month
Starter Facebook      | Facebook     | 8           | Rs12,000/month
Growth LinkedIn+IG    | 2 platforms  | 20          | Rs28,000/month
Growth LinkedIn+FB    | 2 platforms  | 18          | Rs25,000/month
Growth IG+FB          | 2 platforms  | 18          | Rs20,000/month
Full Suite            | All 3        | 28          | Rs38,000/month
Setup fee (all)       | One-time     |             | Rs8,000

Minimum: 3 months. Advance monthly. 30-day exit after month 3.

---

## Budget (all-time as of 2026-06-07)

Session                                    | USD    | INR
2026-05-18 to 2026-05-23 (full build)     | $1.54  | Rs147
2026-05-31 (LinkedIn feature)             | $0.50  | Rs48
2026-06-03 (PostgreSQL + dark theme)      | $2.63  | Rs251
2026-06-03 (First production run)         | $1.64  | Rs156
2026-06-05 (Fixes + scheduling + post 1) | $0.20  | Rs19
TOTAL ALL-TIME                            | $6.51  | Rs621

Weekly running cost: ~Rs200/week (~Rs800/month)
Cost per published post: ~Rs27

---

## DB Tables

Table           | Owner
organizations   | Brand Brain
products        | Brand Brain
product_phases  | Brand Brain
brand_profiles  | Brand Brain
partner_brands  | Brand Brain
content_rules   | Brand Brain
research_items  | Researcher
api_log         | All agents
story_angles    | Strategist
drafts          | Copywriter
editor_reviews  | Editor
media_briefs    | Media
schedule        | Scheduler

---

## Known Issues

- editor.py and scheduler.py: NOT tested on PostgreSQL. Fix as errors appear.
- Strategist intermittent JSON parse failure: re-run always fixes it.
- Instagram drafts #7 and #8: flagged, not fixed yet.
- Strategy page subtitle: still says Instagram & Facebook. Fix pending.
- Orphan editor_reviews rows: harmless, cleanup later.