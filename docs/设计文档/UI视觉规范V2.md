# 便携化工具箱 · UI 视觉规范 V2

> 适用范围：`radar_tool` 全部 9 个功能页签 + 主窗口外壳
> 技术约束：PyQt5 5.15 / `QSS` / Fusion 风格 / matplotlib 嵌入图 / 最小窗口 1024×640 / 仅浅色主题
> 本文档只定义视觉，不改任何 `.py` 逻辑。代码落地由工程实现方按 §8 迁移映射表机械替换。
> 版式基准：1440×900 排版，1024×640 下不得出现横向滚动。

---

## 0. 一句话设计方向

**仪器面板，不是 SaaS 仪表盘。**

冷灰蓝的低饱和主色 + 1px 发丝描边 + 等宽数字，把视觉噪声全部让给数据本身。
三个可量化的判定标准：任意截图缩到 50% 后仍能看出「哪块是表单、哪块是结果、哪块是图」；任意页面内的颜色总数 ≤ 12；模糊掉文字后仅凭灰阶层次仍能读出信息结构。

---

## 1. 现状诊断（截图事实 → 结论）

| 现象（09 张截图为证） | 结论 |
|---|---|
| 9 个页签在 1560px 宽下已出现左右滚动箭头，「试验记…」被截断；emoji 只出现在 4 个页签上 | 页签即产品骨架，它塌了整个界面就塌了。emoji 混入是页签超宽的元凶之一（9 个 emoji ≈ 160px） |
| 可视化页按钮为 `#4CAF50 / #2196F3 / #FF9800` 三原色；指标计算器为 `#2563eb→#1d4ed8` 渐变 + 2px 描边；校准页 KPI 卡为第三套 | 同一产品三套视觉语法，用户读到的是「三个团队拼的东西」 |
| 06 页 4 个 KPI 空卡只有 `--`，卡片比内容大 3 倍 | 缺「空态」规范，空态被当成默认态 |
| 07 页欢迎区大面积文字互相叠压、内容几乎不可读；浅蓝底与其他页不通 | 存在未经设计稿约束的自由布局，必须用组件规范封死 |
| 00 页「保存范围预…」按钮被压字；02/04 页 matplotlib 中文标题渲染为 □□□□ | 两类硬缺陷：布局溢出 + 中文字体族未声明 |
| 04 页表格列宽不足，单元格显示 `0...`；08 页表头压在组框边框上 | 表格需要最小列宽 + 表头与容器间距规则 |
| 1560px 下 QComboBox 拉满 >800px，输入框高 28px 与页签、按钮尺度不协调 | 表单需要栅格 + 控件最大宽度 |
| `array_designer.py:766` 用**等宽字符填充**凑表格：`f'{"指标":<16} {"数值":>10} {"说明":<28}'` + `f'{"─"*62}'` 塞进 `QTextEdit(Consolas 9pt)`；中文是双宽字符，`<16` 补空格永远对不齐，屏幕上是横竖错位的斜塔，再叠 🔴🟡🟢 混排 | **多列对齐信息一律不许用字符串填充**，必须落到表格或网格布局（§4.5 / §4.6）；emoji 不得承担状态语义 |
| 07 页欢迎区文字互相叠压成"鬼影"：`QFrame { padding:14px; border:1px; border-radius:10px }` 是裸类型选择器，而 `QLabel` 的父类是 `QFrame`——Qt 类型选择器命中子类，于是卡片内**每一个 QLabel 都被套上描边 + 14px 内边距** | 容器类选择器必须带 `objectName`；见 §8 第 15 条与 §6.4 |
| 全工程 6 个近似蓝（`#2563eb`/`#1d4ed8`/`#1e40af`/`#3b82f6`/`#4f8cff`/`#2f6fe4`）、3 个近似绿（`#10b981`/`#22c55e`/`#16a34a`）、3 个近似红（`#dc2626`/`#ef4444`/`#b91c1c`）并存 | "配色不统一"的量化证据。迁移必须**按近似色归并**，不保留 6 个蓝；见 §9.4 |

---

## 2. 设计原则（5 条，每条附「因此不做什么」）

**P1 信息密度优先，留白只用于分组，不用于装饰。**
所有间距必须来自 4px 栅格序列，不允许出现「为了好看多留 20px」。
→ 因此我们**不做**大圆角卡片堆叠、不做 hero 区、不做 32px 以上的区块间空档。

**P2 层次用「底色差 + 1px 描边 + 字重」三件套，零阴影。**
QSS 不支持 `box-shadow`，与其用假的渐变阴影不如彻底放弃。
→ 因此我们**不做**弥散投影、不做玻璃拟态、不做悬浮抬升动效。

**P3 一个动作一种颜色。蓝色只代表「可操作 / 当前」，且一屏只允许一个 primary 实心按钮。**
语义色（成功/警告/危险/信息）成套固定，禁止页面自创。
→ 因此我们**不做**绿色主按钮（`#4CAF50` 加载数据）、不做渐变按钮、不做彩色描边公式块。

**P4 数字必须能竖着比。**
所有数值用等宽族 + 右对齐，单位从单元格里拿出来放到表头或独立 span。
→ 因此我们**不做**「16.4 mm」塞进一个单元格、不做比例数字体显示 KPI。

**P5 每个像素都有令牌，没有魔法值。**
颜色、字号、间距只能引用 §3 的令牌名；内联 `setStyleSheet` 全量清除。
→ 因此我们**不做**局部覆盖样式、不做 emoji 当功能图标、不做 8~10px 圆角。

---

## 3. 设计令牌（唯一真源）

> 命名规则：`--n-*` 中性灰阶、`--s-*` 表面/层次、`--primary-*` 主色、语义色 4 组、`--chart-*` 图表、`--fs-*` 字阶、`--sp-*` 间距、`--r-*` 圆角。
> 工程实现建议：QSS 无 CSS 变量，用 `string.Template` 在 Python 侧插值（见 §6.2）。

### 3.1 中性灰阶（10 档，冷灰 blue-cast，hue 210）

| 令牌 | HEX | 用途 | 白底对比度 |
|---|---|---|---|
| `--n-0` | `#FFFFFF` | 卡片/输入/表格底 | — |
| `--n-100` | `#F5F7FA` | 窗口底、状态栏、表头底 | — |
| `--n-200` | `#E7ECF2` | 分隔线、组框描边、横向网格线 | 1.19:1（仅装饰线） |
| `--n-300` | `#D2DAE3` | 控件描边（默认态）、滚动条 handle | 1.41:1（仅描边） |
| `--n-400` | `#AEB9C6` | 禁用描边、禁用图标、滚动条 hover | 1.99:1（仅禁用） |
| `--n-500` | `#8592A2` | **仅** 占位符 / 空态文字 / 时间戳 | 3.17:1 ⚠ 不得用于正文 |
| `--n-600` | `#64717F` | 次要文字、表头文字、单位、说明 | 4.99:1 ✓ |
| `--n-700` | `#47525F` | 正文默认色 | 7.95:1 ✓ |
| `--n-800` | `#2C353F` | 卡头、表单值、强调正文 | 12.44:1 ✓ |
| `--n-900` | `#111820` | 页面标题、结果卡主值 | 17.9:1 ✓ |

**规则**：`n-500` 及更浅的颜色**永远不能承载需要阅读的句子**（3.17:1 < 4.5:1）。若必须显示浅灰说明文字，用 `n-600`。

### 3.2 表面与层次（elevation 的 QSS 化方案）

阴影不可用，用「底色 + 描边」组合表达层级。**层级越靠上，底色越白、描边越深。**

| 层 | 令牌 | 底色 | 描边 | 用途 |
|---|---|---|---|---|
| L0 窗口 | `--s-app` | `#F5F7FA` | 无 | `QMainWindow` |
| L1 工作区 | `--s-panel` | `#FFFFFF` | 顶边 `1px --n-200` | `QTabWidget::pane`，页签之下整块白 |
| L2 容器 | `--s-panel` | `#FFFFFF` | `1px --n-200` + `--r-2` | `QGroupBox`、面板卡、KPI 卡 |
| L3 内嵌凹陷 | `--s-inset` | `#F7F9FB` | `1px --n-200` | 表格区、结果区、图区、只读文本区（靠**底色变暗**表达凹陷，不靠阴影） |
| L4 浮层 | `--s-panel` | `#FFFFFF` | `1px --n-300` + `--r-3` | 对话框、`QMenu`、下拉弹层；**唯一允许**叠加 `QGraphicsDropShadowEffect(0, 4, 12, rgba(17,24,32,38))` 的地方 |
| 交互 | `--s-hover` / `--s-sel` | `#EFF3F8` / `#E4EEF6` | 无 | hover 底 / 选中底 |

**组框标题背景色必须等于其父容器底色**（L1 上放组框 → 标题背景 `#FFFFFF`；L3 内放组框 → 标题背景 `#F7F9FB`），否则 `QGroupBox::title` 会切出一道割裂的白条。

### 3.3 语义色（4 组，每组 4 档，成套固定）

> **适用范围先说清（避免下一轮给表格套四态）**：本节的四态状态机**只服务 `ResultCard` 与 `KpiCard`** —— 即拥有 L1 主值位、需要"空/算/错/超差"切换的两个组件。**`QTableWidget` 不适用**：表格的空态用 §4.12 的「表内一行居中说明」表达（无遮罩层、无四态切换），表格的错误用 §4.13 的内联错误条，表格的"超差"用 §4.8 徽章着色。**不要**给表格加叠加遮罩或状态机。

| 语义 | 主档（用于图标/描边/填充） | 背景档 | 描边档 | 文字档（写在背景档上） | 文字档对比度 |
|---|---|---|---|---|---|
| Primary（可操作/当前） | `--primary` `#2F6A8C` | `--primary-bg` `#EAF2F7` | `--primary-border` `#BFD5E2` | `--primary-text` `#1F4A62` | 8.37:1 ✓ |
| hover / active（主色子档） | `--primary-hv` `#3A7B9F` / `--primary-active` `#24546F` | — | — | — | 白字 4.65 / 8.16 ✓ |
| Success（成功/达标） | `--success` `#1F7A57` | `--success-bg` `#EAF3EE` | `--success-border` `#A8CDBC` | `--success-text` `#175C42` | 7.01:1 ✓ |
| Warning（警告/需确认） | `--warning` `#B07C16` | `--warning-bg` `#FBF2DE` | `--warning-border` `#E4C88C` | `--warning-text` `#7A5409` | 6.08:1 ✓ |
| warning hover 底（子档） | — | `--warning-bg-hv` `#F7E7CB` | — | — | — |
| Danger（错误/破坏性） | `--danger` `#AC3B41` | `--danger-bg` `#FBEBEC` | `--danger-border` `#E2B0B3` | `--danger-text` `#85272C` | 7.83:1 ✓ |
| Info（说明/提示） | `--info` `#33668F` | `--info-bg` `#EDF2F8` | `--info-border` `#B9CCDF` | `--info-text` `#244C6D` | 8.01:1 ✓ |

