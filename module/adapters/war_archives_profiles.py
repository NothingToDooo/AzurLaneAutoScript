from module.content.catalog import ContentCatalog
from module.war_archives.profile import (
    WAR_ARCHIVES_CLIENT_PROFILES,
    WarArchivesClientProfileError,
)


def validate_mumu12_war_archives_profiles(catalog: ContentCatalog) -> None:
    """在设备构造前验证所有档案内容包引用的客户端 profile。"""

    if not isinstance(catalog, ContentCatalog):
        message = "catalog must be a ContentCatalog"
        raise TypeError(message)
    referenced = set()
    for pack in catalog.packs:
        if pack.kind != "war_archives":
            continue
        definition = pack.war_archives
        if definition is None:
            message = f"war archives pack is missing its typed definition: {pack.pack_id}"
            raise ValueError(message)
        referenced.add(definition.profile_id)

    registered = {profile.profile_id for profile in WAR_ARCHIVES_CLIENT_PROFILES.profiles}
    unknown = sorted(profile_id.value for profile_id in referenced - registered)
    unused = sorted(profile_id.value for profile_id in registered - referenced)
    if unknown or unused:
        message = f"war archives client profile coverage mismatch: unknown={unknown}, unused={unused}"
        raise WarArchivesClientProfileError(message)
