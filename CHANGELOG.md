# Changelog

All notable changes to GuildFM are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and GuildFM
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Making a station is now a few plain steps, starting with what kind of station it is: Just
  music, Music with a DJ, or a Talk show. The type decides the steps after it, so a music
  station never sees DJ settings and a talk show asks for its hosts and the show. Next says
  what's missing, a review lists every choice with Change, and once it's made it can be put on,
  given its own jingles, or left for later. On a wide screen, a card beside the steps fills in
  as you go.
- Each station has its own page, with a card for each part: its type, name and music, DJ or
  hosts, how the DJ talks or the show, and the extras. Change opens just that part and saves it
  on its own. A new type walks through what it needs: turning a station with a DJ into a talk
  show asks for its hosts, then the show. Its cover, its own jingles and Delete are there too.
- DJs are picked from cards that say who they are and which stations they host, with Hear for a
  line in their voice. New DJs are made in place, and a talk show offers only ElevenLabs voices.
- "Suggest one" has the AI write how a talk show's hosts get on, from their personalities and
  hooks.
- A talk show's slider shows an hour as blocks of talk and music, and "Bring in" chips add the
  day's news, weather, football and more to what the show's about, or take them out.
- ElevenLabs voices say what they sound like, such as "British, middle aged, male", when
  ElevenLabs has that.

### Changed

- The station editor is gone: New station opens the steps, and a station's card on Radio opens
  its page. A DJ's pet peeves, soft spots and running obsession are only asked for on talk
  shows, which are the only stations that use them.
- New stations know what's going on (the time, the weather and music news) unless that's
  turned off.

### Fixed

- A display name with a description added, such as "Gary from Nottingham", is now turned down
  every time, however it's capitalised or spelt, with a message saying to leave the description
  out. Before, the check was close to a coin toss for names like these, so trying again or
  changing the capitals got them through. Real names that look a little like that, such as
  "Jan van der Berg" or "Gary Nottingham", and nicknames such as "Big Mike", are still fine.

## [0.1.10] - 2026-11-20

### Changed

- Each show on a talk station gets one or two of each DJ's hooks (pet peeves, soft spots and
  running obsession), different from the ones they had last show. Before, every hook came up in
  every show, so the same few stories came round each day.
- A talk station remembers what its last few shows talked about, and doesn't plan those topics
  again.
- A talk station's script prompt is now a guide rather than a checklist. The DJs keep to its
  spirit but can stray from it for variety, so a show won't always use everything in it.

### Fixed

- After a restart, a talk show planned straight away had no news or football, because what
  GuildFM had found that day was only kept in memory. It's now kept on disk too.
- Putting a station on could leave a gap of about 20 seconds while it picked its first songs.
  If what was playing ended or was skipped in that time, the speakers stopped and Play said
  there was nothing to play. A station now opens straight away with a song it has played
  before, and its new picks follow. A station that has never played anything still waits for
  its picks.
- On a talk station at 40% or 45% talk, the talk before each song was one segment of up to three
  minutes. It took about 80 seconds to write and voice, so it was often ready only after its
  song had started, and was dropped unheard but still paid for. Talk now comes in segments of
  two minutes at most, so the first is ready in time and the rest are made while it plays. A
  show's plan is sized to match, so it neither runs out early nor ends before its running bits
  pay off.
- A talk station's editing pass wasn't told the day or time, so it could guess wrong and change
  a line that had them right. On The Squawk Box's first morning it decided a Friday was a
  Thursday. It's now told, as the writer is.

## [0.1.9] - 2026-11-19

### Changed

- While GuildFM has the speakers, a room that drops out of the group and sits there silent goes
  back in within about 10 seconds. Rooms on the TV or playing something else are left alone. To
  keep a room quiet, turn its volume down rather than taking it out of the group.

### Fixed

- When Sonos split the speakers into separate rooms, GuildFM could take it for someone using the
  Sonos app, say the speakers were overridden and stop until a curator pressed Play. It now
  stays with the rooms playing its queue.

## [0.1.8] - 2026-11-17

### Added

