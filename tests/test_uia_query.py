from __future__ import annotations

from types import SimpleNamespace

from app.agent.uia_query import ScopedUiaQuery


class FakeArray:
    def __init__(self, values):
        self._values = list(values)
        self.Length = len(self._values)

    def GetElement(self, index):
        return self._values[index]


def test_scoped_query_builds_server_side_conditions_and_wraps_results():
    calls = []

    class Automation:
        @staticmethod
        def CreatePropertyCondition(property_id, value):
            return ("property", property_id, value)

        @staticmethod
        def CreateAndCondition(left, right):
            return ("and", left, right)

        @staticmethod
        def CreateOrCondition(left, right):
            return ("or", left, right)

    class Element:
        @staticmethod
        def FindAll(scope, condition):
            calls.append((scope, condition))
            return FakeArray(["first", "second"])

    class Control:
        @staticmethod
        def CreateControlFromElement(element):
            return "wrapped:" + element

    uia = SimpleNamespace(
        _AutomationClient=SimpleNamespace(
            instance=lambda: SimpleNamespace(IUIAutomation=Automation())
        ),
        PropertyId=SimpleNamespace(
            NameProperty=1,
            ControlTypeProperty=2,
            ClassNameProperty=3,
            AutomationIdProperty=4,
            IsEnabledProperty=5,
            IsOffscreenProperty=6,
        ),
        ControlType=SimpleNamespace(EditControl=50004),
        Control=Control,
    )
    root = SimpleNamespace(Element=Element())

    query = ScopedUiaQuery(uia)
    controls = query.find_all(
        root,
        name=("搜索", "查找"),
        control_type="EditControl",
        class_name="mmui::XLineEdit",
        enabled=True,
        visible=True,
    )

    assert controls == ["wrapped:first", "wrapped:second"]
    assert len(calls) == 1
    assert calls[0][0] == 4
    assert "查找" in repr(calls[0][1])
    assert 50004 in _flatten(calls[0][1])
    assert query.request_count == 1


def _flatten(value):
    if isinstance(value, tuple):
        result = []
        for part in value:
            result.extend(_flatten(part))
        return result
    return [value]
