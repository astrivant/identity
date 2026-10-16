import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const packageInfo = require('./package.json');
const limit = 16 * 1024 * 1024;

// Disable SDK diagnostics before import; no source text belongs in worker logs.
console.log = console.info = console.warn = console.error = () => {};
process.env.DO_NOT_TRACK = '1';
process.env.CODEGRAPH_TELEMETRY = '0';
process.umask(0o077);

let graph;
try {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of process.stdin) {
    bytes += chunk.length;
    if (bytes > limit) throw new Error('input_limit');
    chunks.push(chunk);
  }
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  if (!Array.isArray(input.sources) || input.sources.length > 2048) throw new Error('invalid');
  const root = '/work/source';
  await fs.mkdir(root, { mode: 0o700 });
  const paths = [];
  for (const source of input.sources) {
    if (typeof source.path !== 'string' || typeof source.text !== 'string'
        || !source.path.endsWith('.py') || source.path.includes('\\')
        || source.path.split('/').some(part => ['', '.', '..', '.git', '.codegraph'].includes(part))) {
      throw new Error('invalid');
    }
    const destination = path.join(root, source.path);
    await fs.mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
    await fs.writeFile(destination, source.text, { flag: 'wx', mode: 0o600 });
    paths.push(source.path);
  }
  // Only copied Python bytes reach the SDK; repository config and installers never run.
  const { CodeGraph } = await import('./dist/index.js');
  graph = await CodeGraph.init(root);
  await graph.indexAll();
  const files = graph.getFiles();
  if (files.length !== paths.length || files.some(file => file.errors?.length)) throw new Error('coverage');
  const health = graph.getIndexHealth();
  if (health.needsReindex.length || health.parseErrors.length || graph.getPendingReferenceCount() || graph.getIndexState() !== 'complete') throw new Error('incomplete');
  const nodes = graph.getNodesInFiles(paths).map(node => ({
    id: node.id, name: node.name, path: node.filePath, kind: node.kind,
    start: node.startLine, end: node.endLine,
  })).sort((a, b) => a.id.localeCompare(b.id));
  const ids = new Set(nodes.map(node => node.id));
  const edges = graph.getOutgoingEdgesFrom([...ids]).map(edge => ({
    source: edge.source, target: edge.target, kind: edge.kind, provenance: edge.provenance ?? 'unknown',
  }));
  if (edges.some(edge => !ids.has(edge.target))) throw new Error('unqualified_edge');
  edges.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
  const output = JSON.stringify({ nodes, edges, indexer: packageInfo.version, unresolved: paths.reduce((count, file) => count + graph.getUnresolvedReferencesInFile(file).length, 0) });
  if (Buffer.byteLength(output) > limit) throw new Error('output_limit');
  graph.close();
  graph = undefined;
  process.stdout.write(output);
} catch {
  process.exitCode = 1;
} finally {
  if (graph) graph.close();
}
