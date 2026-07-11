import re

from module.base.mask import Mask
from module.ui.assets import MAIN_GOTO_FLEET, PLAYER_CHECK
from module.ui_white.assets import MAIN_GOTO_CAMPAIGN_WHITE

MASK_MAIN = Mask("./assets/mask/MASK_MAIN.png")
MASK_MAIN_WHITE = Mask("./assets/mask/MASK_MAIN_WHITE.png")
MASK_PLAYER = Mask("./assets/mask/MASK_PLAYER.png")


def handle_sensitive_image(image):
    if PLAYER_CHECK.match(image, offset=(30, 30)):
        image = MASK_PLAYER.apply(image)
    if MAIN_GOTO_FLEET.match(image, offset=(30, 30)):
        image = MASK_MAIN.apply(image)
    if MAIN_GOTO_CAMPAIGN_WHITE.match(image, offset=(30, 30)):
        image = MASK_MAIN_WHITE.apply(image)

    return image


def handle_sensitive_text(text):
    text = re.sub(r'File "(.*?)AzurLaneAutoScript', 'File "C:\\\\fakepath\\\\AzurLaneAutoScript', text)
    return re.sub(r"\[Adb_binary\] (.*?)AzurLaneAutoScript", "[Adb_binary] C:\\\\fakepath\\\\AzurLaneAutoScript", text)


def handle_sensitive_logs(logs):
    return [handle_sensitive_text(line) for line in logs]
