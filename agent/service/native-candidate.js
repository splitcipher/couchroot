'use strict';
// Package consistency checks, not device qualification or worker selection.
// Package authenticity remains the existing signed-package installation boundary.
const fs = require('fs'),
  path = require('path');
const { hash } = require('./policy');
const FILES = [
  'native-manifest.json',
  'native-worker',
  'native-app-launcher',
  'native-process-observer',
];
const artifactsFor = (schema) =>
  schema === 2 ? FILES.slice(1) : FILES.slice(1, 3);
const HEX = /^[a-f0-9]{64}$/;
const NEEDED = [
  'libc.so.6',
  'libdl.so.2',
  'libpthread.so.0',
  'librt.so.1',
  'libgcc_s.so.1',
  'ld-linux.so.3',
];
function requireValue(ok, reason) {
  if (!ok) throw Error(reason);
}
function record(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function keys(value, expected) {
  return (
    record(value) &&
    Object.keys(value).sort().join('\0') === expected.slice().sort().join('\0')
  );
}
function present(file) {
  try {
    fs.lstatSync(file);
    return true;
  } catch (e) {
    if (e.code === 'ENOENT') return false;
    throw e;
  }
}
function readBounded(file, limit) {
  const fd = fs.openSync(
    file,
    fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK
  );
  try {
    const before = fs.fstatSync(fd);
    requireValue(
      before.isFile() && before.size <= limit,
      'candidate-file-type-or-size'
    );
    const bytes = Buffer.alloc(before.size + 1);
    let used = 0;
    while (used < bytes.length) {
      const n = fs.readSync(fd, bytes, used, bytes.length - used, null);
      if (!n) break;
      used += n;
    }
    requireValue(
      used === before.size && fs.fstatSync(fd).size === before.size,
      'candidate-file-changed'
    );
    return bytes.subarray(0, used);
  } finally {
    fs.closeSync(fd);
  }
}
function glibc(value, minor) {
  if (typeof value !== 'string' || !/^2\.[0-9]+\.[0-9]+$/.test(value))
    return false;
  const parts = value.split('.').map(Number);
  return parts[1] < minor || (parts[1] === minor && parts[2] === 0);
}
function validateManifest(m, device) {
  requireValue(
    keys(m, [
      'schema',
      'kind',
      'implementation',
      'selection',
      'device_qualified',
      'candidate_profiles',
      'source',
      'toolchain',
      'reproducible_builds',
      'artifacts',
      'runtime_loads',
    ]),
    'candidate-manifest-fields'
  );
  requireValue(
    [1, 2].includes(m.schema) &&
      m.kind === 'native-worker-candidate' &&
      m.implementation === 'native-prototype' &&
      m.selection === 'managed' &&
      m.device_qualified === false &&
      m.reproducible_builds === 2,
    'candidate-manifest-contract'
  );
  requireValue(
    ['qn90a', 's90d'].includes(device) &&
      Array.isArray(m.candidate_profiles) &&
      m.candidate_profiles.includes(device) &&
      new Set(m.candidate_profiles).size === m.candidate_profiles.length &&
      m.candidate_profiles.every((p) => ['qn90a', 's90d'].includes(p)),
    'candidate-profile'
  );
  requireValue(
    record(m.source) &&
      Object.keys(m.source).length <= 128 &&
      Object.keys(m.source).every(
        (p) =>
          (/^(native-worker\/[a-z0-9-]+\.(c|h)|native-worker\/build\.sh|native-launcher\/(app-launcher\.c|build\.sh))$/.test(
            p
          ) ||
            /^native-worker\/mqtt\/(bridge|commands|config|discovery|fd|foreground|metrics|state|wire)\.h$/.test(
              p
            ) ||
            (m.schema === 2 &&
              /^native-observer\/(process-observer\.c|service-profile\.h|build\.sh)$/.test(
                p
              ))) &&
          typeof m.source[p] === 'string' &&
          HEX.test(m.source[p])
      ),
    'candidate-source-manifest'
  );
  for (const name of [
    'native-worker/worker.c',
    'native-worker/build.sh',
    'native-launcher/app-launcher.c',
    'native-launcher/build.sh',
  ])
    requireValue(
      Object.prototype.hasOwnProperty.call(m.source, name),
      'candidate-source-missing'
    );
  if (m.schema === 2)
    for (const name of [
      'native-observer/process-observer.c',
      'native-observer/build.sh',
    ])
      requireValue(
        Object.prototype.hasOwnProperty.call(m.source, name),
        'candidate-source-missing'
      );
  requireValue(
    keys(m.toolchain, ['image', 'compiler']) &&
      typeof m.toolchain.image === 'string' &&
      typeof m.toolchain.compiler === 'string' &&
      /^sha256:[a-f0-9]{64}$/.test(m.toolchain.image) &&
      /^\d+(?:\.\d+){1,2}$/.test(m.toolchain.compiler),
    'candidate-toolchain'
  );
  requireValue(
    keys(m.runtime_loads, ['json_c', 'crypto']) &&
      JSON.stringify(m.runtime_loads.json_c) ===
        JSON.stringify(['libjson-c.so.5', 'libjson-c.so.4']) &&
      JSON.stringify(m.runtime_loads.crypto) ===
        JSON.stringify(['libcrypto.so.1.1', 'libcrypto.so.3']),
    'candidate-runtime-libraries'
  );
  requireValue(
    keys(m.artifacts, artifactsFor(m.schema)),
    'candidate-artifact-set'
  );
  for (const name of artifactsFor(m.schema)) {
    const a = m.artifacts[name];
    requireValue(
      keys(a, [
        'sha256',
        'size',
        'abi',
        'interpreter',
        'needed',
        'glibc_max',
      ]) &&
        typeof a.sha256 === 'string' &&
        HEX.test(a.sha256) &&
        Number.isSafeInteger(a.size) &&
        a.size >= 52 &&
        a.size <= 4 * 1024 * 1024,
      'candidate-artifact-metadata'
    );
    requireValue(
      a.abi === 'armv7-eabi5-softfp' &&
        a.interpreter === '/lib/ld-linux.so.3' &&
        glibc(a.glibc_max, name === 'native-worker' ? 28 : 17),
      'candidate-artifact-abi'
    );
    if (name === 'native-process-observer')
      requireValue(a.size <= 128 * 1024, 'candidate-observer-size');
    requireValue(
      Array.isArray(a.needed) &&
        a.needed.includes('libc.so.6') &&
        new Set(a.needed).size === a.needed.length &&
        a.needed.every((n) => NEEDED.includes(n)),
      'candidate-artifact-dependencies'
    );
  }
}
function loadCandidate(payload, device) {
  const found = FILES.filter((name) => present(path.join(payload, name)));
  const packagePath = path.join(payload, 'manifest.json');
  const packageManifest = present(packagePath)
    ? JSON.parse(readBounded(packagePath, 65536))
    : null;
  if (
    !found.length &&
    (!record(packageManifest) ||
      !FILES.some((name) =>
        Object.prototype.hasOwnProperty.call(packageManifest, name)
      ))
  )
    return null;
  requireValue(
    found.includes(FILES[0]) && record(packageManifest),
    'candidate-package-incomplete'
  );
  const manifestBytes = readBounded(path.join(payload, FILES[0]), 65536);
  requireValue(
    HEX.test(packageManifest[FILES[0]]) &&
      hash(manifestBytes) === packageManifest[FILES[0]],
    'candidate-manifest-digest'
  );
  const manifest = JSON.parse(manifestBytes);
  validateManifest(manifest, device);
  const expected = [FILES[0], ...artifactsFor(manifest.schema)];
  requireValue(
    found.length === expected.length &&
      expected.every((n) => found.includes(n)) &&
      FILES.every(
        (n) =>
          expected.includes(n) ||
          !Object.prototype.hasOwnProperty.call(packageManifest, n)
      ),
    'candidate-package-incomplete'
  );
  const artifacts = {};
  for (const name of artifactsFor(manifest.schema)) {
    const bytes = readBounded(path.join(payload, name), 4 * 1024 * 1024),
      a = manifest.artifacts[name];
    requireValue(
      bytes.length === a.size &&
        hash(bytes) === a.sha256 &&
        packageManifest[name] === a.sha256,
      'candidate-artifact-digest'
    );
    requireValue(
      bytes.subarray(0, 7).equals(Buffer.from([127, 69, 76, 70, 1, 1, 1])) &&
        [2, 3].includes(bytes.readUInt16LE(16)) &&
        bytes.readUInt16LE(18) === 40 &&
        bytes.readUInt32LE(36) >>> 24 === 5 &&
        !(bytes.readUInt32LE(36) & 0x400),
      'candidate-artifact-header'
    );
    if (
      name === 'native-process-observer' &&
      bytes.includes(Buffer.from('--service-supervise'))
    )
      requireValue(
        Object.prototype.hasOwnProperty.call(
          manifest.source,
          'native-observer/service-profile.h'
        ),
        'candidate-source-missing'
      );
    for (const marker of [
      '--test-child-fault',
      'COUCHROOT_NATIVE_JOB_INTENT_FAULT',
      'host-test-without-Smack',
      'COUCHROOT_IO_TEST_PATH',
    ])
      requireValue(
        !bytes.includes(Buffer.from(marker)),
        'candidate-test-controls'
      );
    artifacts[name] = Object.freeze({ sha256: a.sha256, size: a.size });
  }
  return Object.freeze({
    manifest_sha256: hash(manifestBytes),
    implementation: manifest.implementation,
    artifacts: Object.freeze(artifacts),
  });
}
function candidateStatus(payload, device) {
  const checked_at = new Date().toISOString();
  try {
    const candidate = loadCandidate(payload, device);
    return Object.freeze(
      candidate
        ? {
            state: 'verified',
            checked_at,
            manifest_sha256: candidate.manifest_sha256,
            device_qualified: false,
          }
        : { state: 'absent', checked_at }
    );
  } catch (e) {
    const reason = /^candidate-[a-z-]+$/.test(e.message)
      ? e.message
      : 'candidate-unreadable';
    return Object.freeze({
      state: 'invalid',
      checked_at,
      reason,
      device_qualified: false,
    });
  }
}
module.exports = { loadCandidate, candidateStatus };
