import argparse
import csv
import shutil
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

from module.base.utils import load_image
from module.logger import logger
from module.statistics.battle_status import BattleStatusStatistics
from module.statistics.get_items import GetItemsStatistics
from module.statistics.utils import ImageError, load_folder

STATUS_ITEMS_INTERVAL = 10


class DropStatistics(BattleStatusStatistics, GetItemsStatistics):
    def __init__(self, folder):
        """
        Args:
            folder (str): Such as <your_drop_screenshot_folder>/campaign_7_2
        """
        self.folder = folder
        self.template_folder = (Path(self.folder) / "item_template").as_posix()
        if not Path(self.template_folder).exists():
            shutil.copytree("./assets/stats_basic", self.template_folder)
        self.load_template_folder(self.template_folder)
        self.battle_status = load_folder(Path(folder) / "status")
        self.get_items = load_folder(Path(folder) / "get_items")
        self.battle_status_timestamp = np.array([int(f) for f in self.battle_status])

    def _items_to_status(self, get_items):
        """
        Args:
            get_items (str): get_items image filename.

        Returns:
            str: battle_status image filename.
        """
        interval = np.abs(self.battle_status_timestamp - int(get_items))
        if np.min(interval) > STATUS_ITEMS_INTERVAL * 1000:
            raise ImageError(f"Timestamp: {get_items}, battle_status image not found.")
        return str(self.battle_status_timestamp[np.argmin(interval)])

    def extract_template(self, image=None, folder=None):
        """
        Extract and save new templates into 'item_template' folder.
        """
        for ts, file in tqdm(self.get_items.items()):
            try:
                image = load_image(file)
                super().extract_template(image, folder=self.template_folder)
            except (ImageError, OSError, ValueError, cv2.error) as e:
                logger.warning(f"Error image: {ts}, {e}")

    def stat_drop(self, timestamp):
        """
        Args:
            timestamp (str): get_items image timestamp.

        Returns:
            list: Drop data.
        """
        get_items = load_image(self.get_items[timestamp])
        battle_status_timestamp = self._items_to_status(timestamp)
        battle_status = load_image(self.battle_status[battle_status_timestamp])

        enemy_name = self.stats_battle_status(battle_status)
        items = self.stats_get_items(get_items)
        return [[timestamp, battle_status_timestamp, enemy_name, item.name, item.amount] for item in items]

    def generate_data(self):
        """
        Yields:
            list: Drop data.
        """
        for ts, _file in tqdm(self.get_items.items()):
            try:
                data = self.stat_drop(ts)
                yield data
            except (ImageError, OSError, ValueError, cv2.error) as e:
                logger.warning(f"Error image: {ts}, {e}")


# FOLDER：Alas 掉落截图目录，例如 '<your_drop_screenshot_folder>/campaign_7_2'。
FOLDER = ""
# CSV_FILE：统计结果保存路径，例如 'c72.csv'。
CSV_FILE = ""


def main(argv: list[str] | None = None) -> None:
    """运行离线掉落统计工具。"""
    parser = argparse.ArgumentParser(description="离线统计掉落截图")
    parser.add_argument("folder", nargs="?", default=FOLDER, help="Alas 掉落截图目录")
    parser.add_argument("--csv", default=CSV_FILE, help="CSV 输出路径")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--extract-template", action="store_true", help="提取物品模板，之后需要手动重命名")
    mode.add_argument("--export-csv", action="store_true", help="导出掉落统计 CSV")
    args = parser.parse_args(argv)

    if not args.folder:
        parser.error("请设置掉落截图目录")

    stats = DropStatistics(args.folder)
    if args.extract_template:
        stats.extract_template()
        return

    if not args.csv:
        parser.error("导出 CSV 时必须设置 --csv")
    with Path(args.csv).open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        for data in stats.generate_data():
            writer.writerows(data)


if __name__ == "__main__":
    main()