**为什么 primary 是 `#2F6A8C` 而不是 `#2563EB`**：`#2563EB` 是 HSL(221, 83%, 53%)，问题不在对比度（白字 5.17:1 够用），而在饱和度 83% + 亮度 53% 的纯蓝大面积出现时会持续抢夺注意力；`#2F6A8C` 是 HSL(200, 50%, 37%)——饱和度 83%→50%、亮度 53%→37%、色相 221°→200°，白字对比 5.17:1→5.90:1。观感从「按钮蓝」变成「仪表刻度蓝」，能在密集数据旁边安静地表示当前状态。

**primary 与 info 色相接近（200° vs 211°）是刻意保留的**：在这个应用里蓝色只有一个语义家族——「可操作 / 当前 / 说明」。二者的使用契约互斥：`--primary` 只做填充（实心按钮、激活态下划线、选中边条）；`--info` 只做说明性文本块的底与字，**永不填充按钮**。同屏 4 组语义色不会同时出现，因此不需要靠色相区分，靠位置与形态区分。

**语义色使用契约（硬性）**
- Success / Warning / Danger：只用于**状态**（徽章、条形图、校验结果行、图标），不用于普通按钮填充。
- 破坏性操作按钮用「危险描边」形态（白底 + `--danger-border` + `--danger-text`），**不用整块红色填充**；整块 `--danger` 填充仅保留给确认对话框的唯一主按钮。
- 一张卡片内最多出现 1 组语义色。

### 3.4 图表色板（8 色，matplotlib 专用）

浅底白卡上使用，按序分配，**不允许自由取色**。全部 ≥3.8:1 对比白底。

| 令牌 | HEX | 固定语义 | 白底对比 | 线型 |
|---|---|---|---|---|
| `--chart-1` | `#2F6A8C` | 主序列 / 参考真值 | 5.90 | 实线 1.4px |
| `--chart-2` | `#C4661F` | 实测 / 测量值 | 3.99 | 实线 1.4px |
| `--chart-3` | `#2E8A6E` | 拟合 / 理论值 | 4.22 | 实线 1.4px |
| `--chart-4` | `#A34A50` | 超差 / 异常点 | 5.75 | 实线 1.4px + marker |
| `--chart-5` | `#6A5AA8` | 仿真 / 第三组 | 5.77 | 实线 1.2px |
| `--chart-6` | `#7A6B3F` | 参考线 / 包络 | 5.25 | 虚线 1.2px `(0,(4,3))` |
| `--chart-7` | `#3E8BA6` | 辅助 / 背景系列 | 3.85 | 实线 1.0px `alpha .85` |
| `--chart-8` | `#6E6259` | 基准 / 网格标注 | 5.91 | 点线 1.0px |

**约束**：
- `--chart-1` 与 `--chart-7` 不得在同一张图里同时作为实线出现（色相差仅 6°）；必须同用时 `--chart-7` 改虚线。
- 正负/增减不用红绿，用 `--chart-2`（+）/ `--chart-7`（-）。
- 色盲安全靠**色相跨度 + 明度阶梯 + 线型**三重冗余，任何单靠颜色的信息都必须同时有 marker 或线型差异。
- matplotlib 样式统一由 `plotting.py` 一处设置（见 §4.14），禁止面板内 `ax.plot(color='#...')` 写字面色值。

### 3.5 字阶

字体族：
- 中文/混排：`'Microsoft YaHei UI', 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif`
- 纯数值（KPI 值、结果卡主值、表格数值列、版本号）：`'Cascadia Mono', 'Consolas', 'JetBrains Mono', monospace`

| 令牌 | 字号 px | QSS 值 | 字重 | 行高 | 字体族 | 使用场景 |
|---|---|---|---|---|---|---|
| `--fs-32` | 32 | `24pt` | 700 | 40 | 等宽 | 结果卡主结果值（一屏最多 1 处） |
| `--fs-26` | 26 | `19.5pt` | 700 | 32 | 等宽 | KPI 卡数值 |
| `--fs-17` | 17 | `13pt` | 600 | 24 | 中文 | 页面标题（每页仅 1 个） |
| `--fs-15` | 15 | `11pt` | 600 | 22 | 中文 | 区块标题（H2） |
| `--fs-14` | 14 | `10.5pt` | 600 | 20 | 中文 | 卡头 / 组框标题（H3） |
| `--fs-13` | 13 | `10pt` | 400 | 20 | 中文 | **正文默认** |
| `--fs-12` | 12 | `9pt` | 400 | 18 | 中文 | 次要说明、单位、表单辅助提示 |
| `--fs-12s` | 12 | `9pt` | 600 | 16 | 中文 | 表单左标签、表格表头 |
| `--fs-11` | 11 | `8.5pt` | 600 | 14 | 等宽/中文 | 徽章文字、mono 小标（**禁止**用于句子） |

**排印规则**
- 正文字号下限 12px（9pt），已全局遵守；`--fs-11` 只允许出现在徽章与版本号。
- 「QSS 值」列已取整到 0.5pt 便于书写（如 17px 写 `13pt` = 17.33px），96dpi 下差异不足 1px，可接受；不允许反过来为了凑 pt 改设计 px。
- 数值专用等宽族**只用于纯数值控件**。混排中文的 QLabel 如果设 `font-family: Consolas`，Windows 下中文会回退到宋体，观感断裂——因此「数值 + 单位」必须拆成两个控件（见 §4.5）。
- 表格数值列右对齐 + 等宽；文字列左对齐 + 中文族。禁止在同一列混排。
- 行高必须显式指定（`min-height`），不要让 Qt 用 `fontMetrics` 自动撑，否则 28/32/36 三档高度会漂。
- **负号一律半角连字符 `-`（U+002D）**；禁止用排版减号 `−`、短破折号 `–`、全角连字符 `－` 冒充负号（中文破折号 `——` 作标点合法，但不得当减号用）。负值、区间、公式同规则；理由见 §8 第 18 条（测试断言 + 用户复制可解析）。

### 3.6 间距 / 圆角 / 描边 / 尺寸

| 类别 | 令牌 | 值 | 用途 |
|---|---|---|---|
| 间距 | `--sp-1`~`--sp-10` | `2 / 4 / 6 / 8 / 12 / 16 / 20 / 24 / 32 / 40` | 唯一合法间距序列，**不允许 5/10/14/18 这种值** |
| 圆角 | `--r-1` | `2px` | 输入控件、徽章、表格、结果区 |
| | `--r-2` | `4px` | 按钮、卡、组框、KPI 卡 |
| | `--r-3` | `6px` | 对话框、浮层、菜单 |
| 描边 | `--bw` | `1px` | 全部默认描边与分隔线 |
| | `--bw-2` | `2px` | 页签激活下划线、KPI 顶条、图表 ±0 线 |
| | `--bw-3` | `3px` | KPI 左侧强调条（独立 QFrame，非 border） |
| 控件高 | `--h-sm` | `28px` | 表单输入、表格内控件、次要按钮 |
| | `--h-md` | `32px` | 工具栏按钮、页头按钮、primary 按钮 |
| | `--h-lg` | `36px` | 页签、页面级强调按钮（「执行转换」） |
| 行高 | `--row-form` / `--row-table` / `--row-head` | `32 / 26 / 30px` | 表单行 / 表格行 / 表头 |
| | `--row-param` | `24px` | 结果卡内**键值对**行高（QLabel 对，非表格）。**不要用于 QTableWidget**——表格无论放在哪、无论几行，一律 `--row-table` 26px |
| 区高 | `--h-page-header` / `--h-kpi` / `--h-status` / `--h-tab` | `44 / 76 / 26 / 36px` | 页头 / KPI 卡 / 状态栏 / 页签 |
| 图标 | `--icon-sm` / `--icon-md` | `14 / 16px` | 按钮内 / 工具栏；禁止 20px 以上图标出现在按钮里 |

> QSS 高度算式：`min-height = 目标高度 - 2 × border宽度`。例：目标 32px、border 1px → `min-height: 30px`。所有规范里的「控件高」都指**含描边的外框总高**。

### 3.7 交互状态统一映射

| 状态 | 底色 | 描边 | 文字/图标 |
|---|---|---|---|
| 默认 | `--n-0` | `--n-300` | `--n-700` |
| 悬停 | `--s-hover` | `--n-400` | `--n-800` |
| 按下 | `--s-sel` | `--primary` | `--n-900` |
| 聚焦 | `--n-0` | `--primary` | `--n-800` |
| 选中 | `--s-sel` | `--primary`（左 3px 条或 1px 全框） | `--n-900` |
| 禁用 | `--n-100` | `--n-200` | `--n-400`（`--n-500` 作占位符） |
| 错误 | `--n-0` | `--danger` | `--danger-text` |
| 只读 | `--s-inset` | `--n-200` | `--n-600` |

**聚焦态不许改描边宽度**。理由：描边色从 `--n-300`（1.41:1）跳到 `--primary`（5.9:1）已有 4.2 倍对比跃升，人眼完全可辨；而 `border: 1px → 2px` 会让控件外框长 2px，在 1024×640 的密集表单里引发整行抖动。规范：**聚焦只换颜色 + 底色微调，几何尺寸恒定。**

---

## 4. 组件规范

> 每个组件格式：结构 / 尺寸 / 状态 / 示例 QSS。QSS 中的 `{{ }}` 为 `string.Template` 占位符示意，落地时替换为令牌值。

### 4.1 QTabBar（9 个页签的主外壳）

**结构**：水平 9 等权页签，无 pill、无图标（图标统一移入页内页头）。激活态用 **2px 下划线**表达。

**为什么是下划线而不是 pill**：
1. 尺寸账——pill 需要左右各 16px 内边距 + 4px 间距，9 个页签 = 689 + 9×32 + 8×4 ≈ 1009px，超过 1024px 窗口可用的约 985px，必然出滚动箭头（现状就是）；下划线式只需左右 14px、间距 0，可压到 911~941px。
2. 视觉账——pill 激活态是填充块，会和页内唯一的 primary 实心按钮抢焦点；下划线只占用 2px 高度，不进入视觉焦点竞争。
3. 语义账——这是「并列的 9 个工作面」，不是「筛选器」，下划线式更像传统桌面软件的文档页签。

**尺寸**：高 `--h-tab` 36px（`min-height: 34px` + 2px 下划线）；水平内边距 14px；字号 `--fs-13` 10pt / 激活 600 字重；页签栏底部 1px `--n-200` 通栏分隔线（用 `QTabWidget::pane` 的 `border-top` 实现，避免双线）。

