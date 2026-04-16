import hashlib
import os
import re
import sys

import requests
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(REPO_ROOT, "plugin", "src", "settings.yml")
README_PATH = os.path.join(REPO_ROOT, "README.md")
ASSETS_DIR = os.path.join(REPO_ROOT, "assets", "plugin-images")

BADGE_BASE = "https://trmnl-badges.gohk.xyz/badge"
API_BASE = "https://trmnl.com/recipes"

MARKER_START = "<!-- PLUGIN_STATS_START -->"
MARKER_END = "<!-- PLUGIN_STATS_END -->"


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


CONTENT_TYPE_EXT = {
    "image/svg+xml": ".svg",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def download_image(url, dest_stem):
    """Download url, detect real type, return final path (ext may differ from stem)."""
    os.makedirs(os.path.dirname(dest_stem), exist_ok=True)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
    ext = CONTENT_TYPE_EXT.get(content_type) or os.path.splitext(url)[1] or ".png"
    dest = dest_stem if dest_stem.endswith(ext) else (os.path.splitext(dest_stem)[0] + ext)

    new_bytes = resp.content
    if os.path.exists(dest) and hashlib.md5(new_bytes).hexdigest() == md5(dest):
        return dest  # unchanged

    with open(dest, "wb") as f:
        f.write(new_bytes)
    return dest


def fetch_plugin(plugin_id):
    resp = requests.get(f"{API_BASE}/{plugin_id}.json", timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", {})


def build_section(plugin_id, data):
    if not data:
        return f"_Plugin {plugin_id} not yet published._\n\n---"

    name = data.get("name", f"Plugin {plugin_id}")
    icon_url = data.get("icon_url", "")
    screenshot_url = data.get("screenshot_url", "")
    description = (data.get("author_bio") or {}).get("description", "")

    icon_stem = os.path.join(ASSETS_DIR, f"{plugin_id}_icon.png")
    screenshot_stem = os.path.join(ASSETS_DIR, f"{plugin_id}_screenshot.png")

    icon_path = download_image(icon_url, icon_stem) if icon_url else icon_stem
    screenshot_path = download_image(screenshot_url, screenshot_stem) if screenshot_url else screenshot_stem

    icon_rel = os.path.relpath(icon_path, REPO_ROOT)
    screenshot_rel = os.path.relpath(screenshot_path, REPO_ROOT)

    lines = [
        f'## <img src="{icon_rel}" alt="{name} icon" width="32"/> [{name}](https://trmnl.com/recipes/{plugin_id})',
        "",
        f"![Installs]({BADGE_BASE}/installs?recipe={plugin_id}) ![Forks]({BADGE_BASE}/forks?recipe={plugin_id})",
        "",
        f"![{name} screenshot]({screenshot_rel})",
        "",
        "### Description",
        description,
        "",
        "---",
    ]
    return "\n".join(lines)


def update_readme(section_md):
    with open(README_PATH, "r") as f:
        content = f.read()

    if MARKER_START not in content:
        content += f"\n\n{MARKER_START}\n{MARKER_END}\n"

    pattern = re.compile(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        re.DOTALL,
    )
    replacement = f"{MARKER_START}\n{section_md}\n{MARKER_END}"
    updated = pattern.sub(replacement, content)

    with open(README_PATH, "w") as f:
        f.write(updated)


def main():
    with open(SETTINGS_PATH) as f:
        settings = yaml.safe_load(f)

    plugin_id = settings.get("id")
    if not plugin_id:
        print("No plugin ID found in settings.yml", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching plugin {plugin_id}...")
    data = fetch_plugin(plugin_id)
    section = build_section(plugin_id, data)
    update_readme(section)
    print("README updated.")


if __name__ == "__main__":
    main()
