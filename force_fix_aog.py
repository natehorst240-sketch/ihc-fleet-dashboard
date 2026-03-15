"""
Run from repo root:
  python force_fix_aog.py

Force-fixes curly brace escaping in the AOGTracker babel block.
"""

GENERATOR = "scripts/fleet_dashboard_generator.py"

with open(GENERATOR, "r", encoding="utf-8") as f:
    content = f.read()

START_MARKER = '<script type="text/babel">'
END_MARKER   = "</script>"

# Find the babel block that contains AOGTracker
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
old_block = content[start_idx:end_idx]

print(f"Found block at index {start_idx}, length {len(old_block)}")

# Step 1: normalize — unescape any existing {{ }} back to { }
normalized = old_block.replace("{{", "\x00LBRACE\x00").replace("}}", "\x00RBRACE\x00")
normalized = normalized.replace("\x00LBRACE\x00", "{").replace("\x00RBRACE\x00", "}")

# Step 2: re-escape all { } to {{ }}
escaped = normalized.replace("{", "{{").replace("}", "}}")

content = content[:start_idx] + escaped + content[end_idx:]

with open(GENERATOR, "w", encoding="utf-8") as f:
    f.write(content)

print("Done! AOGTracker block re-escaped cleanly.")
print("Now run: python scripts\\fleet_dashboard_generator.py --config configs\\aw109sp.json")
