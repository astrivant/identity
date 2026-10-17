import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { main, publishTests, validateTests } from './publish-tests.mjs';

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

for (const owner of ['example', 'other']) {
  test(`workflow entrypoint preserves inherited repository identity: ${owner}`, async (t) => {
    const directory = await mkdtemp(path.join(tmpdir(), 'witful-test-publication-'));
    const previous = process.cwd();
    const attempt = process.env.GITHUB_RUN_ATTEMPT;
    t.after(async () => {
      process.chdir(previous);
      if (attempt === undefined) delete process.env.GITHUB_RUN_ATTEMPT;
      else process.env.GITHUB_RUN_ATTEMPT = attempt;
      await rm(directory, { recursive: true, force: true });
    });

    // Actions Context exposes repo through its prototype, which object spread omits.
    class ActionContext {
      get repo() { return { owner, repo: 'project' }; }
    }
    const runtime = Object.assign(new ActionContext(), {
      eventName: 'push', ref: 'refs/heads/main', sha: source, runId: 123,
    });
    assert.equal(Object.hasOwn(runtime, 'repo'), false);
    const root = path.join(directory, '.cache/ci/tests');
    for (const [name, bytes] of Object.entries(assets)) {
      const destination = path.join(root, 'publication', name);
      await mkdir(path.dirname(destination), { recursive: true });
      await writeFile(destination, bytes);
    }
    await writeFile(path.join(root, 'publication.json'), JSON.stringify(receipt));
    process.chdir(directory);
    process.env.GITHUB_RUN_ATTEMPT = '1';

    const messages = [];
    const summary = [];
    const core = {
      info(message) { messages.push(JSON.parse(message)); },
      warning() { assert.fail('A valid proposal must not require a warning'); },
      summary: {
        addHeading(value) { summary.push(value); return this; },
        addRaw(value) { summary.push(value); return this; },
        async write() { summary.push('written'); },
      },
    };
    const { github, writes } = fixture();

    if (owner === 'example') {
      await main({ github, context: runtime, core });
      assert.deepEqual(messages, [{ status: 'proposed', url: 'review', revision }]);
      assert.deepEqual(summary, ['Test matrix evidence', 'proposed: review', 'written']);
      assert.equal(writes.find((item) => item.fileChanges).branch.repositoryNameWithOwner, 'example/project');
      assert.equal(writes.at(-1).owner, owner);
      assert.equal(writes.at(-1).repo, 'project');
    } else {
      // Preserve the cross-repository refusal at the real filesystem/entrypoint boundary.
      await assert.rejects(main({ github, context: runtime, core }), /Test publication binding mismatch/u);
      assert.deepEqual(writes, []);
      assert.deepEqual(messages, []);
      assert.deepEqual(summary, []);
    }
    assert.equal(Object.hasOwn(runtime, 'runAttempt'), false);
  });
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
