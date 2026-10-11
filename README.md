# KeyDeck

An on-screen button deck for Windows. Click a button (or press its hotkey) and its saved text drops into whatever text box you were typing in — Discord, a game chat, a browser, anything.

## Download

**[Download KeyDeck.exe](https://github.com/Drakon305/Keydeck/releases/latest/download/KeyDeck.exe)** — always the newest version.

Double-click it and it installs itself (Desktop + Start Menu shortcuts) and opens. Nothing else to install.

> Windows may say *"Windows protected your PC"* because the app isn't signed. Click **More info → Run anyway**.

KeyDeck checks for updates when it opens and offers to install new versions itself, keeping all your buttons. You can also use **Settings → Check for updates**.

**📖 New here? Read the [User Guide](GUIDE.md)** — everything KeyDeck can do, step by step.

## Features

- Grid of colored buttons, resizable window, always-on-top option
- **Pages** (tabs) to group buttons — right-click a tab to rename, move or delete it
- Optional global hotkey per button (works on every page)
- **Go-to-page buttons**: a button (or its hotkey) can jump straight to another page instead of posting text
- Paste or type-out mode, optional auto-Enter
- Text commands:
  - `{hello|hey|what's up}` — picks one at random each time
  - `{clipboard}` — whatever you last copied (e.g. `/tp {clipboard}`)
  - `{enter}` — presses Enter right there, so one button can send several messages (`Hello!{enter}Welcome in!{enter}`)
  - `{wait 2}` — pauses that many seconds before continuing
  - `{tab}` — presses Tab (moves between Discord slash-command options)
  - Round brackets work too: `(enter)`, `(tab)`, `(wait 2)`
- **Backup & share**: Settings → Export buttons… saves a `.keydeck` file; Import buttons… loads one (add alongside yours, or replace). Right-click a tab to export just that page.
- Settings → **Uninstall** removes it cleanly

## Button Library

Click **📦 Library** in KeyDeck to browse ready-made button sets and add the ones you want as new pages. Your own buttons are never changed, and if a set is improved later, the Library shows an **Update** button.

**Adding a set to the library:** build the buttons on their own page in KeyDeck, right-click the tab → **Export this page…**, then upload the `.keydeck` file into the [`packs`](packs) folder on GitHub (open the folder → **Add file → Upload files**). It shows up in everyone's Library right away. Upload a file with the same name to update it.

## Testing updates before everyone gets them

New versions are published as a **beta** first. Only copies with **Settings → Tester: get new versions early (beta)** ticked are offered them.

When a beta looks good: **Actions → Release beta to everyone → Run workflow**. Everyone's KeyDeck then offers the update the next time it opens.

## For the developer

- `keydeck.py` is the whole app.
- To release: bump `VERSION` in `keydeck.py` and push to `main`. The **Build KeyDeck** GitHub Action builds and self-tests `KeyDeck.exe` on Windows, then publishes it as a beta (pre-release).
- `run_debug.bat` runs the source with a visible console for troubleshooting.
