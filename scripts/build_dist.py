"""Build release artefacts into dist/.

- dist/lorekeeper-plugin.zip: the plugin (skills, scripts, spec, templates).
- dist/skills/<skill>.zip: each skill on its own, with the scripts, spec and
  templates copied inside, for apps where skills are uploaded one at a time.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PLUGIN_PARTS = [".claude-plugin", "skills", "scripts", "spec", "templates", "README.md", "LICENSE",
                "requirements.txt"]
SCRIPT_SKIP = {"build_dist.py"}


def _add(z: zipfile.ZipFile, src: Path, arc: str) -> None:
    if src.is_dir():
        for p in sorted(src.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.name not in SCRIPT_SKIP:
                z.write(p, f"{arc}/{p.relative_to(src).as_posix()}")
    else:
        z.write(src, arc)


def build() -> list[Path]:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "skills").mkdir(parents=True)
    out = []
    plugin = DIST / "lorekeeper-plugin.zip"
    with zipfile.ZipFile(plugin, "w", zipfile.ZIP_DEFLATED) as z:
        for part in PLUGIN_PARTS:
            _add(z, ROOT / part, f"lorekeeper/{part}")
    out.append(plugin)
    for skill in sorted((ROOT / "skills").iterdir()):
        if not (skill / "SKILL.md").exists():
            continue
        p = DIST / "skills" / f"{skill.name}.zip"
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            _add(z, skill, skill.name)
            _add(z, ROOT / "scripts", f"{skill.name}/scripts")
            _add(z, ROOT / "templates", f"{skill.name}/templates")
            z.write(ROOT / "spec" / "VAULT.md", f"{skill.name}/references/VAULT.md")
        out.append(p)
    return out


if __name__ == "__main__":
    for p in build():
        print(f"{p.relative_to(ROOT)}  {p.stat().st_size // 1024} KB")
    sys.exit(0)
