"""Restore the real frozen GUI with its artifact-only Agent temporarily absent."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import os
import sys
import tempfile
import time
import uuid

from PIL import ImageGrab
import win32api
import win32con
import win32gui
import win32job
import win32process
import win32event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.manual_window_restore_rendering import compare_colors


def run(executable, output, software):
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    output.mkdir(parents=True, exist_ok=True)
    job = win32job.CreateJobObject(None, "FugeRestoreGate-" + uuid.uuid4().hex)
    limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
    agent_path = executable.with_name("wechat-agent.exe")
    assert agent_path.is_relative_to(ROOT / ".artifacts/restore-fix/frozen")
    disabled_agent = agent_path.with_suffix(".disabled")
    assert agent_path.is_file() and not disabled_agent.exists()
    report = {"frozenExecutable": str(executable), "agentTemporarilyAbsent": True,
              "softwareRequested": software, "captureOrder": "external desktop only", "restores": []}
    from PySide6.QtCore import QSettings
    preferences = QSettings("wx4py", "WeChatCourier")
    saved_preferences = {key: preferences.value(key) for key in preferences.allKeys()}
    with tempfile.TemporaryDirectory() as temporary:
        env = {**os.environ, "LOCALAPPDATA": temporary, "WECHAT_AGENT_GATE_LEASE": str(Path(temporary) / "gate.json"),
               "WECHAT_AGENT_JOURNAL": str(Path(temporary) / "journal.json")}
        if software:
            env["QT_OPENGL"] = "software"
        process, thread, pid, _ = win32process.CreateProcess(str(executable), None, None, None, False,
            win32con.CREATE_SUSPENDED | win32con.CREATE_UNICODE_ENVIRONMENT, env,
            str(executable.parent), win32process.STARTUPINFO())
        try:
            agent_path.rename(disabled_agent)
            win32job.AssignProcessToJobObject(job, process)
            win32process.ResumeThread(thread)
            hwnd = 0
            end = time.monotonic() + 20
            while not hwnd and time.monotonic() < end:
                matches = []
                win32gui.EnumWindows(lambda handle, _: matches.append(handle) if (
                    win32process.GetWindowThreadProcessId(handle)[1] == pid and win32gui.IsWindowVisible(handle)
                    and win32gui.GetClassName(handle).startswith("Qt")) else None, None)
                hwnd = matches[0] if matches else 0
                time.sleep(0.1)
            assert hwnd, "Frozen GUI did not show a window"
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
            time.sleep(3)
            dark = QSettings("wx4py", "WeChatCourier").value("isDark", False, type=bool)

            def capture(name):
                bounds = wintypes.RECT()
                assert ctypes.windll.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(hwnd), 9,
                    ctypes.byref(bounds), ctypes.sizeof(bounds)) == 0
                image = ImageGrab.grab(bbox=(bounds.left, bounds.top, bounds.right, bounds.bottom), all_screens=True).convert("RGB")
                image.save(output / f"{name}.png")
                return image

            end = time.monotonic() + 20
            while True:
                baseline = capture("startup")
                try:
                    compare_colors(baseline, baseline, dark)
                    # The artifact Agent is deliberately absent. Its red offline
                    # header confirms the bounded connect banner has settled.
                    header_height = round(40 * ctypes.windll.user32.GetDpiForWindow(hwnd) / 96)
                    header = baseline.crop((round(baseline.width * 0.6), 0,
                                            round(baseline.width * 0.92), header_height))
                    pixels = header.load()
                    assert sum(r > 160 and r - g > 60 and r - b > 50
                               for y in range(header.height) for x in range(header.width)
                               for r, g, b in (pixels[x, y],)) >= 8
                    break
                except AssertionError:
                    assert time.monotonic() < end, "Frozen GUI content/offline header did not settle"
                    time.sleep(0.5)

            for cycle in range(12):
                maximize = cycle % 4 == 3
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWMAXIMIZED if maximize else win32con.SW_SHOWNORMAL)
                time.sleep(0.4)
                reference = capture(f"{cycle}-before")
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE if cycle == 11 else win32con.SW_MINIMIZE)
                time.sleep(0.1)
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWMAXIMIZED if maximize else win32con.SW_RESTORE)
                time.sleep(0.2)
                immediate = capture(f"{cycle}-immediate")
                time.sleep(0.5)
                idle = capture(f"{cycle}-idle")
                report["restores"].append({"cycle": cycle, "maximized": maximize,
                    "immediate": compare_colors(reference, immediate, dark), "idle": compare_colors(reference, idle, dark)})
            libraries = [Path(win32process.GetModuleFileNameEx(process, module)).name.lower()
                         for module in win32process.EnumProcessModules(process)]
            report["softwareOpenGLLoaded"] = "opengl32sw.dll" in libraries
            assert not software or report["softwareOpenGLLoaded"]
            diag = Path(temporary) / "WxAuto/logs/window-rendering.log"
            text = diag.read_text(encoding="utf-8")
            assert "renderer=OpenGL" in text
            (output / "window-rendering.log").write_text(text, encoding="utf-8")
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            assert win32event.WaitForSingleObject(process, 10000) == win32event.WAIT_OBJECT_0
            assert win32process.GetExitCodeProcess(process) == 0
            report["normalShutdown"] = True
            preferences.sync()
            report["settingsUnchanged"] = saved_preferences == {key: preferences.value(key) for key in preferences.allKeys()}
            assert report["settingsUnchanged"]
            print(json.dumps({key: value for key, value in report.items() if key != "restores"}))
        finally:
            win32job.TerminateJobObject(job, 1)
            if win32process.GetExitCodeProcess(process) == win32con.STILL_ACTIVE:
                win32api.TerminateProcess(process, 1)
            win32event.WaitForSingleObject(process, 10000)
            diag = Path(temporary) / "WxAuto/logs/window-rendering.log"
            if diag.is_file():
                (output / "window-rendering.log").write_bytes(diag.read_bytes())
            if disabled_agent.is_file():
                disabled_agent.rename(agent_path)
            win32api.CloseHandle(thread)
            win32api.CloseHandle(process)
            win32api.CloseHandle(job)
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--software", action="store_true")
    args = parser.parse_args()
    run(args.executable.resolve(), args.output.resolve(), args.software)
