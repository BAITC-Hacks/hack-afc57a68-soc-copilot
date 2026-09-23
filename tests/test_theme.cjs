// Dependency-free tests: node --test tests/test_theme.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { runInNewContext } = require('node:vm');
const script = readFileSync(resolve(__dirname, '../ui/theme.js'), 'utf8');

function events() {
  const handlers = new Map();
  return {
    handlers,
    addEventListener(name, fn) {
      if (!handlers.has(name)) handlers.set(name, new Set());
      handlers.get(name).add(fn);
    },
    removeEventListener(name, fn) { handlers.get(name)?.delete(fn); },
    emit(name, value) { handlers.get(name)?.forEach(fn => fn(value)); },
  };
}

function setup({ saved = null, dark = false, blocked = false, menuOpen = true } = {}) {
  const media = { ...events(), matches: dark };
  let focused = null;
  let control = null;
  let mounts = 0;
  const buttons = ['light', 'dark', 'system'].map(choice => ({
    dataset: { orgThemeChoice: choice },
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    focus() { focused = choice; },
  }));
  const storage = new Map(saved === null ? [] : [['orgtrace.theme', saved]]);
  const menu = {
    parentElement: { querySelector: () => control },
    before(node) { control = node; mounts += 1; },
  };
  const document = {
    ...events(), documentElement: { dataset: {} }, body: {},
    querySelectorAll: () => control ? buttons : [],
    querySelector: selector => selector.includes('theme_bootstrap')
      ? { cloneNode: () => ({ dataset: {} }) } : menuOpen ? menu : null,
  };
  const observers = [];
  class MutationObserver {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() { this.active = true; }
    disconnect() { this.active = false; }
  }
  const mutate = () => observers.filter(o => o.active).forEach(o => o.callback());
  const window = {
    ...events(), matchMedia: () => media,
    localStorage: {
      getItem(key) { if (blocked) throw Error('Blocked'); return storage.get(key) ?? null; },
      setItem(key, value) { if (blocked) throw Error('Blocked'); storage.set(key, value); },
    },
  };
  const run = () => runInNewContext(script, { window, document, MutationObserver });
  const click = choice => document.emit('click', { target: {
    closest: () => buttons.find(b => b.dataset.orgThemeChoice === choice),
  } });
  run();
  return {
    window, document, media, buttons, storage, run, click, mutate, observers,
    root: document.documentElement.dataset,
    get mounts() { return mounts; },
    get focused() { return focused; },
    openMenu() { menuOpen = true; mutate(); },
    closeMenu() { menuOpen = false; control = null; mutate(); },
  };
}

test('first visit follows system and tracks OS changes', () => {
  const app = setup({ dark: true });
  assert.equal(app.root.orgTheme, 'dark');
  assert.equal(app.root.orgThemePreference, 'system');
  app.media.matches = false;
  app.media.emit('change');
  assert.equal(app.root.orgTheme, 'light');
});

test('explicit choice persists and overrides system after reload', () => {
  const app = setup();
  app.click('dark');
  assert.equal(app.root.orgTheme, 'dark');
  assert.equal(app.storage.get('orgtrace.theme'), 'dark');
  assert.equal(app.buttons[1].attributes['aria-pressed'], 'true');
  app.media.emit('change');
  assert.equal(app.root.orgTheme, 'dark');
  assert.equal(setup({ saved: app.storage.get('orgtrace.theme') }).root.orgTheme, 'dark');
  app.click('system');
  assert.equal(app.root.orgTheme, 'light');
});

test('rerenders replace listeners, never double-toggle', () => {
  const app = setup();
  app.run();
  app.run();
  assert.equal(app.document.handlers.get('click').size, 1);
  assert.equal(app.media.handlers.get('change').size, 1);
  assert.equal(app.window.handlers.get('storage').size, 1);
  assert.equal(app.document.handlers.get('keydown').size, 1);
  assert.equal(app.observers.filter(o => o.active).length, 1);
  assert.equal(app.mounts, 1);
  app.click('dark');
  assert.equal(app.root.orgTheme, 'dark');
});

test('theme controls mount only inside the opened menu without duplicates', () => {
  const app = setup({ menuOpen: false, saved: 'dark' });
  assert.equal(app.mounts, 0);
  assert.equal(app.root.orgTheme, 'dark');
  app.openMenu();
  assert.equal(app.mounts, 1);
  assert.equal(app.buttons[1].attributes['aria-pressed'], 'true');
  app.mutate();
  assert.equal(app.mounts, 1);
  app.click('light');
  app.closeMenu();
  app.openMenu();
  assert.equal(app.mounts, 2);
  assert.equal(app.buttons[0].attributes['aria-pressed'], 'true');
});

test('theme buttons support arrow-key navigation', () => {
  const app = setup();
  app.document.emit('keydown', {
    key: 'ArrowRight', target: { closest: () => app.buttons[0] },
    preventDefault() {}, stopPropagation() {},
  });
  assert.equal(app.focused, 'dark');
});

test('blocked storage still supports in-memory theme switches and rerenders', () => {
  const app = setup({ blocked: true });
  app.click('dark');
  app.run();
  assert.equal(app.root.orgTheme, 'dark');
});

test('invalid saved values fall back; tabs synchronize only the theme key', () => {
  const app = setup({ saved: '<invalid>', dark: true });
  assert.equal(app.root.orgThemePreference, 'system');
  app.window.emit('storage', { key: 'orgtrace.theme', newValue: 'light' });
  assert.equal(app.root.orgTheme, 'light');
  app.window.emit('storage', { key: 'unrelated', newValue: 'dark' });
  assert.equal(app.root.orgTheme, 'light');
  app.window.emit('storage', { key: 'orgtrace.theme', newValue: null });
  assert.equal(app.root.orgTheme, 'dark');
});
