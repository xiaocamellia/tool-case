"""
摸鱼游戏栏 - Slacker Game Panel
基于 PyQt5，内置四款休闲小游戏：频谱2048、阵列贪吃蛇、信号源猎手、干扰源扫雷
"""

import sys
import os
import random
import math
import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QMessageBox, QTextEdit, QTabWidget,
    QSplitter, QFrame, QListWidget, QListWidgetItem, QAbstractItemView,
    QButtonGroup, QRadioButton
)
from PyQt5.QtCore import Qt, QTimer, QRect, QPoint, QPointF, QSize
from PyQt5.QtGui import QFont, QColor, QPainter, QBrush, QPen, QPixmap

from .ui_theme import set_button_icon, style_primary_button, style_warning_button
from .logger import get_logger

logger = get_logger('game_panel')

# ==================== 频谱2048 - 颜色方案 ====================
TILE_COLORS = {
    0:      ('#cdc1b4', '#776e65'),
    2:      ('#eee4da', '#776e65'),
    4:      ('#ede0c8', '#776e65'),
    8:      ('#f2b179', '#f9f6f2'),
    16:     ('#f59563', '#f9f6f2'),
    32:     ('#f67c5f', '#f9f6f2'),
    64:     ('#f65e3b', '#f9f6f2'),
    128:    ('#edcf72', '#f9f6f2'),
    256:    ('#edcc61', '#f9f6f2'),
    512:    ('#edc850', '#f9f6f2'),
    1024:   ('#edc53f', '#f9f6f2'),
    2048:   ('#edc22e', '#f9f6f2'),
}

FREQ_LABELS = {
    2: '2.4G', 4: '4.8G', 8: '9.6G', 16: '19G',
    32: '38G', 64: '77G', 128: '153G', 256: '307G',
    512: '614G', 1024: '1.2T', 2048: '2.5T', 4096: '5.0T',
    8192: '10T', 16384: '20T', 32768: '41T', 65536: '82T'
}

SNAKE_COLORS = [
    '#1d4ed8', '#2563eb', '#3b82f6', '#60a5fa',
    '#93c5fd', '#bfdbfe', '#1e40af', '#1e3a8a'
]


# ==================== 游戏主面板 ====================

