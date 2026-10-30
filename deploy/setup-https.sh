#!/usr/bin/env bash
# Sets the office machine up to serve GuildFM over HTTPS at guildfm.com: a fixed address, Caddy
# with its Route 53 module in front of GuildFM, and PUBLIC_URL so browsers go there. Run it with
# sudo from the checkout, after scripts/update.sh. Safe to run again, such as when the domain
# wasn't ready the first time.
#
# It expects the Route 53 key for the certificate in ~guildfm/.caddy-route53.env (or already
# moved to /etc/caddy/route53.env by an earlier run).
set -euo pipefail
cd "$(dirname "$0")/.."

NAME=guildfm.com
DEVICE=enp1s0
ADDRESS=10.240.1.61/24
GATEWAY=10.240.1.1
KEYS=/home/guildfm/.caddy-route53.env
GUILDFM_ENV=$PWD/.env

[ "$(id -u)" = 0 ] || { echo "Run it with sudo."; exit 1; }
[ -f "$KEYS" ] || [ -f /etc/caddy/route53.env ] || { echo "The Route 53 key isn't in $KEYS."; exit 1; }

echo "== A fixed address, $ADDRESS, from the next restart of the machine"
if grep -q "^iface $DEVICE inet dhcp$" /etc/network/interfaces; then
	cp /etc/network/interfaces /etc/network/interfaces.dhcp
	sed -i "s|^iface $DEVICE inet dhcp$|iface $DEVICE inet static\n    address $ADDRESS\n    gateway $GATEWAY|" \
		/etc/network/interfaces
fi
# dhcpcd wrote this and won't run again, so it says the same thing for good.
printf "nameserver 8.8.8.8\nnameserver 8.8.4.4\n" > /etc/resolv.conf
ifquery "$DEVICE" > /dev/null # stops here if the file no longer reads

echo "== Caddy, with its Route 53 module"
if ! dpkg -s caddy > /dev/null 2>&1; then
	# Not started on install: its sample site wants port 80, which is GuildFM's.
	printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
	chmod 755 /usr/sbin/policy-rc.d
	trap 'rm -f /usr/sbin/policy-rc.d' EXIT
	apt-get update -qq
	apt-get install -y caddy
	rm -f /usr/sbin/policy-rc.d
fi
if ! caddy list-modules 2> /dev/null | grep -qx "dns.providers.route53"; then
	# Debian's Caddy has no Route 53 module, so an official build with it takes its place, as
	# Caddy's own instructions for Debian describe. Upgrades of the package leave it be.
	curl -fsSL -o /tmp/caddy.custom \
		"https://caddyserver.com/api/download?os=linux&arch=amd64&p=github.com/caddy-dns/route53"
	chmod 755 /tmp/caddy.custom
	/tmp/caddy.custom list-modules | grep -qx "dns.providers.route53"
	mv /tmp/caddy.custom /usr/bin/caddy.custom
	if ! dpkg-divert --list /usr/bin/caddy | grep -q caddy.default; then
		dpkg-divert --divert /usr/bin/caddy.default --rename /usr/bin/caddy
	fi
	update-alternatives --install /usr/bin/caddy caddy /usr/bin/caddy.default 10
	update-alternatives --install /usr/bin/caddy caddy /usr/bin/caddy.custom 50
fi

echo "== Caddy's settings and key"
if [ -f "$KEYS" ]; then
	install -o root -g caddy -m 640 "$KEYS" /etc/caddy/route53.env
	rm -f "$KEYS"
fi
mkdir -p /etc/systemd/system/caddy.service.d
# Without --environ, which would write the key into the journal.
cat > /etc/systemd/system/caddy.service.d/guildfm.conf << 'EOF'
[Service]
EnvironmentFile=/etc/caddy/route53.env
ExecStart=
ExecStart=/usr/bin/caddy run --config /etc/caddy/Caddyfile
EOF
install -m 644 deploy/Caddyfile /etc/caddy/Caddyfile
(set -a && . /etc/caddy/route53.env && caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile)
systemctl daemon-reload
systemctl enable caddy
systemctl restart caddy

echo "== Waiting for the certificate, which takes a minute or two"
got=""
for _ in $(seq 1 40); do
	if curl -fsS -o /dev/null --resolve "$NAME:443:127.0.0.1" "https://$NAME/api/health"; then
		got=yes
		break
	fi
	sleep 5
done
if [ -z "$got" ]; then
	journalctl -u caddy -n 20 --no-pager
	echo "No certificate yet. Caddy keeps trying by itself; run this again in a while."
	exit 1
fi

echo "== Browsers on plain HTTP sent to https://$NAME"
if ! grep -q "^PUBLIC_URL=" "$GUILDFM_ENV"; then
	echo "PUBLIC_URL=https://$NAME" >> "$GUILDFM_ENV"
fi
systemctl restart guildfm
sleep 5
secure=$(curl -s -o /dev/null -w "%{http_code}" --resolve "$NAME:443:127.0.0.1" "https://$NAME/")
plain=$(curl -s -o /dev/null -w "%{http_code} %{redirect_url}" -H "Host: guildfm.local" http://127.0.0.1/)
echo "https://$NAME/ answers $secure; http://guildfm.local/ answers $plain"
if [ "$secure" != 200 ]; then
	# Most likely GuildFM sending Caddy's requests round again: put it back as it was.
	sed -i "/^PUBLIC_URL=/d" "$GUILDFM_ENV"
	systemctl restart guildfm
	echo "HTTPS didn't answer as it should, so PUBLIC_URL is off again."
	exit 1
fi
echo "Done. Open https://$NAME. The fixed address takes over at the next restart of the machine."
