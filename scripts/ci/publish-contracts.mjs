import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { isDeepStrictEqual } from 'node:util';

const DIRECTORY = 'scripts/ci/provider_contracts/data';
const NAMES = ['github.json', 'gitlab.json', 'manifest.json'];
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

/** Compare selected contracts, retaining newer full-source observations in the run artifact. */
export function sameContracts(before, after) {
  const selected = (assets) => {
    const manifest = JSON.parse(assets['manifest.json']);
    // Only these observation fields may drift without changing the committed contract.
    return Object.fromEntries(Object.entries(manifest).map(([name, entry]) => [name,
      Object.fromEntries(Object.entries(entry).filter(([key]) => !['revision', 'source_sha256', 'latest_observed_at'].includes(key))),
    ]));
  };
  return ['github.json', 'gitlab.json'].every((name) => Buffer.from(before[name]).equals(Buffer.from(after[name])))
    && isDeepStrictEqual(selected(before), selected(after));
}

/** Validate the complete, source-bound renewal before granting it any repository write. */
export function validateBundle({ assets, provenance, observation, source, lock }) {
  if (provenance.source_revision !== source || provenance.poetry_lock_sha256 !== sha256(lock)) throw new Error('Contract source or SDK lock mismatch');
  if (JSON.stringify(Object.keys(assets).sort()) !== JSON.stringify(NAMES)) throw new Error('Unexpected contract publication paths');
  for (const name of NAMES) {
    if (sha256(assets[name]) !== provenance.files[name]) throw new Error(`Contract digest mismatch: ${name}`);
  }
  const manifest = JSON.parse(assets['manifest.json']);
  if (JSON.stringify(manifest) !== JSON.stringify(provenance.vendor_contracts)) throw new Error('Contract provenance mismatch');
  if (!observation.latest || !observation.current || observation.manifest_sha256 !== sha256(assets['manifest.json'])) throw new Error('Missing current observation');
  for (const name of ['github', 'gitlab']) {
    if (!/^[a-f0-9]{40}$/u.test(manifest[name].revision)
      || observation.revisions[name] !== manifest[name].revision
      || manifest[name].snapshot_sha256 !== sha256(assets[`${name}.json`])) throw new Error('Contract snapshot or revision mismatch');
  }
}

/** Read exact GitHub file bytes; missing files and transport failures remain errors. */
async function content(github, repository, ref, name) {
  const { data } = await github.rest.repos.getContent({ ...repository, ref, path: `${DIRECTORY}/${name}` });
  if (data.type !== 'file' || data.encoding !== 'base64') throw new Error('Contract is not an encoded regular file');
  return Buffer.from(data.content, 'base64');
}

