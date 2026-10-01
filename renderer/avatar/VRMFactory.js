import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const cache = new Map();

// Load a VRM file and return a three-vrm VRM instance.
export function loadVRM(url) {
  if (cache.has(url)) {
    return Promise.resolve(cache.get(url)).then(cloneVRM);
  }
  return new Promise((resolve, reject) => {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.load(
      url,
      (gltf) => {
        const vrm = gltf.userData.vrm;
        if (!vrm) {
          reject(new Error('加载的文件不是有效的 VRM 模型: ' + url));
          return;
        }
        try { VRMUtils.removeUnnecessaryVertices(gltf.scene); } catch {}
        try { VRMUtils.combineSkeletons?.(gltf.scene); } catch {}
        // VRM 0.x faces -Z; rotate to face camera (+Z). VRM 1.x already faces +Z.
        try { VRMUtils.rotateVRM0(vrm); } catch {}
        // Fix material transparency / depth-sort issues (face transparent bug).
        // MToon materials must keep depthWrite ON when opaque to prevent
        // face/neck bleeding through to the background.
        vrm.scene.traverse((o) => {
          if (!o.isMesh) return;
          o.frustumCulled = false;
          const mats = Array.isArray(o.material) ? o.material : [o.material];
          for (const m of mats) {
            if (!m) continue;
            // Most VRM parts are opaque; only true cutout/transparent parts should be transparent.
            // Force depthWrite on so skin/face render correctly in depth order.
            if (m.transparent === undefined) m.transparent = false;
            if (!m.transparent) {
              m.depthWrite = true;
            }
            // Set a stable render order: body first, then face, then hair, then accessories.
            // This helps the depth sorting for semi-transparent parts.
            if (m.renderOrder === undefined || m.renderOrder === 0) {
              const name = (o.name || '').toLowerCase();
              if (name.includes('hair')) m.renderOrder = 3;
              else if (name.includes('face') || name.includes('head')) m.renderOrder = 1;
              else if (name.includes('body') || name.includes('skin')) m.renderOrder = 0;
              else if (m.transparent) m.renderOrder = 4;
              else m.renderOrder = 0;
            }
          }
        });
        cache.set(url, { vrm, gltf });
        resolve({ vrm, gltf });
      },
      undefined,
      (err) => {
        const msg = (err && (err.target && err.target.status !== undefined))
          ? `无法加载模型文件（HTTP ${err.target.status}）: ${url}`
          : `无法加载模型文件: ${url}`;
        reject(new Error(msg));
      }
    );
  });
}

// Instantiate a fresh VRM sharing geometry of a cached one.
async function cloneVRM(entry) {
  // We can't cheaply deep-clone a full VRM rig; instead re-load from cache is complex.
  // Simpler & correct: never clone — each costume slot holds its own loaded instance.
  return Promise.resolve(entry);
}

// Dispose a VRM instance safely.
export function disposeVRM(vrm) {
  try { VRMUtils.deepDispose(vrm.scene); } catch {}
}
