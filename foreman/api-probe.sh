#!/bin/bash
# Read-only Foreman API probe as ONE user, from the machine that will really use the account: prints the HTTP
# status and the number of visible objects per endpoint (compare with compare-users.rb's "visible" counts).
# The password is read hidden from the terminal (or with -f FILE from a file) and handed to curl as a config on
# stdin, so it never appears in argv, the environment or a shell history.
#   api-probe.sh <foreman base url> <login> [-f password-file]
# Exit 0 when /api/v2/hosts authenticated, 1 otherwise. GET requests only.
# Note: each failed probe counts towards Foreman's per-address failed-login limit.
set -uo pipefail
BASE="$1"; LOGIN="$2"
if [ "${3:-}" = "-f" ]; then PW="$(cat "$4")"; else read -rs -p "Foreman password for $LOGIN (hidden): " PW; echo; fi
TMP=$(mktemp)
probe() {
  printf 'user = "%s:%s"\n' "$LOGIN" "$PW" | curl -sk -K - -o "$TMP" -w '%{http_code}' "$BASE$1"
}
rc=1
for ep in /api/v2/hosts /api/v2/hostgroups /api/v2/compute_resources /api/v2/subnets /api/v2/domains /foreman_puppet/api/v2/puppetclasses; do
  code=$(probe "$ep?per_page=1")
  total=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('subtotal','?'))" "$TMP" 2>/dev/null || echo '?')
  printf '  %-40s HTTP %s  %s\n' "$ep" "$code" "$total"
  [ "$ep" = /api/v2/hosts ] && [ "$code" = 200 ] && rc=0
done
rm -f "$TMP"
unset PW
exit $rc
