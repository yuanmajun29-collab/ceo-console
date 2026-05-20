#!/usr/bin/env python3
from __future__ import annotations

import sys
import types
from importlib import import_module

_impl = import_module("src.app")


class _CompatModule(types.ModuleType):
    def __getattr__(self, name: str):
        return getattr(_impl, name)

    def __setattr__(self, name: str, value):
        for module in getattr(_impl, "_PROXY_MODULES", []):
            if hasattr(module, name):
                setattr(module, name, value)
        if hasattr(_impl, name):
            setattr(_impl, name, value)
        super().__setattr__(name, value)


def main() -> None:
    _impl.main()


_current = sys.modules[__name__]
_current.__class__ = _CompatModule
for _name in _impl.__all__:
    setattr(_current, _name, getattr(_impl, _name))


if __name__ == "__main__":
    main()
