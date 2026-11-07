#!/usr/bin/env bash
# HTTPS for the tablet on the LAN (INK-181, decision 0076). Browsers give a page every pen sample
# (PointerEvent.getCoalescedEvents) only in a secure context, and http://<laptop-ip> is not one.
# Makes a private certificate authority once and a server certificate for this machine's LAN
# addresses, in data/tls/ (gitignored). Re-run when the laptop's IP changes; the CA stays the same,
# so the tablet trusts the new certificate without reinstalling anything.
#
#   scripts/lan-cert.sh            # prints the files and how to trust the CA on the tablet
set -euo pipefail
cd "$(dirname "$0")/.."
dir="${INKBRIDGE_DATA_DIR:-data}/tls"
mkdir -p "$dir"
umask 077

ca_key="$dir/inkbridge-ca.key"
ca_pem="$dir/inkbridge-ca.pem"
ca_crt="$dir/inkbridge-ca.crt" # DER copy: what Android's "Install a certificate" expects
key="$dir/lan.key"
pem="$dir/lan.pem"

if [[ ! -f "$ca_key" || ! -f "$ca_pem" ]]; then
  openssl req -x509 -new -newkey rsa:2048 -nodes -keyout "$ca_key" -out "$ca_pem" -days 3650 \
    -subj "/CN=Inkbridge local CA ($(hostname))" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
  openssl x509 -in "$ca_pem" -outform der -out "$ca_crt"
  echo "made a new CA: $ca_pem"
fi

# Every IPv4 address of this machine except loopback and container bridges, plus localhost names.
ips=$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | grep -v '^172\.1[7-9]\.' || true)
san="DNS:localhost,DNS:$(hostname).local,IP:127.0.0.1"
for ip in $ips; do san="$san,IP:$ip"; done

current=""
[[ -f "$pem" ]] && current=$(openssl x509 -in "$pem" -noout -ext subjectAltName 2>/dev/null | tail -n +2 | tr -d ' ' || true)
want=$(echo "$san" | sed 's/IP:/IPAddress:/g')
if [[ "$current" != "$want" ]] || ! openssl x509 -in "$pem" -noout -checkend 2592000 >/dev/null 2>&1; then
  ext=$(mktemp)
  trap 'rm -f "$ext"' EXIT
  printf 'basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=%s\n' "$san" >"$ext"
  openssl req -new -newkey rsa:2048 -nodes -keyout "$key" -subj "/CN=$(hostname)" 2>/dev/null |
    openssl x509 -req -CA "$ca_pem" -CAkey "$ca_key" -CAcreateserial -days 397 -extfile "$ext" -out "$pem" 2>/dev/null
  echo "made a server certificate for: $san"
fi

echo "certificate: $pem"
echo "key:         $key"
echo "CA for the tablet: $ca_crt"