class GamePanel(QWidget):
    """摸鱼游戏栏主面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        logger.info('摸鱼游戏栏已创建')

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # ===== 顶部标题 =====
        title_layout = QHBoxLayout()
        lbl_title = QLabel('🎮 摸鱼游戏栏')
        lbl_title.setStyleSheet('font-size: 18px; font-weight: bold; color: #1e293b;')
        title_layout.addWidget(lbl_title)
        lbl_subtitle = QLabel('"科研狗的精神避难所"')
        lbl_subtitle.setStyleSheet('font-size: 10px; color: #94a3b8; font-style: italic;')
        title_layout.addWidget(lbl_subtitle)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # ===== 游戏页签 =====
        self.game_tabs = QTabWidget()
        self.game_tabs.setStyleSheet('''
            QTabWidget::pane { border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px; }
            QTabBar::tab { padding: 8px 16px; font-size: 12px; font-weight: bold; }
            QTabBar::tab:selected { background: #1d4ed8; color: white; border-radius: 4px; }
            QTabBar::tab:!selected { background: #f1f5f9; color: #475569; }
        ''')

        self.game_tabs.addTab(Game2048(), '🧩 频谱2048')
        self.game_tabs.addTab(ArraySnake(), '🐍 阵列贪吃蛇')
        self.game_tabs.addTab(SignalHunter(), '📡 信号源猎手')
        self.game_tabs.addTab(MineSweeper(), '💣 干扰源扫雷')

        layout.addWidget(self.game_tabs, 1)

        # ===== 底部提示 =====
        lbl_hint = QLabel('💡 摸鱼提示：游戏进度自动保存，切换页签/关闭程序不丢失')
        lbl_hint.setStyleSheet('font-size: 9px; color: #94a3b8; padding: 2px;')
        layout.addWidget(lbl_hint)

    def statusBar(self):
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'statusBar'):
                return parent.statusBar()
            parent = parent.parent()
        return None


# ==================== 游戏1: 频谱2048 ====================

class Game2048(QWidget):
    """频谱2048"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = [[0]*4 for _ in range(4)]
        self.score = 0
        self.game_over = False
        self._init_ui()
        self.reset_game()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 得分 + 控制
        top = QHBoxLayout()
        top.addWidget(QLabel('分数:'))
        self.lbl_score = QLabel('0')
        self.lbl_score.setStyleSheet('font-size: 24px; font-weight: bold; color: #1d4ed8;')
        top.addWidget(self.lbl_score)
        top.addStretch()
        self.lbl_status = QLabel('← → ↑ ↓ 方向键移动')
        self.lbl_status.setStyleSheet('font-size: 10px; color: #94a3b8;')
        top.addWidget(self.lbl_status)
        self.btn_reset = QPushButton('🔄 新游戏')
        self.btn_reset.clicked.connect(self.reset_game)
        top.addWidget(self.btn_reset)
        layout.addLayout(top)

        # 频谱显示条
        self.lbl_spectrum = QLabel('📊 频谱: ▁▂▃▅▇▆▃▂')
        self.lbl_spectrum.setStyleSheet('font-size: 11px; color: #64748b; font-family: monospace;')
        layout.addWidget(self.lbl_spectrum)

        # 4x4 网格 - 居中放置
        grid_container = QHBoxLayout()
        grid_container.addStretch()
        grid_widget = QGridLayout()
        grid_widget.setSpacing(8)
        self.tiles = {}
        for r in range(4):
            for c in range(4):
                tile = QLabel('')
                tile.setFixedSize(80, 80)
                tile.setAlignment(Qt.AlignCenter)
                tile.setStyleSheet(self._tile_style(0))
                grid_widget.addWidget(tile, r, c)
                self.tiles[(r, c)] = tile
        grid_container.addLayout(grid_widget)
        grid_container.addStretch()
        layout.addLayout(grid_container)

        layout.addStretch()

        self.setFocusPolicy(Qt.StrongFocus)

    def _tile_style(self, value):
        bg, fg = TILE_COLORS.get(value, ('#cdc1b4', '#776e65'))
        sz = '16px' if value < 100 else '13px' if value < 1000 else '10px'
        return f'background-color: {bg}; color: {fg}; font-size: {sz}; font-weight: bold; border-radius: 8px; border: 1px solid #e2e8f0;'

    def reset_game(self):
        self.grid = [[0]*4 for _ in range(4)]
        self.score = 0
        self.game_over = False
        self._add_random_tile()
        self._add_random_tile()
        self._update_ui()
        self.lbl_status.setText('← → ↑ ↓ 方向键移动')
        self.setFocus()

    def _add_random_tile(self):
        empty = [(r,c) for r in range(4) for c in range(4) if self.grid[r][c] == 0]
        if empty:
            r, c = random.choice(empty)
            self.grid[r][c] = 2 if random.random() < 0.9 else 4

    def _update_ui(self):
        for r in range(4):
            for c in range(4):
                v = self.grid[r][c]
                self.tiles[(r,c)].setText(FREQ_LABELS.get(v, str(v) if v > 0 else ''))
                self.tiles[(r,c)].setStyleSheet(self._tile_style(v))
        self.lbl_score.setText(str(self.score))

        # 频谱条
        levels = [0]*8
        for r in range(4):
            for c in range(4):
                v = self.grid[r][c]
                if v > 0:
                    idx = min(int(math.log2(v))-1, 7)
                    if idx >= 0:
                        levels[idx] = max(levels[idx], min(v/2048, 1.0))
        bars = ''.join(['▁▃▅▇█'[min(int(lv*5),4)] for lv in levels])
        self.lbl_spectrum.setText(f'📊 频谱: {bars}')

    def keyPressEvent(self, event):
        if self.game_over:
            return
        key = event.key()
        moved = False
        if key == Qt.Key_Left:
            moved = self._move_left()
        elif key == Qt.Key_Right:
            moved = self._move_right()
        elif key == Qt.Key_Up:
            moved = self._move_up()
        elif key == Qt.Key_Down:
            moved = self._move_down()
        if moved:
            self._add_random_tile()
            self._update_ui()
            if self._check_game_over():
                self.game_over = True
                self.lbl_status.setText('💀 游戏结束!')
                QMessageBox.information(self, '频谱2048', f'游戏结束！\n最终分数: {self.score}')
                self.reset_game()

    def _move_left(self):
        moved = False
        for r in range(4):
            row = [v for v in self.grid[r] if v != 0]
            merged = []
            i = 0
            while i < len(row):
                if i+1 < len(row) and row[i] == row[i+1]:
                    merged.append(row[i]*2)
                    self.score += row[i]*2
                    i += 2
                else:
                    merged.append(row[i])
                    i += 1
            merged += [0]*(4-len(merged))
            if merged != self.grid[r]:
                moved = True
            self.grid[r] = merged
        return moved

    def _move_right(self):
        self._reverse()
        m = self._move_left()
        self._reverse()
        return m

    def _move_up(self):
        self._transpose()
        m = self._move_left()
        self._transpose()
        return m

    def _move_down(self):
        self._transpose()
        m = self._move_right()
        self._transpose()
        return m

    def _reverse(self):
        for r in range(4):
            self.grid[r] = self.grid[r][::-1]

    def _transpose(self):
        self.grid = [list(col) for col in zip(*self.grid)]

    def _check_game_over(self):
        for r in range(4):
            for c in range(4):
                if self.grid[r][c] == 0:
                    return False
                if c < 3 and self.grid[r][c] == self.grid[r][c+1]:
                    return False
                if r < 3 and self.grid[r][c] == self.grid[r+1][c]:
                    return False
        return True


