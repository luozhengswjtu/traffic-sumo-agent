# TrafficAgent 任务拆分表

## 1. 开发总顺序

推荐严格按下面顺序推进，避免模块互相阻塞：

1. `app`：程序入口、依赖装配、应用初始化
2. `storage`：本地配置、项目元数据、最近项目
3. `ui`：主窗口与基础面板
4. `sumo_domain`：领域对象定义
5. `sumo_tools`：SUMO 文件生成与校验
6. `sim_runner`：仿真启动和状态同步
7. `model_providers`：模型 API 适配
8. `agent`：编排、工具注册、偏好注入
9. `tests`：核心链路测试

这样安排的原因是：

- `ui` 需要 `storage`
- `sumo_tools` 需要 `sumo_domain`
- `agent` 依赖 `model_providers`、`sumo_tools`、`sim_runner`
- 先把底座打好，后面联调会轻很多

## 2. 目录建议

```text
TrafficAgent/
  app/
    main.py
    bootstrap.py

  ui/
    main_window.py
    chat_panel.py
    control_panel.py
    sim_status_panel.py
    settings_dialog.py
    project_dialog.py

  agent/
    orchestrator.py
    intents.py
    tool_registry.py
    memory.py
    prompts.py

  model_providers/
    base.py
    openai_compatible.py

  sumo_domain/
    project_spec.py
    network_spec.py
    route_spec.py
    simulation_spec.py
    preferences.py

  sumo_tools/
    project_builder.py
    network_generator.py
    route_generator.py
    config_generator.py
    validator.py
    netconvert_service.py

  sim_runner/
    runner.py
    process_manager.py
    state.py
    events.py

  storage/
    db.py
    config_store.py
    project_store.py
    recent_store.py

  tests/
```

## 3. 模块拆分

### 3.1 `app` 模块

职责：

- 作为应用启动入口
- 初始化配置、日志、工作区
- 装配 UI、Agent、存储和运行器

建议文件与类：

#### `app/main.py`

- `def main() -> int`
  - 启动 `QApplication`
  - 初始化依赖
  - 展示主窗口

#### `app/bootstrap.py`

- `class AppBootstrap`
  - `build() -> AppContainer`
  - 负责创建全局依赖对象

- `class AppContainer`
  - 字段：
    - `config_store`
    - `project_store`
    - `recent_store`
    - `model_client_factory`
    - `tool_registry`
    - `agent_orchestrator`
    - `sim_runner`

优先级：`P0`

---

### 3.2 `storage` 模块

职责：

- 存储全局配置
- 存储项目元数据
- 存储最近项目
- 为后续偏好和会话记录提供落点

建议文件与类：

#### `storage/config_store.py`

- `class AppConfigStore`
  - `load_app_config() -> AppConfig`
  - `save_app_config(config: AppConfig) -> None`
  - `load_model_config() -> ModelConfig`
  - `save_model_config(config: ModelConfig) -> None`
  - `load_user_preferences() -> UserPreferences`
  - `save_user_preferences(preferences: UserPreferences) -> None`

#### `storage/project_store.py`

- `class ProjectStore`
  - `create_project(name: str, base_dir: Path) -> ProjectMeta`
  - `open_project(path: Path) -> ProjectMeta`
  - `save_project_meta(meta: ProjectMeta) -> None`
  - `load_project_meta(path: Path) -> ProjectMeta`
  - `list_project_files(path: Path) -> list[Path]`

#### `storage/recent_store.py`

- `class RecentProjectStore`
  - `list_recent_projects() -> list[RecentProjectItem]`
  - `add_recent_project(item: RecentProjectItem) -> None`
  - `remove_recent_project(path: Path) -> None`

#### `storage/db.py`

- `def init_db(db_path: Path) -> None`
- `def get_connection() -> sqlite3.Connection`

优先级：`P0`

说明：

- MVP 阶段可以先用 `JSON + SQLite` 混合方案
- 全局设置用 JSON，历史记录用 SQLite

---

### 3.3 `ui` 模块

职责：

