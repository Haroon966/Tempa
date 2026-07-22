from __future__ import annotations


def _patch_memory(tmp_path, monkeypatch):
    from tempa.rag import procedural

    mem = tmp_path / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(procedural, "_memory_dir", lambda: mem)
    monkeypatch.setattr(
        "tempa.rag.procedural.ingest_text",
        lambda *args, **kwargs: {"chunks_created": 0},
    )
    return procedural


def test_correction_capture_and_supersede(tmp_path, monkeypatch):
    procedural = _patch_memory(tmp_path, monkeypatch)

    first = procedural.add_preference("Always use plain text for emails", source="test")
    second = procedural.maybe_capture_from_message("No, always use HTML for emails")
    assert second is not None
    assert second["kind"] == "correction"

    active = procedural.format_durable_for_prompt(kinds=["preference", "correction"])
    assert "HTML" in active
    # First rule should be superseded when topics overlap
    items = procedural.list_durable(kinds=["preference", "correction"], include_superseded=True)
    superseded = [i for i in items if i.get("id") == first["id"]]
    assert superseded and superseded[0].get("superseded_by")
    active_prefs = procedural.list_preferences()
    assert all(i.get("id") != first["id"] for i in active_prefs)


def test_preference_patterns_still_work(tmp_path, monkeypatch):
    procedural = _patch_memory(tmp_path, monkeypatch)
    rec = procedural.maybe_capture_from_message("From now on CC Alex on launch emails")
    assert rec is not None
    assert "CC Alex" in rec["text"] or "CC Alex" in rec.get("rule", "")


def test_clarify_remember_person_email(tmp_path, monkeypatch):
    procedural = _patch_memory(tmp_path, monkeypatch)
    ctx = {"channel": "slack", "slack_thread_ts": "111.222"}

    procedural.register_open_clarification(
        "You mentioned Alex — what's their email address?",
        slot="email",
        context=ctx,
        hint="Alex",
    )
    record = procedural.resolve_open_clarification("alex@example.com", ctx)
    assert record is not None
    assert record["kind"] == "person"
    assert "alex@example.com" in record["text"]
    assert procedural.get_open_clarification(ctx) is None
    assert procedural.find_person_email("Alex") == "alex@example.com"


def test_detect_missing_skips_when_durable_email_known(tmp_path, monkeypatch):
    procedural = _patch_memory(tmp_path, monkeypatch)
    procedural.add_durable("Alex email is alex@example.com", kind="person", source="test")

    from tempa.agents.clarification import detect_missing_context

    ctx: dict = {}
    q = detect_missing_context("send an email to Alex about the launch", ctx)
    assert q is None
    assert ctx.get("known_recipient_email") == "alex@example.com"


def test_knowledge_write_from_extract(tmp_path, monkeypatch):
    procedural = _patch_memory(tmp_path, monkeypatch)

    class FakeChoice:
        message = type(
            "M",
            (),
            {
                "content": (
                    '{"items":[{"kind":"decision","text":"Ship launch on Friday"},'
                    '{"kind":"person","text":"Alex email is alex@co.com"}]}'
                )
            },
        )()

    class FakeResp:
        choices = [FakeChoice()]

    class FakeRouter:
        def chat_completion(self, **kwargs):
            return FakeResp()

    monkeypatch.setattr("tempa.rag.consolidation.get_router", lambda: FakeRouter())
    monkeypatch.setattr(
        "tempa.rag.consolidation.ingest_text",
        lambda *args, **kwargs: {"chunks_created": 0},
    )

    from tempa.rag.consolidation import _extract_knowledge_items, _write_knowledge_items

    items = _extract_knowledge_items("some meeting summary about launch")
    assert len(items) == 2
    written = _write_knowledge_items(items, source="test")
    assert written == 2
    decisions = procedural.list_durable(kinds=["decision"])
    assert any("Friday" in d["text"] for d in decisions)


def test_format_excludes_superseded(tmp_path, monkeypatch):
    procedural = _patch_memory(tmp_path, monkeypatch)
    a = procedural.add_preference("Always ping Slack for deploys", source="test")
    b = procedural.add_preference("Never ping Slack for deploys", source="test")
    assert a["id"] != b["id"]
    prompt = procedural.format_durable_for_prompt(kinds=["preference"])
    assert "Never ping" in prompt
    # Active list should not include superseded
    active = {i["id"] for i in procedural.list_preferences()}
    assert b["id"] in active
