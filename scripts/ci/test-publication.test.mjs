import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { publishTests, validateTests } from './publish-tests.mjs';

const source = 'a'.repeat(40);
const revision = 'b'.repeat(40);
const context = { eventName: 'push', ref: 'refs/heads/main', sha: source, runId: 123, runAttempt: 1, repo: { owner: 'example', repo: 'project' } };
const sample = { version: 1, repository: 'example/project', source, run: '123-1', scope: 'scope', tests: 400, shards: 2, wall_seconds: 10 };
const assets = { '.github/metrics/tests/123-1.json': JSON.stringify(sample), 'docs/assets/test-convergence.svg': '<svg>measured</svg>' };
const receipt = { source, repository: sample.repository, run: sample.run, scope: sample.scope,
  files: Object.fromEntries(Object.entries(assets).map(([name, bytes]) => [name, createHash('sha256').update(bytes).digest('hex')])) };

/** Exercise the exact publisher's optimistic writes and immutable readback contract. */
function fixture({ current = source, verified = true, corrupt = false, retry = false } = {}) {
  const writes = [];
  const github = {
    rest: {
      git: {
        async getRef({ ref }) {
          if (ref === 'heads/main') return { data: { object: { sha: current } } };
          if (retry) return { data: { object: { sha: revision } } };
          throw Object.assign(new Error('Missing'), { status: 404 });
        },
        async createRef(input) { writes.push(input); return { data: { object: { sha: source } } }; },
      },
      repos: {
        async getCommit() { return { data: { commit: { verification: { verified } }, parents: [{ sha: source }], files: Object.keys(assets).map((filename) => ({ filename })) } }; },
        async getContent({ path }) { return { data: { type: 'file', encoding: 'base64', content: Buffer.from(corrupt ? 'wrong' : assets[path]).toString('base64') } }; },
      },
      pulls: {
        async list() { return { data: retry ? [{ state: 'open', html_url: 'review' }] : [] }; },
        async create(input) { writes.push(input); return { data: { state: 'open', html_url: 'review' } }; },
      },
      actions: { async createWorkflowDispatch(input) { writes.push(input); } },
    },
    async graphql(query, { input }) { writes.push(input); return { createCommitOnBranch: { commit: { oid: revision } } }; },
  };
  return { github, writes };
}

test('only exact main events can publish source/run-bound output', () => {
  assert.equal(validateTests({ context, receipt, assets }).length, 2);
  for (const changed of [{ eventName: 'pull_request' }, { ref: 'refs/tags/v1' }, { sha: 'main' }, { runAttempt: 2 }]) {
    assert.throws(() => validateTests({ context: { ...context, ...changed }, receipt, assets }));
  }
});

test('reject artifact path injection, changed bytes, source and fork bindings', () => {
  for (const values of [
    { assets: { ...assets, '../injected': 'code' } },
    { assets: { ...assets, 'docs/assets/test-convergence.svg': 'wrong' } },
    { receipt: { ...receipt, source: revision } },
    { receipt: { ...receipt, repository: 'other/fork' } },
  ]) assert.throws(() => validateTests({ context, receipt, assets, ...values }));
});

test('publish one verified proposal without updating main', async () => {
  const { github, writes } = fixture();
  assert.equal((await publishTests({ github, context, receipt, assets })).status, 'proposed');
  const commit = writes.find((item) => item.fileChanges);
  assert.equal(commit.expectedHeadOid, source);
  assert.equal(commit.branch.branchName, 'automation/test-feedback-123-1');
  assert.equal(writes.at(-1).workflow_id, 'ci.yml');
});

test('superseded main has no writes; reruns read back existing bytes', async () => {
  const stale = fixture({ current: revision });
  assert.equal((await publishTests({ github: stale.github, context, receipt, assets })).status, 'superseded');
  assert.equal(stale.writes.length, 0);
  const retry = fixture({ retry: true });
  await publishTests({ github: retry.github, context, receipt, assets });
  assert.equal(retry.writes.length, 1);
});

for (const options of [{ verified: false }, { corrupt: true }]) {
  test(`reject unverified or changed output ${JSON.stringify(options)}`, async () => {
    const { github } = fixture(options);
    await assert.rejects(publishTests({ github, context, receipt, assets }));
  });
}
