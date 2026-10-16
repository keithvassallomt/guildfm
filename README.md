# GuildFM

Office music, voted on by everyone. GuildFM runs on a machine on the office network. People open it on their phones or laptops, request songs and vote on them, and it plays them on the office Sonos speakers. It also has AI radio stations with a DJ, and spoken announcements.

What it does is described in [stream.md](stream.md), and how it was built in [dev.md](dev.md).

## What you need

- **A machine that stays on**, on the office network (wired is best) and not on a VPN. These steps assume Linux (Debian or Ubuntu); anything that runs systemd will do.
- **The Sonos speakers**, with Spotify linked in the Sonos app. GuildFM plays to the biggest group of speakers, which is normally every room.
- **A Spotify account with Premium**, which owns a free Spotify developer app (below).
- **An OpenAI API key**, for the AI radio, the DJ, the voices and station covers.
- **An ElevenLabs API key** (optional), for the ElevenLabs account's own voices.
- **Software:** git, [uv](https://docs.astral.sh/uv/) (it installs the right Python by itself), Node.js 22 or later, and ffmpeg. Without ffmpeg, everything works, but voices play quieter than the music.

## Setting up the Spotify app

1. Sign in to the [Spotify developer dashboard](https://developer.spotify.com/dashboard) with the Premium account, and create an app.
2. Add this redirect URI, exactly as written: `http://127.0.0.1:8000/auth/spotify/callback`. Spotify only accepts `127.0.0.1` or an HTTPS address here, which is why connecting the account happens on the GuildFM machine itself (see [Connecting Spotify](#connecting-spotify)).
3. Tick **Web API**, save, and copy the client ID and client secret.

The app is used for searching the catalogue. A Spotify account connected from Admin, Settings is only needed for importing playlists, and only playlists that account owns or collaborates on can be imported.

## The `.env` file

Copy `.env.example` to `.env` and fill it in. Every setting is explained in the file. The ones you must fill in:

- `OPENAI_API_KEY`
- `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`
- `GUILDFM_SECRET_KEY`: make one with `openssl rand -hex 32`
- `GUILDFM_ADMIN_PASSWORD`: the password for the `admin` account, which is made the first time GuildFM starts

`ELEVENLABS_API_KEY` is optional. `.env` holds secrets: never commit it.

## Running it on your own machine

```sh
make install   # Python and front end dependencies
make dev       # the API and the front end, reloading as you change the code
```

`make dev` serves the front end at `http://<this machine>:5173`, which phones on the same network can open too. `make serve` builds the front end and runs GuildFM as it runs in the office, at `http://<this machine>:8000`. `make test` runs the tests and `make lint` checks the code.

## Installing it on the office machine

Run these on the office machine, as a user with sudo.

1. **Name the machine `guildfm`**, so people can open `http://guildfm.local:8000` without knowing its address. That name is announced on the network over mDNS by Avahi:

   ```sh
   sudo hostnamectl set-hostname guildfm
   sudo apt install avahi-daemon ffmpeg git
   ```

2. **Make a `guildfm` user**, which GuildFM runs as. Give it sudo, since it's the account you'll log in as to look after GuildFM:

   ```sh
   sudo adduser guildfm
   sudo usermod -aG sudo guildfm
   ```

3. **As the `guildfm` user**, install uv and Node.js, then get GuildFM and build it:

   ```sh
   curl -LsSf https://astral.sh/uv/install.sh | sh   # then open a new shell, so uv is found
   # Node.js 22 or later, from https://nodejs.org (distributions often have an older one)
   git clone <the GuildFM repository> ~/guildfm
   cd ~/guildfm
   uv sync --no-dev --frozen
   (cd web && npm ci && npm run build)
   ```

4. **Fill in `~/guildfm/.env`** (see [above](#the-env-file)). If you're moving GuildFM from another machine, bring its data now (see [Moving in](#moving-in)).

5. **Start it as a service**, so it starts at boot and starts again if it ever stops:

   ```sh
   sudo cp deploy/guildfm.service /etc/systemd/system/
   sudo systemctl enable --now guildfm
   ```

6. **Open `http://guildfm.local:8000`** from a phone, and sign in as `admin`. Check Admin, Status: the speakers should be answering.

If the machine has a firewall, allow TCP port 8000 and UDP port 5353 (mDNS) from the office network. If the speakers can't be found, put their addresses in `SONOS_HOSTS` in `.env`.

Some older Android phones can't open `.local` names. If one can't, use the machine's address instead (reserve one for it on the router, so it doesn't change).

## Connecting Spotify

Only needed for importing playlists. Spotify only sends people back to `127.0.0.1` after they sign in, so connect from a browser on the GuildFM machine itself: open `http://127.0.0.1:8000/admin`, sign in, and connect from Settings.

For a machine without a screen, do it from a laptop through an SSH tunnel. The address Spotify sends you back to then reaches the GuildFM machine:

```sh
ssh -L 8000:127.0.0.1:8000 guildfm@guildfm.local
```

Leave that running, then on the laptop open `http://127.0.0.1:8000/admin`, sign in, and connect from Settings. If the laptop runs GuildFM itself, stop it first, since the tunnel needs port 8000. Spotify asks for the account to be connected again about every six months, and Settings reminds you.

## Moving in

To bring everything from another machine (accounts, playlists, stations, jingles, covers, the Spotify connection and the play history), make a backup there:

```sh
make backup    # prints where the zip went
```

Copy the zip to the office machine, and unzip it into the data folder before GuildFM first starts there (or with it stopped):

```sh
mkdir -p ~/guildfm/data
unzip guildfm-*.zip -d ~/guildfm/data
```

To start fresh instead, sign in as `admin` and upload the jingles from `assets/jingles`: the system idents in Admin, Jingles, and each station's station idents in its editor.

## Looking after it

- **Admin, Status** shows whether the speakers and each service GuildFM uses are working, how many ElevenLabs credits are left this month, the backups, the disk space, and the latest problems.
- **Logs:** `journalctl -u guildfm -f` follows them, and `journalctl -u guildfm --since today` shows today's.
- **Restarting:** `sudo systemctl restart guildfm`. The music carries on through a restart, and GuildFM picks the speakers back up where it left them.
- **Updating:** as the `guildfm` user, run `./scripts/update.sh` in `~/guildfm`. It gets the latest code, rebuilds, makes a backup and restarts GuildFM (asking for your password to restart).

## Backups

GuildFM makes a backup every day: a zip of the database and the uploaded media (jingles, covers and profile photos). It keeps the last 14, in `data/backups`. Backups on the same disk don't help if the disk dies, so point `BACKUP_DIR` in `.env` at another disk or a network share, or copy them off now and then. `make backup` makes one straight away.

To restore one:

```sh
sudo systemctl stop guildfm
unzip -o data/backups/guildfm-<date>.zip -d ~/guildfm/data
sudo systemctl start guildfm
```

## What it costs to run

- **OpenAI:** a request for each batch of songs a station picks, each line the DJ says and its voice, the music news every few hours, and one image for each station's cover. Usage shows at [platform.openai.com/usage](https://platform.openai.com/usage).
- **ElevenLabs** (only for its voices): about 0.45 credits a character on `eleven_v4`, so about 67 credits for a typical DJ line. A DJ station talking every 3 songs through all of the office's hours uses about 69,000 credits a month. A clip is only made once for the same words in the same voice, so a repeating announcement costs nothing after the first time.

## Installing it as an app

People can add GuildFM to their home screen: on an iPhone, Safari's Share button then Add to Home Screen, and Profile explains how on each device. Android and desktop browsers only install it as a proper app, in its own window, over HTTPS. On `http://guildfm.local:8000` they add a shortcut that opens a browser tab, which works just as well. A `.local` name can't get a certificate browsers trust, so HTTPS would mean giving GuildFM a hostname on a company domain, with a certificate from Let's Encrypt.
