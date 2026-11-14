"""结果呈现组件（信息呈现规范 V2 §3 / §4，视觉规范 V2 §4.2/§4.4/§4.5/§4.8）。

四个组件
--------
* :class:`ResultCard` —— L1 主结果 + L2 徽章 + L3 参数表 + L4 提示条，四态互斥。
* :class:`KpiCard`    —— 3px 强调条 + 标签 / 等宽数值 + 独立单位。
* :class:`Badge`      —— 状态徽章（`#badge[tone=...]`）。
* :class:`PageHeader` —— 页面标题区（标题 + 副标题 + 右侧操作区）。

**组件内部零 ``setStyleSheet``**：全部靠 ``setObjectName`` + 全局 QSS 上色，
``setProperty`` 用于 tone / kind / state / alt 等变体。

``ResultCard`` 里不出现 ``QTextEdit``（除"查看详情"对话框用只读 ``QPlainTextEdit``）。
本组件不负责格式化数值，入参必须是已过 :mod:`radar_tool.fmt` 的字符串。
"""

from __future__ import annotations

import re

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from .ui_theme import SIZES_PX, SPACING_PX, repolish

# ==========================================================================
# 小工具
# ==========================================================================

_EMOJI_CHARS = set('🔴🟡🟢✅❌💡📐📊📈📉📡🧮📋🔧🎯📶🧭🔊🧹↕🔄⚠✔✖⭐️️')

#: 可以被当作"单位"的尾 token（N4 单位符号表）
UNIT_TOKENS = {
    'dB', 'dBi', 'dBm', 'dBW', 'dBm/Hz', '°', 'rad', 'mrad', '°C', 'K', 'λ',
    'm', 'cm', 'mm', 'km', 'nm', 'GHz', 'MHz', 'kHz', 'Hz', 's', 'ms', 'μs',
    'V', 'mV', 'μV', 'W', 'mW', '%', '″', 'm²', '倍', '倍率',
}

_NOTE_RE = re.compile(r'\s*[\(（]([^\)）]*)[\)）]\s*$')

#: render_legacy 的 L1 候选键（按优先级，命中即提升为主结果）
_PRIMARY_KEYS = (
    '天线增益', '最大探测距离', '链路余量', '理论测向精度', '阵列增益',
    '接收信噪比', '转换结果', '结果值',
)

_TONE_BY_SYMBOL = {
    '🟢': 'success', '✅': 'success',
    '🟡': 'warning',
    '🔴': 'danger', '❌': 'danger',
    '💡': 'info',
}


def strip_emoji(text):
    """去掉 emoji（H8：emoji 不得承载语义），保留 ``→ ± ≤ ≥ × ~ °``。"""
    if not text:
        return ''
    out = []
    for ch in str(text):
        code = ord(ch)
        if ch in _EMOJI_CHARS:
            continue
        if 0x1F000 <= code <= 0x1FAFF:
            continue
        if 0x2600 <= code <= 0x27BF:
            continue
        if 0x2B00 <= code <= 0x2BFF or code == 0xFE0F:
            continue
        out.append(ch)
    return ''.join(out)


def _tone_of(text):
    for symbol, tone in _TONE_BY_SYMBOL.items():
        if symbol in text:
            return tone
    return None


def split_value_unit(text):
    """把 ``'32.4 dBi (3.7×)'`` 拆成 ``('32.4', 'dBi', '3.7×')``（H9 数值/单位分离）。"""
    text = (text or '').strip()
    note = None
    match = _NOTE_RE.search(text)
    if match:
        note = match.group(1).strip()
        text = text[:match.start()].strip()
    if not text:
        return '', None, note
    tokens = text.split()
    if len(tokens) >= 2 and tokens[-1] in UNIT_TOKENS:
        return ' '.join(tokens[:-1]), tokens[-1], note
    # 紧贴单位（N5 例外：% ° °C ″）单独拆出来，保证数值控件只有数字
    for tight in ('°C', '°', '%', '″'):
        if text.endswith(tight) and len(text) > len(tight):
            head = text[:-len(tight)].strip()
            if head and not head.endswith(('e', 'E')):
                return head, tight, note
    return text, None, note


