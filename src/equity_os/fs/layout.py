"""CompanyLayout — all path getters for a single company's folder tree.

companies/{TICKER}/
  core/
    dossier.json          # CompanyDossier metadata (episodes: [])
    dossier.md            # generated markdown summary
  episodes/
    {date}_{slug}/
      episode.json        # full ThesisEpisode (assumptions + predictions embedded)
      episode.md          # generated markdown sidecar
  assumptions/
    {date}_{slug}/
      {key}_v001.json     # AssumptionRecord snapshot (one per version)
      {key}_changes.jsonl # append-only AssumptionChange log
  predictions/
    {date}_{slug}/
      {metric}_{id8}.json # PredictionRecord
  resolutions/
    {date}_{slug}/
      {metric}_{id8}_resolution.json
  evidence/
    {date}_{slug}/
  outputs/
    {date}_{slug}/
  policy/
    triggers.json         # company-level MonitoringTrigger list (future)
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from .naming import (
    assumption_changes_filename,
    assumption_filename,
    prediction_filename,
    resolution_filename,
)

_TOP_LEVEL_DIRS = (
    "core",
    "episodes",
    "assumptions",
    "predictions",
    "resolutions",
    "evidence",
    "outputs",
    "policy",
    "scores",
    "postmortems",
)


class CompanyLayout:
    def __init__(self, companies_root: Path, ticker: str) -> None:
        self.root = companies_root / ticker.upper()
        self.ticker = ticker.upper()

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    @property
    def core_dir(self) -> Path:
        return self.root / "core"

    @property
    def dossier_json(self) -> Path:
        return self.core_dir / "dossier.json"

    @property
    def dossier_md(self) -> Path:
        return self.core_dir / "dossier.md"

    # ------------------------------------------------------------------
    # Episodes
    # ------------------------------------------------------------------

    @property
    def episodes_dir(self) -> Path:
        return self.root / "episodes"

    def episode_dir(self, slug: str) -> Path:
        return self.episodes_dir / slug

    def episode_json(self, slug: str) -> Path:
        return self.episode_dir(slug) / "episode.json"

    def episode_md(self, slug: str) -> Path:
        return self.episode_dir(slug) / "episode.md"

    def episode_slugs(self) -> list[str]:
        """Sorted list of existing episode directory names."""
        if not self.episodes_dir.exists():
            return []
        return sorted(d.name for d in self.episodes_dir.iterdir() if d.is_dir())

    # ------------------------------------------------------------------
    # Assumptions
    # ------------------------------------------------------------------

    def assumptions_dir(self, episode_slug: str) -> Path:
        return self.root / "assumptions" / episode_slug

    def assumption_json(self, episode_slug: str, key: str, version: int) -> Path:
        return self.assumptions_dir(episode_slug) / assumption_filename(key, version)

    def assumption_changes(self, episode_slug: str, key: str) -> Path:
        return self.assumptions_dir(episode_slug) / assumption_changes_filename(key)

    # ------------------------------------------------------------------
    # Predictions
    # ------------------------------------------------------------------

    def predictions_dir(self, episode_slug: str) -> Path:
        return self.root / "predictions" / episode_slug

    def prediction_json(
        self, episode_slug: str, metric: str, prediction_id: UUID
    ) -> Path:
        return self.predictions_dir(episode_slug) / prediction_filename(
            metric, prediction_id
        )

    # ------------------------------------------------------------------
    # Resolutions
    # ------------------------------------------------------------------

    def resolutions_dir(self, episode_slug: str) -> Path:
        return self.root / "resolutions" / episode_slug

    def resolution_json(
        self, episode_slug: str, metric: str, prediction_id: UUID
    ) -> Path:
        return self.resolutions_dir(episode_slug) / resolution_filename(
            metric, prediction_id
        )

    # ------------------------------------------------------------------
    # Evidence / outputs / policy (stubs for future use)
    # ------------------------------------------------------------------

    def evidence_dir(self, episode_slug: str) -> Path:
        return self.root / "evidence" / episode_slug

    def outputs_dir(self, episode_slug: str) -> Path:
        return self.root / "outputs" / episode_slug

    @property
    def policy_dir(self) -> Path:
        return self.root / "policy"

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def init_dirs(self) -> None:
        """Create the full folder tree for this company."""
        for top in _TOP_LEVEL_DIRS:
            (self.root / top).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Scores and postmortems
    # ------------------------------------------------------------------

    @property
    def scores_dir(self) -> Path:
        return self.root / "scores"

    def score_json(self, episode_slug: str) -> Path:
        return self.scores_dir / f"{episode_slug}.json"

    def score_md(self, episode_slug: str) -> Path:
        return self.scores_dir / f"{episode_slug}.md"

    @property
    def postmortems_dir(self) -> Path:
        return self.root / "postmortems"

    def postmortem_json(self, episode_slug: str) -> Path:
        return self.postmortems_dir / f"{episode_slug}.json"

    def postmortem_md(self, episode_slug: str) -> Path:
        return self.postmortems_dir / f"{episode_slug}.md"

    def exists(self) -> bool:
        return self.dossier_json.exists()
