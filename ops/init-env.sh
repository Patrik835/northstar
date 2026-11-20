#!/bin/sh
# Create .env from .env.example and generate any secrets that are still placeholders.
# Safe to run repeatedly: only `generate-me` placeholders are replaced, so existing
# secrets (and data encrypted with them) are never touched.
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    echo "Created .env from .env.example"
fi

random_hex() { od -An -tx1 -N32 /dev/urandom | tr -d ' \n'; }
random_key() { head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'; }

fill() {
    name=$1
    value=$2
    if grep -q "^${name}=generate-me$" .env; then
        tmp=$(mktemp)
        sed "s|^${name}=generate-me$|${name}=${value}|" .env > "$tmp"
        cat "$tmp" > .env
        rm -f "$tmp"
        echo "Generated ${name}"
    fi
}

fill APP_SECRET_KEY "$(random_hex)"
fill CREDENTIAL_ENCRYPTION_KEY "$(random_key)"
fill POSTGRES_PASSWORD "$(random_hex)"
