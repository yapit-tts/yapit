---
status: backlog
---

# Twitter/X Tweet Extraction via oEmbed

## Intent

X.com URLs currently return "JavaScript is disabled" error text to users. We could use X's official oEmbed API to extract at least some tweet content, but the improvement is marginal — oEmbed truncates long tweets and doesn't support threads, which are the content people would most want read aloud.

## Assumptions

- oEmbed endpoint (`publish.twitter.com/oembed`) remains free, unauthenticated, and stable — it has been for years but X could change this.
- Users submitting X.com URLs expect to hear the tweet read aloud. If they mostly share short tweets, oEmbed covers the case. If they share threads/long posts, it doesn't.
- No usage data on how often users submit X.com URLs — may not be worth the code.

## Research

Tested 2026-02-17 in this session (no separate artefact — findings are small enough to inline):

| Approach | Result |
|---|---|
| **Our Playwright renderer** | Works (~6s, full content) but `networkidle` always times out on x.com. Would need x.com-specific wait strategy. Violates X TOS — $15k/million posts liquidated damages. |
| **oEmbed** | Works for short tweets. Truncates long ones (~280 chars then "..."). No thread traversal, no quoted tweets. Legally clean — officially published API. |
| **fxtwitter** | Dead (403 / redirects to x.com) |
| **vxtwitter** | Video embed stub only, no text |
| **nitter** | Dead |

### Why current pipeline fails on X.com

1. JS heuristic (`_JS_RENDERING_PATTERNS`) doesn't detect X.com — React markers are in external bundles, not inline HTML
2. Trafilatura "succeeds" on the error page, so Playwright fallback (line 64) never triggers

## Done When

- x.com/twitter.com URLs detected and routed to oEmbed fetch
- Blockquote HTML parsed to extract tweet text
- User shown a note that long tweets/threads may be truncated

## Considered & Rejected

- **Playwright rendering**: Full content but TOS violation, slow, needs x.com-specific wait logic.
- **fxtwitter/vxtwitter/nitter**: All dead or dying, TOS-violating, no durability.
- **X API ($100/mo Basic tier)**: Overkill for a feature with unknown demand.
