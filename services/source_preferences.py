"""Source domain preferences for the Researcher agent.

These are SOFT preferences — tiebreakers and nudges, never hard filters.
The agent is the final judge of content quality; these lists guide it when
two sources are otherwise similar in quality.

Public API
----------
format_source_preferences() -> str   system-prompt fragment for injection
"""

from __future__ import annotations

# +1 relevance tiebreaker when content quality is otherwise comparable
PREFERRED_DOMAINS: list[str] = [
    # Cricket authorities
    "cricbuzz.com",
    "espncricinfo.com",
    "icc-cricket.com",
    "bcci.tv",
    "mumbaicricket.com",        # MCA
    "wisden.com",
    "cricket.com.au",           # Cricket Australia
    "ecb.co.uk",                # England & Wales Cricket Board
    # Indian sports media
    "sportstar.thehindu.com",
    "indianexpress.com",
    "thebridge.in",
    "sportskeeda.com",          # small bump only — content-farm tendencies
    # Sports science / peer-reviewed journals
    "pubmed.ncbi.nlm.nih.gov",
    "journals.humankinetics.com",
    "link.springer.com",
    "sciencedirect.com",
    "jstage.jst.go.jp",
    "frontiersin.org",
]

# -2 relevance penalty — mixed or low quality; not a block
DOWNRANK_DOMAINS: list[str] = [
    "medium.com",       # highly variable quality
    "linkedin.com",     # pulse articles especially
    "quora.com",
    "reddit.com",
]


def format_source_preferences() -> str:
    """Return a formatted prompt fragment for injection into the Researcher system prompt."""
    preferred = "\n".join(f"  - {d}" for d in PREFERRED_DOMAINS)
    downranked = "\n".join(f"  - {d}" for d in DOWNRANK_DOMAINS)
    return f"""## Source Domain Preferences (soft bias — not hard filters)

**Preferred domains** — apply +1 as a tiebreaker when two sources are otherwise equal in quality:
{preferred}

**Downranked domains** — apply -2 penalty (mixed quality; do not block entirely):
{downranked}

Applying these preferences:
- A high-quality result from an unknown domain always beats a weak result from a preferred domain
- A preferred domain with thin or off-brand content should still score low
- If you include a downranked-domain source, note in relevance_reason why the content quality justifies it"""
