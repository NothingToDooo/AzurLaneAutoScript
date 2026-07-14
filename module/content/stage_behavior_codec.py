from collections.abc import Mapping, Sequence
from typing import cast

from module.base.utils import node2location
from module.content.battle_policy import (
    AllConditions,
    AnyCondition,
    BattleCondition,
    BattleFlag,
    BattleStep,
    BossStrategy,
    CellAccessibleCondition,
    ClearAnyEnemy,
    ClearBoss,
    ClearBossRoadblock,
    ClearChosenEnemy,
    ClearEnemy,
    ClearFilteredEnemy,
    ClearPriorityEnemy,
    ClearSelectedEnemy,
    ClearSiren,
    DefaultBattle,
    FlagCondition,
    GuardedBattleStep,
    NotCondition,
    TargetExpectation,
)
from module.content.battle_program import (
    AllProgramConditions,
    AnyProgramCondition,
    AttemptBattleAction,
    AttemptFixedTarget,
    AttemptMechanicAction,
    AttemptPresetRoute,
    BattleProgram,
    BattleProgramDelegation,
    BattleProgramMode,
    BossAccessibleCondition,
    BossAtCondition,
    CandidateEnemyCondition,
    CellAccessibleForFleetCondition,
    CellProperty,
    CellPropertyCondition,
    ComparisonOperator,
    DelegateBattle,
    EndCampaign,
    ExecuteFixedTarget,
    ExecutePresetRoute,
    FleetAtCondition,
    MapPresence,
    MapPresenceCondition,
    MarkAllSirenCandidates,
    MechanicActionBranch,
    MetricCondition,
    NotProgramCondition,
    PerformMechanicAction,
    ProgramBranch,
    ProgramCondition,
    ProgramFlag,
    ProgramFlagCondition,
    ProgramMarker,
    ProgramMarkerCondition,
    ProgramMechanicAction,
    ProgramMetric,
    ProgramStatement,
    ReturnBattleAction,
    ReturnMechanicAction,
    ReturnProgramContinue,
    ReturnProgramNoTarget,
    SetMapWeights,
    SetProgramFlag,
    SetProgramFlagFromCondition,
    SetProgramMarker,
    SetProgramMarkerFromCondition,
)
from module.content.cell import CellId
from module.content.errors import ContentValidationError
from module.content.mechanic_rules import (
    EncounterExpectation,
    EnemyMovementRules,
    FixedTargetSequence,
    FleetRole,
    MechanicOperation,
    MechanicProcedure,
    MoveEnemy,
    PresetRouteBattle,
    PresetRouteStep,
    PresetRouteVariant,
    StageMechanicRules,
)

_STEP_FIELDS = {
    "clear_siren": ({"tag"}, {"genres", "include_hidden_candidates"}),
    "clear_filtered_enemy": ({"tag", "preserve"}, {"enemy_filter"}),
    "clear_enemy": ({"tag"}, {"scales", "genres", "sort", "strongest"}),
    "clear_any_enemy": ({"tag"}, {"genres", "sort", "strongest"}),
    "clear_chosen_enemy": ({"tag", "target", "expected"}, set()),
    "clear_selected_enemy": ({"tag", "candidates", "excluded_genres", "expected"}, set()),
    "clear_priority_enemy": ({"tag", "include_scale_1"}, set()),
    "default_battle": ({"tag"}, set()),
    "clear_boss_roadblock": ({"tag", "strategy"}, set()),
    "clear_boss": ({"tag", "strategy"}, set()),
    "guarded": ({"tag", "condition", "step"}, set()),
}

_CONDITION_FIELDS = {
    "flag": {"tag", "flag", "value"},
    "cell_accessible": {"tag", "cell"},
    "all": {"tag", "conditions"},
    "any": {"tag", "conditions"},
    "not": {"tag", "condition"},
}


