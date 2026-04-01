# ChatGPT 工作记录

这份文档记录当前仓库里已经遇到过的问题、已确认的不稳定点，以及推荐的规避方式。后续继续开发前，建议先看一遍，避免重复踩坑。

## 1. 已遇到的问题

### 1.1 PowerShell profile 会报执行策略错误

现象：

- 默认 PowerShell 启动时，会尝试加载用户 profile
- 当前环境里 profile 脚本执行被系统策略禁止
- 终端会出现 `UnauthorizedAccess` / `PSSecurityException`

影响：

- 不一定会中断所有命令
- 但会污染输出，影响排查问题

建议规避：

- 运行命令时优先使用 `login=false`
- 如果需要手动执行命令，尽量使用 `-NoProfile`

### 1.2 PowerShell 中文输出有乱码

现象：

- `Get-Content` 读取中文 Markdown 时，终端里可能显示乱码

影响：

- 文件本身通常没有坏
- 但终端中阅读很痛苦，容易误判为写入失败

建议规避：

- 优先使用 UTF-8 编码读取
- 必要时先切换控制台编码
- 不要仅凭终端显示判断 Markdown 文件损坏

### 1.3 `rg` 当前环境不可用

现象：

- 直接执行 `rg --files` 时出现“拒绝访问”

影响：

- 无法按默认习惯使用 `ripgrep`

当前替代方案：

- 用 `Get-ChildItem -Recurse -File`

后续建议：

- 等环境稳定后再恢复 `rg`
- 在此之前不要把搜索流程强依赖在 `rg` 上

### 1.4 `apply_patch` 在当前 Windows 沙箱里失败

现象：

- 使用 `apply_patch` 时，返回 `windows sandbox: setup refresh failed`

影响：

- 常规补丁写文件流程不可用
- 需要临时改用 PowerShell 写文件兜底

建议规避：

- 后续若 `apply_patch` 恢复，优先回到标准补丁流程
- 在它恢复前，可用小批次 PowerShell 写文件，但要谨慎记录每次变更

### 1.5 当前目录最初不是 git 仓库

现象：

- `git status` 返回 `not a git repository`

影响：

- 目前没有版本管理保护
- 后续变更较多时，不利于追踪和回滚

建议：

- 在开始较大开发前初始化 git 仓库

## 2. 当前代码层面的不稳定点

### 2.1 依赖还没有固定和安装

当前 Phase A 代码已经按目标技术栈写了基础骨架，但依赖还没正式安装和锁定，例如：

- `PySide6`
- `pydantic`

影响：

- 代码结构已经具备
- 但如果本机还没安装这些依赖，直接运行会失败

建议：

- 下一阶段补 `requirements.txt` 或 `pyproject.toml`
- 在进入 UI 和 Agent 开发前先统一安装依赖

### 2.2 目前只有 Phase A，UI 和 SUMO 主链路还没接上

现状：

- 现在完成的是应用底座、配置存储、项目存储、领域模型
- 还没有正式的主窗口模块
- 还没有 SUMO 文件生成器、仿真运行器、Agent 编排器

影响：

- 当前是“可继续开发的地基”
- 还不是“可用产品”

建议：

- 后续按 `route.md` 的顺序继续推进
- 不要在 Phase A 阶段误以为已经具备仿真能力

## 3. 当前约定

### 3.1 本地数据目录

应用运行时的本地数据目录约定为：

- `.traffic_agent/`

其中：

- 配置目录：`.traffic_agent/config/`
- 数据库：`.traffic_agent/traffic_agent.db`

### 3.2 项目工作区

项目默认工作区约定为：

- `workspace/projects/`

每个项目目录下，当前会先创建：

- `sumo/`
- `logs/`
- `outputs/`
- `project.json`

## 4. 后续开发前的建议检查项

每次继续往下做之前，先检查：

1. 是否需要安装或更新依赖
2. PowerShell 是否仍然存在 profile 干扰
3. 中文文档是否只是显示乱码，而不是文件损坏
4. 是否已经初始化 git 仓库
5. 当前开发是否仍然遵守 `route.md` 中定义的阶段顺序

### 1.6 当前环境没有可用的 Python 3 运行时

现象：

- 执行 `py -3` 时提示 `No Installed Pythons Found`

影响：

- 目前无法在本机直接运行 `compileall`
- 无法实际启动当前 Python 代码进行验证

建议：

- 后续开发前先安装 Python 3.11+
- 安装完成后优先验证 `app/main.py` 能否启动

### 2.3 Phase B 已创建 UI 骨架，但还没有业务后端

现状：

- 已新增主窗口、聊天区、参数区、仿真状态区、设置对话框、新建项目对话框
- 主窗口已经接入 Phase A 的配置存储和项目存储
- 但聊天回复、运行按钮、暂停按钮、停止按钮目前都还是占位逻辑

影响：

- 现在可以作为 UI 开发底板继续往下接
- 但还不能认为已经具备真实 Agent 对话和仿真控制能力

建议：

