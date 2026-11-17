# Talk Stations

## Basic idea

So, the idea is to prototype talk stations. This would be something that's added as part of a line-up, for example.

1. When creating a station, more than one DJ can be added.
2. Like today, each DJ has a personality and voice (existing ones can be chosen).
3. However, when there are at least two DJs, we get a new input where we can specify the type of interaction between them, the dynamic. It should say what winds each of them up, and who interrupts whom. For example:

   "Guildbert finds Debbie to be too energetic, and often tries to calm her down during their shows. Debbie, on the other hand, loves to challenge Guildbert's opinions and often sparks lively debates. She can't let him finish a story. The two have a history going back decades, and their chemistry is a big draw for listeners."

4. Then, we add a new setting: Talk Station. If this is enabled, a slew of additional features are unlocked.

### DJ hooks

Each DJ's personality gets three more fields, under **Personality** in the DJ part of the station editor. They belong to the DJ, like the personality, so they follow the DJ to every station they host. Talk stations use them to give the banter something to grab on to.

| Field | Length | Placeholder | What it's for |
|---|---|---|---|
| Pet peeves | 300 characters | Songs that fade out instead of ending. People who clap on the one. | The wind-up: what the other DJ pokes at. |
| Soft spots | 300 characters | Anything by ABBA. Brass bands. The office dog. | What they defend, and what gives them away in the verdict. |
| Running obsession | 200 characters | Building a shed. Has been for eleven years. | Confessions, asides, and callbacks across shows. |

- All three are optional. A move that needs a hook isn't dealt for a DJ without one: no wind-up for a DJ with no pet peeves.
- A hint under them: "For talk stations: what the other DJs can wind them up about, what they go soft on, and what they keep coming back to."
- Changes apply on every station the DJ hosts, as the personality does today, and the editor says so.
- The help topic "The DJ" gets the three fields.

## Talk Station features

### Talk/music ratio

A slider that sets how much of the station's time is talk versus music. For example, 70/30 means 70% talk and 30% music. Using this slider disables the controls which specify how often the DJ should talk.

- It goes from 20% talk to 100% talk. At 100% there's no music at all.
- Above 70%, the slider is coloured red, for the cost and the lack of music.
- It shows "about N credits an hour" next to it.

Talk is the only part that costs anything: about 450 ElevenLabs credits a minute (measured on eleven_v4, 2026-11-16). A half-hour show at 70/30 is 21 minutes of talk, about 9,400 credits; every weekday, that's around 200K a month, more than the account's 160K limit on its own. At 100%, an hour costs about 27,000 credits, so the monthly limit lasts about six hours.

### Script prompt

A text box where the station creator can specify a script or outline for the DJs to follow. This could include topics to discuss, questions to ask each other, or specific segments to include in the show. The script prompt isn't the script itself: the script is written by AI. Instead, the script prompt is a way to guide the AI in generating a script that fits the station's style and content.

How to write good two-host talk is built into GuildFM (see "How the script is written"), so the script prompt only needs to say what the show is about.

### Named fields

The script prompt editor supports named fields. GuildFM only gathers the data for the fields a prompt uses.

| Field | What it is | Where it comes from |
|---|---|---|
| `[news]` | Light, odd and funny news stories | Global Awareness has music news only today. General news needs a new gatherer, told to look for light stories: no politics, tragedy or deaths. |
| `[weather]` | The weather where the office is | Global Awareness, already there. |
| `[sports]` | British football: news, scores and results | New. British football teams only, nothing else. |
| `[celebrities]` | Celebrity news, anniversaries, birthdays | New. Needs care: this is where wrong ages and wrong deaths come from. |
| `[lineup]` | The station's schedule, upcoming shows and segments | The database. |
| `[djs]` | The names and personalities of the DJs at GuildFM | The database. |

### Example script prompt

```text
A lunchtime show of light chat between the two DJs, with plenty of back and forth.

A topic can run for just one segment (i.e. between two songs), for a number of segments, or for
the entire show.

Topics to draw on include, but are not limited to:

- The latest news headlines [news]. Keep it to weird or funny stories. The DJs should have
  opposing viewpoints and engage in a lively discussion.
- The weather [weather]. The DJs have different opinions on the weather and how it affects
  their day-to-day lives, and funny stories about their experiences with it.
- The football [sports]: last night's games, players and teams, and who's having a bad week.
- Celebrities [celebrities], especially relevant celebrity news of the day, or anniversaries
  and birthdays.
- Snarky comments about the other [djs].
- Summaries of the rest of the day's [lineup].
```

## How the script is written

### Three layers

