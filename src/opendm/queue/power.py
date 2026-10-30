"""After-queue actions (sleep/shutdown). The real implementation, with a cancellable
60 s countdown, belongs to the GUI (M4); the engine only calls this interface."""

from typing import Protocol

from opendm.core.models import AfterAction, Queue


class PowerActions(Protocol):
    async def perform(self, action: AfterAction, queue: Queue) -> None: ...


class NoPowerActions:
    """Default: never touches the computer."""

    async def perform(self, action: AfterAction, queue: Queue) -> None:
        return None
