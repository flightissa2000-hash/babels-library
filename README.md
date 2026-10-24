# Babel's Library — your offline library

(The program folder is still called `Inkwell`, its earlier name.)

A personal library for articles and books that runs entirely on your computer.

## Start it
- **Windows:** double-click `Start-Inkwell.bat`. The first time, it installs the small window library it needs
  (one-time, needs internet) and adds an **Babel's Library** shortcut to your Desktop and Start menu. After that, just use the shortcut.
- **macOS / Linux:** run `Start-Inkwell.command` / `./start-inkwell.sh`

Babel's Library opens in its own window (no browser tabs or address bar), along with the desktop widget.
The only requirement is Python 3.9 or newer (https://www.python.org/downloads/; tick "Add python.exe to PATH").
Prefer a browser tab? Use `Open-In-Browser.bat` and go to http://localhost:8765.

## Desktop widget
Babel's Library is either the full window or a small desktop widget, never both. Click the widget button in the top bar
to shrink Babel's Library into the widget; double-click the widget (or its expand button) to bring it back full screen.
- The widget shows what you've read recently, with progress, and searches your whole library. Double-click a book to
  open it straight in the reader, or click its Read / Play / Watch button once. Enter in the search opens the top result.
- **Drag** it by its title bar, or snap it to a corner. Click the **pin** to fix it in place: it can't be moved or
  resized until you unpin it.
- It's an ordinary window, so other windows can sit in front of it.
- **Music plays inside the widget.** Click Play on a song and its album plays from there; the bottom of the widget
  becomes a now-playing bar with shuffle, previous, play/pause, next and the queue. Switching between the widget and
  the full window carries the music across without stopping.
- The ✕ on the widget closes Babel's Library. Settings → Desktop widget lets Babel's Library start as the widget.

## Windows and Linux on one drive
Babel's Library and its library can live on a drive both systems can read (exFAT or NTFS), for example `F:\Inkwell` with the
library in `F:\Library`. File locations are saved relative to the drive, so the same library opens on either system.
- **Windows:** double-click `Start-Inkwell.bat`.
- **Linux:** run `bash start-inkwell.sh` once (it adds Babel's Library to your applications menu). For the native window install
  GTK WebKit, e.g. `sudo apt install python3-gi gir1.2-webkit2-4.1`; without it Babel's Library opens in a Chrome/Chromium/Edge
  app window. Folders picked on one system (inbox, Zotero, Calibre) fall back to this computer's defaults on the other.
- **Moving an install:** put a `relocate.json` next to the new copy's `app` folder
  (`{"from": "<old Babel's Library folder>", "library": "@/Library"}`); the first start copies the library data across and moves
  every library file, with progress shown at the top of the window.

## Audiobooks
Open a book's details (EPUB or PDF) and choose **Make audiobook**. A natural-sounding voice (Piper, free and offline)
reads the book into one MP3 per chapter in `Library\Audiobooks\Author\Title`, in the background with progress at the
top. The first time, the voice engine and voice (about 80 MB) are downloaded. Then:
- **One listing per book:** the book shows 📖 Read and 🎧 Listen; the widget has a Listen button too. Audiobooks never
  appear in Music or in shuffle.
- Listening remembers where you stopped. Pick a chapter from the list in the details.
- **Read along:** with the book open, press 🎧 Listen in the reader to start from the chapter you're on; the sentence
  being spoken is highlighted and the pages follow along (turn pages yourself and it stops following for a few seconds).

## Reading comfort
- Notes start closed; open them with **Notes**.
- **Hide the toolbar** (the ☰ button or **H**) for distraction-free reading; move the mouse to the top edge to bring it
  back, or press H / Esc.
- In one-page and two-page views, arrows sit in the margins either side of the page.

## Refresh the library
Settings → **↻ Refresh library** rechecks the library folder: new files are added, files you moved or renamed are found
again, and entries whose files are gone are removed (nothing is removed if the drive isn't connected).

## Your library folder
Every file Babel's Library manages lives in one normal folder you choose (default: `Documents\Inkwell Library`):
`Articles`, `Books`, `Graphic Novels` (manga in `Graphic Novels\Manga`), `Music\Artist\Album`, `TV\Series\Season NN`
and `Movies`. Click **Change** next to the library folder at the top of the window (or in Settings) to switch at any
time (also from Add to library, under "Main library folder → Change or move…"): either move your whole library to the
new folder, or just switch and leave existing files where they are. Removing an
item asks whether to keep or delete its file. "Rename file to match title" in an item's details tidies its file name.

## How things are sorted
- **Subject** uses the broad classes of the Library of Congress Classification (Science, Social Sciences, Language &
  Literature, History, Medicine, Technology & Engineering, …).
- **Topic** is the discipline inside that (Physics & Astronomy, Chemistry & Materials, Language & Linguistics, Fiction…).
- **Genre** uses bookseller genres (Fantasy, Science Fiction, Mystery & Crime…; Science, History, Foreign Language Study…
  for non-fiction). Articles have no genre. When online, Babel's Library reads the publisher's categories to get this right.
- **Series** is found from the book's own data, its title ("The Way of Kings: The Stormlight Archive") or ComicInfo.
- **Tags** are a small set of broad themes; garbled text from badly-extracted PDFs is filtered out.
- Books show the publisher's **synopsis**; articles show their **abstract**.
- Anything you change yourself (genre, series, subject, tags, synopsis…) is never overwritten by re-sorting.

## Adding things
- **Files:** drag PDFs, EPUBs, CBZs or CBRs onto the window, or use Add to library → Files.
- **Scan a folder:** Add to library → Scan a folder. Babel's Library searches the folder and every sub-folder and adds each
  article, book or graphic novel that isn't already in your library (duplicates are detected by file content) and
  moves it into the library folder. Untick "Move" to copy instead and leave the originals where they are.
- **Zotero or Calibre:** Add to library → Zotero or Calibre. Brings in your items with their files (copied into the
  library folder), tags, notes, and Zotero PDF highlights. For Zotero items with no PDF, it can download a free
  open-access copy when one exists.
- **DOI / ISBN / link:** fills in the details from CrossRef / OpenLibrary and, if a free legal copy exists
  (open access, arXiv, or a direct PDF link), downloads it into the library folder. This and the Zotero downloads are
  the only parts that need internet.
- **Inbox folder (automatic):** anything saved into `Library-Inbox` in your home folder is added on its own.
  Files are moved out of the inbox into the library folder (you can switch this to copying in Settings).
- **Type it in:** for physical books.

## Music, TV & Movies
Music and TV & Movies each have their own tab at the top. TV shows and films get their official poster as the cover
(looked up online; use **Find poster** in the details if one is wrong or missing), a **Watched** checkbox (ticked
automatically when you finish), and a **Currently watching** row that resumes a half-watched episode or film, or
starts the next episode of a show.
 Add MP3, FLAC, M4A, OGG, WAV, MP4, MKV, WEBM and other files the same
ways as books. Music is organised by album (with cover art from the files), TV by series and season, and movies by genre
or series. Albums play in the player bar at the bottom; TV and movies play in the reader and remember where you stopped.
Some video formats (for example certain MKV or AVI files) can't play inside Babel's Library; use "Show in folder" to open those
in your usual video player.

### Music player
- **Shuffle** button in the player (remembered). An album's **Shuffle** button shuffles that album; **Shuffle all
  music** (top of the Music shelf) shuffles every song in every album.
- **Queue:** in an album, use **Play next** or **Add to queue** for the whole album, or the ⤵ / ＋ buttons on a song.
  The ☰ button in the player shows what's up next; click a song to jump to it or ✕ to drop it.

### TV episodes
Episodes are grouped into one show even when they're named like anime releases (`[Group] Show S1 - 03.mkv`,
`Show - 03 [1080p].mkv`) or spelled slightly differently (`Psycho Pass` and `Psycho-Pass` become one show).

### Audio language and subtitles
Under the video are **Audio** and **Subtitles** menus. They list every audio language and text subtitle track inside
MKV files, plus subtitle files next to the video (`Episode.en.srt`, `.ass`, `.vtt`, or a `Subs` folder). Your choice is
remembered for the whole show. Picture-based subtitles (PGS/VobSub from Blu-rays) can't be shown yet.

## Collections
Make your own collections (Summer reading, Thesis sources, Road-trip music…) from the **Collections** bar under the top
bar, from an item's details, or from an album. Click a collection to see only what's in it; Group → Collection sorts by
them. A music collection can be played with ▶ Play.

## Checkout: copy files anywhere
Click **Select**, pick any books, articles, comics, songs, whole albums or whole shows (or "Select all shown"), then
**Check out…** and choose a folder, such as a USB stick or a reader. The files are copied there and stay in your library.
Tick "Keep the library's folders" to copy them with their Books\…, Music\Artist\Album… folders. A whole collection
or album can be checked out from its own Check out button too.

## Reading layouts
Every reader (PDF, EPUB, comics) has a **View** menu: **Scrolling**, **One page** or **Two pages**, plus a page-width
slider (and text size for EPUBs). In the page layouts, click the left or right side of the page to turn it, or use the
arrow keys. Click any picture or figure (or the ⤢ button on a page) to see it full screen, then scroll or use +/- to
zoom and drag to look around. The ⛶ button switches between full screen and a window. Select an annotation and press
Delete to remove it (with Undo).

## Graphic novels and manga
CBZ and CBR comics are their own category. Manga is detected from the file's ComicInfo data, publisher or name and
filed under Graphic novels: Manga, reading right to left. In the reader, **click anywhere on a page to pin a note
there**; drag pins to move them. Use the arrow keys or click beside the page to turn pages, "Two pages" for spreads,
and the direction button to switch left-to-right / right-to-left.

## Pins for articles and books
In the PDF and EPUB reader, turn on **Pin** and click anywhere on the page to drop a comment there (PDF pins can be
dragged). Highlights with notes still work by selecting text.

## Smarter offline AI (optional, recommended)
Out of the box, a built-in offline analyser sorts and tags items using keyword models. For much better topics, tags,
genres and summaries — still 100% offline — install **Ollama** (https://ollama.com), then in a terminal run:

    ollama pull llama3.2

Restart Babel's Library. Settings shows "Local AI connected", and new items are read by the model on your machine.
Use "Re-sort and re-tag" on older items to upgrade them.

## Features
- Articles sorted by general topic; books groupable by genre, subject, fiction/non-fiction, year, author, tag or type
- Tags for the major topics in each work; edit them freely
- APA, MLA and Chicago citations for every item (copy buttons; bibliography export in Settings)
- Reader for PDFs and EPUBs with highlights in four colours and notes with an optional title
- Export annotations as Markdown or JSON (per item or everything)
- Two browsing views for books: Catalogue (drawers of index cards with call numbers and the synopsis or abstract) and Calling cards
- Two themes: Word Town (inspired by Noun Town) and Gruvbox. Original designs; no game artwork is included.
- **Review journal:** a book of everything you've read and watched, with dated entries. Pull it out from the
  bookmark on the right edge (or press J) and it's set down on top of whatever you're doing (the reader, a video,
  the browser) without stopping it: drag it by its cover, resize it from its corner, tuck it away with the ribbon.
  Notes that aren't about media ("✦ A note") get a 📷 Photo button: drag over any part of the screen and it's kept
  as a polaroid under the details, numbered as a figure; write "Fig. 2" in an entry and that polaroid lights up.
- **Browser** inside the window: ads, trackers, pop-ups and YouTube's own ads blocked; split view (⧉) shows two pages
  side by side, each with its own ✕; reopen the last page with ↺; history behind a button or a pull-up sheet;
  saved passwords encrypted for your Windows account; save any article into the library to read offline.
- **The Bulletin** on the home page: articles you haven't opened, things to discover, and a weekly pick to finish
  (or revisit).
- **Catalogue** of books, manga, comics, films, TV and animation to discover, and a **news desk** of university and
  lab press releases plus local news and events.
- **Phone app** (Android, separate project): your library, readers, journal and browser, synced with this computer.

## Your data
Your files are in your library folder. The catalogue, notes, journal photos and covers live in `library_data/` next to
this README. Back up both to back up your library. `library_data/` is personal (it also holds your settings and keys)
and is never part of the source repository.

## Credits
Bundled open-source components: pdf.js (Apache-2.0), epub.js (BSD-2), JSZip (MIT), libarchive.js (MIT), pypdf (BSD-3), mutagen (GPL-2), word-list (MIT),
fonts from Google Fonts via Fontsource (SIL Open Font License).
