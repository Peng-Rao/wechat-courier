from __future__ import annotations

import json

import pytest

from app.agent.contracts import TaskItem, TaskOptions, TaskRequest
from app.agent.diagnostics import UiaDiagnostics
from app.agent.native_driver import NativeWeixinDriver, SearchCandidate, SearchResultRow
from app.agent.retry import TransientUiError
from app.agent.runtime import TaskControl
from app.agent.workflows import WeixinWorkflowEngine
from tests.test_agent_workflows import FakeDriver
from tests.test_native_driver_helpers import FakeControl


def candidate(name, index=0, *, identities=None):
    return SearchCandidate(
        name, frozenset(identities or {name}), "contact", f"search_item_{index}", index, 1
    )


class MessageSearchDriver(FakeDriver):
    def __init__(self):
        super().__init__()
        self.selected = []
        self.selection_modes = []

    def select_search_result(self, selected, *, fuzzy=False):
        self.selected.append(selected)
        self.selection_modes.append(fuzzy)
        self.chat_title = selected.display_name


def run_search(driver, query="Alice", *, fuzzy=False, files=(), diagnostics=None):
    task = TaskRequest(
        "fuzzy-task", "message_send", (TaskItem("one", target=query, message="unchanged message"),),
        TaskOptions.from_payload({"fuzzySearchEnabled": fuzzy, "filePaths": list(files)}),
    )
    events = []
    result = WeixinWorkflowEngine(driver_factory=lambda: driver, sleep=lambda _: None,
                                 diagnostics=diagnostics).run(
        task, TaskControl(), lambda method, payload: events.append((method, payload))
    )
    return result, [payload for method, payload in events if method == "task.event"]


def test_fuzzy_uses_first_result_even_when_later_result_is_exact():
    driver = MessageSearchDriver()
    first, exact = candidate("Alice Smith"), candidate("Alice", 1)
    driver.search_results["Alice"] = [first, exact]

    result, events = run_search(driver, fuzzy=True)

    assert result["success"] == 1
    assert driver.selected == [first]
    assert driver.selection_modes == [True]
    assert driver.sent == ["unchanged message"]
    selected = next(event for event in events if event["step"] == "target_selected")
    assert "Alice" in selected["detail"] and "Alice Smith" in selected["detail"]


def test_fuzzy_accepts_duplicate_names_in_distinct_result_rows():
    driver = MessageSearchDriver()
    first = candidate("Alice")
    driver.search_results["Alice"] = [first, candidate("Alice", 1)]

    result, _ = run_search(driver, fuzzy=True)

    assert result["success"] == 1
    assert driver.selected == [first]


def test_exact_search_still_uses_unique_exact_result():
    driver = MessageSearchDriver()
    first, exact = candidate("Alice Smith"), candidate("Alice", 1)
    driver.search_results["Alice"] = [first, exact]

    result, _ = run_search(driver)

    assert result["success"] == 1
    assert driver.selected == [exact]
    assert driver.selection_modes == [False]


@pytest.mark.parametrize("fuzzy", [False, True])
def test_empty_search_never_sends(fuzzy):
    driver = MessageSearchDriver()

    result, events = run_search(driver, fuzzy=fuzzy)

    assert result["error"] == 1 and not driver.sent
    assert not driver.selected
    assert events[-1]["errorCode"] == "TARGET_NOT_FOUND"


def test_exact_duplicate_search_remains_blocked():
    driver = MessageSearchDriver()
    driver.search_results["Alice"] = [candidate("Alice"), candidate("Alice", 1)]

    result, events = run_search(driver)

    assert result["error"] == 1 and not driver.sent
    assert events[-1]["errorCode"] == "TARGET_NOT_UNIQUE"


def test_fuzzy_does_not_weaken_chat_identity_verification():
    driver = MessageSearchDriver()
    driver.search_results["Alice"] = [candidate("Alice Smith")]
    driver.current_chat_title = lambda: "Bob"

    result, events = run_search(driver, fuzzy=True)

    assert result["error"] == 1 and not driver.sent
    assert events[-1]["errorCode"] == "TARGET_MISMATCH"


def test_fuzzy_does_not_weaken_composer_readback():
    driver = MessageSearchDriver()
    driver.search_results["Alice"] = [candidate("Alice Smith")]
    driver.read_composer_text = lambda: "wrong content"

    result, events = run_search(driver, fuzzy=True)

    assert result["error"] == 1 and not driver.sent
    assert events[-1]["errorCode"] == "CONTENT_READBACK_MISMATCH"


