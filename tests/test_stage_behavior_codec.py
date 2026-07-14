import pytest

from module.content import stage_behavior_codec
from module.content.battle_policy import ClearSiren
from module.content.errors import ContentValidationError
from module.content.mechanic_rules import StageMechanicRules
from module.content.stage_behavior_codec import decode_battle_program, decode_stage_policy


def _program(statement: object) -> dict[str, object]:
    return {
        "battle": 0,
        "activation_modes": ["normal"],
        "statements": [statement],
    }


def _decode_action(action: dict[str, object], entrypoint: str) -> None:
    if entrypoint == "program":
        decode_battle_program(
            _program({"tag": "attempt_battle", "action": action}),
            "program",
            StageMechanicRules(),
        )
        return
    decode_stage_policy({"steps": [action]}, "battle")


def test_stage_policy_decoder_applies_the_canonical_step_defaults() -> None:
    policy = decode_stage_policy({"steps": [{"tag": "clear_siren"}]}, "battle")

    assert policy.steps == (ClearSiren(),)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({}, r"battle requires field 'steps'"),
        ({"steps": [], "extra": True}, r"battle contains unknown fields: \['extra'\]"),
        ({"steps": []}, r"battle\.steps is invalid:.*must not be empty"),
    ],
)
def test_stage_policy_decoder_owns_its_document_schema(value: object, message: str) -> None:
    with pytest.raises(ContentValidationError, match=message):
        decode_stage_policy(value, "battle")


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (
            {"tag": "clear_chosen_enemy", "target": "a1", "expected": "enemy"},
            r"target must be a valid uppercase grid node",
        ),
        ({"tag": "clear_enemy", "scales": [0]}, r"scales\[0\] must be a positive integer"),
    ],
)
@pytest.mark.parametrize("entrypoint", ["policy", "program"])
def test_policy_and_program_share_the_battle_step_contract(
    action: dict[str, object],
    message: str,
    entrypoint: str,
) -> None:
    with pytest.raises(ContentValidationError, match=message):
        _decode_action(action, entrypoint)


def test_registered_but_undecoded_battle_step_is_rejected_at_its_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        stage_behavior_codec._STEP_FIELDS,  # noqa: SLF001 - 测试扩展表与解码器必须同步。
        "future_step",
        ({"tag"}, set()),
    )

    with pytest.raises(
        ContentValidationError,
        match=r"program\.statements\[0\]\.action\.tag contains an unknown tag: 'future_step'",
    ):
        decode_battle_program(
            _program(
                {
                    "tag": "attempt_battle",
                    "action": {"tag": "future_step"},
                }
            ),
            "program",
            StageMechanicRules(),
        )


def test_registered_but_undecoded_program_condition_is_rejected_at_its_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        stage_behavior_codec._PROGRAM_CONDITION_FIELDS,  # noqa: SLF001 - 测试扩展表与解码器必须同步。
        "future_condition",
        {"tag"},
    )

    with pytest.raises(
        ContentValidationError,
        match=(
            r"program\.statements\[0\]\.condition\.tag contains an unknown program condition: "
            r"'future_condition'"
        ),
    ):
        decode_battle_program(
            _program(
                {
                    "tag": "set_flag_from_condition",
                    "flag": "clear_mode",
                    "condition": {"tag": "future_condition"},
                }
            ),
            "program",
            StageMechanicRules(),
        )
