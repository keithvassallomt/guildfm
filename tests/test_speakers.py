from guildfm.speakers import QUEUE_URI, pick_group


class Leader:
    """A group's coordinator, as far as picking a group goes."""

    def __init__(self, uid: str, media: str = "") -> None:
        self.uid = uid
        self.media = media
        self.asked = 0

    def get_current_media_info(self) -> dict[str, str]:
        self.asked += 1
        return {"uri": self.media}


class Group:
    def __init__(self, leader: Leader, size: int = 1) -> None:
        self.coordinator = leader
        self.members = {f"{leader.uid}-{n}" for n in range(size)}


def on_queue(uid: str) -> Leader:
    return Leader(uid, QUEUE_URI.format(uid=uid))


def test_one_group_is_picked_without_asking_the_speakers() -> None:
    leader = Leader("RINCON_A")
    assert pick_group({Group(leader, 6)}, None).coordinator is leader
    assert leader.asked == 0


def test_split_into_single_rooms_stays_with_the_one_on_its_queue() -> None:
    # What the office's speakers did on 2026-11-19: six rooms on their own, one with the queue.
    entrance = on_queue("RINCON_ENTRANCE")
    groups = [Group(Leader(f"RINCON_{n}")) for n in range(5)] + [Group(entrance)]
    assert pick_group(groups, "RINCON_ENTRANCE").coordinator is entrance
    assert pick_group(groups, None).coordinator is entrance


def test_all_stopped_alike_stays_with_the_group_it_was_on() -> None:
    entrance = Leader("RINCON_ENTRANCE")
    groups = [Group(Leader("RINCON_DONUT")), Group(entrance), Group(Leader("RINCON_POD"))]
    assert pick_group(groups, "RINCON_ENTRANCE").coordinator is entrance


def test_the_biggest_group_on_a_queue_wins() -> None:
    # The coordinator taken out of the group: the rest carry on with the queue under another.
    alone = on_queue("RINCON_ENTRANCE")
    rest = on_queue("RINCON_POD")
    groups = [Group(alone), Group(rest, 5)]
    assert pick_group(groups, "RINCON_ENTRANCE").coordinator is rest


def test_a_bigger_group_off_any_queue_doesnt_win() -> None:
    # The TV on, or the radio, in a group of their own.
    ours = on_queue("RINCON_LOUNGE")
    groups = [Group(Leader("RINCON_ARC", "x-sonos-htastream:RINCON_ARC:spdif"), 3), Group(ours)]
    assert pick_group(groups, None).coordinator is ours
