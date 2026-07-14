import ast
from pathlib import Path

from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
from module.base import decorator
from module.campaign.campaign_engine import CampaignEngine

_LEGACY_ORCHESTRATION = frozenset(
    {
        "_battle_by_count",
        "_battle_clear_all",
        "_battle_with_poor_map_data",
        "_clear_remaining_enemy_for_clear_all",
        "battle_default",
        "battle_boss",
        "battle_function",
        "execute_a_battle",
        "run",
    }
)


def _class_node(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_decorator_module_has_no_global_config_dispatch() -> None:
    assert "Config" not in decorator.__all__
    assert not hasattr(decorator, "Config")


def test_production_runtime_exposes_no_legacy_campaign_orchestration() -> None:
    assert CampaignEngine in DeclarativeCampaignMapRuntime.__mro__
    assert _LEGACY_ORCHESTRATION.isdisjoint(dir(CampaignEngine))
    assert _LEGACY_ORCHESTRATION.isdisjoint(dir(DeclarativeCampaignMapRuntime))


def test_production_runtime_source_cannot_restore_reflective_battle_dispatch() -> None:
    root = Path(__file__).parents[1]
    runtime_node = _class_node(
        root / "module" / "adapters" / "campaign_mumu12.py",
        "DeclarativeCampaignMapRuntime",
    )
    engine_node = _class_node(
        root / "module" / "campaign" / "campaign_engine.py",
        "CampaignEngine",
    )

    assert [base.id for base in runtime_node.bases if isinstance(base, ast.Name)] == ["CampaignEngine"]
    assert not (root / "module" / "campaign" / "campaign_base.py").exists()
    for class_node in (runtime_node, engine_node):
        defined_methods = {
            node.name for node in class_node.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        assert _LEGACY_ORCHESTRATION.isdisjoint(defined_methods)
        assert not any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
            for node in ast.walk(class_node)
        )
