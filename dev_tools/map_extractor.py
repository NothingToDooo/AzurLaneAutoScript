import re
from collections.abc import Sized
from contextlib import suppress
from pathlib import Path
from typing import ClassVar

import numpy as np

import module.logger
from dev_tools.utils import LuaLoader
from module.base.utils import location2node
from module.map.utils import camera_2d, camera_spawn_point, get_map_active_area

# 导入 module.logger 会切换到项目根目录。
_ = module.logger

"""
This an auto-tool to extract map files used in Alas.
"""

DIC_SIREN_NAME_CHI_TO_ENG = {
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
        4: "Me",  # This grid 100% spawn enemy?
        6: "ME",
        8: "MB",
        12: "MS",
        16: "__",
        100: "++",  # Dock in Empyreal Tragicomedy
    }

    def __init__(self, data, data_loop):
        self.data = data
        self.data_loop = data_loop
        self.chapter_name = data["chapter_name"].replace("–", "-")
        self.name = data["name"]
        self.profiles = data["profiles"]
        self.map_id = data["id"]

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

    def __str__(self):
        return f"{self.map_id} {self.chapter_name} {self.name}"

    __repr__ = __str__

    def _set_event_enemy_data(self):
        self.event_enemy_data = None
        self.event_enemy_data_loop = None
        if self.map_id not in MAP_EVENT_LIST:
            return

        event_list = MAP_EVENT_LIST[self.map_id]
        self.event_enemy_data = self.extract_event_enemy_data(event_list["event_list"])
        if self.data_loop is not None:
            self.event_enemy_data_loop = self.extract_event_enemy_data(event_list["event_list_loop"])

    def _set_spawn_data(self):
        self.spawn_data = self.parse_spawn_data(self.data, self.event_enemy_data)
        if self.data_loop is None:
            self.spawn_data_loop = None
            return

        self.spawn_data_loop = self.parse_spawn_data(self.data_loop, self.event_enemy_data_loop)
        if len(self.spawn_data) == len(self.spawn_data_loop) and all(
            s1 == s2 for s1, s2 in zip(self.spawn_data, self.spawn_data_loop, strict=True)
        ):
            self.spawn_data_loop = None

    def _set_map_data(self):
        self.map_data = self.parse_map_data(self.data["grids"], self.event_enemy_data)
        self.shape = tuple(np.max(list(self.map_data.keys()), axis=0))
        if self.data_loop is None:
            self.map_data_loop = None
            return

        self.map_data_loop = self.parse_map_data(self.data_loop["grids"], self.event_enemy_data_loop)
        if all(d1 == d2 for d1, d2 in zip(self.map_data.values(), self.map_data_loop.values(), strict=True)):
            self.map_data_loop = None

    def _set_portal_data(self):
        self.portal = []

    def _set_land_based_data(self):
        land_based_rotation_dict = {1: "up", 2: "down", 3: "left", 4: "right"}
        self.land_based = []
        if not isinstance(self.data["land_based"], dict):
            return

        for lb in self.data["land_based"].values():
            y, x, r = lb.values()
            if r not in land_based_rotation_dict:
                continue
            self.land_based.append([location2node((x, y)), land_based_rotation_dict[r]])

    def _iter_siren_ids(self):
        # 部分活动的普通/循环模式海妖配置不同，需要合并。
        sirens = list(self.data["ai_expedition_list"].values())
        if self.data_loop is not None and self.data_loop["ai_expedition_list"] is not None:
            sirens += list(self.data_loop["ai_expedition_list"].values())
        return sirens

    def _add_siren_config(self, siren_id):
        if siren_id == 1:
            return

        exped_data = EXPECTATION_DATA.get(siren_id, {})
        name = exped_data.get("icon", str(siren_id))
        name = DIC_SIREN_NAME_CHI_TO_ENG.get(name, name)
        if name not in self.MAP_SIREN_TEMPLATE:
            self.MAP_SIREN_TEMPLATE.append(name)
        self.MOVABLE_ENEMY_TURN.add(int(exped_data.get("ai_mov", 2)))

    def _set_config_data(self):
        self.MAP_SIREN_TEMPLATE = []
        self.MOVABLE_ENEMY_TURN = set()
        for siren_id in self._iter_siren_ids():
            self._add_siren_config(siren_id)

        self.MAP_HAS_MOVABLE_ENEMY = bool(self.MOVABLE_ENEMY_TURN)
        self.MAP_HAS_MAP_STORY = bool(self.data["story_refresh_boss"])
        self.MAP_HAS_FLEET_STEP = bool(self.data["is_limit_move"])
        self.MAP_HAS_AMBUSH = bool(self.data["is_ambush"]) or bool(self.data["is_air_attack"])
        self.MAP_HAS_MYSTERY = sum([b.get("mystery", 0) for b in self.spawn_data]) > 0
        self.MAP_HAS_PORTAL = bool(self.portal)
        self.MAP_HAS_LAND_BASED = bool(self.land_based)
        for n in range(1, 4):
            setattr(self, f"STAR_REQUIRE_{n}", self.data[f"star_require_{n}"])

    def parse_map_data(self, grids, event_enemy_data=None):
        map_data = {}
        offset_y = min([grid[0] for grid in grids.values()])
        offset_x = min([grid[1] for grid in grids.values()])
        for grid in grids.values():
            loca = (grid[1] - offset_x, grid[0] - offset_y)
            info = "++" if not grid[2] else self.dic_grid_info.get(grid[3], "??")
            if info == "??":
                print(f"Unknown grid info. grid={location2node(loca)}, info={grid[3]}")
            map_data[loca] = info
        if isinstance(event_enemy_data, list):
            for wave in event_enemy_data:
                for enemy in wave.values():
                    loca = (enemy[1][1] - offset_x, enemy[1][0] - offset_y)
                    map_data[loca] = "ME"

        return map_data

    @staticmethod
    def _add_spawn_count(spawn_data, index, field, count):
        if count:
            spawn = spawn_data[index]
            spawn[field] = spawn.get(field, 0) + count

    @staticmethod
    def _add_refresh_counts(spawn_data, refresh_data, field):
        for index, count in refresh_data.items():
            MapData._add_spawn_count(spawn_data, index, field, count)

    @staticmethod
    def _get_battle_count(data):
        try:
            enemy_refresh_max = max(data["enemy_refresh"].keys())
        except ValueError:
            return 0
        return max(data["boss_refresh"], enemy_refresh_max)

    @staticmethod
    def parse_spawn_data(data, event_enemy_data=None):
        battle_count = MapData._get_battle_count(data)
        spawn_data = [{"battle": index} for index in range(battle_count + 1)]

        MapData._add_refresh_counts(spawn_data, data["enemy_refresh"], "enemy")
        if isinstance(event_enemy_data, list):
            for index, wave in enumerate(event_enemy_data):
                if isinstance(wave, Sized):
                    MapData._add_spawn_count(spawn_data, index, "enemy", len(wave))
        if "".join([str(item) for item in data["elite_refresh"].values()]) != "100":  # 部分原始数据有误。
            MapData._add_refresh_counts(spawn_data, data["elite_refresh"], "enemy")
        MapData._add_refresh_counts(spawn_data, data["ai_refresh"], "siren")
        MapData._add_refresh_counts(spawn_data, data["box_refresh"], "mystery")
        with suppress(IndexError):
            spawn_data[data["boss_refresh"]]["boss"] = 1

        return spawn_data

    def extract_event_enemy_data(self, data):
        extracted_data = []
        for event_id in data.values():
            event = MAP_EVENT_TEMPLATE[event_id]
            extracted_data.extend(effect[1] for effect in event["effect"].values() if effect[0] == "enemy")
        return extracted_data

    def map_file_name(self):
        name = self.chapter_name.replace("-", "_").lower()
        if name[0].isdigit():
            name = f"campaign_{name}"
        return name + ".py"

    def _get_base_import(self, has_modified_campaign_base):
        if IS_WAR_ARCHIVES:
            return "from ..campaign_war_archives.campaign_base import CampaignBase"
        if has_modified_campaign_base:
            return "from .campaign_base import CampaignBase"
        return "from module.campaign.campaign_base import CampaignBase"

    def _get_import_lines(self, has_modified_campaign_base):
        lines = [
            self._get_base_import(has_modified_campaign_base),
            "from module.map.map_base import CampaignMap",
        ]
        if self.chapter_name[-1].isdigit():
            chap, stage = self.chapter_name[:-1], self.chapter_name[-1]
            if stage != "1":
                lines.append(f"from .{chap.lower()}1 import Config as ConfigBase")
        lines.append("")
        return lines

    def _get_map_data_rows(self):
        return [
            "    " + " ".join(self.map_data.get((x, y), "??") for x in range(self.shape[0] + 1))
            for y in range(self.shape[1] + 1)
        ]

    def _get_map_data_loop_rows(self):
        map_data_loop = self.map_data_loop
        if map_data_loop is None:
            return []
        return [
            "    " + " ".join(map_data_loop[(x, y)] for x in range(self.shape[0] + 1)) for y in range(self.shape[1] + 1)
        ]

    def _get_flatten_lines(self):
        return [
            *(
                ", ".join(location2node((x, y)) for x in range(self.shape[0] + 1)) + ", \\"
                for y in range(self.shape[1] + 1)
            ),
            "    = MAP.flatten()",
            "",
            "",
        ]

    def _get_map_lines(self):
        lines = [
            f"MAP = CampaignMap('{self.chapter_name}')",
            f"MAP.shape = '{location2node(self.shape)}'",
        ]
        camera_data = camera_2d(get_map_active_area(self.map_data), sight=(-3, -1, 3, 2))
        lines.append(f"MAP.camera_data = {[location2node(loca) for loca in camera_data]}")
        camera_sp = camera_spawn_point(camera_data, sp_list=[k for k, v in self.map_data.items() if v == "SP"])
        lines.append(f"MAP.camera_data_spawn_point = {[location2node(loca) for loca in camera_sp]}")
        if self.MAP_HAS_PORTAL:
            lines.append(f"MAP.portal_data = {self.portal}")
        lines.append('MAP.map_data = """')
        lines.extend(self._get_map_data_rows())
        lines.append('"""')
        if self.map_data_loop is not None:
            lines.append('MAP.map_data_loop = """')
            lines.extend(self._get_map_data_loop_rows())
            lines.append('"""')
        lines.append('MAP.weight_data = """')
        lines.extend("    " + " ".join(["50"] * (self.shape[0] + 1)) for _y in range(self.shape[1] + 1))
        lines.append('"""')
        if self.MAP_HAS_LAND_BASED:
            lines.append(f"MAP.land_based_data = {self.land_based}")
        lines.append("MAP.spawn_data = [")
        lines.extend("    " + str(battle) + "," for battle in self.spawn_data)
        lines.append("]")
        if self.spawn_data_loop is not None:
            lines.append("MAP.spawn_data_loop = [")
            lines.extend("    " + str(battle) + "," for battle in self.spawn_data_loop)
            lines.append("]")
        lines.extend(self._get_flatten_lines())
        return lines

    def _get_config_class_line(self):
        if self.chapter_name[-1].isdigit():
            _chap, stage = self.chapter_name[:-1], self.chapter_name[-1]
            if stage != "1":
                return "class Config(ConfigBase):"
        return "class Config:"

    def _get_config_lines(self):
        lines = [
            self._get_config_class_line(),
            "    # ===== Start of generated config =====",
        ]
        if self.MAP_SIREN_TEMPLATE:
            lines.append(f"    MAP_SIREN_TEMPLATE = {self.MAP_SIREN_TEMPLATE}")
            lines.append(f"    MOVABLE_ENEMY_TURN = {tuple(self.MOVABLE_ENEMY_TURN)}")
            lines.append("    MAP_HAS_SIREN = True")
            lines.append(f"    MAP_HAS_MOVABLE_ENEMY = {self.MAP_HAS_MOVABLE_ENEMY}")
        lines.append(f"    MAP_HAS_MAP_STORY = {self.MAP_HAS_MAP_STORY}")
        lines.append(f"    MAP_HAS_FLEET_STEP = {self.MAP_HAS_FLEET_STEP}")
        lines.append(f"    MAP_HAS_AMBUSH = {self.MAP_HAS_AMBUSH}")
        lines.append(f"    MAP_HAS_MYSTERY = {self.MAP_HAS_MYSTERY}")
        if self.MAP_HAS_PORTAL:
            lines.append(f"    MAP_HAS_PORTAL = {self.MAP_HAS_PORTAL}")
        if self.MAP_HAS_LAND_BASED:
            lines.append(f"    MAP_HAS_LAND_BASED = {self.MAP_HAS_LAND_BASED}")
        lines.extend(
            f"    STAR_REQUIRE_{n} = 0" for n in range(1, 4) if self.__getattribute__(f"STAR_REQUIRE_{n}") != n
        )
        lines.append("    # ===== End of generated config =====")
        lines.append("")
        lines.append("")
        return lines

    def _get_clear_enemy_battle_lines(self, battle_name, preserve):
        lines = [f"    def {battle_name}(self):"]
        if self.MAP_SIREN_TEMPLATE:
            lines.append("        if self.clear_siren():")
            lines.append("            return True")
        lines.append(f"        if self.clear_filter_enemy(self.ENEMY_FILTER, preserve={preserve}):")
        lines.append("            return True")
        lines.append("")
        lines.append("        return self.battle_default()")
        lines.append("")
        return lines

    def _get_campaign_lines(self):
        battle = self.data["boss_refresh"]
        preserve = self.data["boss_refresh"] - 5 if battle >= 5 else 0
        lines = [
            "class Campaign(CampaignBase):",
            "    MAP = MAP",
            f"    ENEMY_FILTER = '{ENEMY_FILTER}'",
            "",
            *self._get_clear_enemy_battle_lines("battle_0", preserve=preserve),
        ]
        if battle >= 6:
            lines.extend(self._get_clear_enemy_battle_lines("battle_5", preserve=0))
        lines.append(f"    def battle_{self.data['boss_refresh']}(self):")
        if battle >= 5:
            lines.append("        return self.fleet_boss.clear_boss()")
        else:
            lines.append("        return self.clear_boss()")
        return lines

    def get_file_lines(self, has_modified_campaign_base):
        """生成地图文件源码行。

        Args:
            has_modified_campaign_base (bool): 目标目录是否有自定义 campaign_base.py。

        Returns:
            list(str): 地图文件的 Python 源码行。
        """
        return [
            *self._get_import_lines(has_modified_campaign_base),
            *self._get_map_lines(),
            *self._get_config_lines(),
            *self._get_campaign_lines(),
        ]

    def write(self, path):
        file = Path(path) / self.map_file_name()
        has_modified_campaign_base = Path(path, "campaign_base.py").exists()
        if has_modified_campaign_base:
            print("Using existing campaign_base.py")
        if Path(file).exists():
            if OVERWRITE:
                print(f"Delete file: {file}")
                Path(file).unlink()
            else:
                print(f"File exists: {file}")
                return False
        print(f"Extract: {file}")
        with file.open("w") as f:
            f.writelines(
                f"{text}\n" for text in self.get_file_lines(has_modified_campaign_base=has_modified_campaign_base)
            )
        return True


