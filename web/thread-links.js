/* Canonical thread references only; never render model HTML or arbitrary URLs. */
(() => {
  'use strict';
  function resolver(inventory) {
    const ids = new Set(), aliases = new Map();
    const add = (name, id) => {
      if (!name) return;
      if (!aliases.has(name)) aliases.set(name, new Set());
      aliases.get(name).add(id);
    };
    for (const row of Array.isArray(inventory) ? inventory : []) {
      if (!row || typeof row.id !== 'string' || !row.id.trim() || row.id.length >= 2048 || typeof row.title !== 'string' || !row.title.trim()) continue;
      ids.add(row.id);
      for (const observed of [row.title, ...(Array.isArray(row.aliases) ? row.aliases : [])]) {
        if (typeof observed !== 'string' || !observed.trim()) continue;
        const title = observed.trim();
        add(title, row.id);
        // A category suffix and a distinctive leading phrase are useful historical
        // abbreviations. No arbitrary substring/fuzzy matching or invented IDs.
        const suffix = title.split(' · ').at(-1);
        add(suffix, row.id);
        const words = suffix.split(' ');
        for (let n = 3; n < words.length; n++) {
          if (!/^(and|or|the|a|to|of|in|for|with|across|after|before)$/i.test(words[n - 1])) add(words.slice(0, n).join(' '), row.id);
        }
      }
    }
    const names = [...aliases.keys()].sort((a, b) => b.length - a.length);
    const escaped = names.map(s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const pattern = escaped.length ? new RegExp(escaped.join('|'), 'gu') : null;
    const word = c => !!c && /[\p{L}\p{N}_#]/u.test(c);
    function parts(text) {
      const output = [];
      const plain = value => { if (value) output.push({ text: value }); };
      function mentions(value, offset) {
        if (!pattern) { plain(value); return; }
        pattern.lastIndex = 0;
        let end = 0;
        for (const m of value.matchAll(pattern)) {
          const start = offset + m.index, finish = start + m[0].length;
          if (word(text[start - 1]) || word(text[finish])) continue;
          const candidates = aliases.get(m[0]);
          if (candidates.size !== 1) continue;
          // One-word titles (e.g. Manager) require naming/list context, not a
          // generic mention of the app or an ordinary word in prose.
          if (!/\s/.test(m[0])) {
            const before = text.slice(Math.max(0, start - 60), start), after = text.slice(finish);
            const quoted = /["“'‘`]$/.test(before) && /^["”'’`]/.test(after);
            const named = /(?:thread|called|named)\s+$/i.test(before);
            const listed = /(?:,\s*|\band\s+)$/.test(before) && /^(?:\s+(?:is|are)\b|[,.;]|$)/.test(after);
            if (!quoted && !named && !listed) continue;
          }
          plain(value.slice(end, m.index));
          output.push({ text: m[0], source_id: [...candidates][0] });
          end = m.index + m[0].length;
        }
        plain(value.slice(end));
      }
      // Explicit references are protected from automatic name resolution even
      // when invalid. Backtick-quoted names can resolve; raw URLs stay inert.
      const tokens = /\[([^\]\n]+)\]\(([^\s)]*)\)|`[^`]*`|https?:\/\/[^\s]+|\/wizard-os-home\/\?[^\s]+/g;
      let end = 0;
      for (const m of text.matchAll(tokens)) {
        mentions(text.slice(end, m.index), end);
        let sid = null;
        if (m[1] && m[2].startsWith('/wizard-os-home/?session=')) {
          const encoded = m[2].slice('/wizard-os-home/?session='.length);
          try { if (!/[&#?]/.test(encoded)) sid = decodeURIComponent(encoded); } catch (_) { /* inert malformed URL */ }
        }
        if (sid && ids.has(sid)) output.push({ text: m[1], source_id: sid });
        else if (m[0].startsWith('`') && !m[0].includes('\n')) mentions(m[0], m.index);
        else plain(m[0]);
        end = m.index + m[0].length;
      }
      mentions(text.slice(end), end);
      return output;
    }
    return parts;
  }
  window.ManagerThreadLinks = { resolver };
})();
