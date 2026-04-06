# TrafficAgent

TrafficAgent 是一个面向 Windows 的桌面应用，用于通过聊天式交互创建、校验并运行 SUMO 交通仿真项目。

当前仓库已经包含以下核心能力：

- 基于 PySide6 的桌面界面
- 本地项目与配置存储
- SUMO 路网、路线与配置文件生成
- 基于 TraCI 的仿真启动与控制
- OpenAI-compatible 模型接入层

![TrafficAgent UI](./artifacts_chat_layout.png)

## 当前状态

项目目前处于 alpha 阶段。

- 主要目标平台：Windows
- 推荐 Python 版本：3.11
- 推荐环境管理方式：Conda / Anaconda
- 外部运行依赖：SUMO、`sumo` / `sumo-gui`、`netconvert`、TraCI

## 主要功能

- 在 `workspace/projects/` 下创建和管理本地 SUMO 项目
- 生成基础路网、车流路线和仿真配置文件
- 在运行前对项目文件进行校验
- 在桌面界面内启动并控制 SUMO 仿真
- 本地保存最近项目、用户偏好和模型配置
- 通过 OpenAI-compatible chat completions 接口驱动助手能力
- 支持将路口图片分析为可继续编辑的草稿结构

## 快速开始

### 1. 创建 Conda 环境

```powershell
conda env create -f environment.yml
conda activate traffic-agent
```

如果你更喜欢使用仓库内的本地环境：

```powershell
conda env create -f environment.yml -p .\.conda
conda activate .\.conda
```

### 2. 安装并配置 SUMO

请先单独安装 SUMO，然后在当前 PowerShell 会话中暴露其二进制和 Python 工具路径：

```powershell
$env:SUMO_HOME = "C:\Program Files\Eclipse\Sumo"
$env:PATH = "$env:SUMO_HOME\bin;$env:PATH"
$env:PYTHONPATH = "$env:SUMO_HOME\tools;$env:PYTHONPATH"
```

如果你的 SUMO 安装路径不同，请自行替换。

更详细的 Windows 安装说明见：[docs/setup-windows.md](./docs/setup-windows.md)

### 3. 启动桌面程序

```powershell
python app\main.py
```

程序首次启动后会自动创建以下本地运行目录和文件：

- `.traffic_agent/config/`
- `.traffic_agent/traffic_agent.db`
- `workspace/projects/`

## 模型配置

程序会将模型设置保存在 `.traffic_agent/config/model_config.json`。

你可以通过以下两种方式配置：

- 启动程序后在 Settings 对话框中填写
- 参考 [docs/model_config.example.json](./docs/model_config.example.json) 手动创建配置文件

配置字段说明：

- `base_url`：OpenAI-compatible API 的基地址
- `api_key`：对应服务提供方的 API Key
- `model`：聊天模型名称
- `supports_vision`：是否将当前模型视为支持图像能力
- `temperature`：生成温度
- `timeout_seconds`：请求超时时间

## 目录结构

```text
app/                应用入口与启动装配
agent/              助手编排、提示词与工具规划
model_providers/    OpenAI-compatible 模型客户端
sim_runner/         SUMO 进程与 TraCI 运行控制
storage/            本地配置、历史与项目存储
sumo_domain/        Pydantic 领域模型
sumo_tools/         SUMO 文件生成与校验工具
ui/                 PySide6 桌面界面
workspace/projects/ 本地生成的项目目录
docs/               安装与仓库文档
```

## 外部依赖说明

本仓库不会内置 SUMO 本体。

如果你希望完整运行仿真，需要确保以下条件成立：

- 已正确安装 SUMO
- `sumo` 或 `sumo-gui` 已加入 `PATH`
- `netconvert` 已加入 `PATH`
- Python 可以导入 TraCI，通常需要把 `SUMO_HOME/tools` 加入 `PYTHONPATH`

当 `netconvert` 不可用时，代码中的部分流程会退化为写入占位 `.net.xml` 文件，但这不能替代真实可运行的 SUMO 工具链。

## 开发说明

- 本地运行数据默认不会提交到 git：`.conda/`、`.tmp/`、`.traffic_agent/`、`workspace/projects/*`
- 当前代码库以 Windows 本地源码运行方式为主，尚未打包为安装程序
- `HUMAN.md`、`ChatGPT.md`、`plan.md`、`route.md` 目前更多是内部过程文档，不应视为主要用户文档

## License

本项目基于 MIT License 开源，详见 [LICENSE](./LICENSE)。
