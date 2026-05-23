# SWPI Social Media Marketing App
## Standard Operating Procedure (SOP)
### For: Jitendra (and anyone operating this app)
### Plain English — no jargon

---

## What this app does

This app helps you create, review, and schedule social media posts for SWPI on Instagram and Facebook.

You give it topics to research. It finds relevant articles, turns them into post ideas, writes the actual posts, checks them for quality, and helps you plan when to publish them.

**You are always in control.** The app never posts anything automatically. You review and approve every step.

---

## Before you start — the one rule

**This app costs money every time it calls the AI.** Not a lot (~$0.03–0.10 per run) but it adds up if you run things carelessly.

The expensive steps are: Research, Strategy, Drafts, and Editor.
The free steps are: Calendar and Orchestrator setup.

**Golden rule: Always check the Pipeline Status on the home page before running anything. If you already have research items, don't research again. If you already have approved angles, don't run strategy again.**

---

## How to start the app

1. Open **PowerShell** (search for it in the Windows Start menu)
2. Type this and press Enter:
   ```
   cd C:\path\to\your\project
   ```
   (Replace with the actual folder where your project lives)
3. Type this and press Enter:
   ```
   streamlit run ui/app.py
   ```
4. Your browser will open automatically showing the app.
5. To stop the app: go back to PowerShell and press **Ctrl + C**

---

## The 7 pages explained

The app has 8 pages in the left sidebar. Here's what each one does and when to use it.

---

### Page 1 — 🏠 Home (Sportz-Well Marketing Studio)

**What it is:** Your dashboard. Shows the current status of everything.

**When to use it:** Every time you open the app, start here. Check the coloured status boxes — they tell you if anything needs your attention.

**What the status boxes mean:**
- Green box = something is ready and waiting for you to use it
- Orange/yellow box = something needs your attention
- Blue box = information only

**Pipeline Status row at the top of the Orchestrator page shows:**
- How many research items you have
- How many angles are approved
- How many drafts exist
- How many are reviewed
- How many media briefs exist
- How many posts are scheduled

---

### Page 2 — 🧠 Brand Brain

**What it is:** The "brain" of the app. Stores everything about SWPI — the brand voice, what topics to write about, what to avoid, proof points, CTA links.

**When to use it:** Rarely. The brand profile is already set up. Only go here if you want to:
- Change something about how SWPI is described
- Update the website URL or CTA
- Add a partner brand
- Check what the current brand rules are

**Tabs inside:**
- **Tab A (Overview):** Read-only view of everything. Good for checking what's set.
- **Tab B (Edit):** Change brand details. Be careful here — changes affect all future posts.
- **Tab C (Partners):** Add/remove partner brands.
- **Tab D (Seed Data):** Only use this on a fresh install to set up SWPI from scratch.

**Warning:** Do not change the brand voice or proof points casually. Every AI-generated post is based on what's in here. If you change it, future posts will sound different.

---

### Page 3 — 🔍 Research

**What it is:** Sends the AI to search the web for relevant articles, studies, and news about topics you care about.

**When to use it:** When you want fresh content ideas. Run research on a topic → the AI finds 5–8 relevant articles → those articles become the raw material for your posts.

**How to use it:**

1. Click **Tab A (Run Research)**
2. Type a topic in the box. Examples:
   - `grassroots cricket academy development India`
   - `coach parent communication youth sports`
   - `mental toughness training young cricketers`
   - `cricket selection trials under-16 India`
3. Choose **Geography** — keep it on "Indian-heavy (3:2)" for SWPI
4. Keep **Max items** at 6–8
5. Keep **Min relevance** at 7
6. Click **Run Research**
7. Wait 30–60 seconds
8. You'll see: "Saved X items" with a cost figure

**Cost:** ~$0.50–0.80 per research run (web search is the expensive part)

**Tab B (Library):** See all your saved research items. You can filter by topic, score, or geography. Delete items that aren't useful.

**Tab C (API Spend):** See how much you've spent this month.

**Good topics to research for SWPI:**
- Cricket academy management India
- Youth athlete development science
- Parent communication sports coaching
- Cricket coaching methodology India
- AI in sports coaching

**Bad topics (waste of money):**
- Your own website URL
- Generic terms like "cricket" or "sports"
- Topics about professional/national teams

---

### Page 4 — 📐 Strategy

**What it is:** Takes all your saved research items and turns them into post ideas called "story angles."

**When to use it:** After you have at least 6–8 research items saved. Run this to get post ideas.

**How to use it:**

1. Click **Tab A (Run Strategist)**
2. Check the green box — it should say "16 research items available" (or however many you have)
3. Leave sliders at default (7 relevance, 12 angles)
4. Optionally type a focus in the box — e.g. "focus on parent communication this round"
5. Click **Propose Story Angles**
6. Wait 30–60 seconds
7. You'll see angles grouped by theme

**Cost:** ~$0.07–0.15 per strategy run

**After running — go to Tab B (Story Angles Library):**
- Read each angle carefully
- Click **Approve** on the ones you like
- Click **Reject** on the ones you don't want
- You can click **Edit** to change the angle's description before approving

