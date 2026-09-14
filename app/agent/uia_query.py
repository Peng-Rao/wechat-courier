from __future__ import annotations

from functools import reduce
from typing import Any, Sequence

from .waiters import check_action_deadline
from .retry import AutomationRetryError


TREE_SCOPE_DESCENDANTS = 0x4


class ScopedQueryUnavailable(RuntimeError):
    pass


class ScopedUiaQuery:
    """Server-side UIA descendant queries scoped to one verified container."""

    def __init__(self, uia_module: Any):
        self._uia = uia_module
        self._request_count = 0

    @property
    def request_count(self) -> int:
        return self._request_count

    def find_all(
        self,
        root: Any,
        *,
        name: str | Sequence[str] | None = None,
        control_type: str | None = None,
        control_types: Sequence[str] | None = None,
        class_name: str | None = None,
        automation_id: str | None = None,
        enabled: bool = True,
        visible: bool | None = None,
    ) -> list[Any]:
        check_action_deadline()
        self._request_count += 1
        try:
            client = self._uia._AutomationClient.instance()
            automation = client.IUIAutomation
            element = root.Element
        except Exception as exc:
            raise ScopedQueryUnavailable(str(exc)) from exc

        conditions = []
        if name is not None:
            names = (name,) if isinstance(name, str) else tuple(name)
            conditions.append(
                self._or_conditions(
                    automation,
                    [
                        automation.CreatePropertyCondition(
                            self._uia.PropertyId.NameProperty, str(value)
                        )
                        for value in names
                    ],
                )
            )
        type_names = (
            (control_type,)
            if control_type is not None
            else tuple(control_types or ())
        )
        if type_names:
            conditions.append(
                self._or_conditions(
                    automation,
                    [
                        automation.CreatePropertyCondition(
                            self._uia.PropertyId.ControlTypeProperty,
                            getattr(self._uia.ControlType, value),
                        )
                        for value in type_names
                    ],
                )
            )
        if class_name is not None:
            conditions.append(
                automation.CreatePropertyCondition(
                    self._uia.PropertyId.ClassNameProperty, class_name
                )
            )
        if automation_id is not None:
            conditions.append(
                automation.CreatePropertyCondition(
                    self._uia.PropertyId.AutomationIdProperty, automation_id
                )
            )
        if enabled:
            conditions.append(
                automation.CreatePropertyCondition(
                    self._uia.PropertyId.IsEnabledProperty, True
                )
            )
        if visible is not None:
            conditions.append(
                automation.CreatePropertyCondition(
                    self._uia.PropertyId.IsOffscreenProperty, not visible
                )
            )

        try:
            if conditions:
                condition = reduce(automation.CreateAndCondition, conditions)
            else:
                condition = automation.CreateTrueCondition()
            elements = self._find_all(element, automation, condition)
            check_action_deadline()
            length = int(elements.Length)
            controls = []
            for index in range(length):
                control = self._uia.Control.CreateControlFromElement(
                    elements.GetElement(index)
                )
                if control is not None:
                    controls.append(control)
            return controls
        except (ScopedQueryUnavailable, AutomationRetryError):
            raise
        except Exception as exc:
            raise ScopedQueryUnavailable(str(exc)) from exc

    def _find_all(self, element, automation, condition):
        build_cache = getattr(element, "FindAllBuildCache", None)
        create_cache = getattr(automation, "CreateCacheRequest", None)
        if callable(build_cache) and callable(create_cache):
            try:
                cache = create_cache()
                for property_id in (
                    self._uia.PropertyId.NameProperty,
                    self._uia.PropertyId.ControlTypeProperty,
                    self._uia.PropertyId.ClassNameProperty,
                    self._uia.PropertyId.AutomationIdProperty,
                    self._uia.PropertyId.IsEnabledProperty,
                    self._uia.PropertyId.IsOffscreenProperty,
                ):
                    cache.AddProperty(property_id)
                return build_cache(TREE_SCOPE_DESCENDANTS, condition, cache)
            except AutomationRetryError:
                raise
            except Exception:
                pass
        return element.FindAll(TREE_SCOPE_DESCENDANTS, condition)

    @staticmethod
    def _or_conditions(automation, conditions):
        if not conditions:
            return automation.CreateFalseCondition()
        return reduce(automation.CreateOrCondition, conditions)


__all__ = [
    "ScopedQueryUnavailable",
    "ScopedUiaQuery",
    "TREE_SCOPE_DESCENDANTS",
]
