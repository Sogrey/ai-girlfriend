import * as THREE from 'three';
import { bus } from '../core/EventBus.js';

// Combines:
//  1. click-through management (window ignores mouse unless cursor near avatar)
//  2. drag-to-move window (uses global mouse position, not pointer deltas)
//  3. click vs drag vs long-press disambiguation
//  4. head-pat detection (click on head bone region)
export class MouseInteractionController {
  constructor(sm, avatar) {
    this.sm = sm;
    this.avatar = avatar;
    this.canvas = sm.canvas;
    this.raycaster = new THREE.Raycaster();
    this.mouseGlobal = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    this._ignore = true;
    this._pressing = false;
    this._dragging = false;
    this._downAt = 0;
    this._downClient = null;
    this._lastClient = null;
    this._longPressTimer = null;
    this._prox = 160; // px radius around head/body considered "near"
    // drag state: track global mouse for window movement
    this._dragStartGlobal = null;
    this._dragWindowStart = null; // {x, y} window position at drag start

    window.desktop?.onGlobalMouse?.((pos) => { this.mouseGlobal = pos; });
    this._bind();
    this._emitter = bus;
  }

  _bind() {
    this.canvas.addEventListener('pointerdown', (e) => this._down(e));
    this.canvas.addEventListener('pointermove', (e) => this._move(e));
    this.canvas.addEventListener('pointerup', (e) => this._up(e));
    this.canvas.addEventListener('pointercancel', (e) => this._up(e));
  }

  // called every frame from the main loop
  update() {
    if (!this.avatar.hasModel()) return;
    const head = this.sm.worldToScreen(this.avatar.headWorldPos());
    const chest = this.sm.worldToScreen(this.avatar.chestWorldPos());
    const dHead = Math.hypot(this.mouseGlobal.x - head.x, this.mouseGlobal.y - head.y);
    const dChest = Math.hypot(this.mouseGlobal.x - chest.x, this.mouseGlobal.y - chest.y);
    // near = cursor close to the avatar, OR hovering the UI widgets.
    // Without the UI check, moving the cursor from the avatar down to the
    // toolbar leaves the "near" zone, which fades the toolbar out and
    // re-enables click-through before the buttons can be clicked.
    const near = dHead < this._prox
      || dChest < this._prox * 0.95
      || this._uiHover();

    // While dragging, ALWAYS keep mouse events active (don't toggle ignore)
    if (!this._dragging) {
      this._setIgnore(!near);
    }
    this._emitter.emit('avatar:proximity', { near: near || this._dragging, dHead, dChest, head, chest });
  }

  // Cursor over (or near) interactive UI elements?
  // - toolbar counts even while hidden: hovering its area summons it
  //   (mouseGlobal is in window/DIP coords, same as getBoundingClientRect)
  // - open panels count only while visible, so clicks on chat/settings/
  //   costume widgets never fall through to the desktop
  _uiHover() {
    for (const id of ['toolbar', 'chat-panel', 'settings-panel', 'costume-bar']) {
      const el = document.getElementById(id);
      if (!el) continue;
      const visible = !el.classList.contains('hidden');
      if (id !== 'toolbar' && !visible) continue;
      const r = el.getBoundingClientRect();
      const m = 20; // px buffer around the element
      if (this.mouseGlobal.x >= r.left - m && this.mouseGlobal.x <= r.right + m &&
          this.mouseGlobal.y >= r.top - m && this.mouseGlobal.y <= r.bottom + m) {
        return true;
      }
    }
    return false;
  }

  _setIgnore(ignore) {
    if (this._ignore === ignore) return;
    this._ignore = ignore;
    window.desktop?.setIgnoreMouse?.(ignore);
  }

  _hitTest(px, py) {
    const nx = (px / window.innerWidth) * 2 - 1;
    const ny = -(py / window.innerHeight) * 2 + 1;
    this.raycaster.setFromCamera(new THREE.Vector2(nx, ny), this.sm.camera);
    const objs = this.avatar.vrm ? this.avatar.vrm.scene : [];
    const hits = this.raycaster.intersectObject(objs, true);
    if (!hits.length) return { hit: false };
    const point = hits[0].point;
    const headPos = this.avatar.headWorldPos();
    const dHead = point.distanceTo(headPos);
    return { hit: true, point, isHead: dHead < 0.16, dHead };
  }

  _down(e) {
    if (e.button !== 0) return;
    const r = this._hitTest(e.clientX, e.clientY);
    if (!r.hit) return;
    this._pressing = true;
    this._dragging = false;
    this._downAt = performance.now();
    this._downClient = { x: e.clientX, y: e.clientY };
    this._lastClient = { x: e.clientX, y: e.clientY };
    // Ensure mouse events stay active during press
    this._setIgnore(false);
    try { this.canvas.setPointerCapture(e.pointerId); } catch {}
    // long press = head pat (mouse press-and-hold on head)
    this._longPressTimer = setTimeout(() => {
      if (this._pressing && !this._dragging) {
        const rr = this._hitTest(e.clientX, e.clientY);
        if (rr.isHead) {
          this._pressing = false;
          clearTimeout(this._longPressTimer);
          bus.emit('action:request', { action: 'head_pat', source: 'long_press' });
        }
      }
    }, 650);
  }

  _move(e) {
    if (!this._pressing || !this._downClient) return;
    const totalDist = Math.hypot(e.clientX - this._downClient.x, e.clientY - this._downClient.y);
    if (!this._dragging && totalDist > 7) {
      this._dragging = true;
      clearTimeout(this._longPressTimer);
      // Start drag: record starting positions
      this._dragStartGlobal = { x: this.mouseGlobal.x, y: this.mouseGlobal.y };
    }
    if (this._dragging) {
      // Move window by global mouse delta (more reliable than pointer delta)
      const dx = this.mouseGlobal.x - this._dragStartGlobal.x;
      const dy = this.mouseGlobal.y - this._dragStartGlobal.y;
      // Apply immediately for responsive drag
      window.desktop.moveWindowBy(dx - (this._lastDragDx || 0), dy - (this._lastDragDy || 0));
      this._lastDragDx = dx;
      this._lastDragDy = dy;
      this._lastClient = { x: e.clientX, y: e.clientY };
    }
  }

  _up(e) {
    clearTimeout(this._longPressTimer);
    if (!this._pressing) return;
    this._pressing = false;
    const dur = performance.now() - this._downAt;
    const totalDist = this._downClient ? Math.hypot(e.clientX - this._downClient.x, e.clientY - this._downClient.y) : 0;

    if (this._dragging) {
      this._dragging = false;
      this._lastDragDx = 0;
      this._lastDragDy = 0;
      this._dragStartGlobal = null;
      return; // pure drag, no click action
    }
    if (totalDist < 6 && dur < 650) {
      const r = this._hitTest(e.clientX, e.clientY);
      if (r.hit) {
        if (r.isHead) {
          bus.emit('action:request', { action: 'head_pat', source: 'click' });
        } else {
          bus.emit('action:request', { action: 'body_click', source: 'click' });
        }
      }
    }
    this._downClient = null;
    this._lastClient = null;
  }
}
