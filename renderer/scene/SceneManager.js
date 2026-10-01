import * as THREE from 'three';

// Three.js scene management: renderer, camera, lights, frame loop.
export class SceneManager {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
      powerPreference: 'high-performance',
      preserveDrawingBuffer: false,
    });
    this.renderer.setClearColor(0x000000, 0); // fully transparent background
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.NoToneMapping;
    // Enable proper transparency sorting for MToon materials (VRM skin/face)
    this.renderer.sortObjects = true;

    this.scene = new THREE.Scene();
    this.clock = new THREE.Clock();

    // Camera: centered. Character position via AvatarController basePos.
    // FOV 45 + distance 5.5 => 1.62m model ≈ 1/3 screen height.
    const w = window.innerWidth, h = window.innerHeight;
    this.camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
    this.camera.position.set(0, 0.76, 5.5);
    this.camera.lookAt(new THREE.Vector3(0, 0.76, 0));
    this.cameraTarget = new THREE.Vector3(0, 0.76, 0);

    this._setupLights();
    this._frameCbs = new Set();

    window.addEventListener('resize', () => this.resize());
    this.resize();
  }

  _setupLights() {
    const amb = new THREE.AmbientLight(0xffffff, 0.9);
    const key = new THREE.DirectionalLight(0xfff0e8, 1.6); // warm key light from front-top
    key.position.set(0.6, 2.4, 2.0);
    const rim = new THREE.DirectionalLight(0xbfd8ff, 0.8); // cool rim light from behind
    rim.position.set(-1.2, 1.6, -1.8);
    const fill = new THREE.DirectionalLight(0xffd9ec, 0.35); // pink fill, bottom-front
    fill.position.set(0.4, -0.6, 1.6);
    this.scene.add(amb, key, rim, fill);
    this._keyLight = key;
  }

  resize() {
    const w = window.innerWidth, h = window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  onFrame(fn) { this._frameCbs.add(fn); }

  start() {
    const loop = () => {
      const dt = Math.min(this.clock.getDelta(), 0.1);
      this._frameCbs.forEach(fn => { try { fn(dt); } catch (e) { console.error(e); } });
      this.renderer.render(this.scene, this.camera);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  // Convert world position to screen pixels.
  worldToScreen(v3) {
    const v = v3.clone().project(this.camera);
    return {
      x: (v.x * 0.5 + 0.5) * window.innerWidth,
      y: (-v.y * 0.5 + 0.5) * window.innerHeight,
    };
  }
}
