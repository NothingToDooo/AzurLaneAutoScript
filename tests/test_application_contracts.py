from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, override

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    Blocked,
    Cancelled,
    Deferred,
    DelayTask,
    DeleteTaskState,
    DisableTask,
    ExecutionMode,
    Faulted,
    OperatorNotificationKind,
    OperatorNotificationRequest,
    RequestAppRestart,
    RescheduleSelf,
    RescheduleTask,
    Retryable,
    RunMetadata,
    RunOutcome,
    ScheduleEffect,
    StateEffect,
    Succeeded,
    Task,
    TaskContext,
    TaskId,
    TaskResult,
    UpsertTaskState,
    WakePolicy,
    WakeTask,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def _metadata(
    *,
    settings_revision: int = 1,
    content_revision: str = "content-v1",
) -> RunMetadata:
    return RunMetadata(
        settings_revision=settings_revision,
        content_revision=content_revision,
    )


@pytest.mark.parametrize("value", ["", " ", "task id", " task", "task\t"])
def test_task_id_rejects_empty_or_whitespace(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty or contain whitespace"):
        TaskId(value)


def test_task_id_is_an_opaque_hashable_value() -> None:
    task_id = TaskId("opsi_explore")

    assert str(task_id) == "opsi_explore"
    assert {task_id, TaskId("opsi_explore")} == {task_id}


def test_execution_modes_are_closed_and_explicit() -> None:
    assert {mode.value for mode in ExecutionMode} == {
        "scheduled_job",
        "assist_session",
        "direct_command",
    }


def test_run_metadata_is_a_hashable_value() -> None:
    metadata = _metadata(settings_revision=4, content_revision="event-20260713")
    equal_metadata = _metadata(
        settings_revision=4,
        content_revision="event-20260713",
    )

    assert {metadata, equal_metadata} == {metadata}


def test_run_metadata_requires_a_positive_integer_settings_revision() -> None:
    invalid_revision = True
    with pytest.raises(TypeError, match="settings_revision must be an integer"):
        _metadata(settings_revision=invalid_revision)
    with pytest.raises(ValueError, match="settings_revision must be positive"):
        _metadata(settings_revision=0)


@pytest.mark.parametrize("revision", ["", " ", " revision", "revision "])
def test_run_metadata_rejects_empty_or_untrimmed_revision_strings(revision: str) -> None:
    with pytest.raises(ValueError, match="content_revision must not be empty or contain surrounding whitespace"):
        _metadata(content_revision=revision)


def test_run_metadata_requires_revision_strings() -> None:
    with pytest.raises(TypeError, match="content_revision must be a string"):
        _metadata(content_revision=cast("str", 1))


def test_abort_is_a_one_shot_signal() -> None:
    abort = AbortToken()
    assert not abort.is_requested
    abort.raise_if_requested()

    assert abort.request("manual stop")
    assert not abort.request("later stop reason")
    assert abort.reason == "manual stop"

    with pytest.raises(AbortRequested, match="manual stop") as raised:
        abort.raise_if_requested()
    assert raised.value.reason == "manual stop"


class _ExternalSignal:
    def __init__(self) -> None:
        self.requested = False

    def is_set(self) -> bool:
        return self.requested


def test_abort_can_link_to_an_external_process_signal() -> None:
    external = _ExternalSignal()
    abort = AbortToken(external_signal=external, external_reason="parent process stopped")

    assert not abort.is_requested
    external.requested = True

    assert abort.is_requested
    assert abort.reason == "parent process stopped"
    assert not abort.request("a later local reason")


def test_linked_abort_checks_the_external_signal_before_io() -> None:
    external = _ExternalSignal()
    abort = AbortToken(external_signal=external, external_reason="manual stop")
    external.requested = True

    with pytest.raises(AbortRequested, match="manual stop"):
        abort.raise_if_requested()


@pytest.mark.parametrize("outcome_type", [Deferred, Retryable, Blocked, Cancelled])
def test_non_success_outcomes_require_a_reason(
    outcome_type: type[Deferred | Retryable | Blocked | Cancelled],
) -> None:
    with pytest.raises(ValueError, match="reason must not be blank"):
        outcome_type(" ")


def test_faulted_keeps_the_original_exception() -> None:
    error = RuntimeError("broken task")

    assert Faulted(error).error is error
    with pytest.raises(TypeError, match="error must be an Exception"):
        Faulted(cast("Exception", "broken task"))


def test_schedule_effects_use_aware_time_and_explicit_wake_policy() -> None:
    due_at = datetime(2026, 7, 14, 4, tzinfo=UTC)
    task_id = TaskId("commission")

    assert RescheduleSelf(due_at).due_at == due_at
    assert RescheduleTask(task_id, due_at).task_id == task_id
    assert DelayTask(task_id, due_at).task_id == task_id
    assert WakeTask(task_id, due_at, WakePolicy.FORCE_ENABLE).enable_policy is WakePolicy.FORCE_ENABLE
    assert WakeTask(task_id, due_at, WakePolicy.RESPECT_DISABLED).enable_policy is WakePolicy.RESPECT_DISABLED
    assert DisableTask(task_id).task_id == task_id
    assert RequestAppRestart("game process stopped").reason == "game process stopped"

    with pytest.raises(ValueError, match="due_at must be timezone-aware"):
        RescheduleSelf(datetime(2026, 7, 14, 4))


def test_wake_task_requires_typed_id_and_policy() -> None:
    due_at = datetime(2026, 7, 14, 4, tzinfo=UTC)

    with pytest.raises(TypeError, match="task_id must be a TaskId"):
        WakeTask(cast("TaskId", "commission"), due_at, WakePolicy.FORCE_ENABLE)
    with pytest.raises(TypeError, match="enable_policy must be a WakePolicy"):
        WakeTask(TaskId("commission"), due_at, cast("WakePolicy", "force_enable"))


def test_task_result_is_an_immutable_typed_envelope() -> None:
    due_at = datetime(2026, 7, 14, 4, tzinfo=UTC)
    effects = (
        RescheduleSelf(due_at),
        WakeTask(TaskId("reward"), due_at, WakePolicy.RESPECT_DISABLED),
    )

    result = TaskResult(outcome=Succeeded(), effects=effects)

    assert result.effects == effects
    with pytest.raises(TypeError, match="effects must be a tuple"):
        TaskResult(outcome=Succeeded(), effects=cast("tuple[ScheduleEffect, ...]", []))


def test_task_state_effect_validates_and_deeply_freezes_strict_json() -> None:
    steps: list[object] = [1, {"stage": "d3"}]
    effect = UpsertTaskState(
        namespace="encounter.progress",
        key="raid",
        schema_version=2,
        payload={"steps": steps, "complete": False},
    )

    steps.append(3)
    payload = cast("Mapping[str, object]", effect.payload)
    assert payload["steps"] == (1, {"stage": "d3"})
    assert payload["complete"] is False
    with pytest.raises(TypeError):
        cast("dict[str, object]", effect.payload)["mutated"] = True


@pytest.mark.parametrize(
    ("namespace", "key", "field_name"),
    [(value, "reset", "namespace") for value in ("", " ", "event reset", "event\treset")]
    + [("event.lifecycle", value, "key") for value in ("", " ", "event reset", "event\treset")],
)
def test_task_state_effect_rejects_invalid_identifiers(namespace: str, key: str, field_name: str) -> None:
    with pytest.raises(ValueError, match=f"{field_name} must not be empty or contain whitespace"):
        UpsertTaskState(namespace, key, 1, None)

    with pytest.raises(ValueError, match=f"{field_name} must not be empty or contain whitespace"):
        DeleteTaskState(namespace, key)


def test_task_state_effect_requires_a_positive_integer_schema_version() -> None:
    invalid_schema_version = True
    with pytest.raises(TypeError, match="schema_version must be an integer"):
        UpsertTaskState(
            namespace="encounter",
            key="raid",
            schema_version=invalid_schema_version,
            payload=None,
        )
    with pytest.raises(ValueError, match="schema_version must be positive"):
        UpsertTaskState("encounter", "raid", 0, None)


@pytest.mark.parametrize("payload", [(1, 2), {1: "value"}, object()])
def test_task_state_effect_rejects_non_json_payloads(payload: object) -> None:
    with pytest.raises(TypeError, match="JSON"):
        UpsertTaskState("encounter", "raid", 1, payload)


@pytest.mark.parametrize("payload", [float("nan"), float("inf"), float("-inf")])
def test_task_state_effect_rejects_non_finite_json_numbers(payload: float) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        UpsertTaskState("encounter", "raid", 1, payload)


def test_task_state_effect_rejects_cyclic_json() -> None:
    payload: list[object] = []
    payload.append(payload)

    with pytest.raises(ValueError, match="must not contain cycles"):
        UpsertTaskState("encounter", "raid", 1, payload)


def test_task_result_rejects_values_outside_the_closed_unions() -> None:
    with pytest.raises(TypeError, match="outcome must be a RunOutcome"):
        TaskResult(outcome=cast("RunOutcome", object()))
    with pytest.raises(TypeError, match="effects must contain only ScheduleEffect values"):
        TaskResult(outcome=Succeeded(), effects=cast("tuple[ScheduleEffect, ...]", (object(),)))
    with pytest.raises(TypeError, match="state_effects must contain only StateEffect values"):
        TaskResult(outcome=Succeeded(), state_effects=cast("tuple[StateEffect, ...]", (object(),)))
    with pytest.raises(TypeError, match="notifications must contain only OperatorNotificationRequest values"):
        TaskResult(outcome=Succeeded(), notifications=cast("tuple[OperatorNotificationRequest, ...]", (object(),)))


def test_operator_notification_request_is_typed_and_secret_free() -> None:
    request = OperatorNotificationRequest(
        OperatorNotificationKind.CAMPAIGN_NEW_SHIP,
        resource="campaign_main/12-4",
    )

    assert request.resource == "campaign_main/12-4"
    with pytest.raises(TypeError, match="kind must be an OperatorNotificationKind"):
        OperatorNotificationRequest(
            cast("OperatorNotificationKind", "campaign_new_ship"),
            resource="campaign_main/12-4",
        )
    with pytest.raises(ValueError, match="resource must be trimmed and non-empty"):
        OperatorNotificationRequest(OperatorNotificationKind.CAMPAIGN_NEW_SHIP, resource=" ")


def test_task_result_validates_notification_requests() -> None:
    request = OperatorNotificationRequest(
        OperatorNotificationKind.CAMPAIGN_REACH_LEVEL_LIMIT,
        resource="campaign_main/12-4",
    )

    result = TaskResult(outcome=Succeeded(), notifications=(request,))

    assert result.notifications == (request,)
    with pytest.raises(TypeError, match="notifications must be a tuple"):
        TaskResult(
            outcome=Succeeded(),
            notifications=cast("tuple[OperatorNotificationRequest, ...]", [request]),
        )
    with pytest.raises(ValueError, match="at most one request per kind"):
        TaskResult(outcome=Succeeded(), notifications=(request, request))


def test_campaign_notification_requires_a_resource() -> None:
    with pytest.raises(TypeError, match="resource must be a string"):
        OperatorNotificationRequest(
            OperatorNotificationKind.CAMPAIGN_RUN_COUNT_LIMIT,
            cast("str", None),
        )


def test_campaign_notification_resource_must_be_single_line() -> None:
    with pytest.raises(ValueError, match="single line"):
        OperatorNotificationRequest(
            OperatorNotificationKind.CAMPAIGN_NEW_SHIP,
            "event/stage\nforged",
        )


def test_task_result_rejects_non_tuple_and_duplicate_state_effects() -> None:
    upsert = UpsertTaskState("encounter.progress", "raid", 1, {"runs": 2})
    delete = DeleteTaskState("encounter.progress", "raid")

    with pytest.raises(TypeError, match="state_effects must be a tuple"):
        TaskResult(outcome=Succeeded(), state_effects=cast("tuple[StateEffect, ...]", [upsert]))
    with pytest.raises(ValueError, match="at most one operation per namespace/key"):
        TaskResult(outcome=Succeeded(), state_effects=(upsert, delete))


def test_task_result_preserves_distinct_state_effect_order() -> None:
    state_effects: tuple[StateEffect, ...] = (
        UpsertTaskState("encounter.progress", "raid", 1, {"runs": 2}),
        DeleteTaskState("event.lifecycle", "reset"),
    )

    result = TaskResult(outcome=Succeeded(), state_effects=state_effects)

    assert result.state_effects is state_effects


def test_task_result_rejects_multiple_reschedule_effects() -> None:
    due_at = datetime(2026, 7, 14, 4, tzinfo=UTC)

    with pytest.raises(ValueError, match="effects must contain at most one RescheduleSelf"):
        TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(due_at), RescheduleSelf(due_at)),
        )


