from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AchievementDef:
    achievement_id: str
    title_key: str
    desc_key: str
    hidden: bool = False


ACHIEVEMENTS: tuple[AchievementDef, ...] = (
    AchievementDef(
        achievement_id="boot_sequence",
        title_key="achievement.boot_sequence.title",
        desc_key="achievement.boot_sequence.desc",
    ),
    AchievementDef(
        achievement_id="snake_first_food",
        title_key="achievement.snake_first_food.title",
        desc_key="achievement.snake_first_food.desc",
    ),
    AchievementDef(
        achievement_id="snake_score_120",
        title_key="achievement.snake_score_120.title",
        desc_key="achievement.snake_score_120.desc",
    ),
    AchievementDef(
        achievement_id="daily_first_win",
        title_key="achievement.daily_first_win.title",
        desc_key="achievement.daily_first_win.desc",
    ),
    AchievementDef(
        achievement_id="daily_streak_3",
        title_key="achievement.daily_streak_3.title",
        desc_key="achievement.daily_streak_3.desc",
    ),
    AchievementDef(
        achievement_id="daily_dual_clear",
        title_key="achievement.daily_dual_clear.title",
        desc_key="achievement.daily_dual_clear.desc",
    ),
    AchievementDef(
        achievement_id="hangman_win",
        title_key="achievement.hangman_win.title",
        desc_key="achievement.hangman_win.desc",
    ),
    AchievementDef(
        achievement_id="hangman_duel_win",
        title_key="achievement.hangman_duel_win.title",
        desc_key="achievement.hangman_duel_win.desc",
    ),
    AchievementDef(
        achievement_id="ttt_win",
        title_key="achievement.ttt_win.title",
        desc_key="achievement.ttt_win.desc",
    ),
    AchievementDef(
        achievement_id="story_complete",
        title_key="achievement.story_complete.title",
        desc_key="achievement.story_complete.desc",
    ),
    AchievementDef(
        achievement_id="story_first_choice",
        title_key="achievement.story_first_choice.title",
        desc_key="achievement.story_first_choice.desc",
    ),
    AchievementDef(
        achievement_id="story_secret_finder",
        title_key="achievement.story_secret_finder.title",
        desc_key="achievement.story_secret_finder.desc",
    ),
    AchievementDef(
        achievement_id="story_archivist",
        title_key="achievement.story_archivist.title",
        desc_key="achievement.story_archivist.desc",
    ),
    AchievementDef(
        achievement_id="story_companion_route",
        title_key="achievement.story_companion_route.title",
        desc_key="achievement.story_companion_route.desc",
        hidden=True,
    ),
    AchievementDef(
        achievement_id="codebreaker_win",
        title_key="achievement.codebreaker_win.title",
        desc_key="achievement.codebreaker_win.desc",
    ),
    AchievementDef(
        achievement_id="rogue_first_run",
        title_key="achievement.rogue_first_run.title",
        desc_key="achievement.rogue_first_run.desc",
    ),
    AchievementDef(
        achievement_id="rogue_depth_3",
        title_key="achievement.rogue_depth_3.title",
        desc_key="achievement.rogue_depth_3.desc",
    ),
    AchievementDef(
        achievement_id="rogue_victory",
        title_key="achievement.rogue_victory.title",
        desc_key="achievement.rogue_victory.desc",
    ),
    AchievementDef(
        achievement_id="secret_echo",
        title_key="achievement.secret_echo.title",
        desc_key="achievement.secret_echo.desc",
        hidden=True,
    ),
)


BY_ID: dict[str, AchievementDef] = {item.achievement_id: item for item in ACHIEVEMENTS}


def achievement_flag(achievement_id: str) -> str:
    return f"achv_{achievement_id}"


def is_unlocked(flags: dict[str, object], achievement_id: str) -> bool:
    return bool(flags.get(achievement_flag(achievement_id), False))


def unlocked_count(flags: dict[str, object]) -> int:
    total = 0
    for item in ACHIEVEMENTS:
        if is_unlocked(flags, item.achievement_id):
            total += 1
    return total