- Phase C 先接 SUMO 文件生成
- Phase D 再接真实仿真运行器
- Phase E 再把聊天区从占位回复替换成真实 Agent 编排

### 2.4 Phase C 已具备基础文件生成骨架，但仍未做真实运行验证

现状：

- 已新增 `sumo_tools` 模块
- 已实现模板化 `NetworkGenerator`、`RouteGenerator`、`ConfigGenerator`
- 已实现 `ProjectBuilder`，可以把 `ProjectContext` 落盘为基础 SUMO 文件
- 已实现 `SumoProjectValidator`
- `NetconvertService` 在本机无 `netconvert` 时会退化为占位 `scenario.net.xml`

影响：

- 代码层面已经具备 Phase C 的基本职责
- 但由于当前机器没有 Python 3，也没有确认 SUMO / netconvert 是否安装，暂时无法做运行级验证

建议：

- 安装 Python 3.11+
- 安装 SUMO，并确认 `netconvert` 在 PATH 中
- Phase D 前先做一次最小构建链路验证

### 1.7 已在项目根目录创建 Anaconda 环境

现状：

- 本地环境路径：`E:\sumoAndQt\TrafficAgent\.conda`
- 已安装：`python 3.11`、`pip`、`pydantic`、`PySide6`

建议使用方式：

- 直接调用：`E:\sumoAndQt\TrafficAgent\.conda\python.exe`
- 或激活：`conda activate E:\sumoAndQt\TrafficAgent\.conda`

### 1.8 pip 会错误引用用户目录里的已装包

现象：

- 在这个 conda 环境里执行 `pip install` 时，`pip` 一度把 `C:\Users\11191\AppData\Roaming\Python\Python311\site-packages` 里的包当成“已满足”
- 但运行时该环境又并不能正常导入这些依赖

影响：

- 容易出现“安装看起来成功，但运行时报缺依赖”的假象

当前处理：

- 对 `typing-extensions` 采用了 `--force-reinstall`

后续建议：

- 如果再遇到类似现象，优先在项目环境里执行 `--force-reinstall`
- 验证时不要只看 `pip` 输出，要加一条真实 `python -c "import ..."` 导入检查

### 1.9 本机 SUMO 工具链已确认可用

当前已确认：

- `sumo.exe`: `E:\SUMO\sumo-1.20.0\bin\sumo.exe`
- `sumo-gui.exe`: `E:\SUMO\sumo-1.20.0\bin\sumo-gui.exe`
- `netconvert.exe`: `E:\SUMO\sumo-1.20.0\bin\netconvert.exe`

结论：

- Phase C/Phase D 可以走真实 SUMO 工具链
- 不再只是占位文件或纯骨架状态

### 2.5 Phase D 当前支持真实启动和停止，但暂停仍是占位语义

现状：

- `SimulationRunner.start_project()` 已可通过 `sumo-gui` 或 `sumo` 启动仿真
- `stop()` 已可终止进程
- `pause()` 当前只更新 UI 状态和日志，不会真正暂停 SUMO 进程

原因：

- 真正的暂停/继续/步进控制需要后续通过 TraCI 或 libsumo 接入

建议：

- Phase E 前不要误以为暂停已经具备真实控制能力
- 如果要做可控步进，下一步应把 TraCI 作为重点能力引入

### 1.10 PowerShell 通过管道写入 Python 脚本时，中文测试内容可能乱码

现象：

- 用 PowerShell here-string 直接管道给 `python -` 时，中文文本在某些测试场景下会被错误解码
- 结果是 Agent 的中文规则解析看起来“全部失效”

影响：

- 会误判为编排器逻辑错误
- 实际上 Qt 界面中的真实中文输入不受这个问题影响

建议：

- 做 CLI 级测试时，优先使用 Unicode 转义字符串
- 或显式写 UTF-8 无 BOM 文件后再执行
- 不要仅凭 `python -` 管道测试来判断中文解析逻辑是否正确

### 2.6 Phase E 当前是“规则优先 + 模型补充”的编排方案

现状：

- 当前 Agent 优先使用本地规则解析常见中文指令
- 当模型 API 已配置且规则无法识别时，才尝试调用 OpenAI 兼容接口做 JSON 解析补充

结论：

- 没配置模型 API 时，聊天生成仍可工作
- 配置了模型 API 后，可逐步提升长尾表达的解析能力

### 2.7 当前聊天编辑能力依赖持久化偏好作为默认值来源

现象：

- 当用户未在新指令里显式指定流量等级、默认时长等参数时，Agent 会从已保存的 `user_preferences.json` 中取默认值
- 因此不同机器或不同测试时刻，默认生成结果可能不同

影响：

- 测试时如果之前把默认流量改成了 `high`，后续“未指定流量”的新场景就会按 `high` 生成
- 这不是编排器错误，而是当前设计行为

建议：

- 验证单个测试用例时，尽量把关键参数写全
- 如果需要稳定复现实验，先检查或重置 `user_preferences.json`

### 2.8 当前聊天编辑已支持相对修改和上下文增量修改

当前已验证支持：

