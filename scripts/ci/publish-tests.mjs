import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');

/** Require exact same-run outputs and closed destination paths before any remote mutation. */
export function validateTests({ context, receipt, assets }) {
  const repository = `${context.repo.owner}/${context.repo.repo}`;
  const run = `${context.runId}-${context.runAttempt}`;
  const metric = `.github/metrics/tests/${run}.json`;
  const names = [metric, 'docs/assets/test-convergence.svg'].sort();
  if (context.eventName !== 'push' || context.ref !== 'refs/heads/main'
    || !/^[a-f0-9]{40}$/u.test(context.sha) || !/^\d+-\d+$/u.test(run)) throw new Error('Only exact main runs may publish test feedback');
  if (receipt.source !== context.sha || receipt.repository !== repository || receipt.run !== run
    || JSON.stringify(Object.keys(assets).sort()) !== JSON.stringify(names)
    || JSON.stringify(Object.keys(receipt.files).sort()) !== JSON.stringify(names)) throw new Error('Test publication binding mismatch');
  for (const name of names) {
    if (receipt.files[name] !== hash(assets[name])) throw new Error('Test publication digest mismatch');
  }
  const sample = JSON.parse(assets[metric]);
  if (sample.version !== 1 || sample.repository !== repository || sample.source !== context.sha || sample.run !== run
    || sample.scope !== receipt.scope || !Number.isInteger(sample.tests) || sample.tests <= 0
    || !Number.isInteger(sample.shards) || sample.shards <= 0
    || !Number.isFinite(sample.wall_seconds) || sample.wall_seconds <= 0) throw new Error('Invalid test measurement');
  return names;
}

/** Reuse the existing reviewed-update job; never push measurements directly through protected main. */
export async function publishTests({ github, context, receipt, assets }) {
  const names = validateTests({ context, receipt, assets });
  const repository = context.repo;
  const current = (await github.rest.git.getRef({ ...repository, ref: 'heads/main' })).data.object.sha;
  if (current !== context.sha) return { status: 'superseded' };
  const branch = `automation/test-feedback-${receipt.run}`;
  let head;
  try {
    head = (await github.rest.git.getRef({ ...repository, ref: `heads/${branch}` })).data.object.sha;
  } catch (error) {
    if (error.status !== 404) throw error;
    head = (await github.rest.git.createRef({ ...repository, ref: `refs/heads/${branch}`, sha: context.sha })).data.object.sha;
  }
  if (head === context.sha) {
    const { createCommitOnBranch } = await github.graphql(`mutation($input: CreateCommitOnBranchInput!) {
      createCommitOnBranch(input: $input) { commit { oid } }
    }`, { input: {
      branch: { repositoryNameWithOwner: `${repository.owner}/${repository.repo}`, branchName: branch },
      expectedHeadOid: context.sha,
      message: { headline: 'Publish accepted test matrix measurements' },
      fileChanges: { additions: names.map((name) => ({ path: name, contents: Buffer.from(assets[name]).toString('base64') })) },
    } });
    head = createCommitOnBranch.commit.oid;
  }
  const { data: commit } = await github.rest.repos.getCommit({ ...repository, ref: head });
  if (!commit.commit.verification.verified || commit.parents.length !== 1 || commit.parents[0].sha !== context.sha
    || JSON.stringify(commit.files.map((file) => file.filename).sort()) !== JSON.stringify(names)) throw new Error('Unexpected feedback commit');
  for (const name of names) {
    const { data } = await github.rest.repos.getContent({ ...repository, ref: head, path: name });
    if (data.type !== 'file' || data.encoding !== 'base64'
      || !Buffer.from(data.content, 'base64').equals(Buffer.from(assets[name]))) throw new Error('Feedback readback mismatch');
  }
  const url = `https://github.com/${repository.owner}/${repository.repo}`;
  const body = [
    '**What:** Publish accepted test scheduling measurements and the CI-generated convergence figure.',
    '**Why:** Make runner allocation, prediction error and observed test time reviewable.',
    '**How:** Retain an independent per-run aggregate; regenerate the plot from compatible accepted records. Cache data is disposable.',
    `**Validation:** [Source](${url}/commit/${context.sha}), [passing run](${url}/actions/runs/${context.runId}).`,
    '- [x] Verify every frozen test assignment and combine raw coverage.',
    '- [x] Validate exact source/run/digest bindings and signed output readback.',
    '- [ ] Review and merge the generated evidence.',
    `![Test matrix convergence](${url}/raw/${head}/docs/assets/test-convergence.svg)`,
    'Prepared by GitHub Actions. Review contact: repository CODEOWNERS.',
  ].join('\n\n');
  const { data: existing } = await github.rest.pulls.list({ ...repository, head: `${repository.owner}:${branch}`, base: 'main', state: 'all' });
  let request = existing[0];
  if (!request) {
    try {
      request = (await github.rest.pulls.create({ ...repository, head: branch, base: 'main', title: 'Publish test matrix convergence', body })).data;
    } catch (error) {
      if (error.status !== 403 || !error.message.includes('not permitted to create or approve pull requests')) throw error;
      return { status: 'review-required', url: `${url}/compare/main...${branch}?expand=1`, revision: head };
    }
  }
  if (request.state === 'open') await github.rest.actions.createWorkflowDispatch({ ...repository, workflow_id: 'ci.yml', ref: branch });
  return { status: request.state === 'open' ? 'proposed' : 'closed', url: request.html_url, revision: head };
}

/** Load only this run's allowlisted bundle inside the existing serialized publication job. */
export async function main({ github, context, core }) {
  const root = '.cache/ci/tests';
  // Actions Context keeps repo on its prototype; explicitly read the publication contract.
  const publication = {
    repo: context.repo,
    eventName: context.eventName,
    ref: context.ref,
    sha: context.sha,
    runId: context.runId,
    runAttempt: process.env.GITHUB_RUN_ATTEMPT,
  };
  const receipt = JSON.parse(await readFile(`${root}/publication.json`, 'utf8'));
  // Never use artifact-provided paths as filesystem input before closing the destination set.
  const names = [`.github/metrics/tests/${publication.runId}-${publication.runAttempt}.json`, 'docs/assets/test-convergence.svg'];
  const assets = Object.fromEntries(await Promise.all(names.map(async (name) => [name, await readFile(path.join(root, 'publication', name))])));
  const result = await publishTests({ github, context: publication, receipt, assets });
  core.info(JSON.stringify(result));
  if (result.status === 'review-required') core.warning('Open the signed feedback proposal from the compare link; required review remains intact.');
  await core.summary.addHeading('Test matrix evidence').addRaw(`${result.status}${result.url ? `: ${result.url}` : ''}`).write();
}
