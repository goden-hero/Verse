const fs = require('fs');
const path = require('path');
const assert = require('assert');

// Read index.js content
const indexPath = path.join(__dirname, '..', 'app', 'web', 'index.js');
const indexJsContent = fs.readFileSync(indexPath, 'utf8');

function createClassListMock() {
  const classes = new Set();
  return {
    add: (cls) => classes.add(cls),
    remove: (cls) => classes.delete(cls),
    contains: (cls) => classes.has(cls),
    toggle: (cls, force) => {
      if (force === undefined) {
        if (classes.has(cls)) classes.delete(cls);
        else classes.add(cls);
      } else if (force) {
        classes.add(cls);
      } else {
        classes.delete(cls);
      }
    }
  };
}

function createMockElement(id) {
  const listeners = {};
  return {
    id,
    disabled: false,
    classList: createClassListMock(),
    addEventListener: (event, handler) => {
      listeners[event] = handler;
    },
    click: () => {
      if (listeners['click']) listeners['click']();
    },
    trigger: (event) => {
      if (listeners[event]) listeners[event]();
    }
  };
}

function createTestEnv() {
  const barBtnRepeat = createMockElement('np-btn-repeat');
  const mobileFullBtnRepeat = createMockElement('mobile-full-btn-repeat');

  const audioListeners = {};
  let playCalledCount = 0;

  const audioMock = {
    currentTime: 100,
    duration: 180,
    src: 'song.mp3',
    play: async () => {
      playCalledCount++;
    },
    getPlayCalledCount: () => playCalledCount,
    resetPlayCalledCount: () => { playCalledCount = 0; },
    addEventListener: (event, handler) => {
      audioListeners[event] = handler;
    },
    trigger: (event) => {
      if (audioListeners[event]) audioListeners[event]();
    }
  };

  const elementsMock = {
    audio: audioMock,
    barBtnRepeat: barBtnRepeat
  };

  const documentMock = {
    getElementById: (id) => {
      if (id === 'np-btn-repeat') return barBtnRepeat;
      if (id === 'mobile-full-btn-repeat') return mobileFullBtnRepeat;
      if (id === 'main-audio-element') return audioMock;
      return null;
    },
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    removeEventListener: () => {},
    createElement: (tag) => createMockElement(tag),
    body: { appendChild: () => {} },
    head: { appendChild: () => {} },
    appendChild: () => {}
  };

  // Extract necessary logic and setup execution environment
  const setupScript = `
    function syncSessionProgress() {}

    ${indexJsContent}

    let nextSongCalled = false;
    const originalPlayNextSong = playNextSong;
    playNextSong = function() {
      nextSongCalled = true;
      originalPlayNextSong();
    };

    initAudioPlayerEvents();
    initMobileEvents();

    return {
      currentState,
      updateLoopUI,
      barBtnRepeat: elements.barBtnRepeat,
      mobileFullBtnRepeat: document.getElementById('mobile-full-btn-repeat'),
      audioMock: elements.audio,
      getNextSongCalled: () => nextSongCalled,
      resetNextSongCalled: () => { nextSongCalled = false; }
    };
  `;

  const contextFunc = new Function(
    'document',
    'window',
    'fetch',
    setupScript
  );

  const windowMock = {
    fetch: async () => ({ ok: true, json: async () => ({}) }),
    addEventListener: () => {}
  };

  return contextFunc(documentMock, windowMock, windowMock.fetch);
}

