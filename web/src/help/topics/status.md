---
title: The Status page
summary: Whether the speakers and services GuildFM needs are working, the backups, and recent problems.
area: running
order: 7
needs: change_settings
pages: /admin/status
---

**Admin**, **Status** shows whether everything GuildFM depends on is working. The badge at the top sums it up: **All working**, or how many things need a look.

![The Status page](shot:status)

## Speakers and services

Each one has a state:

- **Working**: GuildFM's last use of it went fine.
- **Needs a look**: it failed last time, and it says why.
- **Not used yet**: GuildFM hasn't needed it since it started.
- **Off**: it isn't set up.

They are:

- **Sonos speakers**: how many rooms answer.
- **Spotify**: searching, and the connected account's playlists.
- **OpenAI**: the stations' song picks, the DJ's words, voices, music news and covers.
- **ElevenLabs**: its voices and the jingle generator, with the credits used this month.
- **Weather**: for stations with global awareness.
- **ffmpeg**: evens the voices and jingles out to the music's loudness.

Nothing is tested specially: each is judged by how GuildFM's own use of it went. When something fails, the music keeps playing. The DJ goes quiet, announcements use another voice, and stations play songs they've played before.

## Backups

GuildFM backs itself up every day: everyone's accounts, the playlists, stations and settings, and the jingles, covers and photos. The last 14 are kept. Status shows how many there are, the latest, where they're kept, and the space left on the disk.

## Recent problems

The latest warnings and errors, newest first, with how many times each has happened. Most sort themselves out, such as the weather service not answering once. If one keeps happening, pass it on to whoever set GuildFM up.
