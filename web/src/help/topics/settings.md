---
title: Settings
summary: The voting rules, Best Voted, what plays when the queue runs out, the voice, the office location and the connections.
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

- **Upvotes to get in**: a song joins Best Voted once it has more thumbs up than this.
- **Playlist size**: the most songs it holds. When it's full, the song with the fewest thumbs up drops out (the oldest, if several are level).

![Queue and voting, and Best Voted](shot:settings-voting)

## When the queue runs out

What plays when a playlist reaches its end, or nothing was ever chosen:

- **Restart the current playlist** (or AI picks, if no playlist was playing).
- **Play the default AI station**, chosen underneath. With none chosen, AI picks.
- **Let the AI pick the next song**: AI picks, following on from what's been playing.

Choosing **Requests only** on Now Playing is different: then nothing takes over.

![When the queue runs out](shot:settings-runs-out)

## Kiosk

For the touchscreen in the office. See [The kiosk](topic:kiosk).

- **Places**: how many songs the kiosk can add before it takes a break. 8 to start with. A song that plays gives its place back.
- **Break**: in minutes, how long the kiosk can't add or vote once its places are all taken. 3 to start with. After it, all its places are free again.
- **Look**: **Dark** or **Light**.

![Kiosk settings](shot:settings-kiosk)

## AI and voice

- **Weather location**: where the weather comes from, for stations with global awareness. It's saved when you leave the box.
- **Announcement voice**: the voice announcements are read in. Pick a phrase, or type your own, to hear it on this device. ElevenLabs voices can act things out, with tags such as [excited].

![AI and voice](shot:settings-voice)

## Office location

GuildFM lets people in when they're on the office Wi-Fi, but some phones hide that: an iPhone with iCloud Private Relay, for example, reaches GuildFM through Apple. Once the office's location is set here, the page that turns them away offers **Confirm my location**, which lets them in if they're within 150 m of it.

- **Use where I am now**: makes where this device is the office's location. Do it in the office, with precise location allowed. A location that's only rough is turned down.
- **Show on a map**: to check it's in the right place.
- **Remove**: turns location checks off.

Confirming their location, or letting Safari show their address, lets that browser in until midnight.

![Office location](shot:settings-office)

## Connections

- **Spotify account**: the account curators import playlists from. Spotify asks for it to be connected again every six months, and the page says by when. It can only be connected from the GuildFM computer itself, so open GuildFM there, sign in, and tap **Reconnect** (or ask whoever set GuildFM up).
- **Sonos speakers**: whether GuildFM can reach the speakers, and how many it found.

![Connections](shot:settings-connections)