/** Propose passing main-run outputs through a signed commit without bypassing branch review. */
export async function publishContracts({ github, context, assets }) {
  if (context.eventName !== 'push' || context.ref !== 'refs/heads/main' || !/^[a-f0-9]{40}$/u.test(context.sha)) throw new Error('Only exact main pushes publish contracts');
  if (JSON.stringify(Object.keys(assets).sort()) !== JSON.stringify(NAMES)) throw new Error('Unexpected contract publication paths');
  const repository = context.repo;
  const current = await github.rest.git.getRef({ ...repository, ref: 'heads/main' });
  if (current.data.object.sha !== context.sha) return { status: 'superseded' };
  const baseline = Object.fromEntries(await Promise.all(NAMES.map(async (name) => [name, await content(github, repository, context.sha, name)])));
  if (sameContracts(baseline, assets)) return { status: 'unchanged' };
  const changed = [];
  for (const name of NAMES) {
    if (!baseline[name].equals(Buffer.from(assets[name]))) changed.push(name);
  }
  if (!changed.length) return { status: 'unchanged' };

  // Bind proposals to both source and renewed inputs; a rerun can observe another upstream revision.
  const branch = `automation/provider-contracts-${context.sha}-${sha256(assets['manifest.json']).slice(0, 16)}`;
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
      message: { headline: 'Refresh tested provider API contracts' },
      fileChanges: { additions: changed.map((name) => ({ path: `${DIRECTORY}/${name}`, contents: Buffer.from(assets[name]).toString('base64') })) },
    } });
    head = createCommitOnBranch.commit.oid;
  }
  const { data: commit } = await github.rest.repos.getCommit({ ...repository, ref: head });
  if (!commit.commit.verification.verified || commit.parents.length !== 1 || commit.parents[0].sha !== context.sha
    || JSON.stringify(commit.files.map((file) => file.filename).sort()) !== JSON.stringify(changed.map((name) => `${DIRECTORY}/${name}`).sort())) {
    throw new Error('Proposal contains unverified or unexpected changes; preserve it for review');
  }
  for (const name of NAMES) {
    if (!(await content(github, repository, head, name)).equals(Buffer.from(assets[name]))) throw new Error('Proposal readback differs from the tested renewal');
  }
  const url = `https://github.com/${repository.owner}/${repository.repo}`;
  const body = [
    '**What:** Renew the provider contract baseline from passing main CI.',
    '**Why:** Upstream specification updates should reach compatibility tests without a metadata-only failure.',
    '**How:** Reuse this run\'s exact tested snapshots and pins. Application code and locked SDKs stay unchanged.',
    `**Validation:** [Source](${url}/commit/${context.sha}), [tested run](${url}/actions/runs/${context.runId}), [proposal](${url}/commit/${head}).`,
    '- [x] Refresh official sources and pass contract tests with locked SDKs.',
    '- [x] Verify artifact digests, source and signed commit readback.',
    '- [ ] Review the generated diff and require CI on this proposal.',
    'Prepared by GitHub Actions. Review contact: repository CODEOWNERS. This job does not approve or merge.',
  ].join('\n\n');
  const { data: existing } = await github.rest.pulls.list({ ...repository, head: `${repository.owner}:${branch}`, base: 'main', state: 'all' });
  let request = existing[0];
  if (!request) {
    try {
      request = (await github.rest.pulls.create({ ...repository, head: branch, base: 'main', title: 'Refresh tested provider API contracts', body })).data;
    } catch (error) {
      // The platform can disallow bot-created PRs. Retain the signed proposal and expose an actionable compare link.
      if (error.status !== 403 || !error.message.includes('not permitted to create or approve pull requests')) throw error;
      return { status: 'review-required', revision: head, url: `${url}/compare/main...${branch}?expand=1` };
    }
  }
  // GITHUB_TOKEN-created commits do not emit push/PR CI. Dispatch the existing full pipeline explicitly.
  if (request.state === 'open') await github.rest.actions.createWorkflowDispatch({ ...repository, workflow_id: 'ci.yml', ref: branch });
  return { status: request.state === 'open' ? 'proposed' : 'closed', revision: head, url: request.html_url };
}

/** Consume only this run's artifact and immutable checkout in the maintained GitHub SDK action. */
export async function main({ github, context, core }) {
  const root = '.cache/provider-contracts';
  const assets = Object.fromEntries(await Promise.all(NAMES.map(async (name) => [name, await readFile(path.join(root, 'contracts', name))])));
  validateBundle({
    assets,
    provenance: JSON.parse(await readFile(path.join(root, 'provenance.json'), 'utf8')),
    observation: JSON.parse(await readFile(path.join(root, 'latest.json'), 'utf8')),
    source: context.sha,
    lock: await readFile('poetry.lock'),
  });
  const result = await publishContracts({ github, context, assets });
  if (result.status === 'review-required') core.warning('Repository policy disables bot-created PRs. Open the signed proposal using the compare link.');
  core.info(JSON.stringify(result));
  await core.summary.addHeading('Provider contract renewal').addRaw(`${result.status}${result.url ? `: ${result.url}` : ''}`).write();
}
