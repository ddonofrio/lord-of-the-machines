# Lord of the Machines: Technical Architecture Baseline

## Overview
Lord of the Machines is an autonomous software system designed for extensible, agent-based mission execution. Each agent operates with distinct roles (such as Software Developer, Reviewer), leveraging reusable tools and a consistent runtime framework to solve complex, multi-phase missions.

## Key Architectural Components

### 1. Mission Lifecycle
- **Missions** are top-level tasks identified by a unique `mission_id`, with distinct phases (e.g., product_direction, implementation).
- **Phases** represent steps in delivery, influencing available actions and agent roles.
- The **Mission Registry** coordinates these, ensuring flows and state transitions.
- Artifacts and events are persisted in internal storage (`.state/missions/`, `.state/artifacts/`).

### 2. Agents and Tools
- **Agents** are composable LLM-driven processes executing roles via structured tool calls.
- **Tools** are functional APIs exposed to agents, allowing operations such as file editing, diagnostics, or communication. Each agent can request, enumerate, and call available tools, with responses governed by the system contract.
- The `src/lord_of_the_machines/agent_tools/` directory provides core tool implementations (e.g., software_development_environment, memory, communication).

### 3. Runtime and Communication
- **Runtime** modules (`src/lord_of_the_machines/runtime/`) provide the orchestration logic that manages agent activation, tool exposure, environment isolation, and state tracking.
- **Roles and Contracts:** Each agent follows a role-specific process contract as defined in task inputs (e.g., manifest schemas, messaging contract).
- **Tool Results and Sessions:** Agent reasoning is based on structured tool results, not just textual input, which ensures traceability and auditability.
- All agent actions are logged for transparency via the activity journal.

### 4. Extension Points
- **Adding Missions:** Define new mission types or workflows in `src/lord_of_the_machines/mission/`.
- **Adding Tools:** Extend `src/lord_of_the_machines/agent_tools/` with new tool APIs and register them in the runtime.
- **Adding Roles:** Implement new agent behaviors by composing role-specific contracts and integrating with mission flows.

## Example Runtime Flow
1. Mission is initiated (with payload, phase, context).
2. System orchestrates the current agent's activation based on phase and requirements.
3. Agent receives current workspace state, mission context, and any conversation history.
4. Agent calls tools (e.g. software_development_environment, memory) via structured tool call lists.
5. Tool responses are returned; agent reasons further or completes action.
6. Upon role task completion, a summary/result schema is submitted.
7. Mission flow transitions, new agents may be activated for review or next phase.

## Codebase Organization
- `src/lord_of_the_machines/mission/`: Mission logic, phase transitions, core orchestrator.
- `src/lord_of_the_machines/agent_tools/`: Core tools available to agents.
- `src/lord_of_the_machines/runtime/`: Runtime engine and orchestrator modules.
- `tests/`: Automated tests with high coverage expectation.
- `.state/`: Internal state, artifacts, event logs.
- `docs/`: System documentation (this baseline, extension guides, architecture diagrams).

## Useful References
- **Role Contract Example:** Each agent receives an explicit task contract, system guidance, and limited toolset for each task.
- **Tooling:** Standard tools include `software_development_environment` (file and code management), `memory` (internal knowledge store), and project diagnostics (pytest, mypy, bandit, ruff in CI).

## See Also
- [README.md](../README.md) for project orientation and entry points.

---
This document serves as the canonical baseline for how Lord of the Machines operates today. Extension efforts or new role agent on-boarding should begin with this reference.
