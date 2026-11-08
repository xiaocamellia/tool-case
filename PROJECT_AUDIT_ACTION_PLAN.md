# 项目体检与整改行动计划

> 生成日期：2026-11-05
> 适用项目：便携化工具箱（Portable Radar Toolbox）
> 原则：先处理数据安全与计算正确性，再完善依赖、测试和架构。

## 一、当前基线

- [x] `python -m pytest -q -W error`：49 项测试全部通过。
- [x] `python -m compileall -q radar_tool tests`：编译检查通过。
- [x] `python -m pip check`：当前环境依赖关系正常。
- [x] `mypy --ignore-missing-imports radar_tool`：51 个源文件全部通过。
- [x] 未发现 `eval`、`exec`、`pickle`、`subprocess` 或网络访问等直接高危执行入口。

## 二、整改优先级

| 优先级 | 范围 | 完成标准 |
|---|---|---|
| P0 | 路径安全、配置完整性、资源限制、计算公式 | 阻断路径穿越和资源耗尽，关键公式有回归测试 |
| P1 | DOA 数值稳定性、依赖与 CI、错误处理 | 构建可复现，异常输入不会使界面崩溃 |
| P2 | 架构拆分、性能、打包和可维护性 | 核心服务可独立测试，启动与打包有冒烟测试 |

---

## 第一阶段：P0 数据安全与完整性

### 步骤 1：修复试验记录路径穿越

涉及文件：

- `radar_tool/exp_recorder.py`
- `tests/test_runtime_safety.py`

任务：

