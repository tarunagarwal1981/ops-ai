# Project: <your-project-name>

<!-- Template. Replace everything in angle brackets, delete what doesn't apply.
     Keep this file under ~200 lines: it loads into every session.
     Folder-specific rules go in a CLAUDE.md inside that folder (loads on demand). -->

## Commands
- Install: `<pnpm install>`
- Test: `<pnpm test>`
- Lint and format: `<pnpm lint --fix>`
- Run locally: `<pnpm dev>`

## Rules
- Tests go in `<tests/>`, mirroring the `<src/>` folder structure
- Never edit `<migrations/>` by hand; run `<pnpm db:migrate:new>`
- Dates are UTC in the database, local time only in the UI
- Never commit secrets; config comes from environment variables

## Where things are
- API routes: `<src/api/>`
- Shared types: `<src/types/>` (check here before creating a new type)

## Before you say "done"
- Run the tests and the linter
- Summarise what changed and anything you weren't sure about