**宽度预算（关键交付）**：现有页签名共 53 个汉字，13px 字号下 689px + 9×28px 内边距 = 941px（截图稿实测 911px），1024px 窗口安全，无滚动箭头。若再出现第 10 个页签，把内边距降到 12px 并把字号降到 12px（可省 ~60px），**不得**启用左右滚动箭头作为默认方案。

**状态**：默认 `--n-600` 10pt/400 透明底；悬停 `--n-800` + `--s-hover` 底；激活 `--primary` 10pt/600 + 2px `--primary` 下划线；禁用 `--n-400`；首屏懒加载中的页签不加「加载中」动效，直接显示默认态。

```css
QTabWidget::pane { border: none; border-top: 1px solid {{n-200}}; background: {{n-0}}; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent;
    color: {{n-600}};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 0 14px;
    min-height: 34px;          /* 34 + 2px 下划线 = 36 */
    font-family: 'Microsoft YaHei';
    font-size: 10pt;
}
QTabBar::tab:hover   { color: {{n-800}}; background: {{s-hover}}; }
QTabBar::tab:selected{ color: {{primary}}; border-bottom: 2px solid {{primary}}; font-weight: 600; }
QTabBar::tab:disabled{ color: {{n-400}}; }
/* 滚动箭头仅在 window<1024 时出现，出现时压成 24px 方块，禁止 Fusion 默认灰方块 */
QTabBar QToolButton { background: {{n-100}}; border: 1px solid {{n-200}}; border-radius: 2px; width: 24px; }
```

### 4.2 页面标题区（PageHeader）

**结构**：`[页面标题 (fs-17)] [可选副标题 (fs-12, n-600)] … 弹性空白 … [操作区：≥1 个 secondary + 至多 1 个 primary]`
**尺寸**：高 `--h-page-header` 44px；左内边距 `--sp-6` 16px；操作区按钮间距 `--sp-4` 8px；底边 1px `--n-200`。
**规则**：每页只能有 1 个 primary 按钮（该页最高频动作）；页头按钮统一 `--h-md` 32px；标题区不放大图标、不用彩色底。

```css
QWidget#pageHeader { background: {{n-0}}; border-bottom: 1px solid {{n-200}}; min-height: 43px; }
QLabel#pageTitle   { font-size: 13pt; font-weight: 600; color: {{n-900}}; }
QLabel#pageSubtitle{ font-size: 9pt;  color: {{n-600}}; }
```

### 4.3 QGroupBox / 卡头

**结构**：`[标题 —— 1px 内嵌分隔可省略] ` + 内容区。
**尺寸**：`--r-2` 4px 圆角；1px `--n-200` 描边；`margin-top: 10px`（供标题嵌入边框）；`padding: 10px 12px 12px`；标题 `--fs-14` 10.5pt/600 `--n-800`，`left: 10px`，`padding: 0 6px`。
**状态**：默认即唯一态；禁用时整组 `--n-500` 文字 + 50% 透明感（用 `--n-100` 底替代）。

```css
QGroupBox {
    background: {{n-0}};
    border: 1px solid {{n-200}};
    border-radius: 4px;
    margin-top: 10px;
    padding: 10px 12px 12px 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    background: {{n-0}};         /* 必须等于父容器底色 */
    color: {{n-800}};
    font-size: 10.5pt;
    font-weight: 600;
}
```

> 现状 08 页「表头压在组框边框上」= 组框 `padding-top` 不足以容纳表头 30px，或表头被直接放进标题区。规则：**任何 QTableWidget 进组框，组框 `padding-top` ≥ 10px，且表格上方不得再有任何 0 间距元素。**

### 4.4 KPI 指标卡

**结构**：`[3px 左侧强调条] [标签 fs-12s n-600] / [数值 fs-26 等宽 700 n-900 + 单位 fs-12 n-600 基线对齐] / [可选：同比/状态徽章 右对齐]`

**尺寸**：总高 `--h-kpi` 76px；内边距 `--sp-5` 12px（上下 12、左右 14）；宽随栅格（4 列 at ≥1280，2 列 at 1024）；卡间距 `--sp-4` 8px；圆角 `--r-2`；1px `--n-200` 描边。

**单位排版**：数值与单位拆两个 QLabel，用 `QHBoxLayout` + `setAlignment(Qt.AlignBottom)`，间距 `--sp-1` 2px。数值 `--fs-26`、单位 `--fs-12`。**禁止**在一个 QLabel 里写「32.4 dBi」，因为等宽族不含中文单位会回退成宋体。

**空态**：数值位置显示 `--`（两个 em dash，`--n-500`，等宽），并在卡片右下角显示 14px 空心状态点 `--n-400`。不要用一个比内容大 3 倍的空卡（现状 06 页）——空态卡与有数值卡同高，仅数值位变化。

**强调条颜色契约**：`tone="primary"` 用 `--primary`；`tone="success"` 用 `--success`；`tone="warning"` 用 `--warning`；`tone="neutral"` 用 `--n-300`。一屏最多 1 个 `success`/`warning` 强调条。

```css
QFrame#kpiCard            { background: {{n-0}}; border: 1px solid {{n-200}}; border-radius: 4px; }
QFrame#kpiAccent          { border: none; border-radius: 0; }   /* 3px 宽 QFrame，靠 property 上色 */
QFrame#kpiAccent[tone="primary"] { background: {{primary}}; }
QFrame#kpiAccent[tone="success"] { background: {{success}}; }
QFrame#kpiAccent[tone="warning"] { background: {{warning}}; }
QFrame#kpiAccent[tone="neutral"] { background: {{n-300}}; }
QLabel#kpiLabel           { color: {{n-600}}; font-size: 9pt; font-weight: 600; }
QLabel#kpiValue           { color: {{n-900}}; font-size: 19.5pt; font-weight: 700;
                            font-family: 'Consolas'; }
QLabel#kpiUnit            { color: {{n-600}}; font-size: 9pt; }
```

> 为什么强调条用独立 QFrame 而不是 `border-left: 3px`：Fusion 下 `border-left: 3px` + `border-radius: 4px` 会在左侧两角渲染出缺口，且无法单独控制强调条颜色（QSS 一个 box 只有一个 border-color 组）。

### 4.5 结果卡（主结果 + 单位 + 参数表 + 提示）

**结构**（自上而下，四段）：
1. **结果头**：左「主结果」标签 `--fs-12s --n-600`；右侧状态徽章（如 `达标` success / `超差` danger）。
2. **主结果行**：数值 `--fs-32` 等宽 700 `--n-900` + 单位 `--fs-14 --n-600` 基线对齐 + 右侧 `复制` ghost 按钮。
3. **参数表**：2 列（标签右对齐 `--fs-13 --n-600`，值左对齐 `--fs-13` 等宽 `--n-800`），行高 `--row-param` **24px**，行间 1px `--n-200` 或纯斑马纹（选其一，不叠加）。4~6 行为宜，超过 8 行折进「更多参数」折叠。一行内若有两组信息（如「100.0 W」与「20.00 dBW」），用 `--sp-6` 16px 的 layout spacing 分隔，**不得用全角空格凑距离**（§8 第 19 条）。
4. **提示行**：`kind` 四变体（见下），默认 `info`：`--info-bg` 底 + 左侧 3px `--info` 条 + `--fs-12 --info-text`，内边距 6/10。

**尺寸**：卡片 `--r-2`、1px `--n-200`、内边距 14/16；主结果行与参数表间距 `--sp-5` 12px；提示行与参数表间距 `--sp-4` 8px。

**状态**：空态 → 主结果位显示 `--`（`[state="empty"]` → `--n-500`，**不得**沿用 `--n-900`，否则占位符会和真结果抢 L1 视觉位），参数表整体 `--n-500`，提示行改为 `--n-100` 底 + `--n-600` 字「录入参数后自动计算」；错误态 → 主结果位显示 `计算失败`（`--danger-text`，`--fs-17`），提示行换成 `kind="danger"` 的错误原因，并给「重试」 ghost 按钮。

**变体**
- `dense=True`（结果卡所在列 < 360px 时启用）：主结果值由 `--fs-32` 降为 `--fs-26`（复用 KPI 档），单位 `--fs-14` 不变，参数表行高降为 24px 不变。这是**唯一允许**偏离 §4.5 默认字阶的情况，且必须由容器宽度判定，不得手工指定。
- `kind="info" | "warning" | "danger" | "none"`：提示行语义变体，颜色全部取自 §3.3 现有令牌，**不新增色值**。`kind="none"` 时整行 `hide()`，不占位。

```css
QFrame#resultCard  { background: {{n-0}}; border: 1px solid {{n-200}}; border-radius: 4px; }
QLabel#resultValue { color: {{n-900}}; font-size: 24pt; font-weight: 700; font-family: 'Consolas'; }
QLabel#resultValue[state="empty"] { color: {{n-500}}; }
QLabel#resultValue[dense="true"]   { font-size: 19.5pt; }   /* 窄栏降档，见「变体」 */
QLabel#resultUnit  { color: {{n-600}}; font-size: 10.5pt; }
QLabel#paramKey    { color: {{n-600}}; font-size: 10pt; }
QLabel#paramVal    { color: {{n-800}}; font-size: 10pt; font-family: 'Consolas'; }

/* 提示行四变体：只换色，几何尺寸完全一致 */
QFrame#hintBar     { background: {{info-bg}}; border: none; border-left: 3px solid {{info}};
                     border-radius: 2px; }
QFrame#hintBar[kind="warning"] { background: {{warning-bg}}; border-left-color: {{warning}}; }
QFrame#hintBar[kind="danger"]  { background: {{danger-bg}};  border-left-color: {{danger}}; }
QLabel#hintText    { color: {{info-text}}; font-size: 9pt; }
QLabel#hintText[kind="warning"] { color: {{warning-text}}; }
QLabel#hintText[kind="danger"]  { color: {{danger-text}}; }
```

> `#hintBar[kind="danger"]` 与 §4.13 `#errorBar` 视觉等价（`--danger-bg` + 左 3px `--danger` + `--danger-text`）。区别只在语义归属：`#errorBar` 贴在被校验的控件/区块旁边，`#hintBar[kind="danger"]` 是结果卡内部的整卡结论。二者不得在同一屏同时出现。

> **禁止**再用 `QTextEdit` + HTML 字符串拼结果（现状 `calc_ui.py:168`）。HTML 拼接无法保证对齐，且 `selection-background-color`、行高、单位基线全部失控。改为「QLabel 栅格 + 只读 QPlainTextEdit（仅承载需要复制的长文本）」。若短期无法重构，退路是：统一 HTML 模板字符串只允许使用 §3 的令牌值，且 `line-height: 20px`、`font-family: Consolas`，并在外层加 `--s-inset` 底 + 1px `--n-200`。

### 4.5.1 多列信息：禁止字符串填充对齐

