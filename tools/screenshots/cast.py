"""Who and what is in the demo office: the people (all invented), the songs they know (real,
found on Spotify by fetch.py), and the playlists, DJs, stations and line-ups they've made."""

from dataclasses import dataclass
from pathlib import Path

from guildfm.radio import AI_PICKS, AI_PICKS_BRIEF

DEMO = Path(__file__).parent / "demo"
PASSWORD = "demo-password"


@dataclass(frozen=True)
class Person:
    username: str
    name: str
    role: str  # "user", "curator" or "admin"
    # How they look, for painting their photo. None for someone without a photo, shown by
    # their initials, as many people will be.
    looks: str | None
    # Someone an admin added this morning, who hasn't signed in yet.
    new: bool = False


PEOPLE = [
    Person("hannah", "Hannah Price", "admin", "a woman in her forties with short auburn hair "
           "and a warm smile, wearing a green cardigan"),
    Person("tom", "Tom Fletcher", "curator", "a man in his thirties with a short beard and "
           "round glasses, wearing a flannel shirt"),
    Person("priya", "Priya Shah", "user", "a woman in her late twenties with long dark hair, "
           "wearing a denim jacket"),
    Person("owen", "Owen Hughes", "user", "a man in his fifties with grey hair, wearing a navy "
           "jumper"),
    Person("grace", "Grace Liu", "curator", "a woman in her thirties with a black bob, wearing "
           "a striped top"),
    Person("callum", "Callum Reid", "user", None),
    Person("amara", "Amara Okafor", "user", "a woman in her twenties with long braids, wearing "
           "a mustard jumper"),
    Person("ellie", "Ellie Watson", "user", None),
    Person("ben", "Ben Carter", "user", "a man in his twenties with curly hair, wearing a grey "
           "hoodie"),
    Person("sam", "Sam Okoro", "user", None, new=True),
]  # fmt: skip

# Whose eyes each role's screenshots are taken through.
READERS = {"user": "priya", "curator": "tom", "admin": "hannah"}

# Real songs, as (title, artist), found on Spotify by fetch.py.
SONGS = [
    # Requests
    ("Mr. Blue Sky", "Electric Light Orchestra"),
    ("September", "Earth, Wind & Fire"),
    ("Dreams", "Fleetwood Mac"),
    ("Golden Hour", "JVKE"),
    ("Heat Waves", "Glass Animals"),
    ("Don't Stop Me Now", "Queen"),
    ("Levitating", "Dua Lipa"),
    ("Africa", "TOTO"),
    # Office Classics
    ("Walking On Sunshine", "Katrina & The Waves"),
    ("Here Comes The Sun", "The Beatles"),
    ("I Wanna Dance with Somebody", "Whitney Houston"),
    ("Superstition", "Stevie Wonder"),
    ("Take On Me", "a-ha"),
    ("Dancing Queen", "ABBA"),
    ("Sweet Caroline", "Neil Diamond"),
    ("Livin' On A Prayer", "Bon Jovi"),
    ("Ain't No Mountain High Enough", "Marvin Gaye"),
    ("Mr. Brightside", "The Killers"),
    ("Shut Up and Dance", "WALK THE MOON"),
    ("Wake Me Up Before You Go-Go", "Wham!"),
    ("Billie Jean", "Michael Jackson"),
    ("Lovely Day", "Bill Withers"),
    ("Can't Stop the Feeling!", "Justin Timberlake"),
    ("Electric Feel", "MGMT"),
    ("Dog Days Are Over", "Florence + The Machine"),
    ("Golden", "Harry Styles"),
    ("Pompeii", "Bastille"),
    ("Uptown Funk", "Mark Ronson"),
    # More Fleetwood Mac, for searching
    ("Go Your Own Way", "Fleetwood Mac"),
    ("Everywhere", "Fleetwood Mac"),
    ("The Chain", "Fleetwood Mac"),
    ("Landslide", "Fleetwood Mac"),
    ("Little Lies", "Fleetwood Mac"),
    ("Rhiannon", "Fleetwood Mac"),
    ("Don't Stop", "Fleetwood Mac"),
    ("Songbird", "Fleetwood Mac"),
    ("Seven Wonders", "Fleetwood Mac"),
    # What the stations pick
    ("Don't You (Forget About Me)", "Simple Minds"),
    ("Wonderwall", "Oasis"),
    ("Common People", "Pulp"),
    ("Girls Just Want to Have Fun", "Cyndi Lauper"),
    ("Bitter Sweet Symphony", "The Verve"),
    ("Song 2", "Blur"),
    ("Torn", "Natalie Imbruglia"),
    ("Everybody Wants To Rule The World", "Tears For Fears"),
    ("Crazy In Love", "Beyoncé"),
    ("Toxic", "Britney Spears"),
    ("Don't Look Back In Anger", "Oasis"),
    ("Sweet Dreams (Are Made of This)", "Eurythmics"),
    ("Fast Car", "Tracy Chapman"),
    ("Banana Pancakes", "Jack Johnson"),
    ("Bloom", "The Paper Kites"),
    ("Better Together", "Jack Johnson"),
    ("Riptide", "Vance Joy"),
    ("Le Freak", "CHIC"),
    ("Good Times", "CHIC"),
    ("I Feel Love", "Donna Summer"),
    ("Get Lucky", "Daft Punk"),
]