1. **Built in, always on.** How to write natural two-host talk, interruptions, audio tags, and the rules on facts and teasing. Every talk station gets these, so creators don't have to rediscover them.
2. **The station's script prompt.** What the show is about, its topics and segments, its tone.
3. **The show plan.** Written by the AI when a show starts. A show in a line-up knows how long it runs, and is planned whole. A talk station playing outside a line-up has no known length, so it's planned an hour at a time. The plan picks the running bits and places their setups and payoffs across the links. Each bit has an idea (what it is and what's at stake) and an ending (how it pays off), and the writer is only told the ending when it's due: told it earlier, the writer plays it out early. Each link is then written with the plan, what's been said so far, and the songs either side. The plan and the show's state are kept in the source's `dj_memory`.

### Built-in rules

- The DJs have different opinions and say so. They don't praise each other's points or finish each other's sentences.
- Each keeps to their own way of talking.
- Turns vary in length: a story, a two-word reply, a line that gets cut off.
- They use each other's names now and then, so listeners learn who's who.
- They tease each other freely, and go gently on the people who request songs. Opt-outs are respected, as today.
- No made-up facts. Trivia and corrections only from the data GuildFM gives them.
- Audio tags sparingly: four at most in a link.
- No politics, religion or tragedy, in the news or anywhere else.

Listeners know only what they hear, so the talk has to be easy to follow, as if someone has just walked in. The first rehearsal was hard to follow, and these rules came out of it:

- Each turn follows from the one before it: an answer, a reaction, an argument. Nobody carries on with their own thought as if the other hadn't spoken.
- Whoever brings up a story tells it first, plainly, in a sentence or two (what happened, where, to whom), and only then do they riff on it.
- Anything the writer knows that listeners don't (a DJ's hooks, the plan, the show's notes) is explained the first time it comes up on air: no marrows before we know about the allotment.
- One topic a segment, two at most, with room to tell it and argue about it. Not all of the day's material has to be used, and a segment leaves the rest for others.
- Topics change the way people change them: from something just said, or openly ("Right, the weather").
- Hooks are seasoning: now and then, not every segment.
- A running bit comes back in a line at most between its setup and its payoff. Its payoff recaps it in a line, for anyone who's just tuned in.
- The writer is never told a segment's number, and the plan never refers to one by number, so neither ends up on air. If a draft still says "segment", it's written again.
- The opening segment welcomes everyone and doesn't talk about whatever played before the show. After a song, the song is mentioned in the first turn if at all, not every time. A segment with no song before it carries straight on, mid-conversation.

### The edit

Every segment is written, then edited by a second AI call before it's voiced. The editor reads the draft as a listener would. It's told what listeners have heard (the last two segments word for word, the show's notes, whether a song just played or this opens the show), and, kept apart, the background it may use to fix things (the DJs and their hooks, what the plan wants from this segment, the day's material). It checks two things:

1. **Does it follow?** Each turn answers, reacts to, argues with or builds on the one before. No ignoring what was just said, no jumps with no way in, no replies to something nobody said.
2. **Is everything explained?** No joke whose premise listeners haven't heard: no story riffed on before it's told, no person, hobby, rivalry, bet or running joke mentioned as if known.

It fixes only what it flags, keeping every other turn word for word with its marks, and says what it fixed (in the journal: "Segment 3, edited: ..."). Its most common catch in the first runs was an interruption cut so early that the reply answered words listeners never heard. If the edit fails, or cuts more than 40% of the draft, the draft goes out as written. "Hear them together" in the editor skips it, to stay quick.

It adds 10 to 15 seconds to each segment: about 30 seconds to write and edit, 20 to voice.

### Banter moves

GuildFM has a list of moves, and the code deals them out: one or two running bits per show, and one move per link, never the same as the last few. The writer gets a job to do rather than "be funny". The code picks, not the AI: left to itself, a model picks the same favourites every time.

| Move | What happens |
|---|---|
| The bet | Stakes are set early and settled later. The loser pays up on air, or refuses to. |
| The challenge | One sets the other a task: talk about the weather without saying "rain", sneak a word into the next link. Pays off later. |
| The score | A running quiz, such as guessing a number from the day's news before it's revealed. The score carries through the show. Answers come only from what the DJs are given: a quiz on how the next song ends had them making it up. |
| The correction | One states something, the other corrects them. Only from real data (the news, the play history), never invented trivia. |
| The wind-up | One deliberately pokes the other's pet peeve. |
| The verdict | Both rate the last song, and disagree. Never dealt when no song has just played, as at a show's opening. |
| The confession | One admits something embarrassing about themselves. Character fiction, harmless. |
| The aside | One whispers to the listeners behind the other's back. |
| The producer | Both complain about an unseen producer. A classic radio device; no extra voice needed. |
| The guest | Another DJ from `[djs]` drops in, with their own voice. |

