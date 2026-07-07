from pathlib import Path

import numpy as np
from PIL import Image
from tqdm import tqdm

import module.config.server as server

server.server = "cn"  # 不需要修改，用来避免服务器相关错误。

from module.base.base import ModuleBase
from module.base.utils import node2location, rgb2gray
from module.config.config import AzurLaneConfig
from module.map_detection.view import View


class Config:
    """
    Paste the config of map file here
    """

    INTERNAL_LINES_FIND_PEAKS_PARAMETERS = {
        "height": (80, 255 - 17),
        "width": (0.9, 10),
        "prominence": 10,
        "distance": 35,
    }
    EDGE_LINES_FIND_PEAKS_PARAMETERS = {"height": (255 - 17, 255), "prominence": 10, "distance": 50, "wlen": 1000}
    HOMO_EDGE_COLOR_RANGE = (0, 17)


"""
Usage:
    - Enter map, and find a siren.
    - Manually count the siren is in which node, in local map view.
    - Run relative_record.py first, to get enough images.
    - Run relative_record_gif2.py, to generate gif template file.
    - Find one suitable template in <FOLDER>/<NAME>_gif. It should:
        Not contain the face of siren, only contain the body.
        Not contain sea surface as background.
        Contain less frames if possible.
    - Copy to assets/<server>/template, run button_extract.py
    - Use new templates in config, like this:
        MAP_HAS_SIREN = True
        MAP_SIREN_TEMPLATE = ['U73', 'U81']

Arguments:
    CONFIG:     ini config file to load.
    FOLDER:     Folder to save.
    NAME:       Siren name, images will save in <FOLDER>/<NAME>
    NODE:       Node in local map view, that you are going to crop.
"""
CONFIG = "alas"
FOLDER = ""
NAME = "Deutschland"
NODE = "D5"

if __name__ == "__main__":
    for folder in [Path(FOLDER), Path(FOLDER) / NAME]:
        if not folder.exists():
            folder.mkdir()

    cfg = AzurLaneConfig(CONFIG).merge(Config())
    al = ModuleBase(cfg)
    al.device.disable_stuck_detection()
    al.device.screenshot_interval_set(0.11)
    view = View(cfg)
    al.device.screenshot()
    view.load(al.device.image)
    grid = view[node2location(NODE.upper())]

    print("Please check if it is cropping the right area")
    print("If yes, wait until screenshot progress complete")
    print("If no, stop process, change `NODE`, run again")
    image = rgb2gray(grid.relative_crop((-0.5, -1, 0.5, 0), shape=(60, 60)))
    image = Image.fromarray(image, mode="L").show()

    images = [al.device.screenshot() for _n in tqdm(range(300))]
    for n, image in enumerate(images):
        grid.image = np.array(image)
        image = rgb2gray(grid.relative_crop((-0.5, -1, 0.5, 0), shape=(60, 60)))
        image = Image.fromarray(image, mode="L")
        image.save(Path(FOLDER) / NAME / f"{n}.png")

    print("relative_record done")
