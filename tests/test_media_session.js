// Whole-application JS in a deterministic browser/audio harness, not an iOS UI test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/web/index.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../app/web/index.html'), 'utf8');
const song = (id, artwork = true) => ({id, title: `Title ${id}`, artist: `Artist ${id}`, album: `Album ${id}`, artwork_available: artwork, duration: 180});
const response = data => ({ok: true, status: 200, json: async () => data});
const settle = () => new Promise(resolve => setImmediate(resolve));

function environment(options = {}) {
  const listeners = new Map(), actions = new Map(), attempts = [], positions = [], calls = [], logs = [];
  let now = 10000, createdAudio = 0, playCalls = 0;
  const audio = {
    paused: true, ended: false, error: null, duration: NaN, currentTime: 0, playbackRate: 1, readyState: 0,
    addEventListener(name, callback) {
      if (!listeners.has(name)) listeners.set(name, []);
      listeners.get(name).push(callback);
    },
    emit(name) { for (const callback of listeners.get(name) || []) callback(); },
    loadMetadata(duration = 180) { this.duration = duration; this.readyState = 1; this.emit('loadedmetadata'); },
    async play() {
      playCalls++;
      if (this.nextPlay) { const next = this.nextPlay; this.nextPlay = null; return next(); }
      this.paused = false; this.ended = false; this.error = null;
      this.emit('play'); this.emit('playing');
    },
    pause() { this.paused = true; this.emit('pause'); },
    removeAttribute(name) { if (name === 'src') this.src = ''; }
  };
  Object.defineProperty(audio, 'src', {
    get() { return this._src; },
    set(value) { this._src = value; this.currentTime = 0; this.duration = NaN; this.readyState = 0; this.paused = true; this.ended = false; this.error = null; this.emit('emptied'); }
  });
  const session = {metadata: null, playbackState: 'none',
    setActionHandler(action, callback) {
      attempts.push(action);
      if (options.unsupported?.includes(action)) throw new TypeError('Unsupported action');
      actions.set(action, callback);
    },
    setPositionState(value) {
      if (options.positionThrows) throw new TypeError('Unsupported position state');
      if ('duration' in value) {
        assert(Number.isFinite(value.duration) && value.duration > 0);
        assert(Number.isFinite(value.position) && value.position >= 0 && value.position <= value.duration);
        assert(Number.isFinite(value.playbackRate) && value.playbackRate > 0);
      }
      positions.push({...value});
    }
  };
  if (options.noActions) delete session.setActionHandler;
  if (options.noPosition) delete session.setPositionState;
  const document = {
    getElementById: id => id === 'main-audio-element' ? audio : null,
    querySelector: () => null, querySelectorAll: () => [], addEventListener() {},
    createElement(tag) { if (tag === 'audio') createdAudio++; return {}; },
    head: {appendChild() {}}, body: {classList: {add() {}, remove() {}}}
  };
  const context = vm.createContext({
    document, navigator: options.noSession ? {} : {mediaSession: session}, URL, AbortController, setTimeout, clearTimeout,
    Date: class extends Date { static now() { return now; } },
    MediaMetadata: options.noMetadata ? undefined : class {
      constructor(data) {
        if (options.metadataThrows) throw new TypeError('Metadata unavailable');
        Object.assign(this, data);
      }
    },
    console: {log() {}, error: (...args) => logs.push(args), debug: (...args) => logs.push(args)},
    window: {location: {href: 'https://verse.example/index.html'}, addEventListener() {},
      fetch: (...args) => context.fetch(...args)},
    fetch(url, init = {}) {
      calls.push({url, init});
      if (options.fetch) { const result = options.fetch(url, init); if (result) return result; }
      if (url.endsWith('/play') || url.endsWith('/resume')) return Promise.resolve(response({session_id: 8, current_song_index: 1, current_position: 22}));
      if (url.includes('/playlists/') && url.endsWith('/songs')) return Promise.resolve(response([song(1), song(2)]));
      if (/\/songs\/\d+$/.test(url)) return Promise.resolve(response(song(Number(url.split('/').at(-1)))));
      return Promise.resolve(response({}));
    }
  });
  vm.runInContext(source, context);
  const run = code => vm.runInContext(code, context);
  run('initAudioPlayerEvents()');
  return {run, audio, session, actions, attempts, positions, calls, logs, listeners,
    play(track, queue = [track]) { context.track = track; context.queue = queue; return run('playSong(track, queue)'); },
    tick(ms) { now += ms; }, getPlayCalls: () => playCalls, createdAudio: () => createdAudio};
}

