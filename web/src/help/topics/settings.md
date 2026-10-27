---
title: Settings
summary: The voting rules, Best Voted, what plays when the queue runs out, the voice and the connections.
area: running
order: 4
needs: change_settings
pages: /admin/settings
---

**Settings** saves as you go: there's no Save button. Playback hours and monitor mode have topics of their own: [Playback hours](topic:playback-hours) and [Monitor mode](topic:monitor-mode).

## Queue and voting

- **Requests per person**: how many songs one person can have waiting at once. Admins have no limit.
- **Remove at score**: a request is taken out of the queue when its votes add up to this. It's also how many thumbs down skip a playlist's or a station's song.
- **Recently played means**: how long a song counts as recently played, and gets a badge. It can still be requested.
- **Allow explicit tracks**: off to start with. While it's off, explicit songs are hidden from search, refused as requests, and left out of albums and stations.

## Best Voted playlist

- **Upvotes to get in**: a request joins Best Voted once it has more thumbs up than this.
- **Playlist size**: the most songs it holds. When it's full, the song with the fewest thumbs up drops out (the oldest, if several are level).

![Queue and voting, and Best Voted](shot:settings-voting)

## When the queue runs out

What plays when a playlist reaches its end, or nothing was ever chosen:

- **Restart the current playlist** (or AI picks, if no playlist was playing).
- **Play the default AI station**, chosen underneath. With none chosen, AI picks.
- **Let the AI pick the next song**: AI picks, following on from what's been playing.

Choosing **Requests only** on Now Playing is different: then nothing takes over.

![When the queue runs out](shot:settings-runs-out)

## AI and voice

- **Weather location**: where the weather comes from, for stations with global awareness. It's saved when you leave the box.
- **Announcement voice**: the voice announcements are read in. Pick a phrase, or type your own, to hear it on this device. ElevenLabs voices can act things out, with tags such as [excited].

![AI and voice](shot:settings-voice)

## Connections

- **Spotify account**: the account curators import playlists from. Spotify asks for it to be connected again every six months, and the page says by when. It can only be connected from the GuildFM computer itself, so open GuildFM there, sign in, and tap **Reconnect** (or ask whoever set GuildFM up).
- **Sonos speakers**: whether GuildFM can reach the speakers, and how many it found.

![Connections](shot:settings-connections)
