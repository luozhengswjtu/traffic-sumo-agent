from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET


class NetconvertService:
    """Wrap netconvert when available and provide a documented fallback when not."""

    def is_available(self) -> bool:
        return shutil.which("netconvert") is not None

    def build_net_file(self, project_dir: Path, node_file: Path, edge_file: Path) -> Path:
        output_path = project_dir / "sumo" / "scenario.net.xml"
        output_path.parent.mkdir(parents=True, exist_ok=True)

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
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "netconvert 执行失败")
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
