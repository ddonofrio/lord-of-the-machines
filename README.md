# Lord of the Machines

Lord of the Machines is a new lab for building an autonomous AI system that can read its own code, improve its own tools, and move toward a mission it is given.

This first cut focuses on getting the foundation right: a generic, configurable, and tested LLM agent core, plus the first serious tool package for software development work. There is no autonomous mission server or self-programming loop yet; those layers should be built on top of this core.

## Current Status

Included so far:

- A standard Python project layout with `src/`, `tests/`, `config/`, `pyproject.toml`, and an installable package.
- `BaseAgent`, kept as the name because it accurately describes the primitive: a configurable abstraction layer over an LLM, not a domain agent.
- A modular LLM runtime where `BaseAgent` acts as a small orchestrator and larger responsibilities live in dedicated modules:
  - `config.py`: configuration models, named defaults, and loading.
  - `payload.py`: payload construction, instructions, envelope, and input shaping.
  - `providers/`: provider adapters and provider-specific native tool calling behavior.
  - `transport.py`: OpenAI Responses API integration, retries, rate-limit handling, and verbosity fallback.
  - `history.py`: local history and context budgeting.
  - `parser.py`: output parsing and protocol validation.
  - `tools.py` and `memory.py`: tool registration/execution and internal memory.
  - `prompt_cache.py`: `prompt_cache_key` generation.
  - `rate_limit.py`, `tokens.py`, `schema.py`, `replies.py`, and `errors.py`: focused low-level primitives.
- Configuration separated by responsibility:
  - `provider`: provider details, model selection, API key env var, and model override env var.
  - `agent`: system prompt, memory, repair policy, and tool-round limits.
  - `reply`: the tool/method/argument used to extract final assistant messages.
  - `tool_calling`: whether the agent uses the internal JSON protocol for tool calls or OpenAI native function calling.
  - `envelope`: configurable input and output protocol contract.
  - `context`: local history policy and context-budget behavior.
  - `transport`: retries, backoff, and rate-limiting behavior.
  - `prompt_cache`: stable cache-key behavior and field selection.
  - `response_defaults`: OpenAI Responses API defaults.
- `AgentEnvelopeSpec`, which defines the top-level fields included in the request envelope.
- `ToolCallOutputSpec`, which defines the expected output shape (`calls/tool/method/arguments` by default, but fully renameable).
- Typed `ToolDefinition` and `ToolMethodDefinition` contracts as the internal and public tool model.
- Strict config loading for `BaseAgent`: only the current structured config schema is accepted.
- Internal memory compatible with `memory.remember`, `memory.recall`, and `memory.forget`.
- Protocol repair when the model returns invalid JSON or an unsupported tool/method combination.
- Tool execution with tool-result feedback loops until the model produces a final answer.
- Clean local history that stores real conversational messages rather than envelopes or repair prompts.
- Token estimation preflight, local rate limiting, `429` retries, and unsupported-verbosity fallback.
- Configurable prompt caching through `prompt_cache.fields`.
- Unit tests using a fake OpenAI client.
- A first `agent_tools` package under `src/lord_of_the_machines/agent_tools/`.
- `software_development_environment`, a tool package for file reads, controlled edits, search, safe command execution, diagnostics, git inspection, project-context detection, and a persisted activity journal in `logs/`.
- `todo_list`, a tool package for per-agent TODO list files with task creation, completion/uncompletion, removal, and progress inspection.
- `mission_registry`, a persistent mission catalog with lifecycle state, phase status tracking, and role assignments.
- `event_bus`, a persistent event stream with consumer offsets and acknowledgements for event-driven orchestration.
- `artifact_registry`, a versioned registry for mission artifacts and phase outputs.
- `mission` runtime primitives for event-driven orchestration:
  - `MissionRuntime`: consumes mission events and drives phase execution.
  - `AgentAsToolBridge`: exposes specialized agents as tools.
  - `MeetingToolAgent`: a dedicated meeting coordinator agent exposed as a tool.

## Main Configuration

Default config file:

```text
config/base_agent.json
```

Environment variable override:

```text
LORD_OF_THE_MACHINES_BASE_AGENT_CONFIG
```

Default model:

```text
gpt-4.1
```

You can override the model without editing JSON via:

```text
OPENAI_MODEL
```

## Flexible Envelope

The agent no longer hardcodes a single request envelope shape. `AgentEnvelopeSpec` controls which input fields are sent:

