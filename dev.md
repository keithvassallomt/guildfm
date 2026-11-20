# GuildFM Development Plan

The build plan for GuildFM. The spec is [stream.md](stream.md) and the UI reference is the [prototype](https://claude.ai/artifact/J9FURLqbP6ryuCQWhe6UWo) (copy in `prototype/`).

Work goes stage by stage, in order. A task is ticked when it is built and tested. A stage is ticked in the overview when all its tasks are.

Every screen is mobile first and responsive: it has to work on a phone and look like a normal web app on a desktop browser.

From Stage 14 on, any change people can see also updates its help topics and takes their screenshots again (`make screenshots`).

## Overview
- [x] Stage 0: Feasibility and design
- [x] Stage 1: Foundations
- [x] Stage 2: Accounts and roles
- [x] Stage 3: Sonos control
- [x] Stage 4: Spotify catalogue
- [x] Stage 5: Queue and voting
- [x] Stage 6: Playback rules and settings
- [x] Stage 7: Playlists
- [x] Stage 8: Now Playing
- [x] Stage 9: Announcements
- [x] Stage 10: AI radio
- [ ] Stage 11: Hardening and handover
- [x] Stage 12: Line-ups
- [ ] Stage 13: Jingle generator
- [x] Stage 14: Help
- [x] Stage 15: Cloudflare migration
- [x] Stage 16: Spotify rate limits
- [x] Stage 17: Renaming people
- [x] Stage 18: Fewer repeats
- [x] Stage 19: After hours
- [ ] Stage 20: Talk stations
- [ ] Stage 21: Making and editing stations
- [ ] Stage 22: Just a name

## Stage 0: Feasibility and design
- [x] Prove a chosen Spotify track can be queued and played on the office Sonos speakers
- [x] Prove an MP3 served from the GuildFM machine plays over the music as an announcement
- [x] Write the spec (stream.md)
- [x] Build the clickable UI prototype
- [x] Set up the git repository, `.env.example`, `.env` and `.gitignore`
- [x] Create the Spotify developer app and fill in `.env`

## Stage 1: Foundations
Goal: an empty but running app, front end and back end, with the GuildFM look.
- [x] Python project with uv: FastAPI app, settings loaded from `.env`
- [x] SQLite database with SQLAlchemy and Alembic migrations
- [x] Front end with Vite, React and TypeScript, built into static files that FastAPI serves
- [x] The prototype's look as shared styles: colours, fonts, buttons, toggles, tab bar
- [x] Responsive layout: tab bar along the bottom on phones, sidebar and full-width content on desktop
- [x] Websocket channel from server to browser for live updates
- [x] Dev tooling: one command to run everything locally, ruff, pytest
- [x] `.gitignore` extended for Python and Node build output
- [x] First commit

Done when: the app opens on a phone on the office network and shows an empty Queue screen with the tab bar, and on a desktop browser shows the same screen with a sidebar.

## Stage 2: Accounts and roles
Goal: people can sign up and sign in, and each role sees and can do only what the spec allows.
- [x] User model: username, display name, password hash, role, "announce my requests" (on by default)
- [x] Seed the admin account from `.env` on first start
- [x] Create account, sign in, sign out (session cookie)
- [x] Permission checks for user, curator and admin, following the table in stream.md
- [x] Profile screen: display name, announce-my-requests toggle, your requests, sign out
- [x] Users screen (admin): list users, change role, reset password with a temporary password, add an account
- [x] Delete accounts (admin, not your own), signing the person out straight away, including their live connection
- [x] Tests for every permission rule

Done when: a user, a curator and an admin each see the right tabs and controls, and blocked actions are refused by the server, not just hidden.

## Stage 3: Sonos control
Goal: GuildFM controls the office speakers directly over the network.
- [x] Discover speakers and the group, keep the room list fresh, show connection status
- [x] Play, pause, skip and stop
- [x] Volume for the whole office and for each room
- [x] Queue a Spotify track on the speakers (the method proven in Stage 0)
- [x] Follow the speakers, read every second: now playing, position, track ended
- [x] Detect outside control (Sonos or Spotify app) and switch GuildFM to the overridden state
- [x] Handle the Arc being switched to the TV: it drops out, the other rooms carry on (tested against the fake system only; not tried on the real Arc)
- [x] Test an MP3 placed in the Sonos queue between two tracks (the one untested piece): works, with no gap either side
- [x] Admin controls screen wired up: status, transport buttons, volumes

Done when: an admin can run the office music from their phone, and taking over from the Sonos app puts GuildFM into the overridden state.

## Stage 4: Spotify catalogue
Goal: people can find any song on Spotify from GuildFM.
- [x] Spotify app login (client credentials) with token refresh
- [x] Search for tracks and artists, paging past Spotify's 10-result limit
- [x] Store track details locally: title, artist, duration, explicit flag, artwork
- [x] Hide explicit tracks when the setting is off (the setting is stored now; its switch comes with the Settings screen in stage 6)
- [x] Spotify account connection for playlist import (via 127.0.0.1), with a reminder before the six-month expiry
- [x] Search screen wired up (adding to the queue comes in Stage 5)

Done when: searching "fleetwood" on a phone shows Fleetwood Mac's tracks with artwork.

## Stage 5: Queue and voting
Goal: the core of GuildFM: requests, votes, and the music following them.
- [x] Queue model: requests with requester and votes, followed by tracks from the current source
- [x] Playback engine: picks the next track (requests by votes first, then the source), hands it to Sonos shortly before it's needed, and locks it
- [x] Add a request: cap per user (default 5), no duplicates in the queue, "recently played" badge (default 24 hours)
- [x] Voting: thumbs up and down, one vote per person per track, net score, removal at the threshold (default -3)
- [x] Remove your own track; curators reorder, remove any track and override votes
- [x] Play history, used for "recently played" and the Best Voted playlist
- [x] Live updates: queue, now playing and the activity feed, on every phone at once
- [x] Queue screen wired up, including the activity feed
- [x] Search and request straight from the Queue screen, keeping the Search page (added after trying the queue out)
- [x] Request actions tucked into a tray that slides out, and drag to reorder for curators (added after trying the queue out)
- [x] Tests for ordering, the request cap, duplicates and the downvote threshold

Done when: two phones vote on the queue, both see the order change live, and the speakers play the winning track next.

## Stage 6: Playback rules and settings
Goal: admins can shape when and how GuildFM plays.
- [x] Settings storage and the Settings screen, with every default from stream.md
- [x] Stop halts everything, including announcements and the DJ. Play resumes whatever was playing before.
- [x] Playback schedule per weekday. Outside those hours GuildFM stays silent.
- [x] "When the queue runs out" setting, with each option wired up as its stage lands (playlist in 7, AI station and AI pick in 9)
- [x] Connections section: Spotify status and reconnect, Sonos status
- [x] An admin's Play works at any time, overriding the playback hours until Stop or the next closing time (added after trying it out)
- [x] Quick controls for admins: a floating button on every screen but Admin, opening play, pause, stop and the office volume (added after trying it out)
- [x] Previous and skip in the quick controls, Previous on Admin too (greyed out when going back would jump over a song already lined up), and a long track name scrolls (added after trying it out)
- [x] The progress bar glides instead of ticking and jumping (from backlog.md)

Done when: GuildFM starts and stops itself on schedule, and Stop then Play resumes the same source.

## Stage 7: Playlists
Goal: curators can build, import and play playlists, and the office's favourites collect themselves.
- [x] Playlist model: create, rename, add and remove tracks, play as the source
- [x] Import a Spotify playlist from a link, with a clear message when Spotify refuses it (not owned or collaborative)
- [x] Best Voted playlist: a track joins with more than X upvotes (default 5), holds Y tracks (default 50), the fewest upvotes drop out first, then the oldest, and a newcomer needs at least as many upvotes as the track it replaces
- [x] "Restart the current playlist" option for when the queue runs out
- [x] Library screen, Playlists tab, wired up
- [x] Shuffle per playlist (off by default, on for Best Voted), and the playing playlist's next 3 songs on the Queue screen with thumbs down to skip (decided before building)
- [x] Admins have no request cap (decided before building)
- [x] Albums (added from backlog.md after Stage 9): album results when adding songs to a playlist, showing the album's songs before adding all of them, and album links in the import box, which make a playlist named after the album

Done when: a curator imports a Spotify playlist, plays it, and requests still jump ahead of it.

## Stage 8: Now Playing
Goal: everyone lands on a screen that shows what's playing and where it came from, and curators and admins switch sources from it. Added from backlog.md: the desktop layout is prototype B (Tuner), the phone layout prototype A (Console), at https://claude.ai/artifact/86PFwBpK2T7jAJ1t6VJMdu
- [x] Play history records where each song came from (a request, a playlist, later a station), with an API for today's plays, newest first
- [x] Each playlist remembers when it last played, so sources sort last played first
- [x] Switching source takes effect after the current song, even when the old source's next song is already lined up on the speakers. A playlist switched away from carries on where it left off when it's put back on (decided while building)
- [x] "Requests only": after this song, nothing fills the gaps
- [x] Curators get play, pause, previous and skip; volume and Stop all stay with admins
- [x] Now Playing screen, desktop: now playing and the controls on the left, Queue, Library and Radio as bands of tiles with a needle on what's on air, history below
- [x] Now Playing screen, phone: the now playing card, the three sources as tabs, history below
- [x] On air is animated (equaliser, glow, needle), and holds still for people who turn motion off
- [x] The Radio band shows an empty state until Stage 10
- [x] Now Playing is the landing screen and the first tab; Queue stays its own tab; on phones Profile moves to an avatar in the header; quick controls are hidden on Now Playing
- [x] UI tidy-up from backlog.md, after Stage 10: Search folded into the Queue's "Request a song"; Playlists and Radio as their own tabs; Admin's pages under it in the sidebar; playback controls, room volumes and a quick announcement on Now Playing only; photos for people; cover art in the playlists list

Done when: an admin lands on Now Playing and picks another playlist, a waiting request still plays first, the needle moves to the new playlist when it takes over, and a curator can skip but can't change the volume.

## Stage 9: Announcements
Goal: admins type an announcement and the office hears it, now or on schedule.
- [x] Text to speech with OpenAI, saved as MP3 and served to the speakers over the network
- [x] Voice preview in the browser, with built-in or typed phrases
- [x] Announcement model: text, rooms, now or scheduled, over the music or after the current song, repeats (once, daily, weekdays, chosen days, hourly) with an end date
- [x] Scheduler that respects Stop and the playback schedule
- [x] Delivery: overlay clip in each chosen room, or between songs. Between songs, GuildFM pauses the music just before the song ends, plays the clip, then starts the next song, since a clip in the Sonos queue would play in every room (decided while building)
- [x] Announcements always take precedence over the DJ (the DJ's lines queue behind them from Stage 10)
- [x] Announcements and New announcement screens wired up: on/off switch, "Play now", editing and deleting
- [x] Announcements for every room after the current song go through the Sonos queue, straight after the song and ahead of any jingle or DJ, so every room plays them in step. After the current song is the default, and the editor and the quick announcement warn of a slight echo over the music or in more than one chosen room (added after Stage 10)

Done when: a recurring announcement plays in two chosen rooms between songs, and doesn't play while GuildFM is stopped.

## Stage 10: AI radio
Goal: curators create stations with an AI DJ that picks songs and talks between them.
- [x] Station model and the New AI station screen: name, description, global awareness, DJ name, personality, voice, how often, style, announce requests
- [x] Song picking: the AI suggests tracks from the description and recent plays, GuildFM finds them on Spotify, avoiding repeats
- [x] Global awareness: time of day, weather for the configured location (Open-Meteo), and music news through OpenAI web search
- [x] DJ scripts: track intros, commentary and request shout-outs (respecting each user's opt-out)
- [x] DJ voice: text to speech in the chosen voice, delivered in the DJ's personality, with previews
- [x] DJ timing: every N tracks or minutes, the AI choosing between over the intro and between songs, always after any announcement
- [x] Start or switch station (curators and admins), default station, and both AI options for when the queue runs out. "Let the AI pick" is a built-in AI picks station that follows what's been playing, and "Requests only" chosen on Now Playing means nothing takes over (decided while building)
- [x] Library screen, AI stations tab, wired up, and the Radio band on Now Playing
- [x] The DJ can comment on requests, knowing how often a song, its artist and its requester have come up lately, and a station never plays a song a request played recently (added after building the stage)
- [x] Preview an hour of a station from its editor, saved or not: the songs, and what the DJ says and where, with each line playable in the DJ's voice (added after building the stage)
- [x] Installable as an app from backlog.md: manifest, icons (with a maskable one for Android), iPhone home screen tags, and an install section on Profile. Browsers only offer to install over HTTPS or on localhost, so the office needs HTTPS for that (Stage 11) (added after building the stage)
- [x] Voices at the music's loudness (ffmpeg, about -14 LUFS) and clips starting in step in every room, after Keith heard them quiet and echoing (added after building the stage)
- [x] Announcement voices from backlog.md: the voice shown by name, and an "Add an emotion" list for ElevenLabs voices in the editor and the quick announcement (added after building the stage)
- [x] Cropping profile photos from backlog.md: choose the part to use in a round frame, with drag and zoom, before it's sent (react-easy-crop) (added after building the stage)
- [x] Whole albums in the queue from backlog.md, for curators and admins: albums in their request search, queued in order as their requests without counting towards the cap, and one DJ shout-out per album (added after building the stage)
- [x] Station covers from backlog.md: OpenAI paints each station a cover from its name and description, shown on Now Playing, the Radio page and the station editor (with "Paint another"); a new name or description gets a new one, and stations without one get theirs at startup. Now Playing's tiles stay the same width whatever their captions (added after building the stage)
- [x] ElevenLabs voices from backlog.md: the account's own voices alongside OpenAI's, grouped apart in the station editor and settings, for the DJ and announcements. On an ElevenLabs voice the DJ can use tags such as [laughs]; tags are taken out for OpenAI's voices (added after building the stage)
- [x] Jingles from backlog.md: GuildFM's station idents (Admin, Jingles) and each station's show idents (its editor), played in the pause between songs where the AI marks them, never twice in a row, each station with a switch, and shown in the hour preview (added after building the stage)
- [x] Shared DJs from backlog.md: a DJ (name, personality, voice) is their own, chosen in the station editor or made new there, and can host several stations; changes apply on all of them, and how often they talk stays per station. Existing stations' DJs were moved over by a migration (added after building the stage)
- [x] Jingles renamed from backlog.md: system idents (GuildFM's own) and station idents (one station's), and Xennials' Delight's three replaced with six new ones (added after building the stage)
- [x] Station editor from backlog.md: "Paint another" paints from the name and description in the editor, saved or not, and saving those doesn't paint another; leaving with unsaved changes asks first (added after building the stage)
- [x] Crossfade between songs, a switch on each station, off by default: while the station fills the gaps, on its own or as a line-up's show, GuildFM has the speakers crossfade, and turns it off for anything else. Asked for after Keith heard the quiet at the ends and starts of songs, which GuildFM can't trim itself (added after building the stage)
- [x] No crossfade into or out of the DJ, a jingle or an announcement: GuildFM turns it off while one is in the queue or playing, and back on once the song after it starts, since Sonos fades for 10 seconds or more (added after building the stage)
- [x] The DJ and jingles between songs go into the Sonos queue just before their song, so every room plays them in step, after Keith still heard a little reverb from overlay clips. They come back out once played; announcements and the DJ over the start of a song stay overlay clips (added after building the stage)
- [x] The DJ only talks between songs, after Keith heard the echo on a line over the start of a song: Sonos plays an overlay clip room by room with no start time to give, so those can't be in step. The AI no longer chooses where, a line that isn't ready before its song starts is let go, and the hour preview shows every line between songs (added after building the stage)

Done when: a station with a DJ plays for an hour, announces a request by name, and mentions the Carlisle weather.

## Stage 11: Hardening and handover
Goal: GuildFM runs unattended on the office machine.
- [x] After a restart, GuildFM carries on driving the speakers if they're still playing its queue (done early, after trying Stage 8)
- [x] After a restart, GuildFM still says someone took over from the Sonos app, whether that happened before the restart or while it was down (from backlog.md)
- [x] After a restart, the DJ still knows why each song was picked, and the jingles the AI marked still play: both are kept in the database rather than in memory (found while building)
- [x] After a restart, the DJ remembers what it said lately, where it talked and how many songs since it last did, so it doesn't open with the weather after every restart. Kept with the playing source, so it starts afresh, and talks on the first song, each time a station comes on; before, that only happened the first time after startup. The DJ is always told to bring up the weather, time or news only now and then, naming just the time without global awareness (found while building)
- [x] The DJ's album shout-out goes on an album's first song even across a restart, and again when the same album is queued another time: whether it has started is read from the play history rather than remembered (found while building)
- [x] Monitor mode (Settings, admins): GuildFM plays in browsers instead of on the Sonos speakers, songs as beeps for their real length and the DJ, jingles and announcements for real, with "Listen here" at the top of every page. Turning it on or off stops the music and waits for Play; it stays on through a restart (added after building the stage)
- [x] Explicit tracks blocked by default, from backlog.md: "Allow explicit tracks" in Settings is now off unless an admin turns it on (added after building the stage)
- [x] GuildFM's logo in place of the cover on Now Playing and the Queue while an announcement, the DJ or a jingle is on, from backlog.md (added after building the stage)
- [x] GuildFM keeps its own place on the speakers, after Keith found the morning's songs replaying with a station stuck on "After this song": the speakers' queue holds a few played songs, the one on now and what's lined up, and anything else comes off; when stopped speakers go back to the start of their queue, GuildFM and Play carry on from GuildFM's place; and a lined-up song that won't play is skipped after a few seconds (found while building)
- [x] A lined-up song the speakers don't start gets a second try before it's skipped, after Guildbert introduced Red Alert and another song played; and songs Spotify says can't play in the UK are left out of search and imported playlists too, as they already were from albums (found while building)
- [x] The second try at a song that didn't start goes by the speakers' own queue, and a try they turn down skips the song at once, after the music stayed off on 2026-10-30 until someone pressed Play. The journal now notes when the speakers stop, pause or start, with both places in the queue, and the playback buttons give up waiting after 20 seconds
- [x] Names checked by OpenAI when people pick them, after a "BigBalls" and a "bungalistic" on 2026-10-30: display names have to be clean and read like a name, usernames only clean. A name goes through if OpenAI can't answer
- [x] `CHANGELOG.md` (Keep a Changelog, semantic versions, 0.1.0 is what went into the office), and the running version at the foot of the desktop sidebar and first on the Admin page
- [x] Graceful failure: speakers offline (a clip still plays in the rooms that answer), Spotify token expired, OpenAI and ElevenLabs errors including running out of credit, and the weather or a cover failing. The music keeps playing and the DJ goes quiet. An announcement whose ElevenLabs voice fails is read out in the OpenAI announcement voice instead. A station whose AI can't pick plays songs from before (its earlier picks, then its older plays, then Best Voted) rather than going silent (decided while building)
- [x] Logging and a simple status view for admins (Admin, Status): the speakers, Spotify, OpenAI, ElevenLabs (with the credits used this month), the weather, whether ffmpeg was found, the backups and disk space, and recent problems from the log. Each service is judged by how GuildFM's own calls to it went, not by test calls
- [x] Run as a service: a systemd unit (`deploy/guildfm.service`) rather than Docker, ffmpeg in the setup steps, old speech clips cleared out daily rather than only at startup, and `scripts/update.sh` for updates. An empty `AUDIO_LOUDNESS=` no longer stops GuildFM starting (found while building)
- [x] Backups: daily zips of the SQLite database and the uploaded media (jingles, covers, profile photos), the last 14 kept, in `data/backups` or `BACKUP_DIR`, and `guildfm backup` for one now. Speech clips are a cache and are left out
- [x] Moving in: GuildFM installed on the office machine following the README, with a backup from the laptop unzipped into its data folder, or a fresh start with the jingles uploaded again from `assets/jingles`. A fresh start on 2026-10-27: the boss's Spotify app and account, Xennials' Delight and Guildbert, the jingles, and the laptop's playlists
- [ ] Reaching GuildFM: `guildfm.local` advertised over mDNS (Avahi, in the README), and checked on the office's phones and laptops (older Android phones may not resolve `.local` names). Then decide on HTTPS. A `.local` name can't get a certificate browsers trust, so HTTPS means a hostname on a company domain (Let's Encrypt through a DNS challenge, behind Caddy). On plain HTTP, iPhones still add GuildFM to the home screen, and Android and desktop get a shortcut that opens a browser tab. The speakers keep fetching clips over plain HTTP either way
  - [x] HTTPS decided and built, after Mac browsers refused `http://guildfm.local` on 2026-10-30: `https://guildfm.com` in Route 53, pointing at the office machine's fixed private address (10.240.1.61, set on the machine since the router isn't ours), Caddy on 443 with a Let's Encrypt certificate through the DNS challenge, and `PUBLIC_URL` sending plain HTTP there. Set up by `deploy/setup-https.sh`
- [x] README: setting up the Spotify app, the redirect URI and `.env` (OpenAI, and ElevenLabs if wanted), installing ffmpeg, and running GuildFM. Spotify only accepts an HTTPS or `127.0.0.1` redirect, so without HTTPS, Spotify is connected from a browser on the machine itself or through an SSH tunnel. Also what it costs to run: OpenAI for the DJ's lines, voices and covers, and ElevenLabs credits per line
- [ ] Full end-to-end run on the office speakers: requests and votes, a whole album, a station with an ElevenLabs DJ and its jingles, an announcement in chosen rooms, and installing GuildFM on a phone

Done when: GuildFM survives a restart of the machine and a day of normal office use without anyone touching it.

## Stage 12: Line-ups
Goal: curators plan the day as a line-up of AI shows and playlists, and GuildFM switches between them by the clock. From backlog.md, where it was called schedules.
- [x] [Prototype](https://claude.ai/artifact/UHq9ijCE69mbRoYD1C6ccK) for Keith to review: the Line-ups page, the line-up editor (a bar across the screen on desktop, down it on phones) and Now Playing's Line-ups band, as a list of line-ups and as a time strip with the needle, on phone and desktop
- [x] Line-up model: name, description, cover, and slots (a station or a playlist, with a start and an end time on 15-minute steps, never overlapping)
- [x] Switching by the clock: a line-up as the source, its slot worked out from the time, each slot starting at the first song change after its start time. A playlist still playing when its slot ends is cut off there, a gap falls back to "When the queue runs out", and slots outside a day's playback hours don't play
- [x] Hand-overs: when a show starts, its station ident, then its DJ saying what's on and until when
- [x] Line-ups page and editor: list, new, edit and delete. Drag, move and resize on desktop; a day view with start and end times on phones. Playlists as long as the playlist or shorter, and the note that requests shift the timings a little
- [x] Covers painted from the name and description, as for stations
- [x] Now Playing: the Line-ups band (a fourth tab on phones) with the line-ups as tiles, and once one is on, its slots along a time strip with the needle moving with the clock, and back to the list. Picking a playlist, a station or Requests only ends the line-up
- [x] Line-ups in the sidebar on desktop, and on phones through Now Playing's Line-ups tab, keeping the tabs to five
- [x] A show's station picks its first songs up to ten minutes before the show, kept on the station until it comes on, so the show starts without waiting for the AI (added after building the stage)
- [x] A "Put on" button on the Line-ups page as well as Now Playing, as in the prototype; a playlist that runs out before its slot ends starts over; and a line-up whose playing station or playlist is deleted carries on, with a gap there (decided while building)

Done when: a line-up with a morning playlist, a lunchtime show and an afternoon show runs through a day by itself, each show opening with its ident and its DJ, while requests still play first.

## Stage 13: Jingle generator
Goal: whoever looks after jingles describes the ones they want, or has the AI write them, and ElevenLabs makes them to listen to and keep or turn down. Asked for by Keith on 2026-10-21.
- [x] [Prototype](https://claude.ai/artifact/Vnj5Qwy49yCFa9LEU9h5FS) for Keith to review: the generator opened from Admin, Jingles and from the station editor, describing and reviewing, on desktop and phone
- [x] About GuildFM: a setting with a sensible default, edited on Admin, Jingles, for the AI to read when it writes system idents
- [x] Prompts kept: a jingle made here keeps its description, length and whether it's instrumental. One turned down keeps its description, marked as turned down, and its file goes. Uploaded MP3s have none
- [x] The AI writing descriptions: one call for any number of them, answered as JSON (a name, a description, a length of 5 to 15 seconds, instrumental or not). It reads About GuildFM for system idents, or the station's name, description and DJ for a station's own, as they are in the editor, saved or not, as "Paint another" does. It also reads the descriptions made here before, kept and turned down, and what the other cards already say, so they come out different. A card with words in it is built on, not replaced. The AI never names real artists, bands or songs, which ElevenLabs refuses, and spells out any words to be sung or said
- [x] Making them with ElevenLabs Music (`/v1/music`, its model in `.env` as `ELEVENLABS_MUSIC_MODEL`): each description at its length, instrumental forced when asked, then evened out to the voices' loudness as uploads are. Its errors fit to show (out of credits, a description refused and why) and counted in ElevenLabs' health on Status
- [x] Drafts: what ElevenLabs makes waits in the media folder until it's kept or turned down, so closing the generator part way loses nothing, and opening it again picks up where it left off. Drafts no one decided on are cleared after a day, and left out of backups
- [x] The generator, one modal for both places, opened by "Generate jingles" beside "Add MP3s" in the jingle list: how many (1 to 6), and a card for each with its description, a length slider (5 to 15 seconds) and an Instrumental switch. An AI button on each card, and "Write the empty ones" for every empty card in one go
- [x] Making and reviewing: "Generate" makes them all side by side, each card showing its own progress. Each plays on this device, can be renamed, and is kept (it joins the list straight away), turned down, or tried again with the same description. One ElevenLabs refused gets its description back to change, by hand or with the AI. "Generate more" starts another round that knows about this one. Done with some still to decide on asks first; closing it any other way keeps the round for next time (decided while building)
- [x] The jingle list's permissions: admins for system idents, whoever makes stations for a station's own, and none for AI picks
- [x] Tests: what the AI is given (kept and turned down, the other cards), keeping and turning down drafts, permissions, ElevenLabs' errors, and old drafts being cleared
- [x] After Keith's first round: ElevenLabs makes two at a time, and when it says it's busy it's asked again after 5, 15 and 30 seconds. Each jingle is planned by ElevenLabs first (free), then made from the plan with its parts fitted to the length asked for, since from a description alone 12 seconds came out as 20 and 6 as 9. The Instrumental switch takes the words out of the plan. The AI always writes words, sung, chanted or rapped rather than spoken, which the music model left out; it writes an instrumental only for a card switched to one (found while trying it)
- [x] Words that go unsung: a test of the same description four times lost its words once, made on its own, so it wasn't the two at a time. OpenAI's speech to text now listens to each jingle with words, and one where they can't be heard is made again, once; if they're missing again, its card says so. The voices in ElevenLabs' plan also go in the first part's styles, which set the tone for the whole piece, and the plan's words are kept to the ones the description quotes, since ElevenLabs adds lines of its own (found while trying it)

Done when: an admin asks for three system idents, has the AI write two and writes the third, keeps two and turns one down, and the next round's AI descriptions steer clear of the one turned down.

## Stage 14: Help
Goal: help inside GuildFM, in plain words with screenshots, covering every feature, where each person reads only about what they can do. The README stays the technical guide (setting up, `.env`, the service); the help never mentions any of that. Asked for by Keith on 2026-10-23.
- [x] Demo office: a staged GuildFM on the fakes the tests use, so screenshots need no speakers, Spotify or AI. The six office rooms, invented colleagues with photos painted once by OpenAI and kept in the repo, real songs with their real artwork, playlists (Best Voted among them), stations with covers and DJs, a line-up, announcements, jingles and today's plays, at a fixed date and time, the same every run
- [x] Screenshot tool, `make screenshots`: Playwright drives Chromium through each shot as a user, a curator or an admin, on a phone (390 px wide) and a desktop, with motion held still and the control a step is about ringed in orange. Shots are saved small (WebP) in the repo, and one shot or all of them can be taken again with one command
- [x] Help viewer: a Help section at the bottom of the sidebar on desktop and on Profile on phones, topics grouped by area, each topic short numbered steps with screenshots, the phone shots on phones and the desktop shots on desktop. A search box over the topics. A ? in every page's header opens that page's topic, and the sign-in page links to the getting-started topics
- [x] Who sees what: each topic, and any part within one, is marked with the permission it needs (the same ones the app checks), so a user never reads about controls they don't have, and screenshots are taken as the role reading them wherever a page looks different. Admins can switch the help to how a user or a curator sees it, for explaining things to people. The help ships with the app, so this hides it rather than locking it
- [x] Sample for Keith to review before the rest: the viewer, the screenshot tool and two finished topics, Requesting and voting (everyone) and Making an announcement (admins), on phone and desktop
- [x] Topics for everyone: what GuildFM is and why requests play first; creating an account, signing in and a forgotten password (ask an admin, then choose a new one); installing GuildFM on a phone or computer; Profile (display name, photo and cropping, announce my requests, your requests, signing out); Now Playing (what's on, where it came from, today's plays, the logo while the DJ, a jingle or an announcement is on); requesting a song (search, the cap, already queued, "recently played", songs that don't show up); voting and how the queue orders itself, removal at the threshold and the locked next song; removing your own request; thumbs down on a playlist's or station's next songs; what the status chip and banners mean (paused, stopped, outside playback hours, taken over from the Sonos app); the DJ and jingles, and not being named
- [x] Topics for curators: play, pause, previous and skip (and why Previous is sometimes greyed out); reordering, removing and overriding votes in the queue; whole albums in the queue; choosing what fills the gaps on Now Playing, "after this song" and Requests only; playlists (making one, adding songs and albums, renaming, removing songs, shuffle, playing, deleting); importing from Spotify, playlist and album links, and copying a playlist Spotify won't share; Best Voted; Radio and AI picks; making a station (description, global awareness, crossfade, play jingles); its DJ (choosing or making one, shared DJs, personality, voice and preview, how often and what they say, announcing requests); covers and Paint another; a station's own jingles, uploaded or generated; previewing an hour; line-ups (what they are, making one on desktop and phone, putting one on, the Line-ups band, hand-overs and gaps)
- [x] Topics for admins: office and room volume and Stop all; quick controls; the quick announcement; announcements (rooms, now or scheduled, over the music or after the song, repeats, emotions, preview, the on/off switch, Play now, editing, deleting, missed ones); jingles (system idents, uploading, About GuildFM, the jingle generator); users (adding, roles, resetting a password, deleting); every setting explained, with playback hours, when the queue runs out and connections; monitor mode and Listen here; the Status page and what each state means
- [x] Checks: every page in the app has a topic, every screenshot a topic uses exists for each size and role it's shown at, and every permission a topic names is a real one. Build and typecheck pass
- [x] Keeping it current: from this stage on, a stage that changes what people see also updates its topics and takes its screenshots again (noted at the top of this plan)

- [x] The office in phases, so screens that only show in other states can be shot too: a line-up on, the jingle generator's drafts, someone taking over from the Sonos app, and monitor mode. The clock goes back to 11:24 for each, and a role's shot that's the same as the role's below is dropped, since the help falls back to it. Signed out, the sign-in page's link opens the three getting-started topics. A page with several topics opens a list of them from its ?, and curators can read the help as a user too. Covers, photos and songs are gathered once by `tools/screenshots/fetch.py` (decided while building)

Done when: a user, a curator and an admin each open Help on a phone and on a desktop, see only what they can do, with screenshots that match the screen in front of them, and the ? on every page opens the right topic.

## Stage 15: Cloudflare migration
Goal: guildfm.com served through a Cloudflare Tunnel from the office machine, so phones reach it at a public address and Android 17 doesn't ask for Chrome's Local network permission, while only the office's own public address (which can change) gets in. Asked for by Keith on 2026-11-10, after two Pixels couldn't open it.
- [x] Change DNS server to Cloudflare
- [x] Prepare code changes for GuildFM: visitors through Cloudflare whose address isn't the office's (looked up by the machine itself, IPv4 and its IPv6 /64) see "Connect to TJardinePrivate" instead
- [x] Commit and push
- [x] Deploy to office box
- [x] Create Cloudflare tunnel
- [x] Add public hostname
- [x] Test

Done when: a Pixel on TJardinePrivate opens guildfm.com without the Local network permission, and a phone on mobile data sees the Wi-Fi page.

## Stage 16: Spotify rate limits
Goal: GuildFM stays under Spotify's rate limit, and when it does go over, it waits as long as Spotify asks instead of making the wait longer. Asked for by Keith on 2026-11-12, after searching at the office stopped for 18 hours ("Spotify is busy. Try again in 64890 seconds.").
- [x] Waiting as asked: a 429's `Retry-After` pauses every call to Spotify (search, the DJ, imports, the app token) until it's over, refused without asking Spotify. The journal notes the wait and how many calls GuildFM made in the minute before
- [x] Saying until when: a pause under two minutes reads "Spotify is busy. Try again in 7 seconds." and a longer one "Spotify has paused searching until 08:47 tomorrow.", in the office's time zone. The Status page shows the same
- [x] The DJ waits it out: while paused, stations don't ask the AI for picks and play songs from before (no Spotify needed). The hour preview says Spotify is paused
- [x] Fewer calls: the same search within 10 minutes is answered from memory, the DJ looks its picks up in songs GuildFM has found before and searches Spotify only for new ones, and search asks for 10 songs at a time, the next 10 loading by themselves when "Show more" scrolls into view
- [x] Tests, the changelog, and the Requesting help topic
- [x] Deploy to office box

Done when: the office box is on this, and a 429 from Spotify pauses GuildFM for the time Spotify gives, with search saying until when.

## Stage 17: Renaming people
Goal: an admin can rename someone, their display name, their username or both. Asked for by the office's owner through Keith on 2026-11-12.
- [x] Renaming, for admins only and not their own account (as for roles): the same rules as adding someone (a username 3 to 32 letters, numbers, dots, dashes or underscores, not taken; a display name up to 40), and not checked by the AI, as names admins give aren't. They stay signed in, and the queue and Now Playing show the new name straight away
- [x] Rename beside Reset password on Admin, Users, opening a dialog like Add someone's with both names filled in. A new username is said afterwards ("Priya now signs in as priya.s. Let them know.")
- [x] Tests, the changelog, the Users help topic and its screenshots
- [x] Deploy to office box

Done when: an admin renames someone at the office, who stays signed in, sees the new name on their requests, and signs in with the new username next time.

## Stage 18: Fewer repeats
Goal: a station stops coming back to the same songs every day or two. Asked for by Keith on 2026-11-15, after people at the office said stations repeat songs. The office box showed why: Xennials' Delight played 689 songs in a week but only 352 different ones, and 379 in all since it went in, under three days of music. A third of its plays were songs back after 24 to 48 hours. Its memory of 150 picks covers about one office day, and the AI is shown 49 of the roughly 211 songs its picks are refused for, so whole batches come back refused and the station plays songs from before (51 times in a week). Those start from its most recent picks, so they're the songs from a day or two ago. A song under another Spotify id isn't avoided at all (Faith has three), so some came back within hours.
- [x] One song, whatever the version: songs are matched by main artist and title, with remaster, single version and radio edit suffixes taken off, instead of by Spotify id. Everything that avoids a recent song uses it: the AI's picks, songs from before, and a station skipping a song that played lately (`playlists.py`)
- [x] A week's rest: a station doesn't pick a song that played in the office in the last 7 days, or one it has lined up, instead of avoiding its last 150 picks and the last 24 hours. "Recently played means" stays as it is, for the badge on requests and for songs from before
- [x] The AI sees what's refused: the prompt lists those songs, one line each (artist and title), oldest first, and asks it to look past the obvious hits. The list goes near the start of the prompt and drops songs a whole day at a time, so through the day it only grows at the end and OpenAI bills the repeated start at its cached rate. The last 30 plays stay, so it can follow on from what's playing
- [x] Asking again: the AI is asked for 8 spares instead of 4, and when a batch comes back short it's asked once more, told which of its picks were refused and how many more are needed. Songs from before only when the second answer is short too
- [x] Songs from before, longest unheard first: from everything the station has played, then Best Voted, the song not heard for longest first, instead of starting from its last 150 picks
- [x] Saying what happened: each batch notes in the journal how many songs it got, how many of the AI's picks were refused as heard this week, how many Spotify couldn't find, and the tokens it used (in, of those cached, and out), so the real cost shows after a day at the office
- [x] The hour preview picks the same way (`rehearsal.py`)
- [x] Tests, the changelog, and the AI radio help topic (what a station avoids, and what it plays when the AI can't pick)
- [x] Songs from before fall back on anything heard in the office, after the station's own songs and Best Voted, so a new station has something to play while the AI can't pick. Best Voted was empty at the office as Keith added three stations (added after building the stage)
- [x] Deploy to office box

Done when: after a week at the office, no song comes back within 24 hours in another version, a day without a Spotify pause has no songs from before, and songs back within 48 hours are under a tenth of the station's plays (from a third).

## Stage 19: After hours
Goal: the music stays off outside playback hours unless someone wants it, and then only for a while. From backlog.md, asked for by Keith on 2026-11-15, after Xennials' Delight played on 9 November from 18:00 to 21:16 and on 10 November from 02:50 to 08:00. Someone pressed Play at 18:01, after closing, which then had no end until the next closing time. It was paused from the Sonos side at 21:16, and at 02:50 the speakers came back from restarting stopped rather than paused, which GuildFM took for its queue running out, so it started the next song.
- [x] A pause holds: paused from GuildFM or from the Sonos app, GuildFM stays paused if the speakers then stop (as they do when they restart), instead of taking it for its queue running out and starting the next song. Only Play, or a song starting on the speakers, ends it. The same after a restart of GuildFM that finds the speakers stopped
- [x] After-hours play: a new setting, "After-hours play", 4 hours by default (1 to 12). Play pressed outside playback hours plays for that long, then GuildFM stops again, as at closing time. Pressing Play again starts the time over; Stop or opening time ends it. If GuildFM finds itself driving the speakers after hours without Play (picked back up after a restart, say), the time starts then
- [x] Saying so: the setting in Settings under Playback hours, the line at the top saying until when it's playing after hours, and the Now Playing banner outside the hours saying Play plays for the set time instead of "until Stop or the next closing time"
- [x] Tests, the changelog, the Playback hours help topic and its screenshot
- [x] Deploy to office box

Done when: at the office, Play after closing stops by itself after the set hours, and the speakers restarting overnight while GuildFM is paused don't start the music.

## Stage 20: Talk stations
Goal: a station can have two or more DJs with a dynamic between them, and as a talk station it's mostly talk: banter with running bits, real news, weather and football, and the DJs interrupting and talking over each other. Asked for by Keith on 2026-11-16. The plan is [talk.md](talk.md). This stage's work, spikes included, was on the `talk-stations` branch until it was merged into main on 2026-11-17; the rest is on main.
- [x] Spike, `tools/dialogue_spike.py`: two DJs writing and voicing one link, through ElevenLabs Text to Dialogue in one request and stitched a turn at a time. Both sound fine, and cost the same (763 and 762 credits for 1,735 characters, 1 min 42 s of audio). Writing took 10.5 s and voicing 26.8 s
- [x] Spike: real overlap. Turns marked `cut_after` (the word the next DJ cuts in after) and `together`, every turn voiced at once, cut turns with timestamps, mixed with ffmpeg. For Keith to listen to, and to time parallel voicing. Keith: much better than without. 17 turns (2,579 characters) voiced four at a time in 13.4 s, about three times faster per character than one dialogue request, at the same 0.44 credits a character; telling ElevenLabs the turn before costs nothing. Writing with the marks took 20.9 s, and the writer used one cut where it could have used two
- [x] [Prototype](https://claude.ai/artifact/DEcVyXWNPxxt81zu5qZsPF) for Keith to review: the station editor with several DJs and their dynamic, the DJ hooks, and the Talk Station switch with its ratio slider and script prompt, on phone and desktop. Approved with these additions: a talk station needs two or more DJs, each with an ElevenLabs voice; the dynamic ("How they get on") belongs to the station; DJs as cards that open and close, saying their voice and their other stations; "Hear them together", a half-minute exchange played on the device (about 200 credits); the script prompt's fields highlighted in its text and listed under it with Add; and the credits line saying how many hours a month's allowance covers
- [x] Model: a station's DJs (one or more) and their dynamic; DJ hooks on each DJ (pet peeves and soft spots up to 300 characters, a running obsession up to 200, all optional); a station's Talk Station switch, talk ratio (20% to 100%) and script prompt. Migration 0025: a station's DJs in `station_djs`, in order, its DJ becoming its first; the dynamic up to 1,000 characters and the script prompt up to 4,000; the ratio 40% to start. The API keeps today's one-DJ form until the station editor's task
- [x] Named fields' data, gathered only for the fields a station's prompt uses: `[weather]` from Global Awareness; `[news]` a new gatherer for light, odd stories (no politics, tragedy or deaths); `[sports]` British football news, scores and results, nothing else; `[celebrities]` news, birthdays and anniversaries, with care over ages and deaths; `[lineup]` and `[djs]` from the database. In `fields.py`, with the web ones as topics in Global Awareness: light news kept 6 hours, football 3, and celebrities 12 but only on the day they were found. `prime()` starts looking them up ahead of a show. Tried for real on 2026-11-16: a McDonald's mural calling Blackburn Rovers "Crampions", England beating Spain 3-2, and Paul Scholes's birthday. The sources the web search adds to every line, asked not to, are taken out, from the music news too
- [x] The show plan: written when a show starts, the whole show in a line-up and an hour at a time outside one. Its running bits with their setups and payoffs, and a happening when the code's dice roll says so (4 in 10). Kept in the source's `dj_memory` with the show's state: the score, the stakes, who owes whom. In `talk.py` and `talkshow.py`. A show in a line-up that has used up its plan plays songs until it ends. Its end is kept with the plan, so later links know it
- [x] Banter moves: the bet, the challenge, the score, the correction, the wind-up, the verdict, the confession, the aside, the producer and the guest. The code deals them: one or two running bits a show, one move a link, never one of the last few, and a move that needs a hook only for a DJ who has one. A log of recent bits across shows, so a daily show doesn't repeat itself and can call back. A link's move rests for two links rather than three, since with no hooks and no other DJs only four moves are left, and resting three would deal them in a fixed order. The guest is another of GuildFM's DJs with an ElevenLabs voice, picked at random, for one segment
- [x] Writing links: the built-in rules, the station's script prompt, the plan, what's been said so far, the songs either side, and the material today's DJ gets (play history, repeat requests, votes, opt-outs). Turns as JSON with their `cut_after` and `together` marks, checked by the code: the word is in the turn, and at most one or two interruptions a link. In `script.py`. Rehearsed for real on 2026-11-17 (`tools/talk_rehearsal.py`): three segments of a lunchtime show, with the bet and the challenge carried through, the real news, weather and football, and Debbie correcting Guildbert's inches to centimetres. The DJs said "segment four" on air, so the writer is now told segments are never mentioned. Segments ran 10 to 20% over the length asked for (154 to 171 seconds for 140); left to measure at the office before tuning
- [x] Voicing with real overlap: ElevenLabs voices only, every turn at once, cut turns through the with-timestamps endpoint. Mixed with short, varied gaps; an interrupted turn cut just after its word with a quick fade and the next starting a fraction of a second before; `together` turns at the same moment. Levelled like the DJ's clips today. In `mixing.py`, with `speech.say_timed` and `audio.mix`. Each turn's clip and timings are kept like other speech; a 2.5-minute segment voiced in about 20 seconds
- [x] The talk ratio: links sized to it, and the "how often the DJ talks" controls off while it's on. A link longer than fits the 90 s lead is made in chunks of about 2 minutes, the first queued as soon as it's ready and the next made while it plays. At 100% the chunks follow each other. At 100% (Keith, 2026-11-17: requests still play) the station picks no songs: after each reading of the speakers, the talk show keeps a segment queued after whatever's on, a request's link is one segment bringing it in, and the talk carries on after it. Play with nothing lined up starts the talk once its first segment is made, about half a minute later, as does opening time. The "how often" controls going off is in the station editor's task
- [x] Skips: listeners can't skip a link, curators can with Skip, and the next link is told what wasn't heard, with the plan adjusted to match. The queue tells the talk show what was playing when Skip was pressed; a segment is known by its clip. The skip is told to the next segment written, once
- [x] The station editor and its API, as in the prototype. The API takes a station's DJs as a list with their hooks, the dynamic and the talk settings, and refuses a talk station without two or more DJs with ElevenLabs voices, or a ratio outside 20% to 100%. In the editor: several DJs and the dynamic, the hooks under Personality (with their hint, and saying which other stations a change applies to), the Talk Station switch, the ratio slider (red above 70%, "about N credits an hour" beside it) and the script prompt with its named fields, highlighted in its text and listed under it with Add. "Hear them together": a half-minute exchange between the station's DJs, written and voiced the way links are, played on this device
- [x] Saying what it cost: the journal notes each link's credits, characters, and time to write and voice, so the real cost shows after a day at the office. Each segment's line in the journal: seconds of talk, turns, characters, ElevenLabs credits (from the `character-cost` each turn's request returns, nothing for turns voiced before), and the seconds to write and to voice it
- [x] Tests, the changelog, the help (The DJ topic for the hooks, a new topic for talk stations) and their screenshots. The demo office has a talk station, The Lunch Break, with Guildbert and Debbie, and its covers are repainted with the new cover prompt
- [x] Deploy to office box. 0.1.8, on 2026-11-17, with the DJs' hooks copied over and every station's and line-up's cover repainted with the new prompt

Done when: a lunchtime talk show with two DJs runs from a line-up at the office, with a running bit set up early and paid off later, the DJs interrupting and talking over each other, the real weather and football in it, a skipped link not paid off, and the journal's credits close to the slider's estimate.

## Stage 21: Making and editing stations
Goal: making a station is a few plain steps that start with what kind of station it is, and editing one changes one part at a time. Asked for by Keith on 2026-11-20: since talk stations and several DJs, the station editor had grown hard to follow. Turning a station into a talk show needed two DJs, each with an ElevenLabs voice, set up in another part of the page before the Talk station switch would turn on, and settings that didn't apply were greyed out rather than gone.
- [x] [Prototype](https://claude.ai/artifact/26Z8W9NGzMmfKqymwvNGiG) for Keith to review: A, a step-by-step wizard; B, the same on one page with a side panel for DJs; C, editing a station made with A. Each on desktop and phone, with the office's real DJs, and The Squawk Box's real settings for C. Keith picked A for making a station and C for editing one (2026-11-20); B isn't built. Additions in the prototype that are part of the plan: "Suggest one" for how the DJs get on, an hour strip under the talk slider, "Bring in" chips for the script prompt's fields, talk shows offering only ElevenLabs voices, and hooks only asked for on talk shows
- [ ] The three types: Just music (no DJs), Music with a DJ (one DJ, talking as often as its settings say) and Talk show (two to six DJs with ElevenLabs voices, sized by the talk ratio). Nothing new to store: the type is read from the station's DJs and its Talk Station switch, and saved as them. A station with two or more DJs that isn't a talk station shows as Music with a DJ, keeping its first DJ when its DJ step is saved (none on the office box today)
- [ ] The steps, each one piece of UI used by the wizard and by the station page's dialogs: Type; Name and music (with example descriptions to start from); DJ or Hosts; Talking (Music with a DJ) or The show (Talk show); Extras. They replace `StationEditor.tsx`, `StationDJs.tsx` and `TalkStation.tsx`
- [ ] Type: three cards, each with a line on what it is and what it costs (no voice credits; about 90 credits a line; 5,400 to 27,000 credits an hour). Picking Talk show says that it needs two or more DJs with ElevenLabs voices, and whether the office's DJs have them. Talk show can't be picked while ElevenLabs isn't set up, and says why
- [ ] DJ or Hosts: the office's DJs as cards (their personality in a line, the other stations they host, Hear for a phrase in their voice). One for Music with a DJ; two to six for a talk show, numbered in the order picked. New DJ opens a form in place: name, personality, voice (the real list from ElevenLabs, plus OpenAI's for Music with a DJ only) and, for a talk show, the hooks, saying each show uses one or two of them. A DJ's card can open the same form to change them, saying which other stations the change applies to
- [ ] Talking: how often (Every song, Every few songs, Now and then, or Let me choose a number of songs or minutes), what they say (Just the songs, or Songs and stories), saying who asked for a song, and a sample line of what that sounds like. Saved as today's `talk_every`, `talk_unit`, `style` and `announce_requests`
- [ ] The show: the talk slider with an hour strip of talk and music, red above 70%, the credits an hour and how many hours the month's allowance covers. What it's about, with "Bring in" chips that put a field (`[news]`, `[weather]` and so on) into the prompt or take it out, and the line that it's a guide GuildFM strays from for variety. How the DJs get on, with "Suggest one" (the AI writes it from their personalities, a new endpoint) and "Hear them together". Saying who asked for a song
- [ ] Extras: Play jingles, Crossfade between songs and Knows what's going on (global awareness), each with its line, and a note that the cover is painted once the station is made
- [ ] The wizard at `/radio/new`: only the steps the type needs (Just music skips DJ and Talking). A stepper across the top on a desktop, "Step 2 of 6" with a progress bar on a phone. Next names the next step and says what's missing instead of greying out without a word; steps already reached can be jumped back to. A "Your station" card on a desktop that fills in as you go. Review lists every choice with Change, and Preview an hour (not at 100% talk). Create opens a ready screen: Put it on now, Give it its own jingles, Back to Radio. Changing the type after going further keeps what's been filled in, and leaving with anything filled in asks first, as today
- [ ] The station page at `/radio/:id`: the review's summary as cards (type, name and music, DJ or hosts, talking or the show, extras), with Hear on each DJ and Hear them together on the show. Put it on and Preview an hour at the top on a desktop and in a bar along the bottom on a phone. What only a made station has: the cover with Paint another, its own jingles (play, upload, or make more with the jingle generator) and Delete
- [ ] Change opens that one step, as a dialog on a desktop and a full-screen sheet on a phone, on a copy of the station, with its own Save and Cancel. Save saves the station straight away (`PUT /stations/{id}` as today) and says so. A new type chains the steps it needs: to Music with a DJ, then which DJ and how they talk; to Talk show, then the hosts and the show; to Just music, saved straight away, saying the DJs come off this station but stay for others. Picking the station's own type again puts its DJs back as they were
- [ ] The Radio page: New station opens the wizard, and a station's card opens its page
- [ ] Tests (the Suggest one endpoint; a type change saved through the API), build and typecheck, the changelog, the help (Making a station, The DJ, Talk stations, the station's own jingles) and their screenshots, and a What's new note
- [ ] Deploy to office box

Done when: at the office, someone makes a music station, a station with a DJ and a talk show through the wizard without meeting a greyed-out control, changes The Squawk Box's mix from its page with one Change, and turns a station with a DJ into a talk show by being walked through its hosts and the show.

## Stage 22: Just a name
Goal: the display-name check turns down a name with a description added, such as "Gary from Nottingham", every time, however it's written and however often it's tried. Asked for by Keith on 2026-11-20. That morning the sign-up form turned "Gary from Nottingham" down, he signed up as "Gary Nottingham", and Profile then took "GARY FROM NOTTIGHAM". The check ran both times; its verdict on names like these is close to a coin toss, so trying again, or changing the capitals or the spelling, gets through. Five checks of each, with today's wording:

| Name | Turned down | Allowed |
|---|---|---|
| Gary from Nottingham | 4 | 1 |
| GARY FROM NOTTINGHAM | 3 | 2 |
| Gary from Nottigham | 4 | 1 |
| GARY FROM NOTTIGHAM | 1 | 4 |
| Gary Nottingham | 0 | 5 |
| Sam in Accounts | 5 | 0 |

- [ ] The rule said plainly: the AI is told that a name with something added to describe the person (where they're from, their job, their team, a title or a tag line) is not a name, with examples ("Gary from Nottingham", "Sam in Accounts", "Dave the plumber", "Priya (marketing)"), and that capitals, spacing and misspellings don't change the answer. Real names that look a little like that stay fine, such as "Ahmed bin Rashid", "Jan van der Berg" and "Leonardo da Vinci", and so do everyday nicknames like "Big Mike" (`names.py`)
- [ ] Its own message: a third verdict for a described name, so the form can say what to change ("Just your name, please: leave out where you're from or what you do.") instead of "That doesn't look like a name"
- [ ] Measured before it ships: `tools/name_check.py` runs the check five times on each of a list of names that should be turned down (the table's, misspelt and in capitals, plus others) and a list that must stay fine (the examples above and every display name at the office today), with today's wording and the new one. The new wording ships when it turns every described name down five times in five and allows every real name five times in five
- [ ] Steady answers: if the wording alone doesn't get there, the check asks three times at once and turns a name down if any answer does. A name check is one small call and names change rarely, so three cost next to nothing. Rude names, which the AI already calls consistently, stay as they are
- [ ] Names already taken aren't checked again. Gary's (user 20, "GARY FROM NOTTIGHAM") is changed by an admin with Rename (Stage 17), not by this stage
- [ ] Tests (the new verdict and its message on sign-up and Profile, and three answers with one turning the name down), the changelog, and the Profile help topic if its wording changes
- [ ] Deploy to office box

Done when: at the office, "Gary from Nottingham", in any capitals or spelling, is turned down on the sign-up form and on Profile however many times it's tried, with a message that says to leave the description out, and everyone else's names still go through.
