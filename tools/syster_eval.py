from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import statistics
import sys
import time

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from gethes.runtime_paths import user_data_dir
from gethes.syster import SysterAssistant, SysterContext
from gethes.syster_memory import SysterKnowledgeStore


ALLOWED_COMMANDS = (
    "help",
    "menu",
    "clear",
    "snake",
    "ahorcado1",
    "ahorcado2",
    "historia",
    "gato",
    "codigo",
    "physics",
    "roguelike",
    "daily status",
    "logros",
    "slots",
    "savegame",
    "options",
    "theme list",
    "sound on",
    "sound off",
    "graphics low",
    "graphics medium",
    "graphics high",
    "lang es",
    "lang en",
    "lang pt",
    "syster brief",
    "syster train status",
)


@dataclass
class EvalCase:
    prompt: str
    max_lines: int = 4
    max_chars: int = 620
    require_command: bool = False
    forbidden_tokens: tuple[str, ...] = ("ollama", "mistral", "api", "endpoint")


@dataclass
class EvalResult:
    prompt: str
    latency_ms: int
    score: float
    notes: str
    reply: str


def tr(key: str, **kwargs: object) -> str:
    if kwargs:
        try:
            return key.format(**kwargs)
        except Exception:
            pass
    return key


def _contains_allowed_command(reply: str) -> bool:
    lowered = reply.lower()
    for cmd in sorted(ALLOWED_COMMANDS, key=len, reverse=True):
        # Match full command tokens with optional code formatting.
        pattern = rf"(^|[^a-z0-9])`?{re.escape(cmd)}`?([^a-z0-9]|$)"
        if re.search(pattern, lowered):
            return True
    return False


def score_reply(reply: str, case: EvalCase) -> tuple[float, str]:
    cleaned = reply.strip()
    if not cleaned:
        return 0.0, "empty_reply"

    score = 1.0
    notes: list[str] = []

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    line_count = max(1, len(lines))
    if line_count > case.max_lines:
        score -= min(0.35, 0.08 * float(line_count - case.max_lines))
        notes.append(f"line_overflow:{line_count}>{case.max_lines}")

    if len(cleaned) > case.max_chars:
        overflow = len(cleaned) - case.max_chars
        score -= min(0.30, 0.0015 * float(overflow))
        notes.append(f"char_overflow:{len(cleaned)}>{case.max_chars}")

    lowered = cleaned.lower()
    found_forbidden = [token for token in case.forbidden_tokens if token in lowered]
    if found_forbidden:
        score -= min(0.45, 0.15 * float(len(found_forbidden)))
        notes.append(f"immersion_break:{','.join(found_forbidden)}")

    if case.require_command and not _contains_allowed_command(cleaned):
        score -= 0.25
        notes.append("missing_allowed_command")

    return max(0.0, round(score, 3)), ",".join(notes) if notes else "ok"


def build_cases() -> list[EvalCase]:
    return [
        EvalCase(
            prompt="Hola Syster, dame un resumen de mi progreso en 2 lineas.",
            max_lines=2,
            max_chars=320,
        ),
        EvalCase(
            prompt=(
                "Estoy bloqueado en historia. Dame una pista sin spoilers en 2 lineas y un "
                "comando valido para continuar."
            ),
            max_lines=3,
            max_chars=360,
            require_command=True,
        ),
        EvalCase(
            prompt="Dame un plan de 3 pasos para mejorar en roguelike, breve.",
            max_lines=6,
            max_chars=520,
        ),
        EvalCase(
            prompt="Estoy frustrado, dame apoyo emocional corto y accionable en 2 lineas.",
            max_lines=2,
            max_chars=300,
        ),
    ]


