// MuseAI Single Page Application Logic

// Application State
let currentState = {
  currentPage: 1,
  pageSize: 100,
  totalSongs: 0,
  songs: [],
  activeTab: 'view-home',
  currentPlayingSong: null,
  isPlaying: false,
  queue: [],
  queueIndex: -1,
  likedSongIds: new Set(),
  activePlaylistId: null,
  activeSessionId: null,
  lastProgressSync: 0
};

// SVG Icon Helpers to keep HTML clean
const SVG_ICONS = {
  music: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 18V5l12-2v13M9 9h12"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`,
  heart: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>`,
  heartFilled: `<svg viewBox="0 0 24 24" fill="#ef4444" stroke="#ef4444" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>`,
  options: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>`,
  play: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`,
  pause: `<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>`
};

// DOM Elements
const elements = {
  audio: document.getElementById('main-audio-element'),
  navHome: document.getElementById('nav-home'),
  navAssistant: document.getElementById('nav-assistant'),
  navCreate: document.getElementById('nav-create'),
  views: document.querySelectorAll('.content-view'),
  navItems: document.querySelectorAll('.nav-item'),
  songsTableBody: document.getElementById('songs-table-body'),
  paginationContainer: document.querySelector('.pagination-container'),
  btnPrevPage: document.getElementById('btn-prev-page'),
  btnNextPage: document.getElementById('btn-next-page'),
  paginationInfo: document.getElementById('pagination-info'),

  // Playback Elements (Now Playing Sidebar)
  barTitle: document.getElementById('np-title'),
  barArtist: document.getElementById('np-artist'),
  barMiniArt: document.getElementById('np-large-art'),
  barLikeBtn: document.getElementById('np-like-btn'),
  barBtnPlay: document.getElementById('np-btn-play'),
  barPlayIcon: document.getElementById('np-play-icon'),
  barBtnPrev: document.getElementById('np-btn-prev'),
  barBtnNext: document.getElementById('np-btn-next'),
  barBtnShuffle: document.getElementById('np-btn-shuffle'),
  barBtnRepeat: document.getElementById('np-btn-repeat'),
  barProgressSlider: document.getElementById('np-progress-slider'),
  barTimeCurrent: document.getElementById('np-time-current'),
  barTimeTotal: document.getElementById('np-time-total'),
  barVolumeSlider: document.getElementById('np-volume-slider'),
  barBtnVolume: document.getElementById('np-btn-volume'),

  // Search Overlay
  searchOverlay: document.getElementById('search-overlay'),
  searchOverlayInput: document.getElementById('search-overlay-input'),
  searchOverlayResults: document.getElementById('search-overlay-results'),

  // Create Playlist
  playlistForm: document.getElementById('playlist-generator-form'),
  playlistStrategy: document.getElementById('playlist-strategy'),
  playlistSeedType: document.getElementById('playlist-seed-type'),
  playlistSeedValue: document.getElementById('playlist-seed-value'),
  playlistLimit: document.getElementById('playlist-limit'),
  generatedResults: document.getElementById('generated-playlist-results'),
  generatedSongsBody: document.getElementById('generated-songs-table-body'),
  newPlaylistName: document.getElementById('new-playlist-name'),
  btnSavePlaylist: document.getElementById('btn-save-playlist'),
  sidebarPlaylists: document.getElementById('sidebar-playlists')
};

// 1. NAVIGATION / SPA ROUTING
function initNavigation() {
  elements.navItems.forEach(item => {
    item.addEventListener('click', () => {
      const targetViewId = item.getAttribute('data-target');
      
      // Update active nav button
      elements.navItems.forEach(nav => nav.classList.remove('active'));
      item.classList.add('active');
      
      // Update active view visibility
      elements.views.forEach(view => {
        if (view.id === targetViewId) {
          view.classList.add('active');
        } else {
          view.classList.remove('active');
        }
      });
      
      currentState.activeTab = targetViewId;
      console.log(`Navigated to: ${targetViewId}`);

      // If returning home, restore full songs list and dynamic sections
      if (targetViewId === 'view-home') {
        fetchSongs(1);
        loadHomePageSections();
      }
    });
  });
}

// 2. SONG UTILITIES
function formatDuration(seconds) {
  if (isNaN(seconds) || seconds === null) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
}

// 3. API FETCHING & RENDERING
async function fetchSongs(page = 1) {
  try {
    showTableLoading();
    
    const url = `/api/v1/songs?page=${page}&page_size=${currentState.pageSize}`;
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    
    currentState.songs = data.songs;
    currentState.total_count = data.total_count;
    currentState.currentPage = data.page;
    
    renderSongsTable();
    updatePaginationControls();
  } catch (error) {
    console.error("Failed to fetch songs:", error);
    showTableError("Failed to load music library. Make sure the backend server is running.");
  }
}

function showTableLoading() {
  elements.songsTableBody.innerHTML = `
    <tr class="table-loading-row">
      <td colspan="7" style="text-align: center; padding: 40px; color: var(--text-muted);">
        <div class="loader-spinner" style="margin-bottom: 12px; display: inline-block; width: 24px; height: 24px; border: 2px solid rgba(124,58,237,0.2); border-top-color: var(--accent-color); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
        <div>Loading your music library...</div>
      </td>
    </tr>
  `;
}

function showTableError(message) {
  elements.songsTableBody.innerHTML = `
    <tr>
      <td colspan="7" style="text-align: center; padding: 40px; color: #ef4444; font-weight: 500;">
        ${message}
      </td>
    </tr>
  `;
}

function renderSongsTable() {
  if (currentState.songs.length === 0) {
    elements.songsTableBody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; padding: 40px; color: var(--text-muted); font-style: italic;">
          No songs found in the library. Run 'verse scan &lt;path&gt;' in the terminal to add music.
        </td>
      </tr>
    `;
    return;
  }
  
  let html = '';
  const startIdx = (currentState.currentPage - 1) * currentState.pageSize;
  
  currentState.songs.forEach((song, idx) => {
    const globalIdx = startIdx + idx + 1;
    const isPlayingRow = currentState.currentPlayingSong && currentState.currentPlayingSong.id === song.id;
    const rowClass = isPlayingRow ? 'active-row' : '';
    const isLiked = currentState.likedSongIds.has(song.id);
    
    const artworkHtml = song.artwork_available
      ? `<img src="/api/v1/songs/${song.id}/artwork" alt="cover" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
         <div class="placeholder-fallback" style="display:none; align-items:center; justify-content:center; width:100%; height:100%;">${SVG_ICONS.music}</div>`
      : `<div class="placeholder-fallback" style="display:flex; align-items:center; justify-content:center; width:100%; height:100%;">${SVG_ICONS.music}</div>`;
      
    html += `
      <tr class="${rowClass}" data-song-id="${song.id}">
        <td class="col-num">${globalIdx}</td>
        <td class="col-heart">
          <button class="heart-btn ${isLiked ? 'liked' : ''}" data-song-id="${song.id}">
            ${isLiked ? SVG_ICONS.heartFilled : SVG_ICONS.heart}
          </button>
        </td>
        <td class="col-title">
          <div class="table-song-title-cell">
            <div class="table-song-art">
              ${artworkHtml}
            </div>
            <div class="table-song-meta">
              <span class="table-song-title-text">${escapeHtml(song.title)}</span>
              <span class="table-song-genre-tag">${escapeHtml(song.genre)}</span>
            </div>
          </div>
        </td>
        <td class="col-artist">${escapeHtml(song.artist)}</td>
        <td class="col-album">${escapeHtml(song.album)}</td>
        <td class="col-duration">${formatDuration(song.duration)}</td>
        <td class="col-options">
          <button class="options-row-btn">
            ${SVG_ICONS.options}
          </button>
        </td>
      </tr>
    `;
  });
  
  elements.songsTableBody.innerHTML = html;
  
  // Wire row click listeners and heart buttons
  const rows = elements.songsTableBody.querySelectorAll('tr[data-song-id]');
  rows.forEach(row => {
    row.addEventListener('click', (e) => {
      const songId = parseInt(row.getAttribute('data-song-id'));
      
      if (e.target.closest('.heart-btn')) {
        toggleLikeSong(songId);
        return;
      }
      if (e.target.closest('.options-row-btn')) {
        return;
      }
      
      const song = currentState.songs.find(s => s.id === songId);
      if (song) {
        playSong(song, currentState.songs);
      }
    });
  });
}

