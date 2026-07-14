from module.coalition.profile import COALITION_CLIENT_PROFILES
from module.content.activity_catalog import (
    ActivityCatalog,
    CoalitionActivity,
    EventStoryActivity,
    RaidActivity,
)
from module.eventstory.profile import EVENT_STORY_CLIENT_PROFILES
from module.raid.profile import RAID_CLIENT_PROFILES


def validate_mumu12_activity_profiles(catalog: ActivityCatalog) -> None:
    """在设备 I/O 前验证当前全部活动内容都有可执行客户端 profile。"""

    if not isinstance(catalog, ActivityCatalog):
        message = "activity profile validation requires an ActivityCatalog"
        raise TypeError(message)
    event_story_profiles = set()
    raid_profiles = set()
    coalition_profiles = set()
    for activity in catalog.activities:
        if isinstance(activity, EventStoryActivity):
            profile_id = activity.definition.profile_id
            if profile_id is not None:
                EVENT_STORY_CLIENT_PROFILES.resolve(profile_id)
                event_story_profiles.add(profile_id)
        elif isinstance(activity, RaidActivity):
            RAID_CLIENT_PROFILES.bind(activity)
            raid_profiles.add(activity.definition.profile_id)
        elif isinstance(activity, CoalitionActivity):
            profile = COALITION_CLIENT_PROFILES.resolve_profile(activity.definition.profile_id)
            profile.validate_definition(activity.definition)
            coalition_profiles.add(activity.definition.profile_id)

    closures = (
        ("event story", event_story_profiles, EVENT_STORY_CLIENT_PROFILES.profile_ids),
        ("raid", raid_profiles, RAID_CLIENT_PROFILES.profile_ids),
        ("coalition", coalition_profiles, COALITION_CLIENT_PROFILES.profile_ids),
    )
    for kind, referenced, declared in closures:
        if referenced != declared:
            unknown = sorted(profile.value for profile in referenced - declared)
            unused = sorted(profile.value for profile in declared - referenced)
            message = f"{kind} client profile coverage mismatch: unknown={unknown}, unused={unused}"
            raise ValueError(message)
