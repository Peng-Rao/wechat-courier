"""Synthetic WCDB objects; no real account, process, or key material."""

import struct
import threading
import time

import pytest

from app.contacts import native
from tests.test_contact_native import FakeProbe, identity, budget


ANCHOR = b"com.Tencent.WCDB.Config.Cipher"
MASK = bytes.fromhex("d2c7442458020000004889442450488b450048844c2448488944254048584c24")
BASE = 0x10000


class WCDBProbe(FakeProbe):
    def __init__(self, *, key=b"k" * 32, salt=b"s" * 16, raw=False, count=1):
        super().__init__([identity(native)], bytearray(0x60000))
        self.anchors = [BASE + 101]
        self.nodes, self.configs, self.blobs = [], [], []
        self.place(self.anchors[0], ANCHOR)
        for index in range(count):
            node = BASE + 0x10000 + index * 0x80
            config = BASE + 0x20000 + index * 0x100
            blob = BASE + 0x40000 + index * 0x100
            literal = ("x'" + key.hex() + ("" if raw else salt.hex()) + "'").encode()
            encoded = bytes(v ^ MASK[i % len(MASK)] for i, v in enumerate(literal))
            self.place(node + 0x10, struct.pack("<QQ", self.anchors[0], len(ANCHOR)))
            self.place(node + 0x28, struct.pack("<Q", config))
            self.place(config + 0x90, struct.pack("<QQ", blob, len(encoded)))
            self.place(blob, encoded)
            self.nodes.append(node)
            self.configs.append(config)
            self.blobs.append(blob)
        self.truncate_at = None
        self.cancel_after = None
        self.change_at = None
        self.returned_buffers = []

    def place(self, address, data):
        offset = address - BASE
        self.memory[offset:offset + len(data)] = data

    def memory_regions(self, handle):
        yield BASE, len(self.memory)

    def read_memory(self, handle, address, size):
        self.events.append(("read", address, size))
        offset = address - BASE
        count = min(size, 7) if self.short_reads else size
        value = bytearray(self.memory[offset:offset + count]) if 0 <= offset < len(self.memory) else bytearray()
        if self.truncate_at is not None and address <= self.truncate_at < address + size:
            del value[max(0, self.truncate_at - address):]
        if address == self.truncate_at:
            value.clear()
        if self.cancel_after is not None:
            self.cancel_after.set()
        if self.change_after_read and (self.change_at is None or address == self.change_at):
            self.identities[handle] = self.change_after_read
        self.returned_buffers.append(value)
        return value


def extract(probe, **kwargs):
    return [bytes(key) for key in native.candidate_keys(
        probe, identity(native), b"s" * 16, **budget(), **kwargs)]


@pytest.mark.parametrize("raw", [False, True])
def test_wcdb_masked_material_is_a_candidate_not_a_plaintext_literal(raw):
    probe = WCDBProbe(raw=raw)
    assert (b"k" * 32).hex().encode() not in probe.memory
    assert extract(probe) == [b"k" * 32]
    assert probe.events[-1] == ("close", 71)
    assert all(not any(buffer) for buffer in probe.returned_buffers)


@pytest.mark.parametrize("chunk_size", [31, 64, 257])
def test_anchor_and_reference_cross_chunks_and_partial_reads(chunk_size):
    probe = WCDBProbe()
    probe.short_reads = chunk_size == 257
    assert extract(probe, chunk_size=chunk_size) == [b"k" * 32]
    assert max(event[2] for event in probe.events if event[0] == "read") <= chunk_size


@pytest.mark.parametrize("fault", ["node-pointer", "config-pointer", "blob-pointer", "length", "truncated", "wrong-salt", "unmasked"])
def test_invalid_configuration_is_never_yielded(fault):
    probe = WCDBProbe(salt=b"z" * 16 if fault == "wrong-salt" else b"s" * 16)
    if fault == "node-pointer":
        probe.place(probe.nodes[0] + 0x10, struct.pack("<Q", BASE + 999))
    elif fault == "config-pointer":
        probe.place(probe.nodes[0] + 0x28, struct.pack("<Q", 0x800000000000))
    elif fault == "blob-pointer":
        probe.place(probe.configs[0] + 0x90, struct.pack("<Q", BASE + len(probe.memory) + 1))
    elif fault == "length":
        probe.place(probe.configs[0] + 0x98, struct.pack("<Q", 1025))
    elif fault == "truncated":
        probe.truncate_at = probe.blobs[0] + 40
    elif fault == "unmasked":
        probe.place(probe.blobs[0], b"-" * 99)
    assert extract(probe) == []
    assert probe.events[-1] == ("close", 71)


def test_duplicate_configuration_material_is_yielded_and_wiped_once():
    probe = WCDBProbe(count=3)
    values = native.candidate_keys(probe, identity(native), b"s" * 16, **budget())
    first = next(values)
    assert bytes(first) == b"k" * 32
    assert list(values) == []
    assert first == bytearray(32)


def test_closing_generator_releases_remote_buffers_and_candidate():
    probe = WCDBProbe()
    values = native.candidate_keys(probe, identity(native), b"s" * 16, **budget())
    first = next(values)
    values.close()
    assert first == bytearray(32)
    assert all(not any(buffer) for buffer in probe.returned_buffers)
    assert probe.events[-1] == ("close", 71)


@pytest.mark.parametrize("limit", ["anchors", "structures"])
def test_configuration_scan_caps_are_explicit_failures(limit):
    probe = WCDBProbe(count=129 if limit == "structures" else 1, salt=b"z" * 16)
    if limit == "anchors":
        for index in range(33):
            probe.place(BASE + 101 + index * 128, ANCHOR)
    with pytest.raises(native.ContactError) as error:
        extract(probe)
    assert error.value.code == "KEY_SCAN_LIMIT"
    assert probe.events[-1] == ("close", 71)


def test_cancellation_during_read_closes_handle_and_wipes_buffer():
    probe = WCDBProbe()
    cancel = threading.Event()
    probe.cancel_after = cancel
    with pytest.raises(native.ContactError) as error:
        list(native.candidate_keys(probe, identity(native), b"s" * 16,
                                  cancel=cancel, deadline=time.monotonic() + 15))
    assert error.value.code == "CANCELLED"
    assert all(not any(buffer) for buffer in probe.returned_buffers)
    assert probe.events[-1] == ("close", 71)


def test_process_change_after_config_read_never_yields_key():
    probe = WCDBProbe()
    probe.change_after_read = identity(native, start_time=999)
    probe.change_at = probe.configs[0] + 0x88
    with pytest.raises(native.ContactError) as error:
        extract(probe)
    assert error.value.code == "PROCESS_CHANGED"
    assert probe.events[-1] == ("close", 71)


def test_deadline_expiring_during_config_read_wipes_buffers():
    from unittest.mock import patch

    native_clock = time.monotonic
    probe = WCDBProbe()
    until = native_clock() + 15
    def clock():
        expired = any(event[0] == "read" and event[1] == probe.configs[0] + 0x88 for event in probe.events)
        return native_clock() + (100 if expired else 0)
    with patch("app.contacts.native.time.monotonic", side_effect=clock):
        with pytest.raises(native.ContactError) as error:
            list(native.candidate_keys(probe, identity(native), b"s" * 16,
                                      cancel=threading.Event(), deadline=until))
    assert error.value.code == "TIMEOUT"
    assert all(not any(buffer) for buffer in probe.returned_buffers)
    assert probe.events[-1] == ("close", 71)
