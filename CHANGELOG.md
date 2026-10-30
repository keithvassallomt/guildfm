# Changelog

All notable changes to GuildFM are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and GuildFM
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A preview for links to GuildFM in chats: the logo above a radio dial, "The office jukebox"
  and what GuildFM does. Chats that build previews on the sender's phone or computer, such as
  iMessage and WhatsApp, show it for links sent from the office. Slack and Teams build them on
  their own servers, which can't reach GuildFM. `make preview-card` draws the picture again.

## [0.1.2] - 2026-10-30

### Added

- GuildFM at `https://guildfm.com` in the office, with a Let's Encrypt certificate that Caddy
  gets and renews through Route 53. The name points at the office machine's private address, so
  it only works inside the office. `deploy/setup-https.sh` sets it up, and the README says how
  it fits together.
- `PUBLIC_URL` in `.env`: browsers that open a page over plain HTTP by name, such as
  `http://guildfm.local`, are sent there. The speakers, the API and Spotify's sign-in carry on
  as they are.

### Changed

- Long song titles in search results and album track lists wrap onto a second line instead of
  being cut short. A title longer than two lines still ends with "…", so rows stay tidy.

## [0.1.1] - 2026-10-30

### Added

- Names are checked when people pick them, at sign-up and when they change their display name
  on Profile. OpenAI turns down rude names, and display names that aren't plausibly what
  someone is called, such as "bungalistic". A username only has to be clean, since it's for
  signing in. If OpenAI can't be reached within 10 seconds, the name goes through.
- The version GuildFM is running: at the foot of the sidebar on desktop, and first on the
  Admin page.
- This changelog.
- The journal now records when the speakers stop, pause or start again, with where the
  speakers and GuildFM each are in the queue, so a silence can be pieced together afterwards.

### Fixed

- The music stayed off until someone pressed Play when the speakers turned down GuildFM's
  second try at a song that hadn't started. GuildFM now skips that song straight away and
  carries on with the next one.
- GuildFM's second try at a song asked for the wrong place in the speakers' queue when its
  own copy of that queue had drifted from theirs. It now reads the speakers' queue first,
  goes by that, and notes in the journal what had drifted.
- The playback buttons on Now Playing and in the quick controls could stay greyed out for good
  if a command never got an answer. They now give up after 20 seconds and say to check what's
  playing before trying again.
- The song list in "Request a song" scrolled sideways on phones when a title was long. Long
  titles are cut short again.
- Requesters' photos and initials sat below their names on Now Playing. They're now centred
  on the text.

## [0.1.0] - 2026-10-27

The first version, installed on the office machine.
