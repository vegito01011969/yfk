from __future__ import annotations

import logging
from uuid import uuid4

from viral_pipeline.config import Settings
from viral_pipeline.domain import PIPELINE_ORDER, PipelineContext, RunStatus, StageName
from viral_pipeline.providers import build_providers
from viral_pipeline.stages import PipelineStage, build_stages, write_debug_snapshot
from viral_pipeline.storage import PipelineStore

LOGGER = logging.getLogger(__name__)


class PipelineRunner:
    def __init__(self, settings: Settings, store: PipelineStore | None = None) -> None:
        self.settings = settings
        self.store = store or PipelineStore(settings.pipeline_db_path)
        self.stages = build_stages(settings, *build_providers(settings))
        self.stage_by_name = {stage.name: stage for stage in self.stages}

    def create_context(self) -> PipelineContext:
        run_id = uuid4().hex
        workdir = self.settings.runs_dir / run_id
        workdir.mkdir(parents=True, exist_ok=True)
        self.store.create_run(run_id, workdir, PIPELINE_ORDER)
        context = PipelineContext(run_id=run_id, workdir=workdir)
        self.store.save_context(context)
        return context

    def run(
        self,
        run_id: str | None = None,
        only_stage: StageName | None = None,
        resume: bool = True,
    ) -> PipelineContext:
        context = self.store.load_context(run_id) if run_id else self.create_context()
        completed = self.store.completed_stages(context.run_id) if resume else set()
        self.store.update_run(context.run_id, RunStatus.RUNNING)

        try:
            stages = self._select_stages(only_stage)
            for stage in stages:
                if stage.name in completed and only_stage is None:
                    LOGGER.info("Skipping completed stage %s", stage.name.value)
                    continue
                context = self._run_stage(stage, context)
            self.store.update_run(context.run_id, RunStatus.COMPLETE)
            return context
        except Exception as exc:
            self.store.update_run(context.run_id, RunStatus.FAILED, str(exc))
            raise

    def resume_latest(self) -> PipelineContext:
        run_id = self.store.latest_run_id()
        if run_id is None:
            return self.run()
        return self.run(run_id=run_id, resume=True)

    def _select_stages(self, only_stage: StageName | None) -> list[PipelineStage]:
        if only_stage is None:
            return self.stages
        return [self.stage_by_name[only_stage]]

    def _run_stage(self, stage: PipelineStage, context: PipelineContext) -> PipelineContext:
        LOGGER.info("Running stage %s", stage.name.value)
        self.store.start_stage(context.run_id, stage.name)
        try:
            updated = stage.run(context)
            self.store.save_context(updated)
            write_debug_snapshot(updated)
            self.store.complete_stage(updated.run_id, stage.name)
            return updated
        except Exception as exc:
            self.store.fail_stage(context.run_id, stage.name, str(exc))
            raise
