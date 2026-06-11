"""PR F commit 4: cache-bust lint for static HTML files.

Three assertions (pure filesystem, no network):
1. Every local /static/... .css/.js reference carries ?v= (allowlist:
   filename-versioned assets like plotly-2.35.2.min.js).
2. Shared assets appear with ONE unique ?v= value across all pages
   (version drift = stale-cache incident class; proven by deep_analysis.js).
3. Every referenced static asset exists on disk (catches typos).
"""
import re
from collections import defaultdict
from pathlib import Path

# Top-level static HTML only (mockups/ is excluded — not served in prod).
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
HTML_FILES = sorted(STATIC_DIR.glob("*.html"))

# Filename-versioned assets: the version is in the name, not a ?v= query string.
# These are intentionally allowlisted so the lint doesn't flag them.
FILENAME_VERSIONED = frozenset({
    "plotly-2.35.2.min.js",
})

# Regex: captures the asset path (group 1) and optional ?v= query (group 2)
_REF_RE = re.compile(
    r"""(?:href|src)=['"](/static/[^\s'"?#]+\.(css|js))(\?v=[^\s'"#]+)?""",
    re.IGNORECASE,
)


def _collect_refs():
    """Return list of (html_file, asset_path, version_or_None) for all refs."""
    refs = []
    for html in HTML_FILES:
        text = html.read_text(encoding="utf-8")
        for m in _REF_RE.finditer(text):
            asset_path = m.group(1)          # e.g. /static/css/styles.css
            version    = m.group(3)          # e.g. ?v=20260608a  or None
            refs.append((html.name, asset_path, version))
    return refs


def test_all_local_refs_have_version_query_string():
    """Every local /static/*.css|js ref must carry ?v= unless filename-versioned."""
    missing = []
    for html_name, asset_path, version in _collect_refs():
        basename = asset_path.rsplit("/", 1)[-1]
        if basename in FILENAME_VERSIONED:
            continue
        if version is None:
            missing.append(f"{html_name}: {asset_path} (missing ?v=)")
    assert not missing, (
        "These static asset refs are missing ?v= cache-bust query strings:\n"
        + "\n".join(f"  {m}" for m in missing)
    )


def test_shared_assets_have_consistent_version_across_pages():
    """Each asset basename must appear with exactly ONE ?v= value across all pages.

    Version drift is the deep_analysis.js incident class: one page gets a new
    build while others keep the old hash, silently serving stale cached bundles.
    """
    versions: dict[str, set[str]] = defaultdict(set)
    for html_name, asset_path, version in _collect_refs():
        basename = asset_path.rsplit("/", 1)[-1]
        if basename in FILENAME_VERSIONED or version is None:
            continue
        versions[basename].add(version)

    drifted = {k: v for k, v in versions.items() if len(v) > 1}
    assert not drifted, (
        "These assets have inconsistent ?v= versions across pages (cache drift):\n"
        + "\n".join(f"  {k}: {sorted(v)}" for k, v in sorted(drifted.items()))
    )


def test_all_referenced_assets_exist_on_disk():
    """Every /static/... asset referenced in HTML must exist on the filesystem."""
    missing = []
    seen = set()
    for html_name, asset_path, _version in _collect_refs():
        # Strip leading /static/ to get path relative to STATIC_DIR.
        rel = asset_path.removeprefix("/static/")
        if rel in seen:
            continue
        seen.add(rel)
        if not (STATIC_DIR / rel).exists():
            missing.append(f"{html_name}: {asset_path}")
    assert not missing, (
        "These referenced static assets do not exist on disk:\n"
        + "\n".join(f"  {m}" for m in missing)
    )
