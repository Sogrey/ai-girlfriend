import * as THREE from 'three';
import { loadVRM } from './VRMFactory.js';
import { bus } from '../core/EventBus.js';

// Convert project-root-relative path (config) to app:// absolute URL.
// The renderer page lives at app://local/renderer/index.html, so a bare
// 'assets/...' would wrongly resolve against /renderer/ — we must use
// app://local/assets/... explicitly.
function resolveAsset(p) {
  if (!p) return p;
  if (/^app:\/\//.test(p)) return p;
  return 'app://local/' + String(p).replace(/^[\/\\]+/, '').replace(/\\/g, '/');
}

// Costume tint palettes used when a dedicated VRM file is missing.
const TINTS = {
  casual:  { tint: 0xffffff, emissive: 0x000000, emissiveIntensity: 0.0, name: '原装日常风' },
  school:  { tint: 0xcfd8ff, emissive: 0x000000, emissiveIntensity: 0.0, name: '学生蓝白配色' },
  stylish: { tint: 0xffd7e8, emissive: 0x30201a, emissiveIntensity: 0.15, name: '时尚粉金配色' },
  gothic:  { tint: 0xb9a6d9, emissive: 0x1a0f26, emissiveIntensity: 0.25, name: '暗夜洋装配色' },
  seed:    { tint: 0xd6f6ff, emissive: 0x0a2a3a, emissiveIntensity: 0.7, name: '科技感配色' },
};

export class CostumeManager {
  constructor(avatar, cfg) {
    this.avatar = avatar;
    this.slots = {};
    for (const [k, v] of Object.entries(cfg.avatar.costumes || {})) this.slots[k] = resolveAsset(v);
    this.fallbackPath = resolveAsset(cfg.avatar.fallback_model);
    this.currentId = null;
    this._loaded = new Map(); // costumeId -> vrm instance
  }

  url(id) { return this.slots[id]; }

  // Initial load: try default costume file, then fallback model file.
  async initialLoad() {
    const defaultId = 'casual';
    try {
      const vrm = await this._loadSlotFile(defaultId);
      await this.avatar.setModel(vrm);
      this.currentId = defaultId;
      console.log('[costume] loaded dedicated costume file:', defaultId);
      return { ok: true, costume: defaultId, realModel: true };
    } catch (e1) {
      console.log('[costume] costume slot file unavailable:', e1.message);
      // try fallback model
      try {
        const { vrm } = await loadVRM(this.fallbackPath);
        await this.avatar.setModel(vrm);
        this.currentId = defaultId;
        this._applyTint(defaultId);
        console.log('[costume] fallback model loaded with tint', defaultId);
        return { ok: true, costume: defaultId, realModel: false, note: '当前使用通用示例模型（未找到 ' + defaultId + ' 服装 VRM）。将你的 VRM 文件放入 assets/costumes/ 即可获得专属造型。' };
      } catch (e2) {
        console.log('[costume] fallback model failed:', e2.message);
        return { ok: false, error: e2.message };
      }
    }
  }

  async _loadSlotFile(id) {
    if (this._loaded.has(id)) return this._loaded.get(id);
    const { vrm } = await loadVRM(this.url(id));
    this._loaded.set(id, vrm);
    return vrm;
  }

  // Switch costume. Tries the dedicated VRM file; falls back to tinted palette.
  async switch(id, { silent = false } = {}) {
    if (!this.slots[id]) throw new Error('未知的服装: ' + id);
    this.currentId = id;
    try {
      const vrm = await this._loadSlotFile(id);
      await this.avatar.setModel(vrm);
      if (!silent) bus.emit('toast:show', { text: `换装完成（${id} · 完整模型）`, kind: 'ok', ms: 1800 });
      return { ok: true, realModel: true };
    } catch (e) {
      // No dedicated VRM file — tint current materials instead.
      this._applyTint(id);
      if (!silent) bus.emit('toast:show', { text: `已切换到「${TINTS[id]?.name || id}」配色变体。将对应的 VRM 文件放到 assets/costumes/ 可获得完整服装。`, kind: 'warn', ms: 3200 });
      return { ok: true, realModel: false };
    }
  }

  _applyTint(id) {
    const t = TINTS[id] || TINTS.casual;
    const tintC = new THREE.Color(t.tint);
    const emC = new THREE.Color(t.emissive);
    const vrm = this.avatar.vrm;
    if (!vrm) return;
    // restore original colors first if we tinted before
    this._restoreOriginalMaterials?.();
    this._originals = [];
    vrm.scene.traverse((obj) => {
      if (!obj.isMesh) return;
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      for (const m of mats) {
        if (!m || !m.color) continue;
        this._originals.push({ m, color: m.color.clone(), emissive: m.emissive ? m.emissive.clone() : null, emissiveIntensity: m.emissiveIntensity ?? 0 });
        m.color.lerp(tintC, 0.55);
        if (m.emissive) {
          m.emissive.copy(emC);
          m.emissiveIntensity = t.emissiveIntensity;
        }
      }
    });
    this._restoreOriginalMaterials = () => {
      for (const o of this._originals || []) {
        o.m.color.copy(o.color);
        if (o.emissive && o.m.emissive) { o.m.emissive.copy(o.emissive); o.m.emissiveIntensity = o.emissiveIntensity; }
      }
      this._originals = [];
    };
  }

  get costumeName() { return this.currentId; }
}
