from __future__ import annotations

from typing import Any

from lord_of_the_machines.llm.tool_definitions import ToolDefinition, ToolMethodDefinition


PAGINATION_TOOL_NAME = "pagination"
PAGINATION_REF_PREFIX = "pagination://"
DEFAULT_PAGINATION_TARGET = "default"
PAGINATION_STATUSES = {"continue", "stop"}


def pagination_tool_definition() -> ToolDefinition:
    return ToolDefinition(
        name=PAGINATION_TOOL_NAME,
        description=(
            "Emit long answers or long structured fields in pages. Use append_page with "
            "status='continue' while more content remains, then status='stop' for the final "
            "page. The full assembled content can be referenced in any later string field as "
            "pagination://<target>, for example pagination://artifact_content."
        ),
        internal=True,
        methods=[
            ToolMethodDefinition(
                name="append_page",
                description=(
                    "Append one page of content to a named pagination target. Use status='continue' "
                    "to request another model turn, and status='stop' when the target is complete."
                ),
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": (
                                "Stable target name for this paginated content. Use simple names "
                                "such as default, reply, artifact_content, or meeting_summary."
                            ),
                        },
                        "content": {
                            "type": "string",
                            "description": "The next page of content to append.",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["continue", "stop"],
                            "description": (
                                "Use continue when more pages are needed; use stop on the final page."
                            ),
                        },
                    },
                    "required": ["content", "status"],
                },
            ),
            ToolMethodDefinition(
                name="read_pages",
                description="Inspect accumulated pagination targets for the current query.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "target": {"type": "string"},
                        "include_content": {"type": "boolean"},
                    },
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="reset",
                description="Clear one pagination target, or all targets when target is omitted.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"target": {"type": "string"}},
                    "required": [],
                },
            ),
        ],
    )


def pagination_ref(target: str) -> str:
    return f"{PAGINATION_REF_PREFIX}{target}"


def normalize_pagination_target(raw_target: Any) -> str:
    target = str(raw_target or DEFAULT_PAGINATION_TARGET).strip()
    if not target:
        target = DEFAULT_PAGINATION_TARGET
    if any(character.isspace() for character in target):
        raise ValueError("pagination target must not contain whitespace.")
    if "/" in target or "\\" in target:
        raise ValueError("pagination target must not contain path separators.")
    return target


def assembled_page_content(pages_by_target: dict[str, list[str]], target: str) -> str:
    return "".join(pages_by_target.get(target, []))


def resolve_pagination_references(value: Any, pages_by_target: dict[str, list[str]]) -> Any:
    if isinstance(value, str):
        return _resolve_string_reference(value, pages_by_target)
    if isinstance(value, dict):
        return {
            key: resolve_pagination_references(item, pages_by_target)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [resolve_pagination_references(item, pages_by_target) for item in value]
    if isinstance(value, tuple):
        return tuple(resolve_pagination_references(item, pages_by_target) for item in value)
    return value


def _resolve_string_reference(value: str, pages_by_target: dict[str, list[str]]) -> str:
    resolved = value
    for target in sorted(pages_by_target, key=len, reverse=True):
        ref = pagination_ref(target)
        if ref in resolved:
            resolved = resolved.replace(ref, assembled_page_content(pages_by_target, target))
    return resolved
