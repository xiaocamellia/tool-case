# 🛰️ 便携化工具箱 (Portable Radar Toolbox) V1.1.0

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green)](https://www.riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📖 项目简介 | About

**便携化工具箱** 是一款基于 PyQt5 + matplotlib 的雷达信号处理与工程计算一体化桌面工具。集成了雷达挂飞数据可视化、干涉仪测向仿真、测向校正、阵列天线设计、工程指标计算、外场试验记录管理以及内建休闲小游戏等功能，专为雷达工程师与相关领域研究人员打造。

> **Portable Radar Toolbox** is an all-in-one desktop application built with PyQt5 and matplotlib, designed for radar signal processing and engineering calculations. It integrates radar flight data visualization, interferometer direction finding simulation, array antenna design, engineering calculations, experiment recording, and built-in casual mini-games.

---

## ✨ 功能特性 | Features

### 🗺️ 总览

| 模块 | 功能 | 说明 |
|------|------|------|
| 数据可视化处理 | 📊 Radar Data Visualizer | 雷达挂飞数据加载、切片、过滤、多图绘制、叠加对比、高清导出 |
| 数据真值复核 | 📈 Data Truth Review | GPS 时间域插值、雷达样点两阶段对齐、多维联合剔野与批次结果导出 |
| 干涉仪测向仿真 | 📡 Interferometer DF Sim | 阵列配置、DOA估计算法仿真与性能评估 |
| 测向校正自动化 | Direction Finding Calibration | 标定数据导入、参数寻优、批次参数复用与误差对比 |
| 阵列设计助手 | 🔭 Array Design Assistant | 阵列方向图快速设计与评估 |
| 指标计算器 | 🧮 Engineering Calculator | 天线、雷达、链路预算、测向等工程计算合集 |
| 格式转换 | Format Conversion | TR 幅相参数 TXT/BIN 严格转换、回读与逐帧校验 |
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

### 2️⃣ 数据真值复核 | Data Truth Review

- 支持加载 TXT、CSV、DAT、Excel 雷达测量数据与 GPS/惯导真值数据；雷达数据沿用“数据可视化处理”的独立导入、列名匹配和字段识别流程
- 自动识别距离、速度、方位角和俯仰角，复核维度可独立勾选，仅对启用维度执行统计、绘图和导出
- GPS 使用源文件中的真实时间列进行插值，时间单位支持秒、毫秒和微秒；雷达采样间隔可配置，默认 `128 ms`
- GPS 在时间域重采样到雷达采样节拍，随后保持 `1:1` 样点尺度完成对齐，不按样点数量拉伸数据，也不再切换为时间坐标绘图
- 雷达数据的范围截取与数值过滤在对齐前执行，并保留原始样点位置，便于先排除无效数据段再与 GPS 真值配对
- 采用“粗对齐 → 查看雷达减 GPS 差值 → 距离零偏校正 → 精对齐”的两阶段流程；零偏修正和野点剔除仅作用于精对齐
- 精对齐支持多维联合剔野：主参考维度始终参与，其余已启用维度可按需加入；各维度可分别使用手动阈值或自动 MAD 阈值
- 多维野点索引取并集，并同步删除雷达样点及其对应的 GPS 插值样点；对齐偏移量仍只由主参考维度估计
- 原始数据、插值结果、粗/精对齐曲线、误差时序、误差分布和轨迹均可查看，并提供 RMSE、P95、相关系数等统计量
- 对齐与误差计算在后台线程执行，长序列绘图自动抽稀，但统计与导出结果保留全量有效样点
- 支持按批次导出中文表头 CSV、配置 JSON 和 9 张分析图；GPS 原始、插值、粗对齐及精对齐结果均保留 UTC 字段和源时间单位

### 3️⃣ 干涉仪测向仿真 | Interferometer DF Simulation

- 支持线阵、L 阵、圆阵等多种阵列构型配置
- 支持 Bartlett、MUSIC、ESPRIT 等 DOA 估计算法仿真
- 支持 1D/2D 空间谱搜索、峰值标注与测向精度评估
- 支持多目标信号源配置，可分别设置方位、俯仰、频率、幅度与 SNR
- 支持阵元相位误差、幅度误差、位置误差、频率偏差等非理想因素
- 单次仿真与蒙特卡洛分析使用后台线程执行，避免大快拍数或小扫描步长时阻塞界面
- 多目标结果按真实目标与估计峰最近邻匹配后计算误差，避免谱峰强度排序导致误差错配

### 4️⃣ 测向校正自动化 | Direction Finding Calibration

- 支持 Excel、CSV、TXT 四列标定数据导入与校验
- 自动优化 `yy_r4_ZT`、`zz_r4_ZT`，同时纳入方位和俯仰误差
- 展示优化前后的均值、标准差、RMSE、最大绝对误差和双图对比
- 批次固定参数支持本地保存、选择复用、覆盖修改、另存与删除
- 批次配置包含数据路径、固定几何参数、3×3 变换矩阵、优化初值和备注
- 优化结果可一键应用为下一次校正初值，再保存到当前批次配置
- 后台执行校正任务，并可导出 JSON 参数指标、CSV 样本明细和 PNG 误差曲线

### 5️⃣ 阵列设计助手 | Array Design Assistant

- 快速搭建均匀/非均匀线阵、面阵等构型
- 方向图计算与可视化
- 阵元激励优化（幅度加权、相位加权等）

### 6️⃣ 指标计算器合集 | Engineering Calculator Collection

- **天线计算**: 天线增益、波束宽度、有效口径等
- **雷达计算**: 雷达方程、SNR、探测距离等
- **链路预算**: 自由空间损耗、链路余量等
- **测向计算**: 相位差测向、基线解模糊等
- 内置常用物理常数与单位转换

### 7️⃣ 格式转换 | Format Conversion

- TR 幅相参数 TXT 严格校验并转换为 270 字节帧合并 BIN
- 支持 1~24 个参数块，每块 64 行、通道号严格按 1~64 排列
- 按 0.1 单位量化为大端 `int16`，自动配置收发标志、温度字节、包计数与累加和
- 支持 BIN 回读为 TXT，并逐帧校验协议字段与累加和
- 转换前展示帧摘要和幅相数据预览，已有输出文件须确认后覆盖

### 8️⃣ 试验记录助手 | Experiment Recording Assistant

- 项目管理：创建/编辑/删除试验项目
- 结构化任务与记录管理
- 试验步骤内可按需添加数据记录和截图附件，记录来源与步骤对应关系更清晰
- 兼容未归属步骤的历史数据记录与截图附件
- 一键导出为 Word (.docx) 格式试验报告，含步骤、数据表、截图、标题与格式排版

### 9️⃣ 摸鱼游戏 | Mini Games

内置四款休闲小游戏，界面精美，缓解工作压力：

- **🎮 频谱2048 (Spectrum 2048)**: 经典2048玩法，数字对应频段标签（2.4G→4.8G→...→82T）
- **🐍 阵列贪吃蛇 (Array Snake)**: 传统贪吃蛇，雷达主题风
- **🔍 信号源猎手 (Signal Hunter)**: 在网格中搜索隐藏信号源
- **💣 干扰源扫雷 (Minefield Sweeper)**: 扫雷玩法，干扰源主题

---

## 🚀 快速开始 | Quick Start

### 环境要求 | Prerequisites

- Python 3.11+（CI 验证 3.11、3.12）
- pip / conda

### 安装运行 | Installation & Run

```bash
# 克隆仓库
git clone https://github.com/xiaocamellia/tool-case.git
cd tool-case

# 安装锁定的运行依赖
pip install -r requirements.lock

# 开发/测试时安装（含 Ruff、mypy、pip-audit）
pip install -r requirements-dev.txt

# 校验锁定文件哈希
python scripts/verify_lock_hash.py

# 启动程序
python radar_tool/run.py
```

### 依赖清单 | Dependencies

```
# requirements.txt 面向 Python 3.11+ 的安全维护版本
PyQt5>=5.15,<5.16
matplotlib / numpy / pandas / scipy / openpyxl / python-docx
xlrd>=2.0.1,<3
```

---

## 📂 项目结构 | Project Structure

```
tool-case/
├── README.md                     # 本文件
├── requirements.txt              # 运行依赖
├── requirements-dev.txt          # 开发与测试依赖
├── requirements.lock             # 运行依赖精确锁定
├── requirements.lock.sha256      # 锁定文件 SHA256
├── pyproject.toml                # 包入口与工具配置
├── scripts/verify_lock_hash.py   # 锁定文件校验脚本
├── image/                        # 图标资源
│   └── rose.ico
├── radar_tool/                   # 主程序包
    ├── __init__.py
    ├── run.py                    # 程序入口
    ├── main_window.py            # 主窗口、模块页签与懒加载调度
    ├── visualization_panel.py     # 数据可视化处理模块
    ├── app_config.py             # 应用全局配置（matplotlib参数等）
    ├── data_loader.py            # 数据文件加载器
    ├── models.py                 # 数据模型定义（数据集、绘图项等）
    ├── plotting.py               # 绘图引擎与画布
    ├── compare_analysis.py       # 数据真值复核模块
    ├── interferometer_sim.py     # 干涉仪测向仿真模块
    ├── calibration_panel.py      # 测向校正界面与批次参数管理
    ├── calibration_data_loader.py # 标定数据读取与校验
    ├── calibration_model.py      # 校正坐标变换模型
    ├── calibration_optimizer.py  # yy/zz 参数优化
    ├── calibration_metrics.py    # 前后误差指标计算
    ├── calibration_batch_store.py # 可复用批次参数持久化
    ├── array_designer.py         # 阵列设计助手模块
    ├── calc_panel.py             # 指标计算器合集模块
    ├── format_conversion.py      # TR 幅相 TXT/BIN 协议编解码与校验
    ├── format_conversion_panel.py # 格式转换操作界面
    ├── exp_recorder.py           # 试验记录助手模块
    ├── game_panel.py             # 摸鱼游戏模块
    ├── ui_theme.py               # UI 主题与样式
    ├── alignment.py              # 对齐工具
    └── logger.py                 # 日志系统
├── tests/                        # 自动化测试
├── docs/
│   └── 设计文档/                  # 模块设计与处理流程文档
├── packaging/
│   └── nuitka/                    # Nuitka standalone 构建配置
├── artifacts/                    # 本地编译输出（已忽略）
│   ├── bin/                      # 可执行文件及随附 image 资源
│   ├── nuitka/                   # Nuitka 中间产物与分发目录
│   └── reports/                  # 编译报告
├── tools/                        # 本地打包工具（已忽略）
└── var/                          # 运行时数据（自动生成、已忽略）
    ├── 日志/                      # 运行日志
    ├── 测向校正/                  # 校正参数库
    └── 试验数据/                  # 试验记录数据
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
9. **其他功能**: 切换页签使用干涉仪仿真、测向校正、阵列设计、计算器、格式转换、试验记录或小游戏

### 数据真值复核工作流 | Truth Review Workflow

1. **导入数据**: 分别加载雷达数据和 GPS 真值数据，检查自动识别的距离、速度、方位角、俯仰角及 GPS 时间列
2. **选择维度**: 勾选本批次需要复核的维度，并指定用于估计对齐偏移量的主参考维度
3. **预处理雷达数据**: 在对齐前设置雷达样点范围和过滤条件，确认原始与“过滤和截取后”样点统计及曲线
4. **设置时间参数**: 选择 GPS 时间单位（秒/毫秒/微秒），输入雷达采样间隔；默认值为 `128 ms`
5. **执行粗对齐**: GPS 先在时间域插值到雷达采样节拍，再在样点域进行粗对齐；通过“雷达 - GPS”差值图判断距离零偏
6. **设置精对齐**: 输入距离零偏校正值，并为主参考维度及所选备选维度设置手动或自动 MAD 野点阈值
7. **执行精对齐**: 联合各维度的野点索引，同步剔除雷达与 GPS 对应样点，再由主参考维度完成最终样点偏移估计
8. **检查并导出**: 核对对齐曲线、误差图和统计指标，选择导出根目录生成完整批次结果

导出目录命名为 `YYYYMMDD_HHMMSS_<雷达数据名>_真值复核`，包含以下文件：

- `01_真值复核结果.csv`、`02_真值复核有效配对.csv`
- `03_雷达测量数据.csv`、`04_GPS原始真值数据.csv`、`05_GPS时间插值数据.csv`
- `06_粗对齐结果.csv`、`07_误差指标.csv`、`08_对齐算法比较.csv`
- `09_复核配置.json` 及 9 张分析 PNG 图片

CSV 使用“中文名称(english_identifier)”表头。UTC 相关字段包括 `GPS原始UTC时间(gps_utc_time_raw)`、`GPS插值UTC时间(gps_interpolated_utc_time)`、`GPS粗对齐UTC时间(gps_coarse_aligned_utc_time)`、`GPS精对齐UTC时间(gps_fine_aligned_utc_time)` 和 `GPS UTC时间单位(gps_utc_time_unit)`；UTC 数值保持 GPS 源数据的时间单位，不擅自按 Unix 时间转换。

### 数据文件加载 | Data Loading

- 支持 `TXT`、`CSV`、`DAT`、`LOG`、`XLSX` 和 `XLS` 数据文件。
- 文本文件自动识别 UTF-8、UTF-8 BOM 和 GB18030，并识别逗号、分号、中文逗号、制表符或空格分隔。
- 引号内分隔符、行尾分隔符、空值和行字段数差异不会导致整份正常数据加载失败；短行自动补空值。
- 列名文件按非空行读取。列名数少于数据列时自动补 `列--N`，多于数据列时忽略多余名称。
- 字段关联仍可在“复核项目与字段映射”中人工选择；不要依赖列名顺序推断业务含义。
- 若文件仍无法识别，请检查是否误选列名文件、纯文本说明文件或不支持的格式，并使用界面错误信息和日志错误编号进行定位。

### 打包部署 | Packaging

项目仅使用 Nuitka `standalone` 打包。发布采用目录型分发，不使用 `onefile`，避免每次启动解压临时文件，以获得更稳定、更快的启动体验。构建配置位于 `packaging/nuitka/`，编译输出统一存放在 `artifacts/`。

主窗口采用页签懒加载：启动时只创建首页，其他功能页在首次切换时再初始化。

```powershell
# 固定构建环境：Python 3.12.7、MSVC 14.3、Nuitka 4.1.3
python scripts\verify_lock_hash.py
python -m pip install --no-deps -r requirements.lock
python -m pip install --no-deps -r requirements-build.lock

# 正式构建必须提供可信代码签名证书
.\packaging\nuitka\build.ps1 -CertificateThumbprint <SHA1-thumbprint>

# 仅本地链路验证可跳过签名；该产物禁止发布
.\packaging\nuitka\build.ps1 -SkipTests -AllowUnsigned
```

正式发布由 `.github/workflows/release.yml` 在 `v*` 标签或手动触发时执行。流水线从锁定依赖重建环境，完成全量测试、Nuitka standalone 构建、全 PE 文件 Authenticode 签名、隔离安装与离线启动冒烟、Qt/字体/图标/Excel/Word 资源检查、SBOM、第三方清单、构建清单、SHA256 和 Windows Defender 恶意软件扫描。GitHub Actions 需要配置 `WINDOWS_CERTIFICATE_BASE64` 与 `WINDOWS_CERTIFICATE_PASSWORD` 两个发布密钥。

---

## ⚙️ 配置 | Configuration

应用全局配置位于 `radar_tool/app_config.py`，包括：

- **matplotlib 参数**: 字体、DPI、颜色方案、网格样式等
- **颜色循环**: 支持 12 种绘图颜色
- **线型循环**: 支持 4 种线型（实线、虚线、点划线、点线）

---

## 📝 近期更新 | Recent Changes

### 2026-11-08

- **数据加载提速**：编码和分隔符检测共享同一样本，正常文本文件由两次 Pandas 解析降为一次；8 列数字 CSV 基准测试中，1 万、10 万和 30 万行加载时间分别降低约 54%、74% 和 75%。
- **加载兼容性**：放宽普通文本数据的分隔符、引号、行尾符号和缺失字段规则；列名数量不一致不再阻断加载。
- **错误诊断**：后台加载保留原始异常类型，普通格式问题不再误报为“未预期错误”；移除线程启动前设置优先级产生的无效警告。
- **发布计划**：`PROJECT_AUDIT_ACTION_PLAN.md` 增加从构建环境、质量门禁、签名、隔离验收到 GitHub Release 和回滚的详细打包流程。

### 2026-08-28

- **时间基准修正**: GPS 改为使用真实时间列在时间域插值，支持秒、毫秒、微秒单位；雷达采样间隔可配置且默认 `128 ms`，插值后全程按 `1:1` 样点尺度对齐与绘图。
- **两阶段对齐**: 新增粗对齐差值检查、距离零偏校正和精对齐流程，雷达范围截取与过滤固定在对齐前执行。
- **多维联合剔野**: 主参考维度与所有已选备选维度可共同识别野点，分别配置手动或自动 MAD 阈值，并同步剔除雷达/GPS 对应样点。
- **批次完整导出**: 按日期时间和雷达数据名生成独立目录，导出测量数据、GPS 原始/插值数据、粗/精对齐结果、误差指标、配置与 9 张分析图。
- **UTC 信息保留**: 导出结果增加 GPS 原始、插值、粗对齐和精对齐 UTC 字段，并原样保留 GPS 源时间单位。
- **性能与布局**: 对齐任务在后台线程执行，长序列绘图自动抽稀；调整参数区与绘图区布局，改善模块启动显示和长数据操作响应。

### 2026-08-26

- **格式转换**: 新增 TR 幅相参数 TXT/BIN 双向转换、严格协议预检、逐帧累加和校验与数据预览。

### 2026-08-24

- **测向校正自动化**: 新增四列标定数据导入、`yy_r4_ZT`/`zz_r4_ZT` 自动优化、前后误差指标与双图对比。
- **批次参数库**: 固定参数、变换矩阵、优化初值和数据路径可按批次保存，支持复用、覆盖修改、另存和删除。
- **结果导出**: 同步导出 JSON 参数指标、CSV 样本明细和 PNG 误差曲线。
- **后台计算**: 校正优化在线程中执行，避免阻塞主窗口。

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
