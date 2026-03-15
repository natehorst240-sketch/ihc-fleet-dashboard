"""
Run from repo root:
  python fix_aog_escaping.py

Finds the <script type="text/babel"> block in the generator that contains
the AOGTracker JSX and re-escapes all { } to {{ }} so Python f-strings work.
"""

GENERATOR = "scripts/fleet_dashboard_generator.py"

with open(GENERATOR, "r", encoding="utf-8") as f:
    content = f.read()

START = '<script type="text/babel">\nconst { useState'
END   = '\nReactDOM.createRoot(document.getElementById(\'aog-root\')).render(<AOGTracker />);\n</script>'

start_idx = content.find(START)
end_idx   = content.find(END)

if start_idx == -1 or end_idx == -1:
    print("ERROR: Could not find the AOGTracker babel block.")
    print("start found:", start_idx != -1)
    print("end found:  ", end_idx != -1)
    exit(1)

end_idx += len(END)

old_block = content[start_idx:end_idx]

# Check if already escaped (if {{ exists, it's already been escaped)
if "{{" in old_block:
    print("Block already appears to be escaped. Nothing to do.")
    exit(0)

# Escape { and } to {{ and }}
new_block = old_block.replace("{", "{{").replace("}", "}}")

content = content[:start_idx] + new_block + content[end_idx:]

with open(GENERATOR, "w", encoding="utf-8") as f:
    f.write(content)

print("Done! Curly braces escaped in the AOGTracker block.")
print("Now run: python scripts\\fleet_dashboard_generator.py --config configs\\aw109sp.json")
