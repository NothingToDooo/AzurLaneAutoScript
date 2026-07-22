import re
from collections.abc import Sized
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

import numpy as np
import yaml

from dev_tools.utils import LuaLoader, require_lua_int, require_lua_str, require_lua_table
from module.base.utils import location2node
from module.map.utils import camera_2d, camera_spawn_point, get_map_active_area
from module.project_paths import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from yaml.nodes import ScalarNode

    from dev_tools.slpp import LuaTable, LuaValue
    from module.base.type_alias import FilePath

type GridLocation = tuple[int, int]
type SpawnField = Literal["enemy", "siren", "mystery"]
type SpawnRule = dict[str, int]
type StageScalar = str | int | bool | None
type StageValue = StageScalar | Sequence[StageValue] | Mapping[str, StageValue] | Mapping[int, StageValue]
type BattleDocument = dict[int, StageValue]

FILE = PROJECT_ROOT.parent / "AzurLaneLuaScripts"
FOLDER = PROJECT_ROOT / "content" / "events" / "event_20260417_cn" / "stages"
KEYWORD = "2020001"
SELECT = True
OVERWRITE = True
ENEMY_FILTER = "1L > 1M > 1E > 1C > 2L > 2M > 2E > 2C > 3L > 3M > 3E > 3C"


class _LuaDataStore:
    __slots__ = ("chapter", "chapter_loop", "expectation", "map_event_list", "map_event_template")

    def __init__(self) -> None:
        self.chapter: LuaTable = {}
        self.chapter_loop: LuaTable = {}
        self.map_event_list: LuaTable = {}
        self.map_event_template: LuaTable = {}
        self.expectation: LuaTable = {}


_LUA_DATA = _LuaDataStore()


class _LiteralString(str):  # ruff:ignore[subclass-builtin] - PyYAML 以 str 子类区分 literal scalar。
    __slots__ = ()


class _StageDumper(yaml.SafeDumper):
    pass


def _represent_literal(dumper: _StageDumper, value: _LiteralString) -> ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")


_StageDumper.add_representer(_LiteralString, _represent_literal)


def _active_area(map_data: Mapping[GridLocation, str]) -> tuple[int, int, int, int]:
    area = get_map_active_area(map_data)
    return int(area[0]), int(area[1]), int(area[2]), int(area[3])


def _optional_lua_table(value: LuaValue | None, *, context: str) -> LuaTable | None:
    if value is None:
        return None
    return require_lua_table(value, context=context)


