# 🛰️ 便携化工具箱 (Portable Radar Toolbox) V1.0.0

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green)](https://www.riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📖 项目简介 | About

**便携化工具箱** 是一款基于 PyQt5 + matplotlib 的雷达信号处理与工程计算一体化桌面工具。集成了雷达挂飞数据可视化、干涉仪测向仿真、阵列天线设计、工程指标计算、外场试验记录管理以及内建休闲小游戏等功能，专为雷达工程师与相关领域研究人员打造。

> **Portable Radar Toolbox** is an all-in-one desktop application built with PyQt5 and matplotlib, designed for radar signal processing and engineering calculations. It integrates radar flight data visualization, interferometer direction finding simulation, array antenna design, engineering calculations, experiment recording, and built-in casual mini-games.

---

## ✨ 功能特性 | Features

### 🗺️ 总览

| 模块 | 功能 | 说明 |
|------|------|------|
| 数据可视化处理 | 📊 Radar Data Visualizer | 雷达挂飞数据加载、切片、过滤、多图绘制、叠加对比、高清导出 |
| 挂飞对比分析 | 📈 Flight Test Comparison | 测量数据与真值数据的对比分析、误差统计 |
| 干涉仪测向仿真 | 📡 Interferometer DF Sim | 阵列配置、DOA估计算法仿真与性能评估 |
| 阵列设计助手 | 🔭 Array Design Assistant | 阵列方向图快速设计与评估 |
| 指标计算器 | 🧮 Engineering Calculator | 天线、雷达、链路预算、测向等工程计算合集 |
| 试验记录助手 | 📋 Experiment Recorder | 外场/暗室试验的结构化记录与 Word 报告导出 |
| 摸鱼游戏 | 🎮 Mini Games | 频谱2048、阵列贪吃蛇、信号源猎手、干扰源扫雷 |

---

### 1️⃣ 数据可视化处理 | Data Visualization

- **多格式数据加载**: 支持 `.txt` 等文本格式数据文件，自动匹配列名文件
- **数据集管理**: 多数据集同时加载、切换、重载、移除
- **数据切片**: 通过起始/结束采样点索引截取数据范围
- **数据过滤**: 按指定列的值范围筛选数据行
- **多图页签**: 支持创建多个独立绘图页面，任意切换
- **灵活绘图**: 多列参数批量绘图，支持叠加绘制（保留上一幅曲线）
- **曲线管理**: 支持移除/清空绘图项
- **统计显示**: 自动计算并显示每条曲线的均值 (μ)、标准差 (σ)、最大值、最小值、样本数 (N)
- **高清导出**: 支持导出 PNG (600dpi)、PDF、SVG、TIFF 格式
- **交互导航**: matplotlib 原生工具栏（缩放、平移、保存等）
- **独立面板架构**: 数据可视化已拆分为独立 `VisualizationPanel`，主窗口仅负责页面切换与全局状态

### 2️⃣ 挂飞对比分析 | Flight Test Comparison

- 支持加载测向设备测量数据与 GPS/惯导真值数据
- 多种误差指标计算与分析

### 3️⃣ 干涉仪测向仿真 | Interferometer DF Simulation

- 支持线阵、L 阵、圆阵等多种阵列构型配置
- 支持 Bartlett、MUSIC、ESPRIT 等 DOA 估计算法仿真
- 支持 1D/2D 空间谱搜索、峰值标注与测向精度评估
- 支持多目标信号源配置，可分别设置方位、俯仰、频率、幅度与 SNR
- 支持阵元相位误差、幅度误差、位置误差、频率偏差等非理想因素
- 单次仿真与蒙特卡洛分析使用后台线程执行，避免大快拍数或小扫描步长时阻塞界面
- 多目标结果按真实目标与估计峰最近邻匹配后计算误差，避免谱峰强度排序导致误差错配

### 4️⃣ 阵列设计助手 | Array Design Assistant

- 快速搭建均匀/非均匀线阵、面阵等构型
- 方向图计算与可视化
- 阵元激励优化（幅度加权、相位加权等）

### 5️⃣ 指标计算器合集 | Engineering Calculator Collection

- **天线计算**: 天线增益、波束宽度、有效口径等
- **雷达计算**: 雷达方程、SNR、探测距离等
- **链路预算**: 自由空间损耗、链路余量等
- **测向计算**: 相位差测向、基线解模糊等
- 内置常用物理常数与单位转换

### 6️⃣ 试验记录助手 | Experiment Recording Assistant

- 项目管理：创建/编辑/删除试验项目
- 结构化任务与记录管理
- 试验步骤内可按需添加数据记录和截图附件，记录来源与步骤对应关系更清晰
- 兼容未归属步骤的历史数据记录与截图附件
- 一键导出为 Word (.docx) 格式试验报告，含步骤、数据表、截图、标题与格式排版

### 7️⃣ 摸鱼游戏 | Mini Games

内置四款休闲小游戏，界面精美，缓解工作压力：

- **🎮 频谱2048 (Spectrum 2048)**: 经典2048玩法，数字对应频段标签（2.4G→4.8G→...→82T）
- **🐍 阵列贪吃蛇 (Array Snake)**: 传统贪吃蛇，雷达主题风
- **🔍 信号源猎手 (Signal Hunter)**: 在网格中搜索隐藏信号源
- **💣 干扰源扫雷 (Minefield Sweeper)**: 扫雷玩法，干扰源主题

---

## 🚀 快速开始 | Quick Start

### 环境要求 | Prerequisites

- Python 3.8+
- pip / conda

### 安装运行 | Installation & Run

```bash
# 克隆仓库
git clone https://github.com/xiaocamellia/tool-case.git
cd tool-case

# 安装依赖
pip install -r requirements.txt

# 启动程序
python radar_tool/run.py
```

### 依赖清单 | Dependencies

```
PyQt5>=5.15
matplotlib>=3.5
numpy>=1.21
pandas>=1.3
scipy>=1.7
python-docx>=0.8.11
```

---

## 📂 项目结构 | Project Structure

```
tool-case/
├── README.md                     # 本文件
├── requirements.txt              # Python 依赖
├── image/                        # 图标资源
│   └── rose.ico
├── 试验数据/                      # 试验记录数据目录（自动生成）
└── radar_tool/                   # 主程序包
    ├── __init__.py
    ├── run.py                    # 程序入口
    ├── main_window.py            # 主窗口、模块页签与懒加载调度
    ├── visualization_panel.py     # 数据可视化处理模块
    ├── app_config.py             # 应用全局配置（matplotlib参数等）
    ├── data_loader.py            # 数据文件加载器
    ├── models.py                 # 数据模型定义（数据集、绘图项等）
    ├── plotting.py               # 绘图引擎与画布
    ├── compare_analysis.py       # 挂飞对比分析模块
    ├── interferometer_sim.py     # 干涉仪测向仿真模块
    ├── array_designer.py         # 阵列设计助手模块
    ├── calc_panel.py             # 指标计算器合集模块
    ├── exp_recorder.py           # 试验记录助手模块
    ├── game_panel.py             # 摸鱼游戏模块
    ├── ui_theme.py               # UI 主题与样式
    ├── alignment.py              # 对齐工具
    └── logger.py                 # 日志系统
```

---

## 🔧 使用说明 | Usage Guide

### 基本工作流 | Basic Workflow

1. **启动应用**: 运行 `python radar_tool/run.py`
2. **加载数据**: 在"数据可视化处理"页签，点击"加载数据文件"选择雷达数据文件
3. **可选 - 加载列名**: 点击"加载列名文件"为数据列指定名称
4. **选择参数**: 在列选择列表中勾选要绘制的参数
5. **绘图展示**: 点击"绘制"或"叠加绘制"生成对比曲线
6. **调整范围**: 使用起始/结束 SpinBox 切片数据，点击"按当前范围重绘对比图"
7. **数据过滤**: 选择列并设置数值范围过滤数据行
8. **导出结果**: 点击"导出高清图"保存为图片或矢量图
9. **其他功能**: 切换页签使用干涉仪仿真、阵列设计、计算器、试验记录或小游戏

### 打包部署 | Packaging

程序兼容 PyInstaller 和 Nuitka 打包。打包后可执行文件与 `image/` 目录需放在同一路径下。

为降低 Nuitka 打包后的启动等待时间，主窗口采用页签懒加载：启动时只创建首页，其他功能页在首次切换时再初始化。

```bash
# 示例：使用 PyInstaller 打包
pyinstaller --onefile --windowed --add-data "image;image" radar_tool/run.py
```

---

## ⚙️ 配置 | Configuration

应用全局配置位于 `radar_tool/app_config.py`，包括：

- **matplotlib 参数**: 字体、DPI、颜色方案、网格样式等
- **颜色循环**: 支持 12 种绘图颜色
- **线型循环**: 支持 4 种线型（实线、虚线、点划线、点线）

---

## 📝 近期更新 | Recent Changes

### 2026-07-14

- **干涉仪仿真增强**: 支持多目标信号源增删与独立参数配置，包括方位、俯仰、频率、幅度、SNR。
- **非理想因素建模**: 增加阵元相位误差、幅度误差、位置误差与频率偏差配置，并接入信号生成和蒙特卡洛分析。
- **多目标可视化**: 阵列 3D 布局、1D/2D 空间谱图同时标注多个真实目标与多个估计峰。
- **误差统计修正**: 多目标场景下按真实目标与估计峰最近邻匹配后计算误差，避免峰值强度排序造成目标错配。
- **性能与稳定性**: 单次仿真、MUSIC 2D 扫描和蒙特卡洛分析改为后台线程执行，降低界面卡死风险。

### 2026-07-13

- **可视化模块解耦**: 将数据可视化处理从 `MainWindow` 拆分为独立 `VisualizationPanel`，主窗口职责收敛为页签切换和全局状态管理。
- **启动速度优化**: 主功能页签采用懒加载，首次进入对应页签时才创建模块面板，改善 Nuitka 打包后的冷启动体验。
- **试验记录重构**: 数据记录和截图管理移动到试验步骤内部，每个步骤可独立选择是否记录数据或添加截图。
- **记录导出兼容**: Word 报告按步骤输出数据记录和截图，同时保留未归属步骤历史记录的导出兼容。
- **运行问题修复**: 修复可视化面板初始化、页签懒加载占位、试验记录助手方法缺失等启动/切换异常。

---

## 📜 许可证 | License

本项目基于 MIT 许可证开源。详见 [LICENSE](LICENSE) 文件。

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👤 作者 | Author

- **GitHub**: [@xiaocamellia](https://github.com/xiaocamellia)
- **项目地址**: [https://github.com/xiaocamellia/tool-case.git](https://github.com/xiaocamellia/tool-case.git)

---

## 🙏 致谢 | Acknowledgements

- [PyQt5](https://www.riverbankcomputing.com/software/pyqt/) — 跨平台 GUI 框架
- [matplotlib](https://matplotlib.org/) — 高质量数据可视化库
- [NumPy](https://numpy.org/) / [Pandas](https://pandas.pydata.org/) — 科学计算与数据处理
- [SciPy](https://scipy.org/) — 科学计算工具集
- [python-docx](https://python-docx.readthedocs.io/) — Word 文档生成库

---

*Made with ❤️ for radar engineers and signal processing enthusiasts.*