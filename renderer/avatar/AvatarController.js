import * as THREE from 'three';
import { disposeVRM } from './VRMFactory.js';

const BONE_NAMES = [
  'hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
  'leftShoulder', 'leftUpperArm', 'leftLowerArm', 'leftHand',
  'rightShoulder', 'rightUpperArm', 'rightLowerArm', 'rightHand',
  'leftUpperLeg', 'leftLowerLeg', 'leftFoot',
  'rightUpperLeg', 'rightLowerLeg', 'rightFoot',
];

// Central controller over the currently displayed VRM character.
export class AvatarController {
  constructor(sceneManager) {
    this.sm = sceneManager;
    this.vrm = null;
    this._bones = {};
    this._hipsRestY = 0;
    this._currentOpacity = 1;
    this._gazeTarget = new THREE.Object3D();
    this._gazeTarget.position.set(0, 1.0, 4);
    this._taskbarH = 48; // default; replaced by the real workArea delta below
    sceneManager.scene.add(this._gazeTarget);
    // Measure the real taskbar height (bounds - workArea) from the main
    // process so her feet can rest exactly on its top edge.
    try {
      window.desktop?.getWindowInfo?.().then((info) => {
        const wa = info && info.workArea;
        const sc = info && info.screen;
        if (wa && sc && wa.height && sc.height) {
          const tb = sc.height - (wa.y + wa.height);
          if (tb >= 0 && tb < 200) this._taskbarH = tb;
        }
      }).catch(() => {});
    } catch {}
  }

  get bones() { return this._bones; }
  get head() { return this._bones.head || null; }
  get neck() { return this._bones.neck || null; }
  get expressionManager() { return this.vrm ? this.vrm.expressionManager : null; }
  get gazeTarget() { return this._gazeTarget; }
  get currentOpacity() { return this._currentOpacity; }

  async setModel(vrm) {
    if (this.vrm) {
      this.sm.scene.remove(this.vrm.scene);
      disposeVRM(this.vrm);
    }
    this.vrm = vrm;
    // Character placement: standing at the bottom-right of the window with
    // her feet at the taskbar's top edge (minus a small gap). The toolbar now
    // floats ABOVE her head, so placement no longer depends on it.
    // These are world-space offsets applied to the scene root; animation
    // (AnimationController) adds on top of this base each frame.
    //
    // Camera: z=5.5, FOV 45° → half-view at the z=0 plane:
    //   tan(22.5°) × 5.5 ≈ 2.278m (vertical); horizontal scales by aspect.
    const halfView = Math.tan(THREE.MathUtils.degToRad(45 / 2)) * 5.5;
    const vw = window.innerWidth, vh = window.innerHeight;
    // horizontal: same spot as the old toolbar center (bottom-right area)
    const tbCenterX = vw - 60 - 128; // legacy toolbar center x, kept for continuity
    this._basePosX = ((tbCenterX - vw / 2) / (vw / 2)) * (halfView * (vw / vh));
    // vertical: feet rest just above the Windows taskbar
    const taskbarH = Number.isFinite(this._taskbarH) ? this._taskbarH : 48;
    const footPxY = vh - taskbarH - 6; // 6px breathing room above the taskbar
    const pxPerM = vh / (2 * halfView);
    // Some VRM assets have their origin at the hips rather than the feet -
    // measure the real lowest point so her FEET land at the taskbar edge.
    const box = new THREE.Box3().setFromObject(vrm.scene);
    const feetOffsetY = Number.isFinite(box.min.y) ? box.min.y : 0;
    this._basePosY = 0.76 - (footPxY - vh / 2) / pxPerM - feetOffsetY;
    this.vrm.scene.position.set(this._basePosX, this._basePosY, 0);
    this.vrm.scene.rotation.set(0, 0, 0);
    this.vrm.scene.scale.setScalar(1);
    this.sm.scene.add(this.vrm.scene);

    if (this.vrm.lookAt) {
      try {
        this.vrm.lookAt.target = this._gazeTarget;
        if ('applicable' in this.vrm.lookAt) this.vrm.lookAt.applicable = true;
      } catch {}
    }

    this._bones = {};
    for (const n of BONE_NAMES) {
      try {
        const b = this.vrm.humanoid?.getNormalizedBoneNode?.(n);
        if (b) this._bones[n] = b;
      } catch {}
    }
    if (this._bones.hips) this._hipsRestY = this._bones.hips.position.y;
    this.resetPose();
    // NOTE: opacity is NOT forced to 1 here. Forcing it the instant the
    // model loads can flash a frame where textures are not on the GPU yet.
    // The animation loop (AnimationController._applyPose → tickOpacity)
    // damps opacity toward the current action's target every frame, which
    // is the single source of truth for visibility.
    console.log('[avatar] model ready: bones=' + Object.keys(this._bones).length + ' expressions=' + (this.expressionManager ? this.expressionManager.expressions.length : 0));
  }