- [x] 项目、任务、记录 ID 只接受 UUID 或 `[A-Za-z0-9_-]`，禁止 `/`、`\`、`.` 和绝对路径。
- [x] `_image_storage_dir()` 在创建目录前将结果 `resolve()`，并确认位于 `IMAGES_DIR` 内。
- [x] JSON 中的图片路径只保存相对 `IMAGES_DIR` 的路径，不再持久化任意绝对路径。
- [x] 加载和导出图片前统一调用安全路径解析函数，拒绝越界路径、符号链接和特殊设备文件。
- [x] 复制图片前限制文件大小、图片像素数和支持的格式，并校验文件魔数。
- [x] 为 `experiments.json` 增加版本号和 Schema 校验。

验收测试：

- [x] ID 为 `../escape`、`..\\escape`、绝对路径时必须拒绝。
- [x] 图片路径指向 `IMAGES_DIR` 外部文件时必须拒绝。
- [x] 正常 UUID、相对图片路径和旧版记录仍可加载、保存、导出。


**步骤 1 修改结论（待架构师/测试工程师评审）：** 已集中校验项目、任务和记录 ID；图片目录创建前执行 resolve 与边界检查；JSON 仅持久化相对图片路径并自动迁移旧版安全绝对路径；加载/导出统一经过安全路径解析，拒绝越界、符号链接、特殊设备文件，并在复制前限制大小、像素数、格式和魔数；`experiments.json` 已增加 `schema_version=1` 与结构校验。验收测试与全量测试均通过：`python -m pytest -q -W error` → 59 passed；`python -m compileall -q radar_tool tests` → 通过；`python -m pip check` → 依赖关系正常。

### 步骤 2：修复配置损坏和数据丢失

涉及文件：

- `radar_tool/exp_recorder.py`
- `radar_tool/calibration_batch_store.py`

任务：

- [x] JSON 加载失败时将损坏文件重命名为 `.corrupt-<时间戳>`，不要静默保留后覆盖。
- [x] 每次成功保存前保留最近一次有效 `.bak`。
- [x] 对根节点、项目、任务、记录、步骤、图片执行完整类型和结构校验。
- [x] `CalibrationBatchStore._load()` 跳过非法单条配置并记录警告，不让整个校正页加载失败。
- [x] 校验配置 ID 唯一性、矩阵为有限数值、参数名称和数值类型正确。
- [x] JSON 文件增加最大大小和最大嵌套深度限制。

验收测试：

- [x] 损坏 JSON 后原文件仍可恢复。
- [x] 单条非法校正配置不会影响其他合法配置。
- [x] 连续保存、加载、更新不会产生数据丢失。


**步骤 2 修改结论（待架构师/测试工程师评审）：** 已为试验记录和校正配置 JSON 增加损坏文件 `.corrupt-<时间戳>` 隔离、有效 `.bak` 备份、文件大小与嵌套深度限制；试验记录执行根节点/项目/任务/记录/步骤/图片结构校验；`CalibrationBatchStore` 会逐条跳过非法或重复 ID 配置并记录警告，同时校验矩阵有限性、参数名称和数值类型。验收测试与全量测试均通过：`python -m pytest -q -W error` → 67 passed；`python -m compileall -q radar_tool tests` → 通过；`python -m pip check` → 依赖关系正常。

### 步骤 3：增加文件解析资源限制

涉及文件：

- `radar_tool/data_loader.py`
- `radar_tool/calibration_data_loader.py`
- `radar_tool/format_conversion.py`
- `radar_tool/format_conversion_panel.py`

任务：

- [x] 建立统一输入限制：文件大小、最大行数、最大列数、最大样本数、最大 BIN 帧数。
- [x] `load_tr_amplitude_phase_txt()` 和 `load_tr_amplitude_phase_bin()` 读取前先检查文件大小。
- [x] CSV、TXT、DAT、LOG 在读取前后验证行列数量。
- [x] Excel 读取限制工作表数量、行列数量和压缩包解压后总大小。
- [x] 大文件解析放入后台任务，支持取消和超时，禁止阻塞 Qt UI 线程。
- [x] 错误消息明确说明超限项和允许范围，不输出完整本地路径。

验收测试：

- [x] 超过大小、行数、列数限制的文件得到受控异常。
- [x] 超大 BIN、异常 XLSX 和密集文本不会造成无界内存增长。
- [x] 正常文件仍保持当前解析结果不变。

**步骤 3 修改结论（待架构师/测试工程师评审）：** 已新增统一输入资源限制模块，限制文件大小、文本/表格行列数、样本数、BIN 帧数、Excel 工作表数及解压总大小；TXT/CSV/DAT/LOG 和 Excel 均在读取前预检、读取后复核，TR 幅相 TXT/BIN 在读取前检查大小并支持解析控制；格式转换面板改为 QThread 后台解析，提供取消、超时和状态反馈，超限错误仅报告限制项与允许范围，不输出完整本地路径。验收测试覆盖超限文件、异常 XLSX、超大 BIN、后台取消/超时及正常解析回归。全量验证：`python -m pytest -q -W error` → 74 passed；`python -m compileall -q radar_tool tests` → 通过；`python -m pip check` → 依赖关系正常。

---

## 第二阶段：P0 工程计算正确性

### 步骤 4：修复链路预算

涉及文件：

- `radar_tool/calc_panel.py`

任务：

- [x] 增加码率 `Rb` 输入，不得固定 `Rb = B`。
- [x] 计算 `EbN0 = C/N - 10*log10(B/Rb)`。
- [x] 计算链路余量 `margin = EbN0 - EbN0_req`。
- [x] 验证频率、距离、带宽、码率必须大于零。
- [x] 核对输入单位与 dBm、dBW、Hz、bps 的换算。

验收测试：

- [x] 使用手算链路预算样例验证 `Pr`、`Pn`、`C/N`、`Eb/N0` 和余量。
- [x] `B != Rb` 时结果不能退化为 `Eb/N0 = C/N`。

**步骤 4 修改结论（待架构师/测试工程师评审）：** 已在链路预算界面新增独立码率 `Rb` 输入（bps），按 Hz/MHz、km、GHz 和 dBm/dBW 单位显式换算；实现 `Eb/N0 = C/N - 10*log10(B/Rb)` 与 `margin = Eb/N0 - EbN0_req`，并校验频率、距离、带宽、码率必须为有限正数，错误信息说明允许范围。结果同时展示 Pr/Pn 的 dBm 与 dBW、频率/带宽 Hz、码率 bps 及链路余量。验收测试覆盖手算样例、`B != Rb` 不退化、`B == Rb` 保持 C/N，以及非正输入拒绝。全量验证：`python -m pytest -q -W error` → 77 passed；`python -m compileall -q radar_tool tests` → 通过；`python -m pip check` → 依赖关系正常。

### 步骤 5：修复测向精度公式

涉及文件：

- `radar_tool/calc_panel.py`

任务：

- [x] 干涉仪误差公式加入 `cos(theta)` 项，与界面展示公式保持一致。
- [x] 限制来波方向为 `-90 < theta < 90`，接近正侧射时给出奇异或高误差提示。
- [x] 明确 MUSIC 精度模型的适用条件，避免直接把阵元数作为无条件开根号增益。
- [x] 对 CRB 和理论 RMSE 的单位、快拍数和 SNR 定义补充公式说明。

验收测试：

- [x] `theta = 0` 时与现有结果一致。
- [x] `theta` 接近 90 度时误差按理论发散。
- [x] 负角度和超范围角度行为明确。

**步骤 5 修改结论（待架构师/测试工程师评审）：** 已将干涉仪误差公式改为包含 `cos(theta)` 的形式，并严格限制 `-90° < theta < 90°`；接近正侧射时输出奇异/高误差提示，负角度按偶对称公式计算，超范围角度明确拒绝。MUSIC 仅在阵元数、快拍数（K≥2N）、SNR（≥0 dB）等条件满足时施加 √N 近似增益，否则显示不适用且不作无条件阵元数增益。CRB 以 rad² 计算并换算为角度 RMSE（°），结果补充 SNR 线性定义、快拍数 K 和单位说明。验收测试覆盖 theta=0 回归、接近 90° 发散、负角度/超范围行为及 MUSIC 条件。全量验证：`python -m pytest -q -W error` → 82 passed；`python -m compileall -q radar_tool tests` → 通过；`python -m pip check` → 依赖关系正常。

### 步骤 6：修复阵列设计计算

涉及文件：

- `radar_tool/array_designer.py`
- `radar_tool/calc_panel.py`

任务：

- [x] `_calc_pattern()` 纳入 `elem['phase']`。
- [x] 自定义阵元的幅度、相位修改后立即反映到方向图和指标。
- [x] 副瓣搜索覆盖主瓣左右两侧，并正确识别主瓣边界。
- [x] ULA、矩形面阵、UCA 使用各自适用的孔径、波束宽度和栅瓣公式。
- [x] 自定义阵列至少包含两个有效阵元，所有坐标、幅度和相位必须有限。
- [x] 补充 UCA 半径、矩形面阵行列数及两个方向间距输入。

验收测试：

- [x] 固定相位偏移会产生可预测的波束偏移。
- [x] 对称阵列的左右副瓣均被统计。
- [x] UCA 和矩形面阵不再输出纯 ULA 公式结果。

**步骤 6 修改结论（待架构师/测试工程师评审）：** 已在阵列方向图中纳入阵元相位，表格和自定义对话框支持幅度/相位编辑并即时刷新方向图与指标；主瓣按 -3dB 连续区域确定边界，左右副瓣分别搜索并返回左右电平；ULA、矩形面阵和 UCA 分别使用线阵、行列双向和半径相关孔径/波束宽度/栅瓣公式；自定义阵列强制至少两个有效阵元且坐标、幅度、相位必须有限且幅度非零。界面新增 UCA 半径、矩形面阵行列数及 X/Y 两个方向间距输入。验收测试覆盖固定相位波束偏移、左右副瓣、UCA/RECT 公式区分、表格即时更新和自定义输入校验。全量验证：`python -m pytest -q -W error` → 92 passed；`python -m compileall -q radar_tool tests` → 通过；`python -m pip check` → 依赖关系正常。

### 步骤 7：修复单位换算和输入域

涉及文件：

- `radar_tool/calc_panel.py`

任务：

- [x] 补齐 `rad ↔ mrad` 换算。
- [x] 倍数转 dB 时禁止倍数小于等于零，不返回误导性的 `0 dB`。
- [x] 频率、波长、功率、带宽、距离、RCS 等参数按物理意义验证输入域。
- [x] 所有计算回调捕获领域异常，显示明确错误，不产生未处理异常。
- [x] 为温度、角度、功率、频率建立独立的纯函数计算器，UI 只负责取值和展示。

验收测试：

- [x] 所有单位组合进行正反换算一致性测试。
- [x] 零、负数、NaN、无穷输入得到明确拒绝。

**步骤 7 修改结论（待架构师/测试工程师评审）：** 已补齐 rad↔mrad 及所有频率/波长、功率、角度、增益、温度、长度单位组合的纯函数换算；倍数转 dB 强制要求倍数大于 0，不再返回误导性的 0 dB；频率、波长、线性功率、带宽、距离、RCS、温度等按物理意义校验有限性与正值域，角度允许合法负值但拒绝 NaN/无穷。单位转换、天线增益、作用距离、链路预算、测向、阵列和信噪比回调均捕获领域异常并显示明确错误。验收测试覆盖所有单位组合正反换算、零/负数/NaN/无穷输入拒绝及 UI 错误展示。全量验证：`python -m pytest -q -W error` → 97 passed；`python -m compileall -q radar_tool tests` → 通过；`python -m pip check` → 依赖关系正常。

---

## 第三阶段：P1 数值算法与依赖

### 步骤 8：加固 DOA 算法

涉及文件：

- `radar_tool/algorithms/doa_estimation.py`
- `radar_tool/algorithms/array_geometry.py`

任务：

- [x] Hermitian 协方差矩阵使用 `np.linalg.eigh`，替代 `np.linalg.eig`。
- [x] 验证阵元坐标、快拍矩阵、信号数和扫描范围。
- [x] MUSIC 要求 `0 < N_signals < N_ant`，并对零噪声子空间给出明确异常。
- [x] ESPRIT 对 `arcsin` 参数裁剪或明确报告不可解，不产生 NaN。
- [x] 扫描步长必须大于零，范围起点不得大于终点。
- [x] 为随机阵列误差、初始相位、噪声和 Monte Carlo 增加 `seed` 参数。
- [x] Monte Carlo 少于两个样本时不使用 `ddof=1`。
- [x] 统一光速常量并明确单位。

验收测试：

- [x] 单源、双源、低 SNR、相关源和奇异阵列均有基准测试。
- [x] 相同随机种子结果完全可复现。
- [x] ESPRIT 超出可见范围时返回可解释结果，不返回 NaN。

**步骤 8 修改结论（待架构师/测试工程师评审）：** 已将 Hermitian 协方差特征分解切换为 `np.linalg.eigh`，补齐阵元坐标、快拍矩阵、信号数、扫描范围与奇异重复阵元校验；MUSIC 严格要求 `0 < N_signals < N_ant` 并对零噪声子空间抛出明确异常，ESPRIT 对超出可见范围的 `arcsin` 参数进行边界裁剪并保证有限输出。扫描步长强制大于 0、起点不得大于终点，阵列误差、初始相位、噪声和 Monte Carlo 统一使用可复现`seed`，单样本 Monte Carlo 使用 `ddof=0`，光速统一为带米/秒单位说明的 `SPEED_OF_LIGHT_M_PER_S`。新增测试覆盖单源、双源、低 SNR、相关源、奇异阵列、同种子完全复现和 ESPRIT 越界裁剪。全量验证：`python -m pytest -q -W error` → 116 passed；`python -m compileall -q radar_tool tests` → 通过；`python -m pip check` → 依赖关系正常。

### 步骤 9：统一输入 Schema 和错误模型

涉及文件：

- `radar_tool/models.py`
- 各数据加载、配置和导出模块

任务：

- [x] 定义项目记录、校正配置、真值复核配置的数据类或显式 Schema。
- [x] 定义统一的 `ValidationError`、`DataLimitError`、`ExportError`。
- [x] UI 只捕获领域异常，其他异常记录完整堆栈并进入统一错误页面。
- [x] JSON Schema 带 `schema_version`，提供逐版本迁移函数。
- [x] 不在异常框和日志中暴露完整敏感路径或原始数据。

**步骤 9 修改结论（待架构师/测试工程师评审）：** 已在 `radar_tool/schemas.py` 定义项目记录、校正配置和真值复核配置的显式 dataclass Schema，并在 `models.py` 统一导出；新增 `ValidationError`、`DataLimitError`、`ExportError` 领域异常层级，输入限制和格式转换异常已纳入统一模型。项目、校正和真值复核 JSON 文档均使用 `schema_version=1`，提供旧版项目映射、`version` 校正配置和无版本真值配置的逐版本迁移函数。UI 统一异常入口对领域异常显示安全文本，对未预期异常记录脱敏后的完整堆栈并进入统一错误页面；日志格式化器统一隐藏绝对路径和原始数值序列，成功/失败提示不再展示完整敏感路径。新增 Schema、迁移、异常层级、脱敏和统一错误页面测试。全量验证：`python -m pytest -q -W error` → 127 passed；`python -m compileall -q radar_tool tests` → 通过；`python -m pip check` → 依赖关系正常。

### 步骤 10：完善依赖与供应链基线

涉及文件：

- `requirements.txt`
- `requirements-dev.txt`
- `.github/workflows/tests.yml`

任务：

- [x] 新增 `pyproject.toml`，声明 Python 版本、包入口和开发工具配置。
- [x] 明确支持 Python 3.8 还是升级到 3.10+，README、CI 和依赖版本保持一致。
- [x] 生成锁定依赖文件并记录哈希。
- [x] 为 `.xls` 增加 `xlrd`，或从文档和过滤器中移除 `.xls` 支持。
- [x] CI 增加 Ruff、mypy、`pip-audit`、依赖锁定检查。
- [x] GitHub Actions 固定到提交 SHA，并设置 `permissions: contents: read`。

**步骤 10 修改结论（待架构师/测试工程师评审）：** 新增 `pyproject.toml`，声明包入口 `portable-radar-toolbox`、setuptools 包发现及 Ruff/mypy/pytest 工具配置；README、`requirements.txt` 和 CI 保持统一的 Python 最低版本，CI 矩阵验证当前支持版本。运行依赖增加 `.xls` 所需 `xlrd>=2.0.1,<3`，并维护精确版本 `requirements.lock`；`requirements.lock.sha256` 记录锁定文件 SHA256，`scripts/verify_lock_hash.py` 在 CI 中校验哈希及精确 pin。GitHub Actions 的 checkout/setup-python 均固定到提交 SHA，并设置 `permissions: contents: read`；CI 增加 Ruff、mypy、pip-audit、锁定检查和严格 pytest。步骤 14 的安全扫描要求 Pillow 和 fonttools 的修复版本不再支持 Python 3.8，因此当前最低版本已提升为 Python 3.11，并同步更新依赖、README、CI 和锁定文件。

---

## 第四阶段：P2 架构与体验

### 步骤 11：拆分大型模块

建议拆分：

- [x] `compare_analysis.py`：数据加载、预处理、对齐、统计、绘图、导出分离。
- [x] `exp_recorder.py`：记录 Schema、仓储、图片管理、Word 导出、UI 分离。
- [x] `interferometer_sim.py`：仿真服务、Monte Carlo、结果模型、绘图、UI 分离。
- [x] `calc_panel.py`：纯计算函数、单位定义、UI 控件分离。

**步骤 11 修改结论（待架构师/测试工程师评审）：** 已完成四个大型模块的职责拆分：`calc_panel.py` 拆为单位换算、公式计算和 UI 控件模块；`exp_recorder.py` 拆为存储、图片、Schema、Word 导出和兼容 UI 门面；`compare_analysis.py` 拆为核心算法、数据、Worker、绘图和导出 mixins，并保留原兼容导出；`interferometer_sim.py` 拆为仿真服务、绘图 mixins、结果格式化 mixins 和兼容 UI 门面。所有原公开名称继续可导入，后台 Worker 与 UI 解耦。全量验证：`python -m compileall -q radar_tool tests scripts` → 通过；`python -m pytest -q -W error` → 127 passed；`python -m pip check` → 依赖关系正常。

### 步骤 12：统一后台任务管理

涉及文件：

- `radar_tool/main_window.py`
- 各后台任务模块

任务：

- [x] 建立统一任务注册表，替代按 `_thread` 后缀扫描对象属性。
- [x] 每个任务提供开始、进度、成功、失败、取消和完成状态。
- [x] 窗口关闭时执行有界等待，并明确展示任务名称和取消状态。
- [x] 文件加载、计算、绘图数据准备和导出逐步移出 UI 线程。
- [x] 同一任务禁止重复启动，旧结果带版本号，过期结果自动丢弃。

**步骤 12 修改结论（待架构师/测试工程师评审）：** 新增 `background_tasks.py` 统一注册表，按顶层窗口管理任务，提供开始、进度、成功、失败、取消请求、取消和完成信号；主窗口不再扫描 `_thread` 属性，关闭前统一请求取消并执行 3 秒有界等待，对话框展示任务名称与最终取消状态。格式解析、测向校正、真值复核、DOA/Monte Carlo 仿真、文件加载和高清图导出均已登记；文件解析、计算、绘图数据准备和图片编码移出 UI 线程。注册表为同名任务增加启动前重复检查、递增版本号和 stale 标记，各结果处理器校验当前版本后才更新 UI。全量验证：`python -m compileall -q radar_tool tests scripts` → 通过；`python -m pytest -q -W error` → 131 passed；`python -m pip check` → 依赖关系正常；`git diff --check` → 通过。

### 步骤 13：完善导出可靠性

涉及文件：

- `radar_tool/calibration_panel.py`
- `radar_tool/compare_export.py`
- `radar_tool/experiment_word_export.py`
- `radar_tool/export_safety.py`

任务：

- [x] 多文件导出先写临时批次目录，全部成功后原子重命名。
- [x] 导出失败清理临时文件，并明确指出已生成的残留文件。
- [x] CSV 中由用户控制且以 `=`, `+`, `-`, `@` 开头的文本进行公式注入转义。
- [x] 导出文件包含版本、输入摘要、参数和生成时间，支持追溯。
- [x] Word 导出只允许应用管理目录内的图片，不允许从 JSON 任意绝对路径读取。

**步骤 13 修改结论（待架构师/测试工程师评审）：** 新增 `export_safety.py`，提供同父目录临时批次写入、成功后 `os.replace()` 原子发布、失败自动清理，以及清理失败时列明残留相对文件的 `BatchExportError`；CSV 导出统一转义表头和字符串单元格中的 `=`、`+`、`-`、`@` 前缀，数值负号保持不变；元数据统一包含应用版本 `1.0.0`、导出 Schema 版本、ISO 生成时间、输入摘要和参数。真值复核与测向校正的 JSON、CSV、PNG 均改为批次原子导出，并写入 `00_导出元数据.json`，主配置 JSON 同时嵌入相同元数据。Word 报告尾注加入版本、输入摘要和参数，图片解析显式使用延迟加载的安全解析器，仅接受应用图片目录内且不含符号链接的路径，避免循环导入。全量验证：`python -m pytest -q -W error --basetemp=.pytest_tmp_step13` → 138 passed；`python -m compileall -q radar_tool tests scripts` → 通过；`python -m pip check` → 依赖关系正常；`git diff --check` → 通过。

### 步骤 14：补充测试和质量门槛

优先新增测试：

- [x] 路径穿越和恶意图片路径测试。
- [x] 损坏 JSON、备份恢复和 Schema 迁移测试。
- [x] 大文件、异常 XLSX、BIN 边界和模糊解析测试。
- [x] 所有计算器的公式基准测试。
- [x] DOA、阵列方向图和 Monte Carlo 数值测试。
- [x] 所有 Qt 面板的离屏初始化与关键交互测试。
- [x] 打包产物启动、资源加载和用户数据目录测试。

CI 质量门槛：

- [x] 测试通过率 100%。
- [x] Ruff 无错误。
- [x] mypy 对核心计算和数据模块无错误。
- [x] `pip-audit` 无未处理高危漏洞。
- [x] 打包冒烟测试通过。

**步骤 14 修改结论（待架构师/测试工程师评审）：** 新增确定性损坏 XLSX、大文件边界、BIN 截断与随机损坏语料测试；补充全部 Qt 面板离屏初始化和计算器导航、游戏重置、仿真清除、记录保存等关键交互；新增打包运行路径、图标资源、隔离用户数据目录及全部延迟页签冒烟测试。路径穿越、恶意图片、损坏 JSON、备份恢复、Schema 迁移、公式基准、DOA、阵列方向图和 Monte Carlo 回归由既有专项测试持续覆盖。由于 Pillow 10.4 和 fonttools 4.57 的安全修复版本要求更高 Python，当前最低版本调整为 Python 3.11，README、`pyproject.toml`、`requirements.txt`、CI 矩阵和精确锁文件保持一致；锁文件更新后 `pip-audit` 报告 `No known vulnerabilities found`。CI 将 Ruff、核心 mypy、pip-audit、严格 pytest 和应用冒烟全部设为失败即阻断。全量验证：`python -m pytest -q -W error --basetemp=.pytest_tmp_step14_full` → 153 passed；`python -m radar_tool.run --smoke-test` → 通过；`ruff check --select E9,F63,F7,F82 radar_tool tests` → All checks passed；核心 mypy → 14 个源文件无错误；`pip-audit -r requirements.lock --no-deps --disable-pip` → No known vulnerabilities found；`python scripts/verify_lock_hash.py`、`python -m compileall -q radar_tool tests scripts`、`python -m pip check`、`git diff --check` → 通过。

### 步骤 15：固化 Nuitka 发布链路（后置执行）

涉及文件：

- `packaging/nuitka/build.ps1`
- `requirements-build.lock`
- 发布 CI 工作流

执行门槛：

- [x] 步骤 1 至 9 的安全、数据和计算验收测试全部通过。
- [x] 步骤 10 至 14 的依赖、质量门槛和核心回归测试全部通过。
- [x] 正式发布仅由稳定标签或人工显式触发，且测试、类型检查、依赖审计和打包冒烟失败即阻断。

任务：

- [x] 完全移除旧打包配置、命令和构建目录说明。
- [x] 主打包技术确定为 Nuitka `standalone`，使用目录型发布物，不使用 `onefile`。
- [x] 固定 Nuitka、编译器和 Python 版本，构建环境必须从锁定依赖重建。
- [x] 构建脚本显式收集 PyQt5、matplotlib、openpyxl 和 python-docx 的运行时数据与插件。
- [x] 发布前对主可执行文件和发布目录进行代码签名。
- [x] 增加可复现构建、版本元数据、构建日志和产物哈希。
- [x] 对打包产物执行安装、离线启动、页签初始化、用户数据目录和退出冒烟测试。
- [x] 检查 Qt 插件、字体、图标、Excel 引擎和 `python-docx` 是否完整包含。
- [x] 生成第三方组件清单和 SBOM，并执行恶意软件扫描。

**步骤 15 修改结论：** 构建链路固定为 Python 3.12.7、MSVC 14.3 和 Nuitka 4.1.3，运行时与构建工具分别由 `requirements.lock`、`requirements-build.lock` 及 SHA256 锁文件约束。`packaging/nuitka/build.ps1` 修正项目根目录计算，强制依赖版本检查，使用 Nuitka `standalone` 显式收集 PyQt5、matplotlib、openpyxl、python-docx、xlrd 及其运行时资源，并写入 Windows 版本元数据。正式构建对发布目录内所有 EXE/DLL/PYD 执行 Authenticode 签名和验证；生成确定性 ZIP、独立 SHA256、逐文件构建清单、CycloneDX SBOM 与第三方组件清单。`verify_release.ps1` 将发布目录复制到隔离安装位置，执行离线 `--smoke-test`，覆盖全部页签、用户数据目录、Qt 平台插件、matplotlib 字体、图标、Excel 与 Word 能力。`.github/workflows/release.yml` 仅在 `v*` 标签或人工触发时构建，要求签名密钥，执行 Windows Defender 扫描并发布签名产物。为修复复核发现的问题，`runtime_paths.py` 进一步拒绝路径分隔符、绝对路径、`..` 和符号链接逃逸；Word 导出的可选依赖回退改为类型安全实现，全量 mypy 由 18 个错误降至 0。

### 步骤 16：建立可执行的打包发布操作流程（待执行）

本步骤不是更换打包工具，而是把已经固化的 Nuitka 链路转化为发布工程师可以逐项执行、复核和留档的标准流程。目标是让“源码提交 → 构建候选包 → 签名 → 隔离验证 → 发布 → 回滚”形成闭环。

完成标准：

- [ ] 从全新 Windows 构建机或 CI 环境可重复生成目录型 Windows x64 发布包。
- [ ] 版本号、Git 标签、EXE 文件元数据、ZIP 文件名和发布标题一致。
- [ ] 正式产物全部通过 Authenticode、SHA256、SBOM、构建清单和恶意软件扫描。
- [ ] ZIP 解压后能在无 Python、无网络环境中启动并完成应用冒烟测试。
- [ ] 发布记录能够追溯到源码提交、构建环境、测试结果、签名证书和产物哈希。
- [ ] 未签名或仅用于本地验证的产物不会进入 GitHub Release 或对外分发目录。

#### 16.1 构建前置条件

| 项目 | 固定要求 | 检查方式 |
|---|---|---|
| 操作系统 | Windows 10/11 或 Windows Server，x64 | 构建机信息留档 |
| Python | CPython 3.12.7，64 位 | `build-environment.json` 与解释器输出一致 |
| 编译器 | MSVC 14.3 和 Windows SDK | Nuitka 能找到 `cl.exe`、`signtool.exe` |
| Nuitka | 4.1.3 | `python -m nuitka --version` |
| 代码签名 | 正式发布必须使用有效 Authenticode 证书 | `Get-AuthenticodeSignature` 返回 `Valid` |
| GitHub Secrets | `WINDOWS_CERTIFICATE_BASE64`、`WINDOWS_CERTIFICATE_PASSWORD` | 先通过手工 workflow 验证 |
| 源码状态 | 发布必须来自干净、已评审的提交 | `git status --short` 为空 |
| 发布资料 | 版本说明、已知问题、升级/兼容说明 | 发布负责人签字确认 |

构建机必须具备 MSVC Build Tools、Windows SDK 和可用的 `signtool.exe`。若证书安装在 Windows 证书存储中，本地构建优先使用证书 SHA1 指纹；PFX 和密码只在 GitHub Actions 的临时目录中使用，不写入仓库、构建脚本参数记录或普通环境文件。

#### 16.2 确定版本和冻结发布内容

1. 选择语义化版本 `X.Y.Z`，确认是否包含破坏性变更、数据格式迁移或依赖升级。
2. 检查目标提交的 Git 状态和差异；发布候选不得包含未评审的本地修改。
3. 当前版本号仍分散在以下位置，发版时必须同步检查：
   - `pyproject.toml`
   - `build-environment.json`
   - `radar_tool/__init__.py`
   - `radar_tool/export_safety.py`
   - `radar_tool/main_window.py`
   - `README.md`
   - `packaging/nuitka/build.ps1`
   - `.github/workflows/release.yml`
4. 更新版本说明，至少记录新增功能、缺陷修复、数据兼容性、依赖变化、已知问题和升级注意事项。
5. 确认 `requirements.lock`、`requirements-build.lock` 及两个 SHA256 文件属于同一提交，不在发版当天临时升级依赖。
6. 在发布评审记录中写明版本号、提交 SHA、负责人、测试负责人和目标发布时间。

发布前执行：

```powershell
git status --short
git diff --check
git rev-parse HEAD
python scripts\verify_lock_hash.py
```

预期结果：工作区无未提交修改，差异检查无空白错误，锁文件哈希校验通过，并记录完整提交 SHA。

#### 16.3 重建锁定构建环境

构建环境不得直接复用日常开发环境。建议创建独立虚拟环境，并使用构建机上明确的 Python 3.12.7 路径：

```powershell
$Python = "C:\Python3127\python.exe"
& $Python -m venv .venv-build
& .venv-build\Scripts\python.exe -m pip install --upgrade pip
& .venv-build\Scripts\python.exe -m pip install --no-deps -r requirements.lock
& .venv-build\Scripts\python.exe -m pip install --no-deps -r requirements-build.lock
& .venv-build\Scripts\python.exe -m pip install -r requirements-dev.txt
& .venv-build\Scripts\python.exe -m pip check
& .venv-build\Scripts\python.exe -c "import platform; print(platform.python_version(), platform.architecture()[0])"
```

最后一条命令必须输出 `3.12.7 64bit`。如果 Python、Nuitka 或依赖版本不一致，应删除并重建构建环境，禁止通过临时升级或降低版本绕过构建脚本检查。

#### 16.4 发布前质量门禁

按以下顺序执行，任何一步失败均停止打包：

```powershell
$Python = ".venv-build\Scripts\python.exe"
& $Python scripts\verify_lock_hash.py
& $Python -m pip check
& $Python -m compileall -q radar_tool tests scripts
& $Python -m ruff check --select E9,F63,F7,F82 radar_tool tests
& $Python -m mypy --ignore-missing-imports radar_tool
& $Python -m pip_audit -r requirements.lock --no-deps --disable-pip
$env:QT_QPA_PLATFORM = "offscreen"
& $Python -m pytest -q -W error
& $Python -m radar_tool.run --smoke-test
```

质量记录至少保存命令、开始/结束时间、提交 SHA、测试数量、失败项和执行人。对于业务数据正确性、Excel/Word 导出和错误编号诊断，除自动测试外还应使用约定的黄金样本执行一次人工复核。

#### 16.5 本地未签名候选构建

仅用于验证构建链路，不产生可发布产物：

```powershell
.\packaging\nuitka\build.ps1 `
  -Python .venv-build\Scripts\python.exe `
  -Version "X.Y.Z" `
  -AllowUnsigned
```

