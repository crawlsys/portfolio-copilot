# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed
- **Congressional disclosure detail 404**: clicking "Details" on a disclosure
  returned a 404. Next.js delivers the dynamic `[filingId]` segment
  still percent-encoded and the openapi-fetch client re-encoded it, so
  synthetic IDs containing a colon (`quiver-filing:<digest>`) were
  double-encoded (`%253A`) and the API returned 404 → `notFound()`. Fixed by
  decoding the route param once before the API call
  (`web/src/app/congressional/[filingId]/page.tsx`). Deployed as web image
  `tracker-web:20260623-1`.
