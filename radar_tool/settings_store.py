"""QSettings 薄封装 —— 全局配置持久化（G-10）。

组织名 PortableRadarToolbox / 应用名 RadarTool，保证打包与源码运行读到同一套键。
用法::

    from .settings_store import settings
    settings.get('limits/max_file_mb', 512)
    settings.set('ui/show_game_tab', False)
    settings.sync()
"""

from PyQt5.QtCore import QSettings

_ORG = 'PortableRadarToolbox'
_APP = 'RadarTool'


class SettingsStore:
    """对 QSettings 的极简包装，提供 get / set / sync 三个方法。"""

    def __init__(self):
        self._qs = QSettings(_ORG, _APP)

    def get(self, key, default=None):
        val = self._qs.value(key, default)
        # QSettings 对缺失键可能返回 None 或空串，统一回落 default
        if val is None:
            return default
        return val

    def get_bool(self, key, default=False):
        val = self._qs.value(key, None)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        return str(val).lower() in ('true', '1', 'yes')

    def get_int(self, key, default=0):
        val = self._qs.value(key, None)
        if val is None:
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def get_float(self, key, default=0.0):
        val = self._qs.value(key, None)
        if val is None:
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def set(self, key, value):
        self._qs.setValue(key, value)

    def sync(self):
        self._qs.sync()


# 模块级单例，随处可 import 使用
settings = SettingsStore()
