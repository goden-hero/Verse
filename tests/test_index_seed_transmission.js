const fs = require('fs');
const path = require('path');
const assert = require('assert');

// Read index.js content
const indexPath = path.join(__dirname, '..', 'app', 'web', 'index.js');
const indexJsContent = fs.readFileSync(indexPath, 'utf8');

// Mock DOM environment and global state
function createTestEnv() {
  const elementsMock = {
    playlistStrategy: { value: 'automatic' },
    playlistSeedType: { value: 'current song' },
    playlistSeedValue: { value: '' },
    playlistLimit: { value: '20' }
  };

  const currentStateMock = {
    currentPlayingSong: null,
    queue: [],
    queueIndex: -1
  };

  let lastFetchPayload = null;

  const mockBtn = {
    innerHTML: 'Generate Playlist',
    disabled: false
  };

  const documentMock = {
    getElementById: (id) => {
      if (id === 'btn-generate-playlist') return mockBtn;
      return null;
    }
  };

  const fetchMock = async (url, options) => {
    lastFetchPayload = JSON.parse(options.body);
    return {
      ok: true,
      json: async () => []
    };
  };

  // Build isolated VM / function execution context
  const contextFunc = new Function(
    'elements',
    'currentState',
    'document',
    'fetch',
    `
    let currentGeneratedSongs = [];
    function alert(msg) {}
    function renderGeneratedPlaylist() {}
    
    ${indexJsContent.substring(
      indexJsContent.indexOf('async function handleGeneratePlaylist'),
      indexJsContent.indexOf('function renderGeneratedPlaylist()')
    )}

    return { handleGeneratePlaylist };
    `
  );

  const { handleGeneratePlaylist } = contextFunc(
    elementsMock,
    currentStateMock,
    documentMock,
    fetchMock
  );

  return {
    elementsMock,
    currentStateMock,
    handleGeneratePlaylist,
    getLastFetchPayload: () => lastFetchPayload
  };
}

async function runTests() {
  console.log('Running Frontend Playlist Seed Transmission Tests...');

  // Test 1: Current Song selected with Song A (id: 101)
  {
    const env = createTestEnv();
    env.elementsMock.playlistSeedType.value = 'current song';
    env.currentStateMock.currentPlayingSong = { id: 101, title: 'Song A' };

    const eventMock = { preventDefault: () => {} };
    await env.handleGeneratePlaylist(eventMock);

    const payload = env.getLastFetchPayload();
    assert.strictEqual(payload.seed_type, 'current song');
    assert.strictEqual(payload.seed_value, '101');
    assert.deepStrictEqual(payload.seed_song_ids, [101]);
    console.log('✔ Test 1 Passed: Song A ID (101) correctly sent as seed_value');
  }

  // Test 2: Changing currently playing song to Song B (id: 202) updates seed_value
  {
    const env = createTestEnv();
    env.elementsMock.playlistSeedType.value = 'current song';
    
    // First play Song A
    env.currentStateMock.currentPlayingSong = { id: 101, title: 'Song A' };
    const eventMock = { preventDefault: () => {} };
    await env.handleGeneratePlaylist(eventMock);
    assert.strictEqual(env.getLastFetchPayload().seed_value, '101');

    // Change to Song B
    env.currentStateMock.currentPlayingSong = { id: 202, title: 'Song B' };
    await env.handleGeneratePlaylist(eventMock);
    const payload = env.getLastFetchPayload();
    assert.strictEqual(payload.seed_type, 'current song');
    assert.strictEqual(payload.seed_value, '202');
    assert.deepStrictEqual(payload.seed_song_ids, [202]);
    console.log('✔ Test 2 Passed: Changing current song from 101 to 202 updates seed_value');
  }

  // Test 3: No current song loaded (null) -> sends empty seed_value gracefully
  {
    const env = createTestEnv();
    env.elementsMock.playlistSeedType.value = 'current song';
    env.currentStateMock.currentPlayingSong = null;

    const eventMock = { preventDefault: () => {} };
    await env.handleGeneratePlaylist(eventMock);

    const payload = env.getLastFetchPayload();
    assert.strictEqual(payload.seed_type, 'current song');
    assert.strictEqual(payload.seed_value, '');
    assert.deepStrictEqual(payload.seed_song_ids, []);
    console.log('✔ Test 3 Passed: No current song sends empty seed_value gracefully');
  }

  // Test 4: Current Queue selected with queue populated
  {
    const env = createTestEnv();
    env.elementsMock.playlistSeedType.value = 'current queue';
    env.currentStateMock.queue = [{ id: 55, title: 'Queue Song 1' }, { id: 56, title: 'Queue Song 2' }];
    env.currentStateMock.queueIndex = 0;

    const eventMock = { preventDefault: () => {} };
    await env.handleGeneratePlaylist(eventMock);

    const payload = env.getLastFetchPayload();
    assert.strictEqual(payload.seed_type, 'current queue');
    assert.strictEqual(payload.seed_value, '55');
    assert.deepStrictEqual(payload.seed_song_ids, [55, 56]);
    console.log('✔ Test 4 Passed: Current Queue seed transmission uses all queue song IDs');
  }

  console.log('\nAll Frontend Seed Transmission Tests Passed Successfully!');
}

runTests().catch((err) => {
  console.error('Test failed:', err);
  process.exit(1);
});