def test_fuzzy_unknown_send_is_not_replayed():
    driver = MessageSearchDriver()
    driver.search_results["Alice"] = [candidate("Alice Smith")]
    driver.send_verification = None

    result, _ = run_search(driver, fuzzy=True)

    assert result["unknown"] == 1
    assert driver.sent == ["unchanged message"]
    assert driver.search_calls == 1


def test_fuzzy_search_diagnostics_redact_query_and_actual_match(tmp_path):
    driver = MessageSearchDriver()
    query = "private-name"
    matched = "private-name full contact"
    driver.search_results[query] = [candidate(matched)]
    diagnostics = UiaDiagnostics(log_dir=tmp_path)

    result, _ = run_search(driver, query, fuzzy=True, diagnostics=diagnostics)
    diagnostics.close()

    assert result["success"] == 1
    raw = (tmp_path / "uia-diagnostics.jsonl").read_text(encoding="utf-8")
    assert query not in raw and matched not in raw
    entry = next(json.loads(line) for line in raw.splitlines()
                 if json.loads(line)["action"] == "search_target_matched")
    assert entry["account"]["length"] == len(query)
    assert entry["contact"]["length"] == len(matched)


def native_search_driver(rows):
    driver = NativeWeixinDriver(gate_backend=object())
    driver._search_query = "Alice"
    driver._search_rows = lambda: rows
    driver._click_search_candidate = lambda control: clicks.append(control)
    driver._wait_for = lambda predicate, *_args, **_kwargs: predicate()
    driver.composer_ready = lambda: bool(clicks)
    driver.current_chat_title = lambda: "Alice Smith" if clicks else ""
    clicks = []
    return driver, clicks


def test_native_fuzzy_clicks_first_supported_row_without_exact_query_gate():
    first, exact = candidate("Alice Smith"), candidate("Alice", 1)
    row, later = FakeControl("Alice Smith"), FakeControl("Alice")
    driver, clicks = native_search_driver([SearchResultRow(first, row), SearchResultRow(exact, later)])

    driver.select_search_result(first, fuzzy=True)

    assert clicks == [row]
    assert driver._selected_identities == first.identities


def test_native_fuzzy_refuses_nonfirst_row():
    first, second = candidate("Alice Smith"), candidate("Alice", 1)
    driver, clicks = native_search_driver([
        SearchResultRow(first, FakeControl()), SearchResultRow(second, FakeControl())
    ])

    with pytest.raises(TransientUiError):
        driver.select_search_result(second, fuzzy=True)

    assert clicks == []


def test_native_fuzzy_re_resolves_first_row_before_click():
    first = candidate("Alice Smith")
    stale, fresh = FakeControl("stale"), FakeControl("fresh")
    snapshots = iter(([SearchResultRow(first, stale)], [SearchResultRow(first, fresh)]))
    driver, clicks = native_search_driver([])
    driver._search_rows = lambda: next(snapshots)

    driver.select_search_result(first, fuzzy=True)

    assert clicks == [fresh]


@pytest.mark.parametrize("change", ["reordered", "identity_changed", "gone"])
def test_native_fuzzy_rejects_changed_first_result_before_click(change):
    first, other = candidate("Alice Smith"), candidate("Alice", 1)
    original = [SearchResultRow(first, FakeControl()), SearchResultRow(other, FakeControl())]
    changed = {
        "reordered": original[::-1],
        "identity_changed": [SearchResultRow(candidate("Bob"), FakeControl())],
        "gone": [],
    }[change]
    snapshots = iter((original, changed))
    driver, clicks = native_search_driver([])
    driver._search_rows = lambda: next(snapshots)

    with pytest.raises(TransientUiError):
        driver.select_search_result(first, fuzzy=True)

    assert clicks == []


def test_native_fuzzy_rejects_external_search_input_change():
    first = candidate("Alice Smith")
    driver, clicks = native_search_driver([SearchResultRow(first, FakeControl())])
    driver._search_edit = FakeControl()
    driver._actions = type("Actions", (), {"read_text": staticmethod(lambda _: "Bob")})()

    with pytest.raises(TransientUiError):
        driver.select_search_result(first, fuzzy=True)

    assert clicks == []
