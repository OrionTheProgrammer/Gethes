from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess


def run_git(args: list[str]) -> str:
    try:
        out = subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL)
        return out.strip()
    except Exception:
        return ""


def list_commits(previous_tag: str, limit: int = 16) -> list[str]:
    if previous_tag:
        raw = run_git(["log", f"{previous_tag}..HEAD", "--pretty=format:%s"])
    else:
        raw = run_git(["log", f"-n{limit}", "--pretty=format:%s"])
    if not raw:
        return []
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    unique: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        unique.append(line)
        if len(unique) >= limit:
            break
    return unique


def previous_tag_for(current_tag: str) -> str:
    tags_raw = run_git(["tag", "--sort=-v:refname"])
    if not tags_raw:
        return ""
    tags = [line.strip() for line in tags_raw.splitlines() if line.strip()]
    if current_tag in tags:
        idx = tags.index(current_tag)
        if idx + 1 < len(tags):
            return tags[idx + 1]
    return ""


def load_custom_notes(version: str) -> str:
    candidates = [
        Path("release") / "notes" / f"v{version}.md",
        Path("release") / "notes" / f"{version}.md",
    ]
    for path in candidates:
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if text:
                return text
    return ""


def generate_body(version: str) -> str:
    custom = load_custom_notes(version)
    if custom:
        return custom

    current_tag = f"v{version}"
    previous = previous_tag_for(current_tag)
    commits = list_commits(previous, limit=14)
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = []
    lines.append(f"# Gethes v{version}")
    lines.append("")
    lines.append("## Highlights")
    if commits:
        for item in commits[:8]:
            lines.append(f"- {item}")
    else:
        lines.append("- Stability and quality improvements across gameplay, UI, and Syster.")
        lines.append("- Updated packaging and distribution pipeline.")
    lines.append("")
    lines.append("## Distribution")
    lines.append("- `Gethes-Setup-v{version}.exe`")
    lines.append("- `Gethes-v{version}-win64-portable.zip`")
    lines.append("- `SHA256SUMS-v{version}.txt`")
    lines.append("")
    lines.append("## Notes")
    lines.append("- Auto-generated release metadata by CI pipeline.")
    if previous:
        lines.append(f"- Commit range: `{previous}..{current_tag}`")
    lines.append(f"- Built: `{built_at}`")
    lines.append("")
    return "\n".join(lines).replace("{version}", version)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate release title/body markdown.")
    parser.add_argument("--version", required=True, help="Version string without leading v")
    parser.add_argument(
        "--out",
        default="release/release_body.md",
        help="Output markdown body path",
    )
    parser.add_argument(
        "--title-out",
        default="release/release_title.txt",
        help="Output title text path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = args.version.strip().lstrip("v")
    if not version:
        raise SystemExit("version is required")

    body = generate_body(version)
    title = f"Gethes v{version}"

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")

    title_path = Path(args.title_out)
    title_path.parent.mkdir(parents=True, exist_ok=True)
    title_path.write_text(title, encoding="utf-8")

    print(f"title={title}")
    print(f"body_path={out_path.resolve()}")
    print(f"title_path={title_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
