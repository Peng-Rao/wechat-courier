from __future__ import annotations

import uuid

import pytest
from PySide6.QtNetwork import QLocalSocket


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def hello(self):
        self.calls.append(("agent.hello", None))
        return {"protocolVersion": 1, "agentVersion": "0.3.0", "pid": 123}

    def inspect(self):
        self.calls.append(("wechat.inspect", None))
        return {"supported": True, "version": "4.1.13.65"}

    def start_task(self, params):
        self.calls.append(("task.start", params))
        return {"accepted": True, "taskId": params["taskId"]}

    def pause_task(self):
        self.calls.append(("task.pause", None))
        return {"accepted": True}

    def resume_task(self):
        self.calls.append(("task.resume", None))
        return {"accepted": True}

    def stop_task(self):
        self.calls.append(("task.stop", None))
        return {"accepted": True}

    def approve_recovery(self, params):
        self.calls.append(("recovery.approve", params))
        return {"accepted": bool(params["approved"])}

    def shutdown(self):
        self.calls.append(("agent.shutdown", None))
        return {"accepted": True}


def test_json_line_decoder_handles_fragmented_and_multiple_frames():
    from app.agent.rpc import JsonLineDecoder, encode_frame

    decoder = JsonLineDecoder()
    first = encode_frame({"jsonrpc": "2.0", "id": 1, "method": "agent.hello"})
    second = encode_frame({"jsonrpc": "2.0", "method": "heartbeat"})

    assert decoder.feed(first[:7]) == []
    assert decoder.feed(first[7:] + second) == [
        {"jsonrpc": "2.0", "id": 1, "method": "agent.hello"},
        {"jsonrpc": "2.0", "method": "heartbeat"},
    ]


def test_json_line_decoder_rejects_oversized_frame():
    from app.agent.rpc import FrameTooLarge, JsonLineDecoder

    decoder = JsonLineDecoder(max_frame_size=8)

    with pytest.raises(FrameTooLarge):
        decoder.feed(b'{"too":"large"}')


def test_rpc_router_requires_successful_hello_before_other_methods():
    from app.agent.rpc import AgentRpcRouter

    runtime = FakeRuntime()
    router = AgentRpcRouter("secret", runtime)

    denied = router.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "wechat.inspect", "params": {}}
    )
    wrong = router.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "agent.hello",
            "params": {"token": "wrong"},
        }
    )
    accepted = router.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "agent.hello",
            "params": {"token": "secret"},
        }
    )

    assert denied["error"]["code"] == -32001
    assert wrong["error"]["code"] == -32001
    assert accepted["result"]["protocolVersion"] == 1
    assert router.authenticated is True


def test_rpc_router_dispatches_the_fixed_method_surface():
    from app.agent.rpc import AgentRpcRouter

    runtime = FakeRuntime()
    router = AgentRpcRouter("secret", runtime)
    router.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "agent.hello",
            "params": {"token": "secret"},
        }
    )

    response = router.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "task.start",
            "params": {"taskId": "task-1", "kind": "message_send", "items": []},
        }
    )
    unknown = router.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "debug.exec", "params": {}}
    )

    assert response["result"] == {"accepted": True, "taskId": "task-1"}
    assert runtime.calls[-1][0] == "task.start"
    assert unknown["error"]["code"] == -32601


def test_local_server_round_trip_requires_authentication(qapp, qtbot):
    from app.agent.rpc import JsonLineDecoder, encode_frame
    from app.agent.server import AgentServer

    name = "wechat-courier-test-" + uuid.uuid4().hex
    server = AgentServer(name, "secret", FakeRuntime(), heartbeat_interval_ms=60_000)
    assert server.listen() is True

    socket = QLocalSocket()
    socket.connectToServer(name)
    assert socket.waitForConnected(2_000)
    socket.write(
        encode_frame(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "agent.hello",
                "params": {"token": "secret"},
            }
        )
    )
    socket.flush()

    qtbot.waitUntil(lambda: socket.bytesAvailable() > 0, timeout=2_000)
    replies = JsonLineDecoder().feed(bytes(socket.readAll()))

    assert replies[0]["id"] == 7
    assert replies[0]["result"]["agentVersion"] == "0.3.0"

    socket.disconnectFromServer()
    server.close()


def _authenticate_socket(name, qtbot):
    from app.agent.rpc import JsonLineDecoder, encode_frame

    socket = QLocalSocket()
    socket.connectToServer(name)
    assert socket.waitForConnected(2_000)
    socket.write(
        encode_frame(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "agent.hello",
                "params": {"token": "secret"},
            }
        )
    )
    socket.flush()
    qtbot.waitUntil(lambda: socket.bytesAvailable() > 0, timeout=2_000)
    assert JsonLineDecoder().feed(bytes(socket.readAll()))[0]["id"] == 1
    return socket


def test_authenticated_disconnect_allows_a_short_reconnect(qapp, qtbot):
    from app.agent.server import AgentServer

    runtime = FakeRuntime()
    name = "wechat-courier-grace-reconnect-" + uuid.uuid4().hex
    server = AgentServer(
        name,
        "secret",
        runtime,
        heartbeat_interval_ms=60_000,
        disconnect_grace_ms=250,
    )
    assert server.listen()
    first = _authenticate_socket(name, qtbot)
    first.abort()
    qtbot.wait(75)

    second = _authenticate_socket(name, qtbot)
    qtbot.wait(300)

    assert ("agent.shutdown", None) not in runtime.calls
    second.abort()
    server.close()


def test_authenticated_disconnect_expires_into_safe_agent_shutdown(qapp, qtbot):
    from app.agent.server import AgentServer

    runtime = FakeRuntime()
    name = "wechat-courier-grace-expiry-" + uuid.uuid4().hex
    server = AgentServer(
        name,
        "secret",
        runtime,
        heartbeat_interval_ms=60_000,
        disconnect_grace_ms=100,
    )
    assert server.listen()
    socket = _authenticate_socket(name, qtbot)

    socket.abort()
    qtbot.waitUntil(
        lambda: ("agent.shutdown", None) in runtime.calls,
        timeout=1_000,
    )

    server.close()