- 承载用户交互
- 展示项目状态、参数、日志、仿真状态
- 向 Agent 和 Runner 发出请求

建议文件与类：

#### `ui/main_window.py`

- `class MainWindow(QMainWindow)`
  - `load_project(path: Path) -> None`
  - `bind_services(container: AppContainer) -> None`
  - `refresh_project_view() -> None`
  - `append_log(message: str) -> None`
  - `show_error(message: str) -> None`

#### `ui/chat_panel.py`

- `class ChatPanel(QWidget)`
  - `submit_message() -> None`
  - `append_user_message(text: str) -> None`
  - `append_agent_message(text: str) -> None`
  - `set_busy(busy: bool) -> None`

- 信号建议：
  - `messageSubmitted(str)`

#### `ui/control_panel.py`

- `class ControlPanel(QWidget)`
  - `load_simulation_spec(spec: SimulationSpec) -> None`
  - `collect_simulation_spec() -> SimulationSpec`
  - `set_run_enabled(enabled: bool) -> None`

- 信号建议：
  - `simulationParamsChanged(SimulationSpec)`
  - `runRequested()`
  - `pauseRequested()`
  - `stopRequested()`

#### `ui/sim_status_panel.py`

- `class SimulationStatusPanel(QWidget)`
  - `update_state(state: SimulationRuntimeState) -> None`
  - `reset() -> None`

#### `ui/settings_dialog.py`

- `class SettingsDialog(QDialog)`
  - `load_settings() -> None`
  - `save_settings() -> None`
  - `collect_model_config() -> ModelConfig`
  - `collect_user_preferences() -> UserPreferences`

#### `ui/project_dialog.py`

- `class NewProjectDialog(QDialog)`
  - `collect_project_name() -> str`
  - `collect_project_path() -> Path`

优先级：`P0`

说明：

- 第一版不做复杂视图嵌入
- 先把“聊天 + 参数 + 状态 + 日志”四块做稳

---

### 3.4 `sumo_domain` 模块

职责：

- 定义系统内部统一的数据结构
- 屏蔽 XML 细节，让 Agent 和工具层围绕结构化对象工作

建议文件与类：

#### `sumo_domain/project_spec.py`

- `class ProjectMeta(BaseModel)`
  - `name: str`
  - `project_dir: Path`
  - `created_at: datetime`
  - `updated_at: datetime`

- `class ProjectContext(BaseModel)`
  - `meta: ProjectMeta`
  - `network: NetworkSpec | None`
  - `routes: RouteSpec | None`
  - `simulation: SimulationSpec | None`

#### `sumo_domain/network_spec.py`

- `class NodeSpec(BaseModel)`
  - `id: str`
  - `x: float`
  - `y: float`
  - `type: str`

- `class EdgeSpec(BaseModel)`
  - `id: str`
  - `from_node: str`
  - `to_node: str`
  - `num_lanes: int`
  - `speed: float`

- `class NetworkSpec(BaseModel)`
  - `scenario_type: str`
  - `nodes: list[NodeSpec]`
  - `edges: list[EdgeSpec]`

#### `sumo_domain/route_spec.py`

- `class FlowSpec(BaseModel)`
  - `id: str`
  - `from_edge: str`
  - `to_edge: str`
  - `begin: int`
  - `end: int`
  - `vehs_per_hour: int`

- `class RouteSpec(BaseModel)`
  - `flows: list[FlowSpec]`

#### `sumo_domain/simulation_spec.py`

- `class SimulationSpec(BaseModel)`
  - `begin_time: int`
  - `end_time: int`
  - `step_length: float`
  - `seed: int | None`
  - `route_file: str`
  - `net_file: str`

- `class SimulationRuntimeState(BaseModel)`
  - `status: str`
  - `current_time: float`
  - `vehicle_count: int`
  - `average_speed: float | None`
  - `message: str | None`

#### `sumo_domain/preferences.py`

- `class UserPreferences(BaseModel)`
  - `default_scenario_type: str`
  - `default_flow_level: str`
  - `default_duration: int`
  - `system_prompt_additions: str | None`