def _mapping(value: object, location: str, fields: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        message = f"{location} must be a mapping with string fields"
        raise ContentValidationError(message)
    item = cast("Mapping[str, object]", value)
    if set(item) != fields:
        message = f"{location} fields must be exactly {sorted(fields)}"
        raise ContentValidationError(message)
    return item


def _sequence(value: object, location: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        message = f"{location} must be a list"
        raise ContentValidationError(message)
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        message = f"{location} must be a non-empty string"
        raise ContentValidationError(message)
    return value


def _integer(value: object, location: str) -> int:
    if type(value) is not int or value < 0:
        message = f"{location} must be a non-negative integer"
        raise ContentValidationError(message)
    return value


def _boolean(value: object, location: str) -> bool:
    if type(value) is not bool:
        message = f"{location} must be a boolean"
        raise ContentValidationError(message)
    return value


def _strings(value: object, location: str) -> tuple[str, ...]:
    return tuple(_string(item, f"{location}[{index}]") for index, item in enumerate(_sequence(value, location)))


def _integers(value: object, location: str) -> tuple[int, ...]:
    return tuple(_integer(item, f"{location}[{index}]") for index, item in enumerate(_sequence(value, location)))


def _step_mapping(value: object, location: str, tag: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        message = f"{location} must be a mapping with string fields"
        raise ContentValidationError(message)
    item = cast("Mapping[str, object]", value)
    required, optional = _STEP_FIELDS[tag]
    if not required <= set(item) or not set(item) <= required | optional:
        message = f"{location} fields must contain {sorted(required)} and only allow {sorted(optional)}"
        raise ContentValidationError(message)
    return item


def _condition(value: object, location: str) -> BattleCondition:
    if not isinstance(value, Mapping) or "tag" not in value:
        message = f"{location} must declare a condition tag"
        raise ContentValidationError(message)
    raw = cast("Mapping[object, object]", value)
    tag = _string(raw["tag"], f"{location}.tag")
    fields = _CONDITION_FIELDS.get(tag)
    if fields is None:
        message = f"{location}.tag contains an unknown condition tag: {tag!r}"
        raise ContentValidationError(message)
    item = _mapping(value, location, fields)
    if tag == "flag":
        return FlagCondition(
            _enum(BattleFlag, item["flag"], f"{location}.flag"),
            _boolean(item["value"], f"{location}.value"),
        )
    if tag == "cell_accessible":
        return CellAccessibleCondition(_cell(item["cell"], f"{location}.cell"))
    if tag in {"all", "any"}:
        conditions = tuple(
            _condition(raw_condition, f"{location}.conditions[{index}]")
            for index, raw_condition in enumerate(_sequence(item["conditions"], f"{location}.conditions"))
        )
        return AllConditions(conditions) if tag == "all" else AnyCondition(conditions)
    return NotCondition(_condition(item["condition"], f"{location}.condition"))


def _strategy(value: object, location: str) -> BossStrategy:
    raw = _string(value, location)
    try:
        return BossStrategy(raw)
    except ValueError as error:
        message = f"{location} contains an unknown BossStrategy: {raw!r}"
        raise ContentValidationError(message) from error


def _step(  # noqa: C901, PLR0911, PLR0912 - 封闭 tag 解码必须穷举。
    value: object,
    location: str,
) -> BattleStep:
    if not isinstance(value, Mapping) or "tag" not in value:
        message = f"{location} must declare a tag"
        raise ContentValidationError(message)
    raw = cast("Mapping[object, object]", value)
    tag = _string(raw["tag"], f"{location}.tag")
    if tag not in _STEP_FIELDS:
        message = f"{location}.tag contains an unknown tag: {tag!r}"
        raise ContentValidationError(message)
    item = _step_mapping(value, location, tag)
    if tag == "clear_siren":
        return ClearSiren(
            _strings(item.get("genres", ()), f"{location}.genres"),
            _boolean(
                item.get("include_hidden_candidates", False),
                f"{location}.include_hidden_candidates",
            ),
        )
    if tag == "clear_filtered_enemy":
        raw_filter = item.get("enemy_filter")
        enemy_filter = None if raw_filter is None else _string(raw_filter, f"{location}.enemy_filter")
        return ClearFilteredEnemy(_integer(item["preserve"], f"{location}.preserve"), enemy_filter)
    if tag == "clear_enemy":
        return ClearEnemy(
            scales=_integers(item.get("scales", ()), f"{location}.scales"),
            genres=_strings(item.get("genres", ()), f"{location}.genres"),
            sort=_strings(item.get("sort", ()), f"{location}.sort"),
            strongest=_boolean(item.get("strongest", False), f"{location}.strongest"),
        )
    if tag == "clear_any_enemy":
        return ClearAnyEnemy(
            genres=_strings(item.get("genres", ()), f"{location}.genres"),
            sort=_strings(item.get("sort", ()), f"{location}.sort"),
            strongest=_boolean(item.get("strongest", False), f"{location}.strongest"),
        )
    if tag == "clear_chosen_enemy":
        return ClearChosenEnemy(
            _cell(item["target"], f"{location}.target"),
            _enum(TargetExpectation, item["expected"], f"{location}.expected"),
        )
    if tag == "clear_selected_enemy":
        return ClearSelectedEnemy(
            _cells(item["candidates"], f"{location}.candidates"),
            _strings(item["excluded_genres"], f"{location}.excluded_genres"),
            _enum(TargetExpectation, item["expected"], f"{location}.expected"),
        )
    if tag == "clear_priority_enemy":
        return ClearPriorityEnemy(_boolean(item["include_scale_1"], f"{location}.include_scale_1"))
    if tag == "default_battle":
        return DefaultBattle()
    if tag == "guarded":
        guarded_step = _step(item["step"], f"{location}.step")
        if isinstance(guarded_step, GuardedBattleStep):
            message = f"{location}.step must not contain a nested guard"
            raise ContentValidationError(message)
        return GuardedBattleStep(
            _condition(item["condition"], f"{location}.condition"),
            guarded_step,
        )
    if tag in {"clear_boss_roadblock", "clear_boss"}:
        strategy = _strategy(item["strategy"], f"{location}.strategy")
        if tag == "clear_boss_roadblock":
            return ClearBossRoadblock(strategy)
        if tag == "clear_boss":
            return ClearBoss(strategy)
    message = f"{location}.tag contains an unknown tag: {tag!r}"
    raise ContentValidationError(message)


def _free_mapping(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        message = f"{location} must be a mapping with string fields"
        raise ContentValidationError(message)
    return cast("Mapping[str, object]", value)


def _cell(value: object, location: str) -> CellId:
    node = _string(value, location)
    try:
        x, y = node2location(node)
    except (TypeError, ValueError) as error:
        message = f"{location} must be a grid node"
        raise ContentValidationError(message) from error
    return CellId(x, y)


def _cells(value: object, location: str) -> tuple[CellId, ...]:
    return tuple(_cell(raw_cell, f"{location}[{index}]") for index, raw_cell in enumerate(_sequence(value, location)))


def _enum[E](enum: type[E], value: object, location: str) -> E:
    raw = _string(value, location)
    try:
        return enum(raw)
    except ValueError as error:
        message = f"{location} contains an unknown {enum.__name__}: {raw!r}"
        raise ContentValidationError(message) from error


def decode_enemy_movement_rules(value: object, location: str) -> EnemyMovementRules:
    moves = []
    for index, raw_move in enumerate(_sequence(value, location)):
        item_location = f"{location}[{index}]"
        item = _mapping(raw_move, item_location, {"battle", "source", "target"})
        moves.append(
            MoveEnemy(
                _integer(item["battle"], f"{item_location}.battle"),
                _cell(item["source"], f"{item_location}.source"),
                _cell(item["target"], f"{item_location}.target"),
            )
        )
    return EnemyMovementRules(tuple(moves))


def decode_mechanic_procedures(value: object, location: str) -> tuple[MechanicProcedure, ...]:
    procedures = []
    for index, raw_procedure in enumerate(_sequence(value, location)):
        item_location = f"{location}[{index}]"
        item = _mapping(raw_procedure, item_location, {"battle", "operations"})
        operations = tuple(
            _enum(MechanicOperation, raw_operation, f"{item_location}.operations[{operation_index}]")
            for operation_index, raw_operation in enumerate(
                _sequence(item["operations"], f"{item_location}.operations")
            )
        )
        procedures.append(MechanicProcedure(_integer(item["battle"], f"{item_location}.battle"), operations))
    return tuple(procedures)


def decode_preset_route_variants(value: object, location: str) -> tuple[PresetRouteVariant, ...]:
    variants = []
    for index, raw_variant in enumerate(_sequence(value, location)):
        item_location = f"{location}[{index}]"
        item = _mapping(raw_variant, item_location, {"start_column", "battles"})
        battles = []
        for battle_index, raw_battle in enumerate(_sequence(item["battles"], f"{item_location}.battles")):
            battle_location = f"{item_location}.battles[{battle_index}]"
            battle_item = _mapping(raw_battle, battle_location, {"battle", "steps"})
            steps = []
            for step_index, raw_step in enumerate(_sequence(battle_item["steps"], f"{battle_location}.steps")):
                step_location = f"{battle_location}.steps[{step_index}]"
                step = _mapping(raw_step, step_location, {"fleet", "delta_x", "delta_y", "clear_enemy"})
                clear_enemy = step["clear_enemy"]
                if type(clear_enemy) is not bool:
                    message = f"{step_location}.clear_enemy must be a boolean"
                    raise ContentValidationError(message)
                steps.append(
                    PresetRouteStep(
                        _enum(FleetRole, step["fleet"], f"{step_location}.fleet"),
                        _signed_integer(step["delta_x"], f"{step_location}.delta_x"),
                        _signed_integer(step["delta_y"], f"{step_location}.delta_y"),
                        clear_enemy,
                    )
                )
            battles.append(
                PresetRouteBattle(
                    _integer(battle_item["battle"], f"{battle_location}.battle"),
                    tuple(steps),
                )
            )
        variants.append(
            PresetRouteVariant(
                _integer(item["start_column"], f"{item_location}.start_column"),
                tuple(battles),
            )
        )
    return tuple(variants)


def decode_fixed_target_sequences(value: object, location: str) -> tuple[FixedTargetSequence, ...]:
    sequences = []
    for index, raw_sequence in enumerate(_sequence(value, location)):
        item_location = f"{location}[{index}]"
        item = _mapping(raw_sequence, item_location, {"battles", "targets", "fleet"})
        battles = tuple(
            _integer(raw_battle, f"{item_location}.battles[{battle_index}]")
            for battle_index, raw_battle in enumerate(_sequence(item["battles"], f"{item_location}.battles"))
        )
        sequences.append(
            FixedTargetSequence(
                battles,
                _cells(item["targets"], f"{item_location}.targets"),
                _enum(FleetRole, item["fleet"], f"{item_location}.fleet"),
            )
        )
    return tuple(sequences)


_PROGRAM_CONDITION_FIELDS = {
    "flag": {"tag", "flag", "value"},
    "marker": {"tag", "marker", "value"},
    "metric": {"tag", "metric", "operator", "value"},
    "cell_property": {"tag", "cell", "property", "operator", "value"},
    "fleet_at": {"tag", "cell", "fleet"},
    "map_presence": {"tag", "presence"},
    "boss_at": {"tag", "cell"},
    "boss_accessible": {"tag", "fleet"},
    "cell_accessible_for_fleet": {"tag", "cell", "fleet"},
    "candidate_enemy": {"tag", "candidates", "excluded_genres"},
    "all": {"tag", "conditions"},
    "any": {"tag", "conditions"},
    "not": {"tag", "condition"},
}


def _program_condition(  # noqa: C901, PLR0911, PLR0912 - 封闭 condition tag 解码必须穷举。
    value: object,
    location: str,
) -> ProgramCondition:
    raw = _free_mapping(value, location)
    tag = _string(raw.get("tag"), f"{location}.tag")
    fields = _PROGRAM_CONDITION_FIELDS.get(tag)
    if fields is None:
        message = f"{location}.tag contains an unknown program condition: {tag!r}"
        raise ContentValidationError(message)
    item = _mapping(value, location, fields)
    if tag == "flag":
        return ProgramFlagCondition(
            _enum(ProgramFlag, item["flag"], f"{location}.flag"),
            _boolean(item["value"], f"{location}.value"),
        )
    if tag == "marker":
        return ProgramMarkerCondition(
            ProgramMarker.parse(_string(item["marker"], f"{location}.marker")),
            _boolean(item["value"], f"{location}.value"),
        )
    if tag == "metric":
        return MetricCondition(
            _enum(ProgramMetric, item["metric"], f"{location}.metric"),
            _enum(ComparisonOperator, item["operator"], f"{location}.operator"),
            _signed_integer(item["value"], f"{location}.value"),
        )
    if tag == "cell_property":
        raw_value = item["value"]
        if not isinstance(raw_value, bool | int | str):
            message = f"{location}.value must be boolean, integer, or string"
            raise ContentValidationError(message)
        return CellPropertyCondition(
            _cell(item["cell"], f"{location}.cell"),
            _enum(CellProperty, item["property"], f"{location}.property"),
            _enum(ComparisonOperator, item["operator"], f"{location}.operator"),
            raw_value,
        )
    if tag == "fleet_at":
        return FleetAtCondition(
            _cell(item["cell"], f"{location}.cell"),
            _enum(FleetRole, item["fleet"], f"{location}.fleet"),
        )
    if tag == "map_presence":
        return MapPresenceCondition(_enum(MapPresence, item["presence"], f"{location}.presence"))
    if tag == "boss_at":
        return BossAtCondition(_cell(item["cell"], f"{location}.cell"))
    if tag == "boss_accessible":
        return BossAccessibleCondition(_enum(FleetRole, item["fleet"], f"{location}.fleet"))
    if tag == "cell_accessible_for_fleet":
        return CellAccessibleForFleetCondition(
            _cell(item["cell"], f"{location}.cell"),
            _enum(FleetRole, item["fleet"], f"{location}.fleet"),
        )
    if tag == "candidate_enemy":
        return CandidateEnemyCondition(
            _cells(item["candidates"], f"{location}.candidates"),
            _strings(item["excluded_genres"], f"{location}.excluded_genres"),
        )
    if tag in {"all", "any"}:
        conditions = tuple(
            _program_condition(raw_condition, f"{location}.conditions[{index}]")
            for index, raw_condition in enumerate(_sequence(item["conditions"], f"{location}.conditions"))
        )
        return AllProgramConditions(conditions) if tag == "all" else AnyProgramCondition(conditions)
    if tag == "not":
        return NotProgramCondition(_program_condition(item["condition"], f"{location}.condition"))
    message = f"{location}.tag contains an unknown program condition: {tag!r}"
    raise ContentValidationError(message)


def _signed_integer(value: object, location: str) -> int:
    if type(value) is not int:
        message = f"{location} must be an integer"
        raise ContentValidationError(message)
    return value


def _program_mechanic_action(
    value: object,
    location: str,
    rules: StageMechanicRules,
) -> ProgramMechanicAction:
    item = _mapping(value, location, {"category", "index"})
    category = _string(item["category"], f"{location}.category")
    index = _integer(item["index"], f"{location}.index")
    actions_by_category = {
        "roadblocks": rules.roadblocks.actions,
        "fleet_coordination": rules.fleet_coordination.actions,
        "pickups": rules.pickups.actions,
        "map_interactions": rules.map_interactions.actions,
        "enemy_movement": rules.enemy_movement.moves,
        "procedures": rules.procedures,
    }
    actions = actions_by_category.get(category)
    if actions is None:
        message = f"{location}.category contains an unknown mechanic category: {category!r}"
        raise ContentValidationError(message)
    if index >= len(actions):
        message = f"{location}.index is outside {category}: {index}"
        raise ContentValidationError(message)
    return actions[index]


def _nullable_expectation(value: object, location: str) -> EncounterExpectation | None:
    if value is None:
        return None
    return _enum(EncounterExpectation, value, location)


def _program_statement(  # noqa: C901, PLR0911, PLR0912 - 封闭 statement tag 解码必须穷举。
    value: object,
    location: str,
    rules: StageMechanicRules,
) -> ProgramStatement:
    raw = _free_mapping(value, location)
    tag = _string(raw.get("tag"), f"{location}.tag")
    if tag in {"attempt_battle", "return_battle"}:
        item = _mapping(value, location, {"tag", "action"})
        action = _step(item["action"], f"{location}.action")
        return AttemptBattleAction(action) if tag == "attempt_battle" else ReturnBattleAction(action)
    if tag in {"attempt_mechanic", "perform_mechanic", "return_mechanic"}:
        item = _mapping(value, location, {"tag", "action", "expected_target"})
        action = _program_mechanic_action(item["action"], f"{location}.action", rules)
        expected = _nullable_expectation(item["expected_target"], f"{location}.expected_target")
        if tag == "attempt_mechanic":
            if expected is None:
                message = f"{location}.expected_target must not be null for attempt_mechanic"
                raise ContentValidationError(message)
            return AttemptMechanicAction(action, expected)
        if tag == "perform_mechanic":
            return PerformMechanicAction(action, expected)
        return ReturnMechanicAction(action, expected)
    if tag == "mechanic_branch":
        item = _mapping(
            value,
            location,
            {"tag", "action", "expected_target", "when_applied", "when_not_applied"},
        )
        action = _program_mechanic_action(item["action"], f"{location}.action", rules)
        return MechanicActionBranch(
            action,
            tuple(
                _program_statement(raw_statement, f"{location}.when_applied[{index}]", rules)
                for index, raw_statement in enumerate(_sequence(item["when_applied"], f"{location}.when_applied"))
            ),
            tuple(
                _program_statement(raw_statement, f"{location}.when_not_applied[{index}]", rules)
                for index, raw_statement in enumerate(
                    _sequence(item["when_not_applied"], f"{location}.when_not_applied")
                )
            ),
            _nullable_expectation(item["expected_target"], f"{location}.expected_target"),
        )
    if tag == "attempt_preset_route":
        item = _mapping(value, location, {"tag", "battle", "expected_target"})
        battle = _integer(item["battle"], f"{location}.battle")
        return AttemptPresetRoute(
            ExecutePresetRoute(
                battle,
                rules.preset_routes,
                rules.fixed_target_sequences,
            ),
            _enum(
                EncounterExpectation,
                item["expected_target"],
                f"{location}.expected_target",
            ),
        )
    if tag == "attempt_fixed_target":
        item = _mapping(value, location, {"tag", "battle", "expected_target"})
        battle = _integer(item["battle"], f"{location}.battle")
        return AttemptFixedTarget(
            ExecuteFixedTarget(battle, rules.fixed_target_sequences),
            _enum(
                EncounterExpectation,
                item["expected_target"],
                f"{location}.expected_target",
            ),
        )
    if tag == "branch":
        item = _mapping(value, location, {"tag", "condition", "when_true", "when_false"})
        return ProgramBranch(
            _program_condition(item["condition"], f"{location}.condition"),
            tuple(
                _program_statement(raw_statement, f"{location}.when_true[{index}]", rules)
                for index, raw_statement in enumerate(_sequence(item["when_true"], f"{location}.when_true"))
            ),
            tuple(
                _program_statement(raw_statement, f"{location}.when_false[{index}]", rules)
                for index, raw_statement in enumerate(_sequence(item["when_false"], f"{location}.when_false"))
            ),
        )
    if tag == "set_flag":
        item = _mapping(value, location, {"tag", "flag", "value"})
        return SetProgramFlag(
            _enum(ProgramFlag, item["flag"], f"{location}.flag"),
            _boolean(item["value"], f"{location}.value"),
        )
    if tag == "set_flag_from_condition":
        item = _mapping(value, location, {"tag", "flag", "condition"})
        return SetProgramFlagFromCondition(
            _enum(ProgramFlag, item["flag"], f"{location}.flag"),
            _program_condition(item["condition"], f"{location}.condition"),
        )
    if tag == "set_marker":
        item = _mapping(value, location, {"tag", "marker", "value"})
        return SetProgramMarker(
            ProgramMarker.parse(_string(item["marker"], f"{location}.marker")),
            _boolean(item["value"], f"{location}.value"),
        )
    if tag == "set_marker_from_condition":
        item = _mapping(value, location, {"tag", "marker", "condition"})
        return SetProgramMarkerFromCondition(
            ProgramMarker.parse(_string(item["marker"], f"{location}.marker")),
            _program_condition(item["condition"], f"{location}.condition"),
        )
    if tag == "mark_all_siren_candidates":
        _mapping(value, location, {"tag"})
        return MarkAllSirenCandidates()
    if tag == "set_map_weights":
        item = _mapping(value, location, {"tag", "rows"})
        rows = tuple(
            tuple(
                _integer(weight, f"{location}.rows[{row_index}][{column_index}]")
                for column_index, weight in enumerate(_sequence(raw_row, f"{location}.rows[{row_index}]"))
            )
            for row_index, raw_row in enumerate(_sequence(item["rows"], f"{location}.rows"))
        )
        return SetMapWeights(rows)
    if tag == "return_continue":
        _mapping(value, location, {"tag"})
        return ReturnProgramContinue()
    if tag == "return_no_target":
        _mapping(value, location, {"tag"})
        return ReturnProgramNoTarget()
    if tag == "end_campaign":
        _mapping(value, location, {"tag"})
        return EndCampaign()
    if tag == "delegate":
        item = _mapping(value, location, {"tag", "target"})
        return DelegateBattle(_enum(BattleProgramDelegation, item["target"], f"{location}.target"))
    message = f"{location}.tag contains an unknown program statement: {tag!r}"
    raise ContentValidationError(message)


def decode_battle_program(
    value: object,
    location: str,
    rules: StageMechanicRules,
) -> BattleProgram:
    """把内容文档中的程序编译为封闭、类型化的 BattleProgram。"""

    item = _mapping(value, location, {"activation_modes", "battle", "statements"})
    activation_modes = tuple(
        _enum(BattleProgramMode, raw_mode, f"{location}.activation_modes[{index}]")
        for index, raw_mode in enumerate(_sequence(item["activation_modes"], f"{location}.activation_modes"))
    )
    if len(set(activation_modes)) != len(activation_modes):
        message = f"{location}.activation_modes must not contain duplicates"
        raise ContentValidationError(message)
    return BattleProgram(
        _integer(item["battle"], f"{location}.battle"),
        frozenset(activation_modes),
        tuple(
            _program_statement(raw_statement, f"{location}.statements[{index}]", rules)
            for index, raw_statement in enumerate(_sequence(item["statements"], f"{location}.statements"))
        ),
    )
