import * as THREE from 'three';

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// Head/neck/eye gaze following the global mouse cursor with smoothing & limits.
export class EyeTrackingController {
  constructor(avatar, sceneManager) {
    this.avatar = avatar;
    this.sm = sceneManager;
    this.mouse = { x: window.innerWidth / 2, y: window.innerHeight / 2 }; // screen px
    this._yaw = 0; this._pitch = 0;
    this.MAX_YAW = 0.62;   // rad ~ 35°
    this.MAX_PITCH = 0.38; // rad ~ 22°
    this._raycaster = new THREE.Raycaster();
    this._planeZ = 0; // avatar stands at z=0 plane
    window.desktop?.onGlobalMouse?.((pos) => { this.mouse = pos; });
  }

  update(dt) {
    if (!this.avatar.hasModel()) return null;

    // screen px -> NDC
    const nx = (this.mouse.x / window.innerWidth) * 2 - 1;
    const ny = -(this.mouse.y / window.innerHeight) * 2 + 1;

    // Project mouse to a world point on the avatar's z-plane.
    this._raycaster.setFromCamera(new THREE.Vector2(nx, ny), this.sm.camera);
    const origin = this._raycaster.ray.origin;
    const dir = this._raycaster.ray.direction;
    let point;
    if (Math.abs(dir.z) > 1e-4) {
      const t = (this._planeZ - origin.z) / dir.z;
      point = origin.clone().addScaledVector(dir, Math.max(t, 0.35));
    } else {
      point = origin.clone();
    }

    // eyes follow the exact point via three-vrm lookAt
    if (this.avatar.gazeTarget) this.avatar.gazeTarget.position.copy(point);

    // head/neck rotation toward the point, clamped
    const headPos = this.avatar.headWorldPos();
    const look = point.clone().sub(headPos).normalize();
    let yaw = Math.atan2(look.x, look.z);          // 0 = facing camera (+Z)
    let pitch = -Math.asin(clamp(look.y, -1, 1)); // negative x-rot looks up
    yaw = clamp(yaw, -this.MAX_YAW, this.MAX_YAW);
    pitch = clamp(pitch, -this.MAX_PITCH, this.MAX_PITCH);

    // smooth follow (faster for big jumps, gentle for small)
    const k = 1 - Math.exp(-7 * dt);
    this._yaw += (yaw - this._yaw) * k;
    this._pitch += (pitch - this._pitch) * k;

    // distribute rotation: neck 35%, head 65%
    const qNeck = new THREE.Quaternion().setFromEuler(new THREE.Euler(this._pitch * 0.35, this._yaw * 0.35, 0, 'YXZ'));
    const qHead = new THREE.Quaternion().setFromEuler(new THREE.Euler(this._pitch * 0.65, this._yaw * 0.65, 0, 'YXZ'));
    return { neck: qNeck, head: qHead };
  }
}