**Only approved angles get turned into posts.** Reject anything that doesn't feel right for SWPI.

**Tab C (Pipeline Overview):** Shows how many angles are approved, rejected, etc.

---

### Page 5 — ✍️ Drafts

**What it is:** Takes your approved story angles and writes the actual Instagram and Facebook posts — two versions of each post (called variants).

**When to use it:** After you have approved story angles in Strategy.

**How to use it:**

1. Click **Tab 1 (Generate Drafts)**
2. You'll see how many approved angles are waiting
3. Click **Generate ALL Approved Angles**
4. Wait 1–3 minutes (it runs each angle one by one)
5. You'll see a success message with how many drafts were created

**Cost:** ~$0.03–0.08 per angle (2 variants per platform = 4 posts per angle if targeting both platforms)

**After generating — go to Tab 2 (Drafts Library):**
- Read each draft carefully
- Check the headline, body, CTA, and hashtags
- If you like it: click **Approve**
- If it has problems: click **Edit** and fix it, or click **Reject**
- Only approved drafts can be scheduled

**What "V1" and "V2" mean:** Each angle produces 2 versions (Variant 1 and Variant 2). They cover the same topic but with different hooks and perspectives. Pick the one you prefer, or approve both.

**Tab 3 (Pipeline Overview):** Shows coverage — how many angles have drafts, how many don't.

---

### Page 6 — 🔎 Editor

**What it is:** An AI quality checker that reads each draft and flags problems. It never rewrites — it just tells you what's wrong.

**When to use it:** After generating drafts. Run the Editor before approving anything.

**How to use it:**

1. Click **Tab 1 (Review Drafts)**
2. Click **Review All Unreviewed Drafts**
3. Wait — it reviews each draft one by one (~$0.027 per draft)
4. You'll see results: Clean (no problems) or Flagged (has issues)

**After reviewing — go to Tab 2 (Editor Library):**
- Green = Clean. Safe to approve.
- Red flag = Flagged. Open it and read the issues.
- Common issues and what they mean:
  - **CAPTION_TOO_SHORT / TOO_LONG:** Post is slightly outside the word limit. Easy fix — edit a sentence.
  - **HYPE_WORD:** Used a banned word like "game-changing" or "revolutionary." Edit the draft to remove it.
  - **GENERIC_HOOK:** The opening line is too vague. Edit to make it more specific.
  - **URL_FORMAT:** The website link is formatted wrong. Should be `sportz-well.com` not `www.sportz-well.com`.

**Important:** A flagged draft is not necessarily bad. Minor issues (2 words over the limit) can be ignored and the draft approved anyway. Major issues (hype words, wrong URLs) should be fixed.

**Tab 3 (Pipeline Overview):** Shows all issues across all drafts with a histogram.

---

### Page 7 — 📸 Media Studio

**What it is:** Takes each draft's image description and turns it into a detailed brief for your photographer — telling them exactly what to shoot.

**When to use it:** After drafts are reviewed and approved. Before you plan your photo shoot.

**How to use it:**

1. Click **Tab 1 (Generate)**
2. Click **Generate All Pending Briefs**
3. Wait — takes ~10 seconds per draft
4. Cost: ~$0.018 per brief

**After generating — go to Tab 2 (Library):**
- Read each brief
- It tells the photographer: what type of shot, who/what to photograph, where, lighting, props, what to avoid
- Click **Approve** if the brief looks good
- Click **Reject** if it's not right and regenerate

**Give the approved briefs to your photographer or content team** before the shoot. They contain everything needed to produce a matching visual.

---

### Page 8 — 🗓 Calendar

**What it is:** Your content calendar. Schedule approved drafts to specific dates and times.

**When to use it:** After drafts are approved and reviewed. Use this to plan your posting schedule.

**How to use it:**

**Tab 1 (Schedule a Draft):**
1. Pick a draft from the dropdown (only approved, unscheduled drafts appear here)
2. Pick a date
3. Pick a time (use your preferred posting time — e.g. 9:00 AM)
4. Click **Confirm Schedule**

**Tab 2 (Calendar View):**
- See all scheduled posts by week or month
- When you've actually posted something to Meta Business Suite: click **Mark Posted**
- Need to change the date? Click **Reschedule**
- Changed your mind? Click **Unschedule**

**Tab 3 (Pipeline Overview):**
- See how many approved drafts are scheduled vs waiting
- Health check tells you if you're on track

**Remember:** This app schedules the post in its own calendar. You still need to manually copy-paste the post into Meta Business Suite and publish it there. Click "Mark Posted" in this app after you've done that.

---

### Page 9 — 🎛 Orchestrator

**What it is:** The control panel. Run individual stages or the full pipeline from one place. Also shows the Pipeline Status snapshot.

**When to use it:** When you want to run multiple stages quickly, or check the overall status of everything.

**Tab 1 (Full Pipeline Run):**
- Runs Research + Strategy automatically
- Then pauses and asks you to approve angles before continuing
- Use this at the start of a new content batch

**Tab 2 (Run Individual Stage):**
- Pick any single stage and run just that one
- Useful when you want to, for example, just run the Editor or just generate Media briefs
- Each stage shows you the cost estimate before you run

