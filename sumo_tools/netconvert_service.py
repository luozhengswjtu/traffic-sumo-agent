from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET

from storage.path_utils import normalize_local_path


class NetconvertService:
    """Wrap netconvert when available and provide a documented fallback when not."""

    def is_available(self) -> bool:
        return shutil.which("netconvert") is not None

    def build_net_file(self, project_dir: Path, node_file: Path, edge_file: Path) -> Path:
        project_dir = normalize_local_path(project_dir)
        node_file = normalize_local_path(node_file)
        edge_file = normalize_local_path(edge_file)
        if not node_file.exists():
            raise FileNotFoundError(f"未找到 node 文件: {node_file}")
        if not edge_file.exists():
            raise FileNotFoundError(f"未找到 edge 文件: {edge_file}")

        output_path = normalize_local_path(project_dir / "sumo" / "scenario.net.xml")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()

        if self.is_available():
            result = subprocess.run(
                [
                    "netconvert",
                    "--node-files",
                    str(node_file),
                    "--edge-files",
                    str(edge_file),
                    "--output-file",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(output_path.parent),
            )
            if result.returncode != 0:
                if output_path.exists():
                    output_path.unlink()
                details = result.stderr.strip() or result.stdout.strip() or "netconvert 执行失败"
                raise RuntimeError(f"netconvert 执行失败: {details}")
            if not output_path.exists():
                raise RuntimeError("netconvert 已返回成功，但未生成 scenario.net.xml。")
            return output_path

        self._write_placeholder_net(output_path)
        return output_path

    @staticmethod
    def _write_placeholder_net(path: Path) -> None:
        root = ET.Element("net", version="placeholder", placeholder="true")
        ET.SubElement(
            root,
            "location",
            netOffset="0.00,0.00",
            convBoundary="-100.00,-100.00,100.00,100.00",
            origBoundary="-100.00,-100.00,100.00,100.00",
        )
        ET.indent(root)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
