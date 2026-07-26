# Web Architecture & SPA Design

Verse includes a responsive Single Page Application (SPA) built with Vanilla HTML5, CSS3, and ES6 JavaScript served directly via FastAPI.

---

## 1. Web Architecture Overview

```mermaid
graph TD
    subgraph Client Browser
        DOM["DOM View Containers (#view-home, #view-assistant, #view-create, #view-playlist-detail)"]
        JS_APP["JavaScript SPA Controller (index.js)"]
        AUDIO_NODE["HTML5 <audio id='main-audio-element'> Node"]
        CSS_TOKENS["Design System & Theme Tokens (index.css)"]
    end

    subgraph FastAPI Web Server (app/api/server.py)
        STATIC_MOUNT["StaticFiles Mount (app/web -> /)"]
        REST_SONGS["/api/v1/songs"]
        REST_SEARCH["/api/v1/search"]
        REST_PLAYLISTS["/api/v1/playlists"]
        REST_PLAYBACK["/api/v1/playback"]
        REST_ASSISTANT["/api/v1/assistant"]
    end

    JS_APP -->|DOM Navigation & Click Listeners| DOM
    JS_APP -->|HTML5 Audio Control & Event Tracking| AUDIO_NODE
    JS_APP -->|HTTP Fetch Requests| REST_SONGS
    JS_APP -->|HTTP Fetch Requests| REST_SEARCH
    JS_APP -->|HTTP Fetch Requests| REST_PLAYLISTS
    JS_APP -->|HTTP Fetch Requests| REST_PLAYBACK
    JS_APP -->|HTTP Fetch Requests| REST_ASSISTANT
    STATIC_MOUNT -->|Serves index.html, index.js, index.css| DOM
```

---

## 2. File Organization

The web frontend resides in [app/web/](file:///home/hisham/projects/music-rec/app/web/):
- **`index.html`** ([file:///home/hisham/projects/music-rec/app/web/index.html](file:///home/hisham/projects/music-rec/app/web/index.html)): Complete HTML structural layout featuring a 3-column layout (Left Navigation Sidebar, Center Main Dynamic View, Right Now Playing / Assistant Preview Panel).
- **`index.css`** ([file:///home/hisham/projects/music-rec/app/web/index.css](file:///home/hisham/projects/music-rec/app/web/index.css)): Modern CSS design system featuring custom HSL CSS variables (`--bg-main`, `--accent-primary`, `--glass-surface`), flexbox/grid layouts, smooth animations, glassmorphism backdrop filters, custom scrollbars, and dynamic resizers.
- **`index.js`** ([file:///home/hisham/projects/music-rec/app/web/index.js](file:///home/hisham/projects/music-rec/app/web/index.js)): State manager, DOM view router, HTTP API fetch client, player controller, and AI Assistant chat renderer.

---

## 3. View Routing & State Management

### Views
Navigation is managed client-side without page reloads by toggling `.active` classes on section elements:
1. `#view-home`: Library grid, continuation mixes, recently played, filter row, and paginated song table.
2. `#view-assistant`: AI Assistant chat conversation view with prompt suggestion chips.
3. `#view-create`: Interactive custom playlist rule generator form & preview table.
4. `#view-playlist-detail`: Rich hero header, artwork display, AI parameter metadata card, and full playlist song list.

### Global State Object (`index.js`)
```javascript
const state = {
  currentView: 'view-home',
  songs: [],
  currentPage: 1,
  totalPages: 1,
  pageSize: 20,
  currentSong: null,
  queue: [],
  queueIndex: 0,
  isPlaying: false,
  isShuffled: false,
  isRepeated: false,
  volume: 0.7,
  activePlaylist: null,
  activeSessionId: null,
};
```

---

## 4. Playback Persistence & Event Listeners

Audio playback uses an invisible HTML5 `<audio id="main-audio-element">` node.
- `timeupdate` listener updates the active progress slider and current time labels.
- `ended` listener automatically advances `state.queueIndex`, triggers next song playback, and notifies the backend `/api/v1/playback/play` endpoint to log play history.
- Browser `localStorage` maintains UI state across page refreshes.