---

## Weekly workflow — the recommended routine

Here's how to use this app on a weekly basis to produce a batch of posts:

### Step 1 — Research (Monday, 10 minutes)
1. Open app → go to **Research**
2. Run 2 research topics relevant to what's happening in cricket/sports this week
3. Check the library — delete anything irrelevant

### Step 2 — Strategy (Monday, 5 minutes + review)
1. Go to **Strategy** → Run Strategist
2. Read the proposed angles
3. Approve 4–6 angles you want to post this week
4. Reject the rest

### Step 3 — Drafts (Monday or Tuesday, 5 minutes)
1. Go to **Drafts** → Generate ALL
2. Wait for drafts to generate
3. Read each draft → approve or edit

### Step 4 — Editor (Tuesday, 10 minutes)
1. Go to **Editor** → Review All
2. Fix any flagged issues in the drafts
3. Approve the clean drafts

### Step 5 — Media briefs (Tuesday, 5 minutes)
1. Go to **Media Studio** → Generate All
2. Read the briefs → approve
3. Send approved briefs to your photographer

### Step 6 — Schedule (Wednesday, 10 minutes)
1. Go to **Calendar** → Schedule a Draft
2. Schedule each approved draft across the week/month
3. Aim for: 3–4 posts per week, mix of Instagram and Facebook

### Step 7 — Post (ongoing)
1. On the scheduled day: open Meta Business Suite
2. Copy the post text from this app (Calendar → click on the post)
3. Paste into Meta Business Suite, add the photo, publish
4. Come back to this app → Calendar → Mark Posted

---

## Troubleshooting — common problems

**"No approved, unscheduled drafts found" on Calendar page**
→ Your drafts haven't been approved yet. Go to Drafts → approve some drafts first.

**"Strategy run failed: Could not parse response as JSON"**
→ This happens occasionally. Just click "Propose Story Angles" again. It usually works on retry.

**Draft is flagged by Editor for CAPTION_TOO_SHORT (e.g. 148 words, needs 150)**
→ Open the draft → click Edit → add one sentence to the body → save → re-review. Or just approve it anyway — 2 words short is not a real problem.

**"No active product found"**
→ Go to Brand Brain → Tab D → click "Seed Sportz-Well Data". This sets up SWPI as the active client.

**The app won't start / PowerShell shows an error**
→ Make sure your virtual environment is active. In PowerShell run:
```
.venv\Scripts\activate
streamlit run ui/app.py
```

**Research is costing too much**
→ You're running too many research topics. 2 topics per week is enough. Each topic costs ~$0.50–0.80.

**I accidentally ran Strategy twice and got duplicate angles**
→ Go to Strategy → Story Angles Library → reject the duplicates. They won't be drafted.

---

## Cost guide — what to expect per week

| Action | Approx cost |
|--------|-------------|
| 1 research topic (6–8 items) | ~$0.60 |
| 1 strategy run (10–12 angles) | ~$0.10 |
| Drafts for 5 angles (both platforms) | ~$0.40 |
| Editor review of 10 drafts | ~$0.27 |
| Media briefs for 10 drafts | ~$0.18 |
| **Full week batch (5 angles, 10 drafts)** | **~$1.50** |

Monthly budget estimate: ~$6–8 for a consistent 3–4 posts/week schedule.

---

## What NOT to do

- ❌ Don't put your website URL as a research topic
- ❌ Don't run Research, Strategy, and Drafts back-to-back without reviewing in between — you'll generate content you didn't want
- ❌ Don't approve a draft just to clear the queue — only approve posts you'd actually publish
- ❌ Don't change the Brand Brain profile casually — it affects every future post
- ❌ Don't skip the Editor step — it catches real problems before they go live
- ❌ Don't forget to click "Mark Posted" in Calendar after publishing — it keeps your pipeline accurate

---

## Glossary — words used in the app

| Word | What it means |
|------|--------------|
| **Research item** | One article or source the Researcher agent found |
| **Story angle** | A post idea — a topic + hook + brief for the Copywriter |
| **Draft** | An actual written post — ready to copy-paste |
| **Variant** | One of two versions of the same draft (V1 or V2) |
| **Editor review** | The quality check on a draft — Clean or Flagged |
| **Media brief** | Instructions for the photographer for a specific post |
| **Schedule entry** | A draft assigned to a specific date and time |
| **Mark Posted** | Confirming you've published the post on Meta Business Suite |
| **Approved** | You've reviewed and accepted this item — it moves to the next stage |
| **Proposed** | The AI created it but you haven't reviewed it yet |
| **Flagged** | The Editor found issues — needs your attention |
| **Clean** | The Editor found no issues — good to go |
| **Hard issue** | A real problem that should be fixed before publishing |
| **Soft issue** | A minor concern — use your judgment |
| **product_id** | Internal database ID for SWPI — you never need to type this |
| **CTA** | Call to Action — the line inviting people to book a demo or visit the website |
| **Platform** | Instagram or Facebook |
| **Phase 1** | SWPI's current focus: grassroots cricket, ages U10–U17 |

---

*Last updated: 2026-05-23 — Phase 1 complete.*