def test_task_result_rejects_multiple_restart_effects() -> None:
    with pytest.raises(ValueError, match="effects must contain at most one RequestAppRestart"):
        TaskResult(
            outcome=Succeeded(),
            effects=(RequestAppRestart("first restart"), RequestAppRestart("second restart")),
        )


@pytest.mark.parametrize(
    "effects",
    [
        (
            WakeTask(
                TaskId("reward"),
                datetime(2026, 7, 14, 4, tzinfo=UTC),
                WakePolicy.FORCE_ENABLE,
            ),
            WakeTask(
                TaskId("reward"),
                datetime(2026, 7, 14, 5, tzinfo=UTC),
                WakePolicy.RESPECT_DISABLED,
            ),
        ),
        (DisableTask(TaskId("reward")), DisableTask(TaskId("reward"))),
        (
            WakeTask(
                TaskId("reward"),
                datetime(2026, 7, 14, 4, tzinfo=UTC),
                WakePolicy.FORCE_ENABLE,
            ),
            DisableTask(TaskId("reward")),
        ),
        (
            DisableTask(TaskId("reward")),
            WakeTask(
                TaskId("reward"),
                datetime(2026, 7, 14, 4, tzinfo=UTC),
                WakePolicy.FORCE_ENABLE,
            ),
        ),
        (
            RescheduleTask(TaskId("reward"), datetime(2026, 7, 14, 4, tzinfo=UTC)),
            DisableTask(TaskId("reward")),
        ),
        (
            DelayTask(TaskId("reward"), datetime(2026, 7, 14, 4, tzinfo=UTC)),
            RescheduleTask(TaskId("reward"), datetime(2026, 7, 14, 5, tzinfo=UTC)),
        ),
        (
            WakeTask(
                TaskId("reward"),
                datetime(2026, 7, 14, 4, tzinfo=UTC),
                WakePolicy.FORCE_ENABLE,
            ),
            RescheduleTask(TaskId("reward"), datetime(2026, 7, 14, 5, tzinfo=UTC)),
        ),
    ],
    ids=[
        "wake-wake",
        "disable-disable",
        "wake-disable",
        "disable-wake",
        "reschedule-disable",
        "delay-reschedule",
        "wake-reschedule",
    ],
)
def test_task_result_rejects_multiple_operations_for_the_same_task(
    effects: tuple[ScheduleEffect, ...],
) -> None:
    with pytest.raises(
        ValueError,
        match="effects must contain at most one target-task schedule operation per task_id",
    ):
        TaskResult(outcome=Succeeded(), effects=effects)


