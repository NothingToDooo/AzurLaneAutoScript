import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dev_tools.utils import LuaLoader, require_lua_int, require_lua_str, require_lua_table

if TYPE_CHECKING:
    from collections.abc import Iterable

    from dev_tools.slpp import LuaTable
    from module.base.type_alias import FilePath
    from module.research.types import ResearchProjectData

type InputKeyword = Literal["need_coin", "need_cube", "need_part"]
type EncodedValue = str | int | bool


class Item:
    def __init__(self, data: LuaTable) -> None:
        """按 Lua 三元组的值顺序读取：类型标记、物品 ID、数量。"""
        self.name = ""
        values = list(data.values())
        if len(values) != 3:
            message = f"research item must contain exactly three values: {data!r}"
            raise ValueError(message)
        self.id = require_lua_int(values[1], context="research item id")
        self.amount = require_lua_int(values[2], context="research item amount")
        if self.id == 1:
            self.id = 59001  # 物资在 technology_data_template 里是 1，在 item_data_statistics 里是 59001。

    def __str__(self) -> str:
        return f"{self.name}({self.id}) x {self.amount}"


INPUT_KEYWORDS: dict[InputKeyword, tuple[str, str]] = {
    "need_coin": ("物资", "coin"),
    "need_cube": ("心智魔方", "cube"),
    "need_part": ("部件", "part"),
}

DR_SHIP = {
    "azuma",
    "friedrich",
    "drake",
    "hakuryu",
    "agir",
    "plymouth",
    "brest",
    "kearsarge",
    "hindenburg",
    "napoli",
    "nakhimov",
    "goudenleeuw",
    "mecklenburg",
    "valparaiso",
    "maximmelmann",
}

SHIP_KEYWORDS = {
    "海王星": "neptune",
    "neptune": "neptune",
    "君主": "monarch",
    "monarch": "monarch",
    "伊吹": "ibuki",
    "ibuki": "ibuki",
    "出云": "izumo",
    "izumo": "izumo",
    "罗恩": "roon",
    "roon": "roon",
    "路易九世": "saintlouis",
    "圣路易斯": "saintlouis",
    "saintlouis": "saintlouis",
    "西雅图": "seattle",
    "seattle": "seattle",
    "佐治亚": "georgia",
    "georgia": "georgia",
    "北风": "kitakaze",
    "kitakaze": "kitakaze",
    "吾妻": "azuma",
    "azuma": "azuma",
    "腓特烈大帝": "friedrich",
    "friedrich": "friedrich",
    "加斯科涅": "gascogne",
    "gascogne": "gascogne",
    "香槟": "champagne",
    "champagne": "champagne",
    "柴郡": "cheshire",
    "cheshire": "cheshire",
    "德雷克": "drake",
    "drake": "drake",
    "美因茨": "mainz",
    "mainz": "mainz",
    "奥丁": "odin",
    "odin": "odin",
    "安克雷奇": "anchorage",
    "anchorage": "anchorage",
    "{namecode:204}": "hakuryu",
    "白龙": "hakuryu",
    "hakuryu": "hakuryu",
    "埃吉尔": "agir",
    "agir": "agir",
    "奥古斯特·冯·帕塞瓦尔": "august",
    "august": "august",
    "马可波罗": "marcopolo",
    "marcopolo": "marcopolo",
    "普利茅斯": "plymouth",
    "plymouth": "plymouth",
    "鲁普雷希特": "rupprecht",
    "rupprecht": "rupprecht",
    "哈尔滨": "harbin",
    "harbin": "harbin",
    "契卡洛夫": "chkalov",
    "chkalov": "chkalov",
    "布雷斯特": "brest",
    "brest": "brest",
    "奇尔沙治": "kearsarge",
    "kearsarge": "kearsarge",
    "兴登堡": "hindenburg",
    "hindenburg": "hindenburg",
    "四万十": "shimanto",
    "shimanto": "shimanto",
    "舒尔茨": "schultz",
    "schultz": "schultz",
    "弗兰德尔": "flandre",
    "flandre": "flandre",
    "那不勒斯": "napoli",
    "napoli": "napoli",
    "纳希莫夫": "nakhimov",
    "nakhimov": "nakhimov",
    "哈尔福德": "halford",
    "halford": "halford",
    "巴亚德": "bayard",
    "bayard": "bayard",
    "大山": "daisen",
    "daisen": "daisen",
    "金狮": "goudenleeuw",
    "goudenleeuw": "goudenleeuw",
    "梅克伦堡": "mecklenburg",
    "mecklenburg": "mecklenburg",
    "德米特里": "dmitri",
    "dmitri": "dmitri",
    "堪萨斯": "kansas",
    "kansas": "kansas",
    "维托里奥": "vittorio",
    "vittorio": "vittorio",
    "瓦尔帕莱索": "valparaiso",
    "valparaiso": "valparaiso",
    "{namecode:565}": "maximmelmann",
    "maximmelmann": "maximmelmann",
    "邓肯": "duncan",
    "duncan": "duncan",
    "{namecode:313}": "takahashi",
    "takahashi": "takahashi",
    "暴风雨": "orage",
    "orage": "orage",
}

EQUIPMENT_AMOUNT = re.compile(r"(?:拆解|分解|Scrap)\D*(8|15)\D*(?:件装备|pieces? of gear)", re.IGNORECASE)


def normalize_name(name: str) -> str:
    return name.replace(" ", "").lower()


def project_consumption(items: Iterable[Item]) -> dict[InputKeyword, bool]:
    data: dict[InputKeyword, bool] = {}
    for item in items:
        name = normalize_name(item.name)
        for key, keywords in INPUT_KEYWORDS.items():
            if any(normalize_name(keyword) in name for keyword in keywords):
                data[key] = True
    return data


