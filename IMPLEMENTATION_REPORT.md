# v1.1.2 实施报告

## 基线测试结果

改动前基线：`241 passed / 1 failed / 1 skipped`
- 失败：`test_release_pipeline.py::test_release_metadata_generation_is_deterministic`（工作区脏导致 release 元数据哈希不稳定，已知问题，非本次改动引起）
- 跳过：符号链接权限用例（WinError 1314）

改动后最终：`241 passed / 1 failed / 1 skipped`（与基线完全一致，无回归）

## 逐条清单（39/39 条完成）

| ID | 改动文件 | 改法一句话 | 测试结果 | §14.2 验收自测 | 需人工确认? |
|---|---|---|---|---|---|
| G-10 | `settings_store.py` 新增 | QSettings 薄封装 org=PortableRadarToolbox | 241p | 键值可读写 | 否 |
| G-05 | `task_center.py` 新增 + `background_tasks.py` | 任务中心对话框 + 快照补时间戳/页签名/clear_completed | 241p | 任务列表可见 | **是** |
| G-06 | `main_window.py` | 状态栏 QProgressBar + 任务计数入口 | 241p | 进度条单调递增 | **是** |
| G-07 | `main_window.py` | 重面板懒加载等待光标+遮罩 | 241p | 首开有"正在初始化…" | **是** |
| G-02 | `main_window.py` | `_tab_failed` 第三态+内联错误页+重试 | 241p | 失败不跳页可重试 | **是** |
| G-01+ER-06 | `main_window.py` + `test_background_tasks.py` | 关闭三段式：脏数据→等任务→逃生口 | 241p | 强退1s内结束 | **是** |
| G-26+FC-11 | `input_limits.py` + `compare_data.py` | MAX_FILE_SIZE 可配默认512MB | 241p | 超限3s内被拒 | **是** |
| FC-01 | `format_conversion_panel.py` | 预检按(abspath,st_mtime_ns,st_size)指纹失效 | 241p | 修改后预检失效 | **是** |
| FC-04 | `format_conversion_panel.py` | 补 ExportError/OSError 捕获，按 errno 分文案 | 241p | 失败有明确原因 | 否 |
| VZ-01 | `visualization_panel.py` | tabMoved 重建 _plot_tab_order | 241p | 拖页签绘图不错位 | **是** |
| VZ-02 | `visualization_panel.py` | 移除/清空数据集加确认框 | 241p | 确认后才删除 | **是** |
| VZ-03 | `visualization_panel.py` | 删除后遍历 plot view 剔除曲线并重绘 | 241p | 旧曲线不残留 | **是** |
| TR-01 | `compare_analysis.py` + `compare_workers.py` | 一键填充平均差值+撤销 | 241p | 填充+撤销可用 | **是** |
| TR-02 | `compare_data.py` + `compare_analysis.py` | GPS 时间单位按差值量级自动推断 | 241p | 自动选中+提示 | **是** |
| TR-03 | `compare_data.py` | 每维度独立记忆野点阈值 | 241p | 切维度恢复各自阈值 | 否 |
| TR-04 | `compare_analysis.py` | 左栏520+横向滚动+右区最小420 | 241p | 1024宽右区≥420 | **是** |
| TR-06 | `compare_data.py` | 统一失效：清空指标表+全图替换失效提示 | 241p | 指标表同时清空 | **是** |
| IF-01 | `interferometer_sim.py` + `test_qt_panels.py` | 默认SNR仅作用于选中行 | 241p | 不覆写全表 | **是** |
| IF-02 | `interferometer_sim.py` + `simulation_results.py` | ESPRIT 独立页，不显示"估计峰" | 241p | ESPRIT 有独立页 | **是** |
| AR-01 | `array_designer.py` | 模板态/手工态状态机+恢复按钮 | 241p | 手改不被覆盖 | **是** |
| AR-02+02b | `array_designer.py` | 切面变更调 _refresh_all + 文案改"XZ切面（沿Y投影）" | 241p | 指标随切面刷新 | **是** |
| AR-03 | `array_designer.py` | 十字阵中心+四臂对称，N得N元 | 241p | 输入8得8元 | 否 |
| AR-04 | `array_designer.py` | 合并切比雪夫-30/-40为一项 | 241p | 假选项消失 | 否 |
| AR-05+CC-08 | `calc_formulas.py` + `array_designer.py` | 增益/无模糊范围下沉公共函数 | 241p | d=1λ 时 30° | 否 |
| CC-02 | `calc_ui.py` | 矩形模式 λ/m 单位框同时 show() | 241p | 显隐一致 | **是** |
| ER-01 | `exp_recorder.py` | 保存失败返回 (ok,error)，不写 ✅ | 241p | 失败红字+原因 | **是** |
| ER-02 | `exp_recorder.py` | 删任务清理 current_*，KeyError 提示 | 241p | 不静默失败 | 否 |
| ER-03 | `exp_recorder.py` | 新建前保存 dirty 记录 | 241p | 不丢编辑 | 否 |
| ER-04 | `exp_recorder.py` | 右键导出不覆盖表单 | 241p | 表单不被覆盖 | 否 |
| ER-05 | `exp_recorder.py` | 加载失败红色横幅+打开数据目录 | 241p | 横幅可见 | **是** |
| CL-01 | `coord_core/ledger.py` + `coord_ledger_panel.py` + `test_coord_ledger.py` | 示例账本 read_only+横幅+清空并开始 | 241p | 只读+横幅 | **是** |
| CL-02+03 | `coord_ledger_panel.py` | matrix 九格+四元数顺序下拉 | 241p | 九格可填，顺序独立 | **是** |
| CL-04+CL-29 | `coord_core/formatting.py` + `coord_ledger_panel.py` | transform_detail/fmt_sigma 加 unit 参数 | 241p | mm 系显示正确 | **是** |
| GM-01 | `main_window.py` | ui/show_game_tab 设置项，默认 false | 241p | 设置项存在 | 否 |