DIC_SIREN_NAME_CHI_TO_ENG: dict[str, str] = {
    # Siren Winter's Crown, Fallen Wings
    "sairenquzhu": "DD",
    "sairenqingxun": "CL",
    "sairenzhongxun": "CA",
    "sairenzhanlie": "BB",
    "sairenhangmu": "CV",
    "sairenqianting": "SS",
    # Siren cyan
    "sairenquzhu_i": "DD",
    "sairenqingxun_i": "CL",
    "sairenzhongxun_i": "CA",
    "sairenzhanlie_i": "BB",
    "sairenhangmu_i": "CV",
    "sairenqianting_i": "SS",
    # Siren red
    "sairenquzhu_M": "DD",
    "sairenqingxun_M": "CL",
    "sairenzhongxun_M": "CAred",
    "sairenzhanlie_M": "BBred",
    "sairenhangmu_M": "CV",
    "sairenqianting_M": "SS",
    # Scherzo of Iron and Blood
    "aruituosha": "Arethusa",
    "xiefeierde": "Sheffield",
    "duosaitejun": "Dorsetshire",
    "shengwang": "Renown",
    "weiershiqinwang": "PrinceOfWales",
    # Universe in Unison
    "edu_idol": "LeMalinIdol",
    "daiduo_idol": "DidoIdol",
    "daqinghuayu_idol": "AlbacoreIdol",
    "baerdimo_idol": "BaltimoreIdol",
    "kelifulan_idol": "ClevelandIdol",
    "xipeier_idol": "HipperIdol",
    "sipeibojue_5": "SpeeIdol",
    "luoen_idol": "RoonIdol",
    "guanghui_idol": "IllustriousIdol",
    # Vacation Lane
    "maliluosi_doa": "MarieRoseDOA",
    "haixiao_doa": "MisakiDOA",
    "xia_doa": "KasumiDOA",
    "zhixiao_doa": "NagisaDOA",
    # The Enigma and the Shark
    "nvjiang": "Amazon",
    # Inverted Orthant
    "luodeni": "Rodney",
    "huangjiafangzhou": "ArkRoyal",
    "jingang": "Kongo",
    "shancheng": "Yamashiro",
    "z24": "Z24",
    "niulunbao": "Nuremberg",
    "longqibing": "Carabiniere",
    # siren_ii has purple lightning around
    # Detect area of DD and CL are not effected
    "sairenquzhu_ii": "DD",
    "sairenqingxun_ii": "CL",
    "sairenzhongxun_ii": "CAlightning",
    "sairenzhanlie_ii": "BBlightning",
    "sairenhangmu_ii": "CVlightning",
    "qinraozhe": "Intruder",
    "xianghe": "Shokaku",
    "ruihe": "Zuikaku",
    "shitelasai": "PeterStrasser",
    # Empyreal Tragicomedy
    "teluntuo": "Trento",
    "lituoliao": "Littorio",
    "jianyu": "Swordfish",  # Not siren but movable enemy
    # Ashen Simulacrum
    "shengdiyage": "SanDiego",
    "weiqita": "Wichita",
    "yalisangna": "Arizona",
    "liekexingdun": "Lexington",
    "tiaoyu": "Dace",
    # Daedalian Hymn
    "geluosite": "Gloucester",
    "yueke": "York",
    "yanzhan": "Warspite",
    "naerxun": "Nelson",
    "kewei": "Formidable",
    "guanghui": "Illustrious",
    # Mirror Involution
    # Note: In this event, sirens are covered by fog
    "duwei": "Dewey",
    "haman": "Hammann",
    "yatelanda": "Atlanta",
    "beianpudun": "Northampton",
    # Swirling Cherry Blossoms
    "xia": "Kasumi",
    "xiang": "Hibiki",
    "guinu": "Kinu",
    "moye": "Maya",
    "yishi": "Ise",
    "sunying": "Junyo",
    # Skybound Oratorio
    "aerjiliya": "Algerie",
    "jialisuoniye": "LaGalissonniere",
    "wokelan": "Vauquelin",
    # Crimson Echoes
    "xili": "Yuudachi",
    "shentong": "Jintsuu",
    "niaohai": "Choukai",
    "wudao": "Kirishima",
    "canglong": "Souryuu",
    # Tower of Transcendence
    "sairenquzhu_6": "DD",
    "sairenqingxun_6": "CL",
    "sairenzhongxun_6": "CA",
    "sairenzhanlie_6": "BB",
    "sairenhangmu_6": "CV",
    # Northern Overture Rerun
    "ganraozhe": "Intruder",
    # Abyssal Refrain
    "lingmin": "Soobrazitelny",
    "jifu": "Kiev",
    "fuerjia": "Volga",
    # Aurora Noctis
    "U81": "U81",
    "U101": "U101",
    "U522": "U522",
    "deyizhi": "Deutschland",
    "tierbici": "Tirpitz",
    "genaisennao": "Gneisenau",
    "shaenhuosite": "Scharnhorst",
    "sipeibojue": "Spee",
    "U73": "U73",
    # Rondo at Rainbow's End
    "z2": "Z2",
    "laibixi": "Leipzig",
    "ougen": "PrinzEugen",
    "sairenqianting_ii": "SS",
    "sairenboss11": "Compiler",
    # Pledge of the Radiant Court
    "sizhannvshen": "Bellona",
    "fuchou": "Revenge",
    # Aquilifer's Ballade
    "tianhou_ghost": "Juno_ghost",
    "haiwangxing_ghost": "Neptune_ghost",
    "lemaer_ghost": "LeMars_ghost",
    "jingjishen_ghost": "Hermes_ghost",
    "qiubite_ghost": "Jupiter_ghost",
    # Aquilifer's Ballade
    "z46": "Z46",
    "haiyinlixi": "PrinzHeinrich",
    "qibolin": "GrafZeppelin",
    "magedebao": "Magdeburg",
    "adaerbote": "PrinzAdalbert",
    "weixi": "Weser",
    "wuerlixi": "UlrichVonHutten",
    # Violet Tempest Blooming Lycoris
    "ruoyue": "Wakaba",
    "liangyue": "Suzutsuki",
    "shenxue": "Miyuki",
    "qifeng": "Hatakaze",
    "yuhei": "Haguro",
    "birui": "Hiei",
    "zhenming": "Haruna",
    "chicheng": "Akagi",
    "jiahe": "Kaga",
    "sanli": "Mikasa",
    "changmen": "Nagato",
    "jiuyun": "Sakawa",
    "qiansui": "Chitose",
    "qiandaitian": "Chiyoda",
    "longfeng": "Ryuuhou",
    "chunyue": "Harutsuki",
    "jiangfeng": "Kawakaze",
    # The Alchemist and the Archipelago of Secrets
    "lianjin_sairenquzhu": "DDalchemist",
    "lianjin_sairenqingxun": "CLalchemist",
    "lianjin_sairenzhongxun": "CAalchemist",
    "lianjin_sairenzhanlie": "BBalchemist",
    "lianjin_sairenhangmu": "CValchemist",
    # Parallel Superimposition
    "sairenboss15": "SirenBoss15",
    "sairenboss16": "SirenBoss16",
    # Revelations of Dust
    "xiafei": "Joffre",
    "lemaer": "LeMars",
    # Confluence of Nothingness
    "shenyuanboss4": "AbyssalBoss4",
    "shenyuanboss4_alter": "AbyssalBoss4",
    "shenyuanboss5": "AbyssalBoss5",
    "shenyuanboss5_alter": "AbyssalBoss5",
    "sairenquzhu_m": "DD",
    "sairenqingxun_m": "CL",
    "sairenzhongxun_m": "CAred",
    "sairenzhanlie_m": "BBred",
    "sairenhangmu_m": "CV",
    "sairenqianting_m": "SS",
    # The Fool's Scales
    "sairenboss18": "SirenBoss18",
    "sairenboss19": "SirenBoss19",
    "srjiaohuangjijia": "Dilloy",
    # Effulgence Before Eclipse
    "chuyue": "Hatsuzuki",
    "zhaozhi": "Asanagi",
    "ruifeng": "Zuiho",
    "shanluan_sairenquzhu": "SK_DD",
    "shanluan_sairenqingxun": "SK_CL",
    "shanluan_sairenzhongxun": "SK_CA",
    "shanluan_sairenzhanlie": "SK_BB",
    "shanluan_sairenhangmu": "SK_CV",
    # Light-Chasing Sea of Stars
    "sairenboss10": "Sirenboss10",
    "UDFsairen_baolei_2": "UDFFortress2",
    # Heart-Linking Harmony
    "lafei_6": "Laffey6",
    "tashigan_idol": "TashkentIdol",
    "xiefeierde_idol": "SheffieldIdol",
    "yilishabai_3": "Elizabeth3",
    "jiasikenie_idol": "GascogneIdol",
    "dafeng_idol": "TaihouIdol",
    # Interlude of Illusions
    "tianlangxing": "Sirius",
    "daiduo": "Dido",
    "z23_g": "Z23_g",
    "laibixi_g": "Leipzig_g",
    "pangpeimagenuo": "PompeoMagno",
    "aerfuleiduo": "AlfredoOriani",
    "guogan": "LAudacieux",
    "dipulaikesi": "Dupleix",
    # Windborne Steel Wings
    "qinraozhe_IV": "Intruder",
    "tiancheng_m_quzhu": "AmagiMasked",
    "tiancheng_m_qingxun": "AmagiMasked",
    "tiancheng_m_zhongxun": "AmagiMasked",
    "tiancheng_m_zhanlie": "AmagiMasked",
    "tiancheng_m_hangmu": "AmagiMasked",
    # Tempesta and the Sleeping Sea
    "hemuhao": "Amity",
    "pucimaosi": "Portsmouth",
    "mali": "MaryCeleste",
    "fengfan_haigu03": "fengfanhaigu03",
    # Dangerous Inventions Incoming
    "tolove_renxing01": "ToLoveNana01",
    "tolove_renxing02": "ToLoveYui02",
    "tolove_renxing03": "ToLoveNana03",
    "tolove_renxing04": "ToLoveHaruna04",
    "tolove_renxing05": "ToLoveGoldenDarkness05",
    # Paradiso of Shackled Light
    "boerzhanuo_alter": "BolzanoAlter",
    "kaisa_alter": "CesareAlter",
    "teluntuo_alter": "TrentoAlter",
    "sairenboss26": "SirenBoss26",
    "sairenboss25": "SirenBoss25",
    # A Rose on the High Tower
    "shengli": "Victorious",
    "huangjiaxiangshu": "RoyalOak",
    # The Alchemist and the Tower of Horizons
    "lianjin_II_sairenquzhu": "DDalchemist2",
    "lianjin_II_sairenqingxun": "CLalchemist2",
    "lianjin_II_sairenzhongxun": "CAalchemist2",
    "lianjin_II_sairenzhanlie": "BBalchemist2",
    "lianjin_II_sairenhangmu": "CValchemist2",
    # Secrets of the Abyss
    "jiulaimu_ruanniguai": "Jiulaimu_Mud",
    "jiulaimu_shixianggui": "Jiulaimu_Statue",
    "jiulaimu_emo": "Jiulaimu_Demon",
    "youlin_ylsb": "Jiulaimu_Ghost",
    # A Note Through the Firmament
    "unknownV_boss_star": "Vboss_Star",
    "unknownV_boss_hermit": "Vboss_Hermit",
    "unknownV_boss_lovers": "Vboss_Lovers",
    "unknownV_boss_chariot": "Vboss_Chariot",
    # Vacation Lane – Beachside Brilliance (event_20260417_cn)
    "bulaimodun": "Bremerton",
    "fushun_g": "FuShunG",
    "lafeier": "Raffaello",
    "huangjiafangzhou_g": "ArkRoyalG",
    "chaijun": "Cheshire",
    "naximofu": "Nakhimov",
    "liekexingdunII": "Lexington2",
    "yuekechengII": "Yorktown2",
    # Miracle by Midnight
    "youeryuan_boss03": "MeowfficerBust_Playtime",
    "youeryuan_boss04": "MeowfficerBust_Hobbies",
    "youeryuan_boss05": "MeowfficerBust_Studying",
}