async function runTests() {
  console.log('Running Functional Loop Playback Tests...\n');

  // Test 1: Initial state is loop OFF
  {
    const env = createTestEnv();
    assert.strictEqual(env.currentState.isRepeat, false);
    assert.strictEqual(env.currentState.isLooping, false);
    assert.strictEqual(env.barBtnRepeat.classList.contains('active'), false);
    assert.strictEqual(env.barBtnRepeat.classList.contains('active-state'), false);
    console.log('✔ Test 1 Passed: Initial loop state is OFF and UI reflects inactive state');
  }

  // Test 2: Clicking Loop button toggles state ON and updates active UI class
  {
    const env = createTestEnv();
    env.barBtnRepeat.click();

    assert.strictEqual(env.currentState.isRepeat, true);
    assert.strictEqual(env.currentState.isLooping, true);
    assert.strictEqual(env.barBtnRepeat.classList.contains('active'), true);
    assert.strictEqual(env.barBtnRepeat.classList.contains('active-state'), true);
    assert.strictEqual(env.mobileFullBtnRepeat.classList.contains('active-state'), true);

    // Toggle back OFF
    env.barBtnRepeat.click();
    assert.strictEqual(env.currentState.isRepeat, false);
    assert.strictEqual(env.currentState.isLooping, false);
    assert.strictEqual(env.barBtnRepeat.classList.contains('active'), false);
    assert.strictEqual(env.barBtnRepeat.classList.contains('active-state'), false);
    console.log('✔ Test 2 Passed: Desktop repeat button toggles state ON/OFF and updates UI');
  }

  // Test 3: Clicking Mobile repeat button syncs with desktop state
  {
    const env = createTestEnv();
    env.mobileFullBtnRepeat.click();

    assert.strictEqual(env.currentState.isRepeat, true);
    assert.strictEqual(env.currentState.isLooping, true);
    assert.strictEqual(env.barBtnRepeat.classList.contains('active'), true);
    assert.strictEqual(env.mobileFullBtnRepeat.classList.contains('active-state'), true);
    console.log('✔ Test 3 Passed: Mobile repeat button toggles state and syncs with desktop button');
  }

  // Test 4: Audio ended event when Loop is OFF -> advances to next track
  {
    const env = createTestEnv();
    env.currentState.isRepeat = false;
    env.currentState.currentPlayingSong = { id: 1, title: 'Track 1' };

    env.audioMock.trigger('ended');
    assert.strictEqual(env.getNextSongCalled(), true);
    assert.strictEqual(env.audioMock.getPlayCalledCount(), 0);
    console.log('✔ Test 4 Passed: Ended event with Loop OFF advances to next song');
  }

  // Test 5: Audio ended event when Loop is ON -> replays current song
  {
    const env = createTestEnv();
    env.currentState.isRepeat = true;
    env.currentState.currentPlayingSong = { id: 42, title: 'Track 42' };
    env.currentState.queue = [{ id: 42, title: 'Track 42' }, { id: 43, title: 'Track 43' }];
    env.currentState.queueIndex = 0;

    env.audioMock.trigger('ended');

    // Wait a tick for async audio.play promise
    await new Promise((r) => setTimeout(r, 10));

    assert.strictEqual(env.audioMock.currentTime, 0);
    assert.strictEqual(env.audioMock.getPlayCalledCount(), 1);
    assert.strictEqual(env.getNextSongCalled(), false);
    assert.strictEqual(env.currentState.queueIndex, 0);
    assert.strictEqual(env.currentState.queue.length, 2);
    console.log('✔ Test 5 Passed: Ended event with Loop ON replays current track without altering queue');
  }

  // Test 6: Loop enabled before starting a song -> loops when song starts and ends
  {
    const env = createTestEnv();
    // Enable loop when no song is playing
    env.currentState.currentPlayingSong = null;
    env.barBtnRepeat.click();
    assert.strictEqual(env.currentState.isRepeat, true);

    // Now start a song
    env.currentState.currentPlayingSong = { id: 99, title: 'Song 99' };
    env.audioMock.trigger('ended');
    await new Promise((r) => setTimeout(r, 10));

    assert.strictEqual(env.audioMock.currentTime, 0);
    assert.strictEqual(env.audioMock.getPlayCalledCount(), 1);
    console.log('✔ Test 6 Passed: Enabling loop before selecting a song works when song ends');
  }

  console.log('\nAll Functional Loop Playback Tests Passed Successfully!');
}

runTests().catch((err) => {
  console.error('Test failed:', err);
  process.exit(1);
});
