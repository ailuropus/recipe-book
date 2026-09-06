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

The database on the server starts empty. Pipe an export straight into the
container from the laptop:

```sh
recipebook export | ssh <server> 'cd rakamakatui && docker compose exec -T app recipebook import -'
```

No file is written on the server, which avoids the trap: `docker compose up`
creates the `backups/` bind mount as **root**, so scp'ing into it as your own
user fails with permission denied until you `sudo chown` it. Reading from stdin
sidesteps that entirely.

`import` merges by id, so running it twice is a no-op rather than a duplicate
bank. Check the result with:

```sh
ssh <server> 'cd rakamakatui && docker compose exec -T app recipebook export' | head -3
```

If you do want files on the server — for the nightly backup cron below — take
ownership of the directory once:

```sh
sudo chown "$USER:$USER" ~/rakamakatui/backups
```

## Updating

```sh
cd rakamakatui
scripts/backup.sh
git pull
docker compose --profile app up -d --build
docker compose exec app alembic upgrade head
```

Back up first, every time. It takes a second and it is the only thing standing
between a bad migration and retyping your recipes.

`scripts/backup.sh`, not `recipebook backup`: there is no `recipebook` on this
host. The CLI is installed inside the image, and nothing in the setup above
puts it on the VPS's PATH — so the bare command fails with "command not found"
at exactly the moment a backup matters most. The script takes the JSON export
*and* a `pg_dump`, both from inside the containers, which is also what keeps it
clear of the root-owned `backups/` directory.

The last two lines belong together. A rebuilt container starts serving the
moment it is up, and a release that adds a column answers every request with a
500 until the migration lands — the new code is querying columns that are not
there yet. It clears as soon as `alembic upgrade head` finishes. Run them back
to back, and do not go hunting for the fault in between.

### Backing a release out

The same shape, aimed at the commit you were on before:

```sh
git checkout <previous sha>
docker compose --profile app up -d --build
docker compose exec app alembic downgrade -1
```

`downgrade -1` only if the release you are undoing added a migration, and only
one step per migration it added. When in doubt:

```sh
git log --oneline <previous sha>..HEAD -- migrations/versions/
```

Nothing listed means the schema did not move and the first two lines are the
whole rollback.

## Backups

Two kinds, because they fail differently. The JSON export carries recipes only
but survives a schema change or a move to another machine. The `pg_dump`
restores everything exactly — revisions, the cost log — but is tied to this
schema.

`scripts/backup.sh` does both. Install it as a nightly cron job:

```sh
crontab -e
```

```
0 3 * * * /home/YOU/rakamakatui/scripts/backup.sh >> /home/YOU/backup.log 2>&1
```

Run it once by hand first, to see it work:

```sh
~/rakamakatui/scripts/backup.sh
```

Keep counts are `KEEP_JSON` (30) and `KEEP_DUMPS` (14), overridable per run:
`KEEP_DUMPS=2 scripts/backup.sh`.

### Everything is written from inside a container, on purpose

Docker creates `./backups` owned by **root**, so anything the host user tries
to write or delete there is permission denied. The script therefore does the
export, the dump, and the pruning inside the containers, where the process is
root and none of that applies. No sudo anywhere.

The consequence to know about: you cannot `rm` an old backup from the shell
either. Go through a container:

```sh
docker compose exec -T app sh -c 'rm /app/backups/rakamakatui-<stamp>.json'
```

### Copy them off the box

A backup that only exists on the machine that dies is not a backup. From the
laptop, whenever you think of it:

```sh
rsync -av netcup:rakamakatui/backups/ ~/rakamakatui-backups/
```

The files are world-readable, so this needs no privileges.

### Restoring

Recipes, into any database, any version of the app:

```sh
recipebook export | ssh <server> 'cd rakamakatui && docker compose exec -T app recipebook import -'
```

Everything, exactly, into the same schema:

```sh
gunzip -c backups/rakamakatui-<stamp>.sql.gz \
  | docker compose exec -T db psql -U recipebook -d recipebook
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