**这一条是为了正面回答 `array_designer.py:766` 那类写法**：
```python
f'{"指标":<16} {"数值":>10} {"说明":<28}'   # ← 禁止
f'{"─"*62}'                                # ← 禁止
```
中文是双宽字符，`<16` 补的是 ASCII 空格，一个汉字占两格宽而填充只算一格，所以列宽恒等是假的，屏幕上必然横竖错位成斜塔；再叠 🔴🟡🟢 混排，可读性归零。

**判定规则（机械可查）**：结果区里出现 **≥2 列、需要上下对齐** 的信息，一律不得用 `str.ljust/rjust/format` + 空格/制表符/盒绘制字符（`─│┌`）拼接，必须落到下述两种结构：

| 列数 | 结构 | 规格 |
|---|---|---|
| 2 列（键—值） | `QGridLayout` + `QLabel#paramKey` / `QLabel#paramVal` | 标签列固定宽（按最长标签 + 8px），右对齐；值列左对齐等宽；行高 `--row-param` 24px |
| ≥3 列（指标表） | `QTableWidget`（沿用 §4.6） | 首列文本左对齐、数值列右对齐等宽、末列「说明」左对齐；行高 26px；超过 12 行才允许滚动 |

**不许**用 `setFont(QFont('Consolas'))` 来"让中文对齐"——Consolas 不含 CJK，Qt 会逐字回退到别的中文字体，宽度依旧不可控；等宽族只能用在**纯数字**列。

**状态语义**：`✅/🟢/🟡/🔴/❌` 一律改为 §4.8 徽章（`达标`/`边界`/`超差`），颜色由语义色令牌决定；结果文本里只允许出现短横、括号、百分号等中性符号。

### 4.6 QTableWidget

**尺寸**：表头高 30px，行高 26px，单元格左右内边距 10px；表头 `--fs-12s` 9pt/600 `--n-600`，底 `--n-100`，下边 1px `--n-300`；无竖网格线，仅横向 1px `--n-200`；斑马纹 `--s-inset`。

**列类型（只有这 4 种，不许自创）**

| 列类型 | 对齐 | 字体 | 颜色 | 宽度 | 备注 |
|---|---|---|---|---|---|
| 文本列（名称/通道/路径） | 左 | `--fs-13` 中文族 | `--n-700` | 首列 stretch，`minimumSectionSize` 56 | 超宽 `elide right` + tooltip |
| 数值列（幅度/增益/距离） | **右** | `--fs-13` 等宽 | `--n-800` | 内容宽 × 1.4，最小 72 | 单元格内**只放数字**，单位进表头 |
| 状态列（通过/超差） | 居中 | `--fs-12s` | 徽章令牌 | 固定 88 | 用 §4.8 徽章，不写彩色文字 |
| 说明列（公式/口径/备注） | 左 | `--fs-12` 中文族 | `--n-600` | 1fr，最小 160 | 最多 2 行，超出 `elide right` + tooltip；**不放数值结论** |

表头文字必须包含单位，如 `增益 (dBi)`、`幅度 (dB)`、`相位 (°)`。说明列用于表达「这个数怎么来的」（如 `近似 10·log₁₀N + 3`），因此字号比正文低一档、颜色退一档，让数值列始终是视觉重心——**说明列不得与数值列同字号同色，否则整表失去读数秩序**。

**选中**：`--s-sel` 底 + `--n-900` 字，无边框、无发光；多选时不加粗。

```css
QTableWidget {
    background: {{n-0}};
    alternate-background-color: {{s-inset}};
    border: 1px solid {{n-200}};
    border-radius: 2px;
    gridline-color: transparent;
    selection-background-color: {{s-sel}};
    selection-color: {{n-900}};
    font-size: 10pt;
}
QTableWidget::item { padding: 0 10px; border: none; border-bottom: 1px solid {{n-200}}; }
QTableWidget::item:selected { background: {{s-sel}}; color: {{n-900}}; }
QHeaderView::section {
    background: {{n-100}};
    color: {{n-600}};
    border: none;
    border-bottom: 1px solid {{n-300}};
    padding: 0 10px;
    min-height: 29px;
    font-size: 9pt;
    font-weight: 600;
}
QTableCornerButton::section { background: {{n-100}}; border: none; }
```

> QSS 不支持 `:only-child` / `:last`，所以**不要**用 `border-right` 画竖网格线（末列永远多一条）。要竖线就用 `gridline-color: {{n-200}}` + `setShowGrid(True)`；要横线优先用上面的 `::item { border-bottom }` + `setShowGrid(False)`。
> 列宽规则：设 `setSectionResizeMode(QHeaderView.Interactive)`，数值列 `setMinimumSectionSize` 按内容宽度 × 1.4 设置（04 页 `0...` 截断就是列宽小于内容）。至少一列 stretch，禁止整表所有列都被写死。

### 4.7 工具栏与按钮四变体

**工具栏**：高 36px，底 `--n-0`，下边 1px `--n-200`，按钮间距 `--sp-2` 4px，左侧留 `--sp-4` 8px；分隔用 1px × 20px 竖线 `--n-200`，不用空白。

| 变体 | 用途 | 默认 | 悬停 | 按下 | 禁用 |
|---|---|---|---|---|---|
| **primary** | 每页唯一主操作（执行/绘制/保存） | 底 `--primary`，白字 600 | 底 `--primary-hv` | 底 `--primary-active` | 底 `--n-400` 白字 |
| **secondary** | 常规动作（新建/导出/浏览） | 白底，1px `--n-300`，`--n-800` | 底 `--s-hover`，边 `--n-400` | 底 `--s-sel`，边 `--primary` | 底 `--n-100`，字 `--n-400` |
| **ghost** | 低频/行内动作（复制/重置/更多） | 透明底，`--primary` 字 | 底 `--s-hover` | 底 `--s-sel` | 字 `--n-400` |
| **danger** | 破坏性动作（删除/清空） | 白底，边 `--danger-border`，字 `--danger-text` | 底 `--danger-bg` | 底 `--danger-bg` + 边 `--danger` | 底 `--n-100`，字 `--n-400` |

**尺寸**：`--h-md` 32px（`min-height: 30px`）；`--h-sm` 28px（表格内/紧凑工具栏）；`--h-lg` 36px（页面级「执行」按钮）；水平内边距 primary/secondary 14px、ghost 8px；图标 14px + 间距 6px。

```css
QPushButton {
    min-height: 30px; padding: 0 14px;
    background: {{n-0}}; color: {{n-800}};
    border: 1px solid {{n-300}}; border-radius: 4px;
    font-size: 10pt;
}
QPushButton:hover    { background: {{s-hover}}; border-color: {{n-400}}; }
QPushButton:pressed  { background: {{s-sel}};  border-color: {{primary}}; }
QPushButton:disabled { background: {{n-100}}; border-color: {{n-200}}; color: {{n-400}}; }

QPushButton[variant="primary"] {
    background: {{primary}}; border: 1px solid {{primary}}; color: #FFFFFF; font-weight: 600;
}
QPushButton[variant="primary"]:hover   { background: {{primary-hv}};  border-color: {{primary-hv}}; }
QPushButton[variant="primary"]:pressed { background: {{primary-active}}; border-color: {{primary-active}}; }
QPushButton[variant="primary"]:disabled{ background: {{n-400}}; border-color: {{n-400}}; color: #FFFFFF; }

QPushButton[variant="ghost"] {
    background: transparent; border: 1px solid transparent; color: {{primary}}; padding: 0 8px;
}
QPushButton[variant="ghost"]:hover { background: {{s-hover}}; }

QPushButton[variant="danger"] {
    background: {{n-0}}; border: 1px solid {{danger-border}}; color: {{danger-text}};
}
QPushButton[variant="danger"]:hover   { background: {{danger-bg}}; }
QPushButton[variant="danger"]:pressed { border-color: {{danger}}; }
```

> 变体通过 `setProperty("variant", "primary")` + 上面的属性选择器实现，**不要**再写 `setStyleSheet(...)`（见 §6.3）。属性变更后必须 `style().unpolish(w); style().polish(w)`，否则不重绘。

### 4.8 徽章（Badge）

**尺寸**：高 20px，内边距 `0 6px`，圆角 `--r-1` 2px，字号 `--fs-11` 8.5pt/600，1px 描边 + 20% 浓度底。
**用法**：状态、计数、单位换算标记。**不放动词、不放图标**。

| 语义 | 底 | 边 | 字 |
|---|---|---|---|
| neutral | `--n-100` | `--n-200` | `--n-600` |
| primary | `--primary-bg` | `--primary-border` | `--primary-text` |
| success | `--success-bg` | `--success-border` | `--success-text` |
| warning | `--warning-bg` | `--warning-border` | `--warning-text` |
| danger | `--danger-bg` | `--danger-border` | `--danger-text` |

```css
QLabel#badge { min-height: 18px; padding: 0 6px; border-radius: 2px;
               border: 1px solid {{n-200}}; background: {{n-100}};
               color: {{n-600}}; font-size: 8.5pt; font-weight: 600; }
QLabel#badge[tone="success"] { background: {{success-bg}}; border-color: {{success-border}}; color: {{success-text}}; }
```

### 4.9 输入控件

**尺寸**：高 `--h-sm` 28px（`min-height: 26px`）；`--r-1` 2px；内边距 `0 8px`；1px `--n-300`；字号 `--fs-13` 10pt；占位符 `--n-500`。

**表单栅格（解决 800px 超宽 QComboBox）**：
- 单列表单：`标签列固定 96px（右对齐，右内边距 8px） + 控件列 min 160 / max 320px`，剩余空间留白。
- 双列表单：两组 `(96 + 8 + 320)` = 848px 上限，组间距 `--sp-6` 16px。
- 路径类输入（可超出 320）：控件 `stretch` + 右侧挂 `浏览…` secondary 按钮（`--h-sm` 28px）。
- 必须 `setMaximumWidth(320)` 的控件：`QLineEdit`、`QComboBox`、`QSpinBox`、`QDoubleSpinBox`。带单位的数值输入用 `QDoubleSpinBox.setSuffix(' mm')`，**不要**在旁边加一个 QLabel 写单位。

```css
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {
    min-height: 26px; padding: 0 8px;
    background: {{n-0}}; color: {{n-800}};
    border: 1px solid {{n-300}}; border-radius: 2px;
    font-size: 10pt;
    selection-background-color: {{s-sel}}; selection-color: {{n-900}};
}
QLineEdit:hover, QComboBox:hover { border-color: {{n-400}}; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: {{primary}};            /* 禁止同时改 border-width */
}
QLineEdit:disabled, QComboBox:disabled {
    background: {{n-100}}; border-color: {{n-200}}; color: {{n-400}};
}
QLineEdit[state="error"] { border-color: {{danger}}; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right;
                       width: 18px; border: none; }
QComboBox QAbstractItemView {
    background: {{n-0}}; border: 1px solid {{n-300}}; border-radius: 2px;
    selection-background-color: {{s-sel}}; selection-color: {{n-900}}; outline: none;
}
QCheckBox { spacing: 6px; font-size: 10pt; color: {{n-700}}; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid {{n-300}};
                       border-radius: 2px; background: {{n-0}}; }
QCheckBox::indicator:checked { background: {{primary}}; border-color: {{primary}}; }
```

