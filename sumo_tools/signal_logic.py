from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from sumo_domain.signal_plan import SignalPhasePreview, SignalPlanSpec, signal_plan_preview


DEFAULT_TLS_ID = "center"
TLS_ADDITIONAL_FILENAME = "scenario.tls.add.xml"
TLS_PROGRAM_ID = "traffic_agent_fixed_v1"
SUPPORTED_SIGNAL_SCENARIOS = {"intersection", "t_junction"}


def is_signal_supported_scenario(scenario_type: str | None) -> bool:
    return (scenario_type or "").strip().lower() in SUPPORTED_SIGNAL_SCENARIOS


def signal_additional_files(signal_plan: SignalPlanSpec | None) -> list[str]:
    if signal_plan is None or not signal_plan.enabled:
        return []
    return [TLS_ADDITIONAL_FILENAME]


def ensure_supported_signal_plan(scenario_type: str | None, signal_plan: SignalPlanSpec | None) -> None:
    if signal_plan is None or not signal_plan.enabled:
        return
    if not is_signal_supported_scenario(scenario_type):
        raise ValueError("signal plan is only supported for intersection and t_junction.")


def build_signal_phase_preview(signal_plan: SignalPlanSpec | None) -> list[SignalPhasePreview]:
    return signal_plan_preview(signal_plan)


def write_signal_additional_file(
    net_file: Path,
    output_path: Path,
    signal_plan: SignalPlanSpec,
    preferred_tls_id: str = DEFAULT_TLS_ID,
) -> Path:
    root = ET.parse(net_file).getroot()
    base_logic = _select_tl_logic(root, preferred_tls_id)
    green_phases = _extract_green_yellow_phases(base_logic)

    additional_root = ET.Element("additional")
    logic_attrs = {
        "id": base_logic.attrib.get("id", preferred_tls_id),
        "type": base_logic.attrib.get("type", "static"),
        "programID": TLS_PROGRAM_ID,
        "offset": str(signal_plan.offset_seconds),
    }
    logic_element = ET.SubElement(additional_root, "tlLogic", **logic_attrs)

    phase_specs = [
        ("ns_green", signal_plan.ns_green_seconds, green_phases[0].attrib["state"]),
        ("ns_yellow", signal_plan.yellow_seconds, green_phases[1].attrib["state"]),
    ]
    if signal_plan.all_red_seconds > 0:
        phase_specs.append(("all_red_1", signal_plan.all_red_seconds, _to_all_red_state(green_phases[1].attrib["state"])))
    phase_specs.extend(
        [
            ("ew_green", signal_plan.ew_green_seconds, green_phases[2].attrib["state"]),
            ("ew_yellow", signal_plan.yellow_seconds, green_phases[3].attrib["state"]),
        ]
    )
    if signal_plan.all_red_seconds > 0:
        phase_specs.append(("all_red_2", signal_plan.all_red_seconds, _to_all_red_state(green_phases[3].attrib["state"])))

    for phase_name, duration_seconds, state in phase_specs:
        ET.SubElement(
            logic_element,
            "phase",
            duration=str(duration_seconds),
            state=state,
            name=phase_name,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(additional_root)
    ET.ElementTree(additional_root).write(output_path, encoding="utf-8", xml_declaration=True)
    return output_path


def _select_tl_logic(root: ET.Element, preferred_tls_id: str) -> ET.Element:
    all_logics = list(root.findall("tlLogic"))
    if not all_logics:
        raise ValueError("generated net.xml does not contain tlLogic.")

    for logic in all_logics:
        if logic.attrib.get("id") == preferred_tls_id:
            return logic

    if len(all_logics) == 1:
        return all_logics[0]
    raise ValueError(f"unable to determine tlLogic id, expected '{preferred_tls_id}'.")


def _extract_green_yellow_phases(logic_element: ET.Element) -> list[ET.Element]:
    phases = list(logic_element.findall("phase"))
    if len(phases) < 4:
        raise ValueError("tlLogic must contain at least 4 phases for fixed-time export.")

    extracted = phases[:4]
    if not _is_green_phase(extracted[0].attrib.get("state", "")):
        raise ValueError("phase 0 is not a green phase.")
    if not _is_yellow_phase(extracted[1].attrib.get("state", "")):
        raise ValueError("phase 1 is not a yellow phase.")
    if not _is_green_phase(extracted[2].attrib.get("state", "")):
        raise ValueError("phase 2 is not a green phase.")
    if not _is_yellow_phase(extracted[3].attrib.get("state", "")):
        raise ValueError("phase 3 is not a yellow phase.")
    return extracted


def _is_green_phase(state: str) -> bool:
    lowered = state.lower()
    return ("g" in lowered) and ("y" not in lowered)


def _is_yellow_phase(state: str) -> bool:
    return "y" in state.lower()


def _to_all_red_state(state: str) -> str:
    return "r" * len(state)
