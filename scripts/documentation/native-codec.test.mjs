// Independent maintained JavaScript codec verifies the shared Python wire and semantic-hash contract.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {decode, encode, Tag} from 'cbor2';
import {sortLengthFirstDeterministic} from 'cbor2/sorts';

const vectors = JSON.parse(readFileSync(new URL('../../tests/native/resources/codec-v1.json', import.meta.url), 'utf8'));
const options = {sortKeys: sortLengthFirstDeterministic, collapseBigInts: true};

// Fixture wrappers preserve bytes and signed 64-bit integers without JSON's number precision loss.
function materialize(value) {
  if (Array.isArray(value)) return value.map(materialize);
  if (value && typeof value === 'object') {
    if (Object.keys(value).length === 1 && '$bytes' in value) return new Uint8Array(Buffer.from(value.$bytes, 'hex'));
    if (Object.keys(value).length === 1 && '$integer' in value) return BigInt(value.$integer);
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, materialize(child)]));
  }
  return value;
}

// This test-only profile guard excludes values supported by CBOR but excluded from native version one.
function admissible(value) {
  assert(!(value instanceof Tag));
  if (typeof value === 'number' || typeof value === 'bigint') {
    if (typeof value === 'number') assert(Number.isSafeInteger(value));
    assert(BigInt(value) >= -(2n ** 63n) && BigInt(value) < 2n ** 63n);
  } else if (Array.isArray(value)) value.forEach(admissible);
  else if (value && typeof value === 'object' && !(value instanceof Uint8Array)) {
    assert.equal(Object.getPrototypeOf(value), Object.prototype);
    Object.values(value).forEach(admissible);
  } else assert(value === null || typeof value === 'boolean' || typeof value === 'string' || value instanceof Uint8Array);
}

function profile(raw) {
  // Decode plain Uint8Array input: Node Buffer has a JSON conversion hook that changes byte-string re-encoding.
  const value = decode(new Uint8Array(raw), {
    ignoreGlobalTags: true, requirePreferred: true, rejectDuplicateKeys: true,
    rejectStreaming: true, rejectFloats: true, rejectUndefined: true,
    sortKeys: sortLengthFirstDeterministic,
  });
  admissible(value);
  assert.equal(Buffer.from(encode(value, options)).toString('hex'), Buffer.from(raw).toString('hex'));
  return value;
}

for (const vector of vectors.valid) {
  test(`native CBOR/hash vector: ${vector.name}`, () => {
    const raw = Buffer.from(encode(materialize(vector.value), options));
    assert.equal(raw.toString('hex'), vector.hex);
    profile(raw);
    assert.equal(createHash('sha256').update('witful-native-cbor-v1\0').update(raw).digest('hex'), vector.sha256);
  });
}
for (const raw of vectors.invalid) {
  test(`native CBOR rejection: ${raw}`, () => assert.throws(() => profile(Buffer.from(raw, 'hex'))));
}