> `QComboBox::down-arrow` / `QSpinBox::up-arrow` 如需自定义，QSS 只接受 `image: url(...)`，**不能用 border 三角技巧**。建议：不覆盖，沿用 Fusion 原生箭头；确需替换时提供 16px 单色 SVG 资源。

### 4.10 滚动条

宽/高 10px；handle `--n-300`（圆角 5px，`min-height: 32px`），hover `--n-400`；无箭头、无轨道底色。

```css
QScrollBar:vertical   { background: transparent; width: 10px; margin: 0; border: none; }
QScrollBar::handle:vertical { background: {{n-300}}; min-height: 32px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: {{n-400}}; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; width: 0; border: none; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; border: none; }
QScrollBar::handle:horizontal { background: {{n-300}}; min-width: 32px; border-radius: 5px; }
```

### 4.11 状态栏

**尺寸**：高 `--h-status` 26px；底 `--n-100`；上边 1px `--n-200`；文字 `--fs-12` 9pt `--n-600`；左侧左内边距 `--sp-4` 8px；右侧版本号等宽 `--n-600`，右内边距 12px。
**规则**：状态栏只显示「一句话状态 + 进度 + 任务数 + 版本」，不显示图标；同一状态不得同时出现在页内文本区与状态栏（现状 08 页同一条消息显示两次）。

```css
QStatusBar { background: {{n-100}}; border-top: 1px solid {{n-200}}; min-height: 25px; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: {{n-600}}; font-size: 9pt; }
QStatusBar QLabel#statusVersion { font-family: 'Consolas'; padding-right: 12px; }
QProgressBar { border: none; background: {{n-200}}; border-radius: 2px; max-height: 6px; text-align: center; }
QProgressBar::chunk { background: {{primary}}; border-radius: 2px; }
```

### 4.12 空态

**结构**：居中竖排 `[1px 虚线框 32×32 图标位] / [主文案 fs-13 n-600] / [辅助文案 fs-12 n-500]`，容器最小高 120px。
**规则**：空态文案必须给出**下一步动作**（「点击左侧目录选择数据集」而不是「暂无数据」）；空态不画插画、不用 emoji、不用彩色。

```css
QFrame#emptyState { background: {{s-inset}}; border: 1px dashed {{n-300}}; border-radius: 2px; }
QLabel#emptyTitle { color: {{n-600}}; font-size: 10pt; }
QLabel#emptyHint  { color: {{n-500}}; font-size: 9pt; }
```

### 4.13 错误态

**内联错误条**（表单/区块级）：`--danger-bg` 底 + 左侧 3px `--danger` 条 + `--fs-12 --danger-text`，内边距 8/10，圆角 2px，高度自适应；与出错控件间距 `--sp-2` 4px。
**整页错误**（面板加载失败）：卡片居中，标题 `--fs-15 --danger-text`，正文 `--fs-12 --n-700`，右侧 primary 重试按钮；不弹 `QMessageBox`（现状 `main_window.py` 的错误卡做法保留，仅换色换字号）。
**模态错误**：保留 `QMessageBox`，但按钮统一为 secondary + primary 各一，不再出现三个同色按钮。

```css
QFrame#errorBar { background: {{danger-bg}}; border: none; border-left: 3px solid {{danger}};
                  border-radius: 2px; min-height: 28px; }
QLabel#errorText { color: {{danger-text}}; font-size: 9pt; }
```

### 4.14 图表区（matplotlib 嵌入）

**必须全局声明中文字体族**，否则中文标题渲染为 □□□□（02/04 页现状）。

**根因（已核实）**：`app_config.py:13` 的 `font.family` 只列了 Times New Roman / SimSun / STSong / DejaVu Sans，而本机**没有 SimSun**；于是中文回退到 DejaVu Sans，DejaVu 不含 CJK 字形 → 每个汉字渲染为空心方框。所以修复不是"再加一个字体名"，而是**按可用性排序的回退链 + 覆盖 app_config 已有的 font.family**。

**中文族回退顺序（Windows 现场可用性从高到低）**：
`Microsoft YaHei` → `Microsoft YaHei UI` → `SimHei` → `Microsoft JhengHei` → `Noto Sans CJK SC` → `Source Han Sans SC` → `DejaVu Sans`
前 3 个覆盖全部 Win7+；`SimSun`/`STSong` **不要**放进链里（本机缺失，且笔画过细，9~10px 下糊成一片）。

```python
# plotting.py 中统一设置，禁止面板各自设置
import matplotlib
matplotlib.rcParams.update({
    # ---- 字体：中文族在前，族名必须是 font.family='sans-serif' 才会被检索 ----
    'font.family': 'sans-serif',
    'font.sans-serif': ['Microsoft YaHei', 'Microsoft YaHei UI', 'SimHei',
                        'Microsoft JhengHei', 'Noto Sans CJK SC',
                        'Source Han Sans SC', 'DejaVu Sans'],
    'font.size': 9,                     # 与 --fs-12 同档
    'axes.unicode_minus': False,        # 负号不能变成方块（与字体族是两个独立坑）
    # ---- 画布 ----
    'figure.facecolor': '#FFFFFF',      # --n-0
    'figure.dpi': 100,
    'savefig.facecolor': '#FFFFFF',
    'savefig.bbox': 'tight',
    # ---- 坐标轴 ----
    'axes.facecolor': '#FFFFFF',        # --n-0
    'axes.edgecolor': '#D2DAE3',        # --n-300 轴线
    'axes.linewidth': 0.8,
    'axes.labelcolor': '#47525F',       # --n-700 轴标题
    'axes.labelsize': 9,
    'axes.titlecolor': '#2C353F',       # --n-800 图标题
    'axes.titlesize': 10,
    'axes.titleweight': 'bold',
    'axes.titlepad': 8,
    'axes.spines.top': False,           # 上/右轴线关掉，减少框架噪声
    'axes.spines.right': False,
    # ---- 网格：只留主网格 ----
    'axes.grid': True,
    'axes.grid.axis': 'both',
    'axes.grid.which': 'major',
    'grid.color': '#E7ECF2',            # --n-200
    'grid.linewidth': 0.8,
    'grid.alpha': 1.0,
    # ---- 刻度 ----
    'xtick.color': '#64717F', 'ytick.color': '#64717F',   # --n-600
    'xtick.labelsize': 8.5, 'ytick.labelsize': 8.5,
    'xtick.direction': 'out', 'ytick.direction': 'out',
    'xtick.major.size': 3, 'ytick.major.size': 3,
    'xtick.major.width': 0.8, 'ytick.major.width': 0.8,
    # ---- 图例：无边框、无底色 ----
    'legend.frameon': False,
    'legend.fontsize': 8.5,
    'legend.labelcolor': '#47525F',     # --n-700
    # ---- 线：与图表色板配套 ----
    'lines.linewidth': 1.4,
    'lines.markersize': 4,
    'patch.linewidth': 0.8,
})
# 曲线颜色统一取自 §3.4：ax.plot(..., color=CHART['1'])，禁止写字面 hex
```

**落库后的验收动作（三行命令，照抄即可）**：
```python
from matplotlib import font_manager
print(font_manager.findfont('Microsoft YaHei'))          # 不能是 dejavu 路径
import matplotlib.pyplot as plt; plt.title('中文测试'); plt.savefig('t.png'); # 肉眼确认无方框
```
`findfont` 返回 `...dejavu...` 就说明前 6 个族名全没命中，此时应把 `font.sans-serif` 打印出来对照系统字体列表（`font_manager.fontManager.ttflist`），而不是继续加族名。

**图表容器**：`--s-inset` 底 + 1px `--n-200`，圆角 2px，内边距 0（图自行 `subplots_adjust`）；轴标题与刻度不旋转（空间不足时缩字号，不旋转 90°）；图例不描边框；网格只保留主网格。

**工具栏**（matplotlib 原生导航栏）：统一 20px 图标、`--n-0` 底、悬浮 `--s-hover`、下边 1px `--n-200`，并与页面右侧坐标读数（`(x, y) = (0.937, 0.835)`）同一行右对齐——现状 00 页导航栏图标大小不一、间距混乱。

---

## 5. 布局与栅格

| 断点 | 窗口宽 | 主结构 | 说明 |
|---|---|---|---|
| XL | ≥1440 | 左导航 232 + 主区 1fr + 右栏 340 | 三栏；右栏可折叠 |
| L | 1180-1439 | 左导航 200 + 主区 1fr（右栏并入主区下方） | 默认最大化时绝大多数用户在此档 |
| M | 1024-1179 | 左导航 176 + 主区 1fr | 最小窗口；KPI 由 4 列降 2 列；表单由双列降单列 |

- 页面外边距：`--sp-6` 16px（≥1180）/ `--sp-4` 8px（1024-1179）。
- 列间距：`--sp-4` 8px；区块上下间距 `--sp-5` 12px。
- 任何容器都必须设 `setMinimumWidth` 防空态塌陷：表单卡 280、结果卡 320、图区 320、左导航 176。
- **多列指标卡的最小宽 = 列数 × 72 + 20**（72 是 §4.6 数值列绝对下限，20 是左右 padding）。例：4 列指标 → 308px，容器给 320 只差 12px 就会截断，应给 **≥340px**。这条是 `04 页左栏按 §4.6 下限算出来会差 8px` 的直接修正，改列宽时先算这个数。
- 1024×640 下**不允许**出现横向滚动条：所有 `QComboBox/QLineEdit` 加 `setMaximumWidth(320)`，所有表格首列 stretch 且 `minimumSectionSize=56`。

---

## 6. QSS 实现约定与限制

### 6.1 限制清单（写死在脑子里）

| QSS 能力 | 现实 | 替代方案 |
|---|---|---|
| `box-shadow` | **不支持** | 用底色差 + 描边分层（§3.2）；浮层用 `QGraphicsDropShadowEffect` |
| `transition` / `animation` | **不支持** | 不做过渡；状态切换瞬间完成 |
| CSS 变量 `var(--x)` | **不支持** | Python 侧 `string.Template` 插值（§6.2） |
| `flex` / `gap` | **不支持** | `QBoxLayout` + `setSpacing` + `addSpacing` |
| `outline` | **不生效** | 聚焦用 `border-color` 换色（§3.7） |
| `::before/::after` | **不支持** | 需要装饰条就加一个真 QFrame / QLabel |
| `border-right: none` 的末列选择 | **不支持 `:last`** | 改用 `setShowGrid(False)` + `::item { border-bottom }` |
| `::down-arrow` 三角技巧 | **不支持** | `image: url(svg)` 或沿用原生箭头 |
| 选择器继承 | 子控件上的 `setStyleSheet` 会**覆盖**父级规则 | 只保留一个全局 QSS + `setProperty` 选择器 |

