"""Offline tests only: no WeChat process, desktop actions, or sends."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def harness(monkeypatch):
    path = Path(__file__).with_name("manual_v032_gui_acceptance.py")
    assert path.exists(), "v0.3.2 acceptance harness must exist"
    spec = importlib.util.spec_from_file_location("v032_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_plan_is_identical_across_modes_and_has_unique_single_item_tasks(harness):
    plans = [harness.make_plan("run-fixed", 6) for _ in ("source", "rpc", "gui")]
    assert plans[0] == plans[1] == plans[2]
    assert len({case["request"]["taskId"] for case in plans[0]}) == 6
    assert [(c["request"]["kind"], c["windowState"]) for c in plans[0]] == [
        ("message_send", "visible"), ("friend_add", "visible"),
        ("message_send", "minimized"), ("friend_add", "minimized"),
        ("message_send", "tray"), ("friend_add", "tray"),
    ]
    texts = []
    for case in plans[0]:
        request = case["request"]
        harness.validate_request(request)
        assert len(request["items"]) == 1
        if request["kind"] == "message_send":
            assert request["items"][0]["target"] == harness.SEND_TARGET
            assert request["options"]["fuzzySearchEnabled"] is False
            texts.append(request["items"][0]["message"])
        else:
            assert request["items"][0]["account"] == "18896904196"
    assert len(set(texts)) == 3


def test_gui_friend_csv_matches_current_name_contract_without_changing_defaults(harness):
    from app.friend_import import load_friend_records
    item = harness.make_case("names", 1)["request"]["items"][0]
    records = load_friend_records(harness.friend_import_rows(item))
    assert len(records) == 1 and records[0].valid and not records[0].selected
    assert records[0].remark == item["remark"]
    assert records[0].rendered_greeting == item["greeting"]


def test_evidence_keeps_non_private_timer_and_risk_fields(harness):
    event = {"taskId": "one", "itemId": "row-2", "step": "account_searched",
             "timestamp": "2026-10-04T07:25:33Z", "itemElapsedMs": 15001,
             "riskKind": "friend_frequency", "detail": "private account"}
    evidence = harness.result_evidence({"elapsedSeconds": 16.2, "events": [event]})
    assert evidence["elapsedSeconds"] == 16.2
    assert evidence["events"][0]["itemElapsedMs"] == 15001
    assert evidence["events"][0]["riskKind"] == "friend_frequency"
    assert evidence["events"][0]["timestamp"] == event["timestamp"]
    assert "detail" not in evidence["events"][0]


def test_source_gui_can_be_validated_without_packaging(harness):
    args = harness.parse_args(["--mode", "gui", "--gui-source", "--execute",
                               "--confirm-send", "--confirm-friend-preflight"])
    harness.validate_args(args)
    assert args.gui_source is True and args.gui_exe is None


@pytest.mark.parametrize("mutation", ["target", "account", "attachment", "forward", "batch", "fuzzy"])
def test_rejects_unpermitted_requests(harness, mutation):
    case = harness.make_plan("safety", 2)[mutation == "account"]
    request = case["request"]
    if mutation == "target":
        request["items"][0]["target"] = "another contact"
    elif mutation == "account":
        request["items"][0]["account"] = "123456"
    elif mutation == "attachment":
        request["options"]["filePaths"] = ["private.txt"]
    elif mutation == "forward":
        request["options"]["useForward"] = True
    elif mutation == "fuzzy":
        request["options"]["fuzzySearchEnabled"] = True
    else:
        request["items"].append(dict(request["items"][0]))
    with pytest.raises(ValueError):
        harness.validate_request(request)


def test_live_requires_two_explicit_gates_and_default_is_plan_only(harness):
    args = harness.parse_args([])
    assert not args.execute
    assert args.profile == "smoke"
    for flags in (["--execute"], ["--execute", "--confirm-send"],
                  ["--execute", "--confirm-friend-preflight"]):
        with pytest.raises(ValueError):
            harness.validate_args(harness.parse_args(flags))
    harness.validate_args(harness.parse_args([
        "--mode", "source", "--execute", "--confirm-send", "--confirm-friend-preflight",
    ]))


def successful_result(case):
    request = case["request"]
    return {
        "taskId": request["taskId"], "outcome": "success", "done": 1,
        "total": 1, "success": 1, "error": 0, "unknown": 0, "stopped": 0,
        "cleanup": {"success": True},
        "health": {"windowEnabled": True, "windowResponsive": True,
                   "sessionReady": True, "blockingWindow": None},
        "buildFingerprint": "sha256:" + "a" * 64,
        "events": [{"taskId": request["taskId"],
                    "itemId": request["items"][0]["itemId"],
                    "step": "send_verified" if request["kind"] == "message_send"
                    else "preflight_completed", "outcome": "success"}],
    }


def test_result_needs_terminal_evidence_not_just_success_label(harness):
    case = harness.make_plan("evidence", 1)[0]
    result = successful_result(case)
    harness.validate_result(case, result, set())
    for change in ({"events": []}, {"taskId": "stale"}, {"unknown": 1},
                   {"done": 0}, {"success": 0}):
        with pytest.raises(ValueError):
            harness.validate_result(case, {**result, **change}, set())
    with pytest.raises(ValueError):
        harness.validate_result(case, result, {result["taskId"]})


def test_friend_submit_evidence_is_never_accepted(harness):
    case = harness.make_plan("friend", 2)[1]
    result = successful_result(case)
    result["events"].append({"step": "submit_triggered", "outcome": "working"})
    with pytest.raises(ValueError, match="submit"):
        harness.validate_result(case, result, set())


def test_gui_ids_can_differ_but_must_be_fresh_and_correlated(harness):
    case = harness.make_plan("gui", 1)[0]
    result = successful_result(case)
    result.update(taskId="gui-real-id", mode="gui", echoedItems=case["request"]["items"])
    result["events"][0]["taskId"] = "gui-real-id"
    harness.validate_result(case, result, set())
    result["echoedItems"] = [{"target": "wrong", "message": "wrong"}]
    with pytest.raises(ValueError):
        harness.validate_result(case, result, set())


class FakeClock:
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_soak_stops_at_first_failure_and_never_replays(harness):
    clock = FakeClock()
    calls = []

    def run(case):
        calls.append(case)
        if len(calls) == 2:
            raise TimeoutError("provider hung")
        return successful_result(case)

    result = harness.run_schedule(run, "soak", "soak", 60, 3600,
                                  monotonic=clock.monotonic, sleep=clock.sleep)
    assert not result["ok"]
    assert result["stoppedAfterFirstFailure"]
    assert len(calls) == 2
    assert len(result["tasks"]) == 2
    assert result["tasks"][-1]["errorType"] == "TimeoutError"


def test_full_soak_uses_independent_tasks_for_sixty_minutes(harness):
    clock = FakeClock()
    result = harness.run_schedule(successful_result, "soak", "soak", 60, 3600,
                                  monotonic=clock.monotonic, sleep=clock.sleep)
    assert result["ok"]
    assert result["elapsedSeconds"] == 3600
    assert len(result["tasks"]) == 60
    assert len({t["case"]["request"]["taskId"] for t in result["tasks"]}) == 60


def test_build_fingerprint_covers_packaged_support_files(harness, tmp_path):
    exe = tmp_path / "courier.exe"
    exe.write_bytes(b"exe")
    internal = tmp_path / "_internal"
    internal.mkdir()
    dll = internal / "Qt6Gui.dll"
    dll.write_bytes(b"first")
    one = harness.hash_tree(tmp_path)
    dll.write_bytes(b"second")
    two = harness.hash_tree(tmp_path)
    assert one["sha256"] != two["sha256"]
    assert two["fileCount"] == 2


class FakeControl:
    Name = "startMessageButton"
    IsEnabled = True
    IsOffscreen = False
    BoundingRectangle = SimpleNamespace(left=10, top=20, right=50, bottom=60)

    def __init__(self, pattern=None):
        self.pattern = pattern

    def GetInvokePattern(self):
        return self.pattern


def test_uia_invoke_preferred_and_ambiguous_exception_never_clicks(harness):
    actions = []
    pattern = SimpleNamespace(Invoke=lambda: actions.append("invoke"))
    harness.invoke_control(FakeControl(pattern), lambda c: actions.append("click"))
    assert actions == ["invoke"]

    def broken():
        raise RuntimeError("may already have invoked")

    with pytest.raises(RuntimeError):
        harness.invoke_control(FakeControl(SimpleNamespace(Invoke=broken)),
                               lambda c: actions.append("click"))
    assert actions == ["invoke"]


def test_uia_bounds_fallback_requires_visible_enabled_nonempty_bounds(harness):
    clicks = []
    control = FakeControl()
    harness.invoke_control(control, lambda c: clicks.append(harness.control_center(c)))
    assert clicks == [(30, 40)]
    control.IsOffscreen = True
    with pytest.raises(ValueError):
        harness.invoke_control(control, lambda c: clicks.append("bad"))
    assert clicks == [(30, 40)]


def test_name_lookup_is_exact_unique_and_bounded(harness):
    class Node:
        IsOffscreen = False

        def __init__(self, name, children=()):
            self.Name, self.children = name, children

        def GetChildren(self):
            return self.children

    child = Node("messageRecipientsInput")
    assert harness.find_named(Node("root", [child]), child.Name) is child
    with pytest.raises(ValueError, match="ambiguous"):
        harness.find_named(Node("root", [child, child]), child.Name)
    with pytest.raises(LookupError):
        harness.find_named(Node("root", [Node("prefix " + child.Name)]), child.Name)
    with pytest.raises(ValueError, match="budget"):
        harness.find_named(Node("root", [Node(str(i)) for i in range(10)]), "missing", 3)


def test_delivery_audit_reaches_real_weixin_title_depth(harness, monkeypatch):
    # Live 4.1.13.65 title is at depth 22 (outside the former 20-level query).
    monkeypatch.setitem(sys.modules, "src.core.win32", SimpleNamespace(
        find_wechat_window_refs=lambda: [SimpleNamespace(hwnd=100)]))
    bubble = SimpleNamespace(ClassName="mmui::ChatTextItemView", Name="unique-marker",
                             GetRuntimeId=lambda: [1, 2, 3], GetChildren=lambda: [])
    message_list = SimpleNamespace(Exists=lambda *_: True, ClassName="List",
                                   GetChildren=lambda: [bubble])

    def control(**kwargs):
        if kwargs["AutomationId"] == "chat_message_list":
            return message_list
        return SimpleNamespace(Name=harness.SEND_TARGET,
                               Exists=lambda *_: kwargs["searchDepth"] >= 22)

    desktop = object.__new__(harness.Desktop)
    desktop.notice = lambda _: None
    desktop.root = lambda _: object()
    desktop.uia = SimpleNamespace(Control=control)
    rows = desktop.delivery_snapshot()
    assert len(rows) == 1
    assert rows[0]["text"] == "unique-marker"


def test_file_dialog_open_control_ignores_file_item_with_same_automation_id(harness):
    missing_button = SimpleNamespace(Exists=lambda *_args: False)
    split_button = SimpleNamespace(
        Exists=lambda *_args: True,
        ControlTypeName="SplitButtonControl",
        AutomationId="1",
    )

    class Root:
        def ButtonControl(self, **kwargs):
            assert kwargs == {"AutomationId": "1", "searchDepth": 8}
            return missing_button

        def Control(self, **kwargs):
            return SimpleNamespace(Exists=lambda *_args: True,
                                   ControlTypeName="ListItemControl", AutomationId="1")

        def SplitButtonControl(self, **kwargs):
            assert kwargs == {"AutomationId": "1", "searchDepth": 8}
            return split_button

    assert harness.file_dialog_open_control(Root()) is split_button


def test_choose_file_reacquires_dialog_root_after_filename_write(harness, tmp_path):
    filename = SimpleNamespace(Exists=lambda *_args: True)
    missing = SimpleNamespace(Exists=lambda *_args: False)
    split_button = SimpleNamespace(
        Exists=lambda *_args: True,
        ControlTypeName="SplitButtonControl",
        AutomationId="1",
    )

    class InitialRoot:
        def EditControl(self, **kwargs):
            assert kwargs == {"AutomationId": "1148", "searchDepth": 8}
            return filename

        def ButtonControl(self, **_kwargs):
            return missing

        def Control(self, **_kwargs):
            return missing


    class RefreshedRoot:
        def ButtonControl(self, **kwargs):
            assert kwargs == {"AutomationId": "1", "searchDepth": 8}
            return missing

        def Control(self, **kwargs):
            assert kwargs == {"AutomationId": "1", "searchDepth": 8}
            return split_button

        SplitButtonControl = Control

    roots = iter((InitialRoot(), RefreshedRoot()))
    visible = {"value": True}
    invoked = []
    adapter = object.__new__(harness.GuiAdapter)
    adapter.process = SimpleNamespace(pid=7)
    adapter.notice = lambda _value: None
    adapter.desktop = SimpleNamespace(
        windows=lambda **kwargs: [101],
        root=lambda _hwnd: next(roots),
        fill=lambda control, value: None,
        invoke=lambda control: (invoked.append(control), visible.update(value=False)),
        win=SimpleNamespace(IsWindowVisible=lambda _hwnd: visible["value"]),
    )

    adapter.choose_file(tmp_path / "friend.csv")

    assert invoked == [split_button]


@pytest.mark.parametrize("name", ["acceptanceEditorState", "acceptanceTaskState"])
@pytest.mark.parametrize("description,help_text,expected", [
    ('{"active": false}', '', {"active": False}),
    ('{"active": false}', '{"active": true}', {"active": False}),
    ('', '{"active": false}', {"active": False}),
])
def test_gui_snapshot_reads_full_description_then_legacy_help(harness, name, description,
                                                           help_text, expected):
    property_ids = []
    control = SimpleNamespace(
        GetPropertyValue=lambda property_id: property_ids.append(property_id) or description,
        HelpText=help_text,
    )
    adapter = object.__new__(harness.GuiAdapter)
    adapter.control = lambda requested: control if requested == name else None
    assert adapter.snapshot(name) == expected
    assert property_ids == [30159]


@pytest.mark.parametrize("description,error", [
    ('not json', json.JSONDecodeError),
    ('{"active": false} trailing', json.JSONDecodeError),
    (' ' * 32769, ValueError),
], ids=["invalid-json", "trailing-content", "oversize"])
def test_gui_snapshot_invalid_description_never_falls_back(harness, description, error):
    adapter = object.__new__(harness.GuiAdapter)
    adapter.control = lambda name: SimpleNamespace(
        GetPropertyValue=lambda property_id: description, HelpText='{"active": false}')
    with pytest.raises(error):
        adapter.snapshot("acceptanceEditorState")


def test_gui_snapshot_qml_metadata_contract(harness):
    qml = (harness.REPO_ROOT / "qml" / "App.qml").read_text(encoding="utf-8")
    for name, properties in (
        ("acceptanceEditorState", ("acceptanceMessageStateJson", "acceptanceFriendStateJson")),
        ("acceptanceTaskState", ("acceptanceTaskStateJson",)),
    ):
        node = qml.split(f'Accessible.name: "{name}"', 1)[1].split("\n    }", 1)[0]
        assert "Accessible.description:" in node
        assert "JSON.stringify(" not in node
        for property_name in properties:
            assert f"root.appBackend.task.{property_name}" in node
    readme = (harness.REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "FullDescriptionProperty (30159)" in readme


def test_gui_adapter_has_no_engine_rpc_or_controller_shortcut(harness):
    import inspect
    source = inspect.getsource(harness.GuiAdapter)
    for forbidden in ("WeixinWorkflowEngine", "AgentClient", "task.start", "startMessage(",
                      "startFriends(", "importFile(", "build_items("):
        assert forbidden not in source
    assert '"startMessageButton"' in source
    assert '"importFriendsButton"' in source


def test_default_cli_writes_machine_readable_plan_without_adapter(harness, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("plan must not create any live adapter")

    monkeypatch.setattr(harness, "WorkerSession", forbidden)
    report = tmp_path / "report.json"
    assert harness.main(["--report", str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["status"] == "planned"
    assert data["liveTasksExecuted"] == 0
    assert data["taskAttempts"] == 0
    assert data["buildFingerprint"]["source"]["sha256"]
    assert len(data["plan"]) == 6
    assert data["acceptanceVersion"] == "1.0.0"
    assert data["coverage"]["fullV100Gate"] is False
    assert "attachments" in data["coverage"]["excluded"]


@pytest.mark.parametrize("tasks,executed", [
    ([{"ok": False, "errorType": "ValueError", "case": {"request": {"taskId": "planned"}}}], 0),
    ([{"ok": False, "result": {"taskId": "actual", "outcome": "error"}}], 1),
    ([{"ok": True, "result": {"taskId": "actual"}}, {"ok": False}], 1),
    ([{"ok": False, "result": {"taskId": ""}}, {"ok": False, "result": {}}], 0),
])
def test_report_counts_attempts_separately_from_real_results(harness, monkeypatch, tmp_path,
                                                          tasks, executed):
    worker = SimpleNamespace(
        ready=lambda: None, run=lambda case: pytest.fail("No live tasks allowed"),
        close=lambda **kwargs: None, pids=[], last_stage="gui.activate.verify_after",
        breadcrumbs=[], runtime_fingerprint="", dpi_evidence={}, failure=None,
    )
    monkeypatch.setattr(harness, "WorkerSession", lambda args: worker)
    monkeypatch.setattr(harness, "build_fingerprint", lambda args: {})
    monkeypatch.setattr(harness, "window_diagnostics", lambda pids: [])

    def schedule(*args, checkpoint, **kwargs):
        result = {"tasks": tasks, "ok": False}
        checkpoint(result)
        return result

    monkeypatch.setattr(harness, "run_schedule", schedule)
    path = tmp_path / "report.json"
    assert harness.main(["--mode", "source", "--execute", "--confirm-send",
                         "--confirm-friend-preflight", "--report", str(path)]) == 2
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["taskAttempts"] == len(tasks)
    assert report["liveTasksExecuted"] == executed


@pytest.mark.parametrize("phase,active", [
    ("error", False), ("recovering", False), ("waiting_login", False),
    ("recovering", True), ("awaiting_recovery", True), ("waiting_login", True),
    ("error", True),
])
def test_gui_failed_snapshot_is_preserved_and_counted_without_retry(
        harness, monkeypatch, tmp_path, phase, active):
    actions, observations = [], []
    adapter = object.__new__(harness.GuiAdapter)
    adapter.args = SimpleNamespace(profile="smoke", artifact_dir=str(tmp_path), task_timeout=20)
    adapter.process = SimpleNamespace(pid=7)
    adapter.hwnd, adapter.settings, adapter.log_dir = 55, {}, tmp_path
    adapter.desktop = SimpleNamespace(
        win=SimpleNamespace(ShowWindow=lambda *args: None),
        activate_gui=lambda *args: None, fill=lambda *args: None,
        prepare_wechat=lambda state: {"state": state},
    )
    adapter.control = lambda name: name
    adapter.click = actions.append
    adapter.open_editor = lambda kind: None
    worker = SimpleNamespace(
        ready=lambda: None, close=lambda **kwargs: None, pids=[], last_stage="test",
        breadcrumbs=[], runtime_fingerprint="", dpi_evidence={}, failure=None,
    )

    def run(case):
        request = case["request"]
        editor = {"kind": request["kind"], "items": request["items"], "options": request["options"]}
        adapter.editor_state = lambda: editor
        failed = {**successful_result(case), "taskId": "actual-gui-task", "mode": "gui",
                  "echoedItems": request["items"], "phase": phase, "active": active,
                  "outcome": "error", "error": 1, "success": 0,
                  "detail": "PRIVATE_PAYLOAD"}
        # Active error is transitional; wait for a real terminal snapshot.
        snapshots = [{"taskId": "old"}, failed]
        if phase == "error" and active:
            snapshots.append({**failed, "active": False})
        iterator = iter(snapshots)

        def snapshot(name):
            value = next(iterator)
            observations.append(value)
            return value

        adapter.snapshot = snapshot
        return harness.result_evidence(adapter.run(case))

    worker.run = run
    monkeypatch.setattr(harness, "WorkerSession", lambda args: worker)
    monkeypatch.setattr(harness, "build_fingerprint", lambda args: {})
    monkeypatch.setattr(harness, "window_diagnostics", lambda pids: [])
    monkeypatch.setattr(harness.time, "sleep", lambda seconds: None)
    path = tmp_path / "failed-gui.json"
    assert harness.main(["--mode", "source", "--execute", "--confirm-send",
                         "--confirm-friend-preflight", "--report", str(path)]) == 2
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["taskAttempts"] == report["liveTasksExecuted"] == 1
    assert report["schedule"]["stoppedAfterFirstFailure"] is True
    assert len(report["schedule"]["tasks"]) == 1
    result = report["schedule"]["tasks"][0]["result"]
    assert result["taskId"] == "actual-gui-task"
    assert result["cleanup"] == {"success": True}
    assert result["health"]["blockingWindow"] is None
    assert result["health"]["sessionReady"] is True
    assert result["phase"] == phase
    assert result["active"] is (False if phase == "error" else active)
    assert actions.count("startMessageButton") == 1
    assert len(observations) == (3 if phase == "error" and active else 2)
    assert "PRIVATE_PAYLOAD" not in path.read_text(encoding="utf-8")


def test_active_snapshot_cannot_pass_even_with_success_counts(harness):
    case = harness.make_plan("active", 1)[0]
    with pytest.raises(ValueError, match="active"):
        harness.validate_result(case, {**successful_result(case), "active": True}, set())


def test_interrupted_snapshot_preserves_explicit_null_health_and_cleanup(harness):
    result = harness.result_evidence({"taskId": "started", "active": True,
                                      "phase": "recovering", "cleanup": None, "health": None})
    assert result["cleanup"] is None
    assert result["health"] is None
    assert result["taskId"] == "started"
    with pytest.raises(ValueError, match="active"):
        harness.validate_result(harness.make_plan("interrupted", 1)[0], result, set())


def test_report_evidence_omits_raw_event_details(harness):
    result = {"outcome": "error", "detail": "private payload", "events": [
        {"taskId": "one", "step": "search_ready", "outcome": "error",
         "detail": "private contact", "target": "private name", "errorCode": "UIA_ERROR"},
    ]}
    cleaned = harness.result_evidence(result)
    assert "private" not in json.dumps(cleaned)
    assert cleaned["events"][0]["errorCode"] == "UIA_ERROR"


def test_worker_watchdog_has_hard_deadline_without_retry(harness, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(harness.time, "monotonic", clock.monotonic)
    polls = []

    def poll(seconds):
        polls.append(seconds)
        clock.sleep(seconds)
        return False

    session = harness.WorkerSession.__new__(harness.WorkerSession)
    session.connection = SimpleNamespace(poll=poll)
    session.process = SimpleNamespace(is_alive=lambda: True)
    with pytest.raises(TimeoutError, match="no[ _]retry"):
        session.receive(1)
    assert clock.now == 1
    assert len(polls) == 5


def test_wechat_state_discovery_uses_current_window_helper(harness):
    import inspect
    source = inspect.getsource(harness.Desktop.prepare_wechat)
    assert "find_wechat_window_refs" in source
    assert "WeixinMainWndForPC" not in source


@pytest.mark.parametrize("field,value", [
    ("cleanup", {}), ("cleanup", {"success": False}), ("cleanup", {"success": 1}),
    ("health", {}),
    *[("health", {"windowEnabled": True, "windowResponsive": True,
                  "sessionReady": True, "blockingWindow": None, key: value})
      for key in ("windowEnabled", "windowResponsive", "sessionReady")
      for value in (False, None)],
    ("health", {"windowEnabled": True, "windowResponsive": True,
                "sessionReady": True, "blockingWindow": {"hwnd": 123}}),
])
def test_success_counts_cannot_conceal_environment_failure(harness, field, value):
    case = harness.make_plan("cleanup", 1)[0]
    result = successful_result(case)
    result[field] = value
    with pytest.raises(ValueError):
        harness.validate_result(case, result, set())


def test_result_keeps_sanitized_cleanup_health_and_build_identity(harness):
    result = successful_result(harness.make_plan("metadata", 1)[0])
    result["cleanup"]["detail"] = "private dialog caption"
    result["health"].update(detail="private account", blockingWindow={"hwnd": 5, "title": "private"})
    clean = harness.result_evidence(result)
    assert clean["cleanup"] == {"success": True}
    assert clean["health"]["blockingWindow"] == {"hwnd": 5}
    assert clean["buildFingerprint"] == result["buildFingerprint"]
    assert "private" not in json.dumps(clean)


def test_fixed_independent_is_exactly_twenty_plus_twenty_not_duration_limited(harness):
    clock = FakeClock()
    plan = harness.make_plan("independent", profile="independent")
    assert len(plan) == 40
    result = harness.run_schedule(successful_result, "independent", "independent", 10, 1,
                                  monotonic=clock.monotonic, sleep=clock.sleep)
    assert result["ok"]
    assert len(result["tasks"]) == 40
    assert sum(t["case"]["request"]["kind"] == "message_send" for t in result["tasks"]) == 20
    assert clock.now == 390


def test_changed_runtime_fingerprint_stops_independent_schedule(harness):
    calls = []

    def run(case):
        calls.append(case)
        result = successful_result(case)
        if len(calls) == 2:
            result["buildFingerprint"] = "sha256:" + "b" * 64
        return result

    result = harness.run_schedule(run, "identity", "independent", 10, 1, sleep=lambda _: None)
    assert not result["ok"]
    assert len(calls) == 2


def test_delivery_plan_and_files_are_explicit_generated_and_tamper_checked(harness, tmp_path):
    plan = harness.make_plan("delivery", profile="delivery", artifact_dir=tmp_path)
    assert len(plan) == 2
    assert all("useForward" not in c["request"]["options"] for c in plan)
    assert not list(tmp_path.iterdir()), "Planning must not generate attachments"
    for case in plan:
        harness.materialize_delivery(case, tmp_path)
        request = case["request"]
        harness.validate_request(request, delivery=True, artifact_dir=tmp_path)
        with pytest.raises(ValueError):
            harness.validate_request(request)
        path = Path(request["options"]["filePaths"][0])
        assert path.suffix == ".txt"
        path.write_text("not generated content", encoding="utf-8")
        with pytest.raises(ValueError):
            harness.validate_request(request, delivery=True, artifact_dir=tmp_path)


def test_delivery_requires_extra_confirmation_but_not_friend_authorization(harness):
    args = harness.parse_args(["--mode", "source", "--profile", "delivery", "--execute", "--confirm-send"])
    with pytest.raises(ValueError, match="confirm-delivery"):
        harness.validate_args(args)
    args.confirm_delivery = True
    harness.validate_args(args)


def test_delivery_requires_sub_boundaries_and_no_duplicate_observations(harness, tmp_path):
    case = harness.make_plan("proof", profile="delivery", artifact_dir=tmp_path)[0]
    result = successful_result(case)
    with pytest.raises(ValueError):
        harness.validate_result(case, result, set())
    result["deliveryEvidence"] = {
        "taskId": result["taskId"], "boundaries": {
            "text": {"started": 1, "completed": 1, "verified": True},
            "attachment": {"started": 1, "completed": 1, "verified": True},
        },
        "observed": {"text": 1, "attachment": 1},
        "baseline": {"text": 0, "attachment": 0},
    }
    harness.validate_result(case, result, set())
    result["deliveryEvidence"]["observed"]["attachment"] = 2
    with pytest.raises(ValueError, match="duplicate"):
        harness.validate_result(case, result, set())


def test_tray_close_resolution_waits_for_fresh_visible_control(harness, monkeypatch):
    control = SimpleNamespace(GetRuntimeId=lambda: [1, 2], ProcessId=7, Name="close")
    resolutions, actions = [], []
    monkeypatch.setattr(harness.time, "sleep", lambda _seconds: None)

    def resolve():
        resolutions.append(True)
        if len(resolutions) == 1:
            raise LookupError("Close has not appeared after window restore")
        return control

    harness.hide_to_tray(resolve, lambda c: actions.append("invoke"),
                         lambda c: actions.append("click"), lambda: "invoke" in actions,
                         lambda c: True, lambda value: None)

    assert len(resolutions) == 2
    assert actions == ["invoke"]


def test_tray_invoke_no_effect_allows_one_revalidated_bounds_fallback(harness):
    actions = []
    control = SimpleNamespace(GetRuntimeId=lambda: [1, 2], ProcessId=7, Name="close")

    def wait(hidden, **kwargs):
        if "click" not in actions:
            raise TimeoutError()
        assert hidden()

    harness.hide_to_tray(lambda: control, lambda c: actions.append("invoke"),
                         lambda c: actions.append("click"), lambda: "click" in actions,
                         lambda c: True, lambda value: None, wait=wait)
    assert actions == ["invoke", "click"]


def test_tray_fallback_rejects_changed_close_or_owner(harness):
    controls = iter([SimpleNamespace(GetRuntimeId=lambda: [1], ProcessId=7, Name="close"),
                     SimpleNamespace(GetRuntimeId=lambda: [2], ProcessId=7, Name="close")])
    clicks = []

    def timeout(*args, **kwargs):
        raise TimeoutError()

    with pytest.raises(ValueError):
        harness.hide_to_tray(lambda: next(controls), lambda c: None, clicks.append,
                             lambda: False, lambda c: True, lambda value: None, wait=timeout)
    assert not clicks


def test_safe_traceback_has_locations_and_timeout_not_private_message(harness):
    try:
        raise harness.AcceptanceTimeout("wechat.tray.verify_hidden", 3)
    except Exception as exc:
        data = harness.failure_evidence(exc)
    assert data["stage"] == "wechat.tray.verify_hidden"
    assert data["timeoutSeconds"] == 3
    assert data["traceback"][-1]["function"] == "test_safe_traceback_has_locations_and_timeout_not_private_message"
    try:
        raise ValueError("secret contact payload")
    except Exception as exc:
        assert "secret" not in json.dumps(harness.failure_evidence(exc))


def test_delivery_observation_counts_only_unique_text_and_file_bubbles(harness, tmp_path):
    case = harness.make_plan("observe", profile="delivery", artifact_dir=tmp_path)[1]
    text = case["request"]["items"][0]["message"]
    filename = Path(case["request"]["options"]["filePaths"][0]).name
    old = {"id": "old", "text": "聊天记录"}
    before = [old]
    after = [old, {"id": "text", "text": text}, {"id": "file", "text": filename},
             {"id": "forward", "text": "聊天记录"}]
    baseline, observed = harness.delivery_counts(case, before, after)
    assert baseline == {"text": 0, "attachment": 0}
    assert observed == {"text": 1, "attachment": 1}
    after.append({"id": "secondfile", "text": filename})
    assert harness.delivery_counts(case, before, after)[1]["attachment"] == 2


def test_delivery_diagnostics_require_one_action_pair_per_boundary(harness, tmp_path):
    case = harness.make_plan("actions", profile="delivery", artifact_dir=tmp_path)[0]
    records = []
    for action in ("trigger_send", "verify_sent", "send_files"):
        records.extend([
            {"action": action, "actionId": action, "outcome": "started"},
            {"action": action, "actionId": action, "outcome": "success",
             "result": {"type": "bool", "value": True} if action == "verify_sent"
             else {"type": "list", "length": 1}},
        ])
    result = harness.delivery_boundaries(case, records)
    assert result["text"]["verified"] is True
    assert result["attachment"]["verified"] is True
    records.append({"action": "trigger_send", "actionId": "duplicate", "outcome": "started"})
    assert harness.delivery_boundaries(case, records)["text"]["started"] == 2


def test_toggle_uses_pattern_and_readback_without_replay(harness):
    state = {"value": 0, "calls": 0}

    class Toggle:
        @property
        def ToggleState(self):
            return state["value"]

        def Toggle(self):
            state["calls"] += 1
            state["value"] = 1

    desktop = harness.Desktop.__new__(harness.Desktop)
    desktop.click = lambda c: pytest.fail("TogglePattern must take precedence")
    control = FakeControl()
    control.GetTogglePattern = lambda: Toggle()
    desktop.set_toggle(control, True, lambda: state["value"] == 1)
    desktop.set_toggle(control, True, lambda: state["value"] == 1)
    assert state["calls"] == 1


@pytest.mark.parametrize("profile,count", [("delivery", 2), ("independent", 40)])
def test_new_profiles_plan_without_live_adapter_or_attachment_creation(harness, tmp_path, monkeypatch, profile, count):
    monkeypatch.setattr(harness, "WorkerSession", lambda *args: pytest.fail("No live adapter in plan mode"))
    report = tmp_path / "plan.json"
    assert harness.main(["--profile", profile, "--report", str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert len(data["plan"]) == count
    assert data["status"] == "planned"
    assert not list(tmp_path.rglob("*.txt"))


def test_delivery_log_reader_filters_task_and_build_and_omits_context(harness, tmp_path):
    fingerprint = "sha256:" + "a" * 64
    rows = [
        {"taskId": "other", "action": "trigger_send", "context": {"message": "private"}},
        {"taskId": "wanted", "action": "trigger_send", "actionId": "one", "outcome": "started",
         "build": {"buildFingerprint": fingerprint}, "context": {"message": "private"}},
    ]
    log = tmp_path / "uia-diagnostics.jsonl"
    log.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    result = harness.read_delivery_actions(tmp_path, "wanted", fingerprint)
    assert result == [{"action": "trigger_send", "actionId": "one", "outcome": "started"}]
    with pytest.raises(ValueError, match="fingerprint"):
        harness.read_delivery_actions(tmp_path, "wanted", "sha256:" + "b" * 64)


def test_delivery_log_reader_reads_bounded_tail_of_oversized_rotation(harness, tmp_path):
    fingerprint = "sha256:" + "a" * 64
    row = {"taskId": "wanted", "action": "trigger_send", "actionId": "one", "outcome": "success",
           "build": {"buildFingerprint": fingerprint}}
    (tmp_path / "uia-diagnostics.jsonl.2").write_bytes(
        b"x" * (2 * 1024 * 1024 + 13) + b"\n" + json.dumps(row).encode() + b"\n")

    assert harness.read_delivery_actions(tmp_path, "wanted", fingerprint) == [
        {"action": "trigger_send", "actionId": "one", "outcome": "success"}]


def test_post_send_evidence_failure_preserves_completed_task_without_replay(harness, tmp_path, monkeypatch):
    case = harness.make_plan("proof", profile="delivery", artifact_dir=tmp_path)[0]
    result = successful_result(case)
    desktop = SimpleNamespace(delivery_snapshot=lambda: [])

    def fail(*_args):
        raise ValueError("private diagnostic context")

    monkeypatch.setattr(harness, "read_delivery_actions", fail)
    returned = harness.attach_delivery_evidence(case, result, [], desktop, tmp_path)
    assert returned is result
    assert returned["outcome"] == "success"
    assert returned["taskId"]
    assert returned["deliveryVerificationError"]["errorType"] == "ValueError"
    safe = harness.result_evidence(returned)
    assert safe["deliveryVerificationError"]["errorType"] == "ValueError"
    assert "private" not in json.dumps(safe)
    with pytest.raises(ValueError, match="Post-send"):
        harness.validate_result(case, returned, set())


def test_gui_delivery_cannot_remove_an_unrelated_attachment(harness):
    gui = harness.GuiAdapter.__new__(harness.GuiAdapter)
    gui.loaded_files = set()
    gui.editor_state = lambda: {"options": {"filePaths": ["private.txt"]}}
    gui.click = lambda name: pytest.fail("Must not alter unrelated attachment")
    with pytest.raises(ValueError, match="unrelated"):
        gui.configure_delivery({"options": {"filePaths": ["generated.txt"]}})


def test_delivery_evidence_redaction_drops_unrecognized_fields(harness):
    cleaned = harness.result_evidence({"deliveryEvidence": {
        "taskId": "one", "rawPayload": "secret", "baseline": {"text": 0, "private": "secret"},
        "observed": {"text": 1}, "boundaries": {"text": {"started": 1, "completed": 1,
            "verified": True, "detail": "secret"}},
    }})
    assert "secret" not in json.dumps(cleaned)


def test_cursor_mismatch_error_keeps_only_numeric_expected_and_actual(harness):
    exc = RuntimeError("cursor position mismatch: expected=(-250, 120), actual=(-200, 96)")
    assert harness.failure_evidence(exc)["cursor"] == {"expected": [-250, 120], "actual": [-200, 96]}
    unsafe = RuntimeError(str(exc) + " private payload")
    assert "cursor" not in harness.failure_evidence(unsafe)
    assert "private" not in json.dumps(harness.failure_evidence(unsafe))


def test_dpi_awareness_is_set_then_verified_before_desktop_or_qt(harness):
    calls = []
    api = SimpleNamespace(
        set_process=lambda: calls.append("process") or False,
        set_thread=lambda: calls.append("thread") or 123,
        last_error=lambda: 5,
        snapshot=lambda: calls.append("verify") or {"threadAwareness": 2, "perMonitorV2": True},
    )
    data = harness.configure_dpi_awareness(api)
    assert calls == ["process", "thread", "verify"]
    assert data["processSet"] is False
    assert data["processError"] == 5
    assert data["threadAwareness"] == 2
    import inspect
    worker = inspect.getsource(harness.worker_main)
    assert worker.index("configure_dpi_awareness(") < worker.index("adapter_type(args")
    desktop = inspect.getsource(harness.Desktop.__init__)
    assert desktop.index("configure_dpi_awareness(") < desktop.index("from src.core import uiautomation")


def test_failed_dpi_verification_fails_closed(harness):
    api = SimpleNamespace(set_process=lambda: True, set_thread=lambda: 123,
                          last_error=lambda: 0,
                          snapshot=lambda: {"threadAwareness": 0, "perMonitorV2": False})
    with pytest.raises(ValueError, match="DPI"):
        harness.configure_dpi_awareness(api)


@pytest.mark.parametrize("bounds,work,expected", [
    ((1090, 179, 1992, 898), (0, 0, 1920, 1040), (1018, 179, 1920, 898)),
    ((100, 200, 900, 800), (0, 0, 1920, 1040), (100, 200, 900, 800)),
    ((-50, -30, 750, 570), (0, 40, 1920, 1080), (0, 40, 800, 640)),
    ((1700, 900, 2500, 1500), (0, 0, 1920, 1040), (1120, 440, 1920, 1040)),
    ((-2050, 150, -1150, 750), (-1920, 0, 0, 1040), (-1920, 150, -1020, 750)),
    ((-700, -80, 200, 620), (-1920, 0, 0, 1040), (-900, 0, 0, 700)),
    ((-1800, 100, -900, 800), (-1920, 0, 0, 1040), (-1800, 100, -900, 800)),
    ((100, -1300, 900, -700), (0, -1080, 1920, -40), (100, -1080, 900, -480)),
])
def test_clamp_window_to_monitor_work_area_preserves_size(harness, bounds, work, expected):
    actual = harness.clamp_window_to_work_area(bounds, work)
    assert actual == expected
    assert actual[2] - actual[0] == bounds[2] - bounds[0]
    assert actual[3] - actual[1] == bounds[3] - bounds[1]


@pytest.mark.parametrize("bounds,work", [
    ((0, 0, 2000, 600), (0, 0, 1920, 1040)),
    ((0, 0, 800, 1100), (0, 0, 1920, 1040)),
    ((0, 0, 0, 600), (0, 0, 1920, 1040)),
    ((0, 0, 800, 600), (0, 0, 0, 1040)),
])
def test_work_area_clamp_refuses_impossible_geometry_without_resizing(harness, bounds, work):
    with pytest.raises(ValueError):
        harness.clamp_window_to_work_area(bounds, work)


def test_fit_main_window_uses_monitor_geometry_and_no_resize_move(harness):
    desktop = harness.Desktop.__new__(harness.Desktop)
    state = {"bounds": (1090, 179, 1992, 898)}
    moves, notices = [], []

    def move(hwnd, after, x, y, width, height, flags):
        moves.append((hwnd, after, x, y, width, height, flags))
        old = state["bounds"]
        state["bounds"] = (x, y, x + old[2] - old[0], y + old[3] - old[1])

    desktop.win = SimpleNamespace(GetWindowRect=lambda hwnd: state["bounds"], SetWindowPos=move,
                                  IsWindow=lambda hwnd: True, IsWindowEnabled=lambda hwnd: True)
    desktop.proc = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, 7))
    desktop.monitors = SimpleNamespace(MonitorFromWindow=lambda hwnd, flags: 123,
                                       GetMonitorInfo=lambda monitor: {"Work": (0, 0, 1920, 1040)})
    desktop.dpi_api = SimpleNamespace(snapshot=lambda: {"threadAwareness": 2, "perMonitorV2": True})
    desktop.notice = notices.append
    evidence = desktop.fit_main_window(55, 7)
    assert evidence["before"] == [1090, 179, 1992, 898]
    assert evidence["after"] == [1018, 179, 1920, 898]
    assert evidence["workArea"] == [0, 0, 1920, 1040]
    assert len(moves) == 1
    assert moves[0][2:6] == (1018, 179, 0, 0)
    assert moves[0][-1] & 1, "SWP_NOSIZE must preserve the original dimensions"
    desktop.fit_main_window(55, 7)
    assert len(moves) == 1, "Already fitting windows must not be moved"


@pytest.mark.parametrize("scenario", [
    "already-foreground", "activate", "invalid-before", "pid-before", "disabled-before",
    "invalid-after", "pid-after", "disabled-after", "wrong-foreground", "helper-failed",
    "already-foreground-invalid",
])
def test_activate_gui_verifies_identity_and_foreground(harness, monkeypatch, scenario):
    state = {"valid": True, "pid": 7, "enabled": True, "foreground": 99}
    calls = []
    desktop = object.__new__(harness.Desktop)
    desktop.notice = lambda value: None
    desktop.win = SimpleNamespace(
        IsWindow=lambda hwnd: state["valid"],
        IsWindowEnabled=lambda hwnd: state["enabled"],
        GetForegroundWindow=lambda: state["foreground"],
    )
    desktop.proc = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, state["pid"]))
    if scenario.startswith("already-foreground"):
        state["foreground"] = 55
    if scenario in {"invalid-before", "already-foreground-invalid"}:
        state["valid"] = False
    elif scenario == "pid-before":
        state["pid"] = 8
    elif scenario == "disabled-before":
        state["enabled"] = False

    def activate(hwnd):
        calls.append(hwnd)
        state["foreground"] = 55
        if scenario == "invalid-after":
            state["valid"] = False
        elif scenario == "pid-after":
            state["pid"] = 8
        elif scenario == "disabled-after":
            state["enabled"] = False
        elif scenario == "wrong-foreground":
            state["foreground"] = 99
        return scenario != "helper-failed"

    monkeypatch.setitem(sys.modules, "src.core.win32", SimpleNamespace(
        _foreground_with_thread_handshake=activate))
    if scenario in {"activate", "already-foreground"}:
        desktop.activate_gui(55, 7)
    else:
        with pytest.raises(ValueError):
            desktop.activate_gui(55, 7)
    skipped = scenario.endswith("before") or scenario.startswith("already-foreground")
    assert calls == ([] if skipped else [55])


@pytest.mark.parametrize("kind", ["message_send", "friend_add"])
@pytest.mark.parametrize("state", ["editor", "monitor", "hidden-only", "no-effect"])
def test_gui_open_editor_uses_visible_controls_not_last_task_kind(harness, monkeypatch, kind, state):
    actions = []
    clock = FakeClock()
    monkeypatch.setattr(harness.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(harness.time, "sleep", clock.sleep)

    class Node:
        IsEnabled = True

        def __init__(self, name, hidden=False, children=()):
            self.Name, self.IsOffscreen, self.children = name, hidden, children

        def GetChildren(self):
            return self.children

    # An empty friend import table has no account delegate yet.
    field_name = "messageRecipientsInput" if kind == "message_send" else "importFriendsButton"
    hidden_return = Node("taskReturnToEditorButton", True)
    visible_return = Node("taskReturnToEditorButton")
    editor = Node(field_name)
    roots = []

    def root(hwnd):
        assert workspace_reads >= 2, "Wait for the selected workspace before looking for controls"
        roots.append(hwnd)
        children = [hidden_return, Node(field_name, True)]
        if state == "editor" or (state == "monitor" and actions):
            children.append(editor)
        elif state in {"monitor", "no-effect"}:
            children.append(visible_return)
        return Node("root", children=children)

    def invoke(control):
        assert control is visible_return, "Never invoke the other workspace's hidden return button"
        actions.append(control)

    workspace_reads = 0

    def snapshot(name):
        nonlocal workspace_reads
        assert name == "acceptanceEditorState", "Last task kind is not workspace navigation state"
        workspace_reads += 1
        return {"kind": "switching" if workspace_reads == 1 else kind}

    adapter = object.__new__(harness.GuiAdapter)
    adapter.hwnd = 55
    adapter.snapshot = snapshot
    adapter.desktop = SimpleNamespace(root=root, invoke=invoke)
    adapter.notice = lambda value: None
    if state in {"hidden-only", "no-effect"}:
        with pytest.raises(harness.AcceptanceTimeout):
            adapter.open_editor(kind)
    else:
        adapter.open_editor(kind)
    assert len(actions) == (1 if state in {"monitor", "no-effect"} else 0)
    if state == "monitor":
        assert len(roots) >= 2, "Invoke alone does not establish editor visibility"


def test_gui_run_uses_verified_activation_at_both_boundaries(harness):
    import inspect
    source = inspect.getsource(harness.GuiAdapter.run)
    assert "SetForegroundWindow" not in source
    assert source.count("self.desktop.activate_gui(self.hwnd, self.process.pid)") == 2
    assert 'self.snapshot("acceptanceTaskState").get("kind")' not in source
    assert source.index("self.open_editor(kind)") < source.index("self.desktop.fill(")


def test_tray_fixture_uses_verified_activation(harness):
    import inspect
    source = inspect.getsource(harness.Desktop.prepare_wechat)
    assert "SetForegroundWindow" not in source
    assert 'self.activate_gui(hwnd, pid, role="wechat")' in source


def test_prepare_fits_window_before_close_control_lookup(harness):
    import inspect
    source = inspect.getsource(harness.Desktop.prepare_wechat)
    assert source.index("fit_main_window(") < source.index("hide_to_tray(")
    assert source.index("ShowWindow(hwnd, 9)") < source.index("fit_main_window(")


def test_gui_startup_selects_message_settings_before_reading_intervals(harness, monkeypatch, tmp_path):
    actions = []
    state = {"section": None}

    def click(self, name):
        actions.append(name)
        if name == "settingsButton":
            state["section"] = 3
        elif name == "settingsSection0":
            state["section"] = 0

    def control(self, name):
        if name in {"settingsMessageIntervalMin", "settingsMessageIntervalMax"}:
            assert state["section"] == 0, "Appearance must be changed to message settings first"
            actions.append("read:" + name)
        return SimpleNamespace(Name=name)

    monkeypatch.setattr(harness.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=123))
    monkeypatch.setattr(harness, "Desktop", lambda notice: SimpleNamespace(read=lambda control: "2"))
    monkeypatch.setattr(harness.GuiAdapter, "find_window", lambda self: 55)
    monkeypatch.setattr(harness.GuiAdapter, "click", click)
    monkeypatch.setattr(harness.GuiAdapter, "control", control)
    monkeypatch.setattr(harness.GuiAdapter, "snapshot", lambda self, name: {
        "friendSubmitEnabled": False, "active": False, "buildFingerprint": "sha256:" + "a" * 64,
    })
    args = SimpleNamespace(gui_exe=str(tmp_path / "candidate.exe"), startup_timeout=20)
    harness.GuiAdapter(args, lambda value: None)
    assert actions.index("settingsButton") < actions.index("settingsSection0")
    assert actions.index("settingsSection0") < actions.index("read:settingsMessageIntervalMin")
    assert actions.index("read:settingsMessageIntervalMax") < actions.index("settingsCloseButton")
