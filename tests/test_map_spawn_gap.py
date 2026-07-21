from typing import override

from module.map.camera import Camera, FullScanOptions
from module.map.map_base import CampaignMap
from module.map.map_spawn_gap import MapSpawnGapPredictor, MapSpawnProgress


def _campaign_map(map_data: str, spawn_data: list[dict[str, int]]) -> CampaignMap:
    map_ = CampaignMap("spawn-gap-test")
    map_.map_data = map_data
    map_.spawn_data = spawn_data
    map_.load_spawn_data()
    return map_


class _RecordingSpawnGapPredictor(MapSpawnGapPredictor):
    def __init__(self) -> None:
        self.calls: list[tuple[str, MapSpawnProgress]] = []

    @override
    def scan_complete(self, progress: MapSpawnProgress) -> bool:
        self.calls.append(("complete", progress))
        return True

    @override
    def infer_covered_spawns(self, progress: MapSpawnProgress) -> None:
        self.calls.append(("infer", progress))


class _SpawnGapCamera(Camera):
    def __init__(self, map_: CampaignMap, predictor: MapSpawnGapPredictor) -> None:
        self.map = map_
        self.camera = (0, 0)
        self._spawn_gap_predictor = predictor


def test_estimate_accounts_for_progress_and_observed_spawns() -> None:
    map_ = _campaign_map(
        "ME ME MM MS MB",
        [
            {"battle": 0, "enemy": 2, "mystery": 1, "siren": 1},
            {"battle": 1, "enemy": 1, "boss": 1},
        ],
    )
    map_[(0, 0)].is_enemy = True
    map_[(2, 0)].is_mystery = True
    map_[(3, 0)].is_siren = True
    map_[(4, 0)].is_boss = True
    map_.map_covered = ["B1"]
    predictor = MapSpawnGapPredictor(map_)

    snapshot = predictor.estimate(MapSpawnProgress(battle_count=1))

    assert snapshot.missing == {
        "enemy": 1,
        "mystery": 0,
        "siren": 0,
        "boss": 0,
        "carrier": 0,
    }
    assert snapshot.possible == {"enemy": 1, "mystery": 0, "siren": 0, "boss": 0, "carrier": 0}
    assert predictor.scan_complete(MapSpawnProgress(battle_count=1)) is False
    assert predictor.scan_complete(MapSpawnProgress(battle_count=2)) is True
    assert predictor.scan_complete(MapSpawnProgress(battle_count=3)) is False


def test_estimate_restores_cleared_fortress_and_bouncing_enemy_gaps() -> None:
    map_ = _campaign_map("-- -- --", [{"battle": 0}])
    map_.fortress_data = [("A1",), ()]
    map_.bouncing_enemy_data = [("B1", "C1")]
    map_.load_mechanism(fortress=True, bouncing_enemy=True)
    map_[(0, 0)].wipe_out()
    map_[(1, 0)].may_bouncing_enemy = False
    map_[(2, 0)].may_bouncing_enemy = False

    snapshot = MapSpawnGapPredictor(map_).estimate(MapSpawnProgress())

    assert snapshot.missing["enemy"] == 2


def test_infer_covered_spawns_marks_only_forced_candidates() -> None:
    map_ = _campaign_map(
        "ME MM MS MB ME",
        [{"battle": 0, "enemy": 1, "mystery": 1, "siren": 1, "boss": 1}],
    )
    map_.map_covered = ["A1", "B1", "C1", "D1", "E1"]
    predictor = MapSpawnGapPredictor(map_)

    predictor.infer_covered_spawns(MapSpawnProgress())

    assert map_[(0, 0)].is_enemy is False
    assert map_[(4, 0)].is_enemy is False
    assert map_[(1, 0)].is_mystery is True
    assert map_[(2, 0)].is_siren is True
    assert map_[(3, 0)].is_boss is True


def test_infer_covered_carrier_marks_the_only_candidate_as_enemy() -> None:
    map_ = _campaign_map("--", [{"battle": 0}])
    map_.map_covered = ["A1"]

    MapSpawnGapPredictor(map_).infer_covered_spawns(MapSpawnProgress(carrier_count=1, mode="carrier"))

    assert map_[(0, 0)].is_enemy is True


def test_movable_mode_broadens_covered_enemy_and_siren_candidates() -> None:
    map_ = _campaign_map("--", [{"battle": 0}])
    map_.map_covered = ["A1"]
    predictor = MapSpawnGapPredictor(map_)

    normal = predictor.estimate(MapSpawnProgress())
    movable = predictor.estimate(MapSpawnProgress(mode="movable"))

    assert (normal.possible["enemy"], normal.possible["siren"]) == (0, 0)
    assert (movable.possible["enemy"], movable.possible["siren"]) == (1, 1)


def test_poor_map_never_finishes_or_infers_covered_spawns() -> None:
    map_ = _campaign_map("ME", [{"battle": 0, "enemy": 1}])
    map_.map_covered = ["A1"]
    map_.poor_map_data = True
    predictor = MapSpawnGapPredictor(map_)

    assert predictor.scan_complete(MapSpawnProgress()) is False
    predictor.infer_covered_spawns(MapSpawnProgress())

    assert map_[(0, 0)].is_enemy is False


def test_camera_scan_uses_one_progress_snapshot_for_completion_and_inference() -> None:
    map_ = _campaign_map("ME", [{"battle": 0, "enemy": 1}])
    predictor = _RecordingSpawnGapPredictor()
    camera = _SpawnGapCamera(map_, predictor)
    progress = MapSpawnProgress(battle_count=4, mystery_count=3, siren_count=2, carrier_count=1, mode="movable")

    camera.full_scan(
        FullScanOptions(
            queue=map_.to_selected(["A1"]),
            battle_count=progress.battle_count,
            mystery_count=progress.mystery_count,
            siren_count=progress.siren_count,
            carrier_count=progress.carrier_count,
            mode=progress.mode,
        )
    )

    assert predictor.calls == [("complete", progress), ("infer", progress)]