- Talk stations: a station with two or more DJs, each with an ElevenLabs voice, can be mostly
  talk. The DJs chat, bicker and banter, cut each other off and talk over each other, and keep
  running bits going through the show, such as a bet or a score, set up early and paid off
  later. When the station asks for them, they use the day's real odd news, weather, football and
  celebrity birthdays. In the station editor, turn on Mostly talk, set how much of it is talk
  (20% to 100%, with about what an hour costs in ElevenLabs credits), and write a script prompt
  saying what the show is about. The talk stops for each song: the DJs wrap up before it and
  pick up again after it. Requests still play, and a curator can skip a stretch of talk.
- A station can have several DJs, up to six, each on a card that opens and closes. Say how they
  get on, and press Hear them together for half a minute of them talking, played on your device.
- DJ hooks: pet peeves, soft spots and a running obsession, which give the DJs on a talk station
  something to bring out in each other.
- A Talk stations help topic, and the DJs topic covers several DJs and their hooks.
- Skip music when ready, in the monitor mode bar. Each song starts near its end and stops as
  soon as the DJ's next words are ready, so trying out a DJ isn't minutes of beeps.

### Changed

- Station and line-up covers are no longer all an office with a radio in it. OpenAI paints
  each one from its name and its music instead: a play on the name, the mood, or the look of
  the music's era. Press Paint another in a station's editor for a new one.

## [0.1.7] - 2026-11-17

### Added

- When the speakers won't start any songs and GuildFM starts waiting for them, it says so over
  every room, in the announcement voice, sounding a little embarrassed: "Oops, it seems I'm
  having trouble playing songs right now..." It says it at most once an hour, and it shows in the
  announcements log.

### Fixed

- When the speakers stop every song a few seconds in, as they do when they can't get songs from
  Spotify, GuildFM no longer races through the queue. A song that stops like that gets one more
  try and doesn't count as played. After three different songs in a row, GuildFM holds on to
  the same song and tries it every 30 seconds until the speakers play it, and the badge says
  **Won't start**, with a note on Now Playing and the Queue. On 2026-11-17 it went through 29
  songs in five minutes this way, which looked like non-stop skipping.
- GuildFM checks the speakers' own queue before taking songs off it. When its copy had songs
  the speakers had lost, it asked them to remove those again and again, about 50 times near the
  end of every song, and logged that it had taken them off when it hadn't. It could also have
  taken the wrong song off.

## [0.1.6] - 2026-11-16

### Fixed

- Search keeps its Artists and Albums when more songs load. They used to vanish as soon as the
  next 10 songs loaded, which happens straight away when the first 10 fit on the screen.
- Picking an artist in search shows far more of their songs. Spotify only gives 5 songs when
  asked for an artist's, so GuildFM also searches for the artist's name and keeps the songs
  that are theirs.

## [0.1.5] - 2026-11-15

### Added

- An After-hours play setting, under Playback hours: 4 hours to start with. Pressing Play
  outside the playback hours plays for that long, then GuildFM stops again by itself. Settings
  says until when it's playing after hours.

### Changed

- Stations repeat themselves far less. A station doesn't pick a song that's been heard in the
  office in the past week, and the AI is shown that week's songs so it can pick around them. If
  too many of its picks have been heard anyway, it's asked once more before the station falls
  back on songs from before.
- When a station plays songs from before, it starts with the ones not heard for longest,
  instead of the ones it picked most recently. After its own songs and Best Voted, it falls
  back on anything else heard in the office, so a new station doesn't go quiet while the AI
  can't pick.

### Fixed

- Paused music stays paused when the speakers restart, as they sometimes do overnight. GuildFM
  used to take the speakers coming back stopped for its queue running out, and start the next
  song in an empty office.
- Another version of a song that just played, such as a remaster or the single, no longer gets
  past a station. Every version of a song counts as the same song.

## [0.1.4] - 2026-11-12

### Added

- guildfm.com is served through a Cloudflare Tunnel from the office machine, so Android phones
  no longer need Chrome's Local network permission to open it. Visitors who arrive through Cloudflare from
  anywhere but the office's own public address see "Connect to TJardinePrivate" instead of
  GuildFM. The office's address is looked up by the office machine itself, so it can change.
- Admins can rename people on Admin, Users: their display name, the username they sign in
  with, or both. They stay signed in, and sign in with the new username from then on.

### Changed

- Search shows 10 songs at a time, and the next 10 load by themselves when you scroll down to
  them, so GuildFM asks Spotify for less.