class ChapterTemplate:
    def __init__(self):
        pass

    @staticmethod
    def _is_extra_chapter(name):
        name = name.lower().replace(".", "")
        return name in ["extra", "ex"]

    @staticmethod
    def _get_event_id(map_id):
        return (map_id - 2100000) // 20 + 21000 if map_id // 10000 == 210 else map_id // 10000

    @staticmethod
    def _iter_chapter_data():
        for map_id, raw_data in DATA.items():
            if not isinstance(map_id, int) or ChapterTemplate._is_extra_chapter(raw_data["chapter_name"]):
                continue
            yield map_id, raw_data

    @staticmethod
    def _create_map_data(map_id, raw_data):
        return MapData(raw_data, DATA_LOOP.get(map_id, None))

    def _find_maps_by_name(self, name):
        maps = []
        for map_id, raw_data in self._iter_chapter_data():
            if not re.search(name, raw_data["name"]):
                continue
            data = self._create_map_data(map_id, raw_data)
            print(f"Found map: {data}")
            maps.append(data)
        return maps

    def _find_maps_by_id(self, map_id):
        data = MapData(DATA[map_id], DATA_LOOP.get(map_id, None))
        print(f"Found map: {data}")
        return [data]

    def _select_event_maps(self, map_id):
        event_id = self._get_event_id(map_id)
        maps = []
        for current_map_id, raw_data in self._iter_chapter_data():
            if self._get_event_id(raw_data["id"]) != event_id:
                continue
            data = self._create_map_data(current_map_id, raw_data)
            print(f"Selected: {data}")
            maps.append(data)
        return maps

    def _select_maps(self, maps, select):
        print("<<< SELECT MAP >>>")
        if select:
            selected_maps = self._select_event_maps(maps[0].map_id)
        else:
            selected_maps = maps[:1]
            print(f"Selected: {selected_maps[0]}")
        print()
        return selected_maps

    def _find_maps(self, name):
        if isinstance(name, str):
            return self._find_maps_by_name(name)
        return self._find_maps_by_id(name)

    def get_chapter_by_name(self, name, select=False):
        """按地图名关键词或地图 ID 查找地图。

        地图 ID 形如 11004 表示第 10 章困难 4 图，1140017 表示活动图 D2。

        Args:
            name (str, int): 地图名称关键词，例如 '短兵相接'；也可以是地图 ID，例如 702、1140017。
            select (bool): False 只抽取命中的第一张图，True 抽取同活动全部地图。

        Returns:
            list(MapData):
        """
        print("<<< SEARCH MAP >>>")
        name = name.strip()
        name = int(name) if name.isdigit() else name
        print(f"Searching: {name}")
        maps = self._find_maps(name)

        if not maps:
            print("No maps found")
            return []
        print()

        return self._select_maps(maps, select)

    def extract(self, maps, folder):
        """
        Args:
            maps (list[MapData]):
            folder (str):
        """
        print("<<< CONFIRM >>>")
        print("Please confirm selected the correct maps before extracting.\nInput any key and press ENTER to continue")
        input()

        if not Path(folder).exists():
            Path(folder).mkdir()
        for data in maps:
            data.write(folder)


