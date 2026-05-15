# System Command Tooling – Lord of the Machines

## What is this capability?

The `run_system_command` method allows permitted agents to execute arbitrary OS-level (host) commands outside the workspace root. This feature is **powerful but risky**: it is disabled by default and must be explicitly enabled by policy for each environment/role.

- **Danger:** This method is NOT restricted to the workspace. It enables any executable visible to the underlying OS. Use only where platform risk, audit requirements, and compliance rules allow.

- **Use cases:** Deep diagnostics, platform automation, privileged scripting unavailable in workspace context, admin maintenance under policy control.

## How to Enable

1. In your tool or environment, find the `SoftwareDevelopmentEnvironmentPermissionPolicy` configuration.
2. Set `allow_system_command_execution: True` for explicitly trusted agents/roles. (Leave as `False` for almost all general/production contexts.)
3. The method will only appear in the API/tool when this flag is True. By default, attempting to invoke it will raise a `SoftwareDevelopmentEnvironmentPolicyError` and log the denial.

## Method usage (API)

```python
{
  "argv": ["ls", "-al"],              # List of command tokens, required
  "timeout_seconds": 60,               # Optional timeout (default: 60)
  "expected_exit_codes": [0]           # Which exit codes are allowed to be considered success
}
```
- Returns: `{ "argv": ..., "exit_code": ..., "ok": bool, "stdout": ..., "stderr": ... }`
- All input/output is strictly text. Large or binary output is clipped.
- Shell is never invoked: command and arguments must be explicit (no string parsing).

## Safety, Logging, and Compliance

- All system command attempts are AUDITED, including denied requests. Log entries record agent, role, arguments, result, and timestamp.
- **Never enable this policy unless you have secured access controls, audit delivery, and role-level controls.**
- No privilege elevation: commands are run as the process user.
- Secrets or sensitive output may be redacted. Do not intentionally pass plaintext secrets in `argv`.
- See code/config for more platform-specific risk controls and audit sinks.

## Who should use it?

- Primary roles: `software_developer`, `software_development_manager`, `software_architect` – but ONLY where explicitly safe/prioritized.
- Never directly expose this to `product_manager`, `product_director`, or users/operators without defense-in-depth.

## Further Reading
- See the codebase in `src/lord_of_the_machines/agent_tools/software_development_environment/commands.py`, `policy.py`, `tool.py`, and `definition.py` for details and evolving security posture.
- Ask your operations/platform team for audit/approval before configuring OS command access.

## Example

```python
# Correct
{"argv": ["echo", "hello from system"], "timeout_seconds": 3}

# Will be denied without explicit policy:
{"argv": ["uname", "-a"]}
```

---

**This document is part of Lord of the Machines system-command capability rollout.**
If unsure, leave the feature disabled. When in doubt, prefer workspace-scoped `run_command`.