function updatePaginationControls() {
  const totalPages = Math.ceil(currentState.total_count / currentState.pageSize) || 1;
  
  if (totalPages <= 1) {
    if (elements.paginationContainer) {
      elements.paginationContainer.style.display = 'none';
    }
  } else {
    if (elements.paginationContainer) {
      elements.paginationContainer.style.display = 'flex';
    }
    elements.btnPrevPage.disabled = currentState.currentPage <= 1;
    elements.btnNextPage.disabled = currentState.currentPage >= totalPages;
    elements.paginationInfo.innerText = `Page ${currentState.currentPage} of ${totalPages}`;
  }
}

function initPagination() {
  elements.btnPrevPage.addEventListener('click', () => {
    if (currentState.currentPage > 1) {
      fetchSongs(currentState.currentPage - 1);
    }
  });
  
  elements.btnNextPage.addEventListener('click', () => {
    const totalPages = Math.ceil(currentState.total_count / currentState.pageSize) || 1;
    if (currentState.currentPage < totalPages) {
      fetchSongs(currentState.currentPage + 1);
    }
  });
}

// ==========================================
// 4. INSTANT SEARCH OVERLAY LOGIC
// ==========================================
let searchState = {
  isOpen: false,
  results: [],
  selectedIndex: -1
};

let searchTimeout = null;

function showSearchOverlay(initialChar = '') {
  if (searchState.isOpen) return;
  searchState.isOpen = true;
  elements.searchOverlay.classList.add('active');
  elements.searchOverlayInput.value = initialChar;
  elements.searchOverlayInput.focus();
  searchState.selectedIndex = -1;
  if (initialChar) {
    triggerSearch(initialChar);
  } else {
    elements.searchOverlayResults.innerHTML = '';
  }
}

function hideSearchOverlay() {
  searchState.isOpen = false;
  elements.searchOverlay.classList.remove('active');
  elements.searchOverlayInput.value = '';
  elements.searchOverlayResults.innerHTML = '';
  searchState.results = [];
  searchState.selectedIndex = -1;
}

async function triggerSearch(query) {
  const trimmed = query.trim();
  if (!trimmed) {
    elements.searchOverlayResults.innerHTML = '';
    searchState.results = [];
    searchState.selectedIndex = -1;
    return;
  }
  
  try {
    const response = await fetch(`/api/v1/search?q=${encodeURIComponent(trimmed)}`);
    if (!response.ok) throw new Error('Search failed');
    const data = await response.json();
    searchState.results = data;
    searchState.selectedIndex = -1;
    renderSearchResults();
  } catch (err) {
    console.error(err);
  }
}

function renderSearchResults() {
  if (searchState.results.length === 0) {
    elements.searchOverlayResults.innerHTML = `
      <div style="text-align: center; padding: 20px; color: var(--text-muted);">
        No matching songs found
      </div>
    `;
    return;
  }
  
  let html = '';
  searchState.results.forEach((song, idx) => {
    const isHighlighted = idx === searchState.selectedIndex;
    const highlightClass = isHighlighted ? 'highlighted' : '';
    html += `
      <div class="search-result-item ${highlightClass}" data-index="${idx}" data-song-id="${song.id}">
        <div class="table-song-art">
          ${song.artwork_available 
            ? `<img src="/api/v1/songs/${song.id}/artwork" alt="art" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
               <div style="display:none;">${SVG_ICONS.music}</div>`
            : SVG_ICONS.music}
        </div>
        <div class="search-result-meta">
          <div class="search-result-title">${escapeHtml(song.title)}</div>
          <div class="search-result-artist">${escapeHtml(song.artist)}</div>
        </div>
        <div class="search-result-duration">${formatDuration(song.duration)}</div>
      </div>
    `;
  });
  elements.searchOverlayResults.innerHTML = html;
  
  const items = elements.searchOverlayResults.querySelectorAll('.search-result-item');
  items.forEach(item => {
    item.addEventListener('click', () => {
      const idx = parseInt(item.getAttribute('data-index'));
      selectSearchResult(idx);
    });
  });
}

function selectSearchResult(index) {
  const song = searchState.results[index];
  if (!song) return;
  if (typeof playSong === 'function') {
    playSong(song);
  }
  hideSearchOverlay();
}

function handleSearchKeyboard(e) {
  if (!searchState.isOpen) return;
  
  if (e.key === 'Escape') {
    hideSearchOverlay();
    e.preventDefault();
  } else if (e.key === 'ArrowDown') {
    if (searchState.results.length > 0) {
      searchState.selectedIndex = (searchState.selectedIndex + 1) % searchState.results.length;
      renderSearchResults();
      scrollHighlightedIntoView();
    }
    e.preventDefault();
  } else if (e.key === 'ArrowUp') {
    if (searchState.results.length > 0) {
      searchState.selectedIndex = (searchState.selectedIndex - 1 + searchState.results.length) % searchState.results.length;
      renderSearchResults();
      scrollHighlightedIntoView();
    }
    e.preventDefault();
  } else if (e.key === 'Enter') {
    if (searchState.selectedIndex >= 0 && searchState.selectedIndex < searchState.results.length) {
      selectSearchResult(searchState.selectedIndex);
    }
    e.preventDefault();
  }
}

function scrollHighlightedIntoView() {
  const container = elements.searchOverlayResults;
  const highlighted = container.querySelector('.search-result-item.highlighted');
  if (highlighted) {
    highlighted.scrollIntoView({ block: 'nearest' });
  }
}

function initSearchEvents() {
  // Global keydown handler for shortcuts (Space toggle, instant search)
  window.addEventListener('keydown', (e) => {
    // 1. If search overlay is open, delegate arrow/enter/escape keys to handleSearchKeyboard
    if (searchState.isOpen) {
      handleSearchKeyboard(e);
      return;
    }

    // 2. Ignore modifier combinations (Ctrl/Alt/Meta)
    if (e.ctrlKey || e.altKey || e.metaKey) return;

    // 3. Ignore if focus is inside a text input, textarea, or select
    const activeEl = document.activeElement;
    const activeTag = activeEl ? activeEl.tagName.toLowerCase() : '';
    if (activeTag === 'input' || activeTag === 'textarea' || activeTag === 'select' || (activeEl && activeEl.isContentEditable)) {
      return;
    }

    // 4. Spacebar controls Play / Pause when no input is focused
    if (e.code === 'Space' || e.key === ' ') {
      e.preventDefault();
      togglePlayPause();
      return;
    }

    // 5. Instant search on Home view for printable query characters
    if (currentState.activeTab !== 'view-home') return;
    if (e.key.length > 1) return;

    showSearchOverlay(e.key);
    e.preventDefault();
  });

  // Debounced input typing handler
  elements.searchOverlayInput.addEventListener('input', (e) => {
    if (searchTimeout) clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      triggerSearch(e.target.value);
    }, 100);
  });

  // Click outside to close overlay
  elements.searchOverlay.addEventListener('click', (e) => {
    if (!e.target.closest('.search-overlay-content')) {
      hideSearchOverlay();
    }
  });

  // Unify the homepage search box click/focus
  const libSearchInput = document.getElementById('library-search-input');
  if (libSearchInput) {
    libSearchInput.addEventListener('focus', () => {
      libSearchInput.blur();
      showSearchOverlay();
    });
  }
}