```python
AgentEnvelopeSpec(
    version="custom.agent.v1",
    input_fields=[
        EnvelopeField("protocol", "protocol"),
        EnvelopeField("history", "conversation_history"),
        EnvelopeField("context", "runtime_context"),
        EnvelopeField("request", "user"),
        EnvelopeField("contract", "output_contract"),
    ],
)
```

And `ToolCallOutputSpec` controls the output shape the agent validates:

```python
ToolCallOutputSpec(
    calls_field="actions",
    tool_field="tool_name",
    method_field="operation",
    arguments_field="args",
)
```

This makes it possible to support multiple protocol contracts without rewriting `BaseAgent`.

## Tool Calling Modes

`BaseAgent` now supports two tool-calling modes:

- `protocol`:
  the current default. The model receives conceptual tools inside the input envelope and returns a JSON tool-call list that the agent parses and validates locally.
- `openai_native`:
  OpenAI native function calling. The agent converts conceptual tools into provider-native function definitions, sends them in the Responses API `tools` field, parses `function_call` items from the response, executes handlers locally, and continues tool rounds using `function_call_output`.

Default config:

```json
"tool_calling": {
  "mode": "protocol",
  "native_name_separator": "__",
  "include_tools_in_envelope": false,
  "include_output_contract_in_envelope": false
}
```

To enable native OpenAI tool calling:

```json
"tool_calling": {
  "mode": "openai_native"
}
```

In native mode, the agent still keeps the same internal conceptual tool model, so the same tool package can be used through the old protocol path or the OpenAI-native path.

## Typed Tool Contracts

Tools are no longer treated as loose dictionaries inside the runtime API surface. `BaseAgent.add_tool(...)` and `BaseAgent.list_tools()` now operate on typed `ToolDefinition` and `ToolMethodDefinition` objects.

JSON config files still describe tools as JSON objects, but that mapping is normalized at load time. Once the runtime is alive, the agent works with typed tool contracts end to end and only serializes them when building prompt envelopes or provider-native tool payloads.

## Strict Config Schema

`BaseAgentConfig.from_file(...)` now expects the versioned structured schema only:

- `provider`
- `agent`
- `reply`
- `tool_calling`
- `envelope`
- `context`
- `transport`
- `prompt_cache`
- `agent_tools`
- `response_defaults`

Older ad hoc config shapes such as top-level `protocol`, `system_prompt`, `memory`, or provider shortcuts are intentionally rejected instead of being silently merged.

## Provider Adapters

`BaseAgent` now resolves a provider adapter internally. The first implementation is OpenAI, but the internal shape is now explicit enough to support additional providers cleanly.

Current responsibilities of a provider adapter include:

- building the provider client,
- sending requests,
- extracting assistant text,
- parsing native tool calls,
- building native tool-result continuation items,
- adapting the envelope when native tool calling is active,
- recognizing provider-specific retryable and context-limit errors,
- and handling provider-specific verbosity fallback rules.

That means OpenAI-specific behavior is no longer smeared across `BaseAgent`, `payload`, and `transport` as ad hoc conditionals.

## Prompt Cache

The config includes:

```json
"prompt_cache": {
  "enabled": true,
  "key_prefix": "lotm",
  "retention": "24h",
  "fields": ["model", "instructions", "text", "tools", "envelope"]
}
```

The `fields` list controls which stable payload parts feed into `prompt_cache_key`. By default it does not include `input`, so the key does not change on every user message. If a mission needs cache isolation by prompt, tenant, or similar dimensions, those fields can be added deliberately at the cost of lower cache reuse.

## Software Development Environment Tool

The first tool package is structured as a proper package rather than a single oversized file:

```text
src/lord_of_the_machines/agent_tools/software_development_environment/
```

Main pieces:

- `tool.py`: thin public facade and `install()` entry point for `BaseAgent`.
- `config.py`: tool configuration and named defaults.
- `policy.py`: explicit permission and execution policies.
- `contracts.py`: typed request and result models for every operation.
- `definition.py`: tool contract exposed to the LLM.
- `support.py`: shared helpers, path safety, hashing, journaling, and handler instrumentation.
- `workspace.py`: tree listing, file reads, search, and project context detection.
- `editing.py`: controlled writes, replacements, insertions, moves, and deletes.
- `commands.py`: safe command execution, diagnostics, and git inspection.
- `journal.py`: persisted JSONL activity journal.

The goal is to give an LLM a controlled software workspace interface without mixing project navigation, file mutation, command execution, and journaling into one large module.

The tool now has two formal guardrail layers:

