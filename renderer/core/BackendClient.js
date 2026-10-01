import { bus } from './EventBus.js';
import { cfg, get } from './ConfigManager.js';

// WebSocket client to Python backend (port 8765 by default).
export class BackendClient {
  constructor() {
    this.ws = null;
    this.url = null;
    this.connected = false;
    this.reconnectTimer = null;
    this._msgId = 0;
    this._pending = new Map();
    this._autoReconnect = true;
  }

  connect() {
    const port = get('server.port') || 8765;
    this.url = `ws://127.0.0.1:${port}`;
    this._open();
  }

  _open() {
    try {
      this.ws = new WebSocket(this.url);
    } catch (e) {
      bus.emit('backend:error', { message: '无法创建 WebSocket 连接: ' + e.message });
      this._scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      this.connected = true;
      bus.emit('backend:connected');
    };
    this.ws.onclose = () => {
      this.connected = false;
      bus.emit('backend:disconnected');
      if (this._autoReconnect) this._scheduleReconnect();
    };
    this.ws.onerror = () => {
      // onclose will follow
    };
    this.ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      this._dispatch(msg);
    };
  }

  _dispatch(msg) {
    // Response to a request we sent (has _id we tracked)
    if (msg._id && this._pending.has(msg._id)) {
      const { resolve, reject } = this._pending.get(msg._id);
      this._pending.delete(msg._id);
      if (msg.error) reject(new Error(msg.error));
      else resolve(msg);
      return;
    }
    // Otherwise it's a push event from backend
    bus.emit('backend:message', msg);
    if (msg.type) bus.emit(`backend:${msg.type}`, msg);
  }

  _scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this._open();
    }, 2500);
  }

  // Fire-and-forget send.
  send(obj) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(obj));
    return true;
  }

  // Promise-based request that awaits a reply with matching _id.
  request(obj) {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error('Backend not connected'));
        return;
      }
      const id = ++this._msgId;
      const payload = { ...obj, _id: id };
      this._pending.set(id, { resolve, reject });
      // Timeout guard
      setTimeout(() => {
        if (this._pending.has(id)) {
          this._pending.delete(id);
          reject(new Error('Backend request timeout'));
        }
      }, 90000);
      this.ws.send(JSON.stringify(payload));
    });
  }

  close() {
    this._autoReconnect = false;
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    if (this.ws) { try { this.ws.close(); } catch {} }
  }
}

export const backend = new BackendClient();
