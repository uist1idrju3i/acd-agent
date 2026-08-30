"""Typed extraction of firmware declarations from a design graph."""

from __future__ import annotations

from dataclasses import dataclass

from acd.core.electrical import GraphExtractionError
from acd.schema.design_graph import DesignGraph, GraphNode


@dataclass(frozen=True)
class FirmwareModuleView:
    node_id: str
    module_name: str
    mcu_component: str
    entry_state: str


@dataclass(frozen=True)
class FirmwareStateView:
    node_id: str
    state_name: str
    initial: bool


@dataclass(frozen=True)
class FirmwareStateTransitionView:
    node_id: str
    from_state: str
    to_state: str
    trigger: str


@dataclass(frozen=True)
class FirmwareSequenceStepView:
    node_id: str
    step_index: int
    actor: str
    target: str
    action: str


@dataclass(frozen=True)
class FirmwarePinAssignmentView:
    node_id: str
    gpio: int
    net: str


@dataclass(frozen=True)
class FirmwareLane:
    module: FirmwareModuleView
    states: tuple[FirmwareStateView, ...]
    transitions: tuple[FirmwareStateTransitionView, ...]
    sequence_steps: tuple[FirmwareSequenceStepView, ...]
    pin_assignments: tuple[FirmwarePinAssignmentView, ...]


def _str_attr(node: GraphNode, key: str) -> str:
    value = node.attrs.get(key)
    if not isinstance(value, str) or not value:
        raise GraphExtractionError(
            f"node {node.id!r}: attr {key!r} missing or not a string"
        )
    return value


def _int_attr(node: GraphNode, key: str) -> int:
    value = node.attrs.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise GraphExtractionError(
            f"node {node.id!r}: attr {key!r} missing or not an integer"
        )
    return value


def _bool_attr(node: GraphNode, key: str) -> bool:
    value = node.attrs.get(key)
    if not isinstance(value, bool):
        raise GraphExtractionError(
            f"node {node.id!r}: attr {key!r} missing or not a boolean"
        )
    return value


def _require_dependency_set(
    node: GraphNode, expected: set[str], relation: str
) -> None:
    if set(node.depends_on) != expected:
        raise GraphExtractionError(
            f"node {node.id!r}: {relation} dependencies do not match declaration"
        )


def _require_kind(
    nodes: dict[str, GraphNode], node_id: str, expected_kind: str, field: str
) -> GraphNode:
    target = nodes.get(node_id)
    if target is None:
        raise GraphExtractionError(
            f"node reference {field}={node_id!r} does not exist"
        )
    if target.kind != expected_kind:
        raise GraphExtractionError(
            f"node reference {field}={node_id!r} is not {expected_kind}"
        )
    return target


