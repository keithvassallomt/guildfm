---
title: A station's jingles
summary: Upload or make the short idents a station plays between songs.
area: radio
order: 4
needs: create_stations
pages: /radio/:id
---

Jingles (or idents) are short bits of music in the pause between songs, like on the radio. A station plays two kinds: GuildFM's own **system idents**, and its own **station idents**.

The AI that picks a station's songs also decides where a jingle goes: about one song in four, at a change of mood or the start of a new run. Never two in a row, and never the same one twice running.

![A station's jingles](shot:station-jingles)

## Add a station's own idents

Once a station's made, its editor lists its **Station idents**, under **Jingles**:

- **Add MP3s** uploads your own: MP3s of up to a minute each.
- **Generate jingles** has the AI make them for you. See [Making jingles with AI](topic:jingle-generator).
- The play button plays one on this device, not on the speakers. **Remove** deletes it.

Without station idents of its own, a station plays GuildFM's system idents. Turn off **Play jingles** for a station that shouldn't play any. Deleting a station deletes its station idents.

::: needs change_settings
System idents are on **Admin**, **Jingles**. See [GuildFM's jingles](topic:system-jingles).
:::
