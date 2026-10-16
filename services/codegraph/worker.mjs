import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const packageInfo = require('./package.json');
const limit = Number(process.env.WITFUL_CODEGRAPH_BYTES ?? 16 * 1024 * 1024);
const fileLimit = Number(process.env.WITFUL_CODEGRAPH_FILES ?? 2048);

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
  if (!Number.isSafeInteger(limit) || limit < 1 || !Number.isSafeInteger(fileLimit) || fileLimit < 1) throw new Error('invalid_limit');
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  if (input.operation === 'capabilities') {
    const grammar = require('./dist/extraction/grammars.js');
    const languages = [...new Set([...grammar.getSupportedLanguages(), ...Object.values(grammar.EXTENSION_MAP)])].sort();
    process.stdout.write(JSON.stringify({ languages, extensions: grammar.EXTENSION_MAP }));
    process.exit(0);
  }
  if (!Array.isArray(input.sources) || input.sources.length > fileLimit) throw new Error('invalid');
  const root = '/work/source';
  await fs.mkdir(root, { mode: 0o700 });
  const paths = [];
  const controls = new Set();
  for (const source of input.sources) {
    if (typeof source.path !== 'string' || typeof source.text !== 'string'
        || typeof source.digest !== 'string' || !/^[a-f0-9]{64}$/.test(source.digest) || source.path.includes('\\')
        || source.path.split('/').some(part => ['', '.', '..', '.git', '.codegraph'].includes(part))) {
      throw new Error('invalid');
    }
    // Repository-owned SDK settings and ignore rules cannot override signed enrollment inputs.
    if (['codegraph.json', '.gitignore'].includes(path.basename(source.path))) {
      controls.add(source.path);
      continue;
    }
    const destination = path.join(root, source.path);
    await fs.mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
    await fs.writeFile(destination, source.text, { flag: 'wx', mode: 0o600 });
    paths.push(source.path);
  }
  // The SDK owns all language detection, including compound suffixes, content-dependent dialects and contextual files.
  // Copied manifests are inert framework input; no repository installer or source program executes.
  const { CodeGraph } = await import('./dist/index.js');
  const { detectLanguage, isLanguageSupported, isFileLevelOnlyLanguage } = require('./dist/extraction/grammars.js');
  const overrides = input.extensions ?? {};
  if (typeof overrides !== 'object' || Array.isArray(overrides) || overrides === null
      || Object.entries(overrides).some(([suffix, language]) => !/^\.[a-z0-9][a-z0-9_-]{0,63}$/.test(suffix)
        || typeof language !== 'string' || !isLanguageSupported(language))) throw new Error('invalid_language');
  // Only signed operator overrides become SDK configuration. Repository-provided configuration remains inert.
  await fs.writeFile(path.join(root, 'codegraph.json'), JSON.stringify({ extensions: overrides }), { flag: 'wx', mode: 0o600 });
  graph = await CodeGraph.init(root);
  await graph.indexAll();
  const files = graph.getFiles();
  if (files.some(file => file.errors?.length)) throw new Error('coverage');
  const indexed = new Map(files.map(file => [file.path, file]));
  if (files.some(file => !paths.includes(file.path))) throw new Error('unexpected_file');
  const coverage = input.sources.map(source => {
    const language = detectLanguage(source.path, source.text, overrides, root);
    const file = indexed.get(source.path);
    const state = controls.has(source.path) ? 'worker-control'
      : file ? (isFileLevelOnlyLanguage(file.language) ? 'file-only' : 'indexed')
        : isLanguageSupported(language) ? 'sdk-omitted' : 'unsupported';
    return { path: source.path, digest: source.digest, coverage: state, language: file?.language ?? language };
  });
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
  const output = JSON.stringify({ nodes, edges, files: coverage, indexer: packageInfo.version, unresolved: paths.reduce((count, file) => count + graph.getUnresolvedReferencesInFile(file).length, 0) });
  if (Buffer.byteLength(output) > limit) throw new Error('output_limit');
  graph.close();
  graph = undefined;
  process.stdout.write(output);
} catch {
  process.exitCode = 1;
} finally {
  if (graph) graph.close();
}
