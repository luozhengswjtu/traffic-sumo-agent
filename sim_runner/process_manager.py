from __future__ import annotations

import shutil
import socket
import subprocess
from pathlib import Path

from storage.path_utils import normalize_local_path


class SumoProcessManager:
    """Manage SUMO process lifecycle using local sumo or sumo-gui executables."""

    def __init__(self, prefer_gui: bool = True) -> None:
        self.prefer_gui = prefer_gui
        self.process: subprocess.Popen | None = None
        self.last_command: list[str] = []
        self.last_remote_port: int | None = None

    def start(self, sumocfg_path: Path, remote_port: int | None = None) -> list[str]:
        if self.is_running():
            raise RuntimeError("SUMO 进程已在运行。")
        sumocfg_path = normalize_local_path(sumocfg_path)
        if not sumocfg_path.exists():
            raise FileNotFoundError(f"未找到 sumocfg 文件: {sumocfg_path}")
        if remote_port is not None:
            if not isinstance(remote_port, int):
                raise TypeError(f"remote_port 必须是整数，当前值为: {remote_port!r}")
            if remote_port <= 0:
                raise ValueError(f"remote_port 必须大于 0，当前值为: {remote_port}")

        executable = self._resolve_executable()
        command = [executable, "-c", str(sumocfg_path)]
        if remote_port is not None:
            command.extend(["--remote-port", str(remote_port)])
        if executable.lower().endswith("sumo-gui.exe"):
            command.extend(["--start", "true", "--quit-on-end", "true"])

        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(sumocfg_path.parent),
        )
        self.last_command = command
        self.last_remote_port = remote_port
        return command

    def stop(self) -> None:
        if not self.process:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        self.last_remote_port = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def poll_exit_code(self) -> int | None:
        if self.process is None:
            return None
        return self.process.poll()

    def read_available_output(self) -> tuple[str, str]:
        if self.process is None:
            return "", ""

        if self.process.poll() is not None:
            stdout_text, stderr_text = self.process.communicate()
            return stdout_text or "", stderr_text or ""

        return "", ""

    def executable_path(self) -> str | None:
        return self._resolve_executable(optional=True)

    def last_command_text(self) -> str:
        return " ".join(self.last_command)

    @staticmethod
    def allocate_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            return int(sock.getsockname()[1])

    def _resolve_executable(self, optional: bool = False) -> str | None:
        candidates = ["sumo-gui", "sumo"] if self.prefer_gui else ["sumo", "sumo-gui"]
        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                return found
        if optional:
            return None
        raise FileNotFoundError("未找到 sumo 或 sumo-gui 可执行文件。")