// ==========================================
// 5. PLAYLIST GENERATION AND MANAGEMENT LOGIC
// ==========================================
let currentGeneratedSongs = [];

async function handleGeneratePlaylist(e) {
  e.preventDefault();
  
  const strategy = elements.playlistStrategy.value;
  const seedType = elements.playlistSeedType.value;
  const seedValue = elements.playlistSeedValue.value.trim();
  const limit = parseInt(elements.playlistLimit.value) || 20;
  
  // Validate seed value only for manual seed types
  const requiresSeedValue = ['song', 'mood', 'activity'].includes(seedType);
  if (requiresSeedValue && !seedValue) {
    alert(`Please enter a seed value for the selected seed type: ${seedType}`);
    return;
  }
  
  try {
    const btn = document.getElementById('btn-generate-playlist');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<div class="loader-spinner" style="display:inline-block; width: 14px; height: 14px; border: 1.5px solid rgba(255,255,255,0.2); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; margin-right: 6px;"></div> Generating...`;
    
    const response = await fetch('/api/v1/playlists/generate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        strategy: strategy,
        seed_type: seedType,
        seed_value: seedValue,
        limit: limit
      })
    });
    
    btn.disabled = false;
    btn.innerHTML = originalText;
    
    if (!response.ok) {
      throw new Error(`Generation failed: ${response.statusText}`);
    }
    
    const songs = await response.json();
    currentGeneratedSongs = songs;
    renderGeneratedPlaylist();
  } catch (err) {
    console.error(err);
    alert('Failed to generate playlist preview. Please verify your seed values.');
  }
}

function renderGeneratedPlaylist() {
  if (currentGeneratedSongs.length === 0) {
    elements.generatedSongsBody.innerHTML = `
      <tr>
        <td colspan="5" style="text-align: center; padding: 20px; color: var(--text-muted);">
          No recommendations found. Try a different seed or strategy.
        </td>
      </tr>
    `;
    elements.generatedResults.style.display = 'block';
    return;
  }
  
  let html = '';
  currentGeneratedSongs.forEach((song, idx) => {
    html += `
      <tr>
        <td class="col-num">${idx + 1}</td>
        <td class="col-title">
          <div class="table-song-title-cell">
            <div class="table-song-art">
              ${song.artwork_available 
                ? `<img src="/api/v1/songs/${song.id}/artwork" alt="cover" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
                   <div style="display:none;">${SVG_ICONS.music}</div>`
                : SVG_ICONS.music}
            </div>
            <div class="table-song-meta">
              <span class="table-song-title-text">${escapeHtml(song.title)}</span>
            </div>
          </div>
        </td>
        <td class="col-artist">${escapeHtml(song.artist)}</td>
        <td class="col-album">${escapeHtml(song.album)}</td>
        <td class="col-duration">${formatDuration(song.duration)}</td>
      </tr>
    `;
  });
  elements.generatedSongsBody.innerHTML = html;
  
  const seedValue = elements.playlistSeedValue.value.trim();
  const seedLabel = seedValue || elements.playlistSeedType.value.toUpperCase();
  elements.newPlaylistName.value = `${seedLabel} Mix (${elements.playlistStrategy.value})`;
  
  elements.generatedResults.style.display = 'block';
}

async function handleSavePlaylist() {
  const playlistName = elements.newPlaylistName.value.trim();
  if (!playlistName) {
    alert('Please enter a playlist name.');
    return;
  }
  
  const songIds = currentGeneratedSongs.map(s => s.id);
  if (songIds.length === 0) return;
  
  try {
    elements.btnSavePlaylist.disabled = true;
    const response = await fetch('/api/v1/playlists', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        name: playlistName,
        song_ids: songIds
      })
    });
    
    elements.btnSavePlaylist.disabled = false;
    
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      throw new Error(errorBody.detail || `Save failed (${response.status})`);
    }
    
    alert(`Playlist "${playlistName}" saved successfully!`);
    
    // Clear generation preview state
    elements.generatedResults.style.display = 'none';
    elements.playlistForm.reset();
    currentGeneratedSongs = [];
    
    // Refresh Sidebar list
    loadPlaylists();
  } catch (err) {
    console.error(err);
    alert(`Failed to save playlist: ${err.message}`);
    elements.btnSavePlaylist.disabled = false;
  }
}

async function loadPlaylists() {
  try {
    const response = await fetch('/api/v1/playlists');
    if (!response.ok) throw new Error('Failed to fetch playlists');
    const playlists = await response.json();
    
    if (playlists.length === 0) {
      elements.sidebarPlaylists.innerHTML = `
        <li style="font-size: 13px; color: var(--text-muted); padding: 8px; font-style: italic;">
          No playlists saved yet.
        </li>
      `;
      return;
    }
    
    let html = '';
    playlists.forEach(pl => {
      html += `
        <li class="playlist-sidebar-item" data-playlist-id="${pl.id}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 16px; height: 16px; margin-right: 8px;">
            <path d="M9 18V5l12-2v13M9 9h12"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>
          </svg>
          <span class="playlist-sidebar-name">${escapeHtml(pl.name)}</span>
          <span class="playlist-sidebar-count" style="font-size:11px; color:var(--text-muted); margin-left:auto;">${pl.songs_count}</span>
        </li>
      `;
    });
    elements.sidebarPlaylists.innerHTML = html;
    
    // Wire click listener
    const items = elements.sidebarPlaylists.querySelectorAll('.playlist-sidebar-item');
    items.forEach(item => {
      item.addEventListener('click', () => {
        const playlistId = parseInt(item.getAttribute('data-playlist-id'));
        openPlaylistDetail(playlistId);
      });
    });
  } catch (err) {
    console.error(err);
    elements.sidebarPlaylists.innerHTML = `<li style="font-size: 13px; color: #ef4444; padding: 8px;">Error loading playlists.</li>`;
  }
}

// ----------------------------------------------------
// DYNAMIC HOME PAGE SECTIONS (CONTINUE, RECENT, ADDED)
// ----------------------------------------------------
async function loadHomePageSections() {
  await Promise.all([
    loadContinueListeningSection(),
    loadRecentlyPlayedSection(),
    loadRecentlyAddedSection(),
  ]);
}

async function loadContinueListeningSection() {
  const sectionEl = document.getElementById('continue-listening-section');
  const gridEl = document.getElementById('continue-listening-grid');
  if (!sectionEl || !gridEl) return;

  try {
    const response = await fetch('/api/v1/playlists/continue-listening?limit=4');
    if (!response.ok) throw new Error('Failed to fetch continue listening');
    const sessions = await response.json();

    if (sessions.length === 0) {
      sectionEl.style.display = 'none';
      return;
    }

    sectionEl.style.display = 'block';
    let html = '';
    sessions.forEach(s => {
      html += `
        <div class="continue-card" data-playlist-id="${s.playlist_id}">
          <div class="continue-art-wrapper">
            <img class="continue-art-img" src="/api/v1/playlists/${s.playlist_id}/cover" alt="cover">
          </div>
          <div class="continue-info">
            <div class="continue-badge">CONTINUE LISTENING</div>
            <div class="continue-title">${escapeHtml(s.playlist_name)}</div>
            <div class="continue-subtitle">Track ${s.current_song_index + 1} of ${s.song_count} • ${formatDuration(s.current_position)}</div>
          </div>
          <button class="continue-resume-btn" data-resume-id="${s.playlist_id}" title="Resume Playback">
            ${SVG_ICONS.play}
          </button>
        </div>
      `;
    });
    gridEl.innerHTML = html;

    // Wire clicks
    gridEl.querySelectorAll('.continue-card').forEach(card => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('.continue-resume-btn')) return;
        const pid = parseInt(card.getAttribute('data-playlist-id'));
        openPlaylistDetail(pid);
      });
    });

    gridEl.querySelectorAll('.continue-resume-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const pid = parseInt(btn.getAttribute('data-resume-id'));
        resumePlaylist(pid);
      });
    });
  } catch (err) {
    console.error("Failed loading continue listening:", err);
    if (sectionEl) sectionEl.style.display = 'none';
  }
}

async function loadRecentlyPlayedSection() {
  const gridEl = document.getElementById('recently-played-grid');
  if (!gridEl) return;

  try {
    const response = await fetch('/api/v1/playlists?section=recently_played&limit=4');
    if (!response.ok) throw new Error('Failed to fetch recently played');
    const playlists = await response.json();

    if (playlists.length === 0) {
      gridEl.innerHTML = `<div style="color:var(--text-muted); font-size:13px; font-style:italic;">No recently played playlists.</div>`;
      return;
    }

    renderPlaylistGridCards(gridEl, playlists);
  } catch (err) {
    console.error("Failed loading recently played:", err);
  }
}

async function loadRecentlyAddedSection() {
  const gridEl = document.getElementById('recently-added-grid');
  if (!gridEl) return;

  try {
    const response = await fetch('/api/v1/playlists?section=recently_added&limit=6');
    if (!response.ok) throw new Error('Failed to fetch recently added');
    const playlists = await response.json();

    if (playlists.length === 0) {
      gridEl.innerHTML = `<div style="color:var(--text-muted); font-size:13px; font-style:italic;">No saved playlists yet.</div>`;
      return;
    }

    renderPlaylistGridCards(gridEl, playlists);
  } catch (err) {
    console.error("Failed loading recently added:", err);
  }
}

function renderPlaylistGridCards(container, playlists) {
  let html = '';
  playlists.forEach(pl => {
    html += `
      <div class="playlist-card" data-playlist-id="${pl.id}">
        <div class="card-art-container">
          <img class="card-cover-img" src="/api/v1/playlists/${pl.id}/cover" alt="cover">
          <button class="card-play-overlay" data-play-id="${pl.id}" title="Play Playlist">
            ${SVG_ICONS.play}
          </button>
        </div>
        <div class="card-info">
          <h4 class="card-title">${escapeHtml(pl.name)}</h4>
          <p class="card-desc">${pl.songs_count || pl.song_count || 0} songs</p>
        </div>
      </div>
    `;
  });
  container.innerHTML = html;

  container.querySelectorAll('.playlist-card').forEach(card => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('.card-play-overlay')) return;
      const pid = parseInt(card.getAttribute('data-playlist-id'));
      openPlaylistDetail(pid);
    });
  });

  container.querySelectorAll('.card-play-overlay').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const pid = parseInt(btn.getAttribute('data-play-id'));
      playPlaylist(pid, 0);
    });
  });
}

// ----------------------------------------------------
// SPOTIFY-STYLE PLAYLIST DETAILS VIEW
// ----------------------------------------------------
let currentPlaylistData = null;

async function openPlaylistDetail(playlistId) {
  try {
    const response = await fetch(`/api/v1/playlists/${playlistId}`);
    if (!response.ok) throw new Error('Failed to fetch playlist details');
    const pl = await response.json();
    currentPlaylistData = pl;

    // Switch view
    elements.navItems.forEach(n => n.classList.remove('active'));
    elements.views.forEach(v => {
      if (v.id === 'view-playlist-detail') v.classList.add('active');
      else v.classList.remove('active');
    });
    currentState.activeTab = 'view-playlist-detail';

    // Populate Hero Metadata
    const coverImg = document.getElementById('detail-playlist-cover');
    if (coverImg) coverImg.src = `/api/v1/playlists/${pl.id}/cover?t=${Date.now()}`;

    const titleEl = document.getElementById('detail-playlist-title');
    if (titleEl) titleEl.innerText = pl.name;

    const descEl = document.getElementById('detail-playlist-desc');
    if (descEl) descEl.innerText = pl.description || pl.prompt || "Custom playlist";

    const songCountEl = document.getElementById('detail-song-count');
    if (songCountEl) songCountEl.innerText = `${pl.songs_count} songs`;

    const totalDurEl = document.getElementById('detail-total-duration');
    if (totalDurEl) totalDurEl.innerText = formatDuration(pl.total_duration);

    const createdEl = document.getElementById('detail-created-date');
    if (createdEl) {
      const d = new Date(pl.created_at);
      createdEl.innerText = `Created ${d.toLocaleDateString()}`;
    }

    const playCountEl = document.getElementById('detail-play-count');
    if (playCountEl) playCountEl.innerText = `${pl.play_count || 0} plays`;

    // Badges
    const badgeEl = document.getElementById('detail-playlist-badge');
    if (badgeEl) badgeEl.innerText = pl.generated_by || "PLAYLIST";

    const aiBadgeEl = document.getElementById('detail-playlist-ai-badge');
    if (aiBadgeEl) aiBadgeEl.style.display = (pl.generated_by === 'AI') ? 'inline-block' : 'none';

    // AI Meta Card
    const aiBox = document.getElementById('detail-ai-meta-box');
    if (aiBox) {
      if (pl.generated_by === 'AI' || pl.prompt) {
        aiBox.style.display = 'block';
        document.getElementById('ai-meta-prompt').innerText = pl.prompt || 'None';
        document.getElementById('ai-meta-strategy').innerText = pl.strategy || 'hybrid';
        document.getElementById('ai-meta-seed').innerText = pl.seed_song_title || pl.seed_type || 'Automatic';
        document.getElementById('ai-meta-engine').innerText = `${pl.generator_version || 'Verse AI v1.0'} (${pl.llm_model || 'Local MIR'})`;
      } else {
        aiBox.style.display = 'none';
      }
    }

    // Render Song Table
    renderPlaylistDetailTable(pl.songs);

    // Wire actions
    const playAllBtn = document.getElementById('btn-playlist-play-all');
    if (playAllBtn) {
      playAllBtn.onclick = () => playPlaylist(pl.id, 0);
    }

    const shuffleBtn = document.getElementById('btn-playlist-shuffle');
    if (shuffleBtn) {
      shuffleBtn.onclick = () => playPlaylist(pl.id, 0, true);
    }

    const deleteBtn = document.getElementById('btn-playlist-delete');
    if (deleteBtn) {
      deleteBtn.onclick = async () => {
        if (confirm(`Are you sure you want to delete "${pl.name}"?`)) {
          await fetch(`/api/v1/playlists/${pl.id}`, { method: 'DELETE' });
          loadPlaylists();
          loadHomePageSections();
          // Navigate Home
          elements.navHome.click();
        }
      };
    }

    const backBtn = document.getElementById('btn-playlist-back');
    if (backBtn) {
      backBtn.onclick = () => {
        elements.navHome.click();
      };
    }
  } catch (err) {
    console.error("Failed opening playlist detail:", err);
    alert("Could not load playlist details.");
  }
}

function renderPlaylistDetailTable(songs) {
  const bodyEl = document.getElementById('playlist-detail-songs-body');
  if (!bodyEl) return;

  if (!songs || songs.length === 0) {
    bodyEl.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; padding: 24px; color: var(--text-muted);">
          This playlist has no songs.
        </td>
      </tr>
    `;
    return;
  }

  let html = '';
  songs.forEach((s, idx) => {
    const isPlaying = currentState.currentPlayingSong && currentState.currentPlayingSong.id === s.id;
    const isLiked = currentState.likedSongIds.has(s.id);

    html += `
      <tr class="song-table-row ${isPlaying ? 'playing' : ''}" data-song-id="${s.id}" data-idx="${idx}">
        <td class="col-num">${isPlaying ? SVG_ICONS.play : (idx + 1)}</td>
        <td class="col-heart">
          <button class="btn-like-song ${isLiked ? 'liked' : ''}" data-song-id="${s.id}">
            ${isLiked ? SVG_ICONS.heartFilled : SVG_ICONS.heart}
          </button>
        </td>
        <td class="col-title">
          <div class="table-song-title-cell">
            <div class="table-song-art">
              ${s.artwork_available
                ? `<img src="/api/v1/songs/${s.id}/artwork" alt="art">`
                : SVG_ICONS.music}
            </div>
            <div class="table-song-meta">
              <span class="table-song-title-text">${escapeHtml(s.title)}</span>
            </div>
          </div>
        </td>
        <td class="col-artist">${escapeHtml(s.artist)}</td>
        <td class="col-album">${escapeHtml(s.album)}</td>
        <td class="col-duration">${formatDuration(s.duration)}</td>
        <td class="col-options">
          <button class="btn-song-options">${SVG_ICONS.options}</button>
        </td>
      </tr>
    `;
  });
  bodyEl.innerHTML = html;

  bodyEl.querySelectorAll('.song-table-row').forEach(row => {
    row.addEventListener('click', (e) => {
      if (e.target.closest('.btn-like-song') || e.target.closest('.btn-song-options')) return;
      const idx = parseInt(row.getAttribute('data-idx'));
      if (currentPlaylistData && currentPlaylistData.id) {
        playPlaylist(currentPlaylistData.id, idx);
      } else {
        playSong(songs[idx], songs);
      }
    });
  });

  bodyEl.querySelectorAll('.btn-like-song').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const sid = parseInt(btn.getAttribute('data-song-id'));
      toggleLikeSong(sid);
    });
  });
}

