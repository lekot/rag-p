// Copy non-TypeScript assets (icons, JSON descriptors) from source dirs into dist/.
// Replaces the gulp-based icon-copy step from the n8n starter so we don't need
// gulp as a dev dependency just to move a handful of SVGs.
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const DIST = path.join(ROOT, 'dist');
const SOURCE_DIRS = ['nodes', 'credentials'];
const COPY_EXTENSIONS = new Set(['.svg', '.png', '.json']);

function walk(dir, fn) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, fn);
    } else if (entry.isFile()) {
      fn(full);
    }
  }
}

let copied = 0;
for (const sourceDir of SOURCE_DIRS) {
  const absSource = path.join(ROOT, sourceDir);
  if (!fs.existsSync(absSource)) continue;
  walk(absSource, (file) => {
    const ext = path.extname(file).toLowerCase();
    if (!COPY_EXTENSIONS.has(ext)) return;
    const rel = path.relative(ROOT, file);
    const target = path.join(DIST, rel);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(file, target);
    copied += 1;
  });
}

console.log(`copy-icons: copied ${copied} asset(s) into dist/`);