如果质量门禁刚刚由同一构建脚本负责执行，可增加 `-SkipTests`；其他情况下不要跳过测试。禁止使用 `-AllowUnsigned` 生成对外安装包、网盘附件、客户交付包或 GitHub Release 资产。

构建脚本会清理并重建 `artifacts\nuitka`，并生成：

- `artifacts\nuitka\compile\`：Nuitka 中间构建目录。
- `artifacts\nuitka\release\`：已验证的目录型发布内容。
- `artifacts\nuitka\PortableRadarToolbox-X.Y.Z-win64.zip`：确定性压缩包。
- `artifacts\nuitka\PortableRadarToolbox-X.Y.Z-win64.zip.sha256`：压缩包 SHA256。
- `artifacts\nuitka\build-*.log`：构建日志。
- 发布目录中的 `build-manifest.json`、`sbom.cdx.json` 和 `third-party-components.json`。

#### 16.6 正式签名构建

本地持有已安装证书时使用证书 SHA1 指纹：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\packaging\nuitka\build.ps1 `
  -Python .venv-build\Scripts\python.exe `
  -Version "X.Y.Z" `
  -CertificateThumbprint "<证书SHA1指纹>"
```

正式构建不得同时传入 `-AllowUnsigned`。构建脚本会递归签名发布目录中的 `.exe`、`.dll`、`.pyd`，随后逐文件验证 Authenticode。证书密码不直接出现在 PowerShell 历史记录中；如必须使用 PFX，应通过受限变量注入，并在构建结束后清理临时证书文件。

签名完成后的基础复核：

```powershell
.\packaging\nuitka\verify_release.ps1 `
  -DistributionRoot .\artifacts\nuitka\release `
  -RequireSignature