- `class ModelConfig(BaseModel)`
  - `base_url: str`
  - `api_key: str`
  - `model: str`
  - `temperature: float = 0.2`
  - `timeout_seconds: int = 60`

优先级：`P0`

说明：

- `sumo_domain` 是后面所有模块的公共契约
- 这里一定先定，再开始写生成器

---

### 3.5 `sumo_tools` 模块

职责：

- 基于领域对象生成 SUMO 文件
- 管理项目内文件输出
- 执行校验
- 封装 `netconvert`

建议文件与类：

#### `sumo_tools/project_builder.py`

- `class ProjectBuilder`
  - `build_project(context: ProjectContext) -> BuildResult`
  - `write_network_files(project_dir: Path, network: NetworkSpec) -> list[Path]`
  - `write_route_files(project_dir: Path, routes: RouteSpec) -> list[Path]`
  - `write_config_file(project_dir: Path, simulation: SimulationSpec) -> Path`

#### `sumo_tools/network_generator.py`

- `class NetworkGenerator`
  - `generate_intersection(spec: NetworkGenerationRequest) -> NetworkSpec`
  - `generate_t_junction(spec: NetworkGenerationRequest) -> NetworkSpec`
  - `generate_corridor(spec: NetworkGenerationRequest) -> NetworkSpec`

- `class NetworkGenerationRequest(BaseModel)`
  - `scenario_type: str`
  - `lane_count: int`
  - `road_length: float`
  - `speed_limit: float`

#### `sumo_tools/route_generator.py`

- `class RouteGenerator`
  - `generate_routes(network: NetworkSpec, request: RouteGenerationRequest) -> RouteSpec`

- `class RouteGenerationRequest(BaseModel)`
  - `flow_level: str`
  - `duration_seconds: int`
  - `traffic_bias: str | None`

#### `sumo_tools/config_generator.py`

- `class ConfigGenerator`
  - `build_simulation_spec(project_dir: Path, request: SimulationConfigRequest) -> SimulationSpec`
  - `write_sumocfg(path: Path, spec: SimulationSpec) -> Path`

- `class SimulationConfigRequest(BaseModel)`
  - `duration_seconds: int`
  - `step_length: float`
  - `seed: int | None`

#### `sumo_tools/netconvert_service.py`

- `class NetconvertService`
  - `build_net_file(project_dir: Path, node_file: Path, edge_file: Path) -> Path`
  - `is_available() -> bool`

#### `sumo_tools/validator.py`

- `class ValidationIssue(BaseModel)`
  - `level: str`
  - `message: str`
  - `file: str | None`

- `class SumoProjectValidator`
  - `validate_project(project_dir: Path) -> list[ValidationIssue]`
  - `validate_context(context: ProjectContext) -> list[ValidationIssue]`
  - `assert_runnable(project_dir: Path) -> None`

- `class BuildResult(BaseModel)`
  - `generated_files: list[Path]`
  - `issues: list[ValidationIssue]`

优先级：`P0`

说明：

- MVP 成败很大程度取决于这里
- 第一版必须优先支持模板化生成，不做自由形状路网

---

### 3.6 `sim_runner` 模块

职责：

- 启动和控制仿真
- 向 UI 发布运行状态
- 隔离 SUMO 进程或 `traci` 会话

建议文件与类：

#### `sim_runner/state.py`

- `class RunnerStatus(str, Enum)`
  - `IDLE`
  - `STARTING`
  - `RUNNING`
  - `PAUSED`
  - `STOPPED`
  - `ERROR`

#### `sim_runner/events.py`

- `class SimulationEvent(BaseModel)`
  - `type: str`
  - `payload: dict`

#### `sim_runner/process_manager.py`

- `class SumoProcessManager`
  - `start(sumocfg_path: Path) -> None`
  - `stop() -> None`
  - `is_running() -> bool`

#### `sim_runner/runner.py`

