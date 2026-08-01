# Deployment Guide — Presentation

The presentation is a static, self-contained site (`index.html`, `styles.css`, `script.js`). It has no build step and no backend dependency — it can be opened directly or served from any static host.

## Before deploying: replace placeholders

Three placeholder strings appear in `index.html` and must be replaced with real values before the final presentation:

| Placeholder | Where it appears | Replace with |
|---|---|---|
| `LIVE_DEMO_URL` | Slide 8 (Open Live Demo button), Slide 9 (Project Demo link) | The deployed demo URL, or a local/staged alternative if no public demo exists |
| `GITHUB_REPOSITORY_URL` reference | Already filled in as `https://github.com/felipevalenta-marketing/autonomous-company-research-agent` (from the repo's `origin` remote) | Update only if the remote changes |
| `LINKEDIN_URL` | Slide 9 (closing links) | Your LinkedIn profile URL, if you want it included |

Use your editor's find-and-replace across `presentation/index.html` — each placeholder appears exactly once or twice and is easy to locate.

## Option A — GitHub Pages (preferred)

1. Commit the `presentation/` folder to the repository (already isolated from application code).
2. In GitHub: **Settings → Pages → Build and deployment → Source**, choose **Deploy from a branch**.
3. Select the branch (e.g. `main`) and set the folder to `/presentation` if GitHub Pages offers a subfolder option, or use one of the fallback approaches below if it only allows `/` or `/docs`.
   - Fallback: publish from a dedicated `gh-pages` branch containing only the `presentation/` contents at its root, using `git subtree`:
     ```
     git subtree push --prefix presentation origin gh-pages
     ```
   - Then set Pages to deploy from the `gh-pages` branch, root folder.
4. GitHub will publish the site at `https://<username>.github.io/<repository-name>/`.
5. Update `LIVE_DEMO_URL` in `index.html` to that address once published, then redeploy.

## Option B — Netlify Drop

1. Go to Netlify's drag-and-drop deploy page.
2. Drag the `presentation/` folder (containing `index.html`, `styles.css`, `script.js`, `assets/`) onto the page.
3. Netlify assigns a public URL immediately — no account or CLI required for a one-off deploy.
4. Use that URL as `LIVE_DEMO_URL` if this presentation itself is the "demo" link, or keep it separate from the application demo.

## Option C — Vercel static deployment

1. From the `presentation/` directory:
   ```
   npx vercel --prod
   ```
2. Accept the default static-site detection (no framework, no build command).
3. Vercel returns a production URL you can use directly.

## Running locally

No server is required — opening `presentation/index.html` directly in Chrome or Edge works. If a local server is preferred (e.g. to test `fetch`-based behavior or avoid `file://` restrictions), from the `presentation/` directory:

```
python -m http.server 8080
```

Then open `http://localhost:8080`.

## Notes

- The presentation does not modify or depend on the production application (`app/`), its services, tests, or configuration.
- No API keys or `.env` values are used or referenced anywhere in the presentation.
- Fonts are loaded from Google Fonts via CDN with system-font fallbacks; the deck remains legible offline if the CDN is unreachable.
