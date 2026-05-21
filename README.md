# Sportz-Well Marketing

A web app that helps a brand plan, draft, and schedule social media content.
First client: **Sportz-Well** (Indian sports performance brand) and its flagship product **SWPI** (Sportz-Well Performance Intelligence App).

V1 platforms: Instagram and Facebook. V1 generates drafts and schedules them on an internal calendar; the user copy-pastes into Meta Business Suite. API posting comes in V2 after Meta App Review.

See `CLAUDE.md` for the full architecture and build conventions.

## Folder layout

```
agents/      # the five specialized AI agents (Researcher, Strategist, Copywriter, Editor, Scheduler)
db/          # SQLite schema + init script
ui/          # Streamlit UI
services/    # shared services (Anthropic SDK wrapper, etc.)
data/        # local SQLite database files (gitignored)
```

## Quick start

See the bottom of the build prompt for exact terminal commands, or run:

```
pip install -r requirements.txt
python db/init_db.py
streamlit run ui/app.py
```

You will need an Anthropic API key in `.env` — copy `.env.example` to `.env` and paste your key.
