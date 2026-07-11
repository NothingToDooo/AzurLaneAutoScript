import json
import re
from pathlib import Path

import module.logger
from dev_tools.utils import LuaLoader

# 导入 module.logger 会切换到项目根目录。
_ = module.logger


class Item:
    def __init__(self, data):
        """按 Lua 三元组的值顺序读取：类型标记、物品 ID、数量。"""
        self.name = ""
        _, self.id, self.amount = data.values()
        if self.id == 1:
            self.id = 59001  # 物资在 technology_data_template 里是 1，在 item_data_statistics 里是 59001。

    def __str__(self):
        return f"{self.name}({self.id}) x {self.amount}"


INPUT_KEYWORDS = {
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


def normalize_name(name):
    return str(name).replace(" ", "").lower()


def project_consumption(items):
    data = {}
    for item in items:
        name = normalize_name(item.name)
        for key, keywords in INPUT_KEYWORDS.items():
            if any(normalize_name(keyword) in name for keyword in keywords):
                data[key] = True
    return data


def project_ship(items):
    for item in items:
        name = normalize_name(item.name)
        for keyword, ship in SHIP_KEYWORDS.items():
            if normalize_name(keyword) in name:
                return ship
    return ""


def equipment_amount(task):
    result = EQUIPMENT_AMOUNT.search(task)
    return int(result.group(1)) if result else 0


def encode_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def encode_project(data):
    lines = ["    {"]
    for key, value in data.items():
        lines.append(f"        {encode_value(key)}: {encode_value(value)},")
    lines.append("    },")
    return lines


class Project:
    def __init__(self, data):
        self.name = data["name"]
        self.series = int(data["blueprint_version"])
        self.time = int(data["time"])
        self.input = [Item(item) for item in data["consume"].values()]
        self.output = [Item(item) for item in data["drop_client"].values()]
        self.task_id = int(data["condition"])
        self.task = ""

    def encode(self):
        data = {
            "name": self.name,
            "series": self.series,
            "time": self.time,
        }
        data.update(project_consumption(self.input))
        ship = project_ship(self.output)
        if ship:
            data["ship"] = ship
            data["ship_rarity"] = "dr" if ship in DR_SHIP else "pry"
        amount = equipment_amount(self.task)
        if amount:
            data["equipment_amount"] = amount
        return data


class TechnologyTemplate:
    def __init__(self):
        self.projects = self.load_projects(LuaLoader(FOLDER, server="zh-CN"))

    def load_projects(self, loader):
        tech = loader.load("sharecfg/technology_data_template.lua")
        item = loader.load("sharecfgdata/item_data_statistics.lua")
        virtual_item = loader.load("sharecfgdata/item_virtual_data_statistics.lua")
        item.update(virtual_item)
        task = loader.load("sharecfgdata/task_data_template.lua")

        projects = {}
        for tech_key, value in tech.items():
            if tech_key == "all":
                continue
            project = Project(value)
            if project.task_id:
                project.task = task[project.task_id]["desc"].replace("\\n", "")
            for i in project.input:
                i.name = item[i.id]["name"].strip()
            for i in project.output:
                i.name = item[i.id]["name"].strip()

            project_key = (project.series, project.name)
            if project_key not in projects:
                projects[project_key] = project

        return projects

    def encode(self):
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

    def write(self, file):
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