# ==========================================================================
# Badge
# ==========================================================================

class Badge(QLabel):
    """状态徽章：状态词 ≤ 6 汉字，不放动词、不放图标。"""

    def __init__(self, text='', tone='neutral', parent=None):
        super().__init__(text, parent)
        self.setObjectName('badge')
        self.setAlignment(Qt.AlignCenter)
        self.setProperty('tone', tone)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_tone(self, tone='neutral'):
        self.setProperty('tone', tone)
        repolish(self)

    def set_state(self, text, tone='neutral'):
        self.setText(text)
        self.set_tone(tone)
        self.setVisible(bool(text))


# ==========================================================================
# KpiCard
# ==========================================================================

class KpiCard(QFrame):
    """KPI 指标卡（V2 §4.4）：3px 强调条 + 标签 + 等宽数值 + 独立单位。"""

    def __init__(self, label='', unit=None, tone='neutral', hint=None, parent=None):
        super().__init__(parent)
        self.setObjectName('kpiCard')
        self.setMinimumHeight(SIZES_PX['hKpi'])
        self.setFixedHeight(SIZES_PX['hKpi'])

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.accent = QFrame()
        self.accent.setObjectName('kpiAccent')
        self.accent.setFixedWidth(3)
        self.accent.setProperty('tone', tone)
        outer.addWidget(self.accent)

        body = QVBoxLayout()
        body.setContentsMargins(14, 12, 14, 12)
        body.setSpacing(SPACING_PX['sp1'])

        self.label = QLabel(label)
        self.label.setObjectName('kpiLabel')
        body.addWidget(self.label)

        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(SPACING_PX['sp1'])
        self.value = QLabel('--')
        self.value.setObjectName('kpiValue')
        self.value.setProperty('state', 'empty')
        self.unit = QLabel(unit or '')
        self.unit.setObjectName('kpiUnit')
        value_row.addWidget(self.value, 0, Qt.AlignBottom)
        value_row.addWidget(self.unit, 0, Qt.AlignBottom)
        value_row.addStretch(1)
        body.addLayout(value_row)
        body.addStretch(1)

        self.hint = QLabel(hint or '')
        self.hint.setObjectName('kpiHint')
        self.hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.hint.setVisible(bool(hint))
        body.addWidget(self.hint, 0, Qt.AlignRight)

        outer.addLayout(body, 1)
        self._label_text = label
        self._empty_prompt = hint or ''

    # -- API ---------------------------------------------------------------
    def set_value(self, value, unit=None):
        self.value.setText('--' if value is None else str(value))
        self.value.setProperty('state', 'empty' if value is None else 'value')
        if unit is not None:
            self.unit.setText(unit)
        if value is None and self._empty_prompt:
            self.hint.setText(self._empty_prompt)
            self.hint.setVisible(True)
        elif value is not None:
            # 有值时不再占用空态提示位（V2 §4.4：空态提示只属于空态）
            self.hint.setVisible(False)
        repolish(self.value)

    def set_empty(self, prompt=None):
        if prompt:
            self._empty_prompt = prompt
            self.hint.setText(prompt)
            self.hint.setVisible(True)
        self.set_value(None)

    def set_tone(self, tone):
        self.accent.setProperty('tone', tone)
        repolish(self.accent)

    def set_label(self, text):
        self._label_text = text
        self.label.setText(text)

    def value_text(self):
        return self.value.text()


# ==========================================================================
# PageHeader
# ==========================================================================

