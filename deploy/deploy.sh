#!/usr/bin/env bash
# Runs ON THE VPS, in /opt/doc-checker (copied there by .github/workflows/deploy.yml).
#
#   ./deploy.sh <full commit sha>
#
# Switches Doc Checker to the images tagged with that commit, waits until the
# api and frontend are healthy, and puts the previous version back if they
# never get there. Needs .env next to it, and `docker login ghcr.io` done if
# the images aren't on this machine yet.
set -euo pipefail

NEW_TAG="${1:?usage: deploy.sh <full commit sha>}"
if [[ ! "$NEW_TAG" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Not a full commit SHA: $NEW_TAG" >&2
  exit 1
fi

cd "$(dirname "$0")"
[[ -f .env ]] || { echo ".env missing in $PWD" >&2; exit 1; }

COMPOSE=(docker compose -f docker-compose.prod.yaml)
OLD_TAG=$(sed -n 's/^IMAGE_TAG=//p' .env | tail -n 1)

# Write IMAGE_TAG=<tag> into .env (compose reads it from there, so manual
# `docker compose ...` commands on the VPS keep using the deployed version).
set_tag() {
  if grep -q '^IMAGE_TAG=' .env; then
    sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$1/" .env
  else
    printf 'IMAGE_TAG=%s\n' "$1" >> .env
  fi
}

healthy() {  # healthy <service>
  local id
  id=$("${COMPOSE[@]}" ps -q "$1")
  [[ -n "$id" ]] && [[ "$(docker inspect -f '{{.State.Health.Status}}' "$id")" == "healthy" ]]
}

wait_healthy() {
  local _
  for _ in $(seq 1 36); do   # 36 × 5 s = 3 minutes
    if healthy api && healthy frontend; then
      return 0
    fi
    sleep 5
  done
  return 1
}

# Each step only runs if the previous one worked (&&): `set -e` does not
# apply inside a function that is called from an `if`.
start() {  # start <tag>
  set_tag "$1" &&
    "${COMPOSE[@]}" pull --quiet &&
    "${COMPOSE[@]}" up -d --remove-orphans &&
    wait_healthy
}

echo "Deploying $NEW_TAG (running before: ${OLD_TAG:-nothing})"

if start "$NEW_TAG"; then
  "${COMPOSE[@]}" ps
  # Free disk: delete THIS app's images that no container uses and that are
  # older than 7 days (recent ones stay for a quick rollback). The label
  # filter keeps your other apps' images untouched.
  docker image prune -af \
    --filter "until=168h" \
    --filter "label=org.opencontainers.image.source=https://github.com/Alain-16/Doc_Checker" \
    >/dev/null
  echo "Deployed $NEW_TAG"
  exit 0
fi

echo "Deploy of $NEW_TAG FAILED. Container states:" >&2
"${COMPOSE[@]}" ps -a >&2

if [[ -n "$OLD_TAG" && "$OLD_TAG" != "$NEW_TAG" ]]; then
  echo "Rolling back to $OLD_TAG" >&2
  if start "$OLD_TAG"; then
    echo "Rolled back to $OLD_TAG" >&2
  else
    echo "Rollback to $OLD_TAG ALSO failed" >&2
  fi
fi

echo "Read the logs on the VPS:" >&2
echo "  cd $PWD && docker compose -f docker-compose.prod.yaml logs --tail 100 migrate api frontend" >&2
exit 1