"""Job state machine (spec §7.1).

Transitions and validation. Terminal states are succeeded, failed, cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.errors import JobStateError
from ...domain.schemas import JobState

# Allowed transitions
_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.queued: {JobState.leased, JobState.cancelled, JobState.failed},
    JobState.leased: {JobState.running, JobState.queued, JobState.cancelled, JobState.failed},
    JobState.running: {
        JobState.pausing,
        JobState.retry_wait,
        JobState.succeeded,
        JobState.failed,
        JobState.cancelling,
    },
    JobState.pausing: {JobState.paused, JobState.failed, JobState.cancelling},
    JobState.paused: {JobState.queued, JobState.failed, JobState.cancelled},
    JobState.retry_wait: {JobState.queued, JobState.failed, JobState.cancelled},
    JobState.cancelling: {JobState.cancelled, JobState.failed},
    # terminal
    JobState.succeeded: set(),
    JobState.failed: {JobState.queued},  # explicit retry
    JobState.cancelled: set(),
}

_TERMINAL = {JobState.succeeded, JobState.failed, JobState.cancelled}


def is_terminal(state: JobState) -> bool:
    return state in _TERMINAL


@dataclass
class StateMachine:
    current: JobState

    def can_transition(self, to: JobState) -> bool:
        return to in _TRANSITIONS[self.current]

    def transition(self, to: JobState) -> JobState:
        if not self.can_transition(to):
            raise JobStateError(f"invalid job transition {self.current.value} -> {to.value}")
        self.current = to
        return self.current

    @staticmethod
    def valid_from(state: JobState) -> set[JobState]:
        return _TRANSITIONS[state]

    @staticmethod
    def terminal() -> frozenset[JobState]:
        return frozenset(_TERMINAL)
