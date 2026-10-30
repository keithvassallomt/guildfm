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