- `把流量提高30%`
- `把流量降低20%`
- `步长改成0.5`
- `时长改成180秒`
- `把当前场景改成T字路口`
- `3车道`
- `限速60km/h`

结论：

- 当前不是每次都从零生成
- 若存在当前项目上下文，Agent 会基于上下文做增量修改

### 2.9 项目摘要查询与重置类编辑已支持

当前已验证支持：

- `当前项目情况`
- `当前场景摘要`
- `取消偏向`
- `取消随机种子`
- `恢复默认流量`
- `恢复默认时长`
- `恢复默认步长`
- `长度改成300米`

说明：

- `恢复默认流量` 会取当前持久化偏好中的默认流量等级
- 如果默认流量本来就是 `high`，执行后看起来可能不会有视觉变化

### 2.10 CLI 测试时，建议把中文链路拆成短命令逐步验证

原因：

- 当前 Windows + PowerShell + `python -c` 的组合在含中文和多层嵌套字符串时，比较容易让测试脚本本身变复杂
- 功能本身没问题时，测试命令仍可能因为脚本拼接方式不稳定而误导判断

建议：

- 先测生成
- 再单独测编辑
- 再单独测摘要
- 最后再测串联链路

### 2.11 已新增项目操作历史表与追溯能力

当前已新增 SQLite 表：`project_operation_history`

字段包含：

- `created_at`
- `project_name`
- `project_dir`
- `intent`
- `user_message`
- `change_summary`
- `before_state`
- `after_state`
- `generated_files`
- `issues`

说明：

- 历史记录现在通过 `storage/history_store.py` 持久化
- `AgentOrchestrator` 在生成/编辑/偏好更新/运行请求/摘要查询后会自动写历史
- `查看最近操作历史` 这类查询本身不会再次写入历史，避免噪声递增

### 2.12 当前历史追溯已验证通过

已用项目环境做过最小烟测：

1. 生成一个十字路口
2. 再执行 `把流量提高30%，步长改成0.5`
3. 再执行 `查看最近2条操作历史`

验证结果：

- 能得到明确的变更确认文本
- 能拿到递增的历史记录 ID
- 能查询到最近两条记录
- 历史里包含用户原始消息和参数变化摘要

### 2.13 当前仍未提供 GUI 历史面板

当前历史查询入口还是聊天命令，不是独立 UI 面板。
如果后面要继续做：

- 可以优先在主窗口右侧增加“最近变更”只读列表
- 再考虑加筛选、详情查看、回滚

### 2.14 已新增独立 GUI 历史面板

当前已新增文件：`ui/history_panel.py`

主窗口接入情况：

- `ui/main_window.py` 右侧新增 `HistoryPanel`
- 绑定了 `refreshRequested`
- 在项目创建、项目加载、聊天执行完成后会自动刷新
- 若本次结果带 `history_record_id`，会自动选中新写入的那条记录

已验证：

- `compileall` 通过
- 在 `QT_QPA_PLATFORM=offscreen` 下可实例化 `MainWindow`
- 历史面板能正确显示现有记录数量

### 2.15 Phase D 已升级为真实 TraCI 控制链路

当前 `SimulationRunner` 已不再是单纯进程轮询，而是：

- `SumoProcessManager` 负责启动 SUMO 并分配 `--remote-port`
- `SimulationRunner` 通过 `traci.connect(...)` 建立连接
- 使用 Qt `QTimer` 持续驱动 `simulationStep()`

当前已实现：

- 真实暂停：停止步进 timer
- 真实继续：恢复步进 timer
- 真实单步：手动执行一次 `simulationStep()`
- 运行态指标刷新：时间、车辆数、平均速度

### 2.16 当前 UI 已新增继续 / 单步按钮

`ui/control_panel.py` 已新增：

- `resumeRequested`
- `stepRequested`

`ui/main_window.py` 已接线到：

- `SimulationRunner.resume()`
- `SimulationRunner.step_once()`

### 2.17 TraCI 烟测已通过

已在项目环境执行真实脚本验证：

1. 启动 headless `sumo`
2. `pause()`
3. `step_once()`
4. `resume()`
5. `stop()`

实际输出状态：

- `PAUSE paused 1.0 4`
- `STEP paused 2.0 4`
- `RESUME running 2.0 4`
- `BEFORE_STOP running 6.0 8`
- `STOP stopped 6.0 8`

说明当前 TraCI 控制链路已可用。

### 2.18 已补更宽松的编辑句式，并加入“无具体参数”提示

本轮已验证通过的新增句式：

- `增加流量`
- `减少流量`
- `把流量调大一点`
- `把流量调小一点`
- `车道改为5`
- `车道数改为5`

当前默认策略：

- 无百分比的“增加流量”按 `1.2x` 处理
- 无百分比的“减少流量”按 `0.8x` 处理

另外，当规则层已识别为 `edit_scenario`，但没提取出任何可执行参数时：

- 若模型已配置，会先尝试模型兜底解析
- 若仍无结果，会返回明确提示，不再静默按原状态重建