  resetPose() {
    for (const b of Object.values(this._bones)) {
      b.quaternion.identity();
    }
    if (this._bones.hips) {
      this._bones.hips.position.set(0, this._hipsRestY, 0);
    }
  }

  hasModel() { return !!this.vrm; }

  setExpression(name, v) {
    const em = this.expressionManager;
    if (!em) return;
    try { em.setValue(name, v); } catch {}
  }

  hasExpression(name) {
    const em = this.expressionManager;
    if (!em) return false;
    try {
      return em.expressions.some(e =>
        (e.expressionName || '').toLowerCase() === name.toLowerCase()
      );
    } catch { return false; }
  }

  // Fade the whole character (used for leave/return/spawn).
  setOpacity(o, immediate = false) {
    if (!this.vrm) return;
    this._currentOpacity = immediate ? o : this._currentOpacity;
    const target = o;
    const apply = (op) => {
      this.vrm.scene.traverse((obj) => {
        if (!obj.isMesh) return;
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
        for (const m of mats) {
          if (!m) continue;
          // Only touch materials that are genuinely semi-transparent.
          // Forcing opaque materials to transparent causes the face/skin
          // transparency bug. We only enable transparent mode when fading.
          if (op < 0.999) {
            m.transparent = true;
            m.opacity = op;
            m.depthWrite = false;
          } else {
            // Restore: if the material was originally opaque, keep it opaque.
            m.opacity = 1;
            m.depthWrite = true;
            // Don't force transparent=false — MToon may legitimately be transparent.
          }
        }
      });
    };
    if (immediate) {
      apply(o);
    } else {
      this._opacityTarget = target;
      this._applyOpacity = apply;
    }
  }

  tickOpacity(dt) {
    if (this._opacityTarget === undefined) return;
    const cur = this._currentOpacity;
    const t = this._opacityTarget;
    const next = cur + (t - cur) * (1 - Math.exp(-8 * dt));
    if (Math.abs(next - t) < 0.005) {
      this._currentOpacity = t;
      this._applyOpacity?.(t);
      this._opacityTarget = undefined;
    } else {
      this._currentOpacity = next;
      this._applyOpacity?.(next);
    }
  }

  headWorldPos() {
    const v = new THREE.Vector3();
    if (this.head) this.head.getWorldPosition(v);
    else if (this.vrm) this.vrm.scene.getWorldPosition(v);
    return v;
  }

  chestWorldPos() {
    const v = new THREE.Vector3();
    const b = this._bones.chest || this._bones.spine || this.head;
    if (b) b.getWorldPosition(v);
    return v;
  }

  // Lowest foot world position - anchors bottom-side UI (vertical toolbar).
  footWorldPos() {
    const v = new THREE.Vector3();
    const l = this._bones.leftFoot, r = this._bones.rightFoot;
    const a = new THREE.Vector3(), b = new THREE.Vector3();
    const hasL = !!l, hasR = !!r;
    if (hasL) l.getWorldPosition(a);
    if (hasR) r.getWorldPosition(b);
    if (hasL && hasR) v.set((a.x + b.x) / 2, Math.min(a.y, b.y), (a.z + b.z) / 2);
    else if (hasL) v.copy(a);
    else if (hasR) v.copy(b);
    else if (this.vrm) this.vrm.scene.getWorldPosition(v);
    return v;
  }

  update(dt) {
    if (this.vrm) {
      try { this.vrm.update(dt); } catch (e) { console.error('vrm.update error', e); }
    }
  }
}
