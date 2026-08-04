# Deployment Guide — Presentation

The presentation is a static, self-contained site (`index.html`, `styles.css`, `script.js`). It has no build step and no backend dependency — it can be opened directly or served from any static host.

## Demo links

All three DEMO-slide links are resolved and live in `index.html` — no placeholders remain:

| Item | Where it appears | Target |
|---|---|---|
| n8n workflow link (primary button) | Slide 8, first button | `https://felipevalencia.app.n8n.cloud/workflow/b6THKkvUQaJegSRM` |
| Railway deployment link | Slide 8, second button | `https://autonomous-company-research-agent-production.up.railway.app` |
| GitHub repository link | Slide 8, third button, and Slide 9 closing links | `https://github.com/felipevalenta-marketing/autonomous-company-research-agent` |
| LinkedIn link | Slide 9 (closing links) | Not shown — no confirmed profile URL available. An HTML comment in the closing slide markup marks where to add it once one exists. |

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

## Option B — Netlify Drop

1. Go to Netlify's drag-and-drop deploy page.
2. Drag the `presentation/` folder (containing `index.html`, `styles.css`, `script.js`, `assets/`) onto the page.
3. Netlify assigns a public URL immediately — no account or CLI required for a one-off deploy.

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

## Presenter timing (9 slides, ~10 minutes)

Not shown on the slides themselves — for rehearsal only.

| Slide | Content | Target time |
|---|---|---|
| 1 | Title | 0:20 |
| 2 | About Me | 0:40 |
| 3 | Project Elevator Pitch | 0:55 |
| 4 | How It Works | 1:05 |
| 5 | Technical Challenge | 1:10 |
| 6 | Biggest Mistake | 1:05 |
| 7 | Final Results | 0:45 |
| 8 | Demo slide + live demo | 3:00 |
| 9 | Closing | 0:15 |

Total: approximately 9:15–10:00.

Live demo order (run after leaving the Demo slide, return to Closing at the end):

1. Open n8n, show the workflow at a high level.
2. Run the Apple request.
3. Open the final Research Result — show status, resolved company, evidence count, evidence text, similarity score, and SEC source URL.
4. Run or show the Microsoft request and confirm it returns evidence successfully.
5. Briefly explain that this was the regression case fixed during development.
6. Return to the Closing slide.
