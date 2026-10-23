// Parse shipped scripts with the ES5 grammar used by the compatibility contract.
const fs = require('node:fs');
const path = require('node:path');
const acorn = require('acorn');

const web = path.join(__dirname, '..', 'web');
const files = fs.readdirSync(web).filter(name => name.endsWith('.js')).sort();
if (!files.length) throw new Error('No web/*.js files found');
for (const name of files) {
  try {
    acorn.parse(fs.readFileSync(path.join(web, name), 'utf8'), {
      ecmaVersion: 5,
      sourceType: 'script',
    });
  } catch (error) {
    console.error('web/' + name + ': ' + error.message);
    process.exitCode = 1;
  }
}
if (!process.exitCode) console.log('ES5 syntax: ' + files.length + ' shipped scripts passed');
