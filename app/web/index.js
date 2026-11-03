// Verse Single Page Application Logic

// Application State
let currentState = {
  auth: {
    currentUser: null,
    authenticated: false,
    loading: true,
    firstRun: false
  },
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
  lastProgressSync: 0,
  isRepeat: false
};

Object.defineProperty(currentState, 'isLooping', {
  get() { return this.isRepeat; },
  set(val) { this.isRepeat = Boolean(val); },
  configurable: true,
  enumerable: true
});

const nativeFetch = window.fetch.bind(window);

const resources = new Map();
const renderedResources = new Map();
let navigationGeneration = 0;
let requestEpoch = 0;
let requestOwner = null;
function cancelResource(key) {
  resources.get(key)?.controller.abort();
  resources.delete(key);
}
function resetRequests() {
  requestEpoch++;
  resources.forEach(entry => entry.controller.abort());
  resources.clear(); renderedResources.clear();
}
function isSongList(data) {
  return Array.isArray(data) && data.every(s => s && Number.isInteger(s.id) &&
    (s.title == null || typeof s.title === 'string') && (s.artist == null || typeof s.artist === 'string'));
}
function isPlaylistList(data) {
  return Array.isArray(data) && data.every(p => p && Number.isInteger(p.id) &&
    typeof p.name === 'string' && Number.isInteger(p.songs_count));
}
async function requestJSON(key, url, validate, { force = false } = {}) {
  const owner = currentState.auth.currentUser?.id;
  if (owner !== requestOwner) { resetRequests(); requestOwner = owner; }
  const old = resources.get(key);
  if (old?.url === url && old.pending) return old.promise;
  if (old?.url === url && !force && old.data !== undefined && Date.now() - old.time < 30000) return old.data;
  old?.controller.abort();
  const entry = {url, controller: new AbortController(), pending: true};
  const epoch = requestEpoch;
  resources.set(key, entry);
  const current = () => resources.get(key) === entry && requestEpoch === epoch;
  entry.promise = (async () => {
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; entry.controller.abort(); }, 15000);
    try {
      const response = await fetch(url, {signal: entry.controller.signal});
      if (!response.ok) {
        const errorBody = typeof response.json === 'function' ? await response.json().catch(() => null) : null;
        throw new Error(getApiErrorMessage(errorBody, `Request failed (HTTP ${response.status}).`));
      }
      const data = await response.json();
      if (!validate(data)) throw new Error('The server returned an unexpected response.');
      if (!current()) return null;
      Object.assign(entry, {data, time: Date.now(), failed: false});
      return data;
    } catch (error) {
      if (!current() || (error.name === 'AbortError' && !timedOut)) return null;
      entry.failed = true;
      throw new Error(timedOut ? 'The request timed out.' : error.message);
    } finally { clearTimeout(timer); entry.pending = false; }
  })();
  return entry.promise;
}
function clearResourceError(key) { document.getElementById('load-error-' + key)?.remove(); }
function changedResource(key, data) {
  clearResourceError(key);
  // A successful background refresh with identical data must not replace DOM.
  const signature = JSON.stringify(data);
  if (renderedResources.get(key) === signature) return false;
  renderedResources.set(key, signature); return true;
}
function showResourceError(key, target, retry, error) {
  if (!target) return;
  clearResourceError(key);
  const notice = document.createElement('div');
  notice.id = 'load-error-' + key; notice.className = 'resource-error';
  notice.setAttribute('role', 'status');
  const message = document.createElement('span');
  message.textContent = error.message || 'Unable to load this section.';
  const button = document.createElement('button');
  button.type = 'button'; button.textContent = 'Retry'; button.onclick = retry;
  notice.append(message, button); target.before(notice);
}
function refreshPlaylistData(playlistId = null) {
  for (const key of [...resources.keys()]) {
    if (['playlists', 'continue', 'recent', 'added', 'detail', 'play-queue'].some(prefix => key.startsWith(prefix))) {
      cancelResource(key); renderedResources.delete(key);
    }
  }
  loadPlaylists({force: true}); loadHomePageSections({force: true});
  if (playlistId && currentState.activeTab === 'view-playlist-detail' && currentPlaylistData?.id === playlistId) {
    openPlaylistDetail(playlistId, {force: true, preserveControls: true});
  }
}
function setText(element, value) {
  if (element && element.textContent !== String(value ?? '')) element.textContent = value ?? '';
}
function setIcon(element, key, html) {
  if (element && element._verseIcon !== key) { element.innerHTML = html; element._verseIcon = key; }
}
function updateSongArtwork(element, song) {
  if (!element) return;
  const key = song.id + ':' + Boolean(song.artwork_available);
  if (element._verseArtwork === key) return;
  element._verseArtwork = key;
  element.innerHTML = song.artwork_available
    ? `<img src="/api/v1/songs/${song.id}/artwork" decoding="async" alt="art" onerror="this.style.display='none';">` : SVG_ICONS.music;
}
let lastPlayingRowId = null;
function updatePlayingRows() {
  const next = currentState.currentPlayingSong?.id ?? null;
  new Set([lastPlayingRowId, next]).forEach(id => {
    if (id == null) return;
    document.querySelectorAll(`tr[data-song-id="${id}"]`).forEach(row => {
      const active = id === next;
      row.classList.toggle('active-row', active);
      if (row.classList.contains('song-table-row')) {
        setIcon(row.querySelector('.col-num'), active ? currentState.isPlaying : 'number',
          active ? (currentState.isPlaying ? '<div class="playing-eq-bar"><span></span><span></span><span></span></div>' : SVG_ICONS.play) : row.dataset.trackNumber);
      }
    });
  });
  lastPlayingRowId = next;
}
function updateLikeButtons(songId) {
  const liked = currentState.likedSongIds.has(songId);
  document.querySelectorAll(`button[data-song-id="${songId}"]`).forEach(button => {
    button.classList.toggle('liked', liked);
    setIcon(button, liked, liked ? SVG_ICONS.heartFilled : SVG_ICONS.heart);
  });
  if (currentState.currentPlayingSong?.id === songId) {
    [elements.barLikeBtn, document.getElementById('mobile-full-like-btn')].forEach(button =>
      setIcon(button, liked, liked ? SVG_ICONS.heartFilled : SVG_ICONS.heart));
  }
}


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

const authElements = {
  shell: document.getElementById('auth-shell'),
  app: document.getElementById('app-container'),
  loading: document.getElementById('auth-loading'),
  loginForm: document.getElementById('login-form'),
  registerForm: document.getElementById('register-form'),
  loginMessage: document.getElementById('login-message'),
  registerMessage: document.getElementById('register-message'),
  loginUsername: document.getElementById('login-username'),
  loginPassword: document.getElementById('login-password'),
  registerDisplayName: document.getElementById('register-display-name'),
  registerUsername: document.getElementById('register-username'),
  registerPassword: document.getElementById('register-password'),
  registerConfirmPassword: document.getElementById('register-confirm-password'),
  registerTitle: document.getElementById('register-title'),
  registerSubtitle: document.getElementById('register-subtitle'),
  btnShowRegister: document.getElementById('btn-show-register'),
  btnShowLogin: document.getElementById('btn-show-login'),
  accountTrigger: document.getElementById('account-trigger'),
  accountMenu: document.getElementById('account-menu'),
  accountAvatar: document.getElementById('account-avatar'),
  accountDisplayName: document.getElementById('account-display-name'),
  accountUsername: document.getElementById('account-username'),
  btnLogout: document.getElementById('btn-logout'),
  greeting: document.querySelector('.greeting')
};

// 0. AUTHENTICATION STATE AND FLOW
function setAuthMessage(element, message = '', type = 'error') {
  if (!element) return;
  element.textContent = message;
  element.classList.remove('error', 'success');
  if (message) {
    element.classList.add(type);
  }
}

function getApiErrorMessage(errorBody, fallback) {
  if (!errorBody) return fallback;
  if (typeof errorBody.detail === 'string') return errorBody.detail;
  if (Array.isArray(errorBody.detail) && errorBody.detail.length > 0) {
    return 'Please check the form fields and try again.';
  }
  return fallback;
}

function showAuthScreen(mode) {
  if (document.body) {
    document.body.classList.remove('authenticated');
    document.body.classList.add('auth-locked');
  }
  if (authElements.shell) authElements.shell.style.display = 'flex';
  if (authElements.app) authElements.app.style.display = 'none';
  if (authElements.loading) authElements.loading.style.display = 'none';
  if (authElements.loginForm) authElements.loginForm.style.display = mode === 'login' ? 'flex' : 'none';
  if (authElements.registerForm) authElements.registerForm.style.display = mode === 'register' ? 'flex' : 'none';
  setAuthMessage(authElements.loginMessage);
  setAuthMessage(authElements.registerMessage);

  const isFirstRun = currentState.auth.firstRun;
  if (authElements.registerTitle) {
    authElements.registerTitle.textContent = isFirstRun ? 'Create First User' : 'Create Account';
  }
  if (authElements.registerSubtitle) {
    authElements.registerSubtitle.textContent = isFirstRun
      ? 'Create the first Verse user account.'
      : 'Create a user account to start using Verse.';
  }
  if (authElements.btnShowLogin) {
    authElements.btnShowLogin.style.display = isFirstRun ? 'none' : 'block';
  }
}

function showAuthenticatedApp() {
  if (document.body) {
    document.body.classList.remove('auth-locked');
    document.body.classList.add('authenticated');
  }
  if (authElements.shell) authElements.shell.style.display = 'none';
  if (authElements.app) authElements.app.style.display = 'flex';
  renderAuthenticatedUser();
  loadAuthenticatedAppData();
}

function renderAuthenticatedUser() {
  const user = currentState.auth.currentUser;
  if (!user) return;

  const displayName = user.display_name || user.username;
  const initial = (displayName || user.username || 'U').trim().charAt(0).toUpperCase();

  if (authElements.accountAvatar) authElements.accountAvatar.textContent = initial;
  if (authElements.accountDisplayName) authElements.accountDisplayName.textContent = displayName;
  if (authElements.accountUsername) authElements.accountUsername.textContent = `@${user.username}`;
  if (authElements.greeting) authElements.greeting.textContent = `Good Evening, ${displayName}`;

  // Mobile User Elements
  const mobileAvatar = document.getElementById('mobile-user-avatar');
  const mobileAccAvatar = document.getElementById('mobile-account-avatar');
  const mobileAccName = document.getElementById('mobile-account-name');
  const mobileAccUsername = document.getElementById('mobile-account-username');

  if (mobileAvatar) mobileAvatar.textContent = initial;
  if (mobileAccAvatar) mobileAccAvatar.textContent = initial;
  if (mobileAccName) mobileAccName.textContent = displayName;
  if (mobileAccUsername) mobileAccUsername.textContent = `@${user.username}`;
}

async function bootstrapAuthentication() {
  currentState.auth.loading = true;
  if (document.body) {
    document.body.classList.remove('authenticated');
    document.body.classList.add('auth-locked');
  }
  if (authElements.loading) authElements.loading.style.display = 'block';
  if (authElements.loginForm) authElements.loginForm.style.display = 'none';
  if (authElements.registerForm) authElements.registerForm.style.display = 'none';
  if (authElements.app) authElements.app.style.display = 'none';
  currentState.auth.currentUser = null;
  currentState.auth.authenticated = false;

  try {
    const meResponse = await nativeFetch('/api/v1/auth/me', {
      credentials: 'same-origin',
      cache: 'no-store'
    });
    if (meResponse.ok) {
      currentState.auth.currentUser = await meResponse.json();
      currentState.auth.authenticated = true;
      currentState.auth.loading = false;
      showAuthenticatedApp();
      return;
    }
    if (meResponse.status !== 401 && meResponse.status !== 404) {
      throw new Error('session check failed');
    }
    const response = await nativeFetch('/api/v1/auth/first-run');
    if (!response.ok) throw new Error('first-run check failed');
    const data = await response.json();
    currentState.auth.firstRun = Boolean(data.first_run);
    currentState.auth.loading = false;
    showAuthScreen('login');
  } catch (err) {
    console.error('Authentication bootstrap failed:', err);
    currentState.auth.loading = false;
    showAuthScreen('login');
    setAuthMessage(authElements.loginMessage, 'Unable to reach server.');
  }
}

async function authenticateUser(username, password) {
  const loginResponse = await nativeFetch('/api/v1/auth/login', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });

  if (!loginResponse.ok) {
    const errorBody = await loginResponse.json().catch(() => null);
    throw new Error(getApiErrorMessage(errorBody, 'Invalid username or password.'));
  }

  const loginData = await loginResponse.json();
  currentState.auth.currentUser = loginData.user;
  currentState.auth.authenticated = true;

  const meResponse = await fetch('/api/v1/auth/me');
  if (!meResponse.ok) {
    throw new Error('Unable to load authenticated user.');
  }

  currentState.auth.currentUser = await meResponse.json();
  currentState.auth.authenticated = true;
}

async function handleLoginSubmit(e) {
  e.preventDefault();
  const username = authElements.loginUsername.value.trim();
  const password = authElements.loginPassword.value;
  const submitBtn = document.getElementById('btn-login');

  setAuthMessage(authElements.loginMessage);
  submitBtn.disabled = true;

  try {
    await authenticateUser(username, password);
    authElements.loginPassword.value = '';
    showAuthenticatedApp();
  } catch (err) {
    currentState.auth.currentUser = null;
    currentState.auth.authenticated = false;
    setAuthMessage(authElements.loginMessage, err.message || 'Invalid username or password.');
  } finally {
    submitBtn.disabled = false;
  }
}