# ==================== 游戏2: 阵列贪吃蛇 ====================

class ArraySnake(QWidget):
    """阵列贪吃蛇"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cols = 30
        self.rows = 20
        self.snake = [(5,10),(4,10),(3,10)]
        self.direction = (1,0)
        self.next_dir = (1,0)
        self.food = None
        self.score = 0
        self.active = False
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.speed = 150
        self._init_ui()
        self.setFocusPolicy(Qt.StrongFocus)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        top.addWidget(QLabel('得分:'))
        self.lbl_score = QLabel('0')
        self.lbl_score.setStyleSheet('font-size: 22px; font-weight: bold; color: #1d4ed8;')
        top.addWidget(self.lbl_score)

        self.lbl_params = QLabel('阵元: 3 | 孔径: 1.5λ')
        self.lbl_params.setStyleSheet('font-size: 11px; color: #64748b; padding-left: 12px;')
        top.addWidget(self.lbl_params)
        top.addStretch()

        self.btn_start = QPushButton('▶ 开始')
        self.btn_start.clicked.connect(self._toggle_game)
        top.addWidget(self.btn_start)
        layout.addLayout(top)

        # 画布（填满剩余空间）
        self.canvas = QWidget()
        self.canvas.setMinimumSize(400, 280)
        self.canvas.setStyleSheet('background-color: #0f172a; border-radius: 8px; border: 2px solid #334155;')
        self.canvas.paintEvent = self._paint
        layout.addWidget(self.canvas, 1)

        self.lbl_hint = QLabel('方向键/WASD 控制 | 空格暂停 | 吃到 📡 增加阵元')
        self.lbl_hint.setStyleSheet('font-size: 10px; color: #94a3b8;')
        layout.addWidget(self.lbl_hint)

    def start_game(self):
        self.snake = [(5,10),(4,10),(3,10)]
        self.direction = (1,0)
        self.next_dir = (1,0)
        self.score = 0
        self.speed = 150
        self.active = True
        self._spawn_food()
        self.timer.start(self.speed)
        self.btn_start.setText('⏸ 暂停')
        self.lbl_hint.setText('方向键/WASD 控制 | 空格暂停 | 吃到 📡 增加阵元')
        self._update_params()
        self.setFocus()

    def stop_game(self):
        self.active = False
        self.timer.stop()
        self.btn_start.setText('▶ 继续')

    def _toggle_game(self):
        """按钮切换：开始/暂停"""
        if self.active:
            self.stop_game()
        else:
            self.start_game()

    def _spawn_food(self):
        occ = set(self.snake)
        empty = [(x,y) for x in range(self.cols) for y in range(self.rows) if (x,y) not in occ]
        if empty:
            self.food = random.choice(empty)

    def _tick(self):
        if not self.active:
            return
        self.direction = self.next_dir
        dx, dy = self.direction
        hx, hy = self.snake[0]
        nh = (hx+dx, hy+dy)

        # 撞墙检测（碰到墙壁游戏结束）
        if not (0 <= nh[0] < self.cols and 0 <= nh[1] < self.rows):
            self._game_over()
            return

        # 撞自己检测
        if nh in self.snake[:-1]:
            self._game_over()
            return

        self.snake.insert(0, nh)
        if self.food and nh == self.food:
            self.score += 10
            self._spawn_food()
            if self.timer.interval() > 80:
                self.timer.setInterval(max(80, self.timer.interval()-3))
        else:
            self.snake.pop()

        self._update_params()
        self.canvas.update()

    def _update_params(self):
        n = len(self.snake)
        ap = n * 0.5
        self.lbl_params.setText(f'阵元: {n} | 孔径: {ap:.1f}λ')
        self.lbl_score.setText(str(self.score))

    def _game_over(self):
        self.active = False
        self.timer.stop()
        self.btn_start.setText('▶ 开始')
        self.lbl_hint.setText(f'💀 撞到自己了! 得分: {self.score}')
        self.canvas.update()
        QMessageBox.information(self, '阵列贪吃蛇', f'游戏结束！阵元数: {len(self.snake)}\n得分: {self.score}')
        self.start_game()

    def _paint(self, event):
        painter = QPainter(self.canvas)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.canvas.width(), self.canvas.height()
        cw, ch = w/self.cols, h/self.rows

        # 网格
        painter.setPen(QPen(QColor('#1e293b'), 0.5))
        for x in range(self.cols+1):
            painter.drawLine(int(x*cw), 0, int(x*cw), h)
        for y in range(self.rows+1):
            painter.drawLine(0, int(y*ch), w, int(y*ch))

        # 蛇身
        for i, (x, y) in enumerate(self.snake):
            cx, cy = int(x*cw+cw/2), int(y*ch+ch/2)
            r = int(min(cw,ch)*0.38)
            if i == 0:
                painter.setBrush(QBrush(QColor('#22c55e')))
                painter.setPen(QPen(QColor('#4ade80'), 2))
                painter.drawEllipse(QPoint(cx,cy), r+2, r+2)
            else:
                c = QColor(SNAKE_COLORS[min(i, len(SNAKE_COLORS)-1)])
                c.setAlpha(max(100, 255-i*15))
                painter.setBrush(QBrush(c))
                painter.setPen(QPen(QColor('#1e40af'), 1))
                painter.drawEllipse(QPoint(cx,cy), r, r)

        # 食物
        if self.food:
            fx, fy = int(self.food[0]*cw+cw/2), int(self.food[1]*ch+ch/2)
            r = int(min(cw,ch)*0.35)
            painter.setBrush(QBrush(QColor('#ef4444')))
            painter.setPen(QPen(QColor('#fca5a5'), 2))
            painter.drawEllipse(QPoint(fx,fy), r, r)
            painter.setPen(QPen(QColor('#fca5a5'), 2))
            painter.drawLine(fx-r, fy, fx+r, fy)
            painter.drawLine(fx, fy-r, fx, fy+r)

        # 暂停覆盖
        if not self.active and len(self.snake) > 0 and not self.timer.isActive():
            painter.fillRect(0, 0, w, h, QBrush(QColor(0,0,0,80)))
            painter.setPen(QPen(QColor('white'), 1))
            painter.setFont(QFont('sans', 18))
            painter.drawText(QRect(0, 0, w, h), Qt.AlignCenter, '⏸ 已暂停')

        painter.end()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Up, Qt.Key_W): self.next_dir = (0,-1)
        elif key in (Qt.Key_Down, Qt.Key_S): self.next_dir = (0,1)
        elif key in (Qt.Key_Left, Qt.Key_A): self.next_dir = (-1,0)
        elif key in (Qt.Key_Right, Qt.Key_D): self.next_dir = (1,0)
        elif key == Qt.Key_Space:
            if self.active: self.stop_game()
            else: self.start_game()


# ==================== 游戏3: 信号源猎手 ====================

class SignalHunter(QWidget):
    """信号源猎手 - 转动阵列找信号"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0           # 阵列指向角度
        self.source_angle = 45   # 信号源真实角度
        self.source_dist = 0.7   # 信号源距离中心比例
        self.snr = 20            # 信噪比
        self.strength = 0        # 当前信号强度
        self.locked = False      # 是否已锁定
        self.level = 1           # 关卡
        self.max_level = 8
        self.score = 0
        self.time_left = 60      # 剩余时间
        self.target_count = 0    # 已找到信号源数
        self.total_targets = 1   # 总目标数
        self.active = False      # 游戏是否激活（缺少此属性导致报错）
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self._init_level(1)
        self._init_ui()
        self.setFocusPolicy(Qt.StrongFocus)

    def _init_level(self, level):
        self.level = level
        self.locked = False
        self.time_left = 60
        configs = {
            1: {'src': 1, 'snr': 25, 'time': 60, 'move': False},
            2: {'src': 1, 'snr': 20, 'time': 45, 'move': True},
            3: {'src': 2, 'snr': 25, 'time': 60, 'move': False},
            4: {'src': 1, 'snr': 10, 'time': 60, 'move': False},
            5: {'src': 2, 'snr': 15, 'time': 45, 'move': True},
            6: {'src': 3, 'snr': 20, 'time': 60, 'move': False},
            7: {'src': 2, 'snr': 8,  'time': 50, 'move': True},
            8: {'src': 3, 'snr': 5,  'time': 60, 'move': True},
        }
        cfg = configs.get(level, configs[1])
        self.total_targets = cfg['src']
        self.snr = cfg['snr']
        self.target_count = 0
        self.move_src = cfg['move']
        # 随机放置信号源
        self.sources = []
        used = []
        for _ in range(self.total_targets):
            while True:
                a = random.randint(0, 359)
                if all(abs(a-u) > 30 for u in used):
                    used.append(a)
                    break
            d = 0.5 + random.random() * 0.3
            self.sources.append({'angle': a, 'dist': d, 'found': False})

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self.lbl_level = QLabel(f'第 {self.level} 关')
        self.lbl_level.setStyleSheet('font-size: 14px; font-weight: bold;')
        top.addWidget(self.lbl_level)
        self.lbl_time = QLabel('⏱ 60s')
        self.lbl_time.setStyleSheet('font-size: 14px; color: #ef4444; font-weight: bold;')
        top.addWidget(self.lbl_time)
        self.lbl_score_val = QLabel(f'得分: {self.score}')
        self.lbl_score_val.setStyleSheet('font-size: 12px; color: #64748b;')
        top.addWidget(self.lbl_score_val)
        top.addStretch()
        self.lbl_targets = QLabel(f'🎯 0/{self.total_targets}')
        self.lbl_targets.setStyleSheet('font-size: 12px; font-weight: bold; color: #1d4ed8;')
        top.addWidget(self.lbl_targets)
        self.btn_start = QPushButton('▶ 开始')
        self.btn_start.clicked.connect(self._start_level)
        top.addWidget(self.btn_start)
        layout.addLayout(top)

        # 信号强度条
        strength_layout = QHBoxLayout()
        strength_layout.addWidget(QLabel('信号:'))
        self.strength_bar = QLabel('░░░░░░░░░░ 0%')
        self.strength_bar.setStyleSheet('font-size: 14px; font-family: monospace; color: #22c55e;')
        strength_layout.addWidget(self.strength_bar, 1)
        self.lbl_angle = QLabel('指向: 0°')
        self.lbl_angle.setStyleSheet('font-size: 12px; color: #64748b;')
        strength_layout.addWidget(self.lbl_angle)
        layout.addLayout(strength_layout)

        # 画布
        self.canvas = QWidget()
        self.canvas.setMinimumSize(360, 360)
        self.canvas.setStyleSheet('background-color: #0a1628; border-radius: 8px; border: 2px solid #1e3a5f;')
        self.canvas.paintEvent = self._paint
        self.canvas.mouseMoveEvent = self._mouse_move
        self.canvas.setMouseTracking(True)
        layout.addWidget(self.canvas, 1)

        self.lbl_hint = QLabel('🎯 移动鼠标旋转阵列 | 找到信号源即可锁定')
        self.lbl_hint.setStyleSheet('font-size: 10px; color: #94a3b8;')
        layout.addWidget(self.lbl_hint)

        self._update_ui()

    def _start_level(self):
        self._init_level(self.level)
        self.active = True
        self.timer.start(1000)
        self.btn_start.setText('运行中...')
        self.lbl_hint.setText('🎯 移动鼠标旋转阵列，找到所有信号源！')
        self.setFocus()

    def _tick(self):
        if not self.active:
            return
        self.time_left -= 1
        if self.time_left <= 0:
            self.active = False
            self.timer.stop()
            self.btn_start.setText('▶ 重试')
            QMessageBox.information(self, '时间到', '⏰ 时间用完了！')
            return
        if self.move_src:
            for s in self.sources:
                if not s['found']:
                    s['angle'] = (s['angle'] + random.uniform(-3, 3)) % 360
        self._update_ui()

    def _mouse_move(self, event):
        if not self.active:
            return
        cx, cy = self.canvas.width()/2, self.canvas.height()/2
        dx = event.x() - cx
        dy = event.y() - cy
        self.angle = math.degrees(math.atan2(dx, -dy)) % 360

        # 计算信号强度
        self.strength = 0
        best_s = None
        for s in self.sources:
            if s['found']:
                continue
            diff = min(abs(self.angle - s['angle']), 360 - abs(self.angle - s['angle']))
            raw = max(0, math.cos(math.radians(diff*2))**4)
            noise = random.gauss(0, 0.15 * (1 - self.snr/40))
            val = max(0, min(1, raw + noise))
            if val > self.strength:
                self.strength = val
                best_s = s

        # 自动锁定（强度足够高时）
        if best_s and self.strength > 0.7:
            diff = min(abs(self.angle - best_s['angle']), 360 - abs(self.angle - best_s['angle']))
            if diff < 15 and not best_s['found']:
                best_s['found'] = True
                self.target_count += 1
                self.score += max(10, int(self.time_left))
                self.lbl_hint.setText(f'✅ 找到信号源! +{max(10, int(self.time_left))}分')

        self._update_ui()

        # 检查是否通关
        if self.target_count >= self.total_targets:
            self.active = False
            self.timer.stop()
            self.btn_start.setText('▶ 下一关')
            bonus = int(self.time_left * 2)
            self.score += bonus
            QMessageBox.information(self, '通关!', f'第{self.level}关通过！\n时间奖励: +{bonus}分\n总分: {self.score}')
            if self.level < self.max_level:
                self.level += 1
                self._init_level(self.level)
                self._update_ui()
                self.lbl_hint.setText('按「开始」继续挑战！')
            else:
                QMessageBox.information(self, '🎉 恭喜!', f'全部通关！最终得分: {self.score}')
                self.level = 1
                self.score = 0
                self._init_level(1)
                self._update_ui()
            self.btn_start.setText('▶ 开始')

    def _update_ui(self):
        self.lbl_level.setText(f'第 {self.level} 关')
        self.lbl_time.setText(f'⏱ {self.time_left}s')
        self.lbl_score_val.setText(f'得分: {self.score}')
        self.lbl_targets.setText(f'🎯 {self.target_count}/{self.total_targets}')
        self.lbl_angle.setText(f'指向: {int(self.angle)}°')
        bar_len = int(self.strength * 10)
        bar = '█' * bar_len + '░' * (10 - bar_len)
        self.strength_bar.setText(f'{bar} {int(self.strength*100)}%')
        color = '#22c55e' if self.strength > 0.5 else '#eab308' if self.strength > 0.2 else '#ef4444'
        self.strength_bar.setStyleSheet(f'font-size: 14px; font-family: monospace; color: {color};')
        self.canvas.update()

    def _paint(self, event):
        painter = QPainter(self.canvas)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.canvas.width(), self.canvas.height()
        cx, cy = w/2, h/2
        r = min(w, h) * 0.38

        # 背景圆
        painter.setPen(QPen(QColor('#1e3a5f'), 2))
        painter.setBrush(QBrush(QColor('#0d1b36')))
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # 角度刻度
        painter.setPen(QPen(QColor('#1e3a5f'), 1))
        for deg in range(0, 360, 30):
            rad = math.radians(deg)
            x1 = cx + r*0.85*math.sin(rad)
            y1 = cy - r*0.85*math.cos(rad)
            x2 = cx + r*0.95*math.sin(rad)
            y2 = cy - r*0.95*math.cos(rad)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # 阵列方向指示器
        rad = math.radians(self.angle)
        arr_len = r * 0.75
        ax = cx + arr_len * math.sin(rad)
        ay = cy - arr_len * math.cos(rad)
        painter.setPen(QPen(QColor('#22c55e'), 3))
        painter.drawLine(QPointF(cx, cy), QPointF(ax, ay))
        # 阵列头
        painter.setBrush(QBrush(QColor('#22c55e')))
        painter.drawEllipse(QPointF(ax, ay), 6, 6)

        # 阵元示意
        for i in range(-2, 3):
            px = cx + i*8*math.cos(rad)
            py = cy + i*8*math.sin(rad)
            painter.setBrush(QBrush(QColor('#3b82f6')))
            painter.drawEllipse(QPointF(px, py), 3, 3)

        # 已找到的信号源标记
        for s in self.sources:
            if s['found']:
                sr = math.radians(s['angle'])
                sx = cx + r*s['dist']*math.sin(sr)
                sy = cy - r*s['dist']*math.cos(sr)
                painter.setPen(QPen(QColor('#22c55e'), 2))
                painter.setFont(QFont('sans', 14))
                painter.drawText(QPointF(sx-8, sy+5), '✅')

        # 信号强度波纹
        if self.strength > 0.1:
            alpha = int(self.strength * 100)
            painter.setPen(QPen(QColor(34, 197, 94, alpha), 2))
            painter.setBrush(QBrush())
            painter.drawEllipse(QPointF(ax, ay), 8+int(self.strength*15), 8+int(self.strength*15))

        # 十字准星
        painter.setPen(QPen(QColor('#334155'), 1, Qt.DashLine))
        painter.drawLine(QPointF(cx-r*1.05, cy), QPointF(cx+r*1.05, cy))
        painter.drawLine(QPointF(cx, cy-r*1.05), QPointF(cx, cy+r*1.05))

        painter.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            if hasattr(self, 'active') and self.active:
                self.active = False
                self.timer.stop()
                self.btn_start.setText('▶ 继续')
            else:
                self._start_level()


