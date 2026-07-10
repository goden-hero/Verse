"""SQLite-backed assistant conversation history management."""

import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import AssistantHistory


class AssistantHistoryManager:
    """Manages recording and fetching conversational prompts, plans, and execution outcomes."""

    @staticmethod
    def log_conversation(prompt: str, plan: list, result: dict, session: Session) -> None:
        """Saves a conversation conversation event with timestamp and plan JSONs."""
        entry = AssistantHistory(
            timestamp=datetime.utcnow(),
            prompt=prompt,
            plan=json.dumps(plan),
            result=json.dumps(result),
        )
        session.add(entry)
        session.commit()

    @staticmethod
    def get_recent_history(limit: int, session: Session) -> list[dict]:
        """Retrieves a list of recent conversation entries."""
        entries = (
            session.query(AssistantHistory)
            .order_by(AssistantHistory.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": entry.id,
                "timestamp": entry.timestamp.isoformat(),
                "prompt": entry.prompt,
                "plan": json.loads(entry.plan),
                "result": json.loads(entry.result),
            }
            for entry in entries
        ]