class MapData:
    dic_grid_info: ClassVar[dict[int, str]] = {
        0: "--",
        1: "SP",
        2: "MM",
        3: "MA",
        4: "Me",
        6: "ME",
        8: "MB",
        12: "MS",
        16: "__",
        100: "++",  # Dock in Empyreal Tragicomedy
    }

    def __init__(self, data: LuaTable, data_loop: LuaTable | None) -> None:
        self.data = data
        self.data_loop = data_loop
        map_context = f"chapter {data.get('id', '<unknown>')}"
        self.chapter_name = require_lua_str(data["chapter_name"], context=f"{map_context} chapter name").replace(
            "–", "-"
        )
        self.name = require_lua_str(data["name"], context=f"{map_context} name")
        self.profiles = data["profiles"]
        self.map_id = require_lua_int(data["id"], context=f"{map_context} id")

        try:
            self._set_event_enemy_data()
            self._set_spawn_data()
            self._set_map_data()
            self._set_portal_data()
            self._set_land_based_data()
            self._set_config_data()
        except Exception:
            for k, v in data.items():
                print(f"{k} = {v}")
            raise

    def __str__(self) -> str:
        return f"{self.map_id} {self.chapter_name} {self.name}"

    __repr__ = __str__

    def _set_event_enemy_data(self) -> None:
        self.event_enemy_data = None
        self.event_enemy_data_loop = None
        if self.map_id not in _LUA_DATA.map_event_list:
            return

        event_list = require_lua_table(_LUA_DATA.map_event_list[self.map_id], context=f"map {self.map_id} event list")
        event_data = require_lua_table(event_list["event_list"], context=f"map {self.map_id} event enemies")
        self.event_enemy_data = self.extract_event_enemy_data(event_data)
        if self.data_loop is not None:
            event_data_loop = require_lua_table(
                event_list["event_list_loop"], context=f"map {self.map_id} loop event enemies"
            )
            self.event_enemy_data_loop = self.extract_event_enemy_data(event_data_loop)

    def _set_spawn_data(self) -> None:
        self.spawn_data = self.parse_spawn_data(self.data, self.event_enemy_data)
        if self.data_loop is None:
            self.spawn_data_loop = None
            return

        self.spawn_data_loop = self.parse_spawn_data(self.data_loop, self.event_enemy_data_loop)
        if len(self.spawn_data) == len(self.spawn_data_loop) and all(
            s1 == s2 for s1, s2 in zip(self.spawn_data, self.spawn_data_loop, strict=True)
        ):
            self.spawn_data_loop = None

    def _set_map_data(self) -> None:
        grids = require_lua_table(self.data["grids"], context=f"map {self.map_id} grids")
        self.map_data = self.parse_map_data(grids, self.event_enemy_data)
        shape = np.max(list(self.map_data), axis=0)
        self.shape = (int(shape[0]), int(shape[1]))
        if self.data_loop is None:
            self.map_data_loop = None
            return

        loop_grids = require_lua_table(self.data_loop["grids"], context=f"map {self.map_id} loop grids")
        self.map_data_loop = self.parse_map_data(loop_grids, self.event_enemy_data_loop)
        if all(d1 == d2 for d1, d2 in zip(self.map_data.values(), self.map_data_loop.values(), strict=True)):
            self.map_data_loop = None

    def _set_portal_data(self) -> None:
        self.portal: list[tuple[str, str]] = []

    def _set_land_based_data(self) -> None:
        land_based_rotation_dict = {1: "up", 2: "down", 3: "left", 4: "right"}
        self.land_based: list[list[str]] = []
        land_based = self.data["land_based"]
        if not isinstance(land_based, dict):
            return

        for land_based_value in land_based.values():
            entry = require_lua_table(land_based_value, context=f"map {self.map_id} land-based entry")
            values = list(entry.values())
            if len(values) != 3:
                message = f"map {self.map_id} land-based entry must contain y, x, and rotation"
                raise ValueError(message)
            y = require_lua_int(values[0], context=f"map {self.map_id} land-based y")
            x = require_lua_int(values[1], context=f"map {self.map_id} land-based x")
            rotation = require_lua_int(values[2], context=f"map {self.map_id} land-based rotation")
            if rotation not in land_based_rotation_dict:
                continue
            self.land_based.append([location2node((x, y)), land_based_rotation_dict[rotation]])

    def _iter_siren_ids(self) -> Iterator[int]:
        # 部分活动的普通/循环模式海妖配置不同，需要合并。
        siren_table = require_lua_table(
            self.data["ai_expedition_list"], context=f"map {self.map_id} siren expedition list"
        )
        sirens = list(siren_table.values())
        if self.data_loop is not None:
            loop_value = self.data_loop["ai_expedition_list"]
            if loop_value is not None:
                loop_sirens = require_lua_table(loop_value, context=f"map {self.map_id} loop siren expedition list")
                sirens.extend(loop_sirens.values())
        for siren_id in sirens:
            yield require_lua_int(siren_id, context=f"map {self.map_id} siren id")

    def _add_siren_config(self, siren_id: int) -> None:
        if siren_id == 1:
            return

        exped_data = require_lua_table(_LUA_DATA.expectation.get(siren_id, {}), context=f"siren expedition {siren_id}")
        icon = exped_data.get("icon")
        name = str(siren_id) if icon is None else require_lua_str(icon, context=f"siren expedition {siren_id} icon")
        name = DIC_SIREN_NAME_CHI_TO_ENG.get(name, name)
        if name not in self.MAP_SIREN_TEMPLATE:
            self.MAP_SIREN_TEMPLATE.append(name)
        self.MOVABLE_ENEMY_TURN.add(
            require_lua_int(exped_data.get("ai_mov", 2), context=f"siren expedition {siren_id} movement")
        )

    def _set_config_data(self) -> None:
        self.MAP_SIREN_TEMPLATE: list[str] = []
        self.MOVABLE_ENEMY_TURN: set[int] = set()
        for siren_id in self._iter_siren_ids():
            self._add_siren_config(siren_id)

        self.MAP_HAS_MOVABLE_ENEMY = bool(self.MOVABLE_ENEMY_TURN)
        self.MAP_HAS_MAP_STORY = bool(self.data["story_refresh_boss"])
        self.MAP_HAS_FLEET_STEP = bool(self.data["is_limit_move"])
        self.MAP_HAS_AMBUSH = bool(self.data["is_ambush"]) or bool(self.data["is_air_attack"])
        self.MAP_HAS_MYSTERY = sum(b.get("mystery", 0) for b in self.spawn_data) > 0
        self.MAP_HAS_PORTAL = bool(self.portal)
        self.MAP_HAS_LAND_BASED = bool(self.land_based)
        for number in range(1, 4):
            requirement = require_lua_int(
                self.data[f"star_require_{number}"], context=f"map {self.map_id} star requirement {number}"
            )
            setattr(self, f"STAR_REQUIRE_{number}", requirement)

    def parse_map_data(
        self, grids: LuaTable, event_enemy_data: list[LuaTable] | None = None
    ) -> dict[GridLocation, str]:
        map_data: dict[GridLocation, str] = {}
        grid_rows = [require_lua_table(grid, context=f"map {self.map_id} grid") for grid in grids.values()]
        offset_y = min(require_lua_int(grid[0], context=f"map {self.map_id} grid y") for grid in grid_rows)
        offset_x = min(require_lua_int(grid[1], context=f"map {self.map_id} grid x") for grid in grid_rows)
        for grid in grid_rows:
            y = require_lua_int(grid[0], context=f"map {self.map_id} grid y")
            x = require_lua_int(grid[1], context=f"map {self.map_id} grid x")
            is_land = require_lua_int(grid[2], context=f"map {self.map_id} grid land flag")
            grid_type = require_lua_int(grid[3], context=f"map {self.map_id} grid type")
            loca = (x - offset_x, y - offset_y)
            info = "++" if not is_land else self.dic_grid_info.get(grid_type, "??")
            if info == "??":
                print(f"Unknown grid info. grid={location2node(loca)}, info={grid_type}")
            map_data[loca] = info
        if event_enemy_data is not None:
            for wave in event_enemy_data:
                for enemy_value in wave.values():
                    enemy = require_lua_table(enemy_value, context=f"map {self.map_id} event enemy")
                    position = require_lua_table(enemy[1], context=f"map {self.map_id} event enemy position")
                    enemy_y = require_lua_int(position[0], context=f"map {self.map_id} event enemy y")
                    enemy_x = require_lua_int(position[1], context=f"map {self.map_id} event enemy x")
                    loca = (enemy_x - offset_x, enemy_y - offset_y)
                    map_data[loca] = "ME"

        return map_data

    @staticmethod
    def _add_spawn_count(spawn_data: list[SpawnRule], index: int, field: SpawnField, count: int) -> None:
        if count:
            spawn = spawn_data[index]
            spawn[field] = spawn.get(field, 0) + count

    @staticmethod
    def _add_refresh_counts(spawn_data: list[SpawnRule], refresh_data: LuaTable, field: SpawnField) -> None:
        for index, count in refresh_data.items():
            MapData._add_spawn_count(
                spawn_data,
                require_lua_int(index, context=f"{field} refresh battle"),
                field,
                require_lua_int(count, context=f"{field} refresh count"),
            )

    @staticmethod
    def _get_battle_count(data: LuaTable) -> int:
        enemy_refresh = require_lua_table(data["enemy_refresh"], context="enemy refresh")
        try:
            enemy_refresh_max = max(require_lua_int(index, context="enemy refresh battle") for index in enemy_refresh)
        except ValueError:
            return 0
        boss_refresh = require_lua_int(data["boss_refresh"], context="boss refresh")
        return max(boss_refresh, enemy_refresh_max)

    @staticmethod
    def parse_spawn_data(data: LuaTable, event_enemy_data: list[LuaTable] | None = None) -> list[SpawnRule]:
        battle_count = MapData._get_battle_count(data)
        spawn_data = [{"battle": index} for index in range(battle_count + 1)]

        enemy_refresh = require_lua_table(data["enemy_refresh"], context="enemy refresh")
        MapData._add_refresh_counts(spawn_data, enemy_refresh, "enemy")
        if event_enemy_data is not None:
            for index, wave in enumerate(event_enemy_data):
                if isinstance(wave, Sized):
                    MapData._add_spawn_count(spawn_data, index, "enemy", len(wave))
        elite_refresh = require_lua_table(data["elite_refresh"], context="elite refresh")
        if "".join([str(item) for item in elite_refresh.values()]) != "100":  # 部分原始数据有误。
            MapData._add_refresh_counts(spawn_data, elite_refresh, "enemy")
        ai_refresh = require_lua_table(data["ai_refresh"], context="siren refresh")
        MapData._add_refresh_counts(spawn_data, ai_refresh, "siren")
        box_refresh = require_lua_table(data["box_refresh"], context="mystery refresh")
        MapData._add_refresh_counts(spawn_data, box_refresh, "mystery")
        boss_refresh = require_lua_int(data["boss_refresh"], context="boss refresh")
        with suppress(IndexError):
            spawn_data[boss_refresh]["boss"] = 1

        return spawn_data

    @staticmethod
    def extract_event_enemy_data(data: LuaTable) -> list[LuaTable]:
        extracted_data: list[LuaTable] = []
        for event_id_value in data.values():
            event_id = require_lua_int(event_id_value, context="map event id")
            event = require_lua_table(_LUA_DATA.map_event_template[event_id], context=f"map event {event_id}")
            effects = require_lua_table(event["effect"], context=f"map event {event_id} effects")
            for effect_value in effects.values():
                effect = require_lua_table(effect_value, context=f"map event {event_id} effect")
                if require_lua_str(effect[0], context=f"map event {event_id} effect type") != "enemy":
                    continue
                extracted_data.append(require_lua_table(effect[1], context=f"map event {event_id} enemy wave"))
        return extracted_data

    def stage_file_name(self) -> str:
        name = self.chapter_name.replace("-", "_").lower()
        if name[0].isdigit():
            name = f"campaign_{name}"
        return name + ".yaml"

    def _get_map_data_rows(self) -> list[str]:
        return [
            "    " + " ".join(self.map_data.get((x, y), "??") for x in range(self.shape[0] + 1))
            for y in range(self.shape[1] + 1)
        ]

    def _get_map_data_loop_rows(self) -> list[str]:
        map_data_loop = self.map_data_loop
        if map_data_loop is None:
            return []
        return [
            "    " + " ".join(map_data_loop[(x, y)] for x in range(self.shape[0] + 1)) for y in range(self.shape[1] + 1)
        ]

    def _stage_map_document(self) -> dict[str, StageValue]:
        camera_data = camera_2d(_active_area(self.map_data), sight=(-3, -1, 3, 2))
        camera_sp = camera_spawn_point(
            camera_data,
            sp_list=[key for key, value in self.map_data.items() if value == "SP"],
        )
        document: dict[str, StageValue] = {
            "name": self.chapter_name,
            "shape": location2node(self.shape),
            "camera_data": [location2node(location) for location in camera_data],
            "camera_data_spawn_point": [location2node(location) for location in camera_sp],
            "map_data": _LiteralString("\n".join(row.strip() for row in self._get_map_data_rows())),
            "weight_data": _LiteralString(
                "\n".join(" ".join(["50"] * (self.shape[0] + 1)) for _row in range(self.shape[1] + 1))
            ),
            "spawn_data": self.spawn_data,
        }
        if self.MAP_HAS_PORTAL:
            document["portal_data"] = self.portal
        if self.map_data_loop is not None:
            document["map_data_loop"] = _LiteralString("\n".join(row.strip() for row in self._get_map_data_loop_rows()))
        if self.MAP_HAS_LAND_BASED:
            document["land_based_data"] = self.land_based
        if self.spawn_data_loop is not None:
            document["spawn_data_loop"] = self.spawn_data_loop
        return document

    def _stage_config_document(self) -> dict[str, StageValue]:
        document: dict[str, StageValue] = {}
        if self.MAP_SIREN_TEMPLATE:
            document["MAP_SIREN_TEMPLATE"] = list(self.MAP_SIREN_TEMPLATE)
            document["MAP_HAS_SIREN"] = True
        document["MAP_HAS_MAP_STORY"] = self.MAP_HAS_MAP_STORY
        document["MAP_HAS_FLEET_STEP"] = self.MAP_HAS_FLEET_STEP
        document["MAP_HAS_AMBUSH"] = self.MAP_HAS_AMBUSH
        document["MAP_HAS_MYSTERY"] = self.MAP_HAS_MYSTERY
        if self.MAP_HAS_PORTAL:
            document["MAP_HAS_PORTAL"] = True
        if self.MAP_HAS_LAND_BASED:
            document["MAP_HAS_LAND_BASED"] = True
        for number in range(1, 4):
            requirement = getattr(self, f"STAR_REQUIRE_{number}")
            if requirement != number:
                document[f"STAR_REQUIRE_{number}"] = 0
        return document

    def _stage_battle_document(self) -> BattleDocument:
        declared_boss = require_lua_int(self.data["boss_refresh"], context=f"map {self.chapter_name} boss refresh")
        boss_battles = tuple(item["battle"] for item in self.spawn_data if item.get("boss") == 1)
        if not boss_battles:
            return {}
        if len(boss_battles) != 1 or boss_battles[0] != declared_boss:
            message = f"map {self.chapter_name} boss refresh does not match spawn data"
            raise ValueError(message)
        boss_battle = boss_battles[0]
        preserve = boss_battle - 5 if boss_battle >= 5 else 0
        clear_steps: list[StageValue] = []
        if self.MAP_SIREN_TEMPLATE:
            clear_steps.append({"tag": "clear_siren"})
        clear_steps.extend(
            (
                {"tag": "clear_filtered_enemy", "preserve": preserve},
                {"tag": "default_battle"},
            )
        )
        battles: BattleDocument = {}
        if boss_battle > 0:
            battles[0] = {"steps": clear_steps}
        if boss_battle >= 6:
            battle_five_steps: list[StageValue] = []
            if self.MAP_SIREN_TEMPLATE:
                battle_five_steps.append({"tag": "clear_siren"})
            battle_five_steps.extend(
                (
                    {"tag": "clear_filtered_enemy", "preserve": 0},
                    {"tag": "default_battle"},
                )
            )
            battles[5] = {"steps": battle_five_steps}
        battles[boss_battle] = {"steps": [{"tag": "clear_boss", "strategy": "fleet_boss"}]}
        return battles

    def _stage_mechanics_document(self) -> dict[str, StageValue]:
        return {
            "roadblocks": [],
            "fleet_coordination": [],
            "pickups": [],
            "map_interactions": [],
            "moving_enemies": {
                "turns": sorted(self.MOVABLE_ENEMY_TURN) if self.MAP_HAS_MOVABLE_ENEMY else [],
                "wait_until_clear": False,
                "initial_enemy_cells": [],
                "initial_siren_cells": [],
            },
            "enemy_movement": [],
            "procedures": [],
            "map_structures": {
                "walls": [],
                "maze_groups": [],
                "fortress_enemy_cells": [],
                "fortress_block_cells": [],
                "bouncing_enemy_routes": [],
            },
        }

    def stage_document(self) -> dict[str, StageValue]:
        return {
            "schema_version": 6,
            "map": self._stage_map_document(),
            "config": self._stage_config_document(),
            "enemy_filter": ENEMY_FILTER,
            "battles": self._stage_battle_document(),
            "mechanics": self._stage_mechanics_document(),
            "programs": [],
            "boss_approaches": [],
            "hard_mode": None,
        }

    def render_stage_yaml(self) -> str:
        return yaml.dump(
            self.stage_document(),
            Dumper=_StageDumper,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )

    def write_stage(
        self,
        path: FilePath,
        *,
        overwrite: bool = False,
        check: bool = False,
    ) -> bool:
        file = Path(path) / self.stage_file_name()
        content = self.render_stage_yaml()
        if check:
            return file.is_file() and file.read_text(encoding="utf-8") == content
        if file.exists() and not overwrite:
            print(f"File exists: {file}")
            return False
        file.parent.mkdir(parents=True, exist_ok=True)
        print(f"Extract: {file}")
        file.write_text(content, encoding="utf-8", newline="\n")
        return True


