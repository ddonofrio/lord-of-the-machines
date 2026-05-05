# Lord of the Machines – Technical Architecture Baseline

## Overview
Lord of the Machines is an autonomous AI system designed to execute complex software development missions through a structured, multi-role pipeline. It leverages a modular LLM agent runtime, interconnected tools, and a phase-driven mission lifecycle to iteratively design, implement, and improve itself and its outputs.

## Architectural Layers

- **Agent Runtime Core**: The foundation is the `BaseAgent`, a configurable orchestrator responsible for protocol compliance, role management, tool execution, and interaction between LLM and tools. Main components:
    - `src/lord_of_the_machines/base_agent.py`
    - Manages the input/output protocol, memory, pagination, and tool-calling logic.

- **Tool System**: Implemented under `src/lord_of_the_machines/agent_tools/` and as separate tool modules (e.g., `software_development_environment`, `todo_list`, `mission_registry`, `meeting` tool). Tools provide concrete actions like file edits, environment inspections, diagnostics, and coordination.

- **Mission Runtime**:
    - `src/lord_of_the_machines/mission/`
    - The `MissionRuntime` class orchestrates mission events, phase transitions, and agent/tool bindings.
    - Phase-specific logic enforces required artifacts and handoffs between roles such as `product_director`, `product_manager`, `software_architect`, `software_development_manager`, and `software_developer`.

- **Artifact and Event Registries**: 
    - `artifact_registry` maintains versioned artifacts for each mission/phase.
    - `event_bus` provides persistent event streaming with offsets for event-driven orchestration and auditing.
    - `mission_registry` tracks lifecycle state, phase statuses, and assignments.

- **History and Memory**:
    - Local conversation state is managed via `history.py`.
    - Internal memory (`memory.py`) supports persistent facts, and the `pagination.py` module handles long output.

## Runtime Flow

1. **Mission Intake**: New requirements are registered in `mission_registry`.
2. **Phase Execution**: For each mission phase, the mission runtime triggers the appropriate agent (role) to execute and produce an artifact.
3. **Artifact Handoff**: Artifacts (designs, plans, code, documentation) are versioned and handed off to the next phase through the `artifact_registry`.
4. **Tool Calls**: Agents make structured tool calls for file I/O (`software_development_environment`), meetings (`meeting` tool), etc.
5. **Decision and Validation**: Diagnostics, tests, and reviews are performed, often requested by tool calls or as explicit validation steps in the pipeline.
6. **Completion or Loop**: Once all acceptance criteria are met, the mission is completed. Otherwise, workflow cycles with follow-ups, risk mitigation, or quality improvements.

## Extension Points
- **New tools** can be added by implementing the tool interface and registering under `agent_tools`.
- **Additional roles/phases** are registered in the system protocol and mission runtime logic.
- **External integrations** can be handled through additional `providers/` or modifying the transport and envelope layers.

## Key Files and Modules
- `src/lord_of_the_machines/base_agent.py` – Core runtime agent
- `src/lord_of_the_machines/agent_tools/` – Tool package implementations
- `src/lord_of_the_machines/mission/` – Mission runtime/event/registry logic
    - `mission.py`, `artifact_registry.py`, `event_bus.py`, `mission_registry.py`
- `src/lord_of_the_machines/history.py`, `memory.py`, `pagination.py` – Conversation, memory, and long-output handling
- `README.md` – Entry point with documentation links
- `docs/technical-architecture-baseline.md` – This document

## Versioning and Change Management
- All artifacts and missions are versioned in `artifact_registry`.
- Documentation must be updated with meaningful architectural or interface changes, enforced by acceptance criteria and review tasks.

## See Also
- `README.md` (contains usage, project overview, and links)
- Tests under `tests/` for concrete runtime and tool behaviors

---
*This document is reviewed in every major phase or architectural update. For details on individual tools, see their respective modules under `src/lord_of_the_machines/agent_tools/`.*
