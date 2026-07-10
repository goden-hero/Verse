"""Planner module validating JSON plans into ActionPlan models."""

import logging
from app.assistant.schemas import ActionPlan

logger = logging.getLogger("music_rec.assistant.planner")


class Planner:
    """Validates parsed raw dictionary structures into ActionPlan model instances."""

    @staticmethod
    def create_plan(raw_plan_dict: dict) -> ActionPlan:
        """Constructs and validates the ActionPlan using Pydantic."""
        logger.info("Constructing Pydantic ActionPlan structure...")
        return ActionPlan.model_validate(raw_plan_dict)
