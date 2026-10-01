import * as THREE from 'three';

function makeHeartTexture(color = '#ff5e93') {
  const c = document.createElement('canvas');
  c.width = 64; c.height = 64;
  const ctx = c.getContext('2d');
  ctx.fillStyle = color;
  // heart = two circles + rotated square
  ctx.beginPath();
  const cx = 32, cy = 26, r = 13;
  ctx.arc(cx - r * 0.92, cy, r, 0, Math.PI * 2);
  ctx.arc(cx + r * 0.92, cy, r, 0, Math.PI * 2);
  ctx.moveTo(cx - 2 * r, cy + 1);
  ctx.lineTo(cx + 2 * r, cy + 1);
  ctx.lineTo(cx, cy + 24);
  ctx.closePath();
  ctx.shadowColor = color;
  ctx.shadowBlur = 8;
  ctx.fill();
  ctx.fill();
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeStarTexture(color = '#ffe08a') {
  const c = document.createElement('canvas');
  c.width = 64; c.height = 64;
  const ctx = c.getContext('2d');
  ctx.fillStyle = color;
  ctx.shadowColor = color;
  ctx.shadowBlur = 10;
  ctx.beginPath();
  const cx = 32, cy = 32, R = 26, r = 11;
  for (let i = 0; i < 10; i++) {
    const ang = (Math.PI / 5) * i - Math.PI / 2;
    const rad = i % 2 === 0 ? R : r;
    const x = cx + Math.cos(ang) * rad, y = cy + Math.sin(ang) * rad;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fill();
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

// Lightweight sprite particle system for hearts / stars effects.
export class ParticleSystem {
  constructor(sceneManager) {
    this.sm = sceneManager;
    this.texHeart = makeHeartTexture();
    this.texStar = makeStarTexture();
    this.pool = [];
    this.active = [];
    this._initPool(60);
  }

  _initPool(n) {
    for (let i = 0; i < n; i++) {
      const mat = new THREE.SpriteMaterial({ map: this.texHeart, transparent: true, depthWrite: false, opacity: 0 });
      const s = new THREE.Sprite(mat);
      s.visible = false;
      this.pool.push(s);
    }
  }

  _get() {
    return this.pool.pop() || null;
  }

  spawnHearts(worldPos, count = 14, opts = {}) {
    this._spawn(worldPos, count, { tex: this.texHeart, color: 0xff7fb0, size: 0.14, up: 0.55, spread: 0.5, life: 1.3, ...opts });
  }
  spawnStars(worldPos, count = 20, opts = {}) {
    this._spawn(worldPos, count, { tex: this.texStar, color: 0xffe6a0, size: 0.1, up: 0.7, spread: 0.8, life: 1.1, ...opts });
  }
  spawnBurst(worldPos, count = 26, opts = {}) {
    this._spawn(worldPos, count, { tex: this.texStar, color: 0xaee6ff, size: 0.09, up: 0.3, spread: 1.2, life: 0.9, ...opts });
  }

  _spawn(worldPos, count, o) {
    for (let i = 0; i < count; i++) {
      const s = this._get();
      if (!s) return;
      s.material.map = o.tex;
      s.material.color = new THREE.Color(o.color);
      s.material.opacity = 0;
      s.position.copy(worldPos)
        .add(new THREE.Vector3(
          (Math.random() - 0.5) * o.spread,
          (Math.random() - 0.3) * o.spread * 0.6,
          (Math.random() - 0.5) * o.spread * 0.4
        ));
      s.scale.setScalar(o.size * (0.6 + Math.random() * 0.8));
      s.visible = true;
      this.sm.scene.add(s);
      this.active.push({
        s, life: o.life * (0.7 + Math.random() * 0.6), age: 0,
        vel: new THREE.Vector3((Math.random() - 0.5) * 0.35, o.up * (0.6 + Math.random() * 0.8), (Math.random() - 0.5) * 0.15),
        size: s.scale.x,
      });
    }
  }

  update(dt) {
    for (let i = this.active.length - 1; i >= 0; i--) {
      const p = this.active[i];
      p.age += dt;
      const u = p.age / p.life;
      if (u >= 1) {
        p.s.visible = false;
        p.s.material.opacity = 0;
        this.sm.scene.remove(p.s);
        this.active.splice(i, 1);
        this.pool.push(p.s);
        continue;
      }
      p.s.position.addScaledVector(p.vel, dt);
      p.vel.y += 0.12 * dt; // slight float-up acceleration, no hard gravity
      p.vel.multiplyScalar(1 - 0.6 * dt);
      const fadeIn = Math.min(u * 6, 1);
      p.s.material.opacity = fadeIn * (1 - u) * 0.95;
      const sc = p.size * (0.85 + 0.35 * Math.sin(u * Math.PI));
      p.s.scale.setScalar(sc);
    }
  }
}