- The same search within 10 minutes is answered from memory, and the DJ looks its picks up in
  songs GuildFM has found before, asking Spotify only for new ones.

### Fixed

- When Spotify says GuildFM has asked too much, GuildFM now waits as long as Spotify asks
  before asking again. It used to keep asking, which can make Spotify's wait longer: one in
  November lasted 18 hours. Meanwhile stations play songs from before, without asking the AI
  for picks, and search says when it will work again, such as "Spotify has paused searching
  until 08:47 tomorrow". The journal notes how many calls GuildFM made in the minute before.

## [0.1.3] - 2026-11-06

### Added

- A preview for links to GuildFM in chats: the logo above a radio dial, "The office jukebox"
  and what GuildFM does. Chats that build previews on the sender's phone or computer, such as
  iMessage and WhatsApp, show it for links sent from the office. Slack and Teams build them on
  their own servers, which can't reach GuildFM. `make preview-card` draws the picture again.
- Thumbs up and down for the song that's playing, on Now Playing and at the top of the Queue,
  whether it was a request or came from a playlist or a station. No number of thumbs down stops
  it, but its votes count as they do in the queue: they're kept with it in Played today, and
  enough thumbs up put it in Best Voted. A request's votes from the queue carry on.
- The DJ knows how the office voted, and brings it up now and then: the votes so far on the song
  that just played, the votes on a request coming up, thumbs down on a station's song that
  weren't enough to skip it, and how the song coming up did the last time it played. It only
  knows the numbers, never who voted.
- "What's new in GuildFM": after an update that has something to tell, everyone sees a short
  note about it once, the next time they open GuildFM or come back to it, without signing in
  again. Not every version has one. New accounts don't get the notes from before they joined.

### Changed

- Played today shows the score of songs from a playlist or a station too, not only requests.
- "Made it into Best Voted" in the activity only appears when a song first gets in, not each time
  a song already there plays again.

### Fixed

- After the office machine restarted on 5 November, GuildFM couldn't reach Spotify, OpenAI,
  ElevenLabs or the weather, so searching for songs failed and the DJ and stations' AI went
  quiet. `deploy/setup-https.sh` wrote the machine's nameservers where the old network client
  wiped them as it shut down. It now writes them where they're kept.

## [0.1.2] - 2026-10-30

### Added

- GuildFM at `https://guildfm.com` in the office, with a Let's Encrypt certificate that Caddy
  gets and renews through Route 53. The name points at the office machine's private address, so
  it only works inside the office. `deploy/setup-https.sh` sets it up, and the README says how
  it fits together.
- `PUBLIC_URL` in `.env`: browsers that open a page over plain HTTP by name, such as
  `http://guildfm.local`, are sent there. The speakers, the API and Spotify's sign-in carry on
  as they are.

### Changed

- Long song titles in search results and album track lists wrap onto a second line instead of
  being cut short. A title longer than two lines still ends with "…", so rows stay tidy.

## [0.1.1] - 2026-10-30

### Added

- Names are checked when people pick them, at sign-up and when they change their display name
  on Profile. OpenAI turns down rude names, and display names that aren't plausibly what
  someone is called, such as "bungalistic". A username only has to be clean, since it's for
  signing in. If OpenAI can't be reached within 10 seconds, the name goes through.
- The version GuildFM is running: at the foot of the sidebar on desktop, and first on the
  Admin page.
- This changelog.
- The journal now records when the speakers stop, pause or start again, with where the
  speakers and GuildFM each are in the queue, so a silence can be pieced together afterwards.

### Fixed

- The music stayed off until someone pressed Play when the speakers turned down GuildFM's
  second try at a song that hadn't started. GuildFM now skips that song straight away and
  carries on with the next one.
- GuildFM's second try at a song asked for the wrong place in the speakers' queue when its
  own copy of that queue had drifted from theirs. It now reads the speakers' queue first,
  goes by that, and notes in the journal what had drifted.
- The playback buttons on Now Playing and in the quick controls could stay greyed out for good
  if a command never got an answer. They now give up after 20 seconds and say to check what's
  playing before trying again.
- The song list in "Request a song" scrolled sideways on phones when a title was long. Long
  titles are cut short again.
- Requesters' photos and initials sat below their names on Now Playing. They're now centred
  on the text.

## [0.1.0] - 2026-10-27

The first version, installed on the office machine.
