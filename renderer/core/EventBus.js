// Tiny event bus for decoupled module communication.
export class EventBus {
  constructor() { this._h = new Map(); }
  on(type, fn) {
    if (!this._h.has(type)) this._h.set(type, new Set());
    this._h.get(type).add(fn);
    return () => this.off(type, fn);
  }
  off(type, fn) { this._h.get(type)?.delete(fn); }
  emit(type, ...args) {
    this._h.get(type)?.forEach(fn => { try { fn(...args); } catch (e) { console.error('[bus]', type, e); } });
  }
}
export const bus = new EventBus();