async function main() {
  const env = environment();
  const {audio, session, actions, run, positions} = env;
  assert.deepEqual([...actions.keys()], ['play', 'pause', 'previoustrack', 'nexttrack', 'seekbackward', 'seekforward', 'seekto']);
  run('initAudioPlayerEvents()');
  assert.equal(env.attempts.length, 7, 'reinitialization must not duplicate handlers/listeners');
  assert.equal(env.listeners.get('playing').length, 1);

  const queue = [song(1), song(2, false), song(3)];
  const starting = env.play(queue[0], queue);
  assert.equal(session.metadata.title, 'Title 1', 'metadata must publish synchronously');
  assert.equal(session.metadata.artist, 'Artist 1');
  assert.equal(session.metadata.album, 'Album 1');
  assert.equal(session.metadata.artwork[0].src, 'https://verse.example/api/v1/songs/1/artwork?fallback=true');
  assert.equal(session.metadata.artwork[0].sizes, undefined, 'never invent original cover dimensions');
  await starting;
  assert.equal(session.playbackState, 'playing');
  audio.loadMetadata();
  audio.currentTime = 30;
  const count = positions.length;
  for (let i = 0; i < 20; i++) audio.emit('timeupdate');
  assert.equal(positions.length, count, 'routine position updates are throttled');
  env.tick(1000); audio.emit('timeupdate');
  assert.equal(positions.length, count + 1);
  assert.equal(positions.at(-1).position, 30);
  audio.playbackRate = 1.25; audio.emit('ratechange');
  assert.equal(positions.at(-1).playbackRate, 1.25);
  actions.get('pause')();
  assert.equal(session.playbackState, 'paused'); assert.equal(run('currentState.isPlaying'), false);
  await actions.get('play')();
  assert.equal(session.playbackState, 'playing');
  audio.pause(); // external audio event, not an application button
  assert.equal(session.playbackState, 'paused');

  actions.get('seekforward')({seekOffset: 12}); assert.equal(audio.currentTime, 42);
  actions.get('seekbackward')({}); assert.equal(audio.currentTime, 32);
  actions.get('seekto')({seekTime: 999}); assert.equal(audio.currentTime, 180);
  actions.get('seekto')({seekTime: -10}); assert.equal(audio.currentTime, 0);
  actions.get('seekto')({seekTime: NaN}); assert.equal(audio.currentTime, 0);
  assert.equal(audio.paused, true); assert.equal(session.playbackState, 'paused');
  let fast = null;
  audio.fastSeek = value => { fast = value; audio.currentTime = value; };
  actions.get('seekto')({seekTime: 15, fastSeek: true}); assert.equal(fast, 15);
  audio.fastSeek = () => { throw new TypeError('Unavailable'); };
  actions.get('seekto')({seekTime: 16, fastSeek: true}); assert.equal(audio.currentTime, 16);

  actions.get('nexttrack')(); await settle();
  assert.equal(run('currentState.queueIndex'), 1);
  assert.equal(session.metadata.title, 'Title 2');
  assert.equal(session.metadata.album, 'Album 2');
  assert.equal(session.metadata.artwork[0].src, 'https://verse.example/api/v1/artwork/default');
  assert.equal(session.metadata.artwork[0].sizes, '512x512');
  assert.equal(session.metadata.artwork[0].type, 'image/png');
  assert.deepEqual(positions.at(-1), {}, 'old track position cleared until new metadata loads');
  audio.loadMetadata(); audio.currentTime = 20;
  actions.get('previoustrack')(); assert.equal(audio.currentTime, 0); assert.equal(run('currentState.queueIndex'), 1);
  actions.get('previoustrack')(); await settle(); assert.equal(run('currentState.queueIndex'), 0);
  audio.ended = true; audio.paused = true; audio.emit('ended'); await settle();
  assert.equal(run('currentState.queueIndex'), 1); assert.equal(session.metadata.title, 'Title 2');
  assert.equal(run('currentState.queue.length'), 3);
  run('currentState.isRepeat = true');
  audio.loadMetadata(); audio.currentTime = 180; audio.ended = true; audio.emit('ended'); await settle();
  assert.equal(run('currentState.queueIndex'), 1); assert.equal(audio.currentTime, 0);
  run('currentState.isRepeat = false');

  for (const invalid of [NaN, Infinity, 0, -1]) {
    audio.duration = invalid; audio.emit('durationchange'); assert.deepEqual(positions.at(-1), {});
  }
  audio.duration = 180; audio.currentTime = Infinity; audio.emit('seeked'); assert.deepEqual(positions.at(-1), {});
  audio.currentTime = 20; audio.playbackRate = 0; audio.emit('ratechange'); assert.deepEqual(positions.at(-1), {});
  audio.playbackRate = 1;
  audio.error = {code: 4}; audio.emit('error'); assert.equal(session.playbackState, 'paused');
  audio.error = null; audio.pause();
  audio.nextPlay = () => Promise.reject(new Error('NotAllowedError'));
  assert.equal(await actions.get('play')(), false);
  assert.equal(session.playbackState, 'paused'); assert.equal(run('currentState.isPlaying'), false);
  audio.nextPlay = () => Promise.reject(new Error('DecodeError'));
  await env.play(song(4, false)); assert.equal(session.metadata.title, 'Title 4'); assert.equal(session.playbackState, 'paused');
  audio.nextPlay = () => Promise.reject(new Error('Blocked toggle'));
  assert.equal(await run('togglePlayPause()'), false);

  // Playlist start/resume, direct library/queue/recommendation calls all converge.
  await run('playPlaylist(42)'); await settle(); assert.equal(session.metadata.title, 'Title 1');
  await run('resumePlaylist(42)'); await settle(); assert.equal(session.metadata.title, 'Title 2');
  assert.equal(audio.currentTime, 22, 'saved resume offset survives before loadedmetadata');
  audio.nextPlay = () => Promise.reject(new Error('Resume blocked'));
  await run('resumePlaylist(42)'); await settle();
  assert.equal(audio.currentTime, 22, 'blocked play must not discard the saved resume offset');
  assert.equal(session.playbackState, 'paused');
  const persistent = run('elements.audio');
  run("currentState.activeTab = 'view-home'; navigationGeneration++");
  await env.play(song(5));
  assert.equal(run('elements.audio'), persistent); assert.equal(env.createdAudio(), 0);
  assert.equal((html.match(/<audio\b/g) || []).length, 1);

  // Late detail responses (even transports ignoring abort) cannot restore old tags.
  let resolveOld;
  const stale = environment({fetch: (url) => url === '/api/v1/songs/90' ? new Promise(resolve => { resolveOld = resolve; }) : null});
  await stale.play({id: 90, title: 'Partial', artist: 'Preview'});
  assert.equal(stale.session.metadata.album, '');
  await stale.play(song(91, false));
  assert.equal(stale.calls.find(c => c.url === '/api/v1/songs/90').init.signal.aborted, true);
  resolveOld(response(song(90))); await settle(); assert.equal(stale.session.metadata.title, 'Title 91');
  await stale.play({id: 92, title: 'Partial'}); await settle();
  assert.equal(stale.session.metadata.album, 'Album 92');
  let rejectOld;
  stale.audio.nextPlay = () => new Promise((_, reject) => { rejectOld = reject; });
  const oldPlay = stale.play(song(93)); await stale.play(song(94));
  rejectOld(new Error('Obsolete play')); await oldPlay;
  assert.equal(stale.session.playbackState, 'playing'); assert.equal(stale.session.metadata.title, 'Title 94');
  // A delayed playlist resume must not seek a different, newer song.
  let finishResume;
  stale.audio.nextPlay = () => new Promise(resolve => { finishResume = resolve; });
  const resuming = stale.run('resumePlaylist(42)'); await settle();
  assert.equal(typeof finishResume, 'function');
  await stale.play(song(96)); stale.audio.loadMetadata(); stale.audio.currentTime = 44;
  finishResume(); await resuming;
  assert.equal(stale.audio.currentTime, 44); assert.equal(stale.session.metadata.title, 'Title 96');

  for (const bad of [
    {ok: false, status: 503},
    {ok: true, json: async () => { throw new SyntaxError('Invalid JSON'); }},
    response({detail: 'unexpected'}),
    new Error('Network unavailable')
  ]) {
    const failed = environment({fetch: url => url === '/api/v1/songs/95'
      ? (bad instanceof Error ? Promise.reject(bad) : Promise.resolve(bad)) : null});
    await failed.play({id: 95, title: 'New partial'}); await settle();
    assert.equal(failed.session.metadata.title, 'New partial'); assert.equal(failed.session.metadata.album, '');
    assert.equal(failed.session.playbackState, 'playing');
  }

  await run('handleLogout()');
  assert.equal(session.metadata, null); assert.equal(session.playbackState, 'none');
  assert.deepEqual(positions.at(-1), {});
  for (const options of [{noSession: true}, {noMetadata: true}, {metadataThrows: true}, {noActions: true, noPosition: true}, {positionThrows: true}, {unsupported: ['previoustrack', 'seekto']}]) {
    const partial = environment(options);
    await partial.play(song(1)); partial.audio.loadMetadata(); partial.audio.emit('timeupdate');
    assert.equal(partial.run('currentState.isPlaying'), true);
    if (options.unsupported) {
      assert.equal(partial.attempts.length, 7); assert(partial.actions.has('nexttrack')); assert(partial.actions.has('seekforward'));
      partial.actions.get('pause')(); await partial.actions.get('play')();
    }
  }
  console.log('Media Session checks passed: metadata, fallback URLs, action isolation, audio events, rejected play, seek/clamping, throttling, stale lookups, playlist/queue/loop, logout, persistent audio, partial/no API.');
}
// Pending promises alone do not keep Node alive: fail instead of silently exiting
// successfully if a regression leaves an awaited playback operation unfinished.
const watchdog = setTimeout(() => { console.error('Media Session checks timed out'); process.exit(1); }, 15000);
main().then(() => clearTimeout(watchdog)).catch(error => {
  clearTimeout(watchdog); console.error(error); process.exitCode = 1;
});
