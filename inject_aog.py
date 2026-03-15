"""
Run this once from your repo root:
  python inject_aog.py

It injects the AOGTracker component into fleet_dashboard_generator.py.
"""
import re

GENERATOR = "scripts/fleet_dashboard_generator.py"
JSX_FILE  = "AOGTracker.jsx"

# Read files
with open(GENERATOR, "r", encoding="utf-8") as f:
    gen = f.read()

with open(JSX_FILE, "r", encoding="utf-8") as f:
    jsx = f.read()

# Strip the import line and export default
jsx = re.sub(r"^import.*\n", "", jsx, flags=re.MULTILINE)
jsx = jsx.replace("export default function AOGTracker", "function AOGTracker")

# Prepend hook destructure, append render call
jsx = "const { useState, useEffect, useCallback } = React;\n" + jsx
jsx = jsx + "\nReactDOM.createRoot(document.getElementById('aog-root')).render(<AOGTracker />);"

# IMPORTANT: The generator uses Python f-strings, so { and } in the JSX
# must be doubled to {{ and }} so Python doesn't treat them as f-string expressions.
jsx_escaped = jsx.replace("{", "{{").replace("}", "}}")

# Build the replacement script block
new_block = '<script type="text/babel">\n' + jsx_escaped + '\n</script>'

# Find and replace the placeholder block
old_block = """<script type="text/babel">
// --- paste entire contents of AOGTracker.jsx here ---
// Then at the very bottom of the pasted code, replace "export default function AOGTracker()" 
// with just "function AOGTracker()" and add this after the closing brace:

ReactDOM.createRoot(document.getElementById('aog-root')).render(<AOGTracker />);
</script>"""

if old_block not in gen:
    print("ERROR: Could not find the placeholder block in the generator.")
    print("Make sure the generator still has the original placeholder comment.")
    exit(1)

gen = gen.replace(old_block, new_block)

with open(GENERATOR, "w", encoding="utf-8") as f:
    f.write(gen)

print("Done! AOGTracker injected into", GENERATOR)
print("Now run: python scripts/fleet_dashboard_generator.py --config configs/aw109sp.json")