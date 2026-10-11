#!/usr/bin/env bash
# Template for your machine-local values. Committed to the repo on purpose, so
# whoever clones knows exactly what to fill in.
#
#   cp ctest/live.local.example.sh ctest/live.local.sh
#
# Nothing in this directory structure reads the example file; only
# ctest/live.local.sh is sourced, and it is git-ignored.

BILI_ROOM_ID=0

# Login is NOT optional on this route -- do not skip it.
#
# The DOM route reads the chat pane out of a real bilibili tab, and bilibili
# does not load that pane for guests: an anonymous tab shows "登录后可参与讨论"
# and a permanently empty `.chat-items`, which looks exactly like a dead
# collector. So the profile used by ctest/edge_cdp.py must be logged in once by
# hand (scan the QR code). There is no credential to put in this file -- the
# session lives in the browser profile, not here.
#
# (The old advice to leave this blank "because the feed is readable
# anonymously" was measured and found false.)
