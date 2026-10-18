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
- Clicking a button doesn't take focus away from your game (Settings to turn off)
- **Pages** (tabs) to group buttons — right-click a tab to rename, move or delete it
- Optional global hotkey per button (works on every page)
- **Go-to-page buttons**: a button (or its hotkey) can jump straight to another page instead of posting text
- **Website buttons**: open a web address in your browser
- **Slash command buttons**: fill in `/reply` + options and KeyDeck types, picks and sends it (Settings → Slash command speed)
- Right-click a button: Edit / Duplicate / Submit to Library / Delete
- Paste, type-out, or copy-to-clipboard-only mode, optional Enter before and/or after
- Text commands:
  - `{hello|hey|what's up}` — picks one at random each time
  - `{clipboard}` — whatever you last copied (e.g. `/tp {clipboard}`)
  - `{enter}` — presses Enter right there, so one button can send several messages (`Hello!{enter}Welcome in!{enter}`)
  - `{wait 2}` — pauses that many seconds before continuing
  - `{tab}` — presses Tab (moves between Discord slash-command options)
  - `{key f1}` — presses any key or combo, e.g. `{key f1}vanish{enter}{key f1}` or `{key ctrl+v}`
  - Round brackets work too: `(enter)`, `(tab)`, `(wait 2)`
- **Stream Deck import**: Settings → Import Stream Deck profile… turns an Elgato profile into KeyDeck pages
- **Auto pages**: right-click a tab → Show automatically in… (e.g. RustClient.exe)
- **Backup & share**: Settings → Export buttons… saves a `.keydeck` file; Import buttons… loads one (add alongside yours, or replace). Right-click a tab to export just that page.
- Settings → **Uninstall** removes it cleanly

## Button Library

Click **📦 Library** in KeyDeck to see every shared button as colored tiles. Search, click to select as many as you want, and add them to any of your pages (or a new one) in one go. Your own buttons are never changed.

**Sharing:** right-click a button (or a page tab) → **Submit to Library…**. The admin approves it from inside KeyDeck, and can edit or delete Library buttons by right-clicking them.

## Testing updates before everyone gets them

New versions are published as a **beta** first. Only copies with **Settings → Tester: get new versions early (beta)** ticked are offered them.

When a beta looks good: **Actions → Release beta to everyone → Run workflow**. Everyone's KeyDeck then offers the update the next time it opens.

## For the developer

- `keydeck.py` is the whole app.
- To release: bump `VERSION` in `keydeck.py` and push to `main`. The **Build KeyDeck** GitHub Action builds and self-tests `KeyDeck.exe` on Windows, then publishes it as a beta (pre-release).
- `run_debug.bat` runs the source with a visible console for troubleshooting.
