import pytest

from module.content import stage_behavior_codec
from module.content.errors import ContentValidationError
from module.content.mechanic_rules import StageMechanicRules
from module.content.stage_behavior_codec import decode_battle_program


def _program(statement: object) -> dict[str, object]:
    return {
        "battle": 0,
        "activation_modes": ["normal"],
        "statements": [statement],
    }


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
