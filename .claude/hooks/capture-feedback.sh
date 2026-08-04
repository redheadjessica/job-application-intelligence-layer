#!/usr/bin/env bash
# JAIL feedback-capture backstop (UserPromptSubmit hook).
#
# WHY: user feedback given in chat used to evaporate if the user never ran /reconcile in that
# thread. This appends each user prompt to a gitignored feedback inbox so nothing is lost between
# reconcile runs. The /reconcile pass (reconcile-spec §0) reads this inbox, applies the
# fact-vs-inference rule, and marks entries processed. This is a raw backstop, NOT canon.
#
# HARD REQUIREMENTS: never block or alter the prompt (no stdout, always exit 0), never fail a
# session, and stay a silent no-op on fresh clones / non-JAIL projects (dir doesn't exist yet).

input="$(cat 2>/dev/null || true)"

root="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$root" ]; then
  root="$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true)"
fi
[ -z "$root" ] && root="$(pwd 2>/dev/null || echo .)"

inbox_dir="$root/PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/learning"
# Only capture for a set-up instance; a fresh clone has no private tree — exit silently.
[ -d "$inbox_dir" ] || exit 0

prompt="$(printf '%s' "$input" | jq -r '.prompt // empty' 2>/dev/null || true)"
[ -z "$prompt" ] && exit 0
sid="$(printf '%s' "$input" | jq -r '.session_id // "unknown"' 2>/dev/null || echo unknown)"

inbox="$inbox_dir/feedback-inbox.md"
if [ ! -f "$inbox" ]; then
  printf '# Feedback Inbox (raw capture — processed + cleared by /reconcile)\n\nAppend-only raw log of user prompts, captured by the UserPromptSubmit hook so nothing is lost between reconcile runs. NOT canon: the reconcile pass (reconcile-spec §0) reads this, applies the fact-vs-inference rule, echoes what it captured in chat, and marks entries processed. Gitignored.\n\n---\n' > "$inbox" 2>/dev/null || true
fi

{
  printf '\n### %s · session %s\n' "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo undated)" "$sid"
  printf '%s\n' "$prompt"
} >> "$inbox" 2>/dev/null || true

exit 0