// ----------------------------------------------------
// PLAYBACK SESSION ENGINE INTEGRATION
// ----------------------------------------------------
async function playPlaylist(playlistId, startIndex = 0, shuffle = false) {
  try {
    const startResp = await fetch(`/api/v1/playlists/${playlistId}/play`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ song_index: startIndex, position: 0.0 })
    });

    if (!startResp.ok) throw new Error('Failed to start playlist session');
    const sessionData = await startResp.json();
    currentState.activeSessionId = sessionData.session_id;
    currentState.activePlaylistId = playlistId;

    // Fetch song queue
    const songsResp = await fetch(`/api/v1/playlists/${playlistId}/songs`);
    if (!songsResp.ok) throw new Error('Failed to fetch playlist songs');
    let songs = await songsResp.json();

    if (songs.length === 0) {
      alert("This playlist has no songs to play.");
      return;
    }

    if (shuffle) {
      songs = [...songs].sort(() => Math.random() - 0.5);
      startIndex = 0;
    }

    playSong(songs[startIndex], songs);
  } catch (err) {
    console.error("Failed to play playlist:", err);
  }
}

async function resumePlaylist(playlistId) {
  try {
    const resumeResp = await fetch(`/api/v1/playlists/${playlistId}/resume`, {
      method: 'POST'
    });
    if (!resumeResp.ok) throw new Error('Failed to resume playlist');
    const sessionData = await resumeResp.json();

    currentState.activeSessionId = sessionData.session_id;
    currentState.activePlaylistId = playlistId;

    const songsResp = await fetch(`/api/v1/playlists/${playlistId}/songs`);
    if (!songsResp.ok) throw new Error('Failed to fetch playlist songs');
    const songs = await songsResp.json();

    if (songs.length === 0) return;

    let targetIndex = sessionData.current_song_index || 0;
    if (targetIndex >= songs.length) targetIndex = 0;

    await playSong(songs[targetIndex], songs);

    if (elements.audio && sessionData.current_position > 0) {
      elements.audio.currentTime = sessionData.current_position;
    }
  } catch (err) {
    console.error("Failed to resume playlist:", err);
  }
}

