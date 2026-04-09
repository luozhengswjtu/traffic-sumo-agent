from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from sim_runner.process_manager import SumoProcessManager
from sim_runner.state import RunnerStatus
from sumo_domain.signal_plan import SignalRuntimeStatus
from sumo_domain.simulation_spec import SimulationRuntimeState
from sumo_tools.validator import SumoProjectValidator

try:
    import traci
except ImportError:  # pragma: no cover - depends on local SUMO install
    traci = None


class SimulationRunner(QObject):
    stateChanged = Signal(object)
    logProduced = Signal(str)
    runFailed = Signal(str)

    def __init__(
        self,
        process_manager: SumoProcessManager | None = None,
        validator: SumoProjectValidator | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.process_manager = process_manager or SumoProcessManager()
        self.validator = validator or SumoProjectValidator()
        self._state = SimulationRuntimeState(
            status=RunnerStatus.IDLE.value,
            current_time=0.0,
            vehicle_count=0,
            average_speed=None,
            message="等待启动仿真",
            signal_status=None,
        )
        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(500)
        self._monitor_timer.timeout.connect(self._poll_process)

        self._step_timer = QTimer(self)
        self._step_timer.setInterval(150)
        self._step_timer.timeout.connect(self._advance_one_step)

        self._traci_connection = None
        self._connection_label: str | None = None
        self._current_project_dir: Path | None = None

    def start_project(self, project_dir: Path) -> None:
        if traci is None:
            self._set_error("未找到 traci 模块，无法启用 TraCI 控制。")
            return

        if self.process_manager.is_running() or self._traci_connection is not None:
            self.stop()

        project_dir = Path(project_dir).resolve()
        sumocfg_path = project_dir / "sumo" / "scenario.sumocfg"
        remote_port = self.process_manager.allocate_free_port()
        try:
            issues = self.validator.validate_project(project_dir)
            self._log_validation_warnings(issues)
            self.validator.assert_runnable(project_dir)
            command = self.process_manager.start(sumocfg_path, remote_port=remote_port)
            self.logProduced.emit(f"准备启动 SUMO：{' '.join(command)}")
            self._connect_traci(remote_port)
        except Exception as exc:
            error_message = self._build_startup_error_message(project_dir, sumocfg_path, remote_port, exc)
            self.process_manager.stop()
            self._close_traci(wait=False)
            self._set_error(error_message)
            return

        self._current_project_dir = project_dir
        self._monitor_timer.start()
        self._step_timer.start()
        self._refresh_runtime_state(
            status=RunnerStatus.RUNNING.value,
            message=f"TraCI 已连接：{' '.join(command)}",
        )
        self.logProduced.emit(f"SUMO 已启动并接入 TraCI：{' '.join(command)}")

    def pause(self) -> None:
        if self._traci_connection is None:
            self.logProduced.emit("当前没有运行中的 TraCI 仿真。")
            return
        if self._state.status == RunnerStatus.PAUSED.value:
            self.logProduced.emit("当前仿真已经处于暂停状态。")
            return

        self._step_timer.stop()
        self._refresh_runtime_state(
            status=RunnerStatus.PAUSED.value,
            message="仿真已暂停，未继续推进时间步。",
        )
        self.logProduced.emit("TraCI 暂停成功。")

    def resume(self) -> None:
        if self._traci_connection is None:
            self.logProduced.emit("当前没有运行中的 TraCI 仿真。")
            return
        if self._state.status == RunnerStatus.RUNNING.value and self._step_timer.isActive():
            self.logProduced.emit("当前仿真已经在运行。")
            return

        self._step_timer.start()
        self._refresh_runtime_state(
            status=RunnerStatus.RUNNING.value,
            message="仿真已恢复，TraCI 正在持续推进时间步。",
        )
        self.logProduced.emit("TraCI 已继续运行。")

    def stop(self) -> None:
        self._monitor_timer.stop()
        self._step_timer.stop()
        self._close_traci(wait=False)
        self.process_manager.stop()
        self._current_project_dir = None
        self._state = SimulationRuntimeState(
            status=RunnerStatus.STOPPED.value,
            current_time=self._state.current_time,
            vehicle_count=self._state.vehicle_count,
            average_speed=self._state.average_speed,
            message="SUMO 进程已停止。",
            signal_status=None,
        )
        self.stateChanged.emit(self._state)
        self.logProduced.emit("SUMO 进程已停止。")

    def step_once(self) -> None:
        if self._traci_connection is None:
            self.logProduced.emit("当前没有运行中的 TraCI 仿真。")
            return

        self._step_timer.stop()
        self._advance_one_step(force_pause=True)

    def current_state(self) -> SimulationRuntimeState:
        return self._state

    def _connect_traci(self, remote_port: int) -> None:
        self._connection_label = f"traffic_agent_{remote_port}"
        self._traci_connection = traci.connect(
            port=remote_port,
            numRetries=20,
            waitBetweenRetries=0.25,
            label=self._connection_label,
        )
        delta_t = self._safe_delta_t()
        interval_ms = max(50, min(500, int(delta_t * 200)))
        self._step_timer.setInterval(interval_ms)

    def _advance_one_step(self, force_pause: bool = False) -> None:
        if self._traci_connection is None:
            return

        try:
            self._traci_connection.simulationStep()
            min_expected = self._traci_connection.simulation.getMinExpectedNumber()
        except Exception as exc:
            self._monitor_timer.stop()
            self._step_timer.stop()
            self._set_error(f"TraCI 步进失败：{exc}")
            self._close_traci(wait=False)
            self.process_manager.stop()
            self._current_project_dir = None
            return

        if min_expected <= 0:
            self._finish_completed_run()
            return

        next_status = RunnerStatus.PAUSED.value if force_pause else RunnerStatus.RUNNING.value
        message = "已执行一次单步。" if force_pause else "TraCI 正在推进仿真。"
        self._refresh_runtime_state(status=next_status, message=message)
        if force_pause:
            self.logProduced.emit("TraCI 单步执行完成。")

    def _refresh_runtime_state(self, status: str, message: str) -> None:
        if self._traci_connection is None:
            return

        current_time = float(self._traci_connection.simulation.getTime())
        vehicle_ids = list(self._traci_connection.vehicle.getIDList())
        vehicle_count = len(vehicle_ids)
        average_speed = None
        if vehicle_ids:
            total_speed = sum(float(self._traci_connection.vehicle.getSpeed(vehicle_id)) for vehicle_id in vehicle_ids)
            average_speed = total_speed / vehicle_count

        self._state = SimulationRuntimeState(
            status=status,
            current_time=current_time,
            vehicle_count=vehicle_count,
            average_speed=average_speed,
            message=message,
            signal_status=self._read_signal_status(),
        )
        self.stateChanged.emit(self._state)

    def _finish_completed_run(self) -> None:
        self._monitor_timer.stop()
        self._step_timer.stop()
        self._refresh_runtime_state(
            status=RunnerStatus.STOPPED.value,
            message="仿真已完成，SUMO 不再有待运行车辆。",
        )
        self.logProduced.emit("TraCI 检测到仿真已完成。")
        self._close_traci(wait=False)
        self.process_manager.stop()
        self._current_project_dir = None

    def _poll_process(self) -> None:
        exit_code = self.process_manager.poll_exit_code()
        if exit_code is None:
            return

        stdout_text, stderr_text = self.process_manager.read_available_output()
        self._monitor_timer.stop()
        self._step_timer.stop()

        if exit_code == 0:
            self._close_traci(wait=False)
            self._state = SimulationRuntimeState(
                status=RunnerStatus.STOPPED.value,
                current_time=self._state.current_time,
                vehicle_count=self._state.vehicle_count,
                average_speed=self._state.average_speed,
                message="SUMO 正常退出。",
                signal_status=None,
            )
            self.stateChanged.emit(self._state)
            if stdout_text.strip():
                self.logProduced.emit(stdout_text.strip())
            self.logProduced.emit("SUMO 正常退出。")
            self._current_project_dir = None
            return

        error_message = stderr_text.strip() or stdout_text.strip() or f"SUMO 异常退出，返回码 {exit_code}"
        if self.process_manager.last_command:
            error_message = f"{error_message}\n命令: {self.process_manager.last_command_text()}"
        self._set_error(error_message)
        self._close_traci(wait=False)
        self.process_manager.stop()
        self._current_project_dir = None

    def _close_traci(self, wait: bool) -> None:
        if self._traci_connection is None:
            return
        try:
            self._traci_connection.close(wait)
        except Exception:
            pass
        self._traci_connection = None
        self._connection_label = None

    def _safe_delta_t(self) -> float:
        if self._traci_connection is None:
            return 1.0
        try:
            delta_t = float(self._traci_connection.simulation.getDeltaT())
        except Exception:
            return 1.0
        if delta_t > 10.0:
            delta_t = delta_t / 1000.0
        return max(0.1, delta_t)

    def _log_validation_warnings(self, issues: list) -> None:
        for issue in issues:
            if issue.level != "warning":
                continue
            location = f" ({issue.file})" if issue.file else ""
            self.logProduced.emit(f"运行前校验 WARNING: {issue.message}{location}")

    def _build_startup_error_message(self, project_dir: Path, sumocfg_path: Path, remote_port: int, exc: Exception) -> str:
        parts = [
            f"启动仿真失败：{exc}",
            f"项目目录: {project_dir}",
            f"配置文件: {sumocfg_path}",
            f"TraCI 端口: {remote_port}",
        ]
        if self.process_manager.last_command:
            parts.append(f"启动命令: {self.process_manager.last_command_text()}")
        exit_code = self.process_manager.poll_exit_code()
        if exit_code is not None:
            parts.append(f"进程退出码: {exit_code}")
        stdout_text, stderr_text = self.process_manager.read_available_output()
        if stderr_text.strip():
            parts.append(f"stderr: {stderr_text.strip()}")
        elif stdout_text.strip():
            parts.append(f"stdout: {stdout_text.strip()}")
        return "\n".join(parts)

    def _set_error(self, message: str) -> None:
        self._monitor_timer.stop()
        self._step_timer.stop()
        self._state = SimulationRuntimeState(
            status=RunnerStatus.ERROR.value,
            current_time=self._state.current_time,
            vehicle_count=self._state.vehicle_count,
            average_speed=self._state.average_speed,
            message=message,
            signal_status=None,
        )
        self.stateChanged.emit(self._state)
        self.logProduced.emit(f"运行错误：{message}")
        self.runFailed.emit(message)

    def _read_signal_status(self) -> SignalRuntimeStatus | None:
        if self._traci_connection is None:
            return None
        try:
            tls_ids = list(self._traci_connection.trafficlight.getIDList())
        except Exception:
            return None
        if not tls_ids:
            return None
        tls_id = tls_ids[0]
        try:
            return SignalRuntimeStatus(
                tls_id=tls_id,
                program_id=str(self._traci_connection.trafficlight.getProgram(tls_id)),
                phase_index=int(self._traci_connection.trafficlight.getPhase(tls_id)),
                phase_name=str(self._traci_connection.trafficlight.getPhaseName(tls_id) or ""),
                next_switch_time=float(self._traci_connection.trafficlight.getNextSwitch(tls_id)),
            )
        except Exception:
            return None
