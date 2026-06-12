from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from crafting_bot import paths
from crafting_bot.domain.screen_classification import (
    KnownScreen,
    ScreenCandidate,
    ScreenClassificationResult,
)
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.services.level_scanner import LevelScanner
from crafting_bot.vision.image_tools import crop_area


@dataclass(frozen=True)
class ScreenCheck:
    screen: KnownScreen
    target_name: str
    threshold: float = 0.18
    source: str = "legacy"


class ScreenClassifier:
    """Classifies the current game screen from calibrated identity markers.

    This service is intentionally observation-only. It does not click, navigate,
    recover, or change bot state.

    Classifier markers are separate from cycle verification targets:
    - classifier_* markers answer: "what screen am I on?"
    - *_check_area targets answer: "did my last click reach the expected step?"

    Bag/anvil are deliberately not separate classified screens. They are controls
    inside the normal game/workshop flow and remain handled by the hire runner's
    direct verification targets.
    """

    CLASSIFIER_CHECKS: tuple[ScreenCheck, ...] = (
        ScreenCheck("REBUILD_WORKSHOP", "classifier_rebuild_workshop_marker", threshold=0.16, source="classifier"),
        ScreenCheck("TAKE_REWARD_SCREEN", "classifier_take_reward_marker", threshold=0.16, source="classifier"),
        ScreenCheck("FREE_SCREEN", "classifier_free_screen_marker", threshold=0.16, source="classifier"),
        ScreenCheck("HEADQUARTERS_SCREEN", "classifier_headquarters_marker", threshold=0.16, source="classifier"),
        ScreenCheck("DYNASTY_SCREEN", "classifier_dynasty_marker", threshold=0.16, source="classifier"),
        ScreenCheck("REINCARNATION_CONFIRM_SCREEN", "classifier_reincarnation_confirm_marker", threshold=0.16, source="classifier"),
        ScreenCheck("MAP_SCREEN", "classifier_map_marker", threshold=0.16, source="classifier"),
    )

    # Legacy/action check areas remain as fallback only. They were calibrated for
    # step verification, not full-screen identity, so they should not be allowed
    # to beat a readable level screen or purpose-built classifier marker.
    LEGACY_CHECKS: tuple[ScreenCheck, ...] = (
        ScreenCheck("REBUILD_WORKSHOP", "rebuild_workshop_check_area", source="legacy"),
        ScreenCheck("TAKE_REWARD_SCREEN", "reward_button_check_area", source="legacy"),
        ScreenCheck("TAKE_REWARD_SCREEN", "early_reward_button_check_area", source="legacy"),
        ScreenCheck("FREE_SCREEN", "free_button_check_area", source="legacy"),
        ScreenCheck("FREE_SCREEN", "early_free_button_check_area", source="legacy"),
        ScreenCheck("FREE_SCREEN", "early_free_button_alt_check_area", source="legacy"),
        ScreenCheck("FREE_SCREEN", "free_button_alt_check_area", source="legacy"),
        ScreenCheck("HEADQUARTERS_SCREEN", "dynasty_button_check_area", source="legacy"),
        ScreenCheck("DYNASTY_SCREEN", "reincarnate_button_check_area", source="legacy"),
        ScreenCheck("REINCARNATION_CONFIRM_SCREEN", "default_button_check_area", source="legacy"),
    )

    SCREEN_CHECKS: tuple[ScreenCheck, ...] = CLASSIFIER_CHECKS + LEGACY_CHECKS

    CLASSIFIER_PRIORITY: tuple[tuple[KnownScreen, tuple[str, ...]], ...] = (
        ("REBUILD_WORKSHOP", ("classifier_rebuild_workshop_marker",)),
        ("REINCARNATION_CONFIRM_SCREEN", ("classifier_reincarnation_confirm_marker",)),
        ("DYNASTY_SCREEN", ("classifier_dynasty_marker",)),
        ("HEADQUARTERS_SCREEN", ("classifier_headquarters_marker",)),
        ("TAKE_REWARD_SCREEN", ("classifier_take_reward_marker",)),
        ("FREE_SCREEN", ("classifier_free_screen_marker",)),
        ("MAP_SCREEN", ("classifier_map_marker",)),
    )

    LEGACY_PRIORITY: tuple[tuple[KnownScreen, tuple[str, ...]], ...] = (
        ("REBUILD_WORKSHOP", ("rebuild_workshop_check_area",)),
        ("REINCARNATION_CONFIRM_SCREEN", ("default_button_check_area",)),
        ("DYNASTY_SCREEN", ("reincarnate_button_check_area",)),
        ("HEADQUARTERS_SCREEN", ("dynasty_button_check_area",)),
        ("TAKE_REWARD_SCREEN", ("reward_button_check_area", "early_reward_button_check_area")),
        ("FREE_SCREEN", ("free_button_check_area", "early_free_button_check_area", "early_free_button_alt_check_area", "free_button_alt_check_area")),
    )

    def __init__(
        self,
        calibration: CalibrationStore,
        scanner: LevelScanner,
        screenshot_path: Path = paths.LATEST_SCREENSHOT_PATH,
    ) -> None:
        self.calibration = calibration
        self.scanner = scanner
        self.screenshot_path = screenshot_path

    def classify(self) -> ScreenClassificationResult:
        try:
            screenshot = self.scanner.screen_capture.capture()
            self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot.save(self.screenshot_path)
        except Exception as exc:
            return ScreenClassificationResult(
                ok=False,
                screen="UNKNOWN",
                confidence="unknown",
                message=f"Screen classification failed before capture: {exc}",
            )

        candidates = tuple(self._check_area_candidate(screenshot, check) for check in self.SCREEN_CHECKS)
        passed_candidates = [candidate for candidate in candidates if candidate.passed and candidate.score is not None]

        classifier_candidates = [
            candidate
            for candidate in passed_candidates
            if candidate.target_name.startswith("classifier_")
        ]
        legacy_candidates = [
            candidate
            for candidate in passed_candidates
            if not candidate.target_name.startswith("classifier_")
        ]

        # Dedicated classifier markers are purpose-built for screen identity.
        #
        # MAP_SCREEN is a special fallback. Its marker can remain visible behind
        # Rebuild Workshop, Take Reward, and Free modal screens. Therefore it is
        # intentionally excluded from the first classifier pass and only checked
        # after non-map classifier markers, level_area, and legacy modal markers
        # have failed.
        non_map_classifier_candidates = [
            candidate for candidate in classifier_candidates if candidate.screen != "MAP_SCREEN"
        ]
        map_classifier_candidates = [
            candidate for candidate in classifier_candidates if candidate.screen == "MAP_SCREEN"
        ]

        classifier_match = self._classifier_identity_candidate(non_map_classifier_candidates)
        if classifier_match is not None:
            best = classifier_match
            return ScreenClassificationResult(
                ok=True,
                screen=best.screen,
                confidence=self._confidence_for_score(best.score, best.threshold),
                matched_target=best.target_name,
                score=best.score,
                threshold=best.threshold,
                screenshot_path=self.screenshot_path,
                candidates=candidates,
                message=(
                    f"Classified as {best.screen} using classifier marker {best.target_name}: "
                    f"score={best.score:.4f}, threshold={best.threshold:.4f}."
                ),
            )

        # If no classifier marker is available/passing, a readable level badge is
        # the safest sign that this is the playable level screen. Legacy action
        # check areas are not allowed to override this because they can be broad
        # or visually similar across panels.
        level_scan = self.scanner.scan()
        if level_scan.ok and level_scan.level is not None:
            confidence = "high" if (level_scan.digit_score is not None and level_scan.digit_score >= 0.75) else "medium"
            ignored_overlay = ""
            if legacy_candidates:
                best_overlay = min(
                    legacy_candidates,
                    key=lambda candidate: candidate.score if candidate.score is not None else 999.0,
                )
                ignored_overlay = (
                    f" Ignored legacy candidate {best_overlay.screen} "
                    f"({best_overlay.target_name}, score={best_overlay.score:.4f}) because level_area was readable."
                )
            return ScreenClassificationResult(
                ok=True,
                screen="LEVEL_SCREEN",
                confidence=confidence,
                matched_target="level_area",
                score=level_scan.ready_score,
                threshold=None,
                level=level_scan.level,
                level_text=level_scan.level_text,
                ready=level_scan.ready,
                ready_score=level_scan.ready_score,
                digit_score=level_scan.digit_score,
                screenshot_path=self.screenshot_path,
                candidates=candidates,
                message=(
                    f"Classified as LEVEL_SCREEN by level scan: "
                    f"level={level_scan.level_text}, ready={level_scan.ready}." + ignored_overlay
                ),
            )

        # Fallback for existing installations before classifier markers are
        # calibrated. Use semantic priority rather than lowest score wins.
        legacy_match = self._prioritized_candidate(legacy_candidates, self.LEGACY_PRIORITY)
        if legacy_match is not None:
            best = legacy_match
            return ScreenClassificationResult(
                ok=True,
                screen=best.screen,
                confidence=self._confidence_for_score(best.score, best.threshold),
                matched_target=best.target_name,
                score=best.score,
                threshold=best.threshold,
                screenshot_path=self.screenshot_path,
                candidates=candidates,
                message=(
                    f"Classified as {best.screen} using legacy fallback marker {best.target_name}: "
                    f"score={best.score:.4f}, threshold={best.threshold:.4f}. Level scan and classifier markers were not usable."
                ),
            )

        map_match = self._classifier_identity_candidate(map_classifier_candidates)
        if map_match is not None:
            best = map_match
            return ScreenClassificationResult(
                ok=True,
                screen="MAP_SCREEN",
                confidence=self._confidence_for_score(best.score, best.threshold),
                matched_target=best.target_name,
                score=best.score,
                threshold=best.threshold,
                screenshot_path=self.screenshot_path,
                candidates=candidates,
                message=(
                    f"Classified as MAP_SCREEN using fallback map marker {best.target_name}: "
                    f"score={best.score:.4f}, threshold={best.threshold:.4f}. "
                    "No level screen, modal classifier marker, or legacy modal marker matched first."
                ),
            )

        best_failed = min(
            (candidate for candidate in candidates if candidate.score is not None),
            key=lambda candidate: candidate.score if candidate.score is not None else 999.0,
            default=None,
        )
        extra = ""
        if best_failed:
            extra = (
                f" Best failed marker was {best_failed.target_name} for {best_failed.screen}: "
                f"score={best_failed.score:.4f}, threshold={best_failed.threshold:.4f}."
            )

        return ScreenClassificationResult(
            ok=True,
            screen="UNKNOWN",
            confidence="unknown",
            matched_target=best_failed.target_name if best_failed else None,
            score=best_failed.score if best_failed else None,
            threshold=best_failed.threshold if best_failed else None,
            screenshot_path=self.screenshot_path,
            candidates=candidates,
            message="Could not classify the current screen." + extra,
        )

    def _check_area_candidate(self, screenshot: Image.Image, check: ScreenCheck) -> ScreenCandidate:
        if not self.calibration.has_area(check.target_name):
            return ScreenCandidate(
                screen=check.screen,
                target_name=check.target_name,
                attempted=False,
                passed=False,
                threshold=check.threshold,
                message=f"Missing calibrated {check.source} area.",
            )

        reference_path = paths.CALIBRATION_CROP_DIR / f"{check.target_name}.png"
        if not reference_path.exists():
            return ScreenCandidate(
                screen=check.screen,
                target_name=check.target_name,
                attempted=False,
                passed=False,
                threshold=check.threshold,
                message=f"Missing reference crop: {reference_path}",
            )

        try:
            area = self.calibration.get_area(check.target_name)
            live_crop = crop_area(screenshot, area).convert("RGB")
            reference = Image.open(reference_path).convert("RGB")
            if live_crop.size != reference.size:
                return ScreenCandidate(
                    screen=check.screen,
                    target_name=check.target_name,
                    attempted=True,
                    passed=False,
                    threshold=check.threshold,
                    message=f"Crop size mismatch: live={live_crop.size}, reference={reference.size}.",
                )

            score = self._image_diff(live_crop, reference)
            passed = score <= check.threshold
            return ScreenCandidate(
                screen=check.screen,
                target_name=check.target_name,
                attempted=True,
                passed=passed,
                score=score,
                threshold=check.threshold,
                message=(
                    f"{'PASS' if passed else 'fail'}: score={score:.4f}, "
                    f"threshold={check.threshold:.4f}."
                ),
            )
        except Exception as exc:
            return ScreenCandidate(
                screen=check.screen,
                target_name=check.target_name,
                attempted=True,
                passed=False,
                threshold=check.threshold,
                message=f"Check failed: {exc}",
            )

    @staticmethod
    def _image_diff(a: Image.Image, b: Image.Image) -> float:
        arr_a = np.asarray(a, dtype=np.int16)
        arr_b = np.asarray(b, dtype=np.int16)
        return float(np.mean(np.abs(arr_a - arr_b)) / 255.0)

    def _classifier_identity_candidate(self, passed_candidates: list[ScreenCandidate]) -> ScreenCandidate | None:
        """Choose a dedicated classifier marker.

        Rules:
        1. If any classifier marker is an exact/near-exact match, choose the
           lowest score. This prevents weaker overlay markers from winning only
           because of semantic priority.
        2. Otherwise fall back to semantic priority, which prevents small/broad
           markers from beating parent screen markers when all matches are only
           medium confidence.
        """
        if not passed_candidates:
            return None

        exact_or_near_exact = [
            candidate
            for candidate in passed_candidates
            if candidate.score is not None and candidate.score <= 0.05
        ]
        if exact_or_near_exact:
            return min(
                exact_or_near_exact,
                key=lambda candidate: candidate.score if candidate.score is not None else 999.0,
            )

        return self._prioritized_candidate(passed_candidates, self.CLASSIFIER_PRIORITY)

    def _prioritized_candidate(
        self,
        passed_candidates: list[ScreenCandidate],
        priority: tuple[tuple[KnownScreen, tuple[str, ...]], ...],
    ) -> ScreenCandidate | None:
        by_target = {candidate.target_name: candidate for candidate in passed_candidates}

        for screen, target_names in priority:
            screen_candidates = [
                by_target[target_name]
                for target_name in target_names
                if target_name in by_target and by_target[target_name].screen == screen
            ]
            if screen_candidates:
                return min(
                    screen_candidates,
                    key=lambda candidate: candidate.score if candidate.score is not None else 999.0,
                )

        return min(
            passed_candidates,
            key=lambda candidate: candidate.score if candidate.score is not None else 999.0,
            default=None,
        )

    @staticmethod
    def _confidence_for_score(score: float | None, threshold: float | None) -> str:
        if score is None:
            return "unknown"
        if score <= 0.08:
            return "high"
        if threshold is not None and score <= threshold:
            return "medium"
        return "low"