def run_eval(args: argparse.Namespace) -> int:
    package_dir = Path(args.package_dir).resolve()
    storage_dir = user_data_dir("Gethes")
    knowledge_dir = storage_dir / "syster"
    store = SysterKnowledgeStore(knowledge_dir)
    try:
        syster = SysterAssistant(
            mode="hybrid",
            ollama_enabled=True,
            ollama_model=args.model,
            package_dir=package_dir,
            storage_dir=storage_dir,
            knowledge_store=store,
            ollama_autostart=True,
            ollama_auto_pull=True,
        )
        profile_result = syster.optimize_for_cuda(args.profile)
        status = syster.core_runtime_status(force_probe=True)

        print("== Syster Eval ==")
        print(f"profile={profile_result.get('profile')} model={args.model}")
        print(
            "runtime: "
            f"online={status.get('online')} "
            f"state={status.get('state')} "
            f"cuda={status.get('cuda_available')} "
            f"ctx={status.get('context_length')} "
            f"kv={status.get('kv_cache_type')}"
        )

        if not status.get("online"):
            print("error: local AI runtime is offline")
            return 2
        if not status.get("model_ready"):
            print("error: model is not ready yet (try again after download finishes)")
            return 3

        context = SysterContext(
            slot_id=1,
            route_name="Origen",
            story_page=4,
            story_total=12,
            achievements_unlocked=9,
            achievements_total=32,
            rogue_runs=7,
            rogue_wins=2,
            rogue_best_depth=10,
            last_command="historia",
            player_name=args.player,
            language="es",
            active_theme="obsidian",
            sound_enabled=True,
            graphics_level="high",
            ui_scale=1.2,
            recent_commands=["menu", "historia", "roguelike", "logros"],
            recent_events=["intro_played", "chapter_2_unlocked"],
            best_scores={"snake_best_score": 32, "rogue_best_gold": 901},
            unlocked_themes=["default", "obsidian", "terminal_amber"],
        )

        cases = build_cases()
        results: list[EvalResult] = []
        for run_id in range(args.runs):
            print(f"-- run {run_id + 1}/{args.runs} --")
            for idx, case in enumerate(cases, start=1):
                t0 = time.perf_counter()
                reply = syster.reply(case.prompt, tr, context)
                latency_ms = int((time.perf_counter() - t0) * 1000.0)
                score, notes = score_reply(reply, case)
                results.append(
                    EvalResult(
                        prompt=case.prompt,
                        latency_ms=latency_ms,
                        score=score,
                        notes=notes,
                        reply=reply,
                    )
                )
                print(
                    f"[{idx}] {latency_ms:>5} ms | score={score:.3f} | notes={notes}\n"
                    f"reply: {reply[:190].replace(chr(10), ' ')}"
                )
                if args.store_feedback:
                    syster.record_feedback(
                        prompt=case.prompt,
                        reply=reply,
                        score=score,
                        notes=f"auto_eval profile={args.profile} {notes}",
                    )

        latencies = [row.latency_ms for row in results]
        scores = [row.score for row in results]
        avg_latency = statistics.mean(latencies) if latencies else 0.0
        avg_score = statistics.mean(scores) if scores else 0.0
        pass_rate = (
            (sum(1 for value in scores if value >= 0.75) / float(len(scores))) * 100.0
            if scores
            else 0.0
        )

        print("== Summary ==")
        print(
            f"samples={len(results)} "
            f"avg_latency_ms={avg_latency:.1f} "
            f"avg_score={avg_score:.3f} "
            f"pass_rate={pass_rate:.1f}%"
        )

        if args.json_out:
            payload = {
                "profile": args.profile,
                "model": args.model,
                "status": status,
                "profile_result": profile_result,
                "summary": {
                    "samples": len(results),
                    "avg_latency_ms": avg_latency,
                    "avg_score": avg_score,
                    "pass_rate": pass_rate,
                },
                "results": [asdict(row) for row in results],
            }
            out_path = Path(args.json_out).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"json_out={out_path}")
        return 0
    finally:
        store.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate and train Syster responses locally.")
    parser.add_argument(
        "--profile",
        default="balanced",
        choices=("speed", "balanced", "quality"),
        help="CUDA runtime profile.",
    )
    parser.add_argument("--model", default="mistral", help="Local model tag.")
    parser.add_argument("--runs", default=1, type=int, help="How many full benchmark rounds.")
    parser.add_argument("--player", default="Orion", help="Player name injected in context.")
    parser.add_argument(
        "--package-dir",
        default="gethes",
        help="Path to package dir containing vendor/syster_core.",
    )
    parser.add_argument(
        "--store-feedback",
        action="store_true",
        help="Store auto feedback in syster_training.db.",
    )
    parser.add_argument("--json-out", default="", help="Optional output JSON path.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_eval(parse_args()))
