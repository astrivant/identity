import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { publishContracts, validateBundle } from './publish-contracts.mjs';

const SOURCE = 'a'.repeat(40);
const OUTPUT = 'b'.repeat(40);
const DIRECTORY = 'scripts/ci/provider_contracts/data/';
const context = { eventName: 'push', ref: 'refs/heads/main', sha: SOURCE, runId: 123, repo: { owner: 'example', repo: 'fixture' } };
const assets = { 'github.json': Buffer.from('{}'), 'gitlab.json': Buffer.from('{}'), 'manifest.json': Buffer.from('new') };
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');

/** Model signed proposal retries and partial failures at the maintained SDK boundary. */
function fixture({ current = SOURCE, unchanged = false, existing = false, verified = true, corrupt = false, denied = false, edited = false, failed = false } = {}) {
  const writes = [];
  const github = {
    rest: {
      git: {
        async getRef({ ref }) {
          if (ref === 'heads/main') return { data: { object: { sha: current } } };
          if (existing) return { data: { object: { sha: OUTPUT } } };
          throw Object.assign(new Error('Missing'), { status: 404 });
        },
        async createRef(input) { writes.push(['ref', input]); return { data: { object: { sha: SOURCE } } }; },
      },
      repos: {
        async getContent({ ref, path }) {
          const name = path.slice(DIRECTORY.length);
          const changed = name === 'manifest.json' && (corrupt || (ref === SOURCE && !unchanged));
          return { data: { type: 'file', encoding: 'base64', content: Buffer.from(changed ? 'old' : assets[name]).toString('base64') } };
        },
        async getCommit() {
          return { data: { commit: { verification: { verified } }, parents: [{ sha: SOURCE }], files: [{ filename: `${DIRECTORY}${edited ? 'unrelated' : 'manifest.json'}` }] } };
        },
      },
      pulls: {
        async list() { return { data: existing ? [{ state: 'open', html_url: 'https://example.invalid/pr/1' }] : [] }; },
        async create(input) {
          writes.push(['pr', input]);
          if (denied) throw Object.assign(new Error('GitHub Actions is not permitted to create or approve pull requests.'), { status: 403 });
          return { data: { state: 'open', html_url: 'https://example.invalid/pr/1' } };
        },
      },
      actions: { async createWorkflowDispatch(input) { writes.push(['dispatch', input]); } },
    },
    async graphql(query, { input }) {
      assert.ok(query.includes('createCommitOnBranch'));
      writes.push(['commit', input]);
      if (failed) throw new Error('Expected head changed');
      return { createCommitOnBranch: { commit: { oid: OUTPUT } } };
    },
  };
  return { github, writes };
}

test('renewal validates source, lock, hashes, selected snapshots and observation before publication', () => {
  const snapshots = { 'github.json': '{}', 'gitlab.json': '{}' };
  const manifest = Object.fromEntries(['github', 'gitlab'].map((name) => [name, { revision: SOURCE, snapshot_sha256: hash('{}') }]));
  const payload = { ...snapshots, 'manifest.json': JSON.stringify(manifest) };
  const bundle = {
    assets: payload, source: SOURCE, lock: 'locked',
    provenance: { source_revision: SOURCE, poetry_lock_sha256: hash('locked'), vendor_contracts: manifest, files: Object.fromEntries(Object.entries(payload).map(([name, bytes]) => [name, hash(bytes)])) },
    observation: { latest: true, current: true, revisions: { github: SOURCE, gitlab: SOURCE }, manifest_sha256: hash(payload['manifest.json']) },
  };
  validateBundle(bundle);
  for (const mutation of [
    { source: OUTPUT }, { lock: 'wrong' }, { assets: { ...payload, 'github.json': 'tampered' } },
    { observation: { ...bundle.observation, current: false } },
    { assets: { ...payload, '../escape': 'wrong' } },
  ]) assert.throws(() => validateBundle({ ...bundle, ...mutation }));
});

test('new main proposal uses one signed expected-head commit and dispatches full CI', async () => {
  const { github, writes } = fixture();
  assert.equal((await publishContracts({ github, context, assets })).status, 'proposed');
  assert.deepEqual(writes.map(([kind]) => kind), ['ref', 'commit', 'pr', 'dispatch']);
  const commit = writes.find(([kind]) => kind === 'commit')[1];
  assert.equal(commit.expectedHeadOid, SOURCE);
  assert.deepEqual(commit.fileChanges.additions.map(({ path }) => path), [`${DIRECTORY}manifest.json`]);
  assert.notEqual(commit.branch.branchName, 'main');
});

test('retry verifies the existing signed bytes without a second commit or PR', async () => {
  const { github, writes } = fixture({ existing: true });
  assert.equal((await publishContracts({ github, context, assets })).status, 'proposed');
  assert.deepEqual(writes.map(([kind]) => kind), ['dispatch']);
});

for (const [options, expected] of [[{ current: OUTPUT }, 'superseded'], [{ unchanged: true }, 'unchanged']]) {
  test(`skip ${expected} without writes`, async () => {
    const { github, writes } = fixture(options);
    assert.equal((await publishContracts({ github, context, assets })).status, expected);
    assert.equal(writes.length, 0);
  });
}

for (const options of [{ verified: false }, { corrupt: true }, { edited: true }, { failed: true }]) {
  test(`fail publication with no PR on invalid proposal ${JSON.stringify(options)}`, async () => {
    const { github, writes } = fixture(options);
    await assert.rejects(publishContracts({ github, context, assets }));
    assert.ok(writes.every(([kind]) => kind !== 'pr' && kind !== 'dispatch'));
  });
}

test('disabled bot PR policy retains signed branch and actionable compare link', async () => {
  const { github, writes } = fixture({ denied: true });
  const result = await publishContracts({ github, context, assets });
  assert.equal(result.status, 'review-required');
  assert.ok(result.url.includes('/compare/main...automation/'));
  assert.ok(writes.every(([kind]) => kind !== 'dispatch'));
});

test('PR/tag contexts and unexpected paths cannot obtain write effects', async () => {
  const { github, writes } = fixture();
  for (const invalid of [{ ...context, eventName: 'pull_request' }, { ...context, ref: 'refs/tags/v1' }]) {
    await assert.rejects(publishContracts({ github, context: invalid, assets }));
  }
  await assert.rejects(publishContracts({ github, context, assets: { ...assets, 'unexpected.json': '{}' } }));
  assert.equal(writes.length, 0);
});

test('a newer renewal at the same application source gets a distinct recoverable proposal', async () => {
  const first = fixture({ denied: true });
  const second = fixture({ denied: true });
  await publishContracts({ github: first.github, context, assets });
  // Stop after capturing branch selection, before readback of this deliberately different bundle.
  await assert.rejects(publishContracts({ github: second.github, context, assets: { ...assets, 'manifest.json': Buffer.from('next') } }));
  assert.notEqual(first.writes[0][1].ref, second.writes[0][1].ref);
});
