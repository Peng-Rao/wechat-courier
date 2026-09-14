from __future__ import annotations

from app.agent.journal import SafetyJournal


def test_safety_journal_survives_agent_restart_and_clears_atomically(tmp_path):
    path = tmp_path / "agent-safety.json"
    journal = SafetyJournal(path)

    record = journal.mark(
        task_id="task-1",
        kind="message_send",
        item_id="item-2",
        boundary="send_triggered",
        item_index=1,
        session_generation=4,
    )

    restored = SafetyJournal(path).load()
    assert restored == record
    assert restored["taskId"] == "task-1"
    assert restored["itemId"] == "item-2"
    assert restored["boundary"] == "send_triggered"
    assert restored["itemIndex"] == 1
    assert restored["sessionGeneration"] == 4

    assert SafetyJournal(path).clear(task_id="another-task") is False
    assert SafetyJournal(path).load() == record
    assert SafetyJournal(path).clear(task_id="task-1") is True
    assert SafetyJournal(path).load() is None


def test_safety_journal_ignores_invalid_or_incomplete_data(tmp_path):
    path = tmp_path / "agent-safety.json"
    path.write_text('{"taskId":"task-1"}', encoding="utf-8")

    assert SafetyJournal(path).load() is None
