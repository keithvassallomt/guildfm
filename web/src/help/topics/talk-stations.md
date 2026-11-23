---
title: Talk stations
summary: Two or more DJs, mostly talking: banter, running bits, and the day's news, weather and football.
area: radio
order: 4
needs: create_stations
---

A talk station is mostly its DJs talking, with songs in between. Two or more DJs chat, bicker and banter, cut each other off and talk over each other, and keep running bits going through the show, such as a bet, a challenge or a score. When the station asks for them, they use the day's real news, weather and football.

## Make one

1. Go to **Radio**, tap **New station**, and pick **Talk show**. A talk show needs two or more DJs with **ElevenLabs** voices, and it says how many of the office's DJs have one.
2. Name the show, and say what music plays between the talk.
3. **Hosts**: tap two to six DJs, in the order you want them. Each shows their place on the show. A DJ with an OpenAI voice opens their details first, to choose an ElevenLabs one. **New DJ** makes one with an ElevenLabs voice. See [DJs](topic:djs).
4. **The show**: how much talk, what it's about, and how they get on (below).
5. The extras, then check it over and tap **Create station**. See [Making a station](topic:making-a-station).

![Picking Talk show](shot:wizard-talk)

If ElevenLabs isn't set up, **Talk show** can't be picked, and says why.

## Turn a station into one

On a station's page, tap **Change** on **Type** and pick **Talk show**. GuildFM walks you through the hosts, then the show, and saves. To change just the show later, tap **Change** on **The show**.

![Turning a station into a talk show](shot:talk-turn-into)

## How much talk

The slider runs from 20% talk to 100%. Under it, an hour shows as twelve blocks of five minutes, the talk in orange, with about how many minutes of each. At 40%, there's a little over two minutes of talk between songs; at 60%, about five; at 70%, about eight. At 100% it's all talk, and only requests play. Above 70% the slider turns red: there's very little music, and it's costly.

Under that is about how many ElevenLabs credits an hour of it costs, and how many hours of it this month's allowance covers. A minute of talk is about 450 credits.

![How much talk](shot:talk-mix)

## What it's about

Say what the show is about, as you'd brief a presenter: the kind of chat, and what to draw on. How to sound like two people, the running bits and the surprises are GuildFM's job.

It's a guide, not a checklist. To keep shows varied, a show won't always use everything in it, and the DJs can wander onto other things.

**Bring in what's going on today** adds a field to the prompt, where the cursor is, or takes it out again. Fields are picked out in the prompt, in square brackets:

- **Odd news** (`[news]`): light, odd and funny stories from the past week, newest first.
- **Odd facts and history** (`[oddities]`): odd facts, and funny true stories from this day in past years.
- **Weather** (`[weather]`): the weather where the office is.
- **Football** (`[sports]`): British football: news, scores and results.
- **Birthdays and celebs** (`[celebrities]`): birthdays, anniversaries and news.
- **What's on next** (`[lineup]`): what's on for the rest of the day.
- **The other DJs** (`[djs]`): GuildFM's other DJs.

GuildFM only looks up the fields the prompt uses, before each show.

![What it's about, and bringing in the day's news](shot:talk-prompt)

## How they get on

**How do they get on?** says who winds whom up, and who interrupts whom. It belongs to this station, so the same DJs can get on differently somewhere else. Everything in it comes up in every show, so keep running jokes, such as a feud over the office fridge, in a DJ's hooks, which are shared out a show at a time.

- **Suggest one** has the AI write it from their personalities and hooks. If there's something there already, it says **Suggest another**, and **Put back what was there** undoes it.
- **Hear them together** writes and voices a half-minute exchange between them, and plays it on this device, not the office speakers. It costs about 200 credits.

![How they get on](shot:talk-get-on)

## On air

- The show is planned an hour at a time, or the whole show in a line-up, with running bits set up early and paid off later. The first talk comes after the first song.
- Each show remembers what the last few talked about, so a daily show doesn't keep coming back to the same stories.
- The talk stops for each song: the DJs wrap up before it, and pick up again after it.
- Requests still play, and the DJs bring them in.
- In a line-up, the show opens at the start of its slot and signs off at the end.
- Curators can skip a stretch of talk with **Skip**. The DJs know it wasn't heard, so they don't pay off what listeners missed.
- In monitor mode, **Skip music when ready** lets you hear the talk without waiting through the songs. See [Monitor mode](topic:monitor-mode).