async function handleRegisterSubmit(e) {
  e.preventDefault();
  const displayName = authElements.registerDisplayName.value.trim();
  const username = authElements.registerUsername.value.trim();
  const password = authElements.registerPassword.value;
  const confirmPassword = authElements.registerConfirmPassword.value;
  const submitBtn = document.getElementById('btn-register');

  setAuthMessage(authElements.registerMessage);

  if (password !== confirmPassword) {
    setAuthMessage(authElements.registerMessage, 'Passwords do not match.');
    return;
  }

  submitBtn.disabled = true;
  try {
    const response = await nativeFetch('/api/v1/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        display_name: displayName,
        username,
        password
      })
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      throw new Error(getApiErrorMessage(errorBody, 'Unable to create account.'));
    }

    await authenticateUser(username, password);
    authElements.registerPassword.value = '';
    authElements.registerConfirmPassword.value = '';
    currentState.auth.firstRun = false;
    showAuthenticatedApp();
  } catch (err) {
    setAuthMessage(authElements.registerMessage, err.message || 'Unable to create account.');
  } finally {
    submitBtn.disabled = false;
  }
}

async function handleLogout() {
  try {
    const response = await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'same-origin' });
    if (!response.ok) throw new Error('Unable to sign out. Please try again.');
  } catch (err) {
    console.error('Logout request failed:', err);
    alert('Unable to sign out. Please try again.');
    return;
  }

  if (elements.audio) {
    elements.audio.pause();
    elements.audio.removeAttribute('src');
  }

  resetRequests();
  navigationGeneration++;
  currentState.auth.currentUser = null;
  currentState.auth.authenticated = false;
  currentState.currentPlayingSong = null;
  currentState.isPlaying = false;
  playbackGeneration++;
  clearMediaSession();
  searchState.selectedSongs.clear();
  updateSearchSelection();
  hideSearchOverlay();
  closeManualPlaylistDialog(true);
  resetSongRequests();
  currentState.queue = [];
  currentState.queueIndex = -1;
  currentState.activePlaylistId = null;
  currentState.activeSessionId = null;

  if (authElements.accountMenu) authElements.accountMenu.classList.remove('open');
  showAuthScreen('login');
}

function loadAuthenticatedAppData() {
  refreshSongRequests();
  fetchSongs(1);
  loadPlaylists();
  loadHomePageSections();
}

function initAuthEvents() {
  if (authElements.loginForm) authElements.loginForm.addEventListener('submit', handleLoginSubmit);
  if (authElements.registerForm) authElements.registerForm.addEventListener('submit', handleRegisterSubmit);
  if (authElements.btnShowRegister) {
    authElements.btnShowRegister.addEventListener('click', () => showAuthScreen('register'));
  }
  if (authElements.btnShowLogin) {
    authElements.btnShowLogin.addEventListener('click', () => showAuthScreen('login'));
  }
  if (authElements.btnLogout) authElements.btnLogout.addEventListener('click', handleLogout);
  if (authElements.accountTrigger && authElements.accountMenu) {
    authElements.accountTrigger.addEventListener('click', () => {
      authElements.accountMenu.classList.toggle('open');
    });
  }
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#sidebar-account') && authElements.accountMenu) {
      authElements.accountMenu.classList.remove('open');
    }
  });
}

