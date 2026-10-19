# GuildFM Development Plan

The build plan for GuildFM. The spec is [stream.md](stream.md) and the UI reference is the [prototype](https://claude.ai/artifact/J9FURLqbP6ryuCQWhe6UWo) (copy in `prototype/`).

Work goes stage by stage, in order. A task is ticked when it is built and tested. A stage is ticked in the overview when all its tasks are.

Every screen is mobile first and responsive: it has to work on a phone and look like a normal web app on a desktop browser.

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
- [ ] Stage 10: AI radio
- [ ] Stage 11: Hardening and handover

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
- [x] The DJ and jingles between songs go into the Sonos queue just before their song, so every room plays them in step, after Keith still heard a little reverb from overlay clips. They come back out once played; announcements and the DJ over the start of a song stay overlay clips (added after building the stage)

Done when: a station with a DJ plays for an hour, announces a request by name, and mentions the Carlisle weather.

## Stage 11: Hardening and handover
Goal: GuildFM runs unattended on the office machine.
- [x] After a restart, GuildFM carries on driving the speakers if they're still playing its queue (done early, after trying Stage 8)
- [x] After a restart, GuildFM still says someone took over from the Sonos app, whether that happened before the restart or while it was down (from backlog.md)
- [x] After a restart, the DJ still knows why each song was picked, and the jingles the AI marked still play: both are kept in the database rather than in memory (found while building)
- [x] After a restart, the DJ remembers what it said lately, where it talked and how many songs since it last did, so it doesn't open with the weather after every restart. Kept with the playing source, so it starts afresh, and talks on the first song, each time a station comes on; before, that only happened the first time after startup. The DJ is always told to bring up the weather, time or news only now and then, naming just the time without global awareness (found while building)
- [x] The DJ's album shout-out goes on an album's first song even across a restart, and again when the same album is queued another time: whether it has started is read from the play history rather than remembered (found while building)
- [x] Monitor mode (Settings, admins): GuildFM plays in browsers instead of on the Sonos speakers, songs as beeps for their real length and the DJ, jingles and announcements for real, with "Listen here" at the top of every page. Turning it on or off stops the music and waits for Play; it stays on through a restart (added after building the stage)
- [x] Graceful failure: speakers offline (a clip still plays in the rooms that answer), Spotify token expired, OpenAI and ElevenLabs errors including running out of credit, and the weather or a cover failing. The music keeps playing and the DJ goes quiet. An announcement whose ElevenLabs voice fails is read out in the OpenAI announcement voice instead. A station whose AI can't pick plays songs from before (its earlier picks, then its older plays, then Best Voted) rather than going silent (decided while building)
- [x] Logging and a simple status view for admins (Admin, Status): the speakers, Spotify, OpenAI, ElevenLabs (with the credits used this month), the weather, whether ffmpeg was found, the backups and disk space, and recent problems from the log. Each service is judged by how GuildFM's own calls to it went, not by test calls
- [x] Run as a service: a systemd unit (`deploy/guildfm.service`) rather than Docker, ffmpeg in the setup steps, old speech clips cleared out daily rather than only at startup, and `scripts/update.sh` for updates. An empty `AUDIO_LOUDNESS=` no longer stops GuildFM starting (found while building)
- [x] Backups: daily zips of the SQLite database and the uploaded media (jingles, covers, profile photos), the last 14 kept, in `data/backups` or `BACKUP_DIR`, and `guildfm backup` for one now. Speech clips are a cache and are left out
- [ ] Moving in: GuildFM installed on the office machine following the README, with a backup from the laptop unzipped into its data folder, or a fresh start with the jingles uploaded again from `assets/jingles`
- [ ] Reaching GuildFM: `guildfm.local` advertised over mDNS (Avahi, in the README), and checked on the office's phones and laptops (older Android phones may not resolve `.local` names). Then decide on HTTPS. A `.local` name can't get a certificate browsers trust, so HTTPS means a hostname on a company domain (Let's Encrypt through a DNS challenge, behind Caddy). On plain HTTP, iPhones still add GuildFM to the home screen, and Android and desktop get a shortcut that opens a browser tab. The speakers keep fetching clips over plain HTTP either way
- [x] README: setting up the Spotify app, the redirect URI and `.env` (OpenAI, and ElevenLabs if wanted), installing ffmpeg, and running GuildFM. Spotify only accepts an HTTPS or `127.0.0.1` redirect, so without HTTPS, Spotify is connected from a browser on the machine itself or through an SSH tunnel. Also what it costs to run: OpenAI for the DJ's lines, voices and covers, and ElevenLabs credits per line
- [ ] Full end-to-end run on the office speakers: requests and votes, a whole album, a station with an ElevenLabs DJ and its jingles, an announcement in chosen rooms, and installing GuildFM on a phone

Done when: GuildFM survives a restart of the machine and a day of normal office use without anyone touching it.
