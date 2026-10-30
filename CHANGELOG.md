# Changelog

All notable changes to GuildFM are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and GuildFM
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
