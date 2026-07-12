from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from typing import Any

from PySide6.QtCore import QObject


_SKIPPED_PROVIDER_MEMBERS = {
    "__annotations__",
    "__dict__",
    "__doc__",
    "__init__",
    "__module__",
    "__slots__",
    "__weakref__",
}


@dataclass(frozen=True, slots=True)
class LazyFeatureProvider:
    module_name: str
    class_name: str
    member_names: tuple[str, ...]
    method_arities: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class _LazyFeatureMember:
    provider: LazyFeatureProvider
    name: str
    method_arity: int | None = None


@lru_cache(maxsize=2048)
def _load_lazy_descriptor(module_name: str, class_name: str, name: str) -> object:
    provider = getattr(import_module(module_name), class_name)
    for owner in provider.__mro__:
        if name in owner.__dict__:
            return owner.__dict__[name]
    raise AttributeError(f"{module_name}.{class_name} has no member {name!r}.")


def _member_descriptor(member: object) -> object:
    if isinstance(member, _LazyFeatureMember):
        provider = member.provider
        return _load_lazy_descriptor(provider.module_name, provider.class_name, member.name)
    return member


def _provider_members(providers: Sequence[type | LazyFeatureProvider]) -> dict[str, object]:
    members: dict[str, object] = {}
    missing = object()
    for provider in providers:
        if isinstance(provider, LazyFeatureProvider):
            provider_members = {
                name: _LazyFeatureMember(provider, name)
                if name not in provider.method_arities
                else _LazyFeatureMember(provider, name, provider.method_arities[name])
                for name in provider.member_names
                if name not in _SKIPPED_PROVIDER_MEMBERS
            }
        else:
            provider_members = {}
            for owner in provider.__mro__:
                if owner is object:
                    continue
                for name, descriptor in owner.__dict__.items():
                    if name in _SKIPPED_PROVIDER_MEMBERS or (name.startswith("__") and name.endswith("__")):
                        continue
                    provider_members.setdefault(name, descriptor)
        for name, descriptor in provider_members.items():
            previous = members.get(name, missing)
            if previous is not missing and previous is not descriptor:
                raise TypeError(f"Composed window member {name!r} has multiple providers.")
            members.setdefault(name, descriptor)
    return members


class WindowFeatureController:
    """Bind legacy feature-provider descriptors to one owned shell window."""

    def __init__(self, window: object, providers: Sequence[type | LazyFeatureProvider]) -> None:
        self.window = window
        self._members = _provider_members(tuple(providers))
        self._lazy_methods: dict[str, _LazyBoundFeatureMethod] = {}

    @property
    def members(self) -> Mapping[str, object]:
        return self._members

    def resolve(self, name: str) -> Any:
        descriptor = _member_descriptor(self._members[name])
        getter = getattr(descriptor, "__get__", None)
        if callable(getter):
            return getter(self.window, type(self.window))
        return descriptor

    def lazy_method(self, name: str, arity: int) -> object:
        method = self._lazy_methods.get(name)
        if method is None:
            method = _LazyBoundFeatureMethod(self, name, arity)
            self._lazy_methods[name] = method
        return method.callback

    def assign(self, name: str, value: object) -> None:
        descriptor = _member_descriptor(self._members[name])
        setter = getattr(descriptor, "__set__", None)
        if not callable(setter):
            raise AttributeError(f"Composed window member {name!r} is read-only.")
        setter(self.window, value)

    def delete(self, name: str) -> None:
        descriptor = _member_descriptor(self._members[name])
        deleter = getattr(descriptor, "__delete__", None)
        if not callable(deleter):
            raise AttributeError(f"Composed window member {name!r} cannot be deleted.")
        deleter(self.window)


class _LazyBoundFeatureMethod(QObject):
    def __init__(self, controller: WindowFeatureController, name: str, arity: int) -> None:
        parent = controller.window if isinstance(controller.window, QObject) else None
        super().__init__(parent)
        self._controller = controller
        self._name = name
        self._arity = arity
        self.callback = self._invoke

    def _invoke(self, *args: object, **kwargs: object) -> Any:
        callback = self._controller.resolve(self._name)
        positional = args if self._arity < 0 else args[: self._arity]
        return callback(*positional, **kwargs)


class _ForwardedFeatureMember:
    def __init__(self, controller_attribute: str, name: str, descriptor: object) -> None:
        self._controller_attribute = controller_attribute
        self._name = name
        self._descriptor = descriptor

    def __get__(self, instance: object | None, owner: type | None = None) -> Any:
        if instance is None:
            descriptor = _member_descriptor(self._descriptor)
            getter = getattr(descriptor, "__get__", None)
            if callable(getter):
                return getter(None, owner)
            return descriptor
        controller = object.__getattribute__(instance, self._controller_attribute)
        if isinstance(self._descriptor, _LazyFeatureMember) and self._descriptor.method_arity is not None:
            instance_values = object.__getattribute__(instance, "__dict__")
            if self._name in instance_values:
                return instance_values[self._name]
            return controller.lazy_method(self._name, self._descriptor.method_arity)
        descriptor = _member_descriptor(self._descriptor)
        if not callable(getattr(descriptor, "__set__", None)) and not callable(
            getattr(descriptor, "__delete__", None)
        ):
            instance_values = object.__getattribute__(instance, "__dict__")
            if self._name in instance_values:
                return instance_values[self._name]
        return controller.resolve(self._name)

    def __set__(self, instance: object, value: object) -> None:
        controller = object.__getattribute__(instance, self._controller_attribute)
        descriptor = _member_descriptor(self._descriptor)
        if callable(getattr(descriptor, "__set__", None)):
            controller.assign(self._name, value)
        else:
            object.__getattribute__(instance, "__dict__")[self._name] = value

    def __delete__(self, instance: object) -> None:
        controller = object.__getattribute__(instance, self._controller_attribute)
        descriptor = _member_descriptor(self._descriptor)
        if callable(getattr(descriptor, "__delete__", None)):
            controller.delete(self._name)
        else:
            try:
                del object.__getattribute__(instance, "__dict__")[self._name]
            except KeyError as exc:
                raise AttributeError(self._name) from exc


def install_window_feature_controller(
    window_type: type,
    *,
    controller_attribute: str,
    providers: Sequence[type | LazyFeatureProvider],
    bridged_members: Sequence[str] = (),
) -> None:
    """Install stable compatibility descriptors backed by an owned controller."""

    members = _provider_members(tuple(providers))
    bridges = frozenset(bridged_members)
    unknown_bridges = bridges.difference(members)
    if unknown_bridges:
        names = ", ".join(sorted(unknown_bridges))
        raise TypeError(f"Main window bridge(s) have no composed provider: {names}.")
    installed: dict[str, str] = dict(getattr(window_type, "__cdmw_composed_members__", {}))
    for name, descriptor in members.items():
        previous_controller = installed.get(name)
        if previous_controller is not None:
            raise TypeError(
                f"Main window member {name!r} is already owned by {previous_controller!r}."
            )
        if name in bridges:
            if name not in window_type.__dict__:
                raise TypeError(f"Main window bridge {name!r} is not defined on the class.")
        elif name in window_type.__dict__:
            raise TypeError(f"Main window already defines composed member {name!r}.")
        else:
            setattr(window_type, name, _ForwardedFeatureMember(controller_attribute, name, descriptor))
        installed[name] = controller_attribute
    window_type.__cdmw_composed_members__ = installed


__all__ = ["LazyFeatureProvider", "WindowFeatureController", "install_window_feature_controller"]
