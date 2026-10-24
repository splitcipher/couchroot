'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');

function policy(contents, options = {}) {
  const source = path.resolve(__dirname, '../agent/service/policy.js');
  const real = createRequire(source);
  let reads = 0;
  const mock = {
    lstatSync(file) {
      assert.equal(file, '/etc/prd_info.ini');
      if (options.error) throw options.error;
      return {
        isFile: () => true,
        isSymbolicLink: () => options.symlink === true,
        size: Buffer.byteLength(contents),
      };
    },
    readFileSync(file) {
      assert.equal(file, '/etc/prd_info.ini');
      reads++;
      return Buffer.from(contents);
    },
  };
  const module = { exports: {} };
  vm.runInNewContext(fs.readFileSync(source, 'utf8'), {
    module,
    exports: module.exports,
    Buffer,
    require: (name) => (name === 'fs' ? mock : real(name)),
  });
  return { verify: () => module.exports.verifyFirmware({ firmware: 'T-EXAMPLE-1.0' }), reads: () => reads };
}

test('firmware matching keeps existing exact-line and CRLF semantics', () => {
  for (const content of [
    'Version=T-EXAMPLE-1.0;\n',
    'Other=value\r\nVersion=T-EXAMPLE-1.0;\r\n',
    'Version=other;\nVersion=T-EXAMPLE-1.0;\n',
  ]) assert.doesNotThrow(policy(content).verify);
});

test('mismatch exposes exact observed version and expected line, without other device fields', () => {
  assert.throws(
    policy('Serial=private-value\nVersion=T-EXAMPLE-2.0;\nOther=private-too\n').verify,
    (error) => error.message === 'Firmware mismatch in /etc/prd_info.ini: expected "Version=T-EXAMPLE-1.0;"; observed ["Version=T-EXAMPLE-2.0;"]'
  );
});

test('diagnostic quotes whitespace and controls without accepting normalized firmware', () => {
  for (const line of [' Version=T-EXAMPLE-1.0;', 'Version=T-EXAMPLE-1.0; ', 'version=T-EXAMPLE-1.0;', 'Version=T-EXAMPLE-1.0;\t\0']) {
    assert.throws(policy(line + '\n').verify, (error) => {
      assert(error.message.includes(JSON.stringify(line)));
      assert(!error.message.includes('\0'));
      return true;
    });
  }
});

test('missing and multiple mismatched version lines remain distinguishable', () => {
  assert.throws(policy('Serial=private\n').verify, /observed \[\]$/);
  assert.throws(policy('Version=first;\nVersion=second;\n').verify, /observed \["Version=first;","Version=second;"\]$/);
});

test('oversized diagnostic is explicitly truncated within the status error budget', () => {
  assert.throws(policy('Version=' + 'x'.repeat(1000)).verify, (error) => {
    assert(error.message.endsWith(' [truncated]'));
    assert(('firmware verification: ' + error.message).length <= 300);
    return true;
  });
});

test('file and read guards still refuse before producing firmware values', () => {
  for (const [content, options, pattern] of [
    ['Version=T-EXAMPLE-1.0;', { symlink: true }, /Invalid configuration file/],
    ['x'.repeat(65537), {}, /Invalid configuration file/],
    ['', { error: Object.assign(Error('permission denied'), { code: 'EACCES' }) }, /permission denied/],
  ]) {
    const p = policy(content, options);
    assert.throws(p.verify, pattern);
    assert.equal(p.reads(), 0);
  }
});