### 6.2 令牌插值写法（替代 CSS 变量）

```python
from string import Template

T = {
    'n0': '#FFFFFF', 'n100': '#F5F7FA', 'n200': '#E7ECF2', 'n300': '#D2DAE3',
    'primary': '#2F6A8C', 'primary_hv': '#3A7B9F', 'primary_active': '#24546F',
    # ... §3 全部令牌
}
QSS = Template(MAIN_STYLESHEET_TEMPLATE).substitute(T)   # 模板里写 $primary、$n200
app.setStyleSheet(QSS)
```
用 `string.Template`（`$name`）而不是 `str.format`（`{name}`），因为 QSS 本身大量使用 `{ }`，两者混用会互相转义。

### 6.3 消灭内联样式的三个动作

1. **全量删除** 各面板的 `setStyleSheet(...)` 调用（13 个文件、本机统计 113 处调用点，其中 `game_panel.py` 30 处属 2048 游戏页，**豁免**）。
2. 需要变体时用属性：`btn.setProperty('variant', 'primary')`，QSS 侧 `QPushButton[variant="primary"]`。
3. 属性运行中改变后必须重新抛光：
```python
def repolish(w):
    w.style().unpolish(w); w.style().polish(w); w.update()
```

### 6.4 类型选择器会命中子类（07 页文字鬼影的真实根因）

Qt Style Sheet 的类型选择器**不是精确匹配，而是 `inherit` 匹配**：`QFrame { ... }` 会同时命中 `QLabel`（`QLabel → QFrame → QWidget`）、`QAbstractScrollArea` 等所有子类。

**改造前** `ui_theme.py` 用 `QWidget { font-family; font-size; color }`，把 `QTabBar::tab`、`QHeaderView::section`、`QStatusBar` 全染成同一色。**该问题已修复**：现在 `ui_theme.py:147-150` 的 `QWidget` 规则只保留 `font-family`，颜色与字号改由逐个控件规则承担。所以这一条**不需要再改第二遍**——若你在评审时看到旧文档写"现有代码是全染"，那是改造前的描述。

**07 页欢迎区文字叠压的根因就在这里**：某人写了
```css
QFrame { padding: 14px; border: 1px solid #E2E8F0; border-radius: 10px; background: #FFF; }
```
于是卡片内**每一个 QLabel 都被套上 1px 描边 + 14px 内边距**，几十个标签各画一个圆角框，文字互相压成鬼影。同类写法 `calibration_panel.py:364` 的 `_create_summary_box` 也用了裸 `QFrame`，靠给每个 label 补 `border: none` 兜住了，但 `padding` 仍在生效，只是不明显。

**四条硬规则**
1. **容器类选择器必须带 objectName**：`QFrame#summaryBox`、`QFrame#kpiCard`、`QWidget#pageHeader`。不带 `#` 的类型选择器只允许出现在**叶子控件**上（`QPushButton`、`QLineEdit`、`QLabel#...` 之外不写 `QLabel { border }` 这类）。
2. **`QWidget` 选择器只允许写 `font-family`**（其余颜色/字号逐个控件指定），或改用 `QMainWindow QWidget` 限定层级——但前者更安全。
3. 需要"一类容器统一外观"时，给这些容器统一 `objectName` 或统一 `setProperty('role','card')`，用 `[role="card"]` 命中，**不要**用类型名。
4. **`QLabel` 类型规则只提供兜底默认，任何承载语义的 label 必须有 `objectName`**。现状 `ui_theme.py:151` 有 `QLabel { color: $n700; font-size: $fs13; background: transparent; }`：ID 选择器特异性更高，所以 `#paramKey` / `#paramVal` / `#resultValue` / `#hintText` / `#kpiLabel` 不会被它污染；但**没有 ID 的 label 会静默继承 `n700` + `13px`**，与说明列要求的 `--n-600` / `--fs-12` 直接冲突。因此：说明列、空态提示、KPI 标签、单位 label **一律给 objectName**，不允许裸 `QLabel` 承载语义。

**自查命令（全文唯一版本，§10 验收同此）**：
```bash
# 容器类裸类型选择器：必须返回空
grep -rnE "^\s*(QFrame|QWidget)\s*\{" radar_tool/*.py \
  | grep -vE "ui_theme\.py|game_panel\.py"

# QLabel 只允许写颜色/字号，出现边框或内边距即违规
grep -rnE "^\s*QLabel\s*\{[^}]*\b(border|padding|margin)" radar_tool/*.py \
  | grep -vE "ui_theme\.py|game_panel\.py"
```
命中一行就是一处潜在的文字鬼影。

**两处豁免，写清楚免得队友困惑**
- `ui_theme.py`：全局 QSS 里 `QWidget { font-family }` 是唯一允许的类型选择器（只写字体族，不写颜色/描边），否则字体无法全局继承。
- `game_panel.py`：摸鱼游戏页，不在 9 个页签内、不参与视觉规范。**已实测确认它没有任何裸类型选择器**（`grep` 结果为空），所以排除它不会漏掉真实缺陷——这条豁免是"确认无害"而非"放任"。若将来游戏页新增了 `QFrame { … }`，仍在排除名单里，但那是新增缺陷，应在 code review 时拦截。

`QLabel` 没进第一条命令，是因为 `QLabel { color: …; font-size: … }` 作为全局默认色是**合法且必要**的；危险的是给它写 `border` / `padding`——那才会让每个标签变成一个小方框。所以拆成第二条精确检查。

---

## 7. 图标策略

**问题**：页签上 9 个位置只有 4 个有 emoji（📡🧮📋📐），按钮上 emoji 与文字混排（📂 🗑️ ✏️ 💾 🔄），且 emoji 在不同 Windows 版本渲染宽度不同（16/18/20px 不定），直接破坏对齐与页签宽度预算。

**方案**：
1. 功能图标统一为 **16px 单色线性 SVG**（`stroke-width: 1.5`，`stroke` 取 `--n-600`，激活态取 `--primary`），或直接复用 `ui_theme.ICON_MAP` 里的 `QStyle` 标准图标。
2. 页签**不放图标**（省 160px 宽度，换取 1024px 下不滚动）。
3. emoji 只允许出现在**纯装饰、无功能语义**的位置，且每页 ≤1 处。

| 位置 | 允许 | 禁止 |
|---|---|---|
| 页签 | 纯文字（推荐），或 16px 单色 SVG | emoji |
| 工具栏/按钮 | `QStyle` 标准图标 或 16px SVG + 文字 | emoji 与文字混排 |
| 状态栏 | 无图标，纯文字 | 任何图标 |
| KPI 卡 | 无图标，或右上角 14px 单色 SVG | emoji |
| 表头/徽章 | 无图标 | emoji |
| 空态 | 1 个 32px 单色描边 SVG | 插画、emoji |
| 对话框正文 | — | 用 emoji 表达状态（🔴/✅ 表示结果，见 `calc_ui.py` 现状） |
| 2048 游戏页 | 内部保留（用户明确要求的彩蛋，`#eee4da` 等色值豁免） | 扩散到其他页面 |

**实现**：`ICON_MAP` 扩展为 `{'open': ..., 'export': ..., 'run': ...}`，统一由 `set_button_icon(btn, name)` 设置；颜色差异用 `QIcon.addPixmap(pixmap, QIcon.Normal, QIcon.On/Off)` 给两态图，**不要**用样式表改图标色。

---

## 8. 禁止清单（以后不许再出现）

> **这 19 条的共同前提：规范文档是工程师的抄写源。**
> 文档里出现的任何字符都可能被逐字抄进代码——所以「排版好看」必须让位于「可被复制、可被断言」。
> 本文件与配套 HTML 预览稿都按此标准自查过：非 U+002D 减号 0 处（禁令条款内为指认字符保留的 3 个字形除外）、`U+3000`/`U+200B` 全角与零宽空格 0 处。
> 写新规范、改示例、截设计稿时都按这一条过一遍。

1. **内联魔法色**：任何 `.py` 里出现 `#RRGGBB` 字面值（`game_panel.py` 除外），一律视为缺陷；只能引用 §3 令牌。
2. **渐变按钮**：`qlineargradient` 全部删除（含 `PRIMARY_BUTTON_STYLE`、`CALC_BUTTON_STYLE`）。
3. **2px 描边公式块 / 强调块**：描边只有 1px（页签下划线、强调条、图表 ±0 线除外）。
4. **emoji 当功能图标**：页签、按钮、KPI、表头、状态栏禁用 emoji。
5. **随意的控件高度**：只允许 28 / 32 / 36 三档；`min-height: 44px`（`CALC_BUTTON_STYLE`）这种巨型按钮不再出现。
6. **超过 6px 的圆角**：8px / 10px 圆角（现状 `ui_theme.py` 的 `border-radius: 8px/10px`）全部改为 2/4/6。
7. **绿色主按钮**：`#4CAF50` 加载数据、`#22c55e` 执行，主操作一律 `--primary`。
8. **控件拉满整行**：输入类控件宽度 > 320px（路径输入除外）。
9. **同页两套视觉**：一个页面内出现两种按钮形态/两种表头/两种字号体系。
10. **状态双写**：同一条消息同时出现在页内文本区与状态栏。
11. **空态 = 空卡**：没有数值的 KPI 卡必须显示 `--` 与下一步提示，不允许留一个 3 倍大的空盒子。
12. **彩色背景整块铺底**：整块 `--primary` / 语义色填充只允许出现在按钮与徽章，不允许整卡铺色。
13. **未经声明的字体族**：新增字体族必须先进 §3.5。
14. **matplotlib 中文字体缺失**：任何新图必须走 `plotting.py` 的全局 rcParams。
15. **无 objectName 的裸类型选择器作用于容器类**：`QFrame { … }` / `QWidget { … }` / `QLabel { border: … }` 全部禁止。类型选择器继承匹配子类，是 07 页文字鬼影的直接成因（§6.4）。容器一律 `QFrame#objectName` 或 `[role="card"]`。
16. **用字符串填充做列对齐**：`f'{"指标":<16}{"数值":>10}'`、`"─"*62`、`\t` 拼接表格——中文双宽字符下必然错位（§4.5.1）。≥2 列需对齐的信息只能落 `QGridLayout` 或 `QTableWidget`。
17. **用等宽字体"修"中文对齐**：Consolas 不含 CJK，Qt 逐字回退，宽度不可控；等宽族只允许出现在纯数字列。
18. **不得用字符替换制造负号**：数值负号、区间连接、公式减号**一律半角连字符 `-`（U+002D）**；禁止改用排版减号 `−`（U+2212）、短破折号 `–`（U+2013）、全角连字符 `－`（U+FF0D）。中文破折号 `—`（U+2014，写作 `——`）作为标点合法，但**不得用作减号或区间连接符**。**设计稿（含本规范附带的 HTML 预览稿）与代码评审都必须看这一条**——文档是工程师的抄写源，设计稿里写 `−133.9`，抄进代码就是一个挂测试且极难查的 bug。
19. **用不可见字符做视觉间距**：`U+3000` 全角空格、`U+200B` 零宽空格、`\t`、连续半角空格，**不得**用于对齐或拉开间距。间距只能来自 `layout->setSpacing()` / `padding` / `margin`。理由：`ResultCard.toPlainText()` 会把它们原样吐出来（ux 规范 §3.6 已把平铺格式写死），测试断言和用户剪贴板都会被弄脏。

