// Loads merged config from main process, provides get/set helpers.
let _cfg = null;

export async function loadConfig() {
  _cfg = await window.desktop.getConfig();
  return _cfg;
}

export function cfg() {
  if (!_cfg) throw new Error('Config not loaded yet');
  return _cfg;
}

export async function saveConfig(patch) {
  _cfg = await window.desktop.updateConfig(patch);
  return _cfg;
}

// Deep getter: get('llm.deepseek.model')
export function get(path) {
  const parts = path.split('.');
  let v = cfg();
  for (const p of parts) { if (v == null) return undefined; v = v[p]; }
  return v;
}
