"""Fix script — adds init_page() to the 5 pages that missed the dark theme.

Run from the project root:  python fix_theme.py
Safe to run multiple times — skips files that are already correct.
Delete this file after running.
"""

import re
from pathlib import Path

TARGET = [
    "ui/pages/1_Brand_Brain.py",
    "ui/pages/4_Drafts.py",
    "ui/pages/6_Media.py",
    "ui/pages/7_Calendar.py",
    "ui/pages/8_Orchestrator.py",
]

IMPORT_LINE = "from services.page_utils import init_page"

for fp in TARGET:
    path = Path(fp)
    if not path.exists():
        print(f"NOT FOUND: {fp}")
        continue

    text = path.read_text(encoding="utf-8")
    mod = False

    # Step 1 — add import if missing
    if IMPORT_LINE not in text:
        text = text.replace(
            "import streamlit as st\n",
            f"import streamlit as st\n{IMPORT_LINE}\n",
            1,
        )
        mod = True

    # Step 2 — add init_page() call after set_page_config if missing
    if "init_page()" not in text:
        text = re.sub(
            r"(st\.set_page_config\(.*?\)\s*\n)",
            r"\1init_page()\n",
            text,
            flags=re.DOTALL,
        )
        mod = True

    if mod:
        path.write_text(text, encoding="utf-8")
        print(f"Fixed:    {fp}")
    else:
        print(f"OK:       {fp}")

print("\nDone. Verify with: Select-String 'init_page' ui\\pages\\1_Brand_Brain.py")