> 第 18 条的理由是测试与可复制性，不是排版洁癖：`tests/test_df_accuracy.py:95` 用 `assertIn('-90', result_text.toPlainText())` 断言，一旦在文本渲染或 QSS 层做 `-` → `−` 的替换，这条直接挂；用户把结果复制进 Python / Excel 也解析不了。视觉上 `−` 确实更接近数学符号，但**代价是机器不可读**，不划算。
> 本规范正文与 HTML 预览稿已全量归一为 U+002D（原先草稿里的 `−`/`–` 均为排版残留，已清零）。**除本条禁令为指认字符而列出的三个字形外，文档中不再出现非 U+002D 的减号。**

---

## 9. 迁移映射表（供机械替换）

### 9.1 `ui_theme.py` 现存值

| 旧值 | 旧用途 | 新令牌 | 新值 |
|---|---|---|---|
| `#f5f7fb` | QMainWindow 背景 | `--s-app` | `#F5F7FA` |
| `#1f2937` | QWidget 正文色 | `--n-700` | `#47525F` |
| `#0f172a` | 组框标题 | `--n-800` | `#2C353F` |
| `#ffffff` | 组框/输入/按钮底 | `--n-0` | `#FFFFFF` |
| `#d7dee9` | 组框/输入描边 | `--n-200`（容器）/ `--n-300`（控件） | `#E7ECF2` / `#D2DAE3` |
| `#cfd8e3` | 按钮描边 | `--n-300` | `#D2DAE3` |
| `#eef4ff` | 按钮 hover 底 | `--s-hover` | `#EFF3F8` |
| `#dbe7ff` | 按钮 pressed 底 | `--s-sel` | `#E4EEF6` |
| `#7c9cff` | 按钮 hover 描边 | `--n-400` | `#AEB9C6` |
| `#1e40af` / `#1e3a8a` | 按钮 hover/pressed 文字 | `--primary-text` / `--primary-active` | `#1F4A62` / `#24546F` |
| `#f3f4f6` | 禁用底 | `--n-100` | `#F5F7FA` |
| `#9ca3af` | 禁用文字 | `--n-400` | `#AEB9C6` |
| `#dbeafe` | 选中底 / selection | `--s-sel` | `#E4EEF6` |
| `#111827` | 选中文字 | `--n-900` | `#111820` |
| `#eef2f7` | 状态栏底 | `--n-100` | `#F5F7FA` |
| `#334155` | 状态栏文字 | `--n-600` | `#64717F` |
| `#4f8cff` → `#2f6fe4` | 主按钮渐变 | `--primary`（**取消渐变**） | `#2F6A8C` |
| `#5f97ff` → `#3b78eb` | 主按钮 hover 渐变 | `--primary-hv` | `#3A7B9F` |
| `#2563eb` → `#1d4ed8` | 主按钮 pressed / calc 渐变 | `--primary-active` | `#24546F` |
| `#1d4ed8` | 主按钮描边 | `--primary`（1px） | `#2F6A8C` |
| `#fff7ed` | 警告按钮底 | `--warning-bg` | `#FBF2DE` |
| `#9a3412` | 警告按钮字 | `--warning-text` | `#7A5409` |
| `#fdba74` | 警告按钮描边 | `--warning-border` | `#E4C88C` |
| `#ffedd5` / `#fed7aa` | 警告 hover/pressed | `--warning-bg-hv` | `#F7E7CB` |
| `#94a3b8`（calc 禁用底） | 禁用主按钮底 | `--n-400` | `#AEB9C6` |
| `#e2e8f0`（calc 禁用字） | 禁用主按钮字 | `--n-0` | `#FFFFFF` |
| `border-radius: 8px / 10px` | 组框/按钮/输入 | `--r-2` 4px（卡、按钮、组框）/ `--r-1` 2px（输入、徽章） | — |
| `min-height: 44px` / `font-size: 16px` | calc 巨型按钮 | `--h-lg` 36px / `--fs-13` 10pt | — |

### 9.2 散落在面板里的值

| 旧值 | 出处（典型） | 新令牌 | 新值 |
|---|---|---|---|
| `#4CAF50` | 可视化页「加载数据」绿按钮 | `--primary`（改主色，不再用绿） | `#2F6A8C` |
| `#2196F3` | 可视化页「绘制」蓝按钮 | `--primary` | `#2F6A8C` |
| `#FF9800` | 可视化页「清空」橙按钮 | `--warning`（仅描边/图标） | `#B07C16` |
| `#2563eb` / `#1d4ed8` | 指标计算器、任务入口 | `--primary` / `--primary-active` | `#2F6A8C` / `#24546F` |
| `#3b82f6` / `#60a5fa` / `#93c5fd` / `#bfdbfe` | 各类 hover / selection | `--primary-hv` / `--primary-border` / `--s-sel` | `#3A7B9F` / `#BFD5E2` / `#E4EEF6` |
| `#64748b`（26 处） | 说明文字、图标 | `--n-600` | `#64717F` |
| `#475569` | 正文 | `--n-700` | `#47525F` |
| `#1e293b` / `#172033` / `#28323f` / `#33414f` / `#5c6b7d` / `#9fb0c0` / `#0d1b36` / `#0a1628` / `#1e3a5f` | 试验记录/账本自造深色 | `--n-900` / `--n-800` / `--n-700` / `--n-600` | 按层级归并 |
| `#f9f6f2`（9 处） | 试验记录暖纸色 | `--n-100`（废止暖色） | `#F5F7FA` |
| `#f1f5f9` / `#f4f7fa` / `#f8fafc` / `#e6eef6` / `#eff6ff` | 各类浅底 | `--n-100` / `--s-inset` / `--s-hover` | `#F5F7FA` / `#F7F9FB` / `#EFF3F8` |
| `#cbd5e1` / `#b6c2cf` | 描边 | `--n-300` | `#D2DAE3` |
| `#dc2626` / `#ef4444` / `#e5484d` / `#b91c1c` / `#b71c1c` | 危险 | `--danger` / `--danger-text` | `#AC3B41` / `#85272C` |
| `#fca5a5` / `#fecaca` / `#fee2e2` / `#fef2f2` / `#ffebee` | 危险浅底/描边 | `--danger-border` / `--danger-bg` | `#E2B0B3` / `#FBEBEC` |
| `#22c55e` / `#10b981` / `#16a34a` / `#059669` / `#0f766e` | 成功 | `--success` | `#1F7A57` |
| `#86efac` / `#4ade80` / `#46a758` / `#ecfdf5` / `#e8f5e9` / `#1b5e20` / `#166534` | 成功浅底/字 | `--success-border` / `--success-bg` / `--success-text` | `#A8CDBC` / `#EAF3EE` / `#175C42` |
| `#f59e0b` / `#d97706` / `#f5a524` / `#eab308` / `#ca8a04` / `#b45309` / `#a16207` / `#e65100` | 警告 | `--warning` / `--warning-text` | `#B07C16` / `#7A5409` |
| `#fefce8` / `#fef3c7` / `#fff8e1` | 警告浅底 | `--warning-bg` | `#FBF2DE` |
| `#6366f1` / `#8b5cf6` / `#7c3aed` / `#ec4899` / `#14b8a6` | 图表/装饰色 | `--chart-5` / `--chart-4` / `--chart-7` | 见 §3.4 |
| `#666666` / `#000` | 杂项文字 | `--n-800` | `#2C353F` |
| `#eee4da` / `#ede0c8` / `#edcf72` / `#edcc61` / `#edc850` / `#edc53f` / `#edc22e` / `#f67c5f` / `#f59563` / `#f2b179` / `#f65e3b` / `#cdc1b4` / `#776e65` | **2048 游戏页专用** | 豁免（仅限 `game_panel.py` 内部） | — |

### 9.3 统计口径

- 全工程 `setStyleSheet(` 调用点（迁移前基线，实施中递减）：**113 处 / 13 个文件**（`game_panel.py` 30、`exp_recorder.py` 16、`calibration_panel.py` 12、`main_window.py` 9、`compare_data.py` 9、`compare_analysis.py` 9、`array_designer.py` 9、`coord_ledger_panel.py` 7、`visualization_panel.py` 5、`format_conversion_panel.py` 5、`calc_ui.py` 5、`ui_theme.py` 3、`interferometer_sim.py` 3）。
- 其中 30 处属游戏页豁免，**需要处理的有效调用点 83 处**。
- 目标终态：`ui_theme.py` 之外 **0 处**；`ui_theme.py` 内 1 个全局 QSS 模板 + 令牌字典。

### 9.4 近似色归并（不要一对一平移）

**迁移的总原则：按"色系"归并，不按"色值"一对一保留。** 基线（迁移前，排除 `game_panel.py`）统计：

| 色系 | 基线唯一色值数 | 出现次数 | 归并到 | 结果 |
|---|---|---|---|---|
| 蓝（含深灰蓝、浅蓝底、蓝描边） | **21** | 127 | `--primary` 的 3 个状态档 + 3 个档位（bg/border/text） | 21 → **1 个色相 × 6 档** |
| 绿 / 青绿 | **13** | 26 | `--success` 四档 | 13 → **1 个色相 × 4 档** |
| 红 | **10** | 29 | `--danger` 四档 | 10 → **1 个色相 × 4 档** |
| 琥珀 / 橙（警告） | **17** | 25 | `--warning` 五档（含 `bg-hv`） | 17 → **1 个色相 × 5 档** |
| 紫 / 粉 / 青（图表与装饰） | **5** | 5 | `--chart-4/5/7` | 5 → **3 个图表令牌** |
| 中性 / 灰蓝 | **30+** | 30+ | `--n-0`~`--n-900` + `--s-*` | 30+ → **10 + 5** |
| **合计** | **约 106** | **242** | **46 个令牌**（含 24 个非灰阶） | 唯一色值降到 **43%** |

**六个蓝必须收敛成一个色相**（这是"配色不统一"最刺眼的部分）：

