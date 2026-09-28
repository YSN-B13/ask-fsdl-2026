#!/bin/bash
# shellcheck source=tasks/pretty_log.sh
set -euo pipefail

# Clear command-line parameters so the sourced script sees nothing.
set --
source tasks/pretty_log.sh

require() {
    if [ -z "${!1:-}" ]; then
        echo "Error: $1 is not set. Add it to .env.dev before running this target." >&2
        exit 1
    fi
}

require MONGODB_USER
require MONGODB_PASSWORD
require MONGODB_HOST
require MONGODB_DATABASE
require MONGODB_COLLECTION
require GEMINI_API_KEY

pretty_log "Pushing mongodb-fsdl secret to Modal"
modal secret create --env dev --force mongodb-fsdl \
    MONGODB_USER="$MONGODB_USER" \
    MONGODB_PASSWORD="$MONGODB_PASSWORD" \
    MONGODB_HOST="$MONGODB_HOST" \
    MONGODB_DATABASE="$MONGODB_DATABASE" \
    MONGODB_COLLECTION="$MONGODB_COLLECTION"

pretty_log "Pushing gemini-api-key-fsdl secret to Modal"
modal secret create --env "$MODAL_ENVIRONMENT" --force gemini-api-key-fsdl \
    GOOGLE_API_KEY="$GEMINI_API_KEY"

pretty_log "Secrets pushed."
