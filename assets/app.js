'use strict';
const $ = selector => document.querySelector(selector);
function el(tag, className = '', text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
let snapshot, draft, submitted = null, current = 0, selection = null, editing = null;
let saveTimer, saveChain = Promise.resolve(), revision = 0, dirty = false, submitting = false;
let searchState = {fileIndexes: new Set(), matches: []}, visibleMatches = 100;
const composer = $('#composer');
const dialog = $('#review-dialog');
const labels = {worktree: 'Uncommitted changes', branches: 'Branches · merge-base → target', commits: 'Commits · exact trees'};
const storageKey = () => 'review-draft-' + snapshot.id;

async function api(path, packet) {
  const response = await fetch(path, packet === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(packet)
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Request failed (' + response.status + ')');
  return data;
}
function showError(message) { $('#error').textContent = message; $('#error').classList.toggle('hidden', !message); }
function count(status) {
  document.querySelectorAll('.comment-count').forEach(n => n.textContent = draft.comments.length);
  $('#draft-status').textContent = submitted ? 'Review submitted · tersimpan untuk agent' :
    draft.comments.length + ' draft comments · ' + (status || (dirty ? 'menyimpan…' : 'tersimpan, belum dikirim'));
}
function remember() {
  try { sessionStorage.setItem(storageKey(), JSON.stringify({draft, at: Date.now()})); } catch (_) { /* Server remains authoritative. */ }
}
function changed() {
  dirty = true;
  revision++;
  remember();
  count();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushDraft, 250);
}
function flushDraft() {
  clearTimeout(saveTimer);
  if (submitted) return saveChain;
  const packet = structuredClone(draft), version = revision;
  saveChain = saveChain.catch(() => {}).then(() => api('/api/draft', packet)).then(() => {
    if (revision === version) { dirty = false; count(); }
  }).catch(error => { count('belum tersimpan · ' + error.message); throw error; });
  // Surface errors in the status without an unhandled rejection during autosave.
  saveChain.catch(() => {});
  return saveChain;
}
function abandonEditor() {
  if (editing && $('#comment-text').value.trim() && !confirm('Komentar ini belum ditambahkan ke draft. Buang teksnya?')) return false;
  editing = null;
  $('#comment-text').value = '';
  composer.classList.add('hidden');
  return true;
}
function clearRange() {
  selection = null;
  $('#range-selection').textContent = 'Klik baris awal lalu akhir untuk memilih.';
  $('#range-selection').title = '';
  $('#comment-range').disabled = $('#clear-range').disabled = true;
  document.querySelectorAll('.row').forEach(row => row.classList.remove('selected', 'range-end'));
  document.querySelectorAll('.num[aria-pressed]').forEach(n => n.setAttribute('aria-pressed', 'false'));
}
function selectLine(line, side, hunk) {
  if (submitted || !abandonEditor()) return;
  const sameRange = selection && selection.side === side && selection.hunk === hunk;
  const numbers = new Set(sameRange ? selection.lines : []);
  if (numbers.has(line)) numbers.delete(line);
  else {
    const sorted = [...numbers].sort((a, b) => a - b);
    const edge = !sorted.length ? line : line < sorted[0] ? sorted[0] : line > sorted.at(-1) ? sorted.at(-1) : line;
    for (let n = Math.min(line, edge); n <= Math.max(line, edge); n++) numbers.add(n);
  }
  if (!numbers.size) { clearRange(); return; }
  const sorted = [...numbers].sort((a, b) => a - b), ranges = [];
  for (const n of sorted) {
    const previous = ranges.at(-1);
    if (previous && previous.end + 1 === n) previous.end = n;
    else ranges.push({start: n, end: n});
  }
  selection = {side, hunk, lines: numbers, ranges};
  let last;
  document.querySelectorAll('.row').forEach(row => {
    const value = row.dataset[side];
    const selected = Number(row.dataset.hunk) === hunk && value !== '' && selection.lines.has(Number(value));
    row.classList.toggle('selected', selected);
    row.classList.remove('range-end');
    row.querySelectorAll('.num[aria-pressed]').forEach(n => n.setAttribute('aria-pressed', String(selected && n.dataset.side === side)));
    if (selected) last = row;
  });
  if (last) last.classList.add('range-end');
  $('#range-selection').textContent = locationLabel({...selection, path: snapshot.files[current].path});
  $('#range-selection').title = $('#range-selection').textContent;
  $('#comment-range').disabled = $('#clear-range').disabled = false;
}
function locationLabel(comment) {
  const ranges = comment.ranges || [{start: comment.start, end: comment.end}];
  const label = ranges.map(r => r.start === r.end ? String(r.start) : r.start + '–' + r.end).join(', ');
  return comment.path + ' · ' + comment.side + ' ' + (ranges.length === 1 && ranges[0].start === ranges[0].end ? 'line ' : 'lines ') + label;
}
function commentRange() {
  if (!selection || submitted) return;
  if (editing && !abandonEditor()) return;
  editing = {path: snapshot.files[current].path, side: selection.side, ranges: selection.ranges};
  $('#comment-location').textContent = locationLabel(editing) + (editing.ranges.length > 1 ? ' · satu komentar per rentang' : '');
  $('#comment-text').value = '';
  document.querySelector('.range-end').after(composer);
  composer.classList.remove('hidden');
  $('#comment-text').focus();
  composer.scrollIntoView({block: 'nearest'});
}
function renderComment(comment, index, row) {
  const wrap = el('div', 'thread-wrap');
  const thread = el('div', 'thread');
  const head = el('div', 'thread-head');
  head.append(el('span', 'review-avatar', 'Y'), el('strong', '', 'You'), el('span', 'muted', locationLabel(comment)), el('span', 'draft-label', submitted ? 'Submitted' : 'Pending'));
  if (!submitted) {
    const edit = el('button', 'btn', 'Edit');
    edit.type = 'button';
    edit.onclick = () => {
      if (!abandonEditor()) return;
      editing = {...comment, index};
      $('#comment-location').textContent = locationLabel(comment);
      $('#comment-text').value = comment.text;
      row.after(composer);
      composer.classList.remove('hidden');
      $('#comment-text').focus();
      composer.scrollIntoView({block: 'nearest'});
    };
    const remove = el('button', 'btn', 'Remove');
    remove.type = 'button';
    remove.onclick = () => { if (!abandonEditor()) return; draft.comments.splice(index, 1); changed(); renderFile(); };
    head.append(edit, remove);
  }
  thread.append(head, el('p', 'comment-text', comment.text));
  wrap.append(thread);
  return wrap;
}
function fileLabel(path) {
  const slash = path.lastIndexOf('/');
  return {name: path.slice(slash + 1), directory: slash < 0 ? 'Repository root' : path.slice(0, slash)};
}
function searchSnapshot(query) {
  const needle = query.toLowerCase(), fileIndexes = new Set(), matches = [];
  snapshot.files.forEach((file, fileIndex) => {
    if (!needle || [file.path, file.old_path || ''].some(path => path.toLowerCase().includes(needle))) fileIndexes.add(fileIndex);
    if (!needle) return;
    file.hunks.forEach((hunk, hunkIndex) => hunk.lines.forEach((line, lineIndex) => {
      if (!line.text.toLowerCase().includes(needle)) return;
      const side = line.type === '-' ? 'old' : 'new';
      fileIndexes.add(fileIndex);
      matches.push({fileIndex, hunkIndex, lineIndex, side, number: line[side]});
    }));
  });
  return {fileIndexes, matches};
}
function highlightText(node, text, query) {
  node.replaceChildren();
  const needle = query.toLowerCase();
  if (!needle) { node.textContent = text; return; }
  const lower = text.toLowerCase();
  // Map expanded lowercase characters (e.g. İ) back to untouched source offsets.
  const starts = [], ends = [];
  if (lower.length !== text.length) {
    let offset = 0;
    for (const character of text) {
      for (let i = 0; i < character.toLowerCase().length; i++) { starts.push(offset); ends.push(offset + character.length); }
      offset += character.length;
    }
  }
  let searchStart = 0, sourceStart = 0, position;
  while ((position = lower.indexOf(needle, searchStart)) !== -1) {
    const start = starts[position] ?? position;
    const end = ends[position + needle.length - 1] ?? position + needle.length;
    if (start >= sourceStart) {
      node.append(document.createTextNode(text.slice(sourceStart, start)), el('mark', '', text.slice(start, end)));
      sourceStart = end;
    }
    searchStart = position + needle.length;
  }
  node.append(document.createTextNode(text.slice(sourceStart)));
}
function highlightSources() {
  const file = snapshot.files[current], query = $('#review-search').value;
  if (!file) return;
  document.querySelectorAll('#lines .row').forEach(row => {
    const line = file.hunks[Number(row.dataset.hunk)].lines[Number(row.dataset.line)];
    highlightText(row.querySelector('.source'), line.text, query);
    row.classList.remove('search-destination');
  });
}
function navigateToMatch(match) {
  hidePathHint();
  if (match.fileIndex !== current) {
    if (!abandonEditor()) return;
    current = match.fileIndex; renderFile();
  }
  document.querySelectorAll('.search-destination').forEach(row => row.classList.remove('search-destination'));
  const row = document.querySelector('.row[data-hunk="' + match.hunkIndex + '"][data-line="' + match.lineIndex + '"]');
  if (!row) return;
  row.classList.add('search-destination'); row.tabIndex = -1;
  row.focus({preventScroll: true}); row.scrollIntoView({block: 'center'});
  row.querySelector('mark')?.scrollIntoView({block: 'nearest', inline: 'nearest'});
}
function renderSearchResults() {
  const box = $('#search-results'), query = $('#review-search').value;
  box.replaceChildren(); box.classList.toggle('hidden', !query);
  if (!query) return;
  const matches = searchState.matches;
  if (!matches.length) box.append(el('p', 'notice', searchState.fileIndexes.size ? 'Files match by path, but no captured code lines match.' : 'No files or captured code match. Try another term or clear search.'));
  matches.slice(0, visibleMatches).forEach(match => {
    const file = snapshot.files[match.fileIndex], label = fileLabel(file.path);
    const button = el('button', 'search-result'); button.type = 'button'; button.dataset.file = match.fileIndex;
    button.append(el('strong', '', label.name + ' · ' + match.side + ' line ' + match.number), el('span', 'result-directory', label.directory));
    const snippet = el('code', 'search-snippet');
    highlightText(snippet, file.hunks[match.hunkIndex].lines[match.lineIndex].text, query);
    button.append(snippet); button.onclick = () => navigateToMatch(match); box.append(button);
  });
  if (matches.length > visibleMatches) {
    const more = el('button', 'btn', 'Show more matches'); more.id = 'more-matches'; more.type = 'button';
    more.onclick = () => { visibleMatches += 100; renderSearchResults(); $('#search-results .search-result:nth-child(' + (visibleMatches - 99) + ')')?.focus(); };
    box.append(more);
  }
}
function renderSearch() {
  visibleMatches = 100; searchState = searchSnapshot($('#review-search').value);
  renderFiles(); renderSearchResults(); highlightSources();
  $('#search-status').textContent = $('#review-search').value ? searchState.fileIndexes.size + ' of ' + snapshot.files.length + ' files · ' + searchState.matches.length + ' matching lines · Only captured text is searched.' : '';
}
let pathHintTimer, pathHintAnchor;
function hidePathHint() {
  clearTimeout(pathHintTimer);
  $('#file-path-hint').hidden = true;
  pathHintAnchor?.removeAttribute('aria-describedby');
  pathHintAnchor = null;
}
function attachPathHint(button, fullPath) {
  const truncated = () => [...button.querySelectorAll('.file-name,.file-directory')].some(node => node.scrollWidth > node.clientWidth);
  const show = () => {
    if (!button.isConnected || !truncated()) return;
    const hint = $('#file-path-hint'), rect = button.getBoundingClientRect();
    pathHintAnchor = button; button.setAttribute('aria-describedby', hint.id);
    hint.textContent = fullPath; hint.hidden = false;
    hint.style.left = Math.max(8, Math.min(rect.left, innerWidth - hint.offsetWidth - 8)) + 'px';
    hint.style.top = Math.max(8, Math.min(rect.bottom + 6, innerHeight - hint.offsetHeight - 8)) + 'px';
  };
  button.onmouseenter = () => { hidePathHint(); if (truncated()) pathHintTimer = setTimeout(show, 1000); };
  button.onfocus = () => { hidePathHint(); show(); };
  button.onmouseleave = button.onblur = hidePathHint;
}
document.addEventListener('keydown', event => { if (event.key === 'Escape') hidePathHint(); });
window.addEventListener('scroll', hidePathHint, true);
window.addEventListener('resize', hidePathHint);
function renderFiles() {
  hidePathHint();
  $('#files').replaceChildren();
  const matches = $('#review-search').value ? searchState.fileIndexes : new Set(snapshot.files.map((_, i) => i));
  $('#file-count').textContent = matches.size + ' / ' + snapshot.files.length;
  if (!matches.size && snapshot.files.length) $('#files').append(el('p', 'small', 'No matching files. Clear search to see all files.'));
  snapshot.files.forEach((item, index) => {
    if (!matches.has(index)) return;
    const button = el('button', 'file' + (index === current ? ' active' : ''));
    button.type = 'button';
    button.dataset.file = index;
    button.setAttribute('aria-label', item.path + ' · ' + item.status + (draft.viewed.includes(item.path) ? ' · Viewed' : ' · Not viewed'));
    if (index === current) button.setAttribute('aria-current', 'true');
    const label = fileLabel(item.path), identity = el('span', 'file-identity');
    identity.append(el('span', 'file-name', label.name), el('span', 'file-directory', label.directory));
    button.append(identity, el('span', 'change', draft.viewed.includes(item.path) ? '✓ ' + item.status : item.status));
    attachPathHint(button, item.path);
    button.onclick = () => { if (abandonEditor()) { current = index; renderFile(); } };
    $('#files').append(button);
  });
}
function renderFile() {
  $('#composer-home').append(composer);
  composer.classList.add('hidden');
  clearRange();
  const file = snapshot.files[current];
  renderFiles();
  $('#file-view').classList.toggle('hidden', !file);
  $('#empty').classList.toggle('hidden', !!file);
  if (!file) return;
  $('#filename').textContent = file.old_path ? file.old_path + ' → ' + file.path : file.path;
  $('#file-position').textContent = (current + 1) + ' of ' + snapshot.files.length + ' files · Unified diff';
  $('#stats').replaceChildren(el('span', 'added', '+' + file.added), document.createTextNode('  '), el('span', 'deleted', '−' + file.deleted));
  $('#viewed').checked = draft.viewed.includes(file.path);
  $('#viewed').disabled = !!submitted;
  $('#lines').replaceChildren();
  if (!file.hunks.length) $('#lines').append(el('p', 'notice', file.note || 'Metadata-only change'));
  file.hunks.forEach((hunk, hi) => {
    $('#lines').append(el('div', 'hunk', hunk.header));
    hunk.lines.forEach((line, li) => {
      const row = el('div', 'row' + (line.type === '+' ? ' add' : line.type === '-' ? ' del' : ''));
      row.dataset.old = line.old ?? ''; row.dataset.new = line.new ?? ''; row.dataset.hunk = hi; row.dataset.line = li;
      for (const side of ['old', 'new']) {
        const value = line[side];
        const cell = el(value === null ? 'span' : 'button', 'num', value ?? '');
        if (value !== null) {
          cell.type = 'button'; cell.dataset.side = side;
          cell.disabled = !!submitted;
          cell.setAttribute('aria-label', side + ' line ' + value);
          cell.setAttribute('aria-pressed', 'false');
          cell.onclick = event => { event.stopPropagation(); selectLine(value, side, hi); };
        }
        row.append(cell);
      }
      const side = line.type === '-' ? 'old' : 'new', number = line[side];
      row.append(el('span', 'sign', line.type), el('span', 'source', line.text));
      row.onclick = () => selectLine(number, side, hi);
      if (!submitted) {
        const add = el('button', 'line-add', '+'); add.type = 'button';
        add.setAttribute('aria-label', 'Comment on ' + side + ' line ' + number);
        add.onclick = event => { event.stopPropagation(); if (!row.classList.contains('range-end')) { clearRange(); selectLine(number, side, hi); } commentRange(); };
        row.append(add);
      }
      $('#lines').append(row);
      if (line.no_newline) $('#lines').append(el('div', 'hunk', '\\ No newline at end of file'));
      draft.comments.forEach((comment, ci) => {
        if (comment.path === file.path && comment.end === line[comment.side]) $('#lines').append(renderComment(comment, ci, row));
      });
    });
  });
  highlightSources();
}
$('#review-search').oninput = renderSearch;
$('#clear-search').onclick = () => { $('#review-search').value = ''; renderSearch(); $('#review-search').focus(); };
function showSubmitted() {
  $('#submitted').classList.remove('hidden');
  $('#submitted').textContent = 'Review submitted: ' + submitted.decision + ' · ' + submitted.comments.length + ' komentar. Feedback tersimpan untuk agent. Untuk revisi selanjutnya, agent membuat snapshot baru.';
  document.querySelectorAll('.finish').forEach(button => button.disabled = true);
  count();
}
function finish() {
  if (editing && $('#comment-text').value.trim()) {
    showError('Komentar yang sedang diketik belum ditambahkan. Klik Add review comment atau Cancel terlebih dahulu.');
    $('#comment-text').focus(); return;
  }
  $('#summary-count').textContent = draft.comments.length + ' inline comments akan disertakan. Draft baru dikirim setelah submit.';
  $('#submit-error').textContent = '';
  dialog.showModal();
}
$('#comment-range').onclick = commentRange;
$('#clear-range').onclick = () => { if (abandonEditor()) clearRange(); };
$('#cancel-comment').onclick = () => abandonEditor();
$('#comment-form').onsubmit = event => {
  event.preventDefault();
  const text = $('#comment-text').value.trim();
  if (!editing || !text) return;
  const ranges = editing.ranges || [{start: editing.start, end: editing.end}];
  const comments = ranges.map(range => ({path: editing.path, side: editing.side, ...range, text}));
  if (editing.index !== undefined) draft.comments.splice(editing.index, 1, ...comments);
  else draft.comments.push(...comments);
  editing = null; $('#comment-text').value = ''; composer.classList.add('hidden');
  showError(''); changed(); renderFile();
};
$('#viewed').onchange = () => {
  const path = snapshot.files[current].path;
  draft.viewed = $('#viewed').checked ? [...new Set([...draft.viewed, path])] : draft.viewed.filter(p => p !== path);
  changed(); renderFiles();
};
document.querySelectorAll('.finish').forEach(button => button.onclick = finish);
$('#close-review').onclick = $('#cancel-review').onclick = () => dialog.close();
$('#review-summary').oninput = () => { draft.summary = $('#review-summary').value; changed(); };
document.querySelectorAll('input[name="decision"]').forEach(input => input.onchange = () => { draft.decision = input.value; changed(); });
dialog.addEventListener('cancel', event => { if (submitting) event.preventDefault(); });
$('#review-form').onsubmit = async event => {
  event.preventDefault();
  if (submitting) return;
  submitting = true;
  const packet = structuredClone(draft);
  dialog.querySelectorAll('input, textarea, button').forEach(control => control.disabled = true);
  try {
    await flushDraft();
    await api('/api/submit', packet);
    submitted = packet; dirty = false;
    try { sessionStorage.removeItem(storageKey()); } catch (_) {}
    dialog.close(); renderFile(); showSubmitted(); $('#submitted').scrollIntoView({behavior: 'smooth'});
  } catch (error) { $('#submit-error').textContent = error.message; }
  finally {
    submitting = false;
    dialog.querySelectorAll('input, textarea, button').forEach(control => control.disabled = false);
  }
};
window.addEventListener('beforeunload', event => {
  if (!submitted && (dirty || (editing && $('#comment-text').value.trim()))) { event.preventDefault(); event.returnValue = ''; }
});
(async () => {
  try {
    // The cookie established by the first request keeps the bearer token out of subsequent URLs.
    history.replaceState(null, '', location.pathname);
    snapshot = await api('/api/snapshot');
    const state = await api('/api/state');
    draft = state.draft || {snapshot_id: snapshot.id, comments: [], summary: '', decision: 'comment', viewed: []};
    submitted = state.review;
    if (submitted) draft = submitted;
    else {
      try {
        const local = JSON.parse(sessionStorage.getItem(storageKey()));
        if (local && local.draft.snapshot_id === snapshot.id) { draft = local.draft; changed(); }
      } catch (_) {}
    }
    $('#repo-name').textContent = '/ ' + snapshot.name;
    $('#comparison').textContent = labels[snapshot.mode];
    $('#base').textContent = snapshot.base_label + ' (' + snapshot.base.slice(0, 8) + ')';
    $('#head').textContent = snapshot.head_label + (snapshot.head === 'working tree' ? '' : ' (' + snapshot.head.slice(0, 8) + ')');
    $('#snapshot-label').textContent = 'Snapshot ' + snapshot.id.slice(0, 8) + ' · ' + snapshot.files.length + ' files';
    $('#file-count').textContent = snapshot.files.length;
    $('#connection').textContent = location.hostname === 'localhost' || location.hostname === '127.0.0.1' ? 'Localhost only' : 'Protected tunnel session';
    $('#overall-summary').textContent = snapshot.summary || 'Agent belum menambahkan summary. Minta agent menjelaskan perubahan berdasarkan snapshot ini sebelum review.';
    $('#review-summary').value = draft.summary;
    document.querySelectorAll('input[name="decision"]').forEach(input => input.checked = input.value === draft.decision);
    $('#loading').classList.add('hidden');
    document.querySelectorAll('.finish').forEach(button => button.disabled = false);
    $('#review-search').disabled = $('#clear-search').disabled = false;
    renderSearch(); renderFile(); count(); if (submitted) showSubmitted();
  } catch (error) { $('#loading').classList.add('hidden'); showError('Gagal memuat review: ' + error.message + '. Buka ulang URL lengkap dari agent.'); }
})();