- `class SimulationRunner(QObject)`
  - `start_project(project_dir: Path) -> None`
  - `pause() -> None`
  - `resume() -> None`
  - `stop() -> None`
  - `step_once() -> None`
  - `current_state() -> SimulationRuntimeState`

- 信号建议：
  - `stateChanged(SimulationRuntimeState)`
  - `logProduced(str)`
  - `runFailed(str)`

优先级：`P0`

说明：

- 第一版可以优先实现“启动、停止、状态回报”
- `pause` 和 `step_once` 可先做简单版本

---

### 3.7 `model_providers` 模块

职责：

- 屏蔽具体模型 API 差异
- 提供统一的聊天与工具调用入口

建议文件与类：

#### `model_providers/base.py`

- `class ChatMessage(BaseModel)`
  - `role: str`
  - `content: str`

- `class ToolCall(BaseModel)`
  - `name: str`
  - `arguments: dict`

- `class ModelResponse(BaseModel)`
  - `text: str`
  - `tool_calls: list[ToolCall]`

- `class BaseModelClient(Protocol)`
  - `chat(messages: list[ChatMessage], tools: list[dict] | None = None) -> ModelResponse`

#### `model_providers/openai_compatible.py`

- `class OpenAICompatibleClient`
  - `__init__(config: ModelConfig) -> None`
  - `chat(messages: list[ChatMessage], tools: list[dict] | None = None) -> ModelResponse`

- `class ModelClientFactory`
  - `create(config: ModelConfig) -> BaseModelClient`

优先级：`P1`

说明：

- 在 UI 和 SUMO 工具稳定前，这一层可以先做轻量占位
- 先只支持 OpenAI 兼容接口

---

### 3.8 `agent` 模块

职责：

- 接收用户消息
- 结合偏好和当前项目上下文，生成执行计划
- 决定调用哪些工具
- 把结果组织成用户可理解的反馈

建议文件与类：

#### `agent/intents.py`

- `class UserIntent(str, Enum)`
  - `CREATE_SCENARIO`
  - `EDIT_SCENARIO`
  - `RUN_SIMULATION`
  - `UPDATE_PREFERENCES`
  - `UNKNOWN`

#### `agent/tool_registry.py`

- `class AgentTool(Protocol)`
  - `name() -> str`
  - `description() -> str`
  - `schema() -> dict`
  - `invoke(arguments: dict) -> dict`

- `class ToolRegistry`
  - `register(tool: AgentTool) -> None`
  - `list_tool_schemas() -> list[dict]`
  - `invoke(name: str, arguments: dict) -> dict`

#### `agent/memory.py`

- `class SessionMemory`
  - `append_user_message(text: str) -> None`
  - `append_agent_message(text: str) -> None`
  - `recent_messages(limit: int = 10) -> list[ChatMessage]`

- `class PreferenceContextBuilder`
  - `build_system_context(preferences: UserPreferences, project: ProjectContext | None) -> str`

#### `agent/prompts.py`

- `def build_system_prompt(preferences: UserPreferences) -> str`
- `def build_user_prompt(user_text: str, project_summary: str | None) -> str`

#### `agent/orchestrator.py`

- `class AgentOrchestrator(QObject)`
  - `handle_user_message(text: str, project: ProjectContext | None) -> AgentExecutionResult`
  - `detect_intent(text: str) -> UserIntent`
  - `execute_tool_plan(tool_calls: list[ToolCall]) -> list[dict]`
  - `summarize_result(result: AgentExecutionResult) -> str`

- `class AgentExecutionResult(BaseModel)`
  - `reply_text: str`
  - `updated_project: ProjectContext | None`
  - `generated_files: list[str]`
  - `issues: list[str]`

优先级：`P1`

说明：

- 第一版先实现“单轮执行”
- 不急着做复杂记忆和多轮推理

---

### 3.9 `tests` 模块

职责：

- 覆盖领域模型、生成链路、校验链路、Agent 编排链路

建议测试文件：

- `tests/test_project_store.py`
- `tests/test_network_generator.py`
- `tests/test_route_generator.py`
- `tests/test_config_generator.py`
- `tests/test_validator.py`
- `tests/test_agent_orchestrator.py`