class PageHeader(QWidget):
    """页面标题区（V2 §4.2）：标题 / 副标题 + 右侧操作区（至多 1 个 primary）。"""

    def __init__(self, title='', subtitle='', parent=None):
        super().__init__(parent)
        self.setObjectName('pageHeader')
        self.setMinimumHeight(SIZES_PX['hPageHeader'])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_PX['sp6'], 0, SPACING_PX['sp6'], 0)
        layout.setSpacing(SPACING_PX['sp4'])

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        self.title = QLabel(title)
        self.title.setObjectName('pageTitle')
        self.subtitle = QLabel(subtitle or '')
        self.subtitle.setObjectName('pageSubtitle')
        self.subtitle.setVisible(bool(subtitle))
        text_col.addStretch(1)
        text_col.addWidget(self.title)
        text_col.addWidget(self.subtitle)
        text_col.addStretch(1)
        layout.addLayout(text_col)
        layout.addStretch(1)

        self._actions = QHBoxLayout()
        self._actions.setContentsMargins(0, 0, 0, 0)
        self._actions.setSpacing(SPACING_PX['sp4'])
        layout.addLayout(self._actions)

    def set_title(self, text):
        self.title.setText(text)

    def set_subtitle(self, text):
        self.subtitle.setText(text or '')
        self.subtitle.setVisible(bool(text))

    def add_action(self, widget):
        self._actions.addWidget(widget)
        return widget

    def actions_layout(self):
        return self._actions


# ==========================================================================
# EmptyState
# ==========================================================================

class EmptyState(QFrame):
    """空态（V2 §4.12）：主文案必须是"下一步动作"。"""

    def __init__(self, title='', hint='', parent=None):
        super().__init__(parent)
        self.setObjectName('emptyState')
        self.setMinimumHeight(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_PX['sp6'], SPACING_PX['sp5'],
                                 SPACING_PX['sp6'], SPACING_PX['sp5'])
        layout.setSpacing(SPACING_PX['sp2'])
        layout.addStretch(1)
        self.title = QLabel(title)
        self.title.setObjectName('emptyTitle')
        self.title.setAlignment(Qt.AlignCenter)
        self.hint = QLabel(hint)
        self.hint.setObjectName('emptyHint')
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setVisible(bool(hint))
        layout.addWidget(self.title)
        layout.addWidget(self.hint)
        layout.addStretch(1)

    def set_text(self, title, hint=''):
        self.title.setText(title)
        self.hint.setText(hint or '')
        self.hint.setVisible(bool(hint))


# ==========================================================================
# ResultCard
# ==========================================================================

