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
    CheckPerCategory 至少为 5。
    """
    if isinstance(value, int) and value < 5:
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