// 1. NAVIGATION / SPA ROUTING
function initNavigation() {
  const allNavItems = document.querySelectorAll('.nav-item, .mobile-nav-item');
  allNavItems.forEach(item => {
    item.addEventListener('click', () => {
      if (!currentState.auth.authenticated) {
        showAuthScreen('login');
        return;
      }

      const targetViewId = item.getAttribute('data-target');
      if (!targetViewId) return;
      if (targetViewId === currentState.activeTab) {
        if (targetViewId === 'view-home') {
          if (resources.get('playlists')?.failed) loadPlaylists({force: true});
          if (['continue', 'recent', 'added'].some(key => resources.get(key)?.failed)) loadHomePageSections();
          if (resources.get('songs')?.failed) fetchSongs(currentState.currentPage);
        }
        return;
      }
      navigationGeneration++;
      cancelResource('detail');
      
      // Update active nav button on all desktop & mobile bars
      allNavItems.forEach(nav => {
        if (nav.getAttribute('data-target') === targetViewId) {
          nav.classList.add('active');
        } else {
          nav.classList.remove('active');
        }
      });
      
      // Update active view visibility
      elements.views.forEach(view => {
        if (view.id === targetViewId) {
          view.classList.add('active');
        } else {
          view.classList.remove('active');
        }
      });
      
      currentState.activeTab = targetViewId;
      
      // Close mobile drawer if open
      const mobileDrawerOverlay = document.getElementById('mobile-drawer-overlay');
      if (mobileDrawerOverlay) mobileDrawerOverlay.classList.remove('active');

      // If returning home, restore full songs list and dynamic sections
      if (targetViewId === 'view-home') {
        fetchSongs(1);
        loadPlaylists();
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
    if (!currentState.songs.length) showTableLoading();
    const url = `/api/v1/songs?page=${page}&page_size=${currentState.pageSize}`;
    const data = await requestJSON('songs', url, d => d && isSongList(d.songs) && Number.isInteger(d.page) && Number.isFinite(d.total_count));
    if (!data || !changedResource('songs', data)) return;
    
    currentState.songs = data.songs;
    currentState.total_count = data.total_count;
    currentState.currentPage = data.page;
    
    renderSongsTable();
    updatePaginationControls();
  } catch (error) {
    console.error("Failed to fetch songs:", error);
    if (!currentState.songs.length) elements.songsTableBody.innerHTML = '';
    showResourceError('songs', elements.songsTableBody.closest('table'), () => fetchSongs(page), error);
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
      ? `<img src="/api/v1/songs/${song.id}/artwork" loading="lazy" decoding="async" alt="cover" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
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
  
  if (!elements.songsTableBody._verseBound) {
    elements.songsTableBody._verseBound = true;
    elements.songsTableBody.addEventListener('click', event => {
      const row = event.target.closest('tr[data-song-id]');
      if (!row) return;
      const id = Number(row.dataset.songId);
      if (event.target.closest('.heart-btn')) { toggleLikeSong(id); return; }
      if (event.target.closest('.options-row-btn')) return;
      const song = currentState.songs.find(s => s.id === id);
      if (song) playSong(song, currentState.songs);
    });
  }
  updatePlayingRows();
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
  selectedIndex: -1,
  selectedSongs: new Map(),
  generation: 0,
  query: '',
  destinationId: null,
  returnFocus: null
};

let searchTimeout = null;

function showSearchOverlay(initialChar = '', destinationId = null) {
  if (searchState.isOpen) return;
  searchState.isOpen = true;
  searchState.destinationId = destinationId;
  searchState.returnFocus = document.activeElement;
  elements.searchOverlay.inert = false;
  elements.searchOverlay.classList.add('active');
  elements.searchOverlayInput.value = initialChar;
  elements.searchOverlayInput.focus();
  searchState.selectedIndex = -1;
  updateSearchSelection();
  triggerSearch(initialChar);
  refreshSongRequests();
}

function hideSearchOverlay() {
  searchState.isOpen = false;
  searchState.generation++;
  clearTimeout(searchTimeout);
  cancelResource('search');
  invalidateExternalSearch();
  if (elements.searchOverlay) {
    elements.searchOverlay.classList.remove('active');
    elements.searchOverlay.inert = true;
  }
  if (elements.searchOverlayInput) elements.searchOverlayInput.value = '';
  if (elements.searchOverlayResults) elements.searchOverlayResults.innerHTML = '';
  searchState.results = [];
  searchState.selectedIndex = -1;
  searchState.returnFocus?.focus();
}

async function triggerSearch(query) {
  scheduleExternalSearch(query);
  const generation = ++searchState.generation;
  const trimmed = query.trim();
  searchState.query = trimmed;
  const status = document.getElementById('search-load-status');
  const retry = document.getElementById('btn-retry-song-search');
  if (retry) retry.hidden = true;
  elements.searchOverlayResults.setAttribute('aria-busy', Boolean(trimmed));
  if (!trimmed) {
    cancelResource('search');
    elements.searchOverlayResults.innerHTML = '';
    searchState.results = [];
    searchState.selectedIndex = -1;
    setText(status, 'Search your entire library by title, artist, or album.');
    return;
  }
  setText(status, 'Searching the library…');
  try {
    const data = await requestJSON('search', `/api/v1/search?q=${encodeURIComponent(trimmed)}`, isSongList);
    if (!data || generation !== searchState.generation || !searchState.isOpen) return;
    clearResourceError('search');
    searchState.results = data;
    searchState.selectedIndex = -1;
    renderSearchResults();
    setText(status, `${data.length} matching song${data.length === 1 ? '' : 's'}`);
  } catch (err) {
    if (generation !== searchState.generation || !searchState.isOpen) return;
    setText(status, err.message || 'Unable to search the library.');
    if (retry) retry.hidden = false;
  } finally {
    if (generation === searchState.generation) elements.searchOverlayResults.setAttribute('aria-busy', 'false');
  }
}

function updateSearchSelection(songId = null) {
  setText(document.getElementById('search-selection-count'), `${searchState.selectedSongs.size} selected`);
  ['btn-clear-song-selection', 'btn-add-selection'].forEach(id => {
    const button = document.getElementById(id);
    if (button) button.disabled = searchState.selectedSongs.size === 0;
  });
  const selector = songId === null ? '.search-result-item' : `.search-result-item[data-song-id="${songId}"]`;
  elements.searchOverlayResults?.querySelectorAll(selector).forEach(row => {
    const selected = searchState.selectedSongs.has(Number(row.dataset.songId));
    row.classList.toggle('selected', selected);
    const checkbox = row.querySelector('.search-song-checkbox');
    if (checkbox) checkbox.checked = selected;
  });
}

function clearSongSelection() {
  searchState.selectedSongs.clear();
  updateSearchSelection();
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
      <div class="search-result-item ${highlightClass} ${searchState.selectedSongs.has(song.id) ? 'selected' : ''}" data-index="${idx}" data-song-id="${song.id}">
        <input type="checkbox" class="search-song-checkbox" aria-label="Select ${escapeHtml(song.title || 'song')}" ${searchState.selectedSongs.has(song.id) ? 'checked' : ''}>
        <div class="table-song-art">
          ${song.artwork_available 
            ? `<img src="/api/v1/songs/${song.id}/artwork" loading="lazy" decoding="async" alt="art" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
               <div style="display:none;">${SVG_ICONS.music}</div>`
            : SVG_ICONS.music}
        </div>
        <div class="search-result-meta">
          <div class="search-result-title">${escapeHtml(song.title)}</div>
          <div class="search-result-artist">${escapeHtml(song.artist)}</div>
          <div class="search-result-artist">${escapeHtml(song.album || '')}</div>
        </div>
        <div class="search-result-duration">${formatDuration(song.duration)}</div>
        <button type="button" class="manual-playlist-button search-result-play" data-search-play aria-label="Play ${escapeHtml(song.title || 'song')}">Play</button>
      </div>
    `;
  });
  elements.searchOverlayResults.innerHTML = html;
  
}

function selectSearchResult(index) {
  const song = searchState.results[index];
  if (!song) return;
  if (searchState.selectedSongs.has(song.id)) searchState.selectedSongs.delete(song.id);
  else searchState.selectedSongs.set(song.id, song);
  updateSearchSelection(song.id);
}

function updateSearchHighlight(previous) {
  [previous, searchState.selectedIndex].forEach(index => {
    const row = elements.searchOverlayResults.querySelector(`[data-index="${index}"]`);
    row?.classList.toggle('highlighted', index === searchState.selectedIndex);
  });
}

function handleSearchKeyboard(e) {
  if (!searchState.isOpen) return;
  if (e.key === 'Tab') { trapPlaylistFocus(e, elements.searchOverlay); return; }
  if (e.key !== 'Escape' && e.target?.closest('button, input[type="checkbox"]')) return;
  const previous = searchState.selectedIndex;
  
  if (e.key === 'Escape') {
    hideSearchOverlay();
    e.preventDefault();
  } else if (e.key === 'ArrowDown') {
    if (searchState.results.length > 0) {
      searchState.selectedIndex = (searchState.selectedIndex + 1) % searchState.results.length;
      updateSearchHighlight(previous);
      scrollHighlightedIntoView();
    }
    e.preventDefault();
  } else if (e.key === 'ArrowUp') {
    if (searchState.results.length > 0) {
      searchState.selectedIndex = (searchState.selectedIndex - 1 + searchState.results.length) % searchState.results.length;
      updateSearchHighlight(previous);
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
  if (!elements.searchOverlay || elements.searchOverlay._verseSearchBound) return;
  elements.searchOverlay._verseSearchBound = true;
  initDiscoveryEvents();
  elements.searchOverlayResults.addEventListener('click', event => {
    const row = event.target.closest('.search-result-item');
    if (!row) return;
    const index = Number(row.dataset.index);
    if (event.target.closest('[data-search-play]')) {
      const song = searchState.results[index];
      if (song) playSong(song);
    } else selectSearchResult(index);
  });
  document.getElementById('btn-close-search')?.addEventListener('click', hideSearchOverlay);
  document.getElementById('btn-clear-song-selection')?.addEventListener('click', clearSongSelection);
  document.getElementById('btn-add-selection')?.addEventListener('click', () => openPlaylistPicker());
  document.getElementById('btn-retry-song-search')?.addEventListener('click', () => triggerSearch(searchState.query));
  // Global keydown handler for shortcuts (Space toggle, instant search)
  window.addEventListener('keydown', (e) => {
    if (manualPlaylistState.open) return;
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
    searchState.generation++;
    cancelResource('search');
    invalidateExternalSearch();
    const retry = document.getElementById('btn-retry-song-search');
    if (retry) retry.hidden = true;
    const query = e.target.value;
    searchTimeout = setTimeout(() => {
      triggerSearch(query);
    }, 100);
  });

  // Click outside to close overlay
  elements.searchOverlay.addEventListener('click', (e) => {
    // An action may replace its button before bubbling reaches this listener.
    // A detached target is not a backdrop click and must not close search.
    if (e.target === elements.searchOverlay) {
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
const discoveryState = {generation: 0, query: '', timer: null, results: [], nodes: new Map(), requestNodes: new Map(),
  jobs: new Map(), pending: new Set(), errors: new Map(), pollTimer: null, polling: false, epoch: 0, canRequest: false};
const activeRequestStates = new Set(['queued', 'resolving', 'downloading', 'indexing']);
const requestStates = new Set([...activeRequestStates, 'awaiting_choice', 'ready', 'failed']);
function isRequestJob(job) {
  return job && typeof job.id === 'string' && typeof job.key === 'string' && requestStates.has(job.state) &&
    job.track && typeof job.track.title === 'string' && typeof job.track.artist === 'string' &&
    (job.state !== 'ready' || (job.song && isSongList([job.song]))) &&
    (job.state !== 'awaiting_choice' || (Array.isArray(job.candidates) && job.candidates.length > 0 &&
      job.candidates.length <= 5 && job.candidates.every(isExternalTrack)));
}
function acceptRequestJob(job) {
  if (!isRequestJob(job)) return false;
  const previous = discoveryState.jobs.get(job.id);
  // API timestamps are UTC ISO strings with microsecond precision. An older
  // search/poll snapshot must not overwrite a completed failure, choice or retry.
  if (previous && typeof job.updated_at === 'string' && typeof previous.updated_at === 'string' &&
      job.updated_at < previous.updated_at) return false;
  discoveryState.jobs.set(job.id, job);
  discoveryState.errors.delete(job.key);
  return true;
}
function isExternalTrack(track) {
  return track && typeof track.key === 'string' && ['spotify', 'musicbrainz'].includes(track.provider) &&
    typeof track.recording_id === 'string' && typeof track.title === 'string' && typeof track.artist === 'string' &&
    typeof track.album === 'string' && Number.isFinite(track.duration) && track.duration >= 0;
}
function invalidateExternalSearch() {
  discoveryState.generation++;
  clearTimeout(discoveryState.timer);
  cancelResource('external-search');
}
function scheduleExternalSearch(query) {
  if (!document.getElementById('external-search-results')) return;
  invalidateExternalSearch();
  discoveryState.query = query.trim();
  if (discoveryState.query.length < 2) {
    discoveryState.results = []; discoveryState.nodes.clear();
    document.getElementById('external-search-results').replaceChildren();
    setText(document.getElementById('external-search-status'), 'Enter at least two characters to discover songs.');
    document.getElementById('btn-retry-external-search').hidden = true;
    return;
  }
  setText(document.getElementById('external-search-status'), 'Searching external catalogue…');
  discoveryState.timer = setTimeout(() => searchExternalSongs(discoveryState.query), 400);
}
async function searchExternalSongs(query) {
  const generation = discoveryState.generation;
  const retry = document.getElementById('btn-retry-external-search');
  if (retry) retry.hidden = true;
  try {
    const data = await requestJSON('external-search', `/api/v1/search/external?q=${encodeURIComponent(query)}`,
      d => d && Array.isArray(d.results) && d.results.every(isExternalTrack) && typeof d.can_request === 'boolean');
    if (!data || generation !== discoveryState.generation || !searchState.isOpen) return;
    discoveryState.results = data.results; discoveryState.canRequest = data.can_request;
    data.results.forEach(track => acceptRequestJob(track.job));
    renderExternalSongs(); renderSongRequests();
    setText(document.getElementById('external-search-status'), !data.can_request
      ? `${data.provider}: downloads need VERSE_MUSIC_DIR and the request worker configured.`
      : data.results.length ? `${data.provider} catalogue · ${data.results.length} results` : 'No external recordings found. Local results are unchanged.');
  } catch (error) {
    if (generation !== discoveryState.generation || !searchState.isOpen) return;
    setText(document.getElementById('external-search-status'), error.message + ' Local search is still available.');
    if (retry) retry.hidden = false;
  }
}
function externalJob(track) { return [...discoveryState.jobs.values()].find(job => job.key === track.key) || track.job; }
function requestLabel(job) {
  if (job.state === 'queued' && job.attempts === 0) return 'Queued — waiting for worker';
  if (job.state === 'queued' && job.error) return 'Queued for retry';
  return {queued:'Queued',resolving:'Resolving recording',downloading:'Downloading',indexing:'Indexing',awaiting_choice:'Choose version',ready:'In your library',failed:'Failed — not processing'}[job.state];
}
function updateExternalSong(row, track) {
  const job = externalJob(track), song = job?.song || track.song;
  const busy = discoveryState.pending.has(track.key);
  const signature = JSON.stringify([song?.id, job?.state, job?.error, job?.candidates, busy, discoveryState.canRequest, discoveryState.errors.get(track.key)]);
  if (row._verseRequestSignature === signature) return;
  row._verseRequestSignature = signature;
  const actions = row.querySelector('.external-result-actions');
  if (song) actions.innerHTML = '<span class="manual-playlist-status">In your library</span><button type="button" class="manual-playlist-button" data-discovery-action="play">Play</button><button type="button" class="manual-playlist-button" data-discovery-action="add">Add to playlist</button>';
  else if (job) actions.innerHTML = `<span>${escapeHtml(requestLabel(job))}</span>${['failed','awaiting_choice'].includes(job.state) ? '<button type="button" class="manual-playlist-button" data-discovery-action="retry">Retry discovery</button><button type="button" class="manual-playlist-button" data-discovery-action="reselect">Search again</button>' : ''}`;
  else actions.innerHTML = `<button type="button" class="manual-playlist-button" data-discovery-action="request" ${busy || !discoveryState.canRequest ? 'disabled' : ''}>${busy ? 'Requesting…' : 'Request song'}</button>`;
  if (busy) actions.querySelectorAll('button').forEach(button => { button.disabled = true; });
  setText(row.querySelector('.external-result-error'), discoveryState.errors.get(track.key) || job?.error || '');
  const previousPicker = row.querySelector('.request-version-picker');
  const wasOpen = previousPicker?.open;
  previousPicker?.remove();
  row.classList.toggle('has-version-options', job?.state === 'awaiting_choice');
  if (job?.state === 'awaiting_choice') {
    const picker = document.createElement('details'); picker.className = 'request-version-picker';
    picker.open = wasOpen ?? true;
    picker.innerHTML = `<summary>Choose version (${job.candidates.length})</summary><p>These are possible matches, not verified recording identities. Choose the release you want.</p>` +
      job.candidates.map(candidate => `<div class="request-version-option"><div><strong>${escapeHtml(candidate.title)}</strong><small>${escapeHtml(candidate.artist)} · ${formatDuration(candidate.duration)}</small><small>${escapeHtml(candidate.album || 'Album unavailable')} · ${escapeHtml(candidate.version || 'Version not specified; check title/release')}</small></div><button type="button" class="manual-playlist-button" data-discovery-action="choose-version" data-candidate-key="${escapeHtml(candidate.key)}" ${busy ? 'disabled' : ''}>Use this version</button></div>`).join('');
    row.appendChild(picker);
  }
}
function renderExternalSongs() {
  const container = document.getElementById('external-search-results');
  if (!container) return;
  const keys = new Set(discoveryState.results.map(track => track.key));
  discoveryState.nodes.forEach((node, key) => { if (!keys.has(key)) { node.remove(); discoveryState.nodes.delete(key); } });
  discoveryState.results.forEach((track, index) => {
    let row = discoveryState.nodes.get(track.key);
    if (!row) {
      row = document.createElement('div'); row.className = 'external-result'; row.dataset.discoveryKey = track.key;
      const art = typeof track.artwork_url === 'string' && track.artwork_url.startsWith('https://')
        ? `<img src="${escapeHtml(track.artwork_url)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.style.display='none'">` : '';
      row.innerHTML = `${art}<div class="external-result-meta"><strong>${escapeHtml(track.title)}</strong><small>${escapeHtml(track.artist)}</small><small>${escapeHtml([track.album,track.version].filter(Boolean).join(' · '))} · ${track.duration > 0 ? formatDuration(track.duration) : 'Duration unavailable'}</small><div class="external-result-error" role="status"></div></div><div class="external-result-actions"></div>`;
      discoveryState.nodes.set(track.key, row);
    }
    updateExternalSong(row, track);
    if (container.children[index] !== row) container.insertBefore(row, container.children[index] || null);
  });
}
function renderSongRequests() {
  const list = document.getElementById('song-requests-list');
  if (!list) return;
  const all = [...discoveryState.jobs.values()];
  const active = all.filter(job => activeRequestStates.has(job.state)).length;
  const choices = all.filter(job => job.state === 'awaiting_choice').length;
  const jobs = all.sort((a,b) => Number(!activeRequestStates.has(a.state)) - Number(!activeRequestStates.has(b.state)) || String(b.created_at).localeCompare(String(a.created_at))).slice(0,100);
  const summary = [active ? `${active} active` : '', choices ? `${choices} need a version` : ''].filter(Boolean).join(', ');
  setText(document.getElementById('song-requests-summary'), `Song requests${summary ? ` (${summary})` : ''}`);
  const signature = JSON.stringify(jobs.map(job => [job.id,job.state,job.error,job.candidates,job.song?.id,discoveryState.pending.has(job.key),discoveryState.errors.get(job.key)]));
  if (list._verseRequestSignature === signature) return;
  list._verseRequestSignature = signature;
  // Keep unrelated request rows/artwork alive during polling, as well as the
  // entire library and audio DOM. Reorder nodes only when ordering changed.
  const ids = new Set(jobs.map(job => job.id));
  discoveryState.requestNodes.forEach((node,id) => { if (!ids.has(id)) { node.remove(); discoveryState.requestNodes.delete(id); } });
  if (!jobs.length) { list.textContent = 'No song requests yet.'; return; }
  if (!discoveryState.requestNodes.size) list.replaceChildren();
  jobs.forEach((job,index) => {
    let row = discoveryState.requestNodes.get(job.id);
    if (!row) {
      row = document.createElement('div'); row.className = 'song-request-item'; row.dataset.requestId = job.id;
      row.innerHTML = `<div class="external-result-meta"><strong>${escapeHtml(job.track.title)}</strong><small>${escapeHtml(job.track.artist)}</small><small class="request-state"></small><small class="external-result-error"></small></div><div class="external-result-actions"></div>`;
      discoveryState.requestNodes.set(job.id,row);
    }
    setText(row.querySelector('.request-state'),requestLabel(job));
    updateExternalSong(row,{...job.track,job});
    if (list.children[index] !== row) list.insertBefore(row,list.children[index] || null);
  });
}
async function submitSongRequest(track, retry = false) {
  if (discoveryState.pending.has(track.key)) return;
  const epoch = discoveryState.epoch;
  const startingVersion = externalJob(track)?.updated_at;
  discoveryState.pending.add(track.key); discoveryState.errors.delete(track.key); renderExternalSongs(); renderSongRequests();
  try {
    const job = retry ? externalJob(track) : null;
    const data = await sendPlaylistMutation(job ? `/api/v1/song-requests/${job.id}/retry` : '/api/v1/song-requests',
      job ? {} : {provider:track.provider,recording_id:track.recording_id,release_id:track.release_id || ''});
    if (epoch !== discoveryState.epoch) return;
    if (!isRequestJob(data)) throw new Error('The server returned an invalid song request. Refresh requests before retrying.');
    acceptRequestJob(data);
    showPlaylistNotice(data.state === 'ready' ? `${data.track.title} is already in your library.` : `Requested ${data.track.title}. It will appear when ready.`);
    refreshSongRequests();
  } catch (error) {
    const current = externalJob(track);
    if (epoch === discoveryState.epoch && (!current || current.updated_at === startingVersion))
      discoveryState.errors.set(track.key, error.message);
  }
  finally {
    if (epoch === discoveryState.epoch) { discoveryState.pending.delete(track.key); renderExternalSongs(); renderSongRequests(); }
  }
}
async function chooseSongRequestVersion(track, candidateKey) {
  const job = externalJob(track);
  if (!job || job.state !== 'awaiting_choice' || discoveryState.pending.has(track.key)) return;
  const epoch = discoveryState.epoch;
  discoveryState.pending.add(track.key); discoveryState.errors.delete(track.key); renderExternalSongs(); renderSongRequests();
  try {
    const data = await sendPlaylistMutation(`/api/v1/song-requests/${job.id}/choose-version`, {candidate_key:candidateKey});
    if (epoch !== discoveryState.epoch) return;
    if (!isRequestJob(data)) throw new Error('Invalid request status. Refresh before retrying the version choice.');
    acceptRequestJob(data);
    showPlaylistNotice('Version selected. Continuing the existing request.');
    refreshSongRequests();
  } catch (error) {
    if (epoch === discoveryState.epoch && externalJob(track)?.updated_at === job.updated_at)
      discoveryState.errors.set(track.key, error.message);
  }
  finally {
    if (epoch === discoveryState.epoch) { discoveryState.pending.delete(track.key); renderExternalSongs(); renderSongRequests(); }
  }
}
async function refreshSongRequests() {
  if (!currentState.auth.authenticated || !document.getElementById('song-requests-list') || discoveryState.polling) return;
  const epoch = discoveryState.epoch;
  discoveryState.polling = true;
  clearTimeout(discoveryState.pollTimer); discoveryState.pollTimer = null;
  try {
    const jobs = await requestJSON('song-requests', '/api/v1/song-requests', data => Array.isArray(data) && data.every(isRequestJob), {force:true});
    if (!jobs || epoch !== discoveryState.epoch) return;
    const present = new Set(jobs.map(job => job.id));
    const missing = [...discoveryState.jobs.values()].filter(job => (activeRequestStates.has(job.state) || job.state === 'awaiting_choice') && !present.has(job.id)).slice(0,10);
    const extra = await Promise.all(missing.map(job => requestJSON('song-request:' + job.id, '/api/v1/song-requests/' + job.id, isRequestJob, {force:true}).catch(() => null)));
    if (epoch !== discoveryState.epoch) return;
    [...jobs, ...extra.filter(Boolean)].forEach(job => {
      const previous = discoveryState.jobs.get(job.id);
      if (acceptRequestJob(job) && previous && previous.state !== 'ready' && job.state === 'ready')
        showPlaylistNotice(`${job.track.title} is ready to play.`);
    });
    while (discoveryState.jobs.size > 150) {
      const removable = [...discoveryState.jobs.values()].find(job => ['ready','failed'].includes(job.state));
      if (!removable) break;
      discoveryState.jobs.delete(removable.id);
    }
    setText(document.getElementById('song-requests-status'), ''); renderSongRequests(); renderExternalSongs();
  } catch (error) {
    if (epoch === discoveryState.epoch) setText(document.getElementById('song-requests-status'), error.message + ' Request status is retained; refresh to retry.');
  } finally {
    if (epoch === discoveryState.epoch) {
      discoveryState.polling = false;
      const active = [...discoveryState.jobs.values()].some(job => activeRequestStates.has(job.state));
      // Terminal/awaiting-choice jobs are not ongoing work. Refresh on opening
      // search, returning to the page, or explicit Refresh instead of polling.
      if (active) discoveryState.pollTimer = setTimeout(refreshSongRequests, 3000);
    }
  }
}
function resetSongRequests() {
  discoveryState.epoch++; discoveryState.polling = false;
  clearTimeout(discoveryState.pollTimer); discoveryState.pollTimer = null; invalidateExternalSearch();
  cancelResource('song-requests');
  discoveryState.jobs.clear(); discoveryState.pending.clear(); discoveryState.errors.clear();
  discoveryState.requestNodes.forEach(node => node.remove()); discoveryState.requestNodes.clear();
  discoveryState.results = []; discoveryState.nodes.clear();
  document.getElementById('external-search-results')?.replaceChildren();
  renderSongRequests();
}
function initDiscoveryEvents() {
  const external = document.getElementById('external-search-results'), list = document.getElementById('song-requests-list');
  if (!external || !list || external._verseDiscoveryBound) return;
  external._verseDiscoveryBound = true;
  document.getElementById('btn-retry-external-search')?.addEventListener('click', () => searchExternalSongs(discoveryState.query));
  document.getElementById('btn-refresh-song-requests')?.addEventListener('click', refreshSongRequests);
  const act = event => {
    const button = event.target.closest('[data-discovery-action]'); if (!button) return;
    const row = button.closest('[data-discovery-key], [data-request-id]');
    const job = row?.dataset.requestId ? discoveryState.jobs.get(row.dataset.requestId) : null;
    const track = job?.track || discoveryState.results.find(item => item.key === row?.dataset.discoveryKey);
    if (!track) return;
    const song = job?.song || externalJob(track)?.song || track.song;
    if (button.dataset.discoveryAction === 'play' && song) playSong(song);
    else if (button.dataset.discoveryAction === 'add' && song) openPlaylistPicker([song.id]);
    else if (button.dataset.discoveryAction === 'choose-version') chooseSongRequestVersion(track, button.dataset.candidateKey);
    else if (button.dataset.discoveryAction === 'reselect') {
      showSearchOverlay(); elements.searchOverlayInput.value = track.title; elements.searchOverlayInput.focus(); triggerSearch(track.title);
    } else submitSongRequest(track, button.dataset.discoveryAction === 'retry');
  };
  external.addEventListener('click', act); list.addEventListener('click', act);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshSongRequests(); });
}

const manualPlaylistState = {
  open: false, pending: false, mode: 'create', origin: 'create', generation: 0,
  playlists: [], destinationId: null, songIds: [], returnFocus: null
};
let playlistNoticeTimer = null;

function trapPlaylistFocus(event, container) {
  if (event.key !== 'Tab') return;
  const controls = [...container.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]')]
    .filter(control => !control.closest('[hidden]'));
  if (!controls.length) return;
  const first = controls[0], last = controls[controls.length - 1];
  if (event.shiftKey && (document.activeElement === first || !container.contains(document.activeElement))) {
    event.preventDefault(); last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !container.contains(document.activeElement))) {
    event.preventDefault(); first.focus();
  }
}

function setManualPlaylistError(message = '') {
  const error = document.getElementById('manual-playlist-error');
  if (error) { error.textContent = message; error.hidden = !message; }
}

function updateManualPlaylistControls() {
  const state = manualPlaylistState;
  const dialog = document.getElementById('manual-playlist-dialog');
  if (!dialog) return;
  dialog.setAttribute('aria-busy', String(state.pending));
  dialog.querySelectorAll('button, input, textarea').forEach(control => { control.disabled = state.pending; });
  const add = document.getElementById('btn-confirm-playlist-add');
  if (add) {
    add.disabled = state.pending || !state.playlists.some(p => p.id === state.destinationId);
    add.textContent = state.pending ? 'Adding…' : `Add ${state.songIds.length} song${state.songIds.length === 1 ? '' : 's'}`;
  }
  setText(document.getElementById('btn-submit-manual-playlist'), state.pending ? 'Creating…' : state.songIds.length ? 'Create and add songs' : 'Create playlist');
}

function showManualPlaylistForm() {
  manualPlaylistState.mode = 'create';
  document.getElementById('playlist-picker-panel').hidden = true;
  document.getElementById('manual-playlist-form').hidden = false;
  setText(document.getElementById('manual-playlist-title'), manualPlaylistState.songIds.length ? 'Create playlist and add songs' : 'Create playlist');
  setText(document.getElementById('btn-cancel-playlist-create'), manualPlaylistState.origin === 'picker' ? 'Back to playlists' : 'Cancel');
  setManualPlaylistError(); updateManualPlaylistControls();
  document.getElementById('manual-playlist-name').focus();
}

function showPlaylistPickerPanel() {
  manualPlaylistState.mode = 'choose';
  document.getElementById('playlist-picker-panel').hidden = false;
  document.getElementById('manual-playlist-form').hidden = true;
  setText(document.getElementById('manual-playlist-title'), `Add ${manualPlaylistState.songIds.length} selected song${manualPlaylistState.songIds.length === 1 ? '' : 's'} to playlist`);
  setManualPlaylistError(); renderPlaylistPicker();
  document.getElementById('playlist-picker-search').focus();
}

function openManualPlaylistDialog(origin) {
  const dialog = document.getElementById('manual-playlist-dialog');
  if (!dialog || manualPlaylistState.open) return false;
  Object.assign(manualPlaylistState, {open: true, pending: false, origin,
    songIds: origin === 'picker' ? [...searchState.selectedSongs.keys()] : [],
    destinationId: searchState.destinationId, playlists: [], returnFocus: document.activeElement});
  manualPlaylistState.generation++;
  document.getElementById('manual-playlist-name').value = '';
  document.getElementById('manual-playlist-description').value = '';
  document.getElementById('playlist-picker-search').value = '';
  document.getElementById('btn-retry-playlist-picker').hidden = true;
  if (typeof dialog.showModal === 'function') dialog.showModal();
  else {
    dialog.setAttribute('open', ''); dialog.classList.add('dialog-fallback');
    const app = document.getElementById('app-container');
    if (app) app.inert = true;
    if (elements.searchOverlay) elements.searchOverlay.inert = true;
  }
  if (origin === 'picker') showPlaylistPickerPanel();
  else showManualPlaylistForm();
  return true;
}

function closeManualPlaylistDialog(force = false) {
  const state = manualPlaylistState;
  if (!state.open || (state.pending && !force)) return;
  state.open = false; state.pending = false; state.generation++;
  const dialog = document.getElementById('manual-playlist-dialog');
  if (typeof dialog?.close === 'function') dialog.close();
  else dialog?.removeAttribute('open');
  if (dialog?.classList.contains('dialog-fallback')) {
    dialog.classList.remove('dialog-fallback');
    const app = document.getElementById('app-container');
    if (app) app.inert = false;
    if (elements.searchOverlay) elements.searchOverlay.inert = !searchState.isOpen;
  }
  state.returnFocus?.focus();
}

async function openPlaylistPicker(songIds = null) {
  if (!(songIds?.length || searchState.selectedSongs.size) || !openManualPlaylistDialog('picker')) return;
  if (Array.isArray(songIds)) { manualPlaylistState.songIds = [...songIds]; showPlaylistPickerPanel(); }
  await loadPlaylistPicker();
}

async function loadPlaylistPicker(options = {}) {
  const state = manualPlaylistState, generation = state.generation;
  setText(document.getElementById('playlist-picker-status'), 'Loading playlists…');
  document.getElementById('btn-retry-playlist-picker').hidden = true;
  try {
    const playlists = await fetchAllPlaylists(options);
    if (!playlists || !state.open || state.generation !== generation) return;
    state.playlists = playlists;
    setManualPlaylistError(); renderPlaylistPicker();
  } catch (error) {
    if (!state.open || state.generation !== generation) return;
    setText(document.getElementById('playlist-picker-status'), 'Unable to load playlists. Your selection is kept.');
    setManualPlaylistError(error.message);
    document.getElementById('btn-retry-playlist-picker').hidden = false;
  }
}

function renderPlaylistPicker() {
  const state = manualPlaylistState;
  const query = document.getElementById('playlist-picker-search').value.trim().toLowerCase();
  const playlists = state.playlists.filter(p => p.name.toLowerCase().includes(query));
  document.getElementById('playlist-picker-list').innerHTML = playlists.map(p => `
    <label class="playlist-picker-option">
      <input type="radio" name="playlist-destination" value="${p.id}" ${state.destinationId === p.id ? 'checked' : ''}>
      <span>${escapeHtml(p.name)}<small>${p.songs_count} songs</small></span>
    </label>`).join('');
  setText(document.getElementById('playlist-picker-status'), playlists.length ? '' : query ? 'No playlists match that name.' : 'No playlists yet. Create one below.');
  const destination = state.playlists.find(p => p.id === state.destinationId);
  setText(document.getElementById('playlist-picker-destination'), destination ? `Destination: ${destination.name}` : 'Choose a playlist.');
  updateManualPlaylistControls();
}

async function sendPlaylistMutation(url, payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(url, {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload), signal: controller.signal});
    const data = await response.json().catch(error => {
      if (error.name === 'AbortError') throw error;
      throw new Error('The server returned an invalid response. Your selection is kept.');
    });
    if (!response.ok) throw new Error(getApiErrorMessage(data, `Request failed (HTTP ${response.status}).`));
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('The request timed out. Your selection is kept; you can try again.');
    throw error;
  } finally { clearTimeout(timer); }
}

function showPlaylistNotice(message) {
  const notice = document.getElementById('playlist-notice');
  if (!notice) return;
  clearTimeout(playlistNoticeTimer);
  notice.textContent = message; notice.hidden = false;
  playlistNoticeTimer = setTimeout(() => { notice.hidden = true; }, 8000);
}

function updatePlaylistSummaries(id, name, count) {
  // Patch confirmed metadata immediately, then revalidate the affected resources.
  ['sidebar-playlists', 'mobile-drawer-playlists'].forEach(listId => {
    const list = document.getElementById(listId);
    if (!list) return;
    let item = list.querySelector(`[data-playlist-id="${id}"]`);
    if (!item) {
      if (!list.querySelector('.playlist-sidebar-item')) list.replaceChildren();
      item = document.createElement('li');
      item.className = 'playlist-sidebar-item'; item.dataset.playlistId = id;
      item.innerHTML = '<span class="playlist-sidebar-name"></span><span class="playlist-sidebar-count"></span>';
      item.addEventListener('click', () => {
        document.getElementById('mobile-drawer-overlay')?.classList.remove('active');
        openPlaylistDetail(id);
      });
    }
    setText(item.querySelector('.playlist-sidebar-name'), name);
    setText(item.querySelector('.playlist-sidebar-count'), count);
    list.prepend(item);
  });
  document.querySelectorAll(`.playlist-card[data-playlist-id="${id}"] .card-desc`).forEach(node => setText(node, `${count} songs`));
}

async function submitManualPlaylist(create = false) {
  const state = manualPlaylistState;
  if (!state.open || state.pending) return;
  const destination = state.playlists.find(p => p.id === state.destinationId);
  const name = create ? document.getElementById('manual-playlist-name').value.trim() : destination?.name;
  if (create && !name) { setManualPlaylistError('Playlist name cannot be blank.'); return; }
  if (!create && !destination) { setManualPlaylistError('Choose a destination playlist.'); return; }
  const songIds = [...state.songIds], generation = state.generation, epoch = requestEpoch;
  const navigation = navigationGeneration, origin = state.origin;
  state.pending = true; setManualPlaylistError(); updateManualPlaylistControls();
  try {
    const data = await sendPlaylistMutation(create ? '/api/v1/playlists' : `/api/v1/playlists/${destination.id}/songs`,
      create ? {name, description: document.getElementById('manual-playlist-description').value.trim(), song_ids: songIds} : {song_ids: songIds});
    if (!state.open || state.generation !== generation || epoch !== requestEpoch) return;
    const id = create ? data?.id : data?.playlist_id;
    if (!Number.isInteger(id) || id <= 0 || (!create && id !== destination.id) ||
        ![data.added_count, data.skipped_count, data.songs_count].every(value => Number.isInteger(value) && value >= 0) ||
        data.added_count + data.skipped_count !== songIds.length) {
      throw new Error('The server returned unexpected playlist data. Your selection is kept.');
    }
    songIds.forEach(sid => searchState.selectedSongs.delete(sid));
    updateSearchSelection();
    updatePlaylistSummaries(id, name, data.songs_count);
    closeManualPlaylistDialog(true);
    showPlaylistNotice(songIds.length ? `Added ${data.added_count} song${data.added_count === 1 ? '' : 's'} to ${name}${data.skipped_count ? ` (${data.skipped_count} already present)` : ''}.` : `Created ${name}. Use Add songs to build your playlist.`);
    refreshPlaylistData(id);
    if (create && origin === 'create' && navigation === navigationGeneration) openPlaylistDetail(id);
  } catch (error) {
    if (state.open && state.generation === generation) setManualPlaylistError(error.message || 'Unable to save. Your selection is kept; try again.');
  } finally {
    if (state.generation === generation) { state.pending = false; updateManualPlaylistControls(); }
  }
}

function initManualPlaylistEvents() {
  const dialog = document.getElementById('manual-playlist-dialog');
  if (!dialog || dialog._verseManualBound) return;
  dialog._verseManualBound = true;
  document.querySelectorAll('[data-create-manual-playlist]').forEach(button => {
    button.addEventListener('click', () => {
      document.getElementById('mobile-drawer-overlay')?.classList.remove('active');
      openManualPlaylistDialog('create');
    });
  });
  document.getElementById('btn-playlist-add-songs')?.addEventListener('click', () => {
    if (currentPlaylistData) showSearchOverlay('', currentPlaylistData.id);
  });
  document.getElementById('btn-close-playlist-dialog').addEventListener('click', () => closeManualPlaylistDialog());
  dialog.addEventListener('cancel', event => { event.preventDefault(); closeManualPlaylistDialog(); });
  dialog.addEventListener('keydown', event => {
    trapPlaylistFocus(event, dialog);
    if (event.key === 'Escape' && dialog.classList.contains('dialog-fallback')) { event.preventDefault(); closeManualPlaylistDialog(); }
  });
  document.getElementById('playlist-picker-search').addEventListener('input', renderPlaylistPicker);
  document.getElementById('playlist-picker-list').addEventListener('change', event => {
    if (event.target.name !== 'playlist-destination' || manualPlaylistState.pending) return;
    manualPlaylistState.destinationId = Number(event.target.value);
    const destination = manualPlaylistState.playlists.find(p => p.id === manualPlaylistState.destinationId);
    setText(document.getElementById('playlist-picker-destination'), destination ? `Destination: ${destination.name}` : 'Choose a playlist.');
    updateManualPlaylistControls();
  });
  document.getElementById('btn-retry-playlist-picker').addEventListener('click', () => loadPlaylistPicker({force: true}));
  document.getElementById('btn-picker-create').addEventListener('click', showManualPlaylistForm);
  document.getElementById('btn-cancel-playlist-create').addEventListener('click', () => {
    if (manualPlaylistState.origin === 'picker') showPlaylistPickerPanel();
    else closeManualPlaylistDialog();
  });
  document.getElementById('btn-confirm-playlist-add').addEventListener('click', () => submitManualPlaylist(false));
  document.getElementById('manual-playlist-form').addEventListener('submit', event => { event.preventDefault(); submitManualPlaylist(true); });
}

let currentGeneratedSongs = [];

async function handleGeneratePlaylist(e) {
  e.preventDefault();
  
  const strategy = elements.playlistStrategy.value;
  const seedType = elements.playlistSeedType.value;
  let seedValue = elements.playlistSeedValue.value.trim();
  let seedSongIds = [];
  const limit = parseInt(elements.playlistLimit.value) || 20;
  
  if (seedType === 'current song') {
    if (currentState.currentPlayingSong && currentState.currentPlayingSong.id !== undefined && currentState.currentPlayingSong.id !== null) {
      seedValue = String(currentState.currentPlayingSong.id);
      seedSongIds = [currentState.currentPlayingSong.id];
    }
  } else if (seedType === 'current queue') {
    const queueStart = currentState.queueIndex >= 0 && currentState.queueIndex < currentState.queue.length
      ? currentState.queueIndex
      : 0;
    // The queue may be a full library/playlist context.  A "current queue"
    // playlist must start with the active song, followed by upcoming songs;
    // otherwise every playback position shares the same first seed tracks.
    seedSongIds = (currentState.queue || [])
      .slice(queueStart)
      .map(song => song && song.id)
      .filter(id => id !== undefined && id !== null);
    if (seedSongIds.length === 0 && currentState.currentPlayingSong && currentState.currentPlayingSong.id !== undefined && currentState.currentPlayingSong.id !== null) {
      seedSongIds = [currentState.currentPlayingSong.id];
    }
    // Preserve the legacy scalar field while sending the complete queue context.
    seedValue = seedSongIds.length > 0 ? String(seedSongIds[0]) : '';
  }
  
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
        seed_song_ids: seedSongIds,
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
                ? `<img src="/api/v1/songs/${song.id}/artwork" loading="lazy" decoding="async" alt="cover" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
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
    
    refreshPlaylistData();
  } catch (err) {
    console.error(err);
    alert(`Failed to save playlist: ${err.message}`);
    elements.btnSavePlaylist.disabled = false;
  }
}

async function fetchAllPlaylists(options = {}) {
    let playlists = await requestJSON('playlists', '/api/v1/playlists?limit=100', isPlaylistList, options);
    if (!playlists) return null;
    for (let offset = 100; playlists.length === offset; offset += 100) {
      const page = await requestJSON('playlists:' + offset, '/api/v1/playlists?limit=100&offset=' + offset, isPlaylistList, options);
      if (!page) return null;
      playlists = playlists.concat(page);
      if (page.length < 100) break;
    }
    return playlists;
}

async function loadPlaylists(options = {}) {
  try {
    const playlists = await fetchAllPlaylists(options);
    if (!playlists) return;
    clearResourceError('playlists-mobile');
    if (!changedResource('playlists', playlists)) return;
    
    const emptyHtml = `
      <li style="font-size: 13px; color: var(--text-muted); padding: 8px; font-style: italic;">
        No playlists saved yet.
      </li>
    `;

    if (playlists.length === 0) {
      if (elements.sidebarPlaylists) elements.sidebarPlaylists.innerHTML = emptyHtml;
      const mobileDrawerPlaylists = document.getElementById('mobile-drawer-playlists');
      if (mobileDrawerPlaylists) mobileDrawerPlaylists.innerHTML = emptyHtml;
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
    
    if (elements.sidebarPlaylists) {
      elements.sidebarPlaylists.innerHTML = html;
      elements.sidebarPlaylists.querySelectorAll('.playlist-sidebar-item').forEach(item => {
        item.addEventListener('click', () => {
          const playlistId = parseInt(item.getAttribute('data-playlist-id'));
          openPlaylistDetail(playlistId);
        });
      });
    }

    const mobileDrawerPlaylists = document.getElementById('mobile-drawer-playlists');
    if (mobileDrawerPlaylists) {
      mobileDrawerPlaylists.innerHTML = html;
      mobileDrawerPlaylists.querySelectorAll('.playlist-sidebar-item').forEach(item => {
        item.addEventListener('click', () => {
          const playlistId = parseInt(item.getAttribute('data-playlist-id'));
          const mobileDrawerOverlay = document.getElementById('mobile-drawer-overlay');
          if (mobileDrawerOverlay) mobileDrawerOverlay.classList.remove('active');
          openPlaylistDetail(playlistId);
        });
      });
    }
  } catch (err) {
    const retry = () => loadPlaylists({force: true});
    const mobile = document.getElementById('mobile-drawer-playlists');
    if (!renderedResources.has('playlists')) {
      if (elements.sidebarPlaylists) elements.sidebarPlaylists.innerHTML = '';
      if (mobile) mobile.innerHTML = '';
    }
    showResourceError('playlists', elements.sidebarPlaylists, retry, err);
    showResourceError('playlists-mobile', mobile, retry, err);
  }
}

// ----------------------------------------------------
// DYNAMIC HOME PAGE SECTIONS (CONTINUE, RECENT, ADDED)
// ----------------------------------------------------
async function loadHomePageSections(options = {}) {
  await Promise.all([
    loadContinueListeningSection(options),
    loadRecentlyPlayedSection(options),
    loadRecentlyAddedSection(options),
  ]);
}

async function loadContinueListeningSection(options = {}) {
  const sectionEl = document.getElementById('continue-listening-section');
  const gridEl = document.getElementById('continue-listening-grid');
  if (!sectionEl || !gridEl) return;

  try {
    const sessions = await requestJSON('continue', '/api/v1/playlists/continue-listening?limit=4', d => Array.isArray(d) && d.every(s => Number.isInteger(s.playlist_id) && Number.isInteger(s.current_song_index) && Number.isInteger(s.song_count)), options);
    if (!sessions || !changedResource('continue', sessions)) return;

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
    sectionEl.style.display = 'block';
    showResourceError('continue', gridEl, () => loadContinueListeningSection({force: true}), err);
  }
}

async function loadRecentlyPlayedSection(options = {}) {
  const gridEl = document.getElementById('recently-played-grid');
  if (!gridEl) return;

  try {
    const playlists = await requestJSON('recent', '/api/v1/playlists?section=recently_played&limit=4', isPlaylistList, options);
    if (!playlists || !changedResource('recent', playlists)) return;

    if (playlists.length === 0) {
      gridEl.innerHTML = `<div style="color:var(--text-muted); font-size:13px; font-style:italic;">No recently played playlists.</div>`;
      return;
    }

    renderPlaylistGridCards(gridEl, playlists);
  } catch (err) {
    showResourceError('recent', gridEl, () => loadRecentlyPlayedSection({force: true}), err);
  }
}

async function loadRecentlyAddedSection(options = {}) {
  const gridEl = document.getElementById('recently-added-grid');
  if (!gridEl) return;

  try {
    const playlists = await requestJSON('added', '/api/v1/playlists?section=recently_added&limit=6', isPlaylistList, options);
    if (!playlists || !changedResource('added', playlists)) return;

    if (playlists.length === 0) {
      gridEl.innerHTML = `<div style="color:var(--text-muted); font-size:13px; font-style:italic;">No saved playlists yet.</div>`;
      return;
    }

    renderPlaylistGridCards(gridEl, playlists);
  } catch (err) {
    showResourceError('added', gridEl, () => loadRecentlyAddedSection({force: true}), err);
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
let playlistTableSearchQuery = '';
let playlistTableSortKey = 'position';

function formatTotalDuration(seconds) {
  if (isNaN(seconds) || seconds <= 0) return "0 min";
  const totalMins = Math.floor(seconds / 60);
  const hrs = Math.floor(totalMins / 60);
  const mins = totalMins % 60;
  if (hrs > 0) {
    return `${hrs} hr ${mins > 0 ? mins + ' min' : ''}`;
  }
  return `${mins} min`;
}

async function openPlaylistDetail(playlistId, options = {}) {
  if (currentState.activeTab === 'view-playlist-detail' && currentPlaylistData?.id === playlistId && !options.force) return;
  const generation = ++navigationGeneration;
  currentState.activeTab = 'view-playlist-detail';
  elements.navItems.forEach(n => n.classList.remove('active'));
  elements.views.forEach(v => v.classList.toggle('active', v.id === 'view-playlist-detail'));
  const table = document.getElementById('playlist-detail-songs-body');
  const detailButtons = ['btn-playlist-add-songs', 'btn-playlist-play-all', 'btn-playlist-shuffle', 'btn-playlist-delete', 'btn-playlist-top-more', 'btn-playlist-download', 'btn-playlist-favorite'];
  const back = document.getElementById('btn-playlist-back');
  if (back) back.onclick = () => elements.navHome.click();
  detailButtons.forEach(id => { const button = document.getElementById(id); if (button) button.disabled = true; });
  if (currentPlaylistData?.id !== playlistId) {
    currentPlaylistData = null;
    setText(document.getElementById('detail-playlist-title'), 'Loading playlist…');
    setText(document.getElementById('detail-playlist-desc'), '');
    if (table) table.innerHTML = '<tr><td colspan="8" class="playlist-pending">Loading tracks…</td></tr>';
  }
  try {
    const pl = await requestJSON('detail', `/api/v1/playlists/${playlistId}`, d => d && d.id === playlistId && typeof d.name === 'string' && isSongList(d.songs), options);
    if (!pl || generation !== navigationGeneration || currentState.activeTab !== 'view-playlist-detail') return;
    clearResourceError('detail');
    detailButtons.forEach(id => { const button = document.getElementById(id); if (button) button.disabled = false; });
    const preserveControls = options.preserveControls && currentPlaylistData?.id === pl.id;
    currentPlaylistData = pl;
    if (!preserveControls) {
      playlistTableSearchQuery = '';
      playlistTableSortKey = 'position';
    }

    // Reset Search & Sort UI controls
    const searchInput = document.getElementById('playlist-table-search');
    if (searchInput && !preserveControls) searchInput.value = '';
    const sortSelect = document.getElementById('playlist-table-sort');
    if (sortSelect && !preserveControls) sortSelect.value = 'position';

    // Switch view
    elements.navItems.forEach(n => n.classList.remove('active'));
    elements.views.forEach(v => {
      if (v.id === 'view-playlist-detail') v.classList.add('active');
      else v.classList.remove('active');
    });
    currentState.activeTab = 'view-playlist-detail';

    // Populate Hero Metadata
    const coverImg = document.getElementById('detail-playlist-cover');
    if (coverImg) coverImg.src = `/api/v1/playlists/${pl.id}/cover`;

    const titleEl = document.getElementById('detail-playlist-title');
    if (titleEl) titleEl.innerText = pl.name;

    const descEl = document.getElementById('detail-playlist-desc');
    if (descEl) descEl.innerText = pl.description || pl.prompt || "Curated mix for your library";

    const songCountEl = document.getElementById('detail-song-count');
    if (songCountEl) songCountEl.innerText = `${pl.songs_count} songs`;

    const totalDurEl = document.getElementById('detail-total-duration');
    if (totalDurEl) totalDurEl.innerText = formatTotalDuration(pl.total_duration);

    const createdEl = document.getElementById('detail-created-date');
    if (createdEl) {
      const d = new Date(pl.created_at);
      createdEl.innerText = `Created ${d.toLocaleDateString()}`;
    }

    // Creator Avatar & Name
    const creatorNameEl = document.getElementById('detail-creator-name');
    const creatorAvatarEl = document.getElementById('detail-creator-avatar');
    const isAi = pl.generated_by === 'AI' || pl.generated_by === 'ai';
    if (creatorNameEl) creatorNameEl.innerText = isAi ? "Verse AI" : "User";
    if (creatorAvatarEl) creatorAvatarEl.innerText = isAi ? "V" : "U";

    // Badges
    const badgeEl = document.getElementById('detail-playlist-badge');
    if (badgeEl) badgeEl.innerText = isAi ? "AI PLAYLIST" : "PUBLIC PLAYLIST";

    const stratBadgeEl = document.getElementById('detail-strategy-badge');
    if (stratBadgeEl) {
      if (pl.strategy) {
        stratBadgeEl.style.display = 'inline-block';
        stratBadgeEl.innerText = pl.strategy;
      } else {
        stratBadgeEl.style.display = 'none';
      }
    }

    // AI Meta Card
    const aiBox = document.getElementById('detail-ai-meta-box');
    if (aiBox) {
      if (isAi || pl.prompt) {
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

    // Wire Action Toolbar Buttons
    const playAllBtn = document.getElementById('btn-playlist-play-all');
    if (playAllBtn) {
      playAllBtn.disabled = pl.songs.length === 0;
      playAllBtn.onclick = () => playPlaylist(pl.id, 0);
    }

    const shuffleBtn = document.getElementById('btn-playlist-shuffle');
    if (shuffleBtn) {
      shuffleBtn.disabled = pl.songs.length === 0;
      shuffleBtn.onclick = () => playPlaylist(pl.id, 0, true);
    }

    const downloadBtn = document.getElementById('btn-playlist-download');
    if (downloadBtn) {
      downloadBtn.onclick = () => {
        alert(`Downloading all ${pl.songs_count} tracks from "${pl.name}"...`);
      };
    }

    const favoriteBtn = document.getElementById('btn-playlist-favorite');
    if (favoriteBtn) {
      favoriteBtn.onclick = () => {
        favoriteBtn.classList.toggle('liked');
        const isFav = favoriteBtn.classList.contains('liked');
        alert(isFav ? `Added "${pl.name}" to your Library favorites.` : `Removed "${pl.name}" from favorites.`);
      };
    }

    const deleteBtn = document.getElementById('btn-playlist-delete');
    const topMoreBtn = document.getElementById('btn-playlist-top-more');
    const handleDelete = async () => {
      if (confirm(`Are you sure you want to delete "${pl.name}"?`)) {
        try {
          const response = await fetch(`/api/v1/playlists/${pl.id}`, { method: 'DELETE' });
          if (!response.ok) throw new Error('Delete failed (HTTP ' + response.status + ').');
          refreshPlaylistData();
          elements.navHome.click();
        } catch (error) {
          showResourceError('detail', table.closest('table'), handleDelete, error);
        }
      }
    };
    if (deleteBtn) deleteBtn.onclick = handleDelete;
    if (topMoreBtn) topMoreBtn.onclick = handleDelete;

    const backBtn = document.getElementById('btn-playlist-back');
    if (backBtn) {
      backBtn.onclick = () => {
        elements.navHome.click();
      };
    }

    // Wire In-Playlist Table Search and Sorting
    if (searchInput) {
      searchInput.oninput = (e) => {
        playlistTableSearchQuery = e.target.value.toLowerCase().trim();
        renderPlaylistDetailTable(currentPlaylistData ? currentPlaylistData.songs : []);
      };
    }
    if (sortSelect) {
      sortSelect.onchange = (e) => {
        playlistTableSortKey = e.target.value;
        renderPlaylistDetailTable(currentPlaylistData ? currentPlaylistData.songs : []);
      };
    }
  } catch (err) {
    if (generation !== navigationGeneration) return;
    if (table && !currentPlaylistData) table.innerHTML = '';
    showResourceError('detail', table?.closest('table'), () => openPlaylistDetail(playlistId, {force: true}), err);
  }
}

function renderPlaylistDetailTable(songs) {
  const bodyEl = document.getElementById('playlist-detail-songs-body');
  if (!bodyEl) return;

  if (!songs || songs.length === 0) {
    bodyEl.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; padding: 32px; color: var(--text-muted);">
          This playlist has no songs. Use Add songs above to choose from your library.
        </td>
      </tr>
    `;
    return;
  }

  // Filter songs
  let filtered = songs;
  if (playlistTableSearchQuery) {
    filtered = songs.filter(s => {
      const title = (s.title || '').toLowerCase();
      const artist = (s.artist || '').toLowerCase();
      const album = (s.album || '').toLowerCase();
      return title.includes(playlistTableSearchQuery) ||
             artist.includes(playlistTableSearchQuery) ||
             album.includes(playlistTableSearchQuery);
    });
  }

  // Sort songs
  let sorted = [...filtered];
  if (playlistTableSortKey === 'title') {
    sorted.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
  } else if (playlistTableSortKey === 'artist') {
    sorted.sort((a, b) => (a.artist || '').localeCompare(b.artist || ''));
  } else if (playlistTableSortKey === 'album') {
    sorted.sort((a, b) => (a.album || '').localeCompare(b.album || ''));
  } else if (playlistTableSortKey === 'duration') {
    sorted.sort((a, b) => (a.duration || 0) - (b.duration || 0));
  } else if (playlistTableSortKey === 'date_added') {
    sorted.sort((a, b) => (a.date_added || '').localeCompare(b.date_added || ''));
  }

  if (sorted.length === 0) {
    bodyEl.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; padding: 24px; color: var(--text-muted);">
          No matching tracks found for "${escapeHtml(playlistTableSearchQuery)}".
        </td>
      </tr>
    `;
    return;
  }

  let html = '';
  const createdDateFallback = currentPlaylistData && currentPlaylistData.created_at
    ? new Date(currentPlaylistData.created_at).toLocaleDateString()
    : 'Recently';

  sorted.forEach((s, idx) => {
    const isPlaying = currentState.currentPlayingSong && currentState.currentPlayingSong.id === s.id;
    const isLiked = currentState.likedSongIds.has(s.id);
    const dateAddedStr = s.date_added || createdDateFallback;

    // Track position indicator
    let numCellContent = idx + 1;
    if (isPlaying) {
      if (currentState.isPlaying) {
        numCellContent = `<div class="playing-eq-bar"><span></span><span></span><span></span></div>`;
      } else {
        numCellContent = SVG_ICONS.play;
      }
    }

    html += `
      <tr class="song-table-row ${isPlaying ? 'active-row' : ''}" data-song-id="${s.id}" data-idx="${idx}" data-track-number="${idx + 1}">
        <td class="col-num">${numCellContent}</td>
        <td class="col-heart">
          <button class="btn-like-song ${isLiked ? 'liked' : ''}" data-song-id="${s.id}">
            ${isLiked ? SVG_ICONS.heartFilled : SVG_ICONS.heart}
          </button>
        </td>
        <td class="col-title">
          <div class="table-song-title-cell">
            <div class="table-song-art">
              ${s.artwork_available
                ? `<img src="/api/v1/songs/${s.id}/artwork" loading="lazy" decoding="async" alt="art">`
                : SVG_ICONS.music}
            </div>
            <div class="table-song-meta">
              <span class="table-song-title-text">${escapeHtml(s.title)}</span>
            </div>
          </div>
        </td>
        <td class="col-artist">${escapeHtml(s.artist)}</td>
        <td class="col-album">${escapeHtml(s.album)}</td>
        <td class="col-date-added">${escapeHtml(dateAddedStr)}</td>
        <td class="col-duration">${formatDuration(s.duration)}</td>
        <td class="col-options">
          <button class="btn-song-options">${SVG_ICONS.options}</button>
        </td>
      </tr>
    `;
  });
  bodyEl.innerHTML = html;

  bodyEl._verseSongs = sorted;
  if (!bodyEl._verseBound) {
    bodyEl._verseBound = true;
    bodyEl.addEventListener('click', event => {
      const row = event.target.closest('tr[data-song-id]');
      if (!row) return;
      const sid = Number(row.dataset.songId);
      if (event.target.closest('.btn-like-song')) { toggleLikeSong(sid); return; }
      if (event.target.closest('.btn-song-options')) return;
      const songs = currentPlaylistData?.songs || bodyEl._verseSongs;
      const song = songs.find(s => s.id === sid);
      if (!song) return;
      if (currentPlaylistData?.id) playPlaylist(currentPlaylistData.id, songs.findIndex(s => s.id === sid));
      else playSong(song, songs);
    });
  }
  updatePlayingRows();
}

// ----------------------------------------------------
// PLAYBACK SESSION ENGINE INTEGRATION
// ----------------------------------------------------
let playbackGeneration = 0;
async function playPlaylist(playlistId, startIndex = 0, shuffle = false) {
  const generation = ++playbackGeneration;
  try {
    const startResp = await fetch(`/api/v1/playlists/${playlistId}/play`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ song_index: startIndex, position: 0.0 })
    });

    if (!startResp.ok) throw new Error('Failed to start playlist session');
    const sessionData = await startResp.json();
    // Fetch song queue
    let songs = currentPlaylistData?.id === playlistId ? currentPlaylistData.songs
      : await requestJSON('play-queue', `/api/v1/playlists/${playlistId}/songs`, isSongList);
    if (!songs || generation !== playbackGeneration) return;
    currentState.activeSessionId = sessionData.session_id;
    currentState.activePlaylistId = playlistId;

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
  const generation = ++playbackGeneration;
  try {
    const resumeResp = await fetch(`/api/v1/playlists/${playlistId}/resume`, {
      method: 'POST'
    });
    if (!resumeResp.ok) throw new Error('Failed to resume playlist');
    const sessionData = await resumeResp.json();

    const songs = currentPlaylistData?.id === playlistId ? currentPlaylistData.songs
      : await requestJSON('play-queue', `/api/v1/playlists/${playlistId}/songs`, isSongList);
    if (!songs || generation !== playbackGeneration) return;
    currentState.activeSessionId = sessionData.session_id;
    currentState.activePlaylistId = playlistId;

    if (songs.length === 0) return;

    let targetIndex = sessionData.current_song_index || 0;
    if (targetIndex >= songs.length) targetIndex = 0;

    const playing = playSong(songs[targetIndex], songs);
    const trackGeneration = playbackGeneration;
    await playing;

    if (trackGeneration === playbackGeneration && elements.audio && sessionData.current_position > 0) {
      // Unlike interactive seeking, a saved resume offset may precede metadata
      // (e.g. play() was blocked). HTML audio retains this default start position.
      elements.audio.currentTime = sessionData.current_position;
      updateMediaPosition(true);
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

  const id = currentState.activeSessionId;
  const job = {url: `/api/v1/playlists/${currentState.activePlaylistId}/progress?session_id=${id}`,
    payload: {song_index: songIndex, position, completed}};
  const state = progressWrites.get(id) || {pending: null, running: false};
  progressWrites.set(id, state);
  state.pending = job;
  if (!state.running) flushProgress(id, state);
}

const progressWrites = new Map();
async function flushProgress(id, state) {
  state.running = true;
  try {
    while (state.pending) {
      const job = state.pending;
      state.pending = null;
      try {
        const response = await fetch(job.url, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(job.payload)});
        if (!response.ok) throw new Error('Progress update failed (HTTP ' + response.status + ').');
      } catch (error) { console.error('Progress sync failed:', error); }
    }
  } finally { state.running = false; progressWrites.delete(id); }
}

function initPlaylistEvents() {
  initManualPlaylistEvents();
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
// The system player uses the same persistent audio element and queue functions
// as the visible players. Every optional API is isolated from normal playback.
let mediaPositionReady = false;
let lastMediaPositionUpdate = null;

function getMediaSession() {
  return typeof navigator !== 'undefined' ? navigator.mediaSession : null;
}

function clearMediaPosition() {
  mediaPositionReady = false;
  lastMediaPositionUpdate = null;
  const session = getMediaSession();
  if (typeof session?.setPositionState === 'function') {
    try { session.setPositionState({}); } catch (_) { /* Optional on Safari. */ }
  }
}

function clearMediaSession() {
  cancelResource('media-metadata');
  clearMediaPosition();
  const session = getMediaSession();
  if (!session) return;
  try { session.metadata = null; } catch (_) { /* Unsupported metadata setter. */ }
  try { session.playbackState = 'none'; } catch (_) { /* Optional state setter. */ }
}

function publishMediaMetadata(song) {
  const session = getMediaSession();
  if (!session) return;
  // Clear first, including if this browser cannot construct the next metadata.
  try { session.metadata = null; } catch (_) { /* Optional metadata setter. */ }
  if (!song || typeof MediaMetadata !== 'function') return;
  try {
    const fallback = song.artwork_available === false;
    const url = new URL(fallback ? '/api/v1/artwork/default'
      : `/api/v1/songs/${song.id}/artwork?fallback=true`, window.location.href);
    // API images require a served page, not an unsupported file: media URL.
    const artwork = ['https:', 'http:'].includes(url.protocol)
      ? [fallback ? {src: url.href, sizes: '512x512', type: 'image/png'} : {src: url.href}] : [];
    session.metadata = new MediaMetadata({
      title: song.title || 'Unknown Title',
      artist: song.artist || 'Unknown Artist',
      album: song.album || '',
      // Originals have variable formats/sizes; only the fallback is known.
      artwork
    });
  } catch (error) { console.debug('System media metadata unavailable:', error); }
}

function publishNowPlaying(song) {
  cancelResource('media-metadata');
  publishMediaMetadata(song);
  // Some entry points (e.g. assistant previews) supply only id/title/artist.
  // Fill in missing tags without delaying play() or retaining old album/art.
  if (!getMediaSession() || typeof MediaMetadata !== 'function' ||
      ('album' in song && 'artwork_available' in song)) return;
  const generation = playbackGeneration;
  requestJSON('media-metadata', `/api/v1/songs/${song.id}`, data =>
    data?.id === song.id && typeof data.artwork_available === 'boolean' &&
    ['title', 'artist', 'album'].every(key => data[key] == null || typeof data[key] === 'string'))
    .then(data => {
      if (!data || generation !== playbackGeneration || currentState.currentPlayingSong?.id !== song.id) return;
      currentState.currentPlayingSong = {...song, ...data};
      publishMediaMetadata(currentState.currentPlayingSong);
      updatePlaybackUI();
    }).catch(error => console.debug('System media tag lookup failed:', error));
}

function updateMediaPosition(force = false) {
  const session = getMediaSession();
  const audio = elements.audio;
  if (!mediaPositionReady || !audio || !currentState.currentPlayingSong ||
      typeof session?.setPositionState !== 'function') return;
  const {duration, currentTime, playbackRate} = audio;
  if (!Number.isFinite(duration) || duration <= 0 || !Number.isFinite(currentTime) ||
      !Number.isFinite(playbackRate) || playbackRate <= 0) {
    try { session.setPositionState({}); } catch (_) { /* Optional method. */ }
    return;
  }
  const now = Date.now();
  if (!force && lastMediaPositionUpdate !== null && now - lastMediaPositionUpdate < 1000) return;
  lastMediaPositionUpdate = now;
  try {
    session.setPositionState({duration, playbackRate, position: Math.min(duration, Math.max(0, currentTime))});
  } catch (_) { /* Unsupported or temporarily unavailable; never interrupt audio. */ }
}

function synchronizeAudioState() {
  const audio = elements.audio;
  const song = currentState.currentPlayingSong;
  currentState.isPlaying = Boolean(song && audio && !audio.paused && !audio.ended && !audio.error);
  const session = getMediaSession();
  if (session) {
    try { session.playbackState = !song ? 'none' : currentState.isPlaying ? 'playing' : 'paused'; }
    catch (_) { /* Some implementations expose only part of Media Session. */ }
  }
  updatePlaybackUI();
  updatePlayingRows();
  updateMediaPosition(true);
}

async function playCurrentAudio() {
  const audio = elements.audio;
  if (!audio || !currentState.currentPlayingSong) return false;
  const generation = playbackGeneration;
  try {
    await audio.play();
    return generation === playbackGeneration;
  } catch (error) {
    if (generation === playbackGeneration) {
      console.error('Autoplay prevented or audio load failed:', error);
      synchronizeAudioState();
    }
    return false;
  }
}

function pauseCurrentAudio() {
  elements.audio?.pause();
}

function seekPlayback(position, fast = false) {
  const audio = elements.audio;
  if (!audio || !currentState.currentPlayingSong || !Number.isFinite(position) ||
      !Number.isFinite(audio.duration) || audio.duration <= 0) return;
  const target = Math.min(audio.duration, Math.max(0, position));
  try {
    if (fast && typeof audio.fastSeek === 'function') audio.fastSeek(target);
    else audio.currentTime = target;
  } catch (_) {
    try { audio.currentTime = target; } catch (_) { return; }
  }
  updateMediaPosition(true);
  syncSessionProgress(false);
}

function initMediaSession() {
  const session = getMediaSession();
  if (typeof session?.setActionHandler !== 'function') return;
  const offset = details => Number.isFinite(details?.seekOffset) && details.seekOffset > 0 ? details.seekOffset : 10;
  const actions = {
    play: playCurrentAudio,
    pause: pauseCurrentAudio,
    previoustrack: playPrevSong,
    nexttrack: playNextSong,
    seekbackward: details => seekPlayback(elements.audio.currentTime - offset(details)),
    seekforward: details => seekPlayback(elements.audio.currentTime + offset(details)),
    seekto: details => seekPlayback(details?.seekTime, Boolean(details?.fastSeek))
  };
  for (const [action, handler] of Object.entries(actions)) {
    try { session.setActionHandler(action, handler); }
    catch (_) { /* Each action is independently optional, notably seeking. */ }
  }
}

async function playSong(song, queueContext = null) {
  if (!song) return;

  const audio = elements.audio;
  if (!audio) return;
  const generation = ++playbackGeneration;

  currentState.currentPlayingSong = song;
  if (queueContext && Array.isArray(queueContext)) {
    currentState.queue = queueContext;
    currentState.queueIndex = queueContext.findIndex(s => s.id === song.id);
  } else if (!currentState.queue.some(s => s.id === song.id)) {
    currentState.queue.push(song);
    currentState.queueIndex = currentState.queue.length - 1;
  }

  audio.src = `/api/v1/songs/${song.id}/stream`;
  clearMediaPosition();
  publishNowPlaying(song);
  // Call synchronously in the originating user gesture; do not await tag fetches.
  const playing = playCurrentAudio();
  updatePlaybackUI();
  updateRightSidebarNowPlaying(song);
  renderQueueList();
  fetchRecommendationsForSong(song.id);
  updatePlayingRows();
  await playing;
  if (generation !== playbackGeneration) return;

  try {
    fetch('/api/v1/history/play', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ song_id: song.id, duration: song.duration || 0.0 })
    }).catch(error => console.error('History request failed:', error));
  } catch (err) {
    console.error("Failed sending play history:", err);
  }

}

function togglePlayPause() {
  const audio = elements.audio;
  if (!audio || !currentState.currentPlayingSong) return;

  if (audio.paused) {
    return playCurrentAudio();
  } else {
    pauseCurrentAudio();
  }
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
      }).catch(error => console.error('Skip history request failed:', error));
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
    seekPlayback(0);
    return;
  }

  const prevIdx = currentState.queueIndex - 1;
  if (prevIdx >= 0 && prevIdx < currentState.queue.length) {
    playSong(currentState.queue[prevIdx], currentState.queue);
  }
}

const pendingLikes = new Set();
async function toggleLikeSong(songId) {
  if (pendingLikes.has(songId)) return;
  const previous = currentState.likedSongIds.has(songId);
  pendingLikes.add(songId);
  if (previous) currentState.likedSongIds.delete(songId);
  else currentState.likedSongIds.add(songId);
  updateLikeButtons(songId);
  try {
    const response = await fetch('/api/v1/history/like', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({song_id: songId, liked: !previous})
    });
    if (!response.ok) throw new Error('Unable to save like (HTTP ' + response.status + ').');
    clearResourceError('like');
  } catch (error) {
    if (previous) currentState.likedSongIds.add(songId);
    else currentState.likedSongIds.delete(songId);
    updateLikeButtons(songId);
    showResourceError('like', elements.songsTableBody?.closest('table'), () => toggleLikeSong(songId), error);
  } finally { pendingLikes.delete(songId); }
}

function updateLoopUI() {
  const isLooping = Boolean(currentState.isRepeat || currentState.isLooping);
  if (elements.barBtnRepeat) {
    elements.barBtnRepeat.classList.toggle('active', isLooping);
    elements.barBtnRepeat.classList.toggle('active-state', isLooping);
  }
  const mobileFullBtnRepeat = document.getElementById('mobile-full-btn-repeat');
  if (mobileFullBtnRepeat) {
    mobileFullBtnRepeat.classList.toggle('active', isLooping);
    mobileFullBtnRepeat.classList.toggle('active-state', isLooping);
  }
}

function updatePlaybackUI() {
  updateLoopUI();
  const song = currentState.currentPlayingSong;
  if (!song) return;

  // Desktop player update
  if (elements.barTitle) setText(elements.barTitle, song.title);
  if (elements.barArtist) setText(elements.barArtist, song.artist);

  if (elements.barMiniArt) {
    updateSongArtwork(elements.barMiniArt, song);
  }

  if (elements.barBtnPlay) {
    elements.barBtnPlay.disabled = false;
    setIcon(elements.barBtnPlay, currentState.isPlaying, currentState.isPlaying ? SVG_ICONS.pause : SVG_ICONS.play);
  }

  if (elements.barBtnPrev) elements.barBtnPrev.disabled = currentState.queueIndex <= 0;
  if (elements.barBtnNext) elements.barBtnNext.disabled = currentState.queueIndex >= currentState.queue.length - 1;
  if (elements.barProgressSlider) elements.barProgressSlider.disabled = false;
  if (elements.barLikeBtn) {
    elements.barLikeBtn.disabled = false;
    const isLiked = currentState.likedSongIds.has(song.id);
    setIcon(elements.barLikeBtn, isLiked, isLiked ? SVG_ICONS.heartFilled : SVG_ICONS.heart);
  }

  // --- MOBILE MINI PLAYER UPDATE ---
  const mobileMiniTitle = document.getElementById('mobile-mini-title');
  const mobileMiniArtist = document.getElementById('mobile-mini-artist');
  const mobileMiniArt = document.getElementById('mobile-mini-art');
  const mobileMiniBtnPlay = document.getElementById('mobile-mini-btn-play');

  if (mobileMiniTitle) setText(mobileMiniTitle, song.title);
  if (mobileMiniArtist) setText(mobileMiniArtist, song.artist);
  if (mobileMiniArt) {
    updateSongArtwork(mobileMiniArt, song);
  }
  if (mobileMiniBtnPlay) {
    setIcon(mobileMiniBtnPlay, currentState.isPlaying, currentState.isPlaying ? SVG_ICONS.pause : SVG_ICONS.play);
  }

  // --- FULL MOBILE PLAYER UPDATE ---
  const mobileFullTitle = document.getElementById('mobile-full-title');
  const mobileFullArtist = document.getElementById('mobile-full-artist');
  const mobileFullArt = document.getElementById('mobile-full-art');
  const mobileFullBtnPlay = document.getElementById('mobile-full-btn-play');
  const mobileFullLikeBtn = document.getElementById('mobile-full-like-btn');
  const mobileFullBtnPrev = document.getElementById('mobile-full-btn-prev');
  const mobileFullBtnNext = document.getElementById('mobile-full-btn-next');

  if (mobileFullTitle) setText(mobileFullTitle, song.title);
  if (mobileFullArtist) setText(mobileFullArtist, song.artist);
  if (mobileFullArt) {
    updateSongArtwork(mobileFullArt, song);
  }
  if (mobileFullBtnPlay) {
    setIcon(mobileFullBtnPlay, currentState.isPlaying, currentState.isPlaying ? SVG_ICONS.pause : SVG_ICONS.play);
  }
  if (mobileFullLikeBtn) {
    const isLiked = currentState.likedSongIds.has(song.id);
    setIcon(mobileFullLikeBtn, isLiked, isLiked ? SVG_ICONS.heartFilled : SVG_ICONS.heart);
  }
  if (mobileFullBtnPrev) mobileFullBtnPrev.disabled = currentState.queueIndex <= 0;
  if (mobileFullBtnNext) mobileFullBtnNext.disabled = currentState.queueIndex >= currentState.queue.length - 1;
}

function updateRightSidebarNowPlaying(song) {
  const npCoverArt = document.getElementById('np-cover-art');
  const npTitle = document.getElementById('np-title');
  const npArtist = document.getElementById('np-artist');
  const npAlbum = document.getElementById('np-album');
  const npGenre = document.getElementById('np-genre');

  if (npTitle) setText(npTitle, song.title);
  if (npArtist) setText(npArtist, song.artist);
  if (npAlbum) setText(npAlbum, song.album || "Unknown Album");
  if (npGenre) setText(npGenre, song.genre || "Music");

  if (npCoverArt) {
    updateSongArtwork(npCoverArt, song);
  }
}

async function fetchRecommendationsForSong(songId) {
  const recList = document.getElementById('np-recommendation-list');
  if (!recList) return;

  try {
    const songs = await requestJSON('recommendations', `/api/v1/recommend?song_id=${songId}&limit=5`, isSongList);
    if (!songs || currentState.currentPlayingSong?.id !== songId) return;
    clearResourceError('recommendations');

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
              ? `<img src="/api/v1/songs/${s.id}/artwork" loading="lazy" decoding="async" alt="art">`
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
    showResourceError('recommendations', recList, () => fetchRecommendationsForSong(songId), err);
  }
}

const queueViews = new Map();
function renderQueueList() {
  const mobile = window.matchMedia ? window.matchMedia('(max-width: 767px)').matches : false;
  const id = mobile ? 'mobile-full-queue-list' : 'np-queue-list';
  if (mobile && !document.getElementById('mobile-full-player')?.classList.contains('active')) return;
  const list = document.getElementById(id);
  if (!list) return;
  let view = queueViews.get(id);
  if (!view) { view = {offset: 0, signature: ''}; queueViews.set(id, view); }
  if (view.queue !== currentState.queue || view.index !== currentState.queueIndex) view.offset = 0;
  view.queue = currentState.queue;
  view.index = currentState.queueIndex;
  const start = currentState.queueIndex + 1 + view.offset;
  const end = Math.min(start + 40, currentState.queue.length);
  const songs = currentState.queue.slice(start, end);
  const signature = start + ':' + currentState.queue.length + ':' + songs.map(s => s.id).join(',');
  if (view.signature === signature) return;
  view.signature = signature;
  // Reconcile visible entries rather than destroy rows still in the next window.
  const existing = new Map([...list.querySelectorAll('[data-queue-idx]')].map(el => [el.dataset.queueIdx, el]));
  const fragment = document.createDocumentFragment();
  songs.forEach((song, i) => {
    const idx = start + i;
    let row = existing.get(String(idx));
    if (!row || row.dataset.songId !== String(song.id)) {
      row = document.createElement('li');
      row.className = 'sidebar-track-item';
      row.dataset.queueIdx = idx;
      row.dataset.songId = song.id;
      row.innerHTML = `<div class="table-song-art" style="width:36px;height:36px;">${song.artwork_available ? `<img src="/api/v1/songs/${song.id}/artwork" loading="lazy" decoding="async" alt="art">` : SVG_ICONS.music}</div><div class="sidebar-track-meta"><div class="sidebar-track-title">${escapeHtml(song.title)}</div><div class="sidebar-track-artist">${escapeHtml(song.artist)}</div></div>`;
    }
    fragment.append(row);
  });
  if (!songs.length) {
    const empty = document.createElement('li');
    empty.className = 'queue-empty-item'; empty.textContent = 'Queue is empty'; fragment.append(empty);
  }
  if (view.offset > 0 || end < currentState.queue.length) {
    const controls = document.createElement('li');
    controls.className = 'queue-pagination';
    controls.innerHTML = `<button data-queue-page="-1" ${view.offset === 0 ? 'disabled' : ''}>Previous</button><span>${start + 1}–${end} of ${currentState.queue.length}</span><button data-queue-page="1" ${end === currentState.queue.length ? 'disabled' : ''}>Next</button>`;
    fragment.append(controls);
  }
  list.replaceChildren(fragment);
  if (!list._verseQueueBound) {
    list._verseQueueBound = true;
    list.addEventListener('click', event => {
      const page = event.target.closest('[data-queue-page]');
      if (page && !page.disabled) { view.offset = Math.max(0, view.offset + Number(page.dataset.queuePage) * 40); view.signature = ''; renderQueueList(); return; }
      const row = event.target.closest('[data-queue-idx]');
      const song = row && currentState.queue[Number(row.dataset.queueIdx)];
      if (song) playSong(song, currentState.queue);
    });
  }
}

function initAudioPlayerEvents() {
  const audio = elements.audio;
  if (!audio || audio._versePlayerBound) return;
  audio._versePlayerBound = true;
  initMediaSession();
  ['play', 'playing', 'pause', 'ended', 'error'].forEach(event => {
    audio.addEventListener(event, synchronizeAudioState);
  });
  audio.addEventListener('emptied', () => { clearMediaPosition(); synchronizeAudioState(); });
  audio.addEventListener('seeked', () => updateMediaPosition(true));
  audio.addEventListener('ratechange', () => updateMediaPosition(true));
  audio.addEventListener('durationchange', () => updateMediaPosition(true));

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
      updateLoopUI();
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
        seekPlayback(targetTime);
      }
    });
  }

  if (elements.barVolumeSlider) {
    elements.barVolumeSlider.addEventListener('input', (e) => {
      audio.volume = parseFloat(e.target.value) / 100;
    });
  }

  audio.addEventListener('timeupdate', () => {
    updateMediaPosition();
    if (!audio.duration) return;
    const pct = (audio.currentTime / audio.duration) * 100;
    if (elements.barProgressSlider) elements.barProgressSlider.value = pct;
    if (elements.barTimeCurrent) elements.barTimeCurrent.innerText = formatDuration(audio.currentTime);

    // Sync Mobile Mini Player Progress Bar
    const mobileMiniProgress = document.getElementById('mobile-mini-progress-bar');
    if (mobileMiniProgress) mobileMiniProgress.style.transform = `scaleX(${pct / 100})`;

    // Sync Full Mobile Player Progress Slider & Time
    const mobileFullProgressSlider = document.getElementById('mobile-full-progress-slider');
    const mobileFullTimeCurrent = document.getElementById('mobile-full-time-current');
    if (mobileFullProgressSlider) mobileFullProgressSlider.value = pct;
    if (mobileFullTimeCurrent) mobileFullTimeCurrent.innerText = formatDuration(audio.currentTime);

    syncSessionProgress(false);
  });

  audio.addEventListener('loadedmetadata', () => {
    mediaPositionReady = true;
    updateMediaPosition(true);
    const totalStr = formatDuration(audio.duration);
    if (elements.barTimeTotal) elements.barTimeTotal.innerText = totalStr;
    const mobileFullTimeTotal = document.getElementById('mobile-full-time-total');
    if (mobileFullTimeTotal) mobileFullTimeTotal.innerText = totalStr;
  });

  audio.addEventListener('ended', () => {
    syncSessionProgress(true);
    if ((currentState.isRepeat || currentState.isLooping) && currentState.currentPlayingSong) {
      seekPlayback(0);
      playCurrentAudio();
    } else {
      playNextSong();
    }
  });

  updateLoopUI();
  window.addEventListener('resize', renderQueueList);
}

// ==========================================
// 6.5 PANEL RESIZING LOGIC
// ==========================================
function initResizers() {
  [['resizer-left', '.sidebar-left', false, 180, 450],
   ['resizer-right', '.sidebar-right', true, 240, 500]].forEach(([id, selector, right, min, max]) => {
    const handle = document.getElementById(id);
    const sidebar = document.querySelector(selector);
    if (!handle || !sidebar || handle._verseResizeBound) return;
    handle._verseResizeBound = true;
    let frame = 0, width = 0;
    const apply = () => { frame = 0; sidebar.style.width = width + 'px'; };
    const move = event => {
      width = Math.min(Math.max(right ? window.innerWidth - event.clientX : event.clientX, min), max);
      if (!frame) frame = requestAnimationFrame(apply);
    };
    const stop = () => {
      handle.classList.remove('resizing');
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', stop);
      window.removeEventListener('blur', stop);
    };
    handle.addEventListener('mousedown', event => {
      event.preventDefault(); handle.classList.add('resizing');
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', stop);
      window.addEventListener('blur', stop);
    });
  });
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
    refreshPlaylistData();
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
      ? `<img src="/api/v1/songs/${playlist.songs[0].id}/artwork" loading="lazy" decoding="async" alt="art">`
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

  // On mobile screen width (< 768), show mobile assistant drawer modal
  if (window.innerWidth < 768) {
    const mobileOverlay = document.getElementById('mobile-assistant-drawer-overlay');
    const mobileContent = document.getElementById('mobile-assistant-drawer-content');
    if (mobileOverlay && mobileContent && assistantSidebar) {
      mobileContent.innerHTML = assistantSidebar.innerHTML;
      mobileOverlay.classList.add('active');

      const mBtnPlayAll = mobileContent.querySelector('#btn-assistant-play-all');
      if (mBtnPlayAll) {
        mBtnPlayAll.onclick = () => {
          if (playlist.songs && playlist.songs.length > 0) {
            playSong(playlist.songs[0], playlist.songs);
          }
        };
      }
      const mBtnSave = mobileContent.querySelector('#btn-save-assistant-playlist');
      if (mBtnSave) {
        mBtnSave.onclick = () => savePlaylistPreview(playlist, mBtnSave);
      }
      const mBtnRegen = mobileContent.querySelector('#btn-sidebar-regen');
      if (mBtnRegen) {
        mBtnRegen.onclick = () => {
          mobileOverlay.classList.remove('active');
          sendAssistantPrompt("Regenerate playlist preview");
        };
      }
      mobileContent.querySelectorAll('tr[data-song-id]').forEach(r => {
        r.addEventListener('click', () => {
          const id = parseInt(r.getAttribute('data-song-id'));
          const song = playlist.songs.find(s => s.id === id);
          if (song) playSong(song, playlist.songs);
        });
      });
    }
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
          👋 Hi! I'm your Verse Music Assistant. Tell me what mood, genre, or vibe you're looking for, or try one of the suggestions above!
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
                ? `<img src="/api/v1/songs/${p.songs[0].id}/artwork" loading="lazy" decoding="async" alt="art">`
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
// 8. MOBILE INTERACTION & MODALS CONTROLLER
// ==========================================
function initMobileEvents() {
  // Mobile Search Header Button
  const mobileBtnSearch = document.getElementById('mobile-btn-search');
  if (mobileBtnSearch) {
    mobileBtnSearch.addEventListener('click', () => showSearchOverlay());
  }

  // Mobile Drawer Toggles
  const mobileBtnDrawer = document.getElementById('mobile-btn-drawer');
  const mobileNavMenu = document.getElementById('mobile-nav-menu');
  const mobileDrawerOverlay = document.getElementById('mobile-drawer-overlay');
  const mobileDrawerClose = document.getElementById('mobile-drawer-close');

  function openMobileDrawer() {
    if (mobileDrawerOverlay) mobileDrawerOverlay.classList.add('active');
  }
  function closeMobileDrawer() {
    if (mobileDrawerOverlay) mobileDrawerOverlay.classList.remove('active');
  }

  if (mobileBtnDrawer) mobileBtnDrawer.addEventListener('click', openMobileDrawer);
  if (mobileNavMenu) mobileNavMenu.addEventListener('click', openMobileDrawer);
  if (mobileDrawerClose) mobileDrawerClose.addEventListener('click', closeMobileDrawer);
  if (mobileDrawerOverlay) {
    mobileDrawerOverlay.addEventListener('click', (e) => {
      if (e.target === mobileDrawerOverlay) closeMobileDrawer();
    });
  }

  // Mobile Drawer Navigation Links
  const mobileLibFavorites = document.getElementById('mobile-lib-favorites');
  const mobileLibRecent = document.getElementById('mobile-lib-recent');
  const mobileLibDownloads = document.getElementById('mobile-lib-downloads');
  const mobileBtnLogout = document.getElementById('mobile-btn-logout');

  if (mobileLibFavorites) {
    mobileLibFavorites.addEventListener('click', () => {
      closeMobileDrawer();
      const navHome = document.getElementById('nav-home');
      if (navHome) navHome.click();
    });
  }
  if (mobileLibRecent) {
    mobileLibRecent.addEventListener('click', () => {
      closeMobileDrawer();
      const navHome = document.getElementById('nav-home');
      if (navHome) navHome.click();
    });
  }
  if (mobileLibDownloads) {
    mobileLibDownloads.addEventListener('click', () => {
      closeMobileDrawer();
      const navHome = document.getElementById('nav-home');
      if (navHome) navHome.click();
    });
  }
  if (mobileBtnLogout) {
    mobileBtnLogout.addEventListener('click', () => {
      closeMobileDrawer();
      handleLogout();
    });
  }

  // Mobile Mini Player -> Expand Full Player
  const miniTrigger = document.getElementById('mobile-mini-player-trigger');
  const mobileFullPlayer = document.getElementById('mobile-full-player');
  const mobilePlayerClose = document.getElementById('mobile-player-close');

  if (miniTrigger && mobileFullPlayer) {
    miniTrigger.addEventListener('click', (e) => {
      if (e.target.closest('.mini-player-btn')) return;
      mobileFullPlayer.classList.add('active');
      renderQueueList();
    });
  }
  if (mobilePlayerClose && mobileFullPlayer) {
    mobilePlayerClose.addEventListener('click', () => {
      mobileFullPlayer.classList.remove('active');
    });
  }

  // Mobile Mini Player Controls
  const mobileMiniBtnPlay = document.getElementById('mobile-mini-btn-play');
  const mobileMiniBtnNext = document.getElementById('mobile-mini-btn-next');
  if (mobileMiniBtnPlay) mobileMiniBtnPlay.addEventListener('click', togglePlayPause);
  if (mobileMiniBtnNext) mobileMiniBtnNext.addEventListener('click', playNextSong);

  // Mobile Full Player Controls
  const mobileFullBtnPlay = document.getElementById('mobile-full-btn-play');
  const mobileFullBtnNext = document.getElementById('mobile-full-btn-next');
  const mobileFullBtnPrev = document.getElementById('mobile-full-btn-prev');
  const mobileFullBtnShuffle = document.getElementById('mobile-full-btn-shuffle');
  const mobileFullBtnRepeat = document.getElementById('mobile-full-btn-repeat');
  const mobileFullLikeBtn = document.getElementById('mobile-full-like-btn');
  const mobileFullProgressSlider = document.getElementById('mobile-full-progress-slider');
  const mobileFullVolumeSlider = document.getElementById('mobile-full-volume-slider');
  const mobileFullBtnVolume = document.getElementById('mobile-full-btn-volume');

  if (mobileFullBtnPlay) mobileFullBtnPlay.addEventListener('click', togglePlayPause);
  if (mobileFullBtnNext) mobileFullBtnNext.addEventListener('click', playNextSong);
  if (mobileFullBtnPrev) mobileFullBtnPrev.addEventListener('click', playPrevSong);

  if (mobileFullLikeBtn) {
    mobileFullLikeBtn.addEventListener('click', () => {
      if (currentState.currentPlayingSong) {
        toggleLikeSong(currentState.currentPlayingSong.id);
      }
    });
  }
  if (mobileFullBtnShuffle) {
    mobileFullBtnShuffle.addEventListener('click', () => {
      currentState.isShuffle = !currentState.isShuffle;
      mobileFullBtnShuffle.classList.toggle('active-state', currentState.isShuffle);
    });
  }
  if (mobileFullBtnRepeat) {
    mobileFullBtnRepeat.addEventListener('click', () => {
      currentState.isRepeat = !currentState.isRepeat;
      updateLoopUI();
    });
  }

  if (mobileFullBtnVolume) {
    mobileFullBtnVolume.addEventListener('click', () => {
      const audio = elements.audio;
      if (!audio) return;
      if (audio.volume > 0) {
        audio.dataset.prevVolume = audio.volume;
        audio.volume = 0;
        if (mobileFullVolumeSlider) mobileFullVolumeSlider.value = 0;
      } else {
        const prev = parseFloat(audio.dataset.prevVolume || '0.7');
        audio.volume = prev;
        if (mobileFullVolumeSlider) mobileFullVolumeSlider.value = prev * 100;
      }
    });
  }

  if (mobileFullProgressSlider) {
    mobileFullProgressSlider.addEventListener('input', (e) => {
      const audio = elements.audio;
      if (audio && audio.duration) {
        seekPlayback((parseFloat(e.target.value) / 100) * audio.duration);
      }
    });
  }

  if (mobileFullVolumeSlider) {
    mobileFullVolumeSlider.addEventListener('input', (e) => {
      const audio = elements.audio;
      if (audio) audio.volume = parseFloat(e.target.value) / 100;
    });
  }

  // Mobile Assistant Drawer Close
  const btnCloseMobileAssistantDrawer = document.getElementById('btn-close-mobile-assistant-drawer');
  const mobileAssistantDrawerOverlay = document.getElementById('mobile-assistant-drawer-overlay');
  if (btnCloseMobileAssistantDrawer && mobileAssistantDrawerOverlay) {
    btnCloseMobileAssistantDrawer.addEventListener('click', () => {
      mobileAssistantDrawerOverlay.classList.remove('active');
    });
  }
  if (mobileAssistantDrawerOverlay) {
    mobileAssistantDrawerOverlay.addEventListener('click', (e) => {
      if (e.target === mobileAssistantDrawerOverlay) {
        mobileAssistantDrawerOverlay.classList.remove('active');
      }
    });
  }
}

// ==========================================
// 9. BOOTSTRAP INITIALIZATION
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
  console.log("Verse Web interface initialized.");
  initAuthEvents();
  initNavigation();
  initPagination();
  initSearchEvents();
  initPlaylistEvents();
  initAssistantEvents();
  initAudioPlayerEvents();
  initResizers();
  initMobileEvents();

  bootstrapAuthentication();
});

// Dynamic Loader Spin Animation Styles
const styleSheet = document.createElement("style");
styleSheet.innerText = `
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
`;
document.head.appendChild(styleSheet);
