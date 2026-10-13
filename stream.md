# GuildFM

GuildFM is a web application running over the local network. It lets everyone in the office queue, vote on and manage the music playing on the office Sonos system, with AI announcements and AI radio stations.

UI prototype: [GuildFM Prototype](https://claude.ai/artifact/J9FURLqbP6ryuCQWhe6UWo) (private to Keith). A copy of its screens is in `prototype/`.

## Terms
- **Queue**: the live list of upcoming tracks that everyone sees and votes on. There is one queue for the whole office.
- **Playlist**: a saved list of tracks that can be played (for example, the Best Voted playlist, or one a curator created or imported).
- **Station**: an AI radio station, which picks its own tracks and can have a DJ.
- **Source**: the playlist or station that keeps the music going when nobody has requested anything.
- **Request**: a track a user adds to the queue. Requests always play before tracks from the source.

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
| Create and import playlists | | Yes | Yes |
| Create AI stations | | Yes | Yes |
| Start or switch playlists and AI stations | | Yes | Yes |
| Playback controls (play, pause, resume, skip, volume, stop) | | | Yes |
| Create announcements | | | Yes |
| Manage users (create accounts, reset passwords, promote to curator or admin, delete accounts) | | | Yes |
| Change settings | | | Yes |

### Profile settings
- Display name: the name the DJ reads out when announcing a request.
- Announce my requests: on by default. Users can opt out.

## Main UI
- A responsive web application will be built to allow users to interact with the system. The main UI will include:
  - A dashboard displaying the currently playing track, upcoming tracks, and user activity.
  - A search feature to find tracks and artists.
  - A queue management system for users to add tracks, and remove their own.
- The application should be MOBILE FIRST, and responsive: designed for phones first, but on a desktop browser it uses the space properly (sidebar navigation, wider content, more columns where they help) instead of looking like a small portrait app.

## Queue and Voting
- Users can vote tracks up or down, using thumbs up and thumbs down. The system automatically orders the queue by votes.
- A track whose score falls to the downvote threshold is removed from the queue. The threshold is a setting.
- Users can remove their own tracks, but only their own.
- Each user can have a limited number of tracks in the queue at once. The cap is a setting (default: 5).
- A track that is already in the queue cannot be added again.
- Tracks played recently show a warning badge (for example, "played 2 hours ago") in search and in the queue, but can still be added.
- Explicit tracks are allowed by default. Admins can block them in settings.
- Curators can manage the queue without voting: override votes, reorder tracks, and remove any track. The reorder controls (move up and down arrows) are only shown to curators and admins.
- Votes reorder everything after the next track. GuildFM hands the next track to Sonos shortly before it plays, so that one is locked.

## Playback
- Admins can play, pause, resume, skip, change volume and stop.
- **Stop** halts all playback, including announcements and the DJ, until play is pressed again.
- **Play** continues whatever was playing before (a playlist, an AI station, or the queue).
- **Playback schedule** (setting): the hours GuildFM plays, for example weekdays 08:00 to 18:00. Outside these hours it behaves as if stopped, so scheduled announcements don't play either.
- **When the queue runs out** (setting), one of:
  1. Restart the current playlist. If no playlist is playing, fall back to option 3.
  2. Play a default AI station.
  3. Ask the AI for a next track that fits the music played so far.

### Outside control
- If someone changes the music from the Sonos or Spotify app, the outside change wins. GuildFM stops everything it is doing (queue, playlist, station, DJ and announcements), the same as pressing Stop, and leaves the speakers alone.
- The dashboard shows that GuildFM has been overridden. Pressing Play takes control back and continues what was playing before.
- If the Arc is switched to the TV, it just drops out of the group. GuildFM carries on in the other rooms.

## Playlists
- Curators and admins can create playlists in GuildFM, or import them from Spotify by pasting a playlist link.
- Curators and admins can play any playlist.

### Best Voted playlist
- There is one Best Voted playlist, maintained automatically.
- A track that gets more than X upvotes goes into it (setting, default: 5).
- The playlist holds up to Y tracks (setting, default: 50).
- When the playlist is full and a new track qualifies, the track with the fewest upvotes drops out. If several tracks tie on fewest upvotes, the oldest entry drops out.
- A new track only gets in if it has at least as many upvotes as the track it would replace.

## Announcement System
- Announcements are audio only, played on the speakers. Only admins can create them.
- The admin types the announcement as text, and it is read out by text-to-speech (OpenAI) in the announcement voice from settings.
- When an announcement is created, there will be options:
    - Which speakers to broadcast to (all, or specific speakers).
    - Whether to play the announcement immediately or schedule it for a later time.
    - Whether the announcement plays over the current track or waits until the current track is finished.
    - A schedule: one-off, or at specific intervals with recurrence patterns.
- Announcements always take precedence over the DJ.
- Announcements don't play while playback is stopped or outside the playback schedule.

## AI Radio
- Admins and curators can create AI radio stations, and start them.
- The user will specify:
    - The name of the station.
    - A description of the station, such as the genre or mood of the music to be played.
    - The personality of the DJ, if any. The DJ is optional, and is a text-to-speech voice that announces the tracks being played, or provides commentary on the music.
    - Global awareness. If enabled, the AI takes into account the time of day, the current weather, and current events to influence the music selection.
- If a DJ is used:
    - The DJ's voice, picked from the OpenAI voices.
    - How often the DJ interjects (for example, every 10 minutes, after every X tracks, etc.).
    - Whether the DJ just announces the track, or provides commentary on the music being played.
    - Whether to announce requests.
- The AI decides whether the DJ talks over a track (with the music lowered) or between tracks, aiming for a mix of both.
- The AI picks tracks by name. GuildFM finds them on Spotify through search.

### Voice preview
- While picking a DJ's voice, the user can preview it with a built-in phrase or one they type.
- The preview is spoken in the DJ's personality (for example, a laid-back late-night DJ sounds different from an upbeat breakfast DJ in the same voice).
- Previews play in the browser, not on the office speakers.
- The announcement voice in settings can be previewed the same way.

### Global awareness
- Weather comes from the location in settings (default: Carlisle, Cumbria, UK).
- There are no news bulletins. Instead, current events steer track choices and DJ commentary. For example: playing a track by an artist who has just passed away, or a song that has just won a song contest, and commenting on it. Commentary on sad news should be respectful.

### Requests and voting on stations
- User requests take precedence over the station's own tracks. The station resumes once there are no requests left.
- If announce requests is on, the DJ announces the request and the display name of the user who made it, unless that user has opted out. If announce requests is off, the DJ does not announce requests.
- Users can vote on station tracks. Votes do not teach the station, so its taste isn't polluted.

## Settings (admin)
- Track cap per user (default: 5).
- Downvote threshold for removing a track (default: a net score of -3).
- How long a track counts as "recently played" (default: 24 hours).
- Explicit tracks allowed (default: yes).
- Upvotes needed for the Best Voted playlist (default: more than 5).
- Best Voted playlist size (default: 50 tracks).
- When the queue runs out (restart playlist, default AI station, or AI next track).
- Default AI station.
- Playback schedule.
- Weather location (default: Carlisle, Cumbria, UK).
- Announcement voice.

## Technical Notes
- **Stack**: Python backend (FastAPI), SQLite database, TypeScript front end (mobile first), live updates over websockets.

Findings from feasibility testing on 13 October 2026, on the office network.

- **Speakers**: six Sonos speakers, all on S2 firmware, normally grouped as one: Downstairs (Arc), Upstairs Lounge (One), Entrance (One), Kitchen (One SL), Pod (One SL), Donut Shop (One).
- **Playing tracks** (tested, works): Spotify is linked in the Sonos app. GuildFM controls the speakers directly over the local network and adds Spotify tracks to the Sonos queue, and the speakers stream them from Spotify themselves.
- **Announcements and DJ over music** (tested, works): each speaker plays an MP3 served by GuildFM as an overlay clip, lowering the music and restoring it afterwards.
- **Clips between tracks** (not yet tested): an MP3 placed in the Sonos queue between two tracks. Same mechanism as playing tracks.
- **Search**: needs a Spotify developer app (free). The Spotify account that owns it needs Premium.
- **Playlist import**: Spotify only lets a development-mode app read playlists that the Spotify account connected to GuildFM owns or collaborates on. Spotify's own editorial playlists and other people's playlists can't be imported directly. This is accepted: the workaround is to copy the playlist into one of the connected account's own playlists in the Spotify app, then import the copy.
- **Outside control**: GuildFM listens to the speakers' change events over the local network, so it can tell when someone else changes the music.
- **AI**: OpenAI for text, text-to-speech, and web search (for global awareness).
- **Host machine**: must be on the office network and not on a VPN. If run in Docker, it needs host networking so it can find the speakers. Testing on Keith's laptop for now.
- **Risk**: the Sonos local network API is unofficial, so a firmware update could break it.