function syncSessionProgress(completed = false) {
  if (!currentState.activeSessionId || !currentState.activePlaylistId) return;

  const now = Date.now();
  if (!completed && now - currentState.lastProgressSync < 4000) return; // throttle 4s
  currentState.lastProgressSync = now;

  const position = elements.audio ? elements.audio.currentTime : 0.0;
  const songIndex = currentState.queueIndex >= 0 ? currentState.queueIndex : 0;

  try {
    fetch(`/api/v1/playlists/${currentState.activePlaylistId}/progress?session_id=${currentState.activeSessionId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        song_index: songIndex,
        position: position,
        completed: completed
      })
    });
  } catch (err) {
    console.error("Progress sync failed:", err);
  }
}

function initPlaylistEvents() {
  if (elements.playlistForm) {
    elements.playlistForm.addEventListener('submit', handleGeneratePlaylist);
  }
  if (elements.btnSavePlaylist) {
    elements.btnSavePlaylist.addEventListener('click', handleSavePlaylist);
  }
  if (elements.playlistSeedType) {
    elements.playlistSeedType.addEventListener('change', () => {
      const val = elements.playlistSeedType.value;
      if (['current song', 'current queue', 'favourites'].includes(val)) {
        elements.playlistSeedValue.placeholder = "Optional (resolves from history/favorites)";
        elements.playlistSeedValue.value = "";
      } else {
        elements.playlistSeedValue.placeholder = "e.g. Song Title, sad, studying...";
      }
    });
  }
}

// ==========================================
// 6. PLAYBACK ENGINE & AUDIO CONTROLLER LOGIC
// ==========================================
async function playSong(song, queueContext = null) {
  if (!song) return;

  const audio = elements.audio;
  if (!audio) return;

  currentState.currentPlayingSong = song;
  if (queueContext && Array.isArray(queueContext)) {
    currentState.queue = queueContext;
    currentState.queueIndex = queueContext.findIndex(s => s.id === song.id);
  } else if (!currentState.queue.some(s => s.id === song.id)) {
    currentState.queue.push(song);
    currentState.queueIndex = currentState.queue.length - 1;
  }

  audio.src = `/api/v1/songs/${song.id}/stream`;
  try {
    await audio.play();
    currentState.isPlaying = true;
  } catch (e) {
    console.error("Autoplay prevented or audio load failed:", e);
    currentState.isPlaying = false;
  }

  try {
    fetch('/api/v1/history/play', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ song_id: song.id, duration: song.duration || 0.0 })
    });
  } catch (err) {
    console.error("Failed sending play history:", err);
  }

  updatePlaybackUI();
  updateRightSidebarNowPlaying(song);
  renderQueueList();
  fetchRecommendationsForSong(song.id);
  renderSongsTable();
}

function togglePlayPause() {
  const audio = elements.audio;
  if (!audio || !currentState.currentPlayingSong) return;

  if (audio.paused) {
    audio.play();
    currentState.isPlaying = true;
  } else {
    audio.pause();
    currentState.isPlaying = false;
  }
  updatePlaybackUI();
}

function playNextSong() {
  if (currentState.queue.length === 0) return;

  const currentSong = currentState.currentPlayingSong;
  const audio = elements.audio;

  if (currentSong && audio && audio.duration > 0 && audio.currentTime < audio.duration * 0.8) {
    try {
      fetch('/api/v1/history/skip', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ song_id: currentSong.id })
      });
    } catch (err) {
      console.error("Failed sending skip history:", err);
    }
  }

  const nextIdx = currentState.queueIndex + 1;
  if (nextIdx < currentState.queue.length) {
    playSong(currentState.queue[nextIdx], currentState.queue);
  }
}

function playPrevSong() {
  const audio = elements.audio;
  if (audio && audio.currentTime > 3.0) {
    audio.currentTime = 0;
    return;
  }

  const prevIdx = currentState.queueIndex - 1;
  if (prevIdx >= 0 && prevIdx < currentState.queue.length) {
    playSong(currentState.queue[prevIdx], currentState.queue);
  }
}

async function toggleLikeSong(songId) {
  const isLiked = currentState.likedSongIds.has(songId);
  const newLikedState = !isLiked;

  if (newLikedState) {
    currentState.likedSongIds.add(songId);
  } else {
    currentState.likedSongIds.delete(songId);
  }

  try {
    await fetch('/api/v1/history/like', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ song_id: songId, liked: newLikedState })
    });
  } catch (err) {
    console.error("Failed sending like history:", err);
  }

  updatePlaybackUI();
  renderSongsTable();
}

function updatePlaybackUI() {
  const song = currentState.currentPlayingSong;
  if (!song) return;

  if (elements.barTitle) elements.barTitle.innerText = song.title;
  if (elements.barArtist) elements.barArtist.innerText = song.artist;

  if (elements.barMiniArt) {
    elements.barMiniArt.innerHTML = song.artwork_available
      ? `<img src="/api/v1/songs/${song.id}/artwork" alt="art" onerror="this.style.display='none';">`
      : SVG_ICONS.music;
  }

  if (elements.barBtnPlay) {
    elements.barBtnPlay.disabled = false;
    elements.barBtnPlay.innerHTML = currentState.isPlaying ? SVG_ICONS.pause : SVG_ICONS.play;
  }

  if (elements.barBtnPrev) elements.barBtnPrev.disabled = currentState.queueIndex <= 0;
  if (elements.barBtnNext) elements.barBtnNext.disabled = currentState.queueIndex >= currentState.queue.length - 1;
  if (elements.barProgressSlider) elements.barProgressSlider.disabled = false;
  if (elements.barLikeBtn) {
    elements.barLikeBtn.disabled = false;
    const isLiked = currentState.likedSongIds.has(song.id);
    elements.barLikeBtn.innerHTML = isLiked ? SVG_ICONS.heartFilled : SVG_ICONS.heart;
  }
}

function updateRightSidebarNowPlaying(song) {
  const npCoverArt = document.getElementById('np-cover-art');
  const npTitle = document.getElementById('np-title');
  const npArtist = document.getElementById('np-artist');
  const npAlbum = document.getElementById('np-album');
  const npGenre = document.getElementById('np-genre');

  if (npTitle) npTitle.innerText = song.title;
  if (npArtist) npArtist.innerText = song.artist;
  if (npAlbum) npAlbum.innerText = song.album || "Unknown Album";
  if (npGenre) npGenre.innerText = song.genre || "Music";

  if (npCoverArt) {
    npCoverArt.innerHTML = song.artwork_available
      ? `<img src="/api/v1/songs/${song.id}/artwork" alt="art" onerror="this.style.display='none';">`
      : SVG_ICONS.music;
  }
}

async function fetchRecommendationsForSong(songId) {
  const recList = document.getElementById('np-recommendation-list');
  if (!recList) return;

  try {
    const response = await fetch(`/api/v1/recommend?song_id=${songId}&limit=5`);
    if (!response.ok) throw new Error('Failed to fetch recommendations');
    const songs = await response.json();

    if (songs.length === 0) {
      recList.innerHTML = `<li class="recommendation-empty-item">No recommendations found</li>`;
      return;
    }

    let html = '';
    songs.forEach(s => {
      html += `
        <li class="sidebar-track-item" data-song-id="${s.id}">
          <div class="table-song-art" style="width:36px; height:36px;">
            ${s.artwork_available
              ? `<img src="/api/v1/songs/${s.id}/artwork" alt="art">`
              : SVG_ICONS.music}
          </div>
          <div class="sidebar-track-meta">
            <div class="sidebar-track-title">${escapeHtml(s.title)}</div>
            <div class="sidebar-track-artist">${escapeHtml(s.artist)}</div>
          </div>
        </li>
      `;
    });
    recList.innerHTML = html;

    const items = recList.querySelectorAll('.sidebar-track-item');
    items.forEach(item => {
      item.addEventListener('click', () => {
        const id = parseInt(item.getAttribute('data-song-id'));
        const targetSong = songs.find(s => s.id === id);
        if (targetSong) {
          playSong(targetSong);
        }
      });
    });
  } catch (err) {
    console.error(err);
    recList.innerHTML = `<li class="recommendation-empty-item">Could not load recommendations</li>`;
  }
}

function renderQueueList() {
  const queueList = document.getElementById('np-queue-list');
  if (!queueList) return;

  const remainingQueue = currentState.queue.slice(currentState.queueIndex + 1);
  if (remainingQueue.length === 0) {
    queueList.innerHTML = `<li class="queue-empty-item">Queue is empty</li>`;
    return;
  }

  let html = '';
  remainingQueue.forEach((s, i) => {
    html += `
      <li class="sidebar-track-item" data-queue-idx="${currentState.queueIndex + 1 + i}">
        <div class="table-song-art" style="width:36px; height:36px;">
          ${s.artwork_available
            ? `<img src="/api/v1/songs/${s.id}/artwork" alt="art">`
            : SVG_ICONS.music}
        </div>
        <div class="sidebar-track-meta">
          <div class="sidebar-track-title">${escapeHtml(s.title)}</div>
          <div class="sidebar-track-artist">${escapeHtml(s.artist)}</div>
        </div>
      </li>
    `;
  });
  queueList.innerHTML = html;

  const items = queueList.querySelectorAll('.sidebar-track-item');
  items.forEach(item => {
    item.addEventListener('click', () => {
      const idx = parseInt(item.getAttribute('data-queue-idx'));
      if (currentState.queue[idx]) {
        playSong(currentState.queue[idx], currentState.queue);
      }
    });
  });
}

function initAudioPlayerEvents() {
  const audio = elements.audio;
  if (!audio) return;

  if (elements.barBtnPlay) {
    elements.barBtnPlay.addEventListener('click', togglePlayPause);
  }
  if (elements.barBtnNext) {
    elements.barBtnNext.addEventListener('click', playNextSong);
  }
  if (elements.barBtnPrev) {
    elements.barBtnPrev.addEventListener('click', playPrevSong);
  }
  if (elements.barLikeBtn) {
    elements.barLikeBtn.addEventListener('click', () => {
      if (currentState.currentPlayingSong) {
        toggleLikeSong(currentState.currentPlayingSong.id);
      }
    });
  }

  if (elements.barBtnShuffle) {
    elements.barBtnShuffle.addEventListener('click', () => {
      currentState.isShuffle = !currentState.isShuffle;
      elements.barBtnShuffle.classList.toggle('active', currentState.isShuffle);
    });
  }
  if (elements.barBtnRepeat) {
    elements.barBtnRepeat.addEventListener('click', () => {
      currentState.isRepeat = !currentState.isRepeat;
      elements.barBtnRepeat.classList.toggle('active', currentState.isRepeat);
    });
  }
  if (elements.barBtnVolume) {
    elements.barBtnVolume.addEventListener('click', () => {
      if (audio.volume > 0) {
        audio.dataset.prevVolume = audio.volume;
        audio.volume = 0;
        if (elements.barVolumeSlider) elements.barVolumeSlider.value = 0;
      } else {
        const prev = parseFloat(audio.dataset.prevVolume || '0.7');
        audio.volume = prev;
        if (elements.barVolumeSlider) elements.barVolumeSlider.value = prev * 100;
      }
    });
  }

  if (elements.barProgressSlider) {
    elements.barProgressSlider.addEventListener('input', (e) => {
      if (audio.duration) {
        const targetTime = (parseFloat(e.target.value) / 100) * audio.duration;
        audio.currentTime = targetTime;
      }
    });
  }

  if (elements.barVolumeSlider) {
    elements.barVolumeSlider.addEventListener('input', (e) => {
      audio.volume = parseFloat(e.target.value) / 100;
    });
  }

  audio.addEventListener('timeupdate', () => {
    if (!audio.duration) return;
    const pct = (audio.currentTime / audio.duration) * 100;
    if (elements.barProgressSlider) elements.barProgressSlider.value = pct;
    if (elements.barTimeCurrent) elements.barTimeCurrent.innerText = formatDuration(audio.currentTime);
    syncSessionProgress(false);
  });

  audio.addEventListener('loadedmetadata', () => {
    if (elements.barTimeTotal) elements.barTimeTotal.innerText = formatDuration(audio.duration);
  });

  audio.addEventListener('ended', () => {
    syncSessionProgress(true);
    playNextSong();
  });
}

// ==========================================
// 6.5 PANEL RESIZING LOGIC
// ==========================================
function initResizers() {
  const leftSidebar = document.querySelector('.sidebar-left');
  const rightSidebar = document.querySelector('.sidebar-right');
  const resizerLeft = document.getElementById('resizer-left');
  const resizerRight = document.getElementById('resizer-right');

  if (resizerLeft && leftSidebar) {
    resizerLeft.addEventListener('mousedown', (e) => {
      e.preventDefault();
      resizerLeft.classList.add('resizing');
      document.addEventListener('mousemove', resizeLeft);
      document.addEventListener('mouseup', stopResizeLeft);
    });

    function resizeLeft(e) {
      const width = Math.min(Math.max(e.clientX, 180), 450);
      leftSidebar.style.width = `${width}px`;
    }

    function stopResizeLeft() {
      resizerLeft.classList.remove('resizing');
      document.removeEventListener('mousemove', resizeLeft);
      document.removeEventListener('mouseup', stopResizeLeft);
    }
  }

  if (resizerRight && rightSidebar) {
    resizerRight.addEventListener('mousedown', (e) => {
      e.preventDefault();
      resizerRight.classList.add('resizing');
      document.addEventListener('mousemove', resizeRight);
      document.addEventListener('mouseup', stopResizeRight);
    });

    function resizeRight(e) {
      const width = Math.min(Math.max(window.innerWidth - e.clientX, 240), 500);
      rightSidebar.style.width = `${width}px`;
    }

    function stopResizeRight() {
      resizerRight.classList.remove('resizing');
      document.removeEventListener('mousemove', resizeRight);
      document.removeEventListener('mouseup', stopResizeRight);
    }
  }
}

// ==========================================
// 7. SECURITY ESCAPING HELPER
// ==========================================
function escapeHtml(str) {
  if (!str) return '';
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ==========================================
// 7.5 AI ASSISTANT CHAT LOGIC
// ==========================================
let chatSessionHistory = [];
let currentAssistantPlaylist = null;

function initAssistantEvents() {
  const chatForm = document.getElementById('chat-prompt-form');
  const chatInput = document.getElementById('chat-prompt-input');
  const btnClearChat = document.getElementById('btn-clear-chat');
  const chipBtns = document.querySelectorAll('.suggestion-chip');

  if (chatForm) {
    chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = chatInput.value.trim();
      if (!text) return;
      chatInput.value = '';
      sendAssistantPrompt(text);
    });
  }

  if (btnClearChat) {
    btnClearChat.addEventListener('click', () => {
      chatSessionHistory = [];
      currentAssistantPlaylist = null;
      const defaultSidebar = document.getElementById('sidebar-default-view');
      const assistantSidebar = document.getElementById('assistant-created-playlist-view');
      if (defaultSidebar) defaultSidebar.style.display = 'block';
      if (assistantSidebar) assistantSidebar.style.display = 'none';
      renderChatMessages();
    });
  }

  chipBtns.forEach(chip => {
    chip.addEventListener('click', () => {
      const promptText = chip.getAttribute('data-prompt');
      if (promptText) {
        if (chatInput) chatInput.value = promptText;
        sendAssistantPrompt(promptText);
      }
    });
  });

  renderChatMessages();
}

async function sendAssistantPrompt(promptText) {
  const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  chatSessionHistory.push({
    sender: 'user',
    text: promptText,
    timestamp: timeStr
  });
  renderChatMessages();

  const loadingId = 'loading-' + Date.now();
  chatSessionHistory.push({
    id: loadingId,
    sender: 'assistant',
    isLoading: true,
    text: 'Thinking...',
    timestamp: timeStr
  });
  renderChatMessages();

  try {
    const response = await fetch('/api/v1/assistant/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: promptText })
    });

    chatSessionHistory = chatSessionHistory.filter(item => item.id !== loadingId);

    if (!response.ok) {
      throw new Error(`Assistant failed: ${response.statusText}`);
    }

    const data = await response.json();
    const respTimeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    chatSessionHistory.push({
      sender: 'assistant',
      text: data.message || "Here are your results:",
      playlist: data.playlist,
      steps: data.steps,
      originalPrompt: promptText,
      timestamp: respTimeStr
    });

    if (data.playlist) {
      renderAssistantSidebarPlaylist(data.playlist);
    }

    renderChatMessages();
  } catch (err) {
    console.error(err);
    chatSessionHistory = chatSessionHistory.filter(item => item.id !== loadingId);
    chatSessionHistory.push({
      sender: 'assistant',
      text: "Failed to connect to AI Assistant. Please verify backend and Ollama status.",
      error: true,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    });
    renderChatMessages();
  }
}

async function savePlaylistPreview(playlist, button) {
  const songIds = (playlist.songs || []).map(song => song.id).filter(Boolean);
  if (songIds.length === 0) {
    alert('This playlist has no songs to save.');
    return;
  }

  const playlistName = window.prompt('Save playlist as:', playlist.name);
  if (!playlistName || !playlistName.trim()) return;

  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = 'Saving...';
  try {
    const response = await fetch('/api/v1/playlists', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: playlistName.trim(), song_ids: songIds })
    });
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      throw new Error(errorBody.detail || `Save failed (${response.status})`);
    }

    button.textContent = 'Saved';
    loadPlaylists();
    loadRecentlyAddedSection();
  } catch (err) {
    console.error('Failed to save playlist preview:', err);
    alert(`Failed to save playlist: ${err.message}`);
    button.disabled = false;
    button.textContent = originalText;
  }
}

function renderAssistantSidebarPlaylist(playlist) {
  if (!playlist) return;
  currentAssistantPlaylist = playlist;

  const defaultSidebar = document.getElementById('sidebar-default-view');
  const assistantSidebar = document.getElementById('assistant-created-playlist-view');

  if (currentState.activeTab === 'view-assistant') {
    if (defaultSidebar) defaultSidebar.style.display = 'none';
    if (assistantSidebar) assistantSidebar.style.display = 'flex';
  }

  const titleEl = document.getElementById('assistant-sidebar-title');
  const countEl = document.getElementById('assistant-sidebar-count');
  const descEl = document.getElementById('assistant-sidebar-desc');
  const artEl = document.getElementById('assistant-sidebar-art');
  const bodyEl = document.getElementById('assistant-sidebar-songs-body');

  if (titleEl) titleEl.innerText = playlist.name;
  if (countEl) countEl.innerText = `${playlist.songs_count} songs • ${formatDuration(playlist.total_duration)}`;
  if (descEl) descEl.innerText = "Calm, nostalgic and perfect for a rainy evening.";

  if (artEl && playlist.songs && playlist.songs.length > 0) {
    artEl.innerHTML = playlist.songs[0].artwork_available
      ? `<img src="/api/v1/songs/${playlist.songs[0].id}/artwork" alt="art">`
      : SVG_ICONS.music;
  }

  if (bodyEl && playlist.songs) {
    let html = '';
    playlist.songs.forEach((s, idx) => {
      html += `
        <tr data-song-id="${s.id}">
          <td style="color:var(--text-muted);">${idx + 1}</td>
          <td style="font-weight:600;">${escapeHtml(s.title)}</td>
          <td style="color:var(--text-muted);">${escapeHtml(s.artist)}</td>
          <td style="text-align:right; color:var(--text-muted);">${formatDuration(s.duration)}</td>
        </tr>
      `;
    });
    bodyEl.innerHTML = html;

    const rows = bodyEl.querySelectorAll('tr[data-song-id]');
    rows.forEach(r => {
      r.addEventListener('click', () => {
        const id = parseInt(r.getAttribute('data-song-id'));
        const song = playlist.songs.find(s => s.id === id);
        if (song) playSong(song, playlist.songs);
      });
    });
  }

  const btnPlayAll = document.getElementById('btn-assistant-play-all');
  if (btnPlayAll) {
    btnPlayAll.onclick = () => {
      if (playlist.songs && playlist.songs.length > 0) {
        playSong(playlist.songs[0], playlist.songs);
      }
    };
  }

  const btnSave = document.getElementById('btn-save-assistant-playlist');
  if (btnSave) {
    btnSave.onclick = () => savePlaylistPreview(playlist, btnSave);
  }

  const btnClose = document.getElementById('btn-close-assistant-sidebar');
  if (btnClose) {
    btnClose.onclick = () => {
      if (defaultSidebar) defaultSidebar.style.display = 'block';
      if (assistantSidebar) assistantSidebar.style.display = 'none';
    };
  }

  const btnRegenSidebar = document.getElementById('btn-sidebar-regen');
  if (btnRegenSidebar) {
    btnRegenSidebar.onclick = () => {
      sendAssistantPrompt("Regenerate playlist preview");
    };
  }
}

function renderChatMessages() {
  const container = document.getElementById('chat-messages-container');
  if (!container) return;

  if (chatSessionHistory.length === 0) {
    container.innerHTML = `
      <div class="chat-message assistant">
        <div class="assistant-bot-icon" style="width:36px; height:36px; border-radius:10px; flex-shrink:0;">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:18px; height:18px;"><path d="M12 2a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2 2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M4 11a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7z"/><line x1="9" y1="14" x2="9" y2="14.01"/><line x1="15" y1="14" x2="15" y2="14.01"/></svg>
        </div>
        <div class="chat-bubble">
          👋 Hi! I'm your MuseAI Music Assistant. Tell me what mood, genre, or vibe you're looking for, or try one of the suggestions above!
        </div>
      </div>
    `;
    return;
  }

  let html = '';
  chatSessionHistory.forEach((msg, idx) => {
    if (msg.isLoading) {
      html += `
        <div class="chat-message assistant">
          <div class="assistant-bot-icon" style="width:36px; height:36px; border-radius:10px; flex-shrink:0;">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:18px; height:18px;"><path d="M12 2a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2 2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M4 11a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7z"/><line x1="9" y1="14" x2="9" y2="14.01"/><line x1="15" y1="14" x2="15" y2="14.01"/></svg>
          </div>
          <div class="chat-bubble" style="display:flex; align-items:center; gap:8px;">
            <div class="loader-spinner" style="width: 14px; height: 14px; border: 2px solid rgba(124,58,237,0.2); border-top-color: var(--accent-color); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
            <span>Thinking & generating playlist recommendations...</span>
          </div>
        </div>
      `;
      return;
    }

    if (msg.sender === 'user') {
      html += `
        <div class="chat-message user">
          <div class="chat-bubble">
            <div>${escapeHtml(msg.text)}</div>
            <div class="chat-meta">
              <span>${msg.timestamp || '10:42 PM'}</span>
              <span>✓✓</span>
            </div>
          </div>
        </div>
      `;
    } else {
      let playlistCardHtml = '';
      if (msg.playlist && msg.playlist.songs && msg.playlist.songs.length > 0) {
        const p = msg.playlist;
        playlistCardHtml = `
          <div class="chat-playlist-card">
            <div class="chat-playlist-art">
              ${p.songs[0].artwork_available
                ? `<img src="/api/v1/songs/${p.songs[0].id}/artwork" alt="art">`
                : SVG_ICONS.music}
            </div>
            <div class="chat-playlist-meta">
              <div class="chat-playlist-title">${escapeHtml(p.name)}</div>
              <div class="chat-playlist-sub">Calm, nostalgic and perfect for a rainy evening.</div>
              <div style="font-size:11px; color:var(--text-muted); margin-bottom:10px;">${p.songs_count} songs • ${formatDuration(p.total_duration)}</div>
              <button class="chat-playlist-btn" data-chat-idx="${idx}">
                <svg viewBox="0 0 24 24" fill="currentColor" style="width:12px; height:12px;"><path d="M8 5v14l11-7z"/></svg>
                Play Playlist
              </button>
              <button class="chat-playlist-btn chat-save-playlist-btn" data-chat-save-idx="${idx}">
                Save Playlist
              </button>
            </div>
          </div>
        `;
      }

      html += `
        <div class="chat-message assistant">
          <div class="assistant-bot-icon" style="width:36px; height:36px; border-radius:10px; flex-shrink:0;">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:18px; height:18px;"><path d="M12 2a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2 2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M4 11a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7z"/><line x1="9" y1="14" x2="9" y2="14.01"/><line x1="15" y1="14" x2="15" y2="14.01"/></svg>
          </div>
          <div class="chat-bubble">
            <div>${escapeHtml(msg.text)}</div>
            ${playlistCardHtml}
            <div class="chat-meta">${msg.timestamp || '10:43 PM'}</div>
            <div class="chat-action-bar">
              <button class="chat-action-btn" style="width:32px; height:32px; border-radius:8px; padding:0; justify-content:center;">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px; height:14px;"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
              </button>
              <button class="chat-action-btn" style="width:32px; height:32px; border-radius:8px; padding:0; justify-content:center;">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px; height:14px;"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/></svg>
              </button>
              <button class="chat-action-btn btn-regenerate-chat" data-chat-idx="${idx}" style="border-radius:20px; padding:6px 14px;">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:12px; height:12px;"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                Regenerate Answer
              </button>
            </div>
          </div>
        </div>
      `;
    }
  });

  container.innerHTML = html;
  container.scrollTop = container.scrollHeight;

  const playBtns = container.querySelectorAll('.chat-playlist-btn');
  playBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.getAttribute('data-chat-idx'));
      const item = chatSessionHistory[idx];
      if (item && item.playlist && item.playlist.songs) {
        playSong(item.playlist.songs[0], item.playlist.songs);
      }
    });
  });

  const saveBtns = container.querySelectorAll('.chat-save-playlist-btn');
  saveBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.getAttribute('data-chat-save-idx'));
      const item = chatSessionHistory[idx];
      if (item?.playlist) savePlaylistPreview(item.playlist, btn);
    });
  });

  const regenBtns = container.querySelectorAll('.btn-regenerate-chat');
  regenBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.getAttribute('data-chat-idx'));
      const item = chatSessionHistory[idx];
      const promptToRegen = item.originalPrompt || "Create a fresh music playlist";
      sendAssistantPrompt(promptToRegen);
    });
  });
}

// ==========================================
// 8. BOOTSTRAP INITIALIZATION
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
  console.log("MuseAI Web interface initialized.");
  initNavigation();
  initPagination();
  initSearchEvents();
  initPlaylistEvents();
  initAssistantEvents();
  initAudioPlayerEvents();
  initResizers();
  
  // Load primary data
  fetchSongs(1);
  loadPlaylists();
  loadHomePageSections();
});

// Dynamic Loader Spin Animation Styles
const styleSheet = document.createElement("style");
styleSheet.innerText = `
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
`;
document.head.appendChild(styleSheet);
