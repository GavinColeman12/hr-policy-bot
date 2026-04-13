"""Base agent class for the multi-agent event crawling system."""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentRole(str, Enum):
    RESEARCHER = "researcher"
    CRAWLER = "crawler"
    CLASSIFIER = "classifier"
    QUALITY = "quality"
    RANKER = "ranker"


@dataclass
class AgentMessage:
    """Message passed between agents."""
    sender: AgentRole
    recipient: AgentRole
    payload: Any
    timestamp: float = field(default_factory=time.time)
    message_type: str = "data"


@dataclass
class AgentResult:
    """Result from an agent's execution."""
    agent: AgentRole
    success: bool
    data: Any = None
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    metadata: dict = field(default_factory=dict)


class BaseAgent(ABC):
    """Base class for all agents in the pipeline."""

    role: AgentRole
    name: str

    def __init__(self):
        self.logger = logging.getLogger(f"agent.{self.role.value}")
        self._message_queue: asyncio.Queue[AgentMessage] = asyncio.Queue()

    @abstractmethod
    async def execute(self, context: dict) -> AgentResult:
        """Execute the agent's primary task."""
        ...

    async def send_message(self, recipient: AgentRole, payload: Any, message_type: str = "data") -> AgentMessage:
        msg = AgentMessage(
            sender=self.role,
            recipient=recipient,
            payload=payload,
            message_type=message_type,
        )
        self.logger.debug(f"Sending {message_type} to {recipient.value}")
        return msg

    async def receive_message(self) -> AgentMessage:
        return await self._message_queue.get()

    async def safe_execute(self, context: dict) -> AgentResult:
        """Execute with error handling and timing."""
        start = time.time()
        try:
            self.logger.info(f"[{self.name}] Starting execution...")
            result = await self.execute(context)
            result.duration_seconds = time.time() - start
            self.logger.info(f"[{self.name}] Completed in {result.duration_seconds:.2f}s")
            return result
        except Exception as e:
            duration = time.time() - start
            self.logger.error(f"[{self.name}] Failed after {duration:.2f}s: {e}")
            return AgentResult(
                agent=self.role,
                success=False,
                errors=[str(e)],
                duration_seconds=duration,
            )