def extract_firmware_lane(graph: DesignGraph) -> FirmwareLane:
    nodes = {node.id: node for node in graph.nodes}
    module_nodes = [node for node in graph.nodes if node.kind == "firmware.module"]
    if len(module_nodes) != 1:
        raise GraphExtractionError(
            f"expected exactly one firmware.module node, got {len(module_nodes)}"
        )
    module_node = module_nodes[0]

    state_nodes = sorted(
        (node for node in graph.nodes if node.kind == "firmware.state"),
        key=lambda node: node.id,
    )
    if not state_nodes:
        raise GraphExtractionError("firmware lane requires at least one state")
    state_ids = {node.id for node in state_nodes}
    mcu_component = _str_attr(module_node, "mcu_component")
    entry_state = _str_attr(module_node, "entry_state")
    _require_kind(nodes, mcu_component, "electrical.component", "mcu_component")
    _require_kind(nodes, entry_state, "firmware.state", "entry_state")
    _require_dependency_set(
        module_node,
        {mcu_component, *state_ids},
        "firmware.module",
    )
    module = FirmwareModuleView(
        node_id=module_node.id,
        module_name=_str_attr(module_node, "module_name"),
        mcu_component=mcu_component,
        entry_state=entry_state,
    )

    states: list[FirmwareStateView] = []
    for node in state_nodes:
        _require_dependency_set(node, {module_node.id}, "firmware.state")
        states.append(
            FirmwareStateView(
                node_id=node.id,
                state_name=_str_attr(node, "state_name"),
                initial=_bool_attr(node, "initial"),
            )
        )
    initial_states = [state for state in states if state.initial]
    if len(initial_states) != 1:
        raise GraphExtractionError(
            f"expected exactly one initial firmware state, got {len(initial_states)}"
        )
    if initial_states[0].node_id != entry_state:
        raise GraphExtractionError(
            "firmware.module entry_state does not match the initial state"
        )

    transition_nodes = sorted(
        (
            node
            for node in graph.nodes
            if node.kind == "firmware.state_transition"
        ),
        key=lambda node: node.id,
    )
    if not transition_nodes:
        raise GraphExtractionError(
            "firmware lane requires at least one state transition"
        )
    transitions: list[FirmwareStateTransitionView] = []
    transition_keys: set[tuple[str, str, str]] = set()
    for node in transition_nodes:
        from_state = _str_attr(node, "from_state")
        to_state = _str_attr(node, "to_state")
        trigger = _str_attr(node, "trigger")
        _require_kind(nodes, from_state, "firmware.state", "from_state")
        _require_kind(nodes, to_state, "firmware.state", "to_state")
        _require_dependency_set(node, {from_state, to_state}, "state transition")
        key = (from_state, to_state, trigger)
        if key in transition_keys:
            raise GraphExtractionError(
                f"duplicate firmware state transition declaration: {key!r}"
            )
        transition_keys.add(key)
        transitions.append(
            FirmwareStateTransitionView(
                node_id=node.id,
                from_state=from_state,
                to_state=to_state,
                trigger=trigger,
            )
        )
    transition_states = {
        state_id
        for transition in transitions
        for state_id in (transition.from_state, transition.to_state)
    }
    if transition_states != state_ids:
        missing = sorted(state_ids - transition_states)
        raise GraphExtractionError(
            "firmware states do not all participate in transitions: "
            + ", ".join(missing)
        )
    reachable = {entry_state}
    while True:
        expanded = reachable | {
            transition.to_state
            for transition in transitions
            if transition.from_state in reachable
        }
        if expanded == reachable:
            break
        reachable = expanded
    if reachable != state_ids:
        raise GraphExtractionError(
            "firmware states are not all reachable from the entry state: "
            + ", ".join(sorted(state_ids - reachable))
        )

    sequence_nodes = sorted(
        (node for node in graph.nodes if node.kind == "firmware.sequence_step"),
        key=lambda node: node.id,
    )
    if not sequence_nodes:
        raise GraphExtractionError(
            "firmware lane requires at least one sequence step"
        )
    sequence_steps: list[FirmwareSequenceStepView] = []
    sequence_ids: set[int] = set()
    for node in sequence_nodes:
        step_index = _int_attr(node, "step_index")
        if step_index in sequence_ids:
            raise GraphExtractionError(
                f"duplicate firmware sequence step index: {step_index}"
            )
        sequence_ids.add(step_index)
        actor = _str_attr(node, "actor")
        target = _str_attr(node, "target")
        _require_kind(nodes, actor, "firmware.module", "actor")
        target_node = nodes.get(target)
        if target_node is None:
            raise GraphExtractionError(
                f"node reference target={target!r} does not exist"
            )
        if target_node.kind not in {"firmware.module", "electrical.component"}:
            raise GraphExtractionError(
                f"node reference target={target!r} has an unsupported kind"
            )
        _require_dependency_set(node, {actor, target}, "sequence step")
        sequence_steps.append(
            FirmwareSequenceStepView(
                node_id=node.id,
                step_index=step_index,
                actor=actor,
                target=target,
                action=_str_attr(node, "action"),
            )
        )
    sequence_steps.sort(key=lambda step: step.step_index)
    expected_indexes = list(range(1, len(sequence_steps) + 1))
    if [step.step_index for step in sequence_steps] != expected_indexes:
        raise GraphExtractionError(
            "firmware sequence step_index must be a contiguous 1-based sequence"
        )

    pin_nodes = sorted(
        (node for node in graph.nodes if node.kind == "firmware.pin_assignment"),
        key=lambda node: node.id,
    )
    pin_assignments: list[FirmwarePinAssignmentView] = []
    for node in pin_nodes:
        net = _str_attr(node, "net")
        _require_kind(nodes, net, "electrical.net", "net")
        _require_dependency_set(node, {net}, "pin assignment")
        pin_assignments.append(
            FirmwarePinAssignmentView(
                node_id=node.id,
                gpio=_int_attr(node, "gpio"),
                net=net,
            )
        )

    states.sort(key=lambda state: state.node_id)
    transitions.sort(key=lambda transition: transition.node_id)
    pin_assignments.sort(key=lambda assignment: assignment.node_id)
    return FirmwareLane(
        module=module,
        states=tuple(states),
        transitions=tuple(transitions),
        sequence_steps=tuple(sequence_steps),
        pin_assignments=tuple(pin_assignments),
    )