class ResultCard(QFrame):
    """结果卡：L1 主结果 / L2 徽章 / L3 参数表 / L4 提示条。

    四态互斥：``set_empty`` / ``set_loading`` / ``set_primary`` / ``set_error``。
    数值格式化不在此完成（先过 :mod:`radar_tool.fmt`）。
    """

    #: 参数表折叠阈值（超过即折叠为「更多参数（+N）」）
    COLLAPSE_OVER = 8

    def __init__(self, parent=None, *, title='计算结果', dense=False):
        super().__init__(parent)
        self.setObjectName('resultCard')
        self.setMinimumWidth(320)
        self._dense = bool(dense)
        self._title_text = title or ''
        self._value_text = ''
        self._unit_text = ''
        self._note_text = ''
        self._status_text = ''
        self._status_tone = 'neutral'
        self._hint_text = ''
        self._hint_kind = 'none'
        self._records = []          # ('group', text) / ('pair', key, val)
        self._collapsed = False
        self._state = 'empty'
        self._empty_prompt = '录入参数后自动计算'

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING_PX['sp6'], 14, SPACING_PX['sp6'], 14)
        outer.setSpacing(0)

        # ---- 结果头 ----
        self._header = QWidget()
        header_row = QHBoxLayout(self._header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(SPACING_PX['sp4'])
        self.title_label = QLabel(self._title_text)
        self.title_label.setObjectName('resultCardTitle')
        self.badge = Badge('', 'neutral')
        self.badge.setVisible(False)
        header_row.addWidget(self.title_label, 0, Qt.AlignVCenter)
        header_row.addStretch(1)
        header_row.addWidget(self.badge, 0, Qt.AlignVCenter)
        outer.addWidget(self._header)

        # ---- L1 主结果行 ----
        self._primary_row = QWidget()
        primary_row = QHBoxLayout(self._primary_row)
        primary_row.setContentsMargins(0, SPACING_PX['sp2'], 0, 0)
        primary_row.setSpacing(SPACING_PX['sp1'])
        self.value_label = QLabel('--')
        self.value_label.setObjectName('resultValue')
        self.value_label.setProperty('state', 'empty')
        self.value_label.setProperty('dense', 'true' if self._dense else 'false')
        self.unit_label = QLabel('')
        self.unit_label.setObjectName('resultUnit')
        self.note_label = QLabel('')
        self.note_label.setObjectName('resultNote')
        self.copy_button = QPushButton('复制')
        self.copy_button.setProperty('variant', 'ghost')
        self.copy_button.setProperty('compact', 'true')
        self.copy_button.setToolTip('复制结果')
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        primary_row.addWidget(self.value_label, 0, Qt.AlignBottom)
        primary_row.addWidget(self.unit_label, 0, Qt.AlignBottom)
        primary_row.addSpacing(SPACING_PX['sp3'])
        primary_row.addWidget(self.note_label, 0, Qt.AlignBottom)
        primary_row.addStretch(1)
        primary_row.addWidget(self.copy_button, 0, Qt.AlignBottom)
        outer.addWidget(self._primary_row)

        # ---- 加载态进度条（默认隐藏） ----
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)

        # ---- L3 参数表 ----
        self._params_wrap = QWidget()
        wrap_layout = QVBoxLayout(self._params_wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.setSpacing(0)
        wrap_layout.addSpacerItem(self._vspacer(SPACING_PX['sp5']))
        self._params_box = QWidget()
        self._params_layout = QVBoxLayout(self._params_box)
        self._params_layout.setContentsMargins(0, 0, 0, 0)
        self._params_layout.setSpacing(0)
        wrap_layout.addWidget(self._params_box)
        self._params_wrap.setVisible(False)
        outer.addWidget(self._params_wrap)

        self.more_button = QPushButton('')
        self.more_button.setProperty('variant', 'ghost')
        self.more_button.setProperty('compact', 'true')
        self.more_button.clicked.connect(self._toggle_collapsed)
        self.more_button.setVisible(False)
        self._more_row = QWidget()
        more_layout = QHBoxLayout(self._more_row)
        more_layout.setContentsMargins(0, 0, 0, 0)
        more_layout.addWidget(self.more_button, 0, Qt.AlignLeft)
        more_layout.addStretch(1)
        self._more_row.setVisible(False)
        outer.addWidget(self._more_row)

        # ---- L4 提示条 ----
        self.hint_bar = QFrame()
        self.hint_bar.setObjectName('hintBar')
        self.hint_bar.setProperty('kind', 'info')
        hint_layout = QHBoxLayout(self.hint_bar)
        hint_layout.setContentsMargins(10, SPACING_PX['sp3'], SPACING_PX['sp4'],
                                       SPACING_PX['sp3'])
        hint_layout.setSpacing(SPACING_PX['sp4'])
        self.hint_label = QLabel('')
        self.hint_label.setObjectName('hintText')
        self.hint_label.setWordWrap(True)
        self.hint_label.setProperty('kind', 'info')
        self.hint_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        hint_layout.addWidget(self.hint_label, 1)
        self.retry_button = QPushButton('重试')
        self.retry_button.setProperty('variant', 'ghost')
        self.retry_button.setProperty('compact', 'true')
        self.retry_button.setVisible(False)
        hint_layout.addWidget(self.retry_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.detail_button = QPushButton('查看详情')
        self.detail_button.setProperty('variant', 'ghost')
        self.detail_button.setProperty('compact', 'true')
        self.detail_button.setVisible(False)
        hint_layout.addWidget(self.detail_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.hint_bar.setVisible(False)
        self._hint_wrap = QWidget()
        hint_wrap_layout = QVBoxLayout(self._hint_wrap)
        hint_wrap_layout.setContentsMargins(0, 0, 0, 0)
        hint_wrap_layout.setSpacing(0)
        hint_wrap_layout.addSpacerItem(self._vspacer(SPACING_PX['sp4']))
        hint_wrap_layout.addWidget(self.hint_bar)
        self._hint_wrap.setVisible(False)
        outer.addWidget(self._hint_wrap)

        self._detail_text = ''
        self.set_empty(self._empty_prompt)

    # -- 内部 ---------------------------------------------------------------
    @staticmethod
    def _vspacer(height):
        from PyQt5.QtWidgets import QSpacerItem, QSizePolicy as _SP

        return QSpacerItem(0, height, _SP.Minimum, _SP.Fixed)

    def _clear_params(self):
        while self._params_layout.count():
            item = self._params_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _make_row(self, key, value, alt=False, muted=False):
        row = QFrame()
        row.setObjectName('paramRow')
        row.setProperty('alt', 'true' if alt else 'false')
        layout = QHBoxLayout(row)
        layout.setContentsMargins(SPACING_PX['sp1'], 0, SPACING_PX['sp2'], 0)
        layout.setSpacing(SPACING_PX['sp4'])
        key_label = QLabel(key)
        key_label.setObjectName('paramKey')
        key_label.setFixedWidth(96)
        key_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label = QLabel(value)
        value_label.setObjectName('paramVal')
        value_label.setProperty('state', 'muted' if muted else 'value')
        value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(key_label, 0)
        layout.addWidget(value_label, 1)
        row.setMinimumHeight(24)
        return row

    def _make_group(self, text):
        label = QLabel(text)
        label.setObjectName('paramGroup')
        label.setContentsMargins(SPACING_PX['sp1'], SPACING_PX['sp3'], 0, SPACING_PX['sp1'])
        return label

    def _rebuild_params(self):
        self._clear_params()
        records = self._records
        pairs = [r for r in records if r[0] == 'pair']
        visible = records
        over = len(pairs) > self.COLLAPSE_OVER
        if over and self._collapsed:
            shown = 0
            visible = []
            for record in records:
                if record[0] == 'group':
                    visible.append(record)
                    continue
                shown += 1
                if shown <= self.COLLAPSE_OVER:
                    visible.append(record)
            hidden = len(pairs) - self.COLLAPSE_OVER
            self.more_button.setText(f'更多参数（+{hidden}）')
            self.more_button.setVisible(True)
            self._more_row.setVisible(True)
        elif over:
            self.more_button.setText('收起')
            self.more_button.setVisible(True)
            self._more_row.setVisible(True)
        else:
            self.more_button.setVisible(False)
            self._more_row.setVisible(False)

        muted = self._state == 'empty'
        alt = False
        for record in visible:
            if record[0] == 'group':
                self._params_layout.addWidget(self._make_group(record[1]))
                alt = False
                continue
            key = record[1]
            value = record[2]
            if key:
                self._params_layout.addWidget(
                    self._make_row(key, value, alt=alt, muted=muted))
            else:
                self._params_layout.addWidget(
                    self._make_row('', value, alt=alt, muted=muted))
            alt = not alt
        self._params_box.setVisible(bool(visible))
        self._params_wrap.setVisible(bool(visible))

    def _toggle_collapsed(self):
        self._collapsed = not self._collapsed
        self._rebuild_params()

    def _set_hint_visible(self, visible):
        self.hint_bar.setVisible(bool(visible))
        self._hint_wrap.setVisible(bool(visible))

    def _set_state(self, state):
        self._state = state
        self.value_label.setProperty('state', state if state != 'result' else 'value')
        repolish(self.value_label)
        if state == 'loading':
            self.progress.setVisible(True)
        else:
            self.progress.setVisible(False)

    # -- 标题 ---------------------------------------------------------------
    def set_title(self, text):
        self._title_text = text or ''
        self.title_label.setText(self._title_text)
        self._header.setVisible(bool(self._title_text) or self.badge.isVisible())

    # -- L1 -----------------------------------------------------------------
    def set_primary(self, value, unit=None, *, note=None, status=None, copyable=True):
        if value is None:
            self.set_empty(self._empty_prompt)
            if status:
                self.set_status(*status)
            return
        self._set_state('result')
        self._value_text = str(value)
        self._unit_text = unit or ''
        self._note_text = note or ''
        self.value_label.setText(self._value_text)
        self.unit_label.setText(self._unit_text)
        self.unit_label.setVisible(bool(self._unit_text))
        self.note_label.setText(self._note_text)
        self.note_label.setVisible(bool(self._note_text))
        self.copy_button.setVisible(bool(copyable))
        self._set_hint_visible(self._hint_kind not in ('none', ''))
        if status:
            self.set_status(*status)
        self._rebuild_params()

    # -- L3 -----------------------------------------------------------------
    def set_params(self, pairs, *, group=None, collapsible_over=None,
                   empty_text=None):
        if collapsible_over is not None:
            self.COLLAPSE_OVER = int(collapsible_over)
        records = []
        if group:
            records.append(('group', str(group)))
        for pair in pairs or []:
            if isinstance(pair, (tuple, list)) and len(pair) >= 2:
                records.append(('pair', str(pair[0]), str(pair[1])))
            elif isinstance(pair, dict):
                records.append(('pair', str(pair.get('key', '')),
                                str(pair.get('value', ''))))
            else:
                records.append(('pair', '', str(pair)))
        if not records and empty_text is not None:
            records = [('pair', '', empty_text)]
        self._records = records
        self._rebuild_params()

    def set_param_records(self, records):
        """内部/迁移用：直接写入 ``('group', t)`` / ``('pair', k, v)`` 记录。"""
        self._records = list(records)
        self._rebuild_params()

    def params_text(self):
        lines = []
        for record in self._records:
            if record[0] == 'group':
                lines.append(record[1])
            elif record[1]:
                lines.append(f'{record[1]}\t{record[2]}')
            else:
                lines.append(record[2])
        return '\n'.join(lines)

    # -- L2 -----------------------------------------------------------------
    def set_status(self, text, tone='neutral'):
        self._status_text = text or ''
        self._status_tone = tone or 'neutral'
        self.badge.set_state(self._status_text, self._status_tone)
        self._header.setVisible(bool(self._title_text) or bool(self._status_text))

    # -- L4 -----------------------------------------------------------------
    def set_hint(self, kind, text):
        kind = kind or 'none'
        self._hint_kind = kind
        self._hint_text = strip_emoji(text or '').strip()
        if kind == 'none' or not self._hint_text:
            self._set_hint_visible(False)
            return
        self.hint_bar.setProperty('kind', kind)
        self.hint_label.setProperty('kind', kind)
        self.hint_label.setText(self._hint_text)
        repolish(self.hint_bar)
        repolish(self.hint_label)
        self._set_hint_visible(True)

    # -- 四态 ---------------------------------------------------------------
    def set_empty(self, prompt, *, hint=None):
        self._empty_prompt = prompt or '录入参数后自动计算'
        self._set_state('empty')
        self._value_text = '--'
        self._unit_text = ''
        self._note_text = ''
        self.value_label.setText('--')
        self.unit_label.setVisible(False)
        self.note_label.setVisible(False)
        self.copy_button.setVisible(False)
        if not self._records:
            self._records = []
        self._rebuild_params()
        text = self._empty_prompt if not hint else f'{self._empty_prompt}；{hint}'
        self.set_hint('neutral', text)
        self.badge.setVisible(False)

    def set_loading(self, text='正在计算…', *, progress=None):
        self._set_state('loading')
        self._value_text = text
        self.value_label.setText(text)
        self.unit_label.setVisible(False)
        self.note_label.setVisible(False)
        self.copy_button.setVisible(False)
        if progress is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(progress))
        self._rebuild_params()

    def set_error(self, reason, *, retry_callable=None, detail=None):
        self._set_state('error')
        self._value_text = '计算失败'
        self.value_label.setText('计算失败')
        self.unit_label.setVisible(False)
        self.note_label.setVisible(False)
        self.copy_button.setVisible(False)
        self.set_status('失败', 'danger')
        self.set_hint('danger', reason)
        self._detail_text = detail or ''
        self.detail_button.setVisible(bool(self._detail_text))
        if self._detail_text:
            try:
                self.detail_button.clicked.disconnect()
            except TypeError:
                pass
            self.detail_button.clicked.connect(self._show_detail)
        self.retry_button.setVisible(retry_callable is not None)
        if retry_callable is not None:
            try:
                self.retry_button.clicked.disconnect()
            except TypeError:
                pass
            self.retry_button.clicked.connect(retry_callable)
        self._rebuild_params()

    def set_partial(self, ok, failed, *, failures=None, retry_callable=None):
        self._set_state('result')
        self._value_text = str(ok)
        self._unit_text = '成功'
        self._note_text = f'{failed} 失败' if failed else ''
        self.value_label.setText(self._value_text)
        self.unit_label.setText(self._unit_text)
        self.unit_label.setVisible(True)
        self.note_label.setText(self._note_text)
        self.note_label.setVisible(bool(self._note_text))
        self.set_status('部分成功', 'warning')
        if failures:
            self.set_params(list(failures), group=f'失败明细（{len(failures)}）')
        self.set_hint(
            'warning',
            f'未成功的 {failed} 项未写入结果，其余 {ok} 项已完成。',
        )
        self.retry_button.setVisible(retry_callable is not None)

    def clear(self):
        self._records = []
        self.set_empty(self._empty_prompt)

    def _show_detail(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('错误详情')
        dialog.resize(560, 320)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(dialog)
        text.setReadOnly(True)
        text.setPlainText(self._detail_text)
        layout.addWidget(text)
        dialog.exec_()

    # -- 复制 ---------------------------------------------------------------
    def to_plain_text(self):
        """纯文本（2 列制表符对齐），供粘贴到 Excel。"""
        lines = []
        if self._title_text:
            lines.append(self._title_text)
        if self._state == 'result':
            primary = ' '.join(
                part for part in (self._value_text, self._unit_text) if part
            )
            if self._note_text:
                primary = f'{primary} ({self._note_text})'
            if primary:
                lines.append(primary)
        elif self._state == 'empty':
            lines.append('--')
        else:
            lines.append(self._value_text)
        if self._status_text:
            lines.append(f'[{self._status_text}]')
        params = self.params_text()
        if params:
            lines.append(params)
        if self._hint_text and self._hint_kind not in ('none', ''):
            lines.append(self._hint_text)
        return '\n'.join(line for line in lines if line != '')

    #: 驼峰别名 —— 测试与外部模块按 Qt 习惯调用 ``toPlainText()``
    def toPlainText(self):
        return self.to_plain_text()

    def to_html(self):
        return self.to_plain_text()

    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.to_plain_text())
        self.copy_button.setToolTip('已复制')

    # ======================================================================
    # 迁移期：解析旧 ``_show_result(lines)`` 协议
    # ======================================================================
    def render_legacy(self, lines):
        """按 §3.4 的判定顺序解析旧协议（阶段 A 迁移用）。

        判定顺序必须与原 ``calc_ui._show_result`` 一致：``##`` → ``**X**: v`` →
        ``**X**`` → 危险标记 → 成功标记 → 警告标记 → ``💡`` → ``:`` → 正文。
        其中 ``**X**: v`` 用 ``line.count('**') >= 2 and '**:' in line`` 判定，
        修掉旧代码 ``endswith('**')`` 永假导致的星号泄漏。
        """
        title = ''
        records = []
        hints = []
        error = None
        tone_for_title = None
        free_lines = []
        primary_key = None

        for raw in lines or []:
            text = strip_emoji('' if raw is None else str(raw)).strip()
            if not text:
                continue
            tone = _tone_of('' if raw is None else str(raw))

            # 1) '##' 卡头 / 分组
            if text.startswith('##'):
                heading = text.lstrip('#').strip()
                if not title:
                    title = heading
                    tone_for_title = tone
                elif tone in ('warning', 'danger', 'success'):
                    hints.append((tone, heading))
                else:
                    records.append(('group', heading))
                continue

            # 2) '**X**: v' → 参数对（P0：星号必须去掉）
            if text.count('**') >= 2 and '**:' in text:
                key, _, value = text.partition('**:')
                records.append(('pair', key.replace('**', '').strip(),
                                value.replace('**', '').strip()))
                continue

            # 3) '**X**' 单独成行 → 分段标题
            if text.count('**') >= 2:
                heading = text.replace('**', '').strip()
                if tone in ('warning', 'danger'):
                    hints.append((tone, heading))
                else:
                    records.append(('group', heading))
                continue

            # 4) 危险标记
            if tone == 'danger':
                if '❌' in str(raw) or title == '':
                    error = error or text
                else:
                    hints.append(('danger', text))
                continue

            # 5) 成功 / 6) 警告 / 7) 提示
            if tone == 'success':
                if '→' in text:
                    left, _, right = text.partition('→')
                    records.append(('pair', left.strip(), right.strip()))
                else:
                    records.append(('pair', '', text))
                continue
            if tone == 'warning':
                hints.append(('warning', text))
                continue
            if tone == 'info':
                hints.append(('info', text))
                continue

            # 8) ':' → 参数对
            if ':' in text:
                key, _, value = text.partition(':')
                key = key.strip()
                value = value.strip()
                if '=' in value and not key:
                    free_lines.append(text)
                    continue
                records.append(('pair', key, value))
                continue

            # 9) 'A B = C D' → L1 主结果 + 输入参数
            parsed = _parse_equality(text)
            if parsed is not None:
                value_text, unit, note, input_text, input_unit = parsed
                primary_key = (value_text, unit, note, input_text, input_unit)
                continue

            free_lines.append(text)

        # ---- L1：优先用等式解析结果，其次按候选键从参数里提升 ----
        primary = None
        if primary_key is not None:
            value_text, unit, note, input_text, input_unit = primary_key
            primary = (value_text, unit, note)
            if input_text:
                records.insert(0, ('pair', '输入值',
                                   f'{input_text} {input_unit}'.strip()))
        else:
            for candidate in _PRIMARY_KEYS:
                for index, record in enumerate(records):
                    if record[0] != 'pair' or not record[1]:
                        continue
                    if candidate in record[1]:
                        value_text, unit, note = split_value_unit(record[2])
                        primary = (value_text, unit, note)
                        records.pop(index)
                        break
                if primary:
                    break

        for text in free_lines:
            records.append(('pair', '', text))

        # ---- 写入：错误态优先级最高（四态互斥） ----
        if title:
            self.set_title(title)
        if error:
            self.set_param_records(records)
            self.set_error(error)
            return
        self._records = records
        if primary:
            self.set_primary(primary[0], primary[1], note=primary[2])
        else:
            # 没有可识别的 L1：主值位留 `--`（不抢焦点），参数表照常显示
            self._state = 'result'
            self._value_text = '--'
            self._unit_text = ''
            self._note_text = ''
            self.value_label.setText('--')
            self.value_label.setProperty('state', 'empty')
            repolish(self.value_label)
            self.unit_label.setVisible(False)
            self.note_label.setVisible(False)
            self.copy_button.setVisible(True)
            self._rebuild_params()
        if tone_for_title:
            parts = title.split()
            candidate = parts[-1] if parts else title
            if len(candidate) > 8:
                candidate = candidate[:8]
            if candidate:
                self.set_status(candidate, tone_for_title)
                if title.endswith(candidate) and title != candidate:
                    self.set_title(title[:-len(candidate)].strip())
        if hints:
            kind = hints[0][0]
            if kind == 'success':
                kind = 'info'
            texts = []
            for hint_kind, hint_text in hints:
                if hint_kind in ('danger', 'warning') and kind == 'info':
                    kind = hint_kind
                cleaned = hint_text.replace('提示：', '').replace('提示:', '').strip()
                if cleaned and cleaned not in texts:
                    texts.append(cleaned)
            self.set_hint(kind, '；'.join(texts))


def _parse_equality(text):
    """``'10 Hz = 0.01 kHz'`` → ``('0.01', 'kHz', None, '10', 'Hz')``。"""
    if text.count('=') != 1:
        return None
    left, _, right = text.partition('=')
    left_tokens = left.split()
    right_tokens = right.split()
    if len(left_tokens) != 2 or len(right_tokens) != 2:
        return None
    value_text, unit, note = split_value_unit(right.strip())
    return value_text, unit, note, left_tokens[0], left_tokens[1]


__all__ = [
    'Badge', 'EmptyState', 'KpiCard', 'PageHeader', 'ResultCard',
    'split_value_unit', 'strip_emoji',
]
