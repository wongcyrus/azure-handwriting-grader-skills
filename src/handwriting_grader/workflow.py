"""Microsoft Agent Framework execution around the persistent grading pipeline."""

import asyncio
import json
from pathlib import Path
from typing import Never

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

from .grading import approved_inputs, grade_exam


def build_grading_workflow(config, config_dir, config_path, model_config_path,
                           endpoint, api_version, summary, *, mode="batch",
                           batch_concurrency=3, grade_function=grade_exam,
                           continue_on_image_policy_block=False):
    class ValidateApproval(Executor):
        @handler
        async def process(self, request: str, ctx: WorkflowContext[str]) -> None:
            approved_inputs(config, config_dir, config_path)
            await ctx.send_message(request)

    class ExecuteGrading(Executor):
        @handler
        async def process(self, request: str, ctx: WorkflowContext[str]) -> None:
            output = await asyncio.to_thread(
                grade_function, config, config_dir, config_path, model_config_path,
                endpoint, api_version, summary,
                mode=mode, batch_concurrency=batch_concurrency,
                continue_on_image_policy_block=continue_on_image_policy_block,
            )
            await ctx.send_message(str(output))

    class RequireHumanReview(Executor):
        @handler
        async def process(self, output: str, ctx: WorkflowContext[Never, str]) -> None:
            # The workflow never grants approval or sends reports.
            await ctx.yield_output(output)

    validate = ValidateApproval(id="validate-human-approvals")
    execute = ExecuteGrading(id="grade-approved-crops")
    review = RequireHumanReview(id="await-human-score-review")
    return (WorkflowBuilder(start_executor=validate, name="human-reviewed-azure-grading",
                            max_iterations=4)
            .add_edge(validate, execute).add_edge(execute, review).build())


def run_grading_workflow(*args, **kwargs):
    async def run():
        workflow = build_grading_workflow(*args, **kwargs)
        events = await workflow.run("grade")
        outputs = events.get_outputs()
        if len(outputs) != 1:
            raise ValueError("Grading workflow did not produce exactly one output")
        return Path(outputs[0])

    return asyncio.run(run())


def run_batch_recovery_workflow(config, config_dir, config_path, question, revision, max_requests):
    from .batch_recovery import inspect_batch_recovery, recover_question_batches

    class ValidateRecovery(Executor):
        @handler
        async def process(self, request: str, ctx: WorkflowContext[str]) -> None:
            info = inspect_batch_recovery(config, config_dir, config_path, question)
            if info["revision"] != revision:
                raise ValueError("Grading or review changed after preview")
            await ctx.send_message(request)

    class ExecuteRecovery(Executor):
        @handler
        async def process(self, request: str, ctx: WorkflowContext[str]) -> None:
            result = await asyncio.to_thread(
                recover_question_batches, config, config_dir, config_path, question, revision, max_requests,
            )
            result["history"] = str(result["history"])
            await ctx.send_message(json.dumps(result))

    class RequireHumanReview(Executor):
        @handler
        async def process(self, output: str, ctx: WorkflowContext[Never, str]) -> None:
            await ctx.yield_output(output)

    async def run():
        validate = ValidateRecovery(id="validate-recovery")
        execute = ExecuteRecovery(id="recover-filtered-batches")
        review = RequireHumanReview(id="await-human-score-review")
        workflow = (WorkflowBuilder(start_executor=validate, name="human-reviewed-batch-recovery",
                                    max_iterations=4)
                    .add_edge(validate, execute).add_edge(execute, review).build())
        events = await workflow.run("recover")
        outputs = events.get_outputs()
        if len(outputs) != 1:
            raise ValueError("Batch recovery workflow did not produce exactly one output")
        return json.loads(outputs[0])

    return asyncio.run(run())


def run_marker_workflow(config, config_dir, model_config_path, endpoint, api_version,
                        language="eng"):
    from .scan_markers import discover_markers, inspect_marker_discovery

    class ValidateMarkerInputs(Executor):
        @handler
        async def process(self, request: str, ctx: WorkflowContext[str]) -> None:
            inspect_marker_discovery(config, config_dir, model_config_path, language)
            await ctx.send_message(request)

    class DiscoverPrintedMarkers(Executor):
        @handler
        async def process(self, request: str, ctx: WorkflowContext[str]) -> None:
            output = await asyncio.to_thread(
                discover_markers, config, config_dir, model_config_path, endpoint,
                api_version, language,
            )
            await ctx.send_message(str(output))

    class RequireMarkerReview(Executor):
        @handler
        async def process(self, output: str, ctx: WorkflowContext[Never, str]) -> None:
            await ctx.yield_output(output)

    async def run():
        validate = ValidateMarkerInputs(id="validate-marker-inputs")
        discover = DiscoverPrintedMarkers(id="discover-printed-markers")
        review = RequireMarkerReview(id="await-human-marker-review")
        workflow = (
            WorkflowBuilder(start_executor=validate, name="human-reviewed-scan-markers",
                            max_iterations=4)
            .add_edge(validate, discover).add_edge(discover, review).build()
        )
        events = await workflow.run("suggest-markers")
        outputs = events.get_outputs()
        if len(outputs) != 1:
            raise ValueError("Marker workflow did not produce exactly one output")
        return Path(outputs[0])

    return asyncio.run(run())