# Artists with their pictures, for search's artist suggestions.
ARTISTS = ["Fleetwood Mac", "Queen"]

# Albums with their songs, as (album, artist), for queueing and adding whole albums.
ALBUMS = [("Rumours", "Fleetwood Mac"), ("Tango in the Night", "Fleetwood Mac")]


@dataclass(frozen=True)
class DJ:
    name: str
    personality: str
    voice: str


DJS = {
    "Guildbert": DJ(
        "Guildbert",
        "Funny, but not corny. Definitely British humour. Sometimes a bit sarcastic, but all in "
        "good fun. Quite cheeky and distinctly northern. Likes a bit of trivia about the track "
        "that's just played or the one coming up.",
        "elevenlabs:guildbert01",
    ),
    "Della": DJ(
        "Della",
        "Warm, softly spoken morning host from Yorkshire. Loves a bit of music trivia, never "
        "talks for long.",
        "marin",
    ),
}


@dataclass(frozen=True)
class Station:
    name: str
    description: str
    curator: str  # who made it
    dj: str | None = None
    talk_every: int = 3
    talk_unit: str = "tracks"
    style: str = "commentary"
    global_awareness: bool = False
    jingles: bool = True
    crossfade: bool = False
    # Station idents from assets/jingles/Station Idents, by folder.
    idents: str | None = None


STATIONS = [
    Station(
        "Xennials' Delight",
        "Mostly hits from the 80s, 90s and early 2000s. Something Xennials (Gen X and "
        "Millennials) from a British background would enjoy, but popular music from across the "
        "western world, not just British music.",
        curator="tom",
        dj="Guildbert",
        global_awareness=True,
        crossfade=True,
        idents="Xennials Delight",
    ),
    Station(
        "Morning Coffee",
        "Gentle acoustic, folk and soul to ease into the day. Warm and unhurried, nothing too "
        "loud before ten.",
        curator="grace",
        dj="Della",
        talk_every=4,
        style="announce",
        global_awareness=True,
    ),
    Station(
        "Friday Feeling",
        "Disco, funk and feel-good pop to see the week out. Big choruses, nothing slow.",
        curator="hannah",
        dj="Guildbert",
        talk_every=15,
        talk_unit="minutes",
        crossfade=True,
    ),
    Station(
        "Deep Focus",
        "Instrumental electronica and post-rock for heads-down afternoons. No vocals, nothing "
        "jarring.",
        curator="tom",
        jingles=False,
    ),
]

# The built-in station, which needs a cover like the rest.
COVERS = [(s.name, s.description, "station") for s in STATIONS] + [
    (AI_PICKS, AI_PICKS_BRIEF, "station")
]


@dataclass(frozen=True)
class Lineup:
    name: str
    description: str
    curator: str
    # (start, end, station or playlist name), with times as "08:00".
    slots: list[tuple[str, str, str]]


LINEUPS = [
    Lineup(
        "Office Day",
        "A normal day: an easy start, Guildbert through to lunch, singalongs at lunchtime and "
        "quieter afternoons.",
        curator="tom",
        slots=[
            ("08:00", "09:30", "Morning Coffee"),
            ("09:30", "12:00", "Xennials' Delight"),
            ("12:00", "13:00", "Lunchtime Singalongs"),
            ("13:00", "15:30", "Deep Focus"),
            ("15:30", "18:00", "Xennials' Delight"),
        ],
    ),
    Lineup(
        "Fridays",
        "Morning Coffee to start, Office Classics until lunch, then Friday Feeling all afternoon.",
        curator="hannah",
        slots=[
            ("08:00", "10:00", "Morning Coffee"),
            ("10:00", "11:15", "Office Classics"),
            ("12:00", "18:00", "Friday Feeling"),
        ],
    ),
]
COVERS += [(lineup.name, lineup.description, "lineup") for lineup in LINEUPS]


def slug(name: str) -> str:
    """A file name for a cover: "Xennials' Delight" becomes "xennials-delight"."""
    return "-".join("".join(c if c.isalnum() else " " for c in name.lower()).split())
