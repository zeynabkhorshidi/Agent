#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export SELLORA_DB=data/sellora-demo.db
export SELLORA_DEMO_MODE=true
export SELLORA_SEED_CUSTOMERS=true
exec bash start-linux.sh
