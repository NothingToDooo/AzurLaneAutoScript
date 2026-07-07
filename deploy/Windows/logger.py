import logging
import os
import sys
from pathlib import Path
from typing import cast


class DeployLogger(logging.Logger):
    def hr(self, title, level=3): ...

    def attr(self, name, text): ...


os.chdir(Path(__file__).resolve().parents[2])

_logger = logging.getLogger("deploy")
logger = cast("DeployLogger", _logger)

formatter = logging.Formatter(fmt="%(message)s")
hdlr = logging.StreamHandler(stream=sys.stdout)
hdlr.setFormatter(formatter)
_logger.addHandler(hdlr)
_logger.setLevel(logging.INFO)


def hr(title, level=3):
    if logger is not _logger:
        return logger.hr(title, level)

    title = str(title).upper()
    if level == 0:
        middle = "|" + " " * 20 + title + " " * 20 + "|"
        border = "+" + "-" * (len(middle) - 2) + "+"
        logger.info(border)
        logger.info(middle)
        logger.info(border)
    if level == 1:
        logger.info("%s %s %s", "=" * 20, title, "=" * 20)
    if level == 2:
        logger.info("%s %s %s", "-" * 20, title, "-" * 20)
    if level == 3:
        logger.info("<<< %s >>>", title)
    return None


def attr(name, text):
    print(f"[{name}] {text}")


_logger.hr = hr
_logger.attr = attr


class Percentage:
    def __init__(self, progress):
        self.progress = progress

    def __call__(self, *args, **kwargs):
        logger.info("Process: [ %s%% ]", self.progress)


class Progress:
    Start = Percentage(0)
    ShowDeployConfig = Percentage(10)

    AdbReplace = Percentage(80)
    AdbConnect = Percentage(95)

    # Must have a 100%
    Finish = Percentage(100)