class ChapterTemplate:
    def __init__(self) -> None:
        pass

    @staticmethod
    def _is_extra_chapter(name: str) -> bool:
        name = name.lower().replace(".", "")
        return name in ["extra", "ex"]

    @staticmethod
    def _get_event_id(map_id: int) -> int:
        return (map_id - 2100000) // 20 + 21000 if map_id // 10000 == 210 else map_id // 10000

    @staticmethod
    def _iter_chapter_data() -> Iterator[tuple[int, LuaTable]]:
        for map_id, raw_value in _LUA_DATA.chapter.items():
            if not isinstance(map_id, int):
                continue
            raw_data = require_lua_table(raw_value, context=f"chapter {map_id}")
            chapter_name = require_lua_str(raw_data["chapter_name"], context=f"chapter {map_id} name")
            if ChapterTemplate._is_extra_chapter(chapter_name):
                continue
            yield map_id, raw_data

    @staticmethod
    def _create_map_data(map_id: int, raw_data: LuaTable) -> MapData:
        loop_data = _optional_lua_table(_LUA_DATA.chapter_loop.get(map_id), context=f"chapter {map_id} loop")
        return MapData(raw_data, loop_data)

    def _find_maps_by_name(self, name: str) -> list[MapData]:
        maps: list[MapData] = []
        for map_id, raw_data in self._iter_chapter_data():
            map_name = require_lua_str(raw_data["name"], context=f"chapter {map_id} name")
            if not re.search(name, map_name):
                continue
            data = self._create_map_data(map_id, raw_data)
            print(f"Found map: {data}")
            maps.append(data)
        return maps

    @staticmethod
    def _find_maps_by_id(map_id: int) -> list[MapData]:
        raw_data = require_lua_table(_LUA_DATA.chapter[map_id], context=f"chapter {map_id}")
        loop_data = _optional_lua_table(_LUA_DATA.chapter_loop.get(map_id), context=f"chapter {map_id} loop")
        data = MapData(raw_data, loop_data)
        print(f"Found map: {data}")
        return [data]

    def _select_event_maps(self, map_id: int) -> list[MapData]:
        event_id = self._get_event_id(map_id)
        maps: list[MapData] = []
        for current_map_id, raw_data in self._iter_chapter_data():
            current_event_id = require_lua_int(raw_data["id"], context=f"chapter {current_map_id} id")
            if self._get_event_id(current_event_id) != event_id:
                continue
            data = self._create_map_data(current_map_id, raw_data)
            print(f"Selected: {data}")
            maps.append(data)
        return maps

    def _select_maps(self, maps: Sequence[MapData], *, select: bool) -> list[MapData]:
        print("<<< SELECT MAP >>>")
        if select:
            selected_maps = self._select_event_maps(maps[0].map_id)
        else:
            selected_maps = list(maps[:1])
            print(f"Selected: {selected_maps[0]}")
        print()
        return selected_maps

    def _find_maps(self, name: str | int) -> list[MapData]:
        if isinstance(name, str):
            return self._find_maps_by_name(name)
        return self._find_maps_by_id(name)

    def get_chapter_by_name(self, name: str, *, select: bool = False) -> list[MapData]:
        """按字符串关键词或数字字符串查找地图。

        地图 ID 例如 11004（第 10 章困难 4 图）和 1140017（活动图 D2）。
        `name` 会先调用 `strip()`，不能传入整数；数字字符串按地图 ID 解析。
        `select=False` 仅取首个命中，`select=True` 选取同活动全部地图。
        """
        print("<<< SEARCH MAP >>>")
        normalized_name = name.strip()
        query: str | int = int(normalized_name) if normalized_name.isdigit() else normalized_name
        print(f"Searching: {query}")
        maps = self._find_maps(query)

        if not maps:
            print("No maps found")
            return []
        print()

        return self._select_maps(maps, select=select)

    @staticmethod
    def extract(maps: Sequence[MapData], folder: FilePath) -> None:
        print("<<< CONFIRM >>>")
        print("Please confirm selected the correct maps before extracting.\nInput any key and press ENTER to continue")
        input()

        if not Path(folder).exists():
            Path(folder).mkdir()
        for data in maps:
            data.write_stage(folder, overwrite=OVERWRITE)


