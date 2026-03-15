"""
Run from repo root:
  python clean_fix_aog.py

Removes the embedded JSX from the generator entirely and replaces it
with a simple external script tag. No escaping issues possible.
"""
import re

GENERATOR = "scripts/fleet_dashboard_generator.py"

with open(GENERATOR, "r", encoding="utf-8") as f:
    content = f.read()

# Find the babel script block containing AOGTracker
START_MARKER = '<script type="text/babel">'
END_MARKER   = "</script>"

start_idx = -1
search_from = 0
while True:
    idx = content.find(START_MARKER, search_from)
    if idx == -1:
        break
    end_idx = content.find(END_MARKER, idx + len(START_MARKER))
    block = content[idx:end_idx + len(END_MARKER)]
    if "AOGTracker" in block:
        start_idx = idx
        break
    search_from = idx + 1

if start_idx == -1:
    print("ERROR: Could not find AOGTracker babel block.")
    exit(1)

end_idx = content.find(END_MARKER, start_idx + len(START_MARKER)) + len(END_MARKER)
print(f"Found block at {start_idx}:{end_idx}")

# Replace with two simple external script tags
# The HTML is served from data/ so AOGTracker.jsx in repo root = ../AOGTracker.jsx
replacement = (
    '<script type="text/babel" src="../AOGTracker.jsx"></script>\n'
    '<script>\n'
    'setTimeout(function() {{\n'
    '  if (typeof AOGTracker !== "undefined") {{\n'
    '    ReactDOM.createRoot(document.getElementById("aog-root")).render(\n'
    '      React.createElement(AOGTracker)\n'
    '    );\n'
    '  }}\n'
    '}}, 500);\n'
    '</script>'
)

content = content[:start_idx] + replacement + content[end_idx:]

with open(GENERATOR, "w", encoding="utf-8") as f:
    f.write(content)

print("Done! Generator now loads AOGTracker.jsx as external file.")
print("Now run: python scripts\\fleet_dashboard_generator.py --config configs\\aw109sp.json")
