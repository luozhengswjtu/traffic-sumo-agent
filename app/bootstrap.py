from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.orchestrator import AgentOrchestrator
from agent.tool_registry import ToolRegistry
from model_providers.openai_compatible import ModelClientFactory
from sim_runner.process_manager import SumoProcessManager
from sim_runner.runner import SimulationRunner
from storage.config_store import AppConfigStore
from storage.db import init_db
from storage.history_store import ProjectHistoryStore
from storage.project_store import ProjectStore
from storage.recent_store import RecentProjectStore
from sumo_tools.config_generator import ConfigGenerator
from sumo_tools.netconvert_service import NetconvertService
from sumo_tools.network_generator import NetworkGenerator
from sumo_tools.project_builder import ProjectBuilder
from sumo_tools.route_generator import RouteGenerator
from sumo_tools.validator import SumoProjectValidator


@dataclass(slots=True)
class AppPaths:
    root_dir: Path
    data_dir: Path
    config_dir: Path
    workspace_dir: Path
    projects_dir: Path
    db_path: Path

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class AppContainer:
    paths: AppPaths
    config_store: AppConfigStore
    project_store: ProjectStore
    recent_store: RecentProjectStore
    history_store: ProjectHistoryStore
    app_config: Any
    model_config: Any
    user_preferences: Any
    network_generator: NetworkGenerator
    route_generator: RouteGenerator
    config_generator: ConfigGenerator
    netconvert_service: NetconvertService
    project_builder: ProjectBuilder
    validator: SumoProjectValidator
    sim_runner: SimulationRunner
    model_client_factory: Any = None
    tool_registry: Any = None
    agent_orchestrator: Any = None


class AppBootstrap:
    """Create shared services for the current application session."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or Path(__file__).resolve().parents[1]

    def build(self) -> AppContainer:
        paths = self._build_paths()
        paths.ensure()
        init_db(paths.db_path)

        config_store = AppConfigStore(paths.config_dir)
        app_config = config_store.load_app_config()
        model_config = config_store.load_model_config()
        user_preferences = config_store.load_user_preferences()

        projects_dir = self._resolve_projects_dir(app_config.projects_root, paths.root_dir)
        projects_dir.mkdir(parents=True, exist_ok=True)

        project_store = ProjectStore(projects_dir)
        recent_store = RecentProjectStore(paths.config_dir / "recent_projects.json")
        history_store = ProjectHistoryStore()

        network_generator = NetworkGenerator()
        route_generator = RouteGenerator()
        config_generator = ConfigGenerator()
        netconvert_service = NetconvertService()
        validator = SumoProjectValidator()
        project_builder = ProjectBuilder(
            config_generator=config_generator,
            netconvert_service=netconvert_service,
            validator=validator,
        )
        sim_runner = SimulationRunner(
            process_manager=SumoProcessManager(prefer_gui=True),
            validator=validator,
        )

        container = AppContainer(
            paths=AppPaths(
                root_dir=paths.root_dir,
                data_dir=paths.data_dir,
                config_dir=paths.config_dir,
                workspace_dir=paths.workspace_dir,
                projects_dir=projects_dir,
                db_path=paths.db_path,
            ),
            config_store=config_store,
            project_store=project_store,
            recent_store=recent_store,
            history_store=history_store,
            app_config=app_config,
            model_config=model_config,
            user_preferences=user_preferences,
            network_generator=network_generator,
            route_generator=route_generator,
            config_generator=config_generator,
            netconvert_service=netconvert_service,
            project_builder=project_builder,
            validator=validator,
            sim_runner=sim_runner,
        )

        container.model_client_factory = ModelClientFactory()
        container.tool_registry = ToolRegistry()
        container.agent_orchestrator = AgentOrchestrator(
            tool_registry=container.tool_registry,
            project_store=container.project_store,
            recent_store=container.recent_store,
            history_store=container.history_store,
            config_store=container.config_store,
            network_generator=container.network_generator,
            route_generator=container.route_generator,
            config_generator=container.config_generator,
            project_builder=container.project_builder,
            validator=container.validator,
            model_client_factory=container.model_client_factory,
            get_model_config=lambda: container.model_config,
            get_user_preferences=lambda: container.user_preferences,
            set_user_preferences=lambda value: setattr(container, "user_preferences", value),
        )
        return container

    def _build_paths(self) -> AppPaths:
        data_dir = self.root_dir / ".traffic_agent"
        config_dir = data_dir / "config"
        workspace_dir = self.root_dir / "workspace"
        projects_dir = workspace_dir / "projects"
        db_path = data_dir / "traffic_agent.db"
        return AppPaths(
            root_dir=self.root_dir,
            data_dir=data_dir,
            config_dir=config_dir,
            workspace_dir=workspace_dir,
            projects_dir=projects_dir,
            db_path=db_path,
        )

    @staticmethod
    def _resolve_projects_dir(projects_root: str, root_dir: Path) -> Path:
        candidate = Path(projects_root)
        if candidate.is_absolute():
            return candidate
        return (root_dir / candidate).resolve()