"""
这是用于抽取地图文件的开发工具。

先克隆 https://github.com/AzurLaneTools/AzurLaneLuaScripts 获取解密后的 Lua 脚本。
Arguments:
    FILE:            Lua 脚本仓库路径
    FOLDER:          保存目录，例如 PROJECT_ROOT / 'content/events/event_future_cn/stages'
    KEYWORD:         地图名称关键词，例如 '短兵相接'；也可以是地图 ID，例如 702
    SELECT:          是否选择同活动的全部地图
    OVERWRITE:       是否覆盖已有文件
"""


def main() -> None:
    loader = LuaLoader(FILE, server="CN")
    _LUA_DATA.chapter = loader.load("./sharecfgdata/chapter_template.lua")
    _LUA_DATA.chapter_loop = loader.load("./sharecfgdata/chapter_template_loop.lua")
    _LUA_DATA.map_event_list = loader.load("./sharecfg/map_event_list.lua")
    _LUA_DATA.map_event_template = loader.load("./sharecfg/map_event_template.lua")
    _LUA_DATA.expectation = loader.load("./sharecfgdata/expedition_data_template.lua")

    chapter = ChapterTemplate()
    chapter.extract(
        chapter.get_chapter_by_name(KEYWORD, select=SELECT),
        folder=FOLDER,
    )


if __name__ == "__main__":
    main()
