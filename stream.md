# GuildFM

GuildFM is a web application running over the local network. It lets everyone in the office queue, vote on and manage the music playing on the office Sonos system, with AI announcements and AI radio stations.

UI prototype: [GuildFM Prototype](https://claude.ai/artifact/J9FURLqbP6ryuCQWhe6UWo) (private to Keith). A copy of its screens is in `prototype/`.

## Terms
- **Queue**: the live list of upcoming tracks that everyone sees and votes on. There is one queue for the whole office.
- **Playlist**: a saved list of tracks that can be played (for example, the Best Voted playlist, or one a curator created or imported).
- **Station**: an AI radio station, which picks its own tracks and can have a DJ.
- **Source**: the playlist, station or line-up that keeps the music going when nobody has requested anything.
- **Request**: a track a user adds to the queue. Requests always play before tracks from the source.
- **Jingle**: a short ident an AI station plays between songs. A **system ident** is GuildFM's own, for any station; a **station ident** belongs to one station.
- **DJ**: a voice with a name and a personality that talks between songs on an AI station. One DJ can host several stations.
- **Line-up**: a plan for the day, like a radio station's schedule: which AI station or playlist fills the gaps between requests at each time of day. An AI station on a line-up is a **show**.

## Users and Roles
- Users must register an account and log in to access the system. Users can create their own accounts.
- An initial admin account is seeded to the system.
- Admins can delete accounts, though not their own. Deleting someone signs them out straight away, and their queued requests and votes go with them.
- There are three roles: user, curator and admin.

| Permission | User | Curator | Admin |
|---|---|---|---|
| Search and add tracks (up to the per-user cap) | Yes | Yes | Yes |
| Vote tracks up or down | Yes | Yes | Yes |
| Remove their own tracks | Yes | Yes | Yes |
| Remove any track, reorder the queue, override votes | | Yes | Yes |
| Add a whole album to the queue | | Yes | Yes |
| Create and import playlists | | Yes | Yes |
| Create AI stations | | Yes | Yes |
| Plan line-ups | | Yes | Yes |
| Start or switch playlists, AI stations and line-ups | | Yes | Yes |
| Play, pause, resume, skip and previous | | Yes | Yes |
| Volume and stop | | | Yes |
| Create announcements | | | Yes |
| Manage users (create accounts, reset passwords, promote to curator or admin, delete accounts) | | | Yes |
| Change settings | | | Yes |

### Profile settings
- Display name: the name the DJ reads out when announcing a request.
- Announce my requests: on by default. Users can opt out.
- A photo: optional. After choosing one, the person picks the part to use in a round frame, dragging the photo about and zooming in (pinch, scroll or a slider). It's cropped to that square and shrunk in the browser before it's sent, and shown as a circle wherever the person is named: beside their requests, in the play history, on the Users page and in the header.

## Main UI
- A responsive web application will be built to allow users to interact with the system. The main UI will include:
  - A dashboard displaying the currently playing track, upcoming tracks, and user activity.
  - A search feature to find tracks and artists, straight from the Queue screen ("Request a song"), so people can request songs without leaving the queue.
  - A queue management system for users to add tracks, and remove their own.
- The application should be MOBILE FIRST, and responsive: designed for phones first, but on a desktop browser it uses the space properly (sidebar navigation, wider content, more columns where they help) instead of looking like a small portrait app.
- The tabs: Now Playing, Queue, Playlists and Radio (curators and admins), and Admin (admins). In the desktop sidebar, Admin's pages (Announcements, Jingles, Users, Settings and Status) are listed under it; on phones they're links on the Admin page.

## Now Playing
- The screen everyone lands on, and the first tab. The Queue screen stays its own tab, for requesting and voting.
- Shows the current song, how far through it is, and where it came from: a request (and who asked), a playlist, or an AI station.
- While an announcement, the DJ or a jingle is on, Now Playing and the Queue show GuildFM's logo in place of the song's cover.
- Curators and admins get the playback controls here. Admins also get the office volume, each room's volume behind a "Rooms" toggle, Stop all, and an Announce button for a quick one-off announcement in every room (picking rooms and scheduling are on the Announcements page). These are the only full playback controls: the Admin page just links to Announcements, Users and Settings.
- The sources: Queue, Playlists, Radio (AI stations) and Line-ups. Playlists and Radio are sorted by when they last played, most recent first. The queue keeps its vote order.
- The source the current song came from is highlighted and animated. Requests always play first: a picked playlist or station fills the gaps between them, and says so while a request is playing.
- Curators and admins switch source by picking a playlist or station, which takes over after the current song. "Requests only" means nothing fills the gaps.
- Below the sources: the songs played today, newest first, each with where it came from.
- On a desktop, now playing and the controls sit on the left, and each kind of source is a band of tiles, with a needle on the one on air. On a phone, the sources are three tabs under the now playing card.
- On phones, Profile moves to an avatar in the header, keeping the bottom tabs to five.

## Queue and Voting
- Users can vote tracks up or down, using thumbs up and thumbs down. The system automatically orders the queue by votes.
- A track whose score falls to the downvote threshold is removed from the queue. The threshold is a setting.
- Users can remove their own tracks, but only their own.
- Each user can have a limited number of tracks in the queue at once. The cap is a setting (default: 5). Admins have no cap.
- A track that is already in the queue cannot be added again.
- Tracks played recently show a warning badge (for example, "played 2 hours ago") in search and in the queue, but can still be added.
- Explicit tracks are blocked by default: hidden from search, refused as requests, and left out of albums and AI stations. Admins can allow them in settings.
- Songs Spotify says can't play in the UK are left out everywhere: search, albums, imported playlists, and so AI stations' picks.
- Curators and admins can add a whole album to the queue: albums show up in their search, and opening one lists its songs, with a button to queue them all (or the ones not already queued). They go in as that person's requests, in the album's order, and don't count towards the cap. Votes move them like any other request. Songs already in the queue stay where they are, and explicit ones are left out when they're turned off. The DJ names the requester on the album's first song only, and the queue marks the songs as part of a whole album.
- Curators can manage the queue without voting: override votes, reorder tracks, and remove any track. Curators and admins reorder by dragging a request (press and hold on a phone), or with the up and down arrows. A request's actions (the arrows, and remove) are tucked behind a small arrow on its right, which slides them out when tapped.
- Votes reorder everything after the next track. GuildFM hands the next track to Sonos shortly before it plays, so that one is locked.

## Playback
- Curators and admins can play, pause, resume, skip and go back. Only admins change the volume and stop. Previous goes back a song in the first few seconds of one, and otherwise starts the current song again. It's greyed out when going back would jump over a song already lined up on the speakers.
- Admins also get a floating button on every screen except Now Playing, which has the controls, that opens quick controls: previous, play, pause, skip, stop all, and the whole-office volume.
- **Stop** halts all playback, including announcements and the DJ, until play is pressed again.
- **Play** continues whatever was playing before (a playlist, an AI station, or the queue).
- **Playback schedule** (setting): the hours GuildFM plays, for example weekdays 08:00 to 18:00. Outside these hours it behaves as if stopped, so scheduled announcements don't play either.
    - At opening time, GuildFM starts playing by itself if there's something to play, taking over the speakers as if Play was pressed. With nothing to play yet, it starts as soon as someone makes a request.
    - At closing time, it stops everything, as if Stop was pressed.
    - A Stop during playback hours lasts until someone presses Play or the next opening time, whichever comes first.
    - A curator or admin can press Play at any time. Outside playback hours this overrides the schedule: GuildFM plays until someone presses Stop or the next closing time comes round.
- **When the queue runs out** (setting), one of:
  1. Restart the current playlist. If no playlist is playing, fall back to option 3.
  2. Play a default AI station. With none chosen, fall back to option 3.
  3. Ask the AI for a next track that fits the music played so far. This is the built-in AI picks station, which follows what's been playing.
- The queue runs out when there are no requests left and nothing is filling the gaps: a playlist played to the end, or nothing was ever chosen. Choosing "Requests only" on Now Playing is different: nothing fills the gaps and nothing takes over, so the music stops when the requests do.

### Outside control
- If someone changes the music from the Sonos or Spotify app, the outside change wins. GuildFM stops everything it is doing (queue, playlist, station, DJ and announcements), the same as pressing Stop, and leaves the speakers alone.
- The dashboard shows that GuildFM has been overridden. Pressing Play takes control back and continues what was playing before.
- If the Arc is switched to the TV, it just drops out of the group. GuildFM carries on in the other rooms.
- If GuildFM restarts while the speakers are still playing its queue, it carries on where it was. Anything else on the speakers after a restart is left alone until someone presses Play.
- GuildFM keeps its own place on the speakers. Their queue holds a few songs that have played (for Previous), the song on now and what's lined up after it; anything else comes off. When the speakers stop, Sonos goes back to the start of its queue, but GuildFM carries on from its own place.
- A lined-up song the speakers don't start gets a second try after a few seconds, often enough after a hiccup, so the song the DJ just introduced still plays. If it doesn't start then either, it's skipped and the next one plays, and the activity on the Queue screen says so.

### Monitor mode
- An admin can switch on monitor mode in Settings, to try GuildFM out without the office hearing. GuildFM then plays in browsers instead of on the Sonos speakers.
- Songs become beeps, each lasting as long as the real song, with a different note per song. The DJ, jingles and announcements play for real, announcements whatever rooms they were for, and the beeps go quiet under anything said over them. Everything else (the queue, votes, stations, the DJ's timing, playback hours) works as it does on the speakers.
- Turning it on stops the music on the speakers, and GuildFM waits for Play, carrying on from the same song. Turning it off does the same the other way round. It stays on through a restart.
- While it's on, admins see a bar at the top of every page with "Listen here", which plays it in that browser (browsers only play sound after a click). Any number of browsers can listen at once.

## Playlists
- Curators and admins can create playlists in GuildFM, or import them from Spotify by pasting a playlist link.
- Whole albums can go into a playlist too. When adding songs to a playlist, albums show up in the search alongside songs and artists; opening one lists its songs, to add all of them or just some. Pasting an album link into the import box makes a playlist named after the album, in track order. Songs that can't play in the UK are left out, and so are explicit ones when they aren't allowed.
- Curators and admins can play any playlist. A playing playlist fills the gaps: requests always play first.
- Switching to another playlist takes effect after the current song. A playlist that's switched away from keeps its place, and carries on from there when it's put back on; once it plays to the end, it starts afresh.
- Each playlist has a Shuffle switch: off by default, on by default for Best Voted.
- While a playlist is playing, the Queue screen shows its next 3 songs under the requests. Anyone can give them a thumbs down; enough of them (the same threshold as requests) skips that song this time round. There's no thumbs up for them, since a playlist keeps its own order.

### Best Voted playlist
- There is one Best Voted playlist, maintained automatically.
- A track that gets more than X upvotes goes into it (setting, default: 5).
- The playlist holds up to Y tracks (setting, default: 50).
- When the playlist is full and a new track qualifies, the track with the fewest upvotes drops out. If several tracks tie on fewest upvotes, the oldest entry drops out.
- A new track only gets in if it has at least as many upvotes as the track it would replace.

## Announcement System
- Announcements are audio only, played on the speakers. Only admins can create them.
- The admin types the announcement as text, and it is read out by text-to-speech in the announcement voice from settings (see Voices). With an ElevenLabs voice, the text can include tags such as [excited]: the editor and the quick announcement have an "Add an emotion" list that puts one in at the cursor, and say which voice will read it, by name.
- When an announcement is created, there will be options:
    - Which speakers to broadcast to (all, or specific speakers). Rooms playing the TV are left out.
    - Whether to play the announcement immediately or schedule it for a later time.
    - Whether the announcement plays over the current track or waits until the current track is finished.
    - A schedule: just once, every day, weekdays, chosen days or every hour (at the same minutes past), from a start date and time, with an optional end date.
- The admin can preview the announcement in the browser before it goes out.
- After the current song is the default. For every room, the song plays to its end, then the announcement, then the next song: it goes through the Sonos queue, so every room plays it in step (see Rooms in step). For chosen rooms, GuildFM pauses the music just before the current song ends, plays the announcement in those rooms, then starts the next song. Over the music, the music goes quiet while the announcement plays, then comes back up. If the music is paused or has run out, it plays straight away.
- Over the music, and in more than one chosen room, each room plays the announcement by itself, so the editor and the quick announcement warn that there may be a slight echo between rooms.
- Scheduled announcements have an on/off switch, can be edited or deleted, and have "Play now", which plays one straight away over the music without changing its schedule.
- Announcements always take precedence over the DJ.
- Announcements don't play while playback is stopped or outside the playback schedule. A paused GuildFM still plays them. "Play now" works whenever GuildFM is playing or paused, even outside playback hours.
- One that comes due while GuildFM can't play it is let go, not saved for later, and shows as missed under "Recently played". Repeating announcements keep to playback hours without that note, so "every day" means every day GuildFM is open.

## AI Radio
- Admins and curators can create AI radio stations, edit and delete them, and start them. A station fills the gaps between requests, like a playlist, and takes over after the current song.
- There's one built-in station, AI picks, which follows what's been playing. It can be started like any other, but not edited or deleted.
- The user will specify:
    - The name of the station.
    - A description of the station, such as the genre or mood of the music to be played.
    - The personality of the DJ, if any. The DJ is optional, and is a text-to-speech voice that announces the tracks being played, or provides commentary on the music.
    - Global awareness. If enabled, the AI takes into account the time of day, the current weather, and current events to influence the music selection.
    - Crossfade between songs (off by default). While the station fills the gaps, on its own or as a line-up's show, the speakers fade each song into the next, hiding the quiet at their starts and ends. Anything else plays without it. The DJ, jingles and announcements never fade: Sonos fades for about 10 to 15 seconds (going by its users; it doesn't say), longer than most of them, so GuildFM turns crossfade off while one is in the queue or playing, and back on once the song after it starts.
- If a DJ is used:
    - Which DJ: one made for another station, or a new one. A DJ is their name, personality and voice, and is kept as a DJ of their own, so they can host any number of stations. Changing a DJ's name, personality or voice from any of their stations' editors changes them on all of them, and the editor says which other stations that is. A DJ is kept when no station has them any more, ready for another. Each DJ's name is their own.
    - The DJ's voice, picked from the OpenAI voices or the ElevenLabs account's own.
    - How often the DJ interjects (for example, every 10 minutes, after every X tracks, etc.).
    - Whether the DJ just announces the track, or provides commentary on the music being played.
    - Whether to announce requests.
    - How often the DJ talks, what they say and whether they announce requests are up to each station, not the DJ.
- The DJ talks between tracks, never over one: the song plays to its end, then the DJ, then the next song, so every room hears it in step (see Rooms in step). A line that isn't ready before its song starts is let go.
- The DJ talks on the first song after the station comes on, then as often as the station says. It always announces a request (when announce requests is on and the requester hasn't opted out), whatever the timing.
- The DJ always knows the time of day, so it never says good morning in the afternoon. Global awareness adds the weather and the news.
- The AI picks tracks by name, a batch at a time. GuildFM finds them on Spotify through search, and leaves out anything played recently, picked by the station lately, already queued, or explicit when explicit tracks are turned off.
- While a station plays, the Queue screen shows its next 3 songs, and anyone can give them a thumbs down, as with a playlist.
- A station never plays a song that played recently, even one it picked before someone requested it.
- If the AI can't pick (OpenAI or Spotify is down, or out of credit), the station carries on with songs heard before, so the music doesn't stop: its own earlier picks, then songs it played longer ago, then Best Voted, each the longest since played first, and still nothing played recently. The AI is asked again when those run low.
- The DJ can comment on requests and the people who make them, with good-natured teasing if it suits the personality. It knows how often the song and its artist have played in the last week, who asked for it before, the votes, and what else the requester has asked for. Nobody who opted out is named.
- The DJ remembers its last few lines, so it doesn't keep repeating the weather or the time.
- Each station has a cover, standing in for album art: OpenAI paints it from the station's name and description, with the name on it as the only text. A new station gets one in the background once it's created, and a new name or description gets a new one. Curators can ask for another from the editor (Paint another), painted from the name and description as they are in the editor, saved or not; saving those afterwards doesn't paint another. Stations without one, such as AI picks, get theirs when GuildFM starts. If OpenAI can't paint one, the station keeps its old cover, or the radio icon. Each costs a few cents.
- Leaving the station editor with changes that haven't been saved asks first ("Leave without saving?"), and so does closing or reloading the tab.
- From the station editor, curators can preview an hour of the station as they've set it up, saved or not: the songs, with when each would start, the jingles, and what the DJ would say before each song, each playable in the DJ's voice. It takes about a minute, nothing is kept, and requests would change the real hour.

### Jingles
- Admins upload system idents (GuildFM's own) under Admin, Jingles. Curators upload a station's station idents in its editor, once it's saved. They're MP3s of up to a minute, and can be previewed on the device, not the speakers.
- Any AI station can play system idents, and each plays its own station idents. AI picks plays system idents only. Each station has a "Play jingles" switch, on by default.
- The AI that picks a station's songs also marks the odd one to have an ident before it, and which kind, aiming for about one song in four, at a change of mood or the start of a new run. It's only offered the kinds there are to play.
- A jingle plays between songs, never over music: the song plays to its end, then the jingle, then anything the DJ says between songs, then the next song. If that song starts before the jingle is lined up, the jingle is let go.
- Never at two song changes in a row, and never the same jingle twice running when there's another of its kind. Requests don't get jingles, and announcements still go first.
- Deleting a station deletes its station idents.
- The originals are in `assets/jingles`: two system idents, and six station idents for Xennials' Delight (which replaced its first three). Uploads are levelled to about -14 LUFS, like the voices; the ones in use also had silence trimmed off the end first.

### Voices
- The DJ and announcements can use OpenAI's voices or the ElevenLabs account's own voices (such as Guildbert). The station editor and settings list them apart, under "OpenAI" and "ElevenLabs".
- ElevenLabs voices are optional: they need ELEVENLABS_API_KEY in .env, and the list comes from the account, so a new voice made there shows up within a few minutes.
- ElevenLabs voices understand tags in square brackets, such as [laughs], [sighs], [excited] or [whispers]. On an ElevenLabs voice the DJ uses one or two now and then, where they suit its personality. OpenAI would read tags out, so they're taken out for OpenAI's voices.
- OpenAI's voices take the DJ's personality as delivery instructions. ElevenLabs voices go by their settings in ElevenLabs and the tags.
- ElevenLabs uses credits: about 0.45 a character on eleven_v4 (the default), going by the account's history, and half that on eleven_v4_turbo. A typical DJ line is about 150 characters, so about 67 credits. A clip is only made once for the same words in the same voice, so a repeating announcement costs nothing after the first time. The Status page shows the credits used this month.
- If ElevenLabs can't speak (out of credits, a deleted voice), the DJ stays quiet, and an announcement is read out in OpenAI's Cedar voice instead, since the message matters more than the voice. A preview still says what's wrong, so the voice can be put right.

### Voice preview
- While picking a DJ's voice, the user can preview it with a built-in phrase or one they type.
- The preview is spoken in the DJ's personality (for example, a laid-back late-night DJ sounds different from an upbeat breakfast DJ in the same voice).
- Previews play in the browser, not on the office speakers.
- The announcement voice in settings can be previewed the same way.

### Global awareness
- Weather comes from the location in settings (default: Carlisle, Cumbria, UK), through Open-Meteo.
- The news comes from an OpenAI web search, refreshed every few hours in the background. It takes up to a minute, so a station put on for the first time picks its first songs without it.
- There are no news bulletins. Instead, current events steer track choices and DJ commentary. For example: playing a track by an artist who has just passed away, or a song that has just won a song contest, and commenting on it. Commentary on sad news should be respectful.

### Requests and voting on stations
- User requests take precedence over the station's own tracks. The station resumes once there are no requests left.
- If announce requests is on, the DJ announces the request and the display name of the user who made it, unless that user has opted out. If announce requests is off, the DJ does not announce requests.
- Users can vote on station tracks. Votes do not teach the station, so its taste isn't polluted.

## Line-ups
- Curators and admins plan the day as line-ups on the Line-ups page, and put one on from there or from Now Playing. A line-up is picked by hand; it isn't tied to days of the week.
- A line-up has a name, a description, and a cover that OpenAI paints from them, like a station's.
- The editor shows the day as a bar from the earliest opening time to the latest closing time in the playback hours. On a desktop the bar runs across the screen; on a phone it runs down it, like a calendar's day view.
- Shows and playlists go onto the bar, snapping to 15 minutes, and never overlap. On a desktop they're dragged on and moved by dragging; on a phone they're added with a start and an end time.
    - A show runs for as long as its slot, which can be moved and resized.
    - A playlist's slot starts as long as the playlist, and can be shortened but not lengthened.
    - Gaps are allowed. During one, "When the queue runs out" decides what plays.
- A note on the editor says requests can shift the timings a little.
- Slots run by the clock. Each starts at the first song change after its start time, so requests can make it start up to a song late, but the day never drifts. A playlist that hasn't finished when its slot ends is cut off there, and one that runs out before its slot ends starts over.
- On a day with shorter playback hours, the slots outside them don't play.
- Hand-overs: when a show starts, its station ident plays (if it has one and jingles are on), then its DJ, if it has one, says what's on and until when. The show's station picks its first songs up to ten minutes ahead, so it starts without waiting for the AI.
- Picking a line-up on Now Playing makes it the source, starting with the slot that covers the time now. It stays the source from day to day until someone picks something else: a playlist, a station or "Requests only" ends it, as switching source always does. At opening time GuildFM starts with the slot that covers it.
- On Now Playing, the Line-ups band sits with Queue, Playlists and Radio, and is a fourth tab on phones. It lists the line-ups as tiles. Once one is on, the band shows its slots along a time strip, with the needle moving with the clock over what's on and what's next, and a back button to the list.
- Line-ups has its own place in the sidebar on a desktop. On a phone it's reached from Now Playing's Line-ups tab, keeping the bottom tabs to five.
- Deleting a station or playlist leaves a gap where it was on any line-up, even while the line-up is playing it. Deleting the line-up that's on means nothing fills the gaps, as when a playing playlist is deleted.

## As an app
- GuildFM can be installed as an app, opening from the home screen or dock in its own window, with its own icon. Profile has a section on it: an Install button where the browser offers one, and on an iPhone or iPad, Safari's two steps (Share, then Add to Home Screen). It's hidden when GuildFM is already running as the app.
- Chrome, Edge and Android only offer to install over HTTPS (or on the machine itself), so in the office that needs GuildFM behind HTTPS. Over plain HTTP, their "add to home screen" is a shortcut that opens a browser tab.
- There's no offline mode: GuildFM needs the office network and the server, as before.

## Looking after GuildFM
GuildFM runs unattended on an always-on machine in the office. How to set it up is in the [README](README.md).

- **Status page** (Admin, Status): the speakers, and each outside service GuildFM uses (Spotify, OpenAI, ElevenLabs with its credits this month, the weather, ffmpeg), each shown as working, needing a look, not used yet or off, with when it last worked or failed and why. Also the backups, the space left on the disk, and the latest problems from the log, with how many times each happened. Nothing is tested specially: each service is judged by how GuildFM's own calls to it went.
- **When things fail**, the music keeps playing. The speakers being offline is retried every few seconds, and a room that doesn't answer doesn't stop an announcement in the others. If the AI can't pick songs, stations play songs from before (see AI Radio). If a voice can't be made, the DJ goes quiet, and announcements fall back to an OpenAI voice. The weather, the news and covers are left out until they can be had.
- **Logs** go to the console, which is the system journal when GuildFM runs as a service, and the latest warnings and errors show on the Status page.
- **Backups**: once a day, a zip of the database and the uploaded media (jingles, covers and profile photos), the last 14 kept, in `data/backups` or wherever `BACKUP_DIR` in `.env` says. `guildfm backup` (or `make backup`) makes one straight away. Restoring is unzipping one into the data folder while GuildFM is stopped.
- **Clearing out**: speech clips nobody has used for 30 days are deleted once a day.
- **Reaching it**: the machine is named `guildfm`, so people open `http://guildfm.local:8000` (mDNS). Browsers only offer to install GuildFM as an app over HTTPS; on plain HTTP, iPhones can still add it to the home screen, and Android and desktop get a shortcut that opens a browser tab. HTTPS would need a hostname on a company domain, since a `.local` name can't get a certificate browsers trust.

## Settings (admin)
- Track cap per user (default: 5).
- Downvote threshold for removing a track (default: a net score of -3).
- How long a track counts as "recently played" (default: 24 hours).
- Explicit tracks allowed (default: no).
- Upvotes needed for the Best Voted playlist (default: more than 5).
- Best Voted playlist size (default: 50 tracks).
- When the queue runs out (restart playlist, default AI station, or AI next track).
- Default AI station.
- Playback schedule.
- Weather location (default: Carlisle, Cumbria, UK).
- Announcement voice.
- Monitor mode (default: off). See Playback.

## Technical Notes
- **Stack**: Python backend (FastAPI), SQLite database, TypeScript front end (mobile first), live updates over websockets.

Findings from feasibility testing on 13 October 2026, on the office network.

- **Speakers**: six Sonos speakers, all on S2 firmware, normally grouped as one: Downstairs (Arc), Upstairs Lounge (One), Entrance (One), Kitchen (One SL), Pod (One SL), Donut Shop (One).
- **Playing tracks** (tested, works): Spotify is linked in the Sonos app. GuildFM controls the speakers directly over the local network and adds Spotify tracks to the Sonos queue, and the speakers stream them from Spotify themselves.
- **Announcements over music** (tested, works): each speaker plays an MP3 served by GuildFM as an overlay clip, lowering the music and restoring it afterwards.
- **Rooms in step**: each room takes its own clip command over its own connection, and some speakers take about a tenth of a second longer to connect than others, which sounded like reverb. GuildFM connects to every room first, then sends them all together (within about a millisecond, measured 16 October 2026). That took away most of it. A little is left, from each speaker fetching and starting the clip itself, so the DJ and jingles between songs now go through the Sonos queue instead (19 October 2026), which the group plays in step. Announcements for every room between songs go through the queue too (19 October 2026). Overlay clips are still used for announcements over the music and in chosen rooms, which keep the little that's left. The DJ used to talk over the start of a song too, and Keith still heard the echo there, so the DJ now only talks between songs (19 October 2026): an overlay clip has no start time to give, so the rooms can't be started together. A way to go further for announcements: measure each room's start delay and send to the faster ones later, tuned by ear.
- **Loudness**: text to speech comes out around -22 LUFS, well under the music. With ffmpeg installed, GuildFM evens every voice clip and uploaded jingle out to about -14 LUFS (`AUDIO_LOUDNESS` in `.env`), which takes under half a second a clip. Without ffmpeg they play as they come.
- **Clips between tracks** (tested, works, no gap either side): the DJ's lines and jingles between songs go into the Sonos queue just before the song they come before, so every room plays them in step, and come back out once played. They play in the rooms playing the music, which GuildFM normally keeps as every room. Announcements for every room between songs go in too, straight after the current song and ahead of any jingle or DJ. Announcements for chosen rooms don't, since an MP3 in the queue plays in every room in the group, not just the chosen ones: between songs, GuildFM pauses the music and plays an overlay clip instead, and does the same for anything the speakers won't take into the queue.
- **Search**: needs a Spotify developer app (free). The Spotify account that owns it needs Premium.
- **Playlist import**: Spotify only lets a development-mode app read playlists that the Spotify account connected to GuildFM owns or collaborates on. Spotify's own editorial playlists and other people's playlists can't be imported directly. This is accepted: the workaround is to copy the playlist into one of the connected account's own playlists in the Spotify app, then import the copy.
- **Outside control**: GuildFM listens to the speakers' change events over the local network, so it can tell when someone else changes the music.
- **AI**: OpenAI for text (gpt-6-astra by default, set in `.env`), text-to-speech (gpt-4o-mini-tts), and web search (for global awareness). Weather from Open-Meteo, which needs no key.
- **Host machine**: must be on the office network and not on a VPN. GuildFM runs there as a systemd service (`deploy/guildfm.service`), not in Docker, which would need host networking to find the speakers. Testing on Keith's laptop for now.
- **Risk**: the Sonos local network API is unofficial, so a firmware update could break it.
