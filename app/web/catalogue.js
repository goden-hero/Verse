// Catalogue browsing is deliberately independent of local-library bulk selection.
const catalogueState = {open:false, query:'', generation:0, timer:null, results:[], nodes:new Map(), index:-1, returnFocus:null};
const selectedSongState = {open:false, generation:0, track:null, data:null, loading:false, error:'', returnFocus:null, scrollTop:0};
const catalogueEl = id => document.getElementById(id);

function showSearchOverlay(initial = '') {
  if (catalogueState.open) return;
  hideLibrarySelection();
  catalogueState.open = true; catalogueState.returnFocus = document.activeElement;
  const overlay = catalogueEl('catalogue-search-overlay');
  overlay.inert = false; overlay.classList.add('active');
  const input = catalogueEl('catalogue-search-input');
  if (initial) { input.value = initial; scheduleCatalogueSearch(initial); }
  input.focus({preventScroll:true});
}
function hideSearchOverlay() {
  if (!catalogueState.open && !selectedSongState.open) return;
  if (selectedSongState.open) closeSelectedSongPanel();
  catalogueState.open = false; catalogueState.generation++;
  clearTimeout(catalogueState.timer); cancelResource('catalogue-search');
  const overlay = catalogueEl('catalogue-search-overlay');
  if (overlay) { overlay.classList.remove('active'); overlay.inert = true; }
  catalogueState.returnFocus?.focus({preventScroll:true});
}
function resetCatalogueUI() {
  hideSearchOverlay(); catalogueState.query = ''; catalogueState.results = []; catalogueState.nodes.clear();
  const input = catalogueEl('catalogue-search-input'); if (input) input.value = '';
  catalogueEl('catalogue-search-results')?.replaceChildren();
  selectedSongState.track = null; selectedSongState.data = null;
}
function catalogueLoading(loading, message) {
  catalogueEl('catalogue-search-results').setAttribute('aria-busy', String(loading));
  catalogueEl('catalogue-search-status').classList.toggle('loading', loading);
  setText(catalogueEl('catalogue-search-status'), message);
}
function scheduleCatalogueSearch(query) {
  clearTimeout(catalogueState.timer); catalogueState.generation++; cancelResource('catalogue-search');
  catalogueState.query = query.trim(); catalogueEl('btn-retry-catalogue').hidden = true;
  if (catalogueState.query.length < 2) {
    catalogueState.results = []; renderCatalogueResults();
    catalogueLoading(false, catalogueState.query ? 'Keep typing to search.' : 'Search for a song or artist.'); return;
  }
  catalogueLoading(true, 'Searching…');
  catalogueState.timer = setTimeout(() => searchCatalogue(catalogueState.query), 450);
}
async function searchCatalogue(query) {
  const generation = catalogueState.generation;
  catalogueEl('btn-retry-catalogue').hidden = true;
  catalogueLoading(true, 'Searching…');
  try {
    const data = await requestJSON('catalogue-search', `/api/v1/search/external?q=${encodeURIComponent(query)}`,
      data => data?.provider === 'musicbrainz' && Array.isArray(data.results) && data.results.every(t => isExternalTrack(t) && t.provider === 'musicbrainz'));
    if (!data || !catalogueState.open || generation !== catalogueState.generation) return;
    catalogueState.results = [...new Map(data.results.map(t => [t.recording_id,t])).values()];
    discoveryState.canRequest = data.can_request === true;
    renderCatalogueResults();
    catalogueLoading(false, data.results.length ? '' : 'No recordings found. Try a song title or artist.');
  } catch (error) {
    if (!catalogueState.open || generation !== catalogueState.generation) return;
    catalogueLoading(false, error.message || 'Search is unavailable.'); catalogueEl('btn-retry-catalogue').hidden = false;
  }
}
function renderCatalogueResults() {
  const list = catalogueEl('catalogue-search-results'), keys = new Set(catalogueState.results.map(t => t.recording_id));
  catalogueState.nodes.forEach((node,key) => { if (!keys.has(key)) { node.remove(); catalogueState.nodes.delete(key); } });
  catalogueState.index = -1;
  catalogueEl('catalogue-search-input').removeAttribute('aria-activedescendant');
  catalogueState.results.forEach((track,index) => {
    let row = catalogueState.nodes.get(track.recording_id);
    if (!row) {
      row = document.createElement('div'); row.className = 'catalogue-result'; row.setAttribute('role','option'); row.tabIndex = -1;
      row.id = 'recording-' + track.recording_id; row.dataset.recordingId = track.recording_id;
      const art = track.artwork_url?.startsWith('https://')
        ? `<img src="${escapeHtml(track.artwork_url)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.hidden=true">` : '';
      row.innerHTML = `<div class="catalogue-art">${SVG_ICONS.music}${art}</div><div class="catalogue-result-meta"><div class="catalogue-title" title="${escapeHtml(track.title)}">${escapeHtml(track.title)}</div><div class="catalogue-artist" title="${escapeHtml(track.artist)}">${escapeHtml(track.artist)}</div></div>${track.duration > 0 ? `<span class="catalogue-duration">${formatDuration(track.duration)}</span>` : ''}`;
      catalogueState.nodes.set(track.recording_id,row);
    }
    row.dataset.index = index; row.setAttribute('aria-selected','false'); row.classList.remove('highlighted');
    if (list.children[index] !== row) list.insertBefore(row,list.children[index] || null);
  });
}
async function openSelectedSong(track, returnFocus = document.activeElement) {
  if (!track) return;
  // Freeze the list under the panel, including a transport that ignores abort.
  catalogueState.generation++; clearTimeout(catalogueState.timer); cancelResource('catalogue-search'); catalogueLoading(false,'');
  Object.assign(selectedSongState, {open:true, track, data:null, error:'', loading:true, returnFocus,
    scrollTop:catalogueEl('catalogue-search-results').scrollTop});
  selectedSongState.generation++;
  const panel = catalogueEl('song-action-panel');
  if (!panel.open) {
    if (typeof panel.showModal === 'function') panel.showModal();
    else { panel.setAttribute('open',''); panel.classList.add('dialog-fallback'); catalogueEl('catalogue-search-overlay').inert = true; }
  }
  setText(catalogueEl('song-action-title'), track.title);
  catalogueEl('song-action-intents').replaceChildren(); catalogueEl('song-action-intents')._signature = null;
  catalogueEl('song-action-details').innerHTML = `<strong>${escapeHtml(track.artist)}</strong><p>${escapeHtml([track.album,track.version,track.duration > 0 ? formatDuration(track.duration) : ''].filter(Boolean).join(' · '))}</p>`;
  catalogueEl('btn-close-song-action').focus({preventScroll:true});
  await checkSelectedAvailability();
}
async function checkSelectedAvailability() {
  const state = selectedSongState, generation = ++state.generation, track = state.track;
  state.loading = true; state.error = ''; renderSelectedSongPanel();
  try {
    const data = await requestJSON('selected-recording', `/api/v1/catalogue/recordings/${encodeURIComponent(track.recording_id)}?release_id=${encodeURIComponent(track.release_id || '')}`,
      data => data && typeof data.can_request === 'boolean' && isExternalTrack(data.track) && (data.song == null || isSongList([data.song])) && (data.job == null || isRequestJob(data.job)), {force:true,timeout:110000});
    if (!data || generation !== state.generation || !state.open) return;
    if (data.track.recording_id !== track.recording_id) throw new Error('The server returned a different recording.');
    state.data = data;
    if (data.job) acceptRequestJob(data.job);
    discoveryState.canRequest = data.can_request === true;
  } catch (error) { if (generation === state.generation && state.open) state.error = error.message; }
  finally { if (generation === state.generation && state.open) { state.loading = false; renderSelectedSongPanel(); } }
}
function closeSelectedSongPanel() {
  const state = selectedSongState;
  if (!state.open) return;
  state.open = false; state.generation++; cancelResource('selected-recording');
  const panel = catalogueEl('song-action-panel');
  if (typeof panel.close === 'function') panel.close(); else panel.removeAttribute('open');
  panel.classList.remove('dialog-fallback');
  catalogueEl('catalogue-search-overlay').inert = !catalogueState.open;
  state.returnFocus?.focus({preventScroll:true});
  catalogueEl('catalogue-search-results').scrollTop = state.scrollTop;
}
function renderSelectedSongPanel() {
  const state = selectedSongState; if (!state.open) return;
  const row = catalogueEl('song-action-row');
  catalogueEl('btn-retry-availability').hidden = !state.error;
  row.hidden = state.loading || Boolean(state.error) || !state.data;
  setText(catalogueEl('song-action-status'), state.loading ? 'Checking your library…' : state.error || state.data?.message ||
    (state.data && !state.data.can_request && !state.data.song ? 'Downloads are not configured on this server.' : ''));
  if (row.hidden) return;
  const track = {...state.track, song:state.data.song, job:state.data.job};
  row.dataset.discoveryKey = track.key;
  const focused = row.contains(document.activeElement) ? document.activeElement.dataset.discoveryAction : null;
  updateExternalSong(row, track);
  if (focused && !row.contains(document.activeElement)) (row.querySelector(`[data-discovery-action="${focused}"]`) || catalogueEl('btn-close-song-action')).focus({preventScroll:true});
  const job = externalJob(track);
  const signature = JSON.stringify(job?.playlist_intents || []), intents = catalogueEl('song-action-intents');
  if (intents._signature !== signature) {
    intents._signature = signature;
    intents.innerHTML = (job?.playlist_intents || []).map(intent => `<p>${escapeHtml(intent.state === 'added'
      ? `${intent.skipped_count ? 'Already in' : 'Added to'} ${intent.playlist_name}.`
      : intent.state === 'failed' ? `${intent.playlist_name}: ${intent.error}`
      : `${intent.playlist_name}: ${job.state === 'failed' ? 'Destination retained for retry.' : 'Will be added when ready.'}`)}</p>${intent.state === 'failed' ? `<button type="button" class="manual-playlist-button" data-retry-intent="${intent.playlist_id}">Retry addition</button>` : ''}`).join('');
  }
}
function notifySongRequestChange(previous, job) {
  const selected = selectedSongState.open && selectedSongState.track?.recording_id === job.track.recording_id;
  for (const intent of job.playlist_intents || []) {
    const old = previous?.playlist_intents?.find(old => old.id === intent.id);
    if (old && old.state !== intent.state && ['added','failed'].includes(intent.state)) {
      if (intent.state === 'added') refreshPlaylistData(intent.playlist_id);
      if (!selected) showPlaylistNotice(intent.state === 'added' ? `${job.track.title} added to ${intent.playlist_name}.` : `${job.track.title} is ready; adding to ${intent.playlist_name} failed.`);
    }
  }
  if (previous && previous.state !== job.state && !selected) {
    if (job.state === 'ready' && !job.playlist_intents?.length) showPlaylistNotice(`${job.track.title} is ready to play.`);
    if (job.state === 'failed') showPlaylistNotice(`${job.track.title}: download failed. Open the song to retry.`);
    if (job.state === 'awaiting_choice') showPlaylistNotice(`${job.track.title}: choose a version to continue.`);
  }
}
function handleCatalogueKeyboard(event) {
  if (selectedSongState.open) {
    if (event.key === 'Escape') { event.preventDefault(); closeSelectedSongPanel(); }
    if (event.key === 'Tab') trapPlaylistFocus(event,catalogueEl('song-action-panel'));
    return true;
  }
  if (!catalogueState.open) return false;
  if (event.key === 'Escape') { event.preventDefault(); hideSearchOverlay(); return true; }
  if (event.key === 'Tab') { trapPlaylistFocus(event,catalogueEl('catalogue-search-overlay')); return true; }
  if (event.target?.closest?.('button')) return true;
  const previous = catalogueState.index;
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault(); const length = catalogueState.results.length;
    if (!length) return true;
    catalogueState.index = (previous + (event.key === 'ArrowDown' ? 1 : -1) + length) % length;
    [previous,catalogueState.index].forEach(index => {
      const node = catalogueEl('catalogue-search-results').querySelector(`[data-index="${index}"]`);
      node?.classList.toggle('highlighted', index === catalogueState.index); node?.setAttribute('aria-selected',String(index === catalogueState.index));
    });
    const node = catalogueEl('catalogue-search-results').querySelector(`[data-index="${catalogueState.index}"]`);
    catalogueEl('catalogue-search-input').setAttribute('aria-activedescendant',node.id); node.scrollIntoView({block:'nearest'});
  } else if (event.key === 'Enter' && catalogueState.index >= 0) {
    event.preventDefault(); openSelectedSong(catalogueState.results[catalogueState.index],catalogueEl('catalogue-search-input'));
  }
  return true;
}
function initDiscoveryEvents() {
  const overlay = catalogueEl('catalogue-search-overlay'); if (!overlay || overlay._bound) return; overlay._bound = true;
  catalogueEl('catalogue-search-input').addEventListener('input',event => scheduleCatalogueSearch(event.target.value));
  catalogueEl('btn-retry-catalogue').addEventListener('click',() => searchCatalogue(catalogueState.query));
  catalogueEl('btn-close-catalogue').addEventListener('click',hideSearchOverlay);
  overlay.addEventListener('click',event => { if (event.target === overlay) hideSearchOverlay(); });
  catalogueEl('catalogue-search-results').addEventListener('click',event => {
    const row = event.target.closest('[data-recording-id]'); if (row) openSelectedSong(catalogueState.results[Number(row.dataset.index)],row);
  });
  catalogueEl('btn-close-song-action').addEventListener('click',closeSelectedSongPanel);
  catalogueEl('btn-retry-availability').addEventListener('click',checkSelectedAvailability);
  catalogueEl('song-action-panel').addEventListener('cancel',event => { event.preventDefault(); closeSelectedSongPanel(); });
  const act = event => {
    const button = event.target.closest('[data-discovery-action]'); if (!button) return;
    const row = button.closest('[data-request-id]'), job = row ? discoveryState.jobs.get(row.dataset.requestId) : null;
    const track = job?.track || (selectedSongState.track && {...selectedSongState.track,song:selectedSongState.data?.song,job:selectedSongState.data?.job});
    if (!track) return;
    const currentJob = externalJob(track), song = currentJob ? currentJob.song : track.song;
    if (button.dataset.discoveryAction === 'play' && song) playSong(song);
    else if (button.dataset.discoveryAction === 'add') openPlaylistPicker(song ? [song.id] : null, song ? null : track);
    else if (button.dataset.discoveryAction === 'choose-version') chooseSongRequestVersion(track,button.dataset.candidateKey);
    else if (button.dataset.discoveryAction === 'reselect') { closeSelectedSongPanel(); showSearchOverlay(); catalogueEl('catalogue-search-input').focus(); }
    else submitSongRequest(track,button.dataset.discoveryAction === 'retry');
  };
  catalogueEl('song-action-panel').addEventListener('click',act);
  catalogueEl('song-requests-list').addEventListener('click',act);
  catalogueEl('btn-refresh-song-requests').addEventListener('click',refreshSongRequests);
  catalogueEl('song-action-intents').addEventListener('click',async event => {
    const button = event.target.closest('[data-retry-intent]'); if (!button) return;
    const track = selectedSongState.track, epoch = discoveryState.epoch; button.disabled = true;
    try {
      const job = await sendPlaylistMutation('/api/v1/song-requests',{provider:track.provider,recording_id:track.recording_id,release_id:track.release_id||'',playlist_id:Number(button.dataset.retryIntent)});
      if (epoch === discoveryState.epoch && isRequestJob(job)) { acceptRequestJob(job); renderSelectedSongPanel(); refreshSongRequests(); }
    } catch (error) { if (epoch === discoveryState.epoch && selectedSongState.open) setText(catalogueEl('song-action-status'),error.message); }
    finally { button.disabled = false; }
  });
  document.addEventListener('visibilitychange',() => { if (!document.hidden) refreshSongRequests(); });
}