def project_ship(items: Iterable[Item]) -> str:
    for item in items:
        name = normalize_name(item.name)
        for keyword, ship in SHIP_KEYWORDS.items():
            if normalize_name(keyword) in name:
                return ship
    return ""


def equipment_amount(task: str) -> int:
    result = EQUIPMENT_AMOUNT.search(task)
    return int(result.group(1)) if result else 0


def encode_value(value: EncodedValue) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def encode_project(data: ResearchProjectData) -> list[str]:
    lines = [
        "    {",
        f'        "name": {encode_value(data["name"])},',
        f'        "series": {encode_value(data["series"])},',
        f'        "time": {encode_value(data["time"])},',
    ]
    lines.extend(
        f'        "{key}": {encode_value(data[key])},' for key in ("need_coin", "need_cube", "need_part") if key in data
    )
    if "ship" in data:
        lines.append(f'        "ship": {encode_value(data["ship"])},')
    if "ship_rarity" in data:
        lines.append(f'        "ship_rarity": {encode_value(data["ship_rarity"])},')
    if "equipment_amount" in data:
        lines.append(f'        "equipment_amount": {encode_value(data["equipment_amount"])},')
    lines.append("    },")
    return lines


class Project:
    def __init__(self, data: LuaTable) -> None:
        self.name = require_lua_str(data["name"], context="research project name")
        self.series = require_lua_int(data["blueprint_version"], context=f"research project {self.name} series")
        self.time = require_lua_int(data["time"], context=f"research project {self.name} time")
        consume = require_lua_table(data["consume"], context=f"research project {self.name} consumption")
        drop_client = require_lua_table(data["drop_client"], context=f"research project {self.name} output")
        self.input = [
            Item(require_lua_table(item, context=f"research project {self.name} input item"))
            for item in consume.values()
        ]
        self.output = [
            Item(require_lua_table(item, context=f"research project {self.name} output item"))
            for item in drop_client.values()
        ]
        self.task_id = require_lua_int(data["condition"], context=f"research project {self.name} task id")
        self.task = ""

    def encode(self) -> ResearchProjectData:
        data: ResearchProjectData = {
            "name": self.name,
            "series": self.series,
            "time": self.time,
        }
        consumption = project_consumption(self.input)
        if consumption.get("need_coin"):
            data["need_coin"] = True
        if consumption.get("need_cube"):
            data["need_cube"] = True
        if consumption.get("need_part"):
            data["need_part"] = True
        ship = project_ship(self.output)
        if ship:
            data["ship"] = ship
            data["ship_rarity"] = "dr" if ship in DR_SHIP else "pry"
        amount = equipment_amount(self.task)
        if amount:
            data["equipment_amount"] = amount
        return data


class TechnologyTemplate:
    def __init__(self) -> None:
        self.projects = self.load_projects(LuaLoader(FOLDER, server="zh-CN"))

    @staticmethod
    def load_projects(loader: LuaLoader) -> dict[tuple[int, str], Project]:
        tech = loader.load("sharecfg/technology_data_template.lua")
        item = loader.load("sharecfgdata/item_data_statistics.lua")
        virtual_item = loader.load("sharecfgdata/item_virtual_data_statistics.lua")
        item.update(virtual_item)
        task = loader.load("sharecfgdata/task_data_template.lua")

        projects: dict[tuple[int, str], Project] = {}
        for tech_key, value in tech.items():
            if tech_key == "all":
                continue
            project_data = require_lua_table(value, context=f"research project {tech_key}")
            project = Project(project_data)
            if project.task_id:
                task_data = require_lua_table(task[project.task_id], context=f"research task {project.task_id}")
                project.task = require_lua_str(
                    task_data["desc"], context=f"research task {project.task_id} description"
                ).replace("\\n", "")
            for project_item in project.input:
                item_data = require_lua_table(item[project_item.id], context=f"research item {project_item.id}")
                project_item.name = require_lua_str(
                    item_data["name"], context=f"research item {project_item.id} name"
                ).strip()
            for project_item in project.output:
                item_data = require_lua_table(item[project_item.id], context=f"research item {project_item.id}")
                project_item.name = require_lua_str(
                    item_data["name"], context=f"research item {project_item.id} name"
                ).strip()

            project_key = (project.series, project.name)
            if project_key not in projects:
                projects[project_key] = project

        return projects

    def encode(self) -> list[str]:
        lines = [
            "# 此文件由 dev_tools/research_extractor.py 自动生成。",
            "# 不要手动修改。",
            "",
            "from typing import TYPE_CHECKING",
            "",
            "if TYPE_CHECKING:",
            "    from module.research.types import ResearchProjectData",
            "",
            "",
            "LIST_RESEARCH_PROJECT: list[ResearchProjectData] = [",
        ]
        for project in self.projects.values():
            lines.extend(encode_project(project.encode()))
        lines.append("]")

        return lines

    def write(self, file: FilePath) -> None:
        print(f"writing {file}")
        with Path(file).open("w", encoding="utf-8") as f:
            f.writelines(f"{text}\n" for text in self.encode())


"""
这是用于抽取科研项目数据的开发工具。

先克隆 https://github.com/AzurLaneTools/AzurLaneLuaScripts 获取解密后的 Lua 脚本。
Arguments:
    FILE: Lua 脚本仓库路径，例如 '<your_folder>/AzurLaneData'
    SAVE: 保存目标，例如 'module/research/project_data.py'
"""
FOLDER = ""
SAVE = "module/research/project_data.py"

if __name__ == "__main__":
    TechnologyTemplate().write(SAVE)
