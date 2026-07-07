from module.config.server import to_server

_COALITION_TO_FROSTFALL = {
    "easy": "tc1",
    "normal": "tc2",
    "hard": "tc3",
}
_COALITION_TO_LITTLE_ACADEMY = {
    "tc1": "easy",
    "tc2": "normal",
    "tc3": "hard",
}


def upload_redirect(value):
    """
    redirect attr about upload.
    """
    if isinstance(value, list):
        if not value[0] and not value[1]:
            return "do_not"
        if value[0] and not value[1]:
            return "save"
        if not value[0] and value[1]:
            return "upload"
        return "save_and_upload"
    if not value:
        return "do_not"
    return "save"


def api_redirect(value):
    """
    redirect attr about api.
    """
    if value == "auto":
        return "default"
    if to_server(value) == "cn":
        return "cn_gz_reverse_proxy"
    return "default"


def dossier_redirect(value):
    """
    OpsiDossierBeacon -> AttackMode
    """
    if value:
        return "current_dossier"
    return "current"


def enhance_favourite_redirect(value):
    """
    EnhanceFavourite -> ShipToEnhance
    """
    if value:
        return "all"
    return "favourite"


def enhance_check_redirect(value):
    """
    CheckPerCategory should be at least 5
    """
    if isinstance(value, int):
        if value < 5:
            return 5
    return value


def emotion_mode_redirect(value):
    """
    CalculateEmotion + IgnoreLowEmotionWarn -> Emotion.Mode
    """
    calculate, ignore = value
    if calculate:
        if ignore:
            return "calculate_ignore"
        return "calculate"
    if ignore:
        return "ignore"
    # Invalid, fallback to calculate
    return "calculate"


def change_ship_redirect(value):
    """
    FlagshipChange + FlagshipEquipChange -> ChangeFlagship
    """
    ship, equip = value
    if not ship:
        return "disabled"
    if equip:
        return "ship_equip"
    return "ship"


def api_redirect2(value):
    """
    remove shanghai proxy, use guangzhou
    """
    if value == "cn_sh_reverse_proxy":
        return "cn_gz_reverse_proxy"
    return value


def coalition_to_frostfall(value):
    """
    将小学院关卡名重定向到飓风与青春之泉。
    """
    return _COALITION_TO_FROSTFALL.get(value, value)


def coalition_to_little_academy(value):
    """
    将飓风与青春之泉关卡名重定向回小学院。
    """
    return _COALITION_TO_LITTLE_ACADEMY.get(value, value)
