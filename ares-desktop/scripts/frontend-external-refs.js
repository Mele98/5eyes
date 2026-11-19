// N-875-02 (H3/I-04): Externe CDN-/Font-Verweise im Frontend finden -- nicht
// nur in ares.html, sondern in JEDER lokal von ares.html eingebundenen Datei
// (ausgelagerte Monolith-Teile wie ares.css, eigene Module, vendor/).
// In CSS zusaetzlich jedes @import und jedes url(...) auf http(s)/protokoll-
// relative Ziele, damit ein `@import url(https://...)` den Preflight nicht
// stumm passiert.
const fs = require('fs');
const path = require('path');

const EXTERNAL_MARKERS = ['fonts.googleapis.com', 'fonts.gstatic.com', 'cdnjs.cloudflare.com', 'cdn.jsdelivr.net'];

function localReferences(html) {
  const refs = [];
  const re = /<(?:script|link)\b[^>]*\b(?:src|href)="([^"'+]+)"/g;
  let m;
  while ((m = re.exec(html))) {
    const ref = m[1];
    if (/^[a-z]+:|^\/\/|^#/i.test(ref)) continue;
    refs.push(ref.startsWith('./') ? ref.slice(2) : ref);
  }
  return [...new Set(refs)];
}

function findExternalFrontendReferences(frontendDir) {
  const findings = [];
  const htmlPath = path.join(frontendDir, 'ares.html');
  const html = fs.readFileSync(htmlPath, 'utf8');
  const files = [['ares.html', html]];
  for (const ref of localReferences(html)) {
    const full = path.join(frontendDir, ref);
    if (!fs.existsSync(full)) {
      findings.push({ file: ref, marker: 'lokale Referenz fehlt' });
      continue;
    }
    files.push([ref, fs.readFileSync(full, 'utf8')]);
  }
  for (const [file, text] of files) {
    for (const marker of EXTERNAL_MARKERS) {
      if (text.includes(marker)) findings.push({ file, marker });
    }
    if (file.endsWith('.css')) {
      if (/@import\b/i.test(text)) findings.push({ file, marker: '@import' });
      if (/url\(\s*['"]?(?:https?:)?\/\//i.test(text)) findings.push({ file, marker: 'url(extern)' });
    }
  }
  return findings;
}

module.exports = { EXTERNAL_MARKERS, localReferences, findExternalFrontendReferences };
