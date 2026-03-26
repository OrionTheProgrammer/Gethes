from gethes.syster import SysterAssistant, SysterContext


def _tr(key: str, **_kwargs: object) -> str:
    return key


def test_syster_detects_new_intents(monkeypatch) -> None:
    syster = SysterAssistant(mode="local")
    monkeypatch.setattr(syster, "_ollama_reply", lambda _prompt, _context: None)
    ctx = SysterContext()

    assert syster.reply("quien eres", _tr, ctx) == "app.syster.reply.identity"
    assert syster.reply("como actualizo gethes", _tr, ctx) == "app.syster.reply.update"
    assert syster.reply("no hay sonido", _tr, ctx) == "app.syster.reply.audio"
    assert syster.reply("quiero mods de historia", _tr, ctx) == "app.syster.reply.mods"


def test_syster_followup_after_audio_intent(monkeypatch) -> None:
    syster = SysterAssistant(mode="local")
    monkeypatch.setattr(syster, "_ollama_reply", lambda _prompt, _context: None)
    ctx = SysterContext(last_command="menu")
    syster.reply("audio", _tr, ctx)
    assert syster.reply("y eso?", _tr, ctx) == "app.syster.reply.followup"


def test_syster_fuzzy_typo_detects_update_intent(monkeypatch) -> None:
    syster = SysterAssistant(mode="local")
    monkeypatch.setattr(syster, "_ollama_reply", lambda _prompt, _context: None)
    ctx = SysterContext()
    assert syster.reply("actulizar", _tr, ctx) == "app.syster.reply.update"