def test_task_result_preserves_distinct_effect_order() -> None:
    due_at = datetime(2026, 7, 14, 4, tzinfo=UTC)
    effects: tuple[ScheduleEffect, ...] = (
        WakeTask(TaskId("reward"), due_at, WakePolicy.RESPECT_DISABLED),
        RescheduleSelf(due_at),
        DisableTask(TaskId("commission")),
        RequestAppRestart("game process stopped"),
    )

    result = TaskResult(outcome=Succeeded(), effects=effects)

    assert result.effects is effects


class _CancellableTask(Task):
    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        return TaskResult(outcome=Succeeded())


def _run_task(task: Task, context: TaskContext) -> TaskResult:
    return task.run(context)


def test_task_context_exposes_task_identity_and_abort_token() -> None:
    abort = AbortToken()
    context = TaskContext(
        task_id=TaskId("main"),
        started_at=datetime(2026, 7, 13, tzinfo=UTC),
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=_metadata(),
        abort=abort,
    )

    assert isinstance(_run_task(_CancellableTask(), context).outcome, Succeeded)
    assert context.abort is abort

    abort.request("manual stop")
    with pytest.raises(AbortRequested, match="manual stop"):
        _run_task(_CancellableTask(), context)


def test_task_context_rejects_untyped_identity_values() -> None:
    with pytest.raises(TypeError, match="task_id must be a TaskId"):
        TaskContext(
            task_id=cast("TaskId", "main"),
            started_at=datetime(2026, 7, 13, tzinfo=UTC),
            mode=ExecutionMode.SCHEDULED_JOB,
            metadata=_metadata(),
            abort=AbortToken(),
        )


def test_task_context_requires_aware_started_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TaskContext(
            task_id=TaskId("main"),
            started_at=datetime(2026, 7, 13),
            mode=ExecutionMode.SCHEDULED_JOB,
            metadata=_metadata(),
            abort=AbortToken(),
        )
