from __future__ import annotations

import pytest

from app.agent.gate import (
    IMAGE_SCN_MEM_WRITE,
    ProcessModule,
    WeixinAccessibilitySession,
)
from app.agent.profile import UnsupportedWeixinVersion


class FakeGateBackend:
    def __init__(self):
        self.hwnd = 101
        self.pid = 202
        self.module = ProcessModule(0x10000000, 0x0B000000, "Weixin.dll")
        self.version = "4.1.13.65"
        self.section = (".data", IMAGE_SCN_MEM_WRITE)
        self.memory = {self.module.base + 0x0AE2B0C8: 0}
        self.screen_reader = False
        self.opened = False
        self.closed = False
        self.writes = []

    def find_main_window(self):
        return self.hwnd

    def get_window_pid(self, hwnd):
        assert hwnd == self.hwnd
        return self.pid

    def find_module(self, pid, name):
        assert (pid, name) == (self.pid, "Weixin.dll")
        return self.module

    def file_version(self, path):
        return self.version

    def pe_section_for_rva(self, path, rva):
        return self.section

    def open_process(self, pid):
        self.opened = True
        return "handle"

    def close_process(self, handle):
        assert handle == "handle"
        self.closed = True

    def read_byte(self, handle, address):
        return self.memory.get(address)

    def write_byte(self, handle, address, value):
        self.writes.append((address, value))
        self.memory[address] = value
        return True

    def get_screen_reader(self):
        return self.screen_reader

    def set_screen_reader(self, enabled):
        self.screen_reader = enabled
        return True


def test_accessibility_session_verifies_enables_and_restores_gate():
    backend = FakeGateBackend()

    with WeixinAccessibilitySession(backend) as session:
        assert session.version == "4.1.13.65"
        assert session.profile.chat_input_automation_id == "chat_input_field"
        assert backend.memory[session.gate_address] == 1
        assert backend.screen_reader is True

    assert backend.memory[session.gate_address] == 0
    assert backend.screen_reader is False
    assert backend.closed is True


def test_accessibility_session_does_not_guess_an_unknown_version():
    backend = FakeGateBackend()
    backend.version = "4.1.14.1"

    with pytest.raises(UnsupportedWeixinVersion):
        WeixinAccessibilitySession(backend).__enter__()

    assert backend.opened is False
    assert backend.writes == []


def test_accessibility_session_requires_a_writable_in_range_gate():
    backend = FakeGateBackend()
    backend.section = (".rdata", 0)
    with pytest.raises(RuntimeError, match="non-writable"):
        WeixinAccessibilitySession(backend).__enter__()
    assert backend.opened is False

    backend = FakeGateBackend()
    backend.module = ProcessModule(0x10000000, 0x1000, "Weixin.dll")
    with pytest.raises(RuntimeError, match="module size"):
        WeixinAccessibilitySession(backend).__enter__()
    assert backend.opened is False


def test_accessibility_session_rejects_an_unexpected_original_byte():
    backend = FakeGateBackend()
    address = backend.module.base + 0x0AE2B0C8
    backend.memory[address] = 7

    with pytest.raises(RuntimeError, match="unexpected gate value"):
        WeixinAccessibilitySession(backend).__enter__()

    assert backend.writes == []
    assert backend.closed is True
