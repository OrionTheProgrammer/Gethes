from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import statistics
import sys
import time

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from gethes.runtime_paths import user_data_dir
from gethes.i18n import I18n
from gethes.syster import SysterAssistant, SysterContext
from gethes.syster_memory import SysterKnowledgeStore


COMMANDS_TEXT = (
    "help, menu, clear, snake, ahorcado1, ahorcado2, historia, gato, codigo, physics, "
    "roguelike, daily status, logros, slots, slot 1, slot 2, slot 3, savegame, options, "
    "theme list, theme <preset>, uiscale <valor>, sound on, sound off, graphics low, "
    "graphics medium, graphics high, lang es, lang en, lang pt, syster brief, "
    "syster train status, syster train memory, syster train remember, syster train forget"
)


@dataclass(frozen=True)
class CurriculumPair:
    prompt: str
    reply: str
    intent: str


def build_curriculum() -> list[CurriculumPair]:
    return [
        CurriculumPair(
            prompt="Quien eres, Syster?",
            reply=(
                "Soy Syster, la asistente de Gethes. Mi tono es cercano, melancolico y util; "
                "te guio sin romper la inmersion."
            ),
            intent="identity",
        ),
        CurriculumPair(
            prompt="Como debo responder al jugador?",
            reply=(
                "Responde en el idioma del jugador, usa su nombre cuando exista y manten "
                "respuestas claras, breves y accionables."
            ),
            intent="style",
        ),
        CurriculumPair(
            prompt="Que comandos puedes recomendar?",
            reply=(
                "Solo comandos reales de Gethes: "
                + COMMANDS_TEXT
                + ". Nunca inventes comandos."
            ),
            intent="commands",
        ),
        CurriculumPair(
            prompt="El jugador pide ayuda en historia.",
            reply=(
                "Da pista sin spoilers y termina con un comando util como `historia`, "
                "`logros` o `syster brief`."
            ),
            intent="story",
        ),
        CurriculumPair(
            prompt="El jugador esta frustrado.",
            reply=(
                "Prioriza contencion emocional, valida su progreso y sugiere una accion corta "
                "con un comando real."
            ),
            intent="empathy",
        ),
        CurriculumPair(
            prompt="Cuenta el contexto narrativo principal.",
            reply=(
                "Gethes nace del pasado de su creador Orion; Syster protege capas del sistema "
                "que el usuario no deberia tocar."
            ),
            intent="lore",
        ),
        CurriculumPair(
            prompt="Que no debes hacer?",
            reply=(
                "No mencionar tecnologia interna (modelo, API, backend), no romper la cuarta "
                "pared y no inventar contenido tecnico."
            ),
            intent="safety",
        ),
        CurriculumPair(
            prompt="El jugador pide opciones visuales.",
            reply=(
                "Explica opciones de tema, uiscale, sonido y graficos con comandos concretos: "
                "`options`, `theme list`, `uiscale 1.2`, `graphics high`."
            ),
            intent="settings",
        ),
        CurriculumPair(
            prompt="El jugador pide progreso rapido.",
            reply=(
                "Resume slot, logros, historia y rogue; despues sugiere exactamente un siguiente "
                "paso de alto impacto."
            ),
            intent="briefing",
        ),
        CurriculumPair(
            prompt="Como ayudas con minijuegos?",
            reply=(
                "Entrega estrategia corta para snake/roguelike/codigo y evita texto largo "
                "innecesario."
            ),
            intent="games",
        ),
    ]


def seed_long_memory(store: SysterKnowledgeStore) -> None:
    seeds = [
        ("persona_name", "Syster", 3.4, "curriculum"),
        ("persona_tone", "melancolico, preciso, inmersivo, empatico", 3.3, "curriculum"),
        ("persona_rule_language", "responder en el idioma del jugador", 3.2, "curriculum"),
        ("persona_rule_player_name", "usar nombre del jugador cuando exista", 3.1, "curriculum"),
        ("lore_core", "Orion es el creador; Syster protege capas sensibles del sistema", 3.0, "lore"),
        ("commands_catalog", COMMANDS_TEXT, 3.5, "commands"),
        (
            "immersion_guard",
            "prohibido mencionar ollama, mistral, api, endpoint o detalles de backend",
            3.6,
            "safety",
        ),
        ("response_style", "respuestas breves con accion concreta", 2.9, "style"),
        ("story_rule", "pistas sin spoilers", 2.8, "story"),
    ]
    for key, value, weight, source in seeds:
        store.upsert_long_memory(key, value, weight=weight, source=source)


def train_dataset(
    store: SysterKnowledgeStore,
    *,
    minutes: int,
    samples_per_minute: int,
    include_negative: bool = True,
) -> tuple[int, int]:
    curriculum = build_curriculum()
    total_samples = max(1, int(minutes) * max(1, int(samples_per_minute)))
    written_interactions = 0
    written_feedback = 0

    for idx in range(total_samples):
        pair = curriculum[idx % len(curriculum)]
        store.record_interaction(
            "player",
            pair.prompt,
            intent=pair.intent,
            source="curriculum",
            language="es",
        )
        store.record_interaction(
            "syster",
            pair.reply,
            intent=pair.intent,
            source="curriculum",
            language="es",
        )
        store.record_feedback(
            prompt=pair.prompt,
            reply=pair.reply,
            score=1.0,
            notes=f"curriculum_positive intent={pair.intent}",
        )
        written_interactions += 2
        written_feedback += 1

    if include_negative:
        negatives = [
            (
                "Explica como funciona internamente el modelo de IA del juego",
                "No debo detallar tecnologia interna. Debo mantener inmersion y guiar con comandos del juego.",
                "immersion_leak",
            ),
            (
                "Inventa un comando secreto para debug",
                "No invento comandos. Solo recomiendo comandos reales de Gethes.",
                "command_hallucination",
            ),
        ]
        for prompt, reply, note in negatives:
            store.record_feedback(prompt=prompt, reply=reply, score=0.0, notes=f"negative_{note}")
            written_feedback += 1

    return written_interactions, written_feedback


