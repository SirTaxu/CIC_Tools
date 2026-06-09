from __future__ import annotations

from dataclasses import dataclass

from crafting_bot.domain.recovery import RecoveryContextName, RecoveryDecision, RecoveryRequest
from crafting_bot.domain.screen_classification import ScreenClassificationResult
from crafting_bot.services.recovery_policy import RecoveryPolicy
from crafting_bot.services.screen_classifier import ScreenClassifier


@dataclass(frozen=True)
class RecoveryDryRunResult:
    ok: bool
    classification: ScreenClassificationResult
    decision: RecoveryDecision
    message: str


class RecoveryDryRunService:
    """Classifies the current screen and reports the recovery decision.

    This service is observation-only. It does not press ESC, click buttons, or
    modify bot state.
    """

    def __init__(
        self,
        classifier: ScreenClassifier,
        policy: RecoveryPolicy | None = None,
    ) -> None:
        self.classifier = classifier
        self.policy = policy or RecoveryPolicy()

    def run(self, context: RecoveryContextName = "general") -> RecoveryDryRunResult:
        classification = self.classifier.classify()
        request = RecoveryRequest(screen=classification.screen, context=context)
        decision = self.policy.decide(request)

        return RecoveryDryRunResult(
            ok=classification.ok,
            classification=classification,
            decision=decision,
            message=(
                f"Recovery dry-run: screen={classification.screen}, context={context}, "
                f"suggested_action={decision.action}, risk={decision.risk}."
            ),
        )