优先级：`P1`

说明：

- 最少覆盖生成和校验
- UI 层可先以集成手测为主

## 4. 按阶段拆分的任务清单

### 阶段 A：项目底座

先写：

1. `app/main.py`
2. `app/bootstrap.py`
3. `storage/config_store.py`
4. `storage/project_store.py`
5. `storage/recent_store.py`
6. `sumo_domain/*.py`

完成标准：

- 程序能启动
- 可以创建和读取项目
- 核心配置对象已经稳定

### 阶段 B：基础 UI

先写：

1. `ui/main_window.py`
2. `ui/chat_panel.py`
3. `ui/control_panel.py`
4. `ui/sim_status_panel.py`
5. `ui/settings_dialog.py`
6. `ui/project_dialog.py`

完成标准：

- 用户能看到主界面
- 能新建项目
- 能输入消息
- 能修改参数

### 阶段 C：SUMO 生成能力

先写：

1. `sumo_tools/network_generator.py`
2. `sumo_tools/route_generator.py`
3. `sumo_tools/config_generator.py`
4. `sumo_tools/netconvert_service.py`
5. `sumo_tools/project_builder.py`
6. `sumo_tools/validator.py`

完成标准：

- 能从结构化参数生成一套可运行 SUMO 文件
- 能校验是否可运行

### 阶段 D：仿真运行

先写：

1. `sim_runner/state.py`
2. `sim_runner/events.py`
3. `sim_runner/process_manager.py`
4. `sim_runner/runner.py`

完成标准：

- 能从当前项目启动仿真
- UI 能收到状态变化

### 阶段 E：模型接入与 Agent

先写：

1. `model_providers/base.py`
2. `model_providers/openai_compatible.py`
3. `agent/tool_registry.py`
4. `agent/prompts.py`
5. `agent/memory.py`
6. `agent/intents.py`
7. `agent/orchestrator.py`

完成标准：

- 用户消息可以转成工具调用
- 可以完成“生成场景”与“修改参数”两类主任务

### 阶段 F：联调与测试

先写：

1. `tests/test_network_generator.py`
2. `tests/test_validator.py`
3. `tests/test_agent_orchestrator.py`
4. 主链路联调

完成标准：

- 至少 5 条 MVP 验收用例可跑通

## 5. 最小接口联动关系

主链路建议固定成下面这套调用关系：

1. `ChatPanel.messageSubmitted(str)`
2. `MainWindow` 接收消息并调用 `AgentOrchestrator.handle_user_message(...)`
3. `AgentOrchestrator` 调用 `ToolRegistry.invoke(...)`
4. 工具层生成 `ProjectContext` 和项目文件
5. `MainWindow` 刷新 `ControlPanel` 和 `SimulationStatusPanel`
6. 用户点击运行后，`MainWindow` 调用 `SimulationRunner.start_project(...)`
7. `SimulationRunner.stateChanged(...)` 回推 UI

这条链路写通后，MVP 的主体就成立了。

## 6. 建议的首批任务卡

如果现在马上开始开发，建议先开这 10 张任务卡：

1. 初始化 Python 项目结构和入口文件
2. 定义 `ProjectMeta`、`NetworkSpec`、`RouteSpec`、`SimulationSpec`
3. 实现应用配置和模型配置存储
4. 实现项目创建和最近项目管理
5. 搭建主窗口和三栏布局
6. 实现基础参数面板
7. 实现十字路口/T 字路口/直线路段生成器
8. 实现 `sumocfg` 和 `net.xml` 生成链路
9. 实现仿真启动和状态显示
10. 接入 Agent 编排器并打通聊天生成场景

## 7. 不要提前做的事情

在 MVP 前，不建议抢跑这些内容：

- 复杂插件体系
- 多 Agent 协同
- 高级画布编辑器
- 大而全的 Prompt 体系
- 过度抽象的事件总线
- 复杂数据库模型

先把单项目、单 Agent、单次仿真闭环做出来，后续扩展会顺很多。