Three things make the moves work:

- **Hooks on each DJ:** pet peeves, soft spots, a running obsession (see "DJ hooks"). The wind-up and the confession need them.
- **State:** the score, the stakes, who owes whom. Saved with the show and passed to every link.
- **Memory across shows:** a short log of recent bits, so a daily show doesn't repeat itself, and so it can call back ("you still owe me a biscuit from Tuesday"). Callbacks across days are what make listeners believe in the hosts.

### Happenings

When a show starts, the code rolls the dice (in code: a language model can't pick a random number fairly). With a 4 in 10 chance, the show gets a happening: something unexpected between the DJs that isn't part of the script prompt, adding excitement and unpredictability. The code picks which kind and tells the show plan. Kinds include, but are not limited to:

- **An argument** about something trivial or personal, not part of the script prompt. Never a controversial topic.
- **A prank:** a practical joke, or a funny challenge.
- **A bet.**
- **A surprise guest:** another DJ from `[djs]`, with their own voice.

Happenings follow the same rules as scenarios: one segment, several, or the entire show if its length is known.

## Interruptions: real overlap

The DJs can interrupt each other and talk over each other. ElevenLabs' Text to Dialogue can't overlap voices, so each turn is voiced on its own and GuildFM mixes them. The spike found the stitched version sounds fine, and costs the same: 762 credits against 763 for the same script in one request.

- **Script format:** each turn has a speaker and text, and two optional marks:
  - `cut_after`: for a turn that gets interrupted, the word after which the next speaker cuts in. The writer still writes the whole sentence, so the voice doesn't wind down as if it were finishing.
  - `together`: the turn is said at the same time as the one before, such as both saying "No!".
- **Voicing:** every turn at once, in parallel. A turn with `cut_after` is voiced with ElevenLabs' with-timestamps endpoint, which says when each word is spoken.
- **Mixing (ffmpeg):** turns follow each other with short, varied gaps. An interrupted turn is cut just after its `cut_after` word with a quick fade, and the next turn starts a fraction of a second before the cut, with an audio tag such as `[interrupting]` so it comes in sharply. A `together` turn starts with the one before.
- **Checked by the code, not trusted to the AI:** the `cut_after` word is really in the turn, and there are at most one or two interruptions a link, so it stays a character trait rather than a tic.
- **Who interrupts whom** comes from the dynamic.

Talk stations use ElevenLabs voices: OpenAI's can't take audio tags or say when each word is spoken.

## Voicing and timing

Measured in the spike: a 2-minute link took about 10 s to write, and about 16 s per minute of audio to voice in one request.

- A link that fits in the 90 s that songs are lined up ahead is made as today.
- A longer link (at 70/30, links average about 8 minutes) is made in chunks of about 2 minutes. The first chunk is queued as soon as it's ready, and the next is made while it plays. Each chunk takes about 30 s to make, so this keeps up easily.
- At 100% talk there are no songs, so the chunks simply follow each other.

A show's plan takes 20 to 40 seconds (longer while the day's news is still being looked up), so it's made ahead of the first talk, in the background, and the first talk only has to be written, edited and voiced (about 50 seconds):

- **A station put on by hand,** or by the queue running out: as it comes on, while the song before its first talk plays.
- **A show in a line-up:** ten minutes before it opens, when its station picks its first songs, planned as it'll be at its start time.
- **The next hour outside a line-up:** while the last two segments of this hour's plan play.
- **A plan from another day** isn't used: the show starts afresh.

An all-talk station has no song to make its first talk behind. When it comes on, or Play is pressed with nothing to play, it opens with one song the office has heard before, picked without the AI (the station's own plays first, then Best Voted, then anything heard), and the talk follows it. With no song heard before, as on a new install, the talk starts on its own once it's ready.

## Songs, requests and skips

- The DJs still react to the songs and the requests, with the material today's DJ gets: play history, repeat requests, votes.
- Listeners can't skip a link: thumbs down only ever skips songs.
- Curators can, with Skip, as today. It's the way to cut off a link that goes wrong (a wrong fact, a tease that lands badly, a client in the office), and at 100% talk the only alternative would be Stop. It couldn't be blocked anyway: anyone with the Sonos app can skip.
- When a link is skipped, the next link is told what wasn't heard, so it doesn't pay off a setup nobody heard. The show plan is adjusted to match.

## Next steps

- Spike: add `cut_after` and `together` to tools/dialogue_spike.py and mix the turns, to hear real overlap and time parallel voicing.

## Future

- Live interaction
