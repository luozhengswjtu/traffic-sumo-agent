from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator


SignalPlanName = Literal["balanced", "ns_priority", "ew_priority", "custom"]


class SignalPlanSpec(BaseModel):
    enabled: bool = False
    controller_type: Literal["fixed_time"] = "fixed_time"
    plan_name: SignalPlanName = "balanced"
    cycle_seconds: int = 80
    offset_seconds: int = 0
    yellow_seconds: int = 3
    all_red_seconds: int = 1
    ns_green_seconds: int = 36
    ew_green_seconds: int = 36

    @model_validator(mode="after")
    def _validate_ranges(self) -> "SignalPlanSpec":
        if self.cycle_seconds < 20:
            raise ValueError("cycle_seconds must be at least 20.")
        if self.offset_seconds < 0:
            raise ValueError("offset_seconds must be >= 0.")
        if self.yellow_seconds < 0:
            raise ValueError("yellow_seconds must be >= 0.")
        if self.all_red_seconds < 0:
            raise ValueError("all_red_seconds must be >= 0.")
        if self.ns_green_seconds < 5:
            raise ValueError("ns_green_seconds must be at least 5.")
        if self.ew_green_seconds < 5:
            raise ValueError("ew_green_seconds must be at least 5.")
        return self


class SignalPhasePreview(BaseModel):
    name: str
    duration_seconds: int
    state_kind: Literal["green", "yellow", "all_red"]


class SignalRuntimeStatus(BaseModel):
    tls_id: str
    program_id: str
    phase_index: int
    phase_name: str = ""
    next_switch_time: float = 0.0


class SignalPlanUpdate(BaseModel):
    enabled: bool | None = None
    plan_name: SignalPlanName | None = None
    cycle_seconds: int | None = None
    offset_seconds: int | None = None
    yellow_seconds: int | None = None
    all_red_seconds: int | None = None
    ns_green_seconds: int | None = None
    ew_green_seconds: int | None = None
    reset: bool = False


PRESET_SPLITS: dict[SignalPlanName, tuple[int, int]] = {
    "balanced": (1, 1),
    "ns_priority": (3, 2),
    "ew_priority": (2, 3),
    "custom": (1, 1),
}


def default_signal_plan() -> SignalPlanSpec:
    return SignalPlanSpec()


def signal_plan_summary_label(plan: SignalPlanSpec | None) -> str:
    if plan is None or not plan.enabled:
        return "disabled"
    return plan.plan_name


def signal_plan_preview(plan: SignalPlanSpec | None) -> list[SignalPhasePreview]:
    if plan is None or not plan.enabled:
        return []
    phases = [
        SignalPhasePreview(name="ns_green", duration_seconds=plan.ns_green_seconds, state_kind="green"),
        SignalPhasePreview(name="ns_yellow", duration_seconds=plan.yellow_seconds, state_kind="yellow"),
    ]
    if plan.all_red_seconds > 0:
        phases.append(SignalPhasePreview(name="all_red_1", duration_seconds=plan.all_red_seconds, state_kind="all_red"))
    phases.extend(
        [
            SignalPhasePreview(name="ew_green", duration_seconds=plan.ew_green_seconds, state_kind="green"),
            SignalPhasePreview(name="ew_yellow", duration_seconds=plan.yellow_seconds, state_kind="yellow"),
        ]
    )
    if plan.all_red_seconds > 0:
        phases.append(SignalPhasePreview(name="all_red_2", duration_seconds=plan.all_red_seconds, state_kind="all_red"))
    return phases


def normalize_signal_plan(
    base_plan: SignalPlanSpec | None,
    update: SignalPlanUpdate | None = None,
) -> SignalPlanSpec | None:
    if update is not None and update.reset:
        return None

    if update is None:
        if base_plan is None:
            return None
        return _normalize_existing_plan(base_plan.model_copy(deep=True))

    if update.enabled is False:
        return None

    plan = base_plan.model_copy(deep=True) if base_plan is not None else default_signal_plan()
    if update.enabled is True:
        plan.enabled = True

    explicit_green_update = any(value is not None for value in (update.ns_green_seconds, update.ew_green_seconds))

    for field_name in (
        "plan_name",
        "cycle_seconds",
        "offset_seconds",
        "yellow_seconds",
        "all_red_seconds",
        "ns_green_seconds",
        "ew_green_seconds",
    ):
        value = getattr(update, field_name)
        if value is not None:
            setattr(plan, field_name, value)

    if explicit_green_update:
        plan.plan_name = "custom"
        available_green = plan.cycle_seconds - 2 * (plan.yellow_seconds + plan.all_red_seconds)
        if update.ns_green_seconds is not None and update.ew_green_seconds is None:
            plan.ew_green_seconds = available_green - plan.ns_green_seconds
        elif update.ew_green_seconds is not None and update.ns_green_seconds is None:
            plan.ns_green_seconds = available_green - plan.ew_green_seconds

    return _normalize_existing_plan(plan)


def _normalize_existing_plan(plan: SignalPlanSpec) -> SignalPlanSpec:
    if not plan.enabled:
        return plan

    available_green = plan.cycle_seconds - 2 * (plan.yellow_seconds + plan.all_red_seconds)
    if available_green < 10:
        raise ValueError("cycle_seconds is too short for the configured yellow/all_red phases.")

    if plan.plan_name != "custom":
        ns_weight, ew_weight = PRESET_SPLITS[plan.plan_name]
        total_weight = ns_weight + ew_weight
        ns_green = max(5, int(round(available_green * ns_weight / total_weight)))
        ew_green = available_green - ns_green
        if ew_green < 5:
            ew_green = 5
            ns_green = available_green - ew_green
        if ns_green < 5:
            ns_green = 5
            ew_green = available_green - ns_green
        plan.ns_green_seconds = ns_green
        plan.ew_green_seconds = ew_green
        return plan

    if plan.ns_green_seconds + plan.ew_green_seconds != available_green:
        plan.cycle_seconds = plan.ns_green_seconds + plan.ew_green_seconds + 2 * (plan.yellow_seconds + plan.all_red_seconds)
    return plan
