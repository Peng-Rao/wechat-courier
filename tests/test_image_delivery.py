from pathlib import Path

import pytest

from tests import manual_v032_gui_acceptance as harness
from app.agent.native_driver import NativeWeixinDriver


def test_image_delivery_plan_is_small_and_only_uses_generated_assets(tmp_path):
    cases = harness.make_plan("image-proof", profile="images", artifact_dir=tmp_path)
    assert len(cases) == 3
    assert [len(c["request"]["options"]["filePaths"]) for c in cases] == [1, 1, 2]
    assert not list(tmp_path.iterdir())
    for case in cases:
        harness.materialize_delivery(case, tmp_path)
        harness.validate_request(case["request"], delivery=True, artifact_dir=tmp_path)
        for value in case["request"]["options"]["filePaths"]:
            path = Path(value)
            assert path.parent == tmp_path
            assert path.stat().st_size <= 65536
        with pytest.raises(ValueError):
            harness.validate_request(case["request"])
    image = Path(cases[0]["request"]["options"]["filePaths"][0])
    image.write_bytes(b"not the generated image")
    with pytest.raises(ValueError, match="generated"):
        harness.validate_request(cases[0]["request"], delivery=True, artifact_dir=tmp_path)


def test_image_delivery_execution_requires_explicit_send_and_delivery_confirmation():
    args = harness.parse_args(["--mode", "source", "--profile", "images", "--execute", "--confirm-send"])
    with pytest.raises(ValueError, match="confirm-delivery"):
        harness.validate_args(args)
    args.confirm_delivery = True
    harness.validate_args(args)


def sending_driver(monkeypatch):
    driver = NativeWeixinDriver(gate_backend=object())
    driver._composer = object()
    driver._click_bounds = lambda _control: None
    driver._send_keys = lambda control, *_args, **_kwargs: control
    driver._attachment_draft_visible = lambda _filename: False
    driver.read_composer_text = lambda: "\ufffc"
    monkeypatch.setattr("src.utils.clipboard_utils.set_files_to_clipboard", lambda _paths: True)
    return driver


def test_image_send_skips_verification_only_after_successful_trigger(tmp_path, monkeypatch):
    image = tmp_path / "source.png"
    image.write_bytes(harness.benign_image("source"))
    driver = sending_driver(monkeypatch)
    driver.attachment_snapshot = lambda: pytest.fail("Image bypass must not query message history")
    driver.verify_attachment_sent = lambda *_a, **_k: pytest.fail("Image verification is disabled")
    sends = []
    driver._invoke_once_or_key = lambda *_args: sends.append(True)

    result = driver.send_files([str(image)])[0]

    assert sends == [True]
    assert result["outcome"] == "success"
    assert result["verificationSkipped"] is True
    assert result["verified"] is False
    assert result["detail"] == "发送成功"
    assert driver.diagnostic_snapshot()["attachmentVerification"]["status"] == "IMAGE_VERIFICATION_SKIPPED"


def test_image_trigger_failure_never_reports_success_or_retries(tmp_path, monkeypatch):
    image = tmp_path / "source.png"
    image.write_bytes(harness.benign_image("source"))
    driver = sending_driver(monkeypatch)
    driver.attachment_snapshot = lambda: ()
    sends = []

    def fail(*_args):
        sends.append(True)
        raise RuntimeError("Enter failed or composer did not clear")

    driver._invoke_once_or_key = fail
    with pytest.raises(RuntimeError, match="composer did not clear"):
        driver.send_files([str(image)])
    assert sends == [True]


def test_empty_image_draft_is_not_reported_as_sent(tmp_path, monkeypatch):
    image = tmp_path / "source.png"
    image.write_bytes(harness.benign_image("source"))
    driver = sending_driver(monkeypatch)
    driver.attachment_snapshot = lambda: ()
    driver.read_composer_text = lambda: ""
    driver._invoke_once_or_key = lambda *_args: pytest.fail("No image was pasted")
    assert driver.send_files([str(image)])[0]["outcome"] != "success"


def test_non_image_attachment_still_uses_original_verification(tmp_path, monkeypatch):
    document = tmp_path / "document.png"
    document.write_bytes(b"This is not an image, despite its extension.")
    driver = sending_driver(monkeypatch)
    before = object()
    driver.attachment_snapshot = lambda: before
    driver._invoke_once_or_key = lambda *_args: None
    calls = []
    driver.verify_attachment_sent = lambda *args, **kwargs: calls.append((args, kwargs)) or True
    result = driver.send_files([str(document)])[0]
    assert result["outcome"] == "success"
    assert not result.get("verificationSkipped")
    assert calls == [((before, document.name, driver._timeout), {"draft_was_visible": False})]


@pytest.mark.parametrize("with_text", [False, True])
def test_image_bypass_displays_success_without_skip_notice_and_keeps_boundary(with_text):
    from app.agent.contracts import TaskItem, TaskOptions
    from tests.test_agent_workflows import FakeDriver, request, run_engine

    class ImageDriver(FakeDriver):
        def send_files(self, paths):
            self.sent_files.append(tuple(paths))
            return [{"path": path, "outcome": "success", "verified": False,
                     "verificationSkipped": True, "detail": "发送成功"} for path in paths]

    driver = ImageDriver()
    driver.search_results = {"Alice": ["Alice"]}
    result, events = run_engine(driver, request(
        "message_send", [TaskItem("one", target="Alice", message="hello" if with_text else "")],
        TaskOptions(file_paths=("image.png",)),
    ))
    assert result["success"] == 1
    assert result["unknown"] == 0
    assert driver.sent_files == [("image.png",)]
    assert events[-1]["outcome"] == "success"
    assert "发送成功" in events[-1]["detail"]
    assert "暂跳过" not in events[-1]["detail"]
    assert "已确认" not in events[-1]["detail"]
    assert events[-1]["destructiveBoundaryCrossed"] is True
