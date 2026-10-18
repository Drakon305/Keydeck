# KeyDeck User Guide

KeyDeck is a panel of buttons that sits on your screen. Click a button (or press its hotkey) and its saved text is typed into whatever text box you were just using: Discord, a game chat, a browser, anything.

---

## 1. Install

1. Download: **[KeyDeck.exe](https://github.com/Drakon305/Keydeck/releases/latest/download/KeyDeck.exe)**
2. Double-click it. It installs itself, adds **Desktop** and **Start Menu** shortcuts, and opens.
3. If Windows says *"Windows protected your PC"*, click **More info → Run anyway** (the app just isn't signed by a big company).

From then on, open KeyDeck from the Desktop shortcut.

---

## 2. The window

| Part | What it does |
|---|---|
| **✎ Edit buttons** | Edit mode: click any button to change it. Click **✓ Done editing** when finished. |
| **+ Add** | Make a new button on the page you're looking at. |
| **📦 Library** | Browse ready-made button sets and add the ones you want. |
| **⚙ Settings** | All options (see section 8). |
| **Tabs** (Main, Game, …) | Your pages. Click to switch, or scroll the mouse wheel over them. |
| **The buttons** | Click to post. **Right-click** any button for **Edit / Duplicate / Submit to Library / Delete**. |

- **Move it:** drag the title bar.
- **Resize it:** drag any edge or corner. The buttons stretch to fill.
- **X** fully closes KeyDeck. **_** minimizes it. **Ctrl+Alt+P** shows/hides it.
- KeyDeck remembers its size, position and last page.

**Using a button:** click into the text box first (e.g. the Discord message box), then click the KeyDeck button. The text goes where your cursor was.

---

## 3. Making a button

Click **+ Add** (or right-click an existing button). In the editor:

- **Button name** – what the button shows.
- **Hotkey (optional)** – click **Record**, press a combo like Ctrl+Alt+1. Works even when KeyDeck is hidden.
- **Text to post** – the message. Can use text commands (section 4).
- **Preview** – shows 3 sample results so you can check it before saving.
- **Color** – pick a color.
- **Shown on page** – which page the button lives on (use this to move a button to another page).
- **What it does:**
  - **Post text** – normal button.
  - **Slash command** – fills in a Discord command like `/reply` for you (see "Discord slash commands" below).
  - **Go to page:** – the button jumps to another page instead (section 5).
- **Paste it** (fast, works almost everywhere) or **Type it out** (needed for Discord slash commands and apps that block pasting).
- **Copy it to the clipboard only** – types nothing, just puts the text on your clipboard (e.g. a "MY STEAMID" button, so `{clipboard}` buttons can use it).
- **Press Enter after** – sends the message automatically.
- **Enabled** – untick to switch a button off without deleting it.
- **Delete / Duplicate / ◀ Move / Move ▶** – remove, copy, or reorder the button.

**Duplicate** (right-click a button → Duplicate) makes a copy right next to it and opens it, so you only change what's different. The copy has no hotkey, since two buttons can't share one.

---

## 4. Text commands

Put these anywhere in a button's text:

| Command | What it does | Example |
|---|---|---|
| `{a\|b\|c}` | Picks one at random each time | `{Hello!\|Hey there!\|Welcome in!}` |
| `{clipboard}` | Whatever you last copied | `/tp {clipboard}` |
| `{enter}` | Presses Enter right there | `Hello!{enter}Welcome in!{enter}` → two messages |
| `{tab}` | Presses Tab | moves between Discord command options |
| `{wait 2}` | Pauses 2 seconds | gives Discord/games time to catch up |
| `{key f1}` | Presses any key or combo | `{key f1}vanish{enter}{key f1}` (Rust console), `{key ctrl+v}`, `{key windows+d}` |

- Round brackets work too: `(enter)`, `(tab)`, `(wait 2)`.
- You can combine them: `/tp {clipboard}{enter}{wait 2}/heal {clipboard}{enter}`
- `{clip}` and `{copied}` do the same as `{clipboard}`.

### Discord slash commands (like /reply)

**The easy way:** in the button editor choose **Slash command**, then fill in:

- **Command:** `/reply`
- **1st option:** the category, e.g. `General Support`
- **2nd option:** the response, e.g. `Raid Not Spawning`
- **3rd option:** only if the command has one

KeyDeck types the command, picks each option from Discord's list, and sends it. Type the option names the way they appear in Discord's list. **Preview** shows exactly what it will do. `{clipboard}` and `{a|b}` work inside options too.

If Discord is laggy and it sends too early or says "response not found", change **Settings → Slash command speed** to **Slow** (or **Very slow**). That slows down every slash-command button at once.

**The manual way** (for anything the easy way can't do): use **Type it out**, untick **Press Enter after**, and use this pattern:

```
/reply{wait 1}{tab}CATEGORY{wait 1.5}{tab}RESPONSE{wait 2}{tab}{wait 0.5}{enter}
```

Example:

```
/reply{wait 1}{tab}General Support{wait 1.5}{tab}Raid Not Spawning{wait 2}{tab}{wait 0.5}{enter}
```

- "Response not found" → make the waits longer (`{wait 3}`) or type less of the response (`Raid Not`).
- Sends too early → make the waits longer.

---

## 5. Pages

- **+ Page** (end of the tab row) – make a new page.
- **Double-click** the current tab – rename it.
- **Right-click** a tab – Rename, Export this page, Import buttons, Move left/right, Delete page.
- **Go-to-page buttons:** in the button editor choose **Go to page:** and pick a page. Clicking it (or its hotkey) jumps there. Tip: put a "Back to Main" button on each page.
- **Hotkeys work on every page**, not just the one showing.

---

## 6. Button Library

Click **📦 Library**. It shows every button people have shared as colored tiles, grouped by where they came from.

- **🔍 Search** to find buttons by name or text.
- **Click tiles** to select as many as you want, from any group (selected tiles get an orange border and ✓). **Hover** a tile to read its full text at the bottom.
- **Select all** on a group header ticks the whole group.
- **Add to:** pick one of your pages, or **➕ New page…**, then click **Add**.
- If a hotkey in an added button is one you already use, it's left off (you keep yours).
- Go-to-page buttons aren't listed (they only work inside their own set).

**Admin (Drakon):** with admin mode on, **right-click** any tile for **✎ Edit** (change its name, text/command, color) or **🗑 Delete**, and every group has **🗑 Delete group**. Changes go live in everyone's Library right away. Copies people already added aren't touched.

**Sharing your buttons:** right-click a single button → **Submit to Library…**, or submit a whole page: right-click the tab → **Submit to Library…**. Drakon approves it, then it shows up in everyone's Library.

---

## 7. Backup and sharing

- **Settings → Export buttons…** saves all your buttons to a `.keydeck` file (Documents folder by default). Keep it as a backup.
- **Right-click a tab → Export this page…** saves just that page.
- **Settings → Import buttons…** loads a `.keydeck` file:
  - **Yes** = add its pages next to yours
  - **No** = replace all your buttons with it (asks again first)
- Send a `.keydeck` file to a friend and they can import it the same way.

---

## 8. Settings

| Setting | What it does |
|---|---|
| Buttons per row / Button size / Font size | Layout of the grid |
| Opacity | See-through window |
| Show/hide hotkey | Default **Ctrl+Alt+P** |
| Keep KeyDeck on top | Stays above other windows |
| Slash command speed | How long slash-command buttons wait for Discord (Fast → Super slow) |
| Show hotkeys on buttons | Small hotkey text on each button |
| Start KeyDeck with Windows | Opens automatically when you log in |
| Tester: get new versions early (beta) | Get new versions before everyone else |
| Fit window to buttons | Snap the window back to fit the grid |
| Check for updates | Look for a new version now |
| Export / Import buttons | Backup and sharing (section 7) |
| Quit KeyDeck / Uninstall | Close it, or remove it from the PC |

---

## 9. Updates

KeyDeck checks for a new version a few seconds after it opens. If there is one, it asks **"Update now?"** — click **Yes** and it updates and restarts itself. Your buttons are kept. Nobody is ever forced to update.

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| Text goes nowhere | Click into the text box first, then the KeyDeck button. |
| Hotkey does nothing in a game | The game may run as admin: right-click KeyDeck → **Run as administrator**. |
| App won't accept pasting | Set the button to **Type it out**. |
| Can't find the window | Press **Ctrl+Alt+P**, or open KeyDeck again from the Desktop shortcut. |
| Antivirus deleted it | Allow KeyDeck.exe in your antivirus, then download it again. |
| Something crashed | The details are in `%APPDATA%\KeyDeck\startup.log` — send that file to Drakon. |

---

## For Drakon (admin only)

- **Getting changes:** ask Claude. Each change is built and tested on Windows automatically and published as a **beta**.
- **Testing a beta:** tick **Settings → Tester** on your KeyDeck, reopen it, accept the update.
- **Releasing to everyone:** GitHub → **Actions** → **Release beta to everyone** → **Run workflow**.
- **Library admin:** Settings → **Library admin key…** → paste your admin key (once). The Library window then shows **📥 Submissions** at the top: **Try it** (adds a test copy to your KeyDeck), **Preview**, **Approve** (goes live in everyone's Library right away) or **Reject**. Approving a set with the same name as an existing one replaces it, and people who added it get an **Update** button.
- **Adding a set yourself:** submit it like anyone else and approve it, or upload the `.keydeck` file to the `packs` folder on GitHub. Delete a file from `packs` to remove it from the Library.
- **Download link to share:** https://github.com/Drakon305/Keydeck/releases/latest/download/KeyDeck.exe