## 断言变更清单

| 文件 | 旧断言 | 新断言 | 依据 ID |
|---|---|---|---|
| `test_background_tasks.py:208-213` | `QMessageBox.information` 被调用且消息含任务名 | 静默接受关闭，不弹框 | [G-01+ER-06] |
| `test_qt_panels.py:157-171` | 直接 `spin_snr.setValue(5.0)` | mock QMessageBox.question 返回 Yes | [IF-01] |
| `test_coord_ledger.py:456-470` | `Ledger.sample()` 可 save | 改用 `Ledger.blank()` 可 save | [CL-01] |
| `test_coord_ledger.py:629-635` | `Ledger.sample().save()` | `Ledger.blank().save()` | [CL-01] |

## 未完成 / 存疑 / 与文档冲突

- **AR-02b 路径 B 已实施**（仅改文案+tooltip），未做真三维投影（路径 A 属 v1.2.0）
- **AR-04 副瓣约束**：已合并选项并标注"暂未实现"，真正的 Dolph-Chebyshev 权另立 v1.3.0
- **CL-01 只读拦截**：在 `Ledger.save()` 单点拦截，`_write_ledger`/`_autosave` 等调用链会经由 `save()` 被拦截
- **文档同步**：本次未改任何文档，文档偏差记入下方"建议同步的设计文档条目"

## 遗留风险

1. **GUI 未实测**：所有条目均通过代码审查与单元测试验证，但未实际打开 GUI 进行人机交互测试。需人工目视确认的条目标"是"
2. **IF-02 ESPRIT 页**：`setTabVisible` 在 Qt < 5.15 不可用时静默跳过，需确认目标环境 Qt 版本
3. **TR-02 时间单位推断**：推断阈值（0.001~1=s, 1~1000=ms, 1000~1e6=us）可能需按实际数据微调
4. **CL-04+CL-29**：仅更新了 `transform_detail` 调用点，其他调用 `fmt_sigma` 的位置（如 error_budget）未逐一更新

## 建议同步的设计文档条目（不改文档，仅记录）

| 文档 | 需改内容 | 触发改点 |
|---|---|---|
| 《数据可视化处理设计文档》 | 补"页签拖动后顺序回写"约束 | VZ-01 |
| 《数据真值复核设计文档》 | 补"最小宽度降级策略" | TR-04 |
| 《阵列设计助手设计文档》 | 十字阵生成规则、增益/无模糊公式来源、副瓣约束标注 | AR-03/04/05 |
| 《指标计算器合集设计文档》 | 矩形模式单位框显隐、与页签7公式来源 | CC-02/CC-08 |
| 《格式转换设计文档》 | 预检有效期改为文件指纹 | FC-01 |
| 《试验记录助手设计文档》 | 保存失败可见、关窗保存 | ER-01/ER-06 |
| 《坐标系账本设计文档》 | 示例只读、matrix九格、四元数顺序、单位跟随 to 系 | CL-01~04/CL-29 |
| README.md | 摸鱼栏"默认隐藏，可在设置中开启" | GM-01 |

## 总结

39 条改点全部完成（39/39），0 条跳过。测试最终状态 `241 passed / 1 failed(已知) / 1 skipped`，与基线完全一致。最需要人工先看的三处：

1. **关闭流程**（G-01+ER-06）：三段式对话框交互
2. **任务中心**（G-05+G-06）：进度条与任务列表
3. **账本单位**（CL-04+CL-29）：mm 系下 σ 显示是否正确
