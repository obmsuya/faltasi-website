from pathlib import Path
import py_compile
import shutil

ROOT = Path.cwd()
path = ROOT / "whatsapp" / "views.py"

if not path.is_file():
    raise SystemExit(f"Missing expected file: {path}")

content = path.read_text(encoding="utf-8")
original = content

# Fix 1: initialize reply before any route can reach the fallback.
anchor = "        if handover_language:\n"
replacement = "        reply = None\n\n" + anchor
if content.count(anchor) != 1:
    raise SystemExit(
        "Could not uniquely locate the WhatsApp routing branch. "
        "No files changed."
    )
content = content.replace(anchor, replacement, 1)

# Fix 2: an already-selected product belongs to the product workflow;
# do not invoke general-message interpretation for that conversation.
anchor = "                if detected_category is None and not current_category:\n"
replacement = (
    "                selected_product_id = (state.data or {}).get(\n"
    "                    \"selected_whatsapp_product_id\"\n"
    "                )\n"
    "\n"
    "                if (\n"
    "                    detected_category is None\n"
    "                    and not current_category\n"
    "                    and not selected_product_id\n"
    "                ):\n"
)
if content.count(anchor) != 1:
    raise SystemExit(
        "Could not uniquely locate the general AI routing condition. "
        "No files changed."
    )
content = content.replace(anchor, replacement, 1)

backup = path.with_name(path.name + ".before_whatsapp_ai_hotfix.bak")
if backup.exists():
    raise SystemExit(
        f"Backup already exists: {backup}. No files changed."
    )

shutil.copy2(path, backup)
path.write_text(content, encoding="utf-8", newline="")

try:
    py_compile.compile(str(path), doraise=True)
except Exception:
    shutil.copy2(backup, path)
    raise

print("Applied WhatsApp routing hotfix.")
print("Python syntax check passed.")
print(f"Backup: {backup}")
print("Fixes:")
print("- reply is initialized before routing/fallback.")
print("- general AI is skipped when a product is already selected.")