Get-FileHash `
  .\artifacts\nuitka\PortableRadarToolbox-X.Y.Z-win64.zip `
  -Algorithm SHA256

Get-AuthenticodeSignature `
  .\artifacts\nuitka\release\PortableRadarToolbox.exe
```

`verify_release.ps1` 必须检查主程序、图标、PyQt5 平台插件、matplotlib 字体、Excel/Word 运行时、发布元数据和隔离启动冒烟。校验结果写入发布记录，不只保留在终端输出中。

#### 16.7 压缩包与隔离安装验收

不要直接分发 `release` 目录。使用构建脚本生成的 ZIP，在一台未安装 Python、未安装项目依赖的 Windows 测试机上执行：

1. 校验 ZIP 的 SHA256 与 `.sha256` 文件一致。
2. 将 ZIP 解压到包含空格和中文字符的普通用户目录，禁止直接从网络共享或压缩软件虚拟目录启动。
3. 运行 `PortableRadarToolbox.exe --smoke-test`，确认退出码为 0。
4. 启动 GUI，逐个打开全部页签，执行数据加载、绘图、格式转换、试验记录和导出操作。
5. 分别验证 UTF-8、GB18030、TXT/CSV/DAT、XLSX/XLS 黄金样本和中文文件名。
6. 确认应用只在 `%APPDATA%\PortableRadarToolbox` 创建用户数据，不在安装目录写入日志、缓存或业务数据。
7. 断网后再次启动，确认不会因缺少网络、Python、Office 或字体环境而崩溃。
8. 检查所有 EXE/DLL/PYD 签名，并使用 Windows Defender 或企业杀毒系统扫描整个解压目录。
9. 检查 `build-manifest.json`、`sbom.cdx.json`、`third-party-components.json` 可读取且与本次版本一致。
10. 卸载/删除测试目录，确认业务数据不会随程序目录删除，用户数据按既定备份策略保留。