"""
这是用于抽取地图文件的开发工具。

先克隆 https://github.com/AzurLaneTools/AzurLaneLuaScripts 获取解密后的 Lua 脚本。
Arguments:
    FILE:            Lua 脚本仓库路径
    FOLDER:          保存目录，例如 './campaign/test'
    KEYWORD:         地图名称关键词，例如 '短兵相接'；也可以是地图 ID，例如 702
    SELECT:          是否选择同活动的全部地图
    OVERWRITE:       是否覆盖已有文件
    IS_WAR_ARCHIVES: 是否按作战档案用法适配
"""
FILE = "../AzurLaneLuaScripts"
FOLDER = "./campaign/event_20260417_cn"
KEYWORD = "2020001"
SELECT = True
OVERWRITE = True
IS_WAR_ARCHIVES = False
ENEMY_FILTER = "1L > 1M > 1E > 1C > 2L > 2M > 2E > 2C > 3L > 3M > 3E > 3C"

LOADER = LuaLoader(FILE, server="CN")
DATA = LOADER.load("./sharecfgdata/chapter_template.lua")
DATA_LOOP = LOADER.load("./sharecfgdata/chapter_template_loop.lua")
MAP_EVENT_LIST = LOADER.load("./sharecfg/map_event_list.lua")
MAP_EVENT_TEMPLATE = LOADER.load("./sharecfg/map_event_template.lua")
EXPECTATION_DATA = LOADER.load("./sharecfgdata/expedition_data_template.lua")

ct = ChapterTemplate()
ct.extract(ct.get_chapter_by_name(KEYWORD, select=SELECT), folder=FOLDER)