- `SoftwareDevelopmentEnvironmentPermissionPolicy` controls what categories of actions are allowed at all, such as writes, destructive operations, commands, diagnostics, git inspection, and protected-path writes.
- `SoftwareDevelopmentEnvironmentExecutionPolicy` controls runtime limits such as maximum destructive scope and command timeout ceilings.

Operations inside the tool parse their request payloads into typed request models and return typed result models before serializing them back to plain mappings for the agent runtime.

## Todo List Tool

The `todo_list` package provides a lightweight task execution board for agents, backed by files on disk and separated per agent id.

```text
src/lord_of_the_machines/agent_tools/todo_list/
```

Capabilities:

- List agents that have TODO directories and summarize open/completed task counts.
- List TODO lists for one agent with per-list progress.
- Create a TODO list file from scratch (optionally with initial tasks).
- Open a TODO list and read all task states.
- Add one or more tasks to an existing list.
- Mark tasks as completed or unmark them as pending.
- Remove tasks.
- Delete TODO list files.

Storage model:

- One root directory configured by `TodoListToolConfig.root_path`.
- One subdirectory per `agent_id`.
- One JSON file per list (`<list_name>.todo.json` by default).

Naming safety:

- `agent_id` and `list_name` use a strict slug pattern (`letters`, `numbers`, `_`, `-`, max `64` chars) to keep file paths predictable and safe.

## Mission Registry Tool

`mission_registry` is the source of truth for mission state.

Core operations:

- Create missions with title, description, metadata, and initial lifecycle status.
- List and filter missions by status.
- Update global mission status (`new`, `in_progress`, `blocked`, `completed`, `archived`).
- Track per-phase status and notes.
- Assign and unassign role ownership (`product_director`, `product_manager`, etc.).

Storage model:

- One JSON file per mission under a configured root.

## Event Bus Tool

`event_bus` provides persistent, replayable orchestration events.

Core operations:

- Publish events with topic, payload, mission id, and optional correlation/causation ids.
- List events with filters by topic, mission, and sequence.
- Consume events per consumer id from a stored ack offset.
- Ack events by sequence or event id.
- Inspect current consumer state.

Storage model:

- Append-only `events.jsonl` stream.
- Per-consumer state files under `consumers/`.

## Artifact Registry Tool

`artifact_registry` stores and versions deliverables emitted by mission phases.

Core operations:

- Publish artifacts (phase, type, title, content, tags, metadata).
- Query artifacts by mission, phase, type, status, and tags.
- Retrieve artifacts by id.
- Update artifacts with automatic version increment.

Storage model:

- One JSON artifact file per artifact id under `<root>/<mission_id>/`.

## Mission Runtime MVP

The project now includes a first event-driven mission runtime under:

```text
src/lord_of_the_machines/mission/
```

Main components:

- `MissionRuntime`: seeds pending missions into `mission.phase.requested`, consumes events, dispatches role executors, updates mission phase state, and publishes completion/failure/artifact events.
- `AgentAsToolBridge`: wraps a `BaseAgent` and exposes it as a regular tool method (`run_task`) so other agents can call it through normal tool calling.
- `MeetingToolAgent`: wraps a specialized meeting organizer agent as a tool (`run_meeting`) and returns a structured meeting result.
- `MeetingRoleExecutor`: adapter that lets meeting output plug directly into mission-phase execution (`RoleTaskResult`).
- `prompting.py` and `RoleAgentFactory`: stable, in-repo prompt composition for role agents. Prompts are built from:
  - global `Golden Rules` shared by all agents,
  - role charter prompt,
  - role-specific DNA rulesets.

Prompt composition is intentionally sourced from versioned runtime code modules, not from `.temp/`.

This is an MVP foundation for the CoT-like event loop: it standardizes role execution contracts and phase transitions while still allowing flexible role-specific prompting.

## Running Tests

From the project root:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

## Next Work

The autonomous layer still needs to be built:

- A CLI or server that starts from a mission.
- Safe self-repository reading strategies for autonomous runs.
- An initial planner that converts a mission into an executable backlog.
- Orchestration of multiple tools and specialized agents on top of `BaseAgent`.
- Long-term mission decision logging above the low-level operational tool journal.
- Operational sandboxing so the system can modify code without damaging human work.
- Specialized agents such as architect, implementer, verifier, toolmaker, and reviewer.
- API and MCP surfaces for exposing internal capabilities.
- A clear permission model covering what the system may edit, execute, install, or publish.

The long-term intent is for the mission runtime to live in `src/lord_of_the_machines/mission` and use `llm.BaseAgent` as a primitive, not the other way around.