验收通过后，将测试机系统版本、安装路径类型、测试样本清单、截图或录屏、签名结果、扫描结果和缺陷单编号归档。

#### 16.8 GitHub Actions 发布

正式发布优先使用 `.github/workflows/release.yml`，避免本地构建机差异：

1. 在 GitHub 仓库配置 `WINDOWS_CERTIFICATE_BASE64` 和 `WINDOWS_CERTIFICATE_PASSWORD`，限制为部署环境或受保护密钥。
2. 确认 workflow 中 Python、应用版本和产物文件名与本次发布一致。
3. 创建与应用版本完全一致的标签，例如 `vX.Y.Z`。
4. 推送标签后观察 `windows-release` job；也可以先通过 `workflow_dispatch` 做受控试跑。
5. CI 必须依次通过锁定依赖检查、质量门禁、签名构建、Defender 扫描、构建记录上传和 Release 发布。
6. 对 GitHub Release 资产再次下载、校验 SHA256、检查签名并执行隔离冒烟，不能只验证 CI 工作目录中的文件。
7. 发布说明引用版本变更、构建清单、SBOM、已知问题和校验方法。

示例：

```powershell
$Version = "X.Y.Z"
$Tag = "v$Version"
git status --short
git tag -a $Tag -m "Portable Radar Toolbox $Tag"
git push origin $Tag
```

