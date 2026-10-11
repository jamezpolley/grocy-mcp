#!/bin/bash
# Shared launcher for MCP servers that need 1Password secret injection.
#
# Usage:
#   op-run-mcp.sh <child command and args>
#
# Resolves secrets via `op run`, then execs the child with the resolved
# values.
#
# Secret source selection (in order):
#   1. OP_ENVIRONMENT_ID          → inject a whole 1Password Environment's
#                                    variables (op run --environment)
#   2. op:// refs already in the inherited environment, authenticated via:
#      a. OP_SERVICE_ACCOUNT_TOKEN → service-account mode (preferred for headless)
#      b. OP_ACCOUNT                → user signin to that account ID
#      c. neither                   → default `op` resolution (may prompt)

set -eu

if [ -n "${OP_ENVIRONMENT_ID:-}" ]; then
  exec op run --environment "$OP_ENVIRONMENT_ID" -- "$@"
fi

if [ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
  exec op run -- "$@"
fi

if [ -n "${OP_ACCOUNT:-}" ]; then
  exec op run --account "$OP_ACCOUNT" -- "$@"
fi

exec op run -- "$@"