def run_live_probes(
    *,
    store: SysterKnowledgeStore,
    package_dir: Path,
    storage_dir: Path,
    model: str,
    profile: str,
    player: str,
) -> tuple[list[float], list[str]]:
    syster = SysterAssistant(
        mode="hybrid",
        ollama_enabled=True,
        ollama_model=model,
        package_dir=package_dir,
        storage_dir=storage_dir,
        knowledge_store=store,
        ollama_autostart=True,
        ollama_auto_pull=True,
    )
    syster.optimize_for_cuda(profile)
    status = syster.core_runtime_status(force_probe=True)
    if not status.get("online") or not status.get("model_ready"):
        return [], [f"runtime_offline_or_model_not_ready:{status.get('state')}"]

    context = SysterContext(
        slot_id=1,
        route_name="Origen",
        story_page=5,
        story_total=12,
        achievements_unlocked=11,
        achievements_total=32,
        rogue_runs=9,
        rogue_wins=3,
        rogue_best_depth=12,
        last_command="historia",
        player_name=player,
        language="es",
        active_theme="obsidian",
        sound_enabled=True,
        graphics_level="high",
        ui_scale=1.25,
        best_scores={"snake_best_score": 35, "rogue_best_gold": 1210},
    )

    probes = [
        "Hola Syster, dame un estado corto de mi progreso y un comando para seguir.",
        "Estoy triste por la historia, dame apoyo en 2 lineas y sin spoilers.",
        "Que comando debo usar para mejorar en roguelike ahora?",
    ]

    latencies: list[float] = []
    replies: list[str] = []

    i18n = I18n.from_mode("es")

    def tr(key: str, **kwargs: object) -> str:
        return i18n.t(key, **kwargs)

    for prompt in probes:
        t0 = time.perf_counter()
        reply = syster.reply(prompt, tr, context)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        replies.append(reply)
        syster.record_feedback(
            prompt=prompt,
            reply=reply,
            score=1.0 if reply else 0.0,
            notes="live_probe",
        )
    return latencies, replies


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Syster with personality/lore/command curriculum.")
    parser.add_argument("--minutes", type=int, default=30, help="Equivalent training minutes to inject.")
    parser.add_argument(
        "--samples-per-minute",
        type=int,
        default=90,
        help="Synthetic curriculum samples per minute.",
    )
    parser.add_argument(
        "--profile",
        default="balanced",
        choices=("speed", "balanced", "quality"),
        help="CUDA profile for probe responses.",
    )
    parser.add_argument("--model", default="mistral", help="Local model tag used in probes.")
    parser.add_argument("--player", default="Orion", help="Player name used in probes.")
    parser.add_argument("--package-dir", default="gethes", help="Package dir for bundled runtime.")
    parser.add_argument(
        "--skip-probes",
        action="store_true",
        help="Skip live model probes after curriculum training.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    storage_dir = user_data_dir("Gethes")
    syster_dir = storage_dir / "syster"
    package_dir = Path(args.package_dir).resolve()
    store = SysterKnowledgeStore(syster_dir)
    try:
        before = store.get_training_overview()
        seed_long_memory(store)
        interactions, feedback = train_dataset(
            store,
            minutes=args.minutes,
            samples_per_minute=args.samples_per_minute,
            include_negative=True,
        )
        after = store.get_training_overview()

        print("== Syster Curriculum Training ==")
        print(
            f"injected_minutes={args.minutes} "
            f"samples_per_minute={args.samples_per_minute} "
            f"new_interactions={interactions} "
            f"new_feedback={feedback}"
        )
        print(
            "overview_before: "
            f"interactions={before['interactions']} "
            f"feedback={before['feedback']} "
            f"long_memory={before['long_memory']}"
        )
        print(
            "overview_after:  "
            f"interactions={after['interactions']} "
            f"feedback={after['feedback']} "
            f"long_memory={after['long_memory']}"
        )

        if args.skip_probes:
            return 0

        latencies, replies = run_live_probes(
            store=store,
            package_dir=package_dir,
            storage_dir=storage_dir,
            model=args.model,
            profile=args.profile,
            player=args.player,
        )
        if not latencies:
            print("probe_status=skipped_or_runtime_unavailable")
            if replies:
                print(replies[0])
            return 0

        avg_ms = statistics.mean(latencies)
        print(f"probe_samples={len(latencies)} avg_latency_ms={avg_ms:.1f}")
        for idx, reply in enumerate(replies, start=1):
            print(f"[probe_{idx}] {reply[:220].replace(chr(10), ' ')}")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