若 workflow 失败，保留 Job URL、失败步骤、构建日志和 runner 版本。修复必须形成新的提交和新的发布候选，不覆盖或复用旧 ZIP。

#### 16.9 发布后核验与留档

| 核验项 | 验收结果 |
|---|---|
| 标签、版本、ZIP 文件名一致 | 必须通过 |
| ZIP SHA256 与发布页一致 | 必须通过 |
| 主程序及 PE 依赖签名有效 | 必须通过 |
| Defender/企业杀毒扫描无告警 | 必须通过 |
| 干净 Windows 离线启动成功 | 必须通过 |
| 全部页签和黄金样本回归通过 | 必须通过 |
| SBOM、第三方清单、构建清单完整 | 必须通过 |
| 升级安装和旧用户数据兼容验证 | 按版本范围执行 |
| 发布说明、已知问题、回滚方案完整 | 必须通过 |

发布记录至少保存：Git 标签和提交 SHA、源码摘要、Python/MSVC/Nuitka 版本、构建 Runner、开始/结束时间、测试报告、签名证书主体和指纹、恶意软件扫描结果、ZIP SHA256、SBOM、构建清单、Job URL、发布负责人和审批人。

#### 16.10 回滚与问题响应

- 发现严重缺陷时立即撤下或标记问题版本，保留原始 ZIP、SHA256 和日志供调查。
- 回滚使用上一已验证版本及其独立校验文件，不重新压缩旧发布目录。
- 数据格式升级前必须验证降级路径；不能安全降级时，在发布说明中明确要求先备份用户数据。
- 运行时错误使用界面错误编号关联脱敏日志，调查日志中的真实异常类型和堆栈，不用二次包装后的文本猜测根因。
- 若安全工具误报，保留哈希、签名和扫描报告并向供应商申诉；申诉期间不绕过扫描发布。

