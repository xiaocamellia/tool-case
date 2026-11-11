"""验证 setMinimumWidth 是否能把控件最小宽度压到 sizeHint 以下。"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QPushButton, QHBoxLayout, QWidget

app = QApplication.instance() or QApplication([])
w = QWidget()
lay = QHBoxLayout(w)
btn = QPushButton('➕ 叠加绘制 (保持上一幅)')
lay.addWidget(btn)
w.show()
app.processEvents()
print('before: sizeHint', btn.sizeHint().width(), 'minHint', btn.minimumSizeHint().width(),
      'explicit min', btn.minimumSize().width(), 'layout min', lay.minimumSize().width())
btn.setMinimumWidth(60)
app.processEvents()
print('after setMinimumWidth(60): minHint', btn.minimumSizeHint().width(),
      'explicit min', btn.minimumSize().width(), 'layout min', lay.minimumSize().width())
w.close()
