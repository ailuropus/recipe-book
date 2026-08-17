# Deploying rakamakatui

A netcup VPS running Debian 13 (trixie), reachable only over Tailscale. No
public port, no reverse proxy, no certificate to renew, no CI.

Everything here is done by hand on purpose. This is one app for one person, and
a deploy is three commands you can read.

## What Tailscale actually does here

This is the part worth understanding before you start, because it replaces
about four things you would otherwise have to build.

Tailscale puts your laptop, your phone, and the VPS on one private network.
Each machine gets a stable address that works from anywhere — a café, mobile
data, another country — without opening a single port to the internet. There is
no public IP to find, no firewall rule to write, and nothing for a scanner to
knock on.

`tailscale serve` then adds one more thing on top: it terminates HTTPS for you.
It gets a real Let's Encrypt certificate for a name like
`vps.your-tailnet.ts.net`, renews it automatically, and forwards requests to a
port on localhost.

So the app binds to `127.0.0.1:8000` and knows nothing about TLS, hostnames, or
certificates. From the phone you open `https://vps.your-tailnet.ts.net` and get
a green padlock. From anywhere not on your tailnet, the name does not resolve
and the port is not there.

That is why the non-goals list has no nginx, no certbot, and no auth: the
network layer is doing all three, and doing them better than a hand-rolled
version would.

## First-time setup

### 1. The machine

Debian 13, as a user with sudo.

Docker comes from Docker's own repository, not Debian's. Debian ships
`docker.io`, but its companion `docker-compose` is the retired Python v1, and
this project needs Compose v2 for `profiles:`. Installing `docker.io` now also
makes a later move to `docker-ce` a conflict to untangle. `docker-compose-v2`
is an Ubuntu package name and does not exist here.

```sh
sudo apt update
sudo apt install -y git ca-certificates curl

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update

sudo apt install -y docker-ce docker-ce-cli containerd.io \
                    docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in for the group to take effect, then check:

```sh
docker --version
docker compose version     # a subcommand, not the docker-compose binary
docker run --rm hello-world
```

### 2. Tailscale

Some netcup images already have the Tailscale apt repository configured — if
`apt update` mentions `pkgs.tailscale.com`, it is there and `apt install` is
enough. Otherwise the install script adds it.

```sh
tailscale version || sudo apt install -y tailscale \
  || curl -fsSL https://tailscale.com/install.sh | sh
sudo systemctl enable --now tailscaled
sudo tailscale up
```

Follow the printed URL to authorise the machine. Then confirm it appears:

```sh
tailscale status
```

Enable HTTPS certificates for your tailnet once, in the Tailscale admin console
under DNS → HTTPS Certificates. Without it `tailscale serve` has no certificate
to issue.

### 3. The app

```sh
git clone <your remote> rakamakatui && cd rakamakatui
cp .env.example .env
```

Edit `.env`. Two lines matter:

```sh
ANTHROPIC_API_KEY=<from Bitwarden>
POSTGRES_PASSWORD=<generate one, e.g. openssl rand -base64 24>
```

Set `POSTGRES_PASSWORD` **before the first `up`**. Postgres only applies it when
it initialises its data directory; changing it later does nothing until the
volume is destroyed. And change it from the default — this repository is public,
so a password that appears in it is not a password.

Leave `DATABASE_URL` alone. That is how the *host* reaches the database. Inside
Docker the database is `db:5432`, and `docker-compose.yml` builds that URL from
`POSTGRES_PASSWORD` itself.

Then:

```sh
docker compose --profile app up -d --build
docker compose exec app alembic upgrade head
```

Both services are `restart: unless-stopped`, so they come back after a reboot
without anything else to configure.

### 4. Publish it to the tailnet

```sh
sudo tailscale serve --bg 8000
tailscale serve status      # prints the https:// URL
```

Open that URL on the phone. Add it to the home screen.

### 5. Move your recipes across

The database on the server starts empty. From the laptop:

```sh
recipebook export -o bank.json
scp bank.json <server>:rakamakatui/
```

Then on the server:

```sh
docker compose exec -T app recipebook import /app/backups/../bank.json
```

Or more simply, put the file in `backups/` first — that directory is mounted
into the container, so anything in it is readable from inside:

```sh
scp bank.json <server>:rakamakatui/backups/
ssh <server> 'cd rakamakatui && docker compose exec -T app recipebook import /app/backups/bank.json'
```

`import` merges by id, so running it twice is a no-op rather than a duplicate
bank.

## Updating

```sh
cd rakamakatui
recipebook backup --dir backups     # before anything else
git pull
docker compose --profile app up -d --build
docker compose exec app alembic upgrade head
```

Back up first, every time. It takes a second and it is the only thing standing
between a bad migration and retyping your recipes.

## Backups

Two kinds, and you want both.

`pg_dump` takes everything — recipes, revision history, the cost log — and
restores exactly. It is tied to this schema:

```sh
docker compose exec db pg_dump -U recipebook recipebook | gzip > dump-$(date +%F).sql.gz
```

The JSON export takes recipes only, and survives a schema change or a move to a
different machine:

```sh
docker compose exec app recipebook backup --dir /app/backups --keep 30
```

A nightly cron for the second one:

```sh
crontab -e
```

```
0 3 * * * cd /home/YOU/rakamakatui && docker compose exec -T app recipebook backup --dir /app/backups --keep 30
```

Copy them off the box periodically. A backup that only exists on the machine
that dies is not a backup:

```sh
# from the laptop
rsync -av vps:rakamakatui/backups/ ~/rakamakatui-backups/
```

Restoring recipes into an empty database:

```sh
docker compose exec app recipebook import /app/backups/rakamakatui-<stamp>.json
```

## Secrets

`.env` on the VPS is the only place the API key lives, and Bitwarden is where it
comes from. It is in `.gitignore` and must stay there.

To rotate the key: change it in Bitwarden, edit `.env`, then
`docker compose --profile app restart app`. The key is read at process start —
editing `.env` under a running server does nothing until it restarts. (Same on
the laptop, which is the one thing about `--reload` that surprises people: it
watches `.py` files, not `.env`.)

## When something is wrong

```sh
docker compose --profile app ps           # is it up
docker compose --profile app logs -f app  # what it says
docker compose exec db pg_isready -U recipebook
tailscale serve status                    # is it published
sudo tailscale status                     # is the machine on the tainet
```

If the site does not load from the phone, check in this order: the phone is on
the tailnet, `tailscale serve status` shows the mapping, the container is up.
It is almost always the first one.

`recipebook spend` shows what the model calls have cost, in total and per
recipe, if the bill looks wrong.

## Deliberately not here

No CI, no container registry, no deploy webhook, no staging environment, no
monitoring, no log aggregation. One person, one app, one box. If a deploy is
ever more than `git pull` and two `docker compose` lines, something has gone
wrong with the design rather than with the deployment.
