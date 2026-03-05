from gethes.i18n import I18n
from gethes.syster import SysterAssistant, SysterContext


def test_briefing_recommends_story_when_in_progress() -> None:
    syster = SysterAssistant(mode="lite")
    tr = I18n.from_mode("en").t
    ctx = SysterContext(
        slot_id=2,
        route_name="Route Delta",
        story_page=3,
        story_total=9,
        achievements_unlocked=4,
        achievements_total=20,
        rogue_runs=0,
        rogue_wins=0,
        rogue_best_depth=0,
    )

    text = syster.briefing(tr, ctx)
    assert "Recommended: `historia`." in text


def test_briefing_recommends_roguelike_when_no_runs() -> None:
    syster = SysterAssistant(mode="lite")
    tr = I18n.from_mode("en").t
    ctx = SysterContext(
        story_page=0,
        story_total=0,
        achievements_unlocked=1,
        achievements_total=20,
        rogue_runs=0,
        rogue_wins=0,
        rogue_best_depth=0,
    )

    text = syster.briefing(tr, ctx)
    assert "Recommended: `roguelike`." in text


def test_reply_diagnostics_intent() -> None:
    syster = SysterAssistant(mode="lite")
    tr = I18n.from_mode("en").t

    reply = syster.reply("I got an error and need diagnostics", tr)
    assert "doctor all" in reply


def test_reply_rogue_progress_intent() -> None:
    syster = SysterAssistant(mode="lite")
    tr = I18n.from_mode("en").t
    ctx = SysterContext(rogue_runs=7, rogue_wins=2, rogue_best_depth=5)

    reply = syster.reply("roguelike progress", tr, context=ctx)
    assert "runs=7" in reply
    assert "wins=2" in reply
    assert "best depth=5" in reply
