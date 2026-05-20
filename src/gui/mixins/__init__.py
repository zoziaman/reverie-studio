# src/gui/mixins/__init__.py
"""
Lightweight exports for GUI mixins.

Avoid importing every mixin eagerly at package import time. Some mixins pull in
heavy GUI/runtime dependencies, which can block unrelated imports and test
collection for simple helpers such as `server_mixin` and `settings_mixin`.
"""

from importlib import import_module

__all__ = [
    "ServerMixin",
    "SDModelMixin",
    "AuthMixin",
    "ChannelMixin",
    "ProductionMixin",
    "SettingsMixin",
]

_MIXIN_MODULES = {
    "ServerMixin": "gui.mixins.server_mixin",
    "SDModelMixin": "gui.mixins.sd_model_mixin",
    "AuthMixin": "gui.mixins.auth_mixin",
    "ChannelMixin": "gui.mixins.channel_mixin",
    "ProductionMixin": "gui.mixins.production_mixin",
    "SettingsMixin": "gui.mixins.settings_mixin",
}


def __getattr__(name):
    module_name = _MIXIN_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