| 基线值 | 频次 | 归并到 | 理由 |
|---|---|---|---|
| `#2563eb` | 15 | `--primary` `#2F6A8C` | 主操作填充，主色基准 |
| `#1d4ed8` | 21 | `--primary-active` `#24546F` | 按下态 / 旧 pressed 渐变终点 |
| `#1e40af` | 5 | `--primary-text` `#1F4A62` | 旧 hover 文字色，作浅底上的可读文字 |
| `#3b82f6` | 4 | `--primary-hv` `#3A7B9F` | 旧 hover 填充 |
| `#4f8cff` → `#2f6fe4` | 1+1 | `--primary`（**取消渐变，取单色**） | 渐变删掉，落回主色 |
| `#5f97ff` → `#3b78eb` | 1+1 | `--primary-hv`（**取消渐变**） | 同上，落回 hover 单色 |

绿 `#10b981 / #22c55e / #16a34a / #059669 / #0f766e / #4caf50` → 全部 `--success` `#1F7A57`；浅绿底（`#ecfdf5 / #e8f5e9 / #86efac / #4ade80`）→ `--success-bg` / `--success-border`。
红 `#dc2626 / #ef4444 / #e5484d / #b91c1c / #b71c1c` → 全部 `--danger` `#AC3B41`（文字用 `--danger-text` `#85272C`）。
琥珀 `#f59e0b / #f5a524 / #eab308 / #ca8a04 / #d97706 / #b45309 / #a16207 / #e65100 / #ff9800` → 全部 `--warning` `#B07C16`；浅底 `#fff8e1 / #fefce8 / #fef3c7 / #fff7ed` → `--warning-bg`。

**为什么不做 alpha 混合过渡**：QSS 支持 `rgba()`，但同一语义在不同页面上用了不同 alpha 就会重新长出"近似色"。语义色只有 §3.3 那几档，需要更淡就用 `--*-bg`，**不允许**写 `rgba(47,106,140,0.12)`。

**验收口径**：迁移完成后，非灰阶唯一色值应当等于 §3.3/§3.4 声明的数量（语义 4 组 × 4~5 档 + 图表 8 色 ≈ 24 个）。多于这个数就是又长出近似色了。

---

## 10. 落地顺序（给工程实现方）

1. 重写 `ui_theme.py`：令牌字典 + `string.Template` + 全局 QSS（覆盖 §4.1/4.3/4.6/4.7/4.9/4.10/4.11 七处）。
2. `main_window.py`：页签名去 emoji、状态栏换令牌色、`QWidget` 选择器收窄。
3. 删 `CALC_BUTTON_STYLE` / `PRIMARY_BUTTON_STYLE` / `WARNING_BUTTON_STYLE`，改 `setProperty('variant', ...)`。
4. 按 §9 迁移映射表逐文件替换内联样式（先 4 个量化页：可视化、指标计算器、测向校正、格式转换）。
5. 修 5 个硬缺陷（每一项都是"用户直接能看出来"级别的）：
   - 00 页「保存范围预…」按钮压字（布局溢出）
   - 02/04 页中文渲染为 □□□□（`plotting.py` 的 rcParams，§4.14）
   - 04 页表格列宽不足导致 `0...` 截断（`minimumSectionSize` + stretch）
   - 07 页欢迎区文字鬼影（裸 `QFrame` 选择器，§6.4）
   - 指标计算器/阵列设计页结果区横竖错位（`array_designer.py:766` 等宽字符填充，§4.5.1）
6. 最后做 07 页（欢迎区重排为 §4.3 组框 + §4.5 卡）与 08 页（表头压边框）。

**验收标准（六条命令 + 两档截图）**
```bash
# 1) 除令牌字典与 matplotlib rcParams 外，不得有颜色字面值
grep -rn --exclude-dir=__pycache__ "#[0-9a-fA-F]\{6\}" radar_tool/ \
  | grep -vE "game_panel|ui_theme.py|plotting.py"
# 2) 容器类不得有裸类型选择器（07 页文字鬼影根因；与 §6.4 命令完全一致）
grep -rnE "^\s*(QFrame|QWidget)\s*\{" radar_tool/*.py | grep -vE "ui_theme\.py|game_panel\.py"
grep -rnE "^\s*QLabel\s*\{[^}]*\b(border|padding|margin)" radar_tool/*.py \
  | grep -vE "ui_theme\.py|game_panel\.py"
# 3) 不得用字符串填充做列对齐
grep -rnE ":<[0-9]+|:>[0-9]+|\"─\"\s*\*" radar_tool/ --exclude-dir=__pycache__
# 4) 不得有残留的内联样式
grep -rn "setStyleSheet" radar_tool/ --exclude-dir=__pycache__ | grep -v game_panel | grep -v ui_theme
# 5) 负号必须是 U+002D
grep -rn --exclude-dir=__pycache__ $'\u2212\|\u2013\uff0d' radar_tool/*.py
# 6) 不得用不可见字符做间距
grep -rn --exclude-dir=__pycache__ $'\u3000\|\u200b' radar_tool/*.py
```
六条命令都必须返回空（README 式说明性输出不算）。两处豁免仅限命令 1/2/4：`ui_theme.py` 的 `QWidget { font-family }` 与 `game_panel.py`（详见 §6.4 的"两处豁免"）。

此外 1024×640 与 1560×900 两档截图：无横向滚动、无元素重叠、无截断文字、图表中文无方框。

---

## 11. 首次实现的复核意见（2026-11-14）

> **记录人说明**：视觉负责人在复核环节遇到接口配额限流（429）未能亲自完成，本节由主理人依据
> `var/design_shots_v3/` 的 18 张实测截图（1024×640 / 1560×900 两档）、代码实测与全量测试结果
> 代为记录，判定以事实为准，不代替视觉负责人的专业签字。

### 11.1 还原度判定

| 检查项 | 规范要求 | 实现现状（实测） | 判定 | 若偏差，最小修法 |
|---|---|---|---|---|
| 页签宽度预算 | 1024 宽下 9 页签不出现滚动箭头 | 全称在 10pt 下实测需 **1471px**（规范原估 941px），故改为 <1280 时切短名 + 9pt + 8px 内边距；实测 942px，两档截图箭头均消失 | 达标（实现路径修正，见 11.2） | — |
| 页签形态 | 2px 下划线，非 pill | 下划线激活态、无图标、纯文字 | 达标 | — |
| 层次建立 | 只用底色差 + 1px 描边 + 字重，零阴影 | 白卡 / inset 灰底 / 1px 描边，无阴影 | 达标 | — |
| 按钮变体 | 只有 primary / secondary / ghost / danger 四种 | 全局 `[variant=...]` 属性选择器；原渐变与 2px 描边已删 | 达标 | — |
| KPI / 结果卡 | 数值与单位分离、基线对齐、等宽 | `0.01`(24pt 等宽) + `kHz`(10.5pt 常规) 基线对齐；参数表 2 列；提示条独立 | 达标 | — |
| 表格 | 无竖网格线、数值右对齐等宽、表头带单位 | 04 页 `ResizeToContents` + 末列 stretch、`-0.052 / 0.000 / 1.00` 完整显示 | 达标 | — |
| 语义色用途 | 只用于状态，不用于普通按钮填充 | 徽章 / `textTone[tone]` / hintBar 三变体；主按钮统一钢青蓝 | 达标 | — |
| 空态 | 给「下一步动作」提示，不留空卡 | 结果卡显示 `--` +「录入参数后自动计算」 | 达标 | — |
| 图表中文 | 中文标题/轴标签无方框 | `msyh.ttc` 回退链生效，标题/轴/图例全部正常 | 达标 | — |
| 内联样式与魔法色 | 令牌之外归零 | `setStyleSheet`、`#RRGGBB`、U+2212 三项 grep 均为 **0**（豁免见 11.3） | 达标 | — |
| emoji 退出功能位 | 页签、按钮、表头禁止 | **页签与结果区已清除**；部分工具栏按钮仍混用 emoji 作功能图标 | **偏差（P1）** | 换 `ICON_MAP` 里的 `QStyle` 标准图标，约 10 处 |
| 控件宽度 | 输入类 ≤320px、主按钮不拉满 | 输入框 320px、主按钮上限 240px | 达标 | — |

### 11.2 规范自身需要修正的三处事实（实测反证）

1. **§4.1 宽度预算算错了**。原文按「53 汉字 × 13px = 689px」估算，实测 `QFontMetrics('Microsoft YaHei', 10)`
   下 53 汉字占 **1219px**（约 23px/字，10pt 在本机 DPI 下的实际值），加 9×28px 内边距共 1471px。
   结论：**单靠削减 padding 无法让全称页签塞进 1024**，必须走短名或降字号。实现采用响应式短名，
   全称由 tooltip 与各页 `PageHeader` 承载，未损失可辨识性。
2. **§4.6 的 `::item { padding: 0 10px }` 会触发 elide**。实测 Consolas 10pt 下 `-0.052` 占 **78px**，
   88px 列减去 20px padding 只剩 68px 内容区 → Qt 渲染成 `-0....`。实现改为 `padding: 0 6px`，
   并对数值表用 `ResizeToContents` 让列宽随内容自适应，而非手写固定列宽。
3. **§3.3 状态机范围已收窄**：只服务 `ResultCard` / `KpiCard`，`QTableWidget` 空态走 §4.12 表内说明，
   不加遮罩层（已在正文补入）。

### 11.3 合理豁免与遗留

- **豁免**：`ui_theme.py`（令牌源）、`app_config.py`（色板源）、`game_panel.py`（2048 彩蛋）、
  `coord_3d.py`（PyVista 3D 视口必须保持深色主题 `SCENE_BG #1d2530`，改浅色反而看不清坐标轴）。
- **P1 遗留**：部分按钮的 emoji 功能图标；`interferometer_sim.txt_stats` 与 `compare_analysis.txt_cmp_stats`
  本期未换成结果卡（前者被 `test_qt_panels.py:153` 的精确相等断言锁死，换结构收益不抵风险），仅套了只读区样式。
- **非缺陷说明**：05 页在 1560×900 下表单区有约 120px 灰底留白，在 1024×640 下自动消失。这是
  `QScrollArea` 取 stretch=1 以保证公式区与结果卡在小窗口下始终可见的防御性布局，**不要**为消除
  大屏留白而把 stretch 改成 0，否则 640 高窗口会裁掉结果卡。

### 11.4 验证结论

- 全量测试：`242 passed, 1 skipped`（跳过项为 Windows symlink 权限 `[WinError 1314]`，与代码无关）。
  首次运行时出现的 31 个 `PermissionError` 全部发生在 pytest 的 `tmp_path` fixture 阶段，根因是系统
  临时目录 `C:\Users\...\AppData\Local\Temp\pytest-of-20693` 拒绝访问，改用 `--basetemp` 后消失。
- 截图：`var/design_shots_v3/` 共 18 张（两档 × 9 页），05 页均带真实计算结果，用于核对主值/单位/参数表。
- 三项验收 grep：内联 `setStyleSheet` = 0、令牌外 `#RRGGBB` = 0、U+2212 = 0。