#### 16.11 后续固化建议

- [ ] 将版本号收敛为 `radar_tool.__version__` 单一来源，构建脚本和 workflow 从该来源生成版本与产物名。
- [ ] 发布 workflow 从标签动态提取 `X.Y.Z`，校验标签、`pyproject.toml` 和 EXE 元数据一致，禁止硬编码 `1.0.0`。
- [ ] ZIP 生成后再次解压到临时目录执行 `verify_release.ps1`，避免只验证压缩前的目录。
- [ ] 为构建产物增加 GitHub Artifact Attestation 或等价的 SLSA provenance。
- [ ] 在两台独立构建机执行候选构建，并比较源码摘要、依赖清单、文件清单和测试结果；只有满足既定容差后才宣称可复现。
- [ ] 将黄金样本、人工验收结果和错误诊断用例纳入版本化发布资料。
- [ ] 为证书到期、GitHub Secrets 轮换、Python/Nuitka 升级和安全漏洞修复建立日历提醒。
- [ ] 增加发布演练标签和回滚演练，至少每季度验证一次。

#### 16.12 发布工程师最终清单

- [ ] 发布内容和版本号已冻结，工作区干净。
- [ ] 锁文件、依赖审计、静态检查、全量测试和源码冒烟通过。
- [ ] 使用独立构建环境和固定工具链完成正式签名构建。
- [ ] Authenticode、ZIP SHA256、SBOM、构建清单和恶意软件扫描通过。
- [ ] 在干净、离线 Windows 环境中通过压缩包安装和功能验收。
- [ ] GitHub Release 资产下载后二次验证通过。
- [ ] 发布说明、已知问题、升级说明和回滚方案已审批。
- [ ] 发布记录、构建日志和测试证据已归档。

---

## 推荐实施顺序

1. 路径穿越、图片路径隔离、JSON Schema 和配置备份。
2. 文件大小、行列数和解析资源限制。
3. 链路预算、测向精度、阵列设计和单位换算公式修正。
4. DOA 输入校验、`eigh`、随机种子和边界处理。
5. 依赖锁定、CI、安全扫描和核心质量门槛。
6. 大模块拆分、统一任务管理、导出事务化和完整回归测试。
7. 核心版本稳定后，执行步骤 15，固化 Nuitka 发布链路。
8. 按步骤 16 执行候选构建、签名、隔离验收和正式发布，并完成发布后留档。

每完成一个步骤，应同时完成对应验收测试并更新本文件的勾选状态。
