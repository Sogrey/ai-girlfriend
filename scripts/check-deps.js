// postinstall sanity check. Never fails the install; only reports.
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..');
const needed = [
  'node_modules/three/package.json',
  'node_modules/@pixiv/three-vrm/package.json',
  'node_modules/electron/package.json',
];
let missing = [];
for (const p of needed) {
  if (!fs.existsSync(path.join(root, p))) missing.push(p);
}
if (missing.length) {
  console.log('[check-deps] missing: ' + missing.join(', '));
} else {
  console.log('[check-deps] all node deps present.');
}
process.exit(0);
