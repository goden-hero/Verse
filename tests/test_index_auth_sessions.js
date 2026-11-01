const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app', 'web', 'index.js'), 'utf8');
const bootstrap = source.slice(source.indexOf('async function bootstrapAuthentication()'), source.indexOf('async function authenticateUser('));

function environment(responses) {
  const events = [];
  const calls = [];
  const state = { auth: { currentUser: null, authenticated: false } };
  const context = vm.createContext({
    currentState: state,
    authElements: {},
    document: { body: { classList: { add() {}, remove() {} } } },
    nativeFetch: async (url, options) => {
      calls.push({ url, options });
      const response = responses.shift();
      assert(response, `Unexpected request: ${url}`);
      return { ok: response.status === 200, status: response.status, json: async () => response.body };
    },
    showAuthenticatedApp: () => events.push('app'),
    showAuthScreen: () => events.push('login'),
    setAuthMessage() {},
    console
  });
  vm.runInContext(bootstrap, context);
  return { context, events, calls, state };
}

async function main() {
  const savedSession = environment([{ status: 200, body: { id: 42, username: 'alice' } }]);
  await savedSession.context.bootstrapAuthentication();
  assert.deepEqual(savedSession.events, ['app']);
  assert.equal(savedSession.state.auth.currentUser.id, 42);
  assert.equal(savedSession.state.auth.authenticated, true);
  assert.equal(savedSession.state.auth.loading, false);
  assert.equal(savedSession.calls.length, 1);
  assert.equal(savedSession.calls[0].url, '/api/v1/auth/me');
  assert.equal(savedSession.calls[0].options.credentials, 'same-origin');

  const expiredSession = environment([
    { status: 401 },
    { status: 200, body: { first_run: false } }
  ]);
  await expiredSession.context.bootstrapAuthentication();
  assert.deepEqual(expiredSession.events, ['login']);
  assert.equal(expiredSession.state.auth.authenticated, false);
  assert.deepEqual(expiredSession.calls.map(call => call.url), ['/api/v1/auth/me', '/api/v1/auth/first-run']);
  console.log('Auth refresh: saved session restored; expired session returns to login.');
}

main().catch(error => { console.error(error); process.exit(1); });
