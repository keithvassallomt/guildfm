---
title: Playback hours
summary: When GuildFM plays by itself, day by day.
area: running
order: 5
needs: change_settings
pages: /admin/settings
---

GuildFM plays during its playback hours, set for each day of the week in **Settings**, under **Playback hours**.

![Playback hours](shot:settings-hours)

- Set when each day opens and closes, or turn its switch off for **Off all day**.
- **Time zone** is the office's.
- **After-hours play**: how many hours the music plays when someone presses **Play** outside the hours. 4 to start with.
- The line at the top says whether it's open now, or when it opens again, and until when it's playing after hours if someone pressed **Play**.

## What happens when

- **At opening time**, GuildFM starts by itself, if there's anything to play. With nothing to play yet, it starts as soon as someone makes a request.
- **At closing time**, it stops everything, as if **Stop all** was pressed.
- **Outside the hours**, nothing plays, scheduled announcements included. Requests wait in the queue.
- **Play** works at any time. Outside the hours, the music then plays for the **After-hours play** time and stops again by itself. Pressing **Play** again starts that time over, and if opening time comes first, it simply carries on into the day.
- **Paused** stays paused, even if the speakers restart (as they sometimes do overnight). Only **Play** starts the music again.
- **Stop all** during the hours lasts until someone presses **Play**, or the next opening time.

A line-up's slots outside a day's hours don't play.