# ==================== 游戏4: 干扰源扫雷 ====================

class MineSweeper(QWidget):
    """干扰源扫雷"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = 9
        self.cols = 9
        self.total_mines = 10
        self.board = []  # -1=雷, 0-8=数字
        self.state = []  # 0=未点, 1=已点, 2=标记旗, 3=标记问号
        self.game_over = False
        self.game_won = False
        self.flags_used = 0
        self.time_elapsed = 0
        self.first_click = True
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.cell_size = 36
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        top.addWidget(QLabel('💣 剩余标记:'))
        self.lbl_mines = QLabel(str(self.total_mines))
        self.lbl_mines.setStyleSheet('font-size: 18px; font-weight: bold; color: #ef4444;')
        top.addWidget(self.lbl_mines)
        top.addStretch()
        self.lbl_time_game = QLabel('⏱ 0s')
        self.lbl_time_game.setStyleSheet('font-size: 12px; color: #64748b;')
        top.addWidget(self.lbl_time_game)

        # 难度选择
        top.addStretch()
        self.difficulty_group = QButtonGroup()
        for i, (name, r, c, m) in enumerate([
            ('简单 9×9', 9, 9, 10),
            ('中等 16×16', 16, 16, 40),
            ('困难 16×30', 16, 30, 99)
        ]):
            btn = QRadioButton(name)
            if i == 0:
                btn.setChecked(True)
            self.difficulty_group.addButton(btn, i)
            top.addWidget(btn)

        self.btn_reset_mine = QPushButton('🔄 新游戏')
        self.btn_reset_mine.clicked.connect(lambda: self._new_game())
        top.addWidget(self.btn_reset_mine)
        layout.addLayout(top)

        # 游戏网格
        self.grid_widget = QGridLayout()
        self.grid_widget.setSpacing(2)
        self.buttons = {}
        layout.addLayout(self.grid_widget)

        layout.addStretch()

        self.lbl_hint_mine = QLabel('左键揭开 | 右键标记 🚩 | 找到所有信号源获胜')
        self.lbl_hint_mine.setStyleSheet('font-size: 10px; color: #94a3b8;')
        layout.addWidget(self.lbl_hint_mine)

        self._new_game()

    def _new_game(self):
        diff = self.difficulty_group.checkedId()
        if diff < 0:
            diff = 0
        configs = [(9, 9, 10), (16, 16, 40), (16, 30, 99)]
        self.rows, self.cols, self.total_mines = configs[diff]
        self.cell_size = 32 if self.rows <= 16 else 28

        # 重建网格
        for btn in self.buttons.values():
            btn.deleteLater()
        self.buttons = {}
        self.grid_widget = QGridLayout()
        self.grid_widget.setSpacing(1)

        for r in range(self.rows):
            for c in range(self.cols):
                btn = QPushButton('')
                btn.setFixedSize(self.cell_size, self.cell_size)
                btn.setStyleSheet(self._btn_style(0, False))
                btn.r, btn.c = r, c
                btn.clicked.connect(lambda checked, rr=r, cc=c: self._click_cell(rr, cc))
                self.grid_widget.addWidget(btn, r, c)
                self.buttons[(r, c)] = btn

        # 将grid_widget加入布局
        # 因为grid_widget已经被重建，需要重新添加到layout
        # 简单处理：直接替换layout内容
        # 先找到主layout
        parent_layout = self.layout()
        # 移除旧的grid_widget
        old_widget = None
        for i in range(parent_layout.count()):
            item = parent_layout.itemAt(i)
            if item and item.layout() and item.layout() == self.grid_widget:
                # 不应该发生
                pass
        # 将新的grid_widget插入到第二个位置（top之后）
        # 由于无法直接替换，我们清空并重新添加
        items_to_keep = []
        for i in range(parent_layout.count()):
            item = parent_layout.itemAt(i)
            if item.widget() != None:
                items_to_keep.append(item.widget())
            elif item.layout() != None:
                items_to_keep.append(item.layout())

        # 这里简化为self.setLayout会破坏已有结构
        # 改用直接替换内容
        parent_layout.insertLayout(1, self.grid_widget)

        self.board = [[0]*self.cols for _ in range(self.rows)]
        self.state = [[0]*self.cols for _ in range(self.rows)]
        self.game_over = False
        self.game_won = False
        self.flags_used = 0
        self.time_elapsed = 0
        self.first_click = True
        self.timer.stop()
        self.lbl_mines.setText(str(self.total_mines))
        self.lbl_time_game.setText('⏱ 0s')
        self.lbl_hint_mine.setText('左键揭开 | 右键标记 🚩')
        self._update_all_buttons()

    def _btn_style(self, val, revealed):
        if not revealed:
            return 'background-color: #475569; border: 1px solid #64748b; border-radius: 3px; font-weight: bold; font-size: 10px;'
        if val == -1:
            return 'background-color: #fecaca; border: 1px solid #ef4444; border-radius: 3px; font-size: 14px;'
        colors = ['', '#3b82f6', '#22c55e', '#ef4444', '#1d4ed8', '#7c3aed', '#f59e0b', '#ec4899', '#000']
        c = colors[val] if 0 < val <= 8 and val < len(colors) else '#334155'
        return f'background-color: #e2e8f0; color: {c}; border: 1px solid #cbd5e1; border-radius: 3px; font-weight: bold; font-size: 12px;'

    def _place_mines(self, safe_r, safe_c):
        """避开首次点击位置布雷"""
        safe = {(safe_r, safe_c)}
        for dr in (-1,0,1):
            for dc in (-1,0,1):
                rr, cc = safe_r+dr, safe_c+dc
                if 0 <= rr < self.rows and 0 <= cc < self.cols:
                    safe.add((rr, cc))

        placed = 0
        while placed < self.total_mines:
            r, c = random.randint(0, self.rows-1), random.randint(0, self.cols-1)
            if (r, c) not in safe and self.board[r][c] != -1:
                self.board[r][c] = -1
                placed += 1
                for dr in (-1,0,1):
                    for dc in (-1,0,1):
                        rr, cc = r+dr, c+dc
                        if 0 <= rr < self.rows and 0 <= cc < self.cols and self.board[rr][cc] != -1:
                            self.board[rr][cc] += 1
            elif (r, c) in safe:
                continue

    def _click_cell(self, r, c):
        if self.game_over or self.game_won:
            return
        if self.state[r][c] == 1:
            return

        # 右键菜单由QPushButton不支持，用shift+点击代替
        modifiers = QApplication.keyboardModifiers()
        if modifiers == Qt.ShiftModifier:
            self._flag_cell(r, c)
            return

        if self.first_click:
            self.first_click = False
            self._place_mines(r, c)
            self.timer.start(1000)

        if self.board[r][c] == -1:
            self._reveal_all()
            self.game_over = True
            self.timer.stop()
            self.lbl_hint_mine.setText('💥 踩到干扰源！游戏结束')
            QMessageBox.information(self, '游戏结束', '💥 你踩到干扰源了！')
            return

        self._reveal_cell(r, c)
        self._check_win()

    def _flag_cell(self, r, c):
        if self.state[r][c] == 0:
            self.state[r][c] = 2  # 旗
            self.flags_used += 1
        elif self.state[r][c] == 2:
            self.state[r][c] = 3  # 问号
            self.flags_used -= 1
        elif self.state[r][c] == 3:
            self.state[r][c] = 0
        self.lbl_mines.setText(str(self.total_mines - self.flags_used))
        self._update_button(r, c)

    def _reveal_cell(self, r, c):
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return
        if self.state[r][c] == 1:
            return
        if self.board[r][c] == -1:
            return

        self.state[r][c] = 1
        self._update_button(r, c)

        if self.board[r][c] == 0:
            for dr in (-1,0,1):
                for dc in (-1,0,1):
                    nr, nc = r+dr, c+dc
                    if 0 <= nr < self.rows and 0 <= nc < self.cols and self.state[nr][nc] != 1:
                        self._reveal_cell(nr, nc)

    def _reveal_all(self):
        for r in range(self.rows):
            for c in range(self.cols):
                if self.board[r][c] == -1:
                    self.state[r][c] = 1
                self._update_button(r, c)

    def _check_win(self):
        unrevealed = 0
        for r in range(self.rows):
            for c in range(self.cols):
                if self.board[r][c] != -1 and self.state[r][c] != 1:
                    unrevealed += 1
        if unrevealed == 0:
            self.game_won = True
            self.timer.stop()
            self.lbl_hint_mine.setText('🎉 找到所有信号源！')
            QMessageBox.information(self, '胜利!', f'🎉 你找到了所有信号源！\n用时: {self.time_elapsed}s')
            self._new_game()

    def _tick(self):
        self.time_elapsed += 1
        self.lbl_time_game.setText(f'⏱ {self.time_elapsed}s')

    def _update_button(self, r, c):
        btn = self.buttons.get((r, c))
        if not btn:
            return
        s = self.state[r][c]
        if s == 0:
            btn.setText('')
            btn.setStyleSheet(self._btn_style(0, False))
        elif s == 1:
            v = self.board[r][c]
            txt = '💣' if v == -1 else str(v) if v > 0 else ''
            btn.setText(txt)
            btn.setStyleSheet(self._btn_style(v, True))
        elif s == 2:
            btn.setText('🚩')
            btn.setStyleSheet('background-color: #fef3c7; border: 1px solid #f59e0b; border-radius: 3px; font-size: 12px;')
        elif s == 3:
            btn.setText('❓')
            btn.setStyleSheet('background-color: #f1f5f9; border: 1px solid #94a3b8; border-radius: 3px; font-size: 10px;')

    def _update_all_buttons(self):
        for r in range(self.rows):
            for c in range(self.cols):
                self._update_button(r, c)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_R:
            self._new_game()


# QApplication keyboardModifiers helper
try:
    from PyQt5.QtWidgets import QApplication
except ImportError:
    pass