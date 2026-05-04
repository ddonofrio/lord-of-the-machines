from __future__ import annotations


TOPIC_PHASE_REQUESTED = "mission.phase.requested"
TOPIC_PHASE_COMPLETED = "mission.phase.completed"
TOPIC_PHASE_FAILED = "mission.phase.failed"
TOPIC_ARTIFACT_PUBLISHED = "mission.artifact.published"

STATUS_COMPLETED = "completed"
STATUS_NEEDS_FOLLOW_UP = "needs_follow_up"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"

ALLOWED_ROLE_RESULT_STATUSES = {
    STATUS_COMPLETED,
    STATUS_NEEDS_FOLLOW_UP,
    STATUS_BLOCKED,
    STATUS_FAILED,
}
