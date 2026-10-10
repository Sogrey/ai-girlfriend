import * as THREE from 'three';

// ---------------------------------------------------------------
// Procedural animation state machine.
// All poses are defined here as bone Euler targets (VRM normalized
// humanoid space). Every frame we damp current pose toward target,
// which gives free blending between any two states.
// ---------------------------------------------------------------

const TAU = Math.PI * 2;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const easeInOut = (t) => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

function set(P, bone, x = 0, y = 0, z = 0) { P[bone] = { x, y, z }; }

// Base pose: arms naturally down, subtle breathing & sway. Always present.
function idlePose(t, P, sceneT) {
  // arms down at sides with slight bend
  set(P, 'leftUpperArm', 0.08, 0, -1.32);
  set(P, 'rightUpperArm', 0.08, 0, 1.32);
  set(P, 'leftLowerArm', -0.06, 0.18, -0.12);
  set(P, 'rightLowerArm', -0.06, -0.18, 0.12);
  set(P, 'leftHand', 0, 0, -0.08);
  set(P, 'rightHand', 0, 0, 0.08);
  // breathing
  const br = Math.sin(t * TAU * 0.22);
  set(P, 'chest', br * 0.025, 0, 0);
  set(P, 'spine', br * 0.012, 0, 0);
  // gentle body sway
  const sway = Math.sin(t * 0.45);
  set(P, 'hips', sway * 0.012, sway * 0.02, 0);
  // head micro motion
  set(P, 'head', Math.sin(t * 0.3) * 0.02, Math.sin(t * 0.23) * 0.03, 0);
  sceneT.posY = br * 0.006;
  sceneT.posX = 0;
  sceneT.rotY = 0;
  sceneT.opacity = 1;
}

// Walk cycle helper (used by leave / return).
function walkCycle(P, phase, amp = 0.35) {
  const s = Math.sin(phase * TAU * 4);
  set(P, 'leftUpperLeg', s * amp, 0, 0);
  set(P, 'rightUpperLeg', -s * amp, 0, 0);
  set(P, 'leftLowerLeg', Math.max(0, -s) * amp * 1.6, 0, 0);
  set(P, 'rightLowerLeg', Math.max(0, s) * amp * 1.6, 0, 0);
  set(P, 'leftUpperArm', -s * amp * 0.7, 0, -1.15);
  set(P, 'rightUpperArm', s * amp * 0.7, 0, 1.15);
}

// Talk gesture overlay: light arm gesturing + head emphasis while she
// speaks (TTS playing). Blended on top of idle with alpha so it fades in/out.
function talkPose(t, P, S, a) {
  const beat = Math.sin(t * 3.1);
  const mix = (bone, x, y, z) => {
    const cur = P[bone] || { x: 0, y: 0, z: 0 };
    P[bone] = { x: lerp(cur.x, x, a), y: lerp(cur.y, y, a), z: lerp(cur.z, z, a) };
  };
  // right arm slightly raised in front, forearm swaying with speech rhythm
  mix('rightUpperArm', -0.4, -0.1, 0.85);
  mix('rightLowerArm', -0.95 + beat * 0.06, -0.15, 0.32 + beat * 0.09);
  mix('rightHand', 0.1, 0, 0.15 + beat * 0.05);
  // subtle torso groove + head emphasis nods
  mix('chest', 0.02, beat * 0.025, 0);
  mix('head', Math.sin(t * 1.7) * 0.03, Math.sin(t * 1.15) * 0.025, 0);
}

// ------------------ action definitions ------------------
const ACTIONS = {
  wave: {
    dur: 2.6,
    fn(u, t, P, S) {
      // Greeting gesture (ref: raised beside the head, open palm facing
      // the viewer, gentle sway). Right arm to head height, palm forward.
      const osc = Math.sin(u * TAU * 2.0);
      // upper arm: raised beside the head, slightly forward (geometry-checked:
      // hand lands ~5cm above head bone = head height, palm toward viewer)
      set(P, 'rightUpperArm', -0.35, -0.18, 0.35);
      // forearm: slight elbow bend so the hand sits at head height
      set(P, 'rightLowerArm', -0.95, 0.12, 0.12 + osc * 0.1);
      // open the palm toward the viewer (rotate around the forearm axis)
      set(P, 'rightHand', -1.5, 0, 0.1);
      set(P, 'head', 0, -0.1, -0.03);
      set(P, 'neck', 0, -0.04, 0);
      // left hand resting at side
      set(P, 'leftUpperArm', 0.08, 0, 1.2);
      set(P, 'leftLowerArm', -0.06, -0.18, 0.12);
    },
  },
  head_pat: {
    dur: 1.9,
    fn(u, t, P, S) {
      const duck = Math.sin(Math.min(u * 1.25, 1) * Math.PI) * 0.9 + Math.sin(Math.min(u * 1.25, 1) * Math.PI) * 0.1;
      set(P, 'head', 0.3, 0.06 * duck, 0);
      set(P, 'neck', 0.14, 0, 0);
      set(P, 'leftShoulder', 0, 0, -0.14);
      set(P, 'rightShoulder', 0, 0, 0.14);
      // hands shyly toward face
      set(P, 'leftUpperArm', -0.45, 0.25, -0.6);
      set(P, 'leftLowerArm', -1.7, 0.1, -0.3);
      set(P, 'rightUpperArm', -0.45, -0.25, 0.6);
      set(P, 'rightLowerArm', -1.7, -0.1, 0.3);
    },
  },
  shy: {
    dur: 2.4,
    fn(u, t, P, S) {
      set(P, 'spine', 0.07, 0, 0);
      set(P, 'head', 0.16, 0.12, 0.06);
      set(P, 'neck', 0.08, 0.05, 0);
      set(P, 'leftUpperArm', -0.6, 0.3, -0.55);
      set(P, 'leftLowerArm', -1.75, 0.1, -0.35);
      set(P, 'rightUpperArm', -0.6, -0.3, 0.55);
      set(P, 'rightLowerArm', -1.75, -0.1, 0.35);
    },
  },
  angry: {
    dur: 2.2,
    fn(u, t, P, S) {
      const stomp = Math.sin(u * TAU * 2);
      set(P, 'chest', -0.05, 0, 0);
      set(P, 'head', 0.1, 0, 0.03);
      set(P, 'hips', 0, 0, stomp * 0.03);
      set(P, 'leftUpperArm', 0.15, 0.35, -0.4);
      set(P, 'leftLowerArm', -0.5, -0.3, -0.5);
      set(P, 'rightUpperArm', 0.15, -0.35, 0.4);
      set(P, 'rightLowerArm', -0.5, 0.3, 0.5);
    },
  },
  surprised: {
    dur: 1.5,
    fn(u, t, P, S) {
      set(P, 'spine', -0.14, 0, 0);
      set(P, 'head', -0.14, 0, 0);
      set(P, 'neck', -0.06, 0, 0);
      set(P, 'leftUpperArm', -1.05, 0.2, -0.3);
      set(P, 'leftLowerArm', -1.35, 0, -0.2);
      set(P, 'rightUpperArm', -1.05, -0.2, 0.3);
      set(P, 'rightLowerArm', -1.35, 0, 0.2);
    },
  },
  comfort: {
    dur: 3.0,
    fn(u, t, P, S) {
      const reach = Math.sin(Math.min(u * 1.6, 1) * Math.PI * 0.5);
      set(P, 'spine', 0.13 * reach, 0, 0);
      set(P, 'head', 0.11, 0, 0);
      set(P, 'leftUpperArm', -0.5 * reach, 0.15, -0.75);
      set(P, 'leftLowerArm', -0.4, 0, -0.3);
      set(P, 'rightUpperArm', -0.5 * reach, -0.15, 0.75);
      set(P, 'rightLowerArm', -0.4, 0, 0.3);
    },
  },
  jump: {
    dur: 1.2,
    fn(u, t, P, S) {
      const hop = Math.sin(u * Math.PI);
      S.posY = hop * 0.34;
      const bend = (u < 0.18 || u > 0.8) ? 1 : 0.1;
      set(P, 'leftUpperLeg', 0.5 * bend, 0, 0);
      set(P, 'rightUpperLeg', 0.5 * bend, 0, 0);
      set(P, 'leftLowerLeg', -0.8 * bend, 0, 0);
      set(P, 'rightLowerLeg', -0.8 * bend, 0, 0);
      set(P, 'leftUpperArm', 0, 0, -0.7 - hop * 0.5);
      set(P, 'rightUpperArm', 0, 0, 0.7 + hop * 0.5);
      set(P, 'head', -0.08 * hop, 0, 0);
    },
  },
  dance: {
    dur: 4.4,
    fn(u, t, P, S) {
      const beat = u * TAU * 2;
      S.posY = Math.abs(Math.sin(beat)) * 0.05;
      set(P, 'hips', 0, Math.sin(beat) * 0.28, Math.sin(beat + 0.6) * 0.08);
      set(P, 'chest', -0.03, -Math.sin(beat) * 0.22, 0);
      set(P, 'leftUpperArm', 0.1, 0, -1.1 - Math.sin(beat) * 0.75);
      set(P, 'rightUpperArm', 0.1, 0, 1.1 + Math.sin(beat) * 0.75);
      set(P, 'leftLowerArm', -0.5, 0, -0.45 - Math.sin(beat) * 0.2);
      set(P, 'rightLowerArm', -0.5, 0, 0.45 + Math.sin(beat) * 0.2);
      set(P, 'head', Math.sin(beat) * 0.09, Math.sin(beat * 0.5) * 0.12, Math.sin(beat + 1.2) * 0.06);
    },
  },
  think: {
    dur: 3.0,
    fn(u, t, P, S) {
      set(P, 'head', 0.04, 0.16, -0.06);
      set(P, 'neck', 0.02, 0.06, 0);
      set(P, 'rightUpperArm', -0.55, -0.35, 0.55);
      set(P, 'rightLowerArm', -1.62, 0, 0.35);
      set(P, 'rightHand', 0.2, 0, 0);
      set(P, 'leftUpperArm', -0.25, 0.35, -0.5);
      set(P, 'leftLowerArm', -1.05, 0.7, -0.25);
    },
  },
  leave: {
    dur: 2.6,
    fn(u, t, P, S) {
      // Wave goodbye, then fade out. No walking.
      S.posX = 0;
      S.rotY = 0;
      if (u < 0.55) {
        // wave goodbye
        const osc = Math.sin(u * TAU * 3);
        const waveStrength = Math.sin(u / 0.55 * Math.PI);
        set(P, 'rightUpperArm', -0.3 * waveStrength, -0.1, 0.5 * waveStrength + 1.32 * (1 - waveStrength));
        set(P, 'rightLowerArm', -1.1 * waveStrength - 0.06 * (1 - waveStrength), 0.15 * waveStrength, 0.2 * waveStrength + osc * 0.25 * waveStrength + 0.12 * (1 - waveStrength));
      }
      // fade out in last 40%
      if (u > 0.6) S.opacity = clamp(1 - (u - 0.6) / 0.4, 0, 1);
    },
  },
  return: {
    dur: 2.8,
    fn(u, t, P, S) {
      // Simple: fade in, then wave hello. No walking (avoids rotation issues).
      S.opacity = clamp(u / 0.2, 0, 1);
      S.posX = 0;
      S.rotY = 0;
      if (u < 0.3) {
        // small happy hop as she appears
        const hop = Math.sin(u / 0.3 * Math.PI);
        S.posY = hop * 0.08;
      }
      // wave hello throughout, strongest in middle (palm-forward greeting)
      const waveStrength = Math.sin(u * Math.PI);
      const osc = Math.sin(u * TAU * 2.0);
      set(P, 'rightUpperArm', -0.35 * waveStrength, -0.18 * waveStrength, 0.35 * waveStrength + 1.32 * (1 - waveStrength));
      set(P, 'rightLowerArm', -0.95 * waveStrength - 0.06 * (1 - waveStrength), 0.12 * waveStrength, 0.12 * waveStrength + osc * 0.1 * waveStrength + 0.12 * (1 - waveStrength));
      set(P, 'rightHand', -1.5 * waveStrength, 0, 0.1);
      set(P, 'head', 0, -0.08 * waveStrength, -0.02);
    },
  },
  change_costume: {
    dur: 2.0,
    spin: true,
    fn(u, t, P, S) {
      // twirl with arms slightly out
      set(P, 'leftUpperArm', 0.05, 0, -0.45);
      set(P, 'rightUpperArm', 0.05, 0, 0.45);
      set(P, 'leftLowerArm', -0.2, 0, -0.3);
      set(P, 'rightLowerArm', -0.2, 0, 0.3);
      set(P, 'head', 0.02, 0, -0.04);
      S.spinY = easeInOut(u) * TAU; // full 360 twirl
      // Ensure we always end facing camera (spinY=0 ≡ 2π≡0 visually)
      if (u >= 1) S.spinY = 0;
    },
  },
  nod: {
    dur: 1.4,
    fn(u, t, P, S) {
      // 1.5 nod cycles with a slight affirming base tilt
      const n = Math.sin(u * Math.PI * 3);
      const env = Math.sin(u * Math.PI); // ease in/out
      set(P, 'head', 0.06 + n * 0.14 * env, 0, 0);
      set(P, 'neck', 0.02 + n * 0.05 * env, 0, 0);
    },
  },
  blow_kiss: {
    dur: 2.2,
    fn(u, t, P, S) {
      // phase 1 (u<=0.4): hand rises to the mouth (elbow deep bend)
      // phase 2 (0.4<u<=0.8): forearm extends toward the viewer, palm opens
      // phase 3: hold the send pose, easing back is handled by pose damping
      const toMouth = easeInOut(clamp(u / 0.4, 0, 1));
      const send = easeInOut(clamp((u - 0.4) / 0.4, 0, 1));
      const hold = 1 - send;
      // upper arm: forward-raised throughout (hand at mouth height)
      set(P, 'rightUpperArm', -1.3 * toMouth, -0.2, 0.5 * hold + 0.3 * send);
      // elbow: deeply bent at the mouth (-1.7), extends toward viewer (-0.3)
      set(P, 'rightLowerArm', (-1.7 * hold + -0.3 * send) * toMouth, -0.1, 0.25 * hold + 0.05 * send);
      // palm: closed near mouth, opens toward viewer when sending
      set(P, 'rightHand', 0.3 * hold + -0.5 * send, 0, 0.12);
      // head tilts slightly toward the hand as the kiss goes out
      set(P, 'head', 0.05 * send, -0.12 * send, -0.04 * send);
      // left arm stays relaxed at the side
      set(P, 'leftUpperArm', 0.08, 0, -1.25);
      set(P, 'leftLowerArm', -0.06, 0.18, -0.12);
    },
  },
  stretch: {
    dur: 3.4,
    fn(u, t, P, S) {
      // arms rise overhead (30%), hold with a wobble, come back down (30%).
      // NOTE: for VRM normalized upper arms the SIDE-RAISE axis is Z
      // (1.32 = hanging down, ~0.35 = raised, negative = overhead/out);
      // X is only the forward/back swing. Verified against wave/surprised.
      const rise = easeInOut(clamp(u / 0.3, 0, 1));
      const fall = easeInOut(clamp((u - 0.7) / 0.3, 0, 1));
      const up = rise * (1 - fall);
      const wob = Math.sin(t * 3) * 0.05 * up;
      // Calibrated (probe-verified): the forward-raise X axis puts the arms
      // overhead (~-2.7 rad); Z stays slightly open to avoid body clipping.
      set(P, 'leftUpperArm', -2.7 * up, 0, -(0.35 + wob));
      set(P, 'rightUpperArm', -2.7 * up, 0, 0.35 + wob);
      set(P, 'leftLowerArm', -0.06, 0.18, -(0.12 + 0.4 * up));
      set(P, 'rightLowerArm', -0.06, -0.18, 0.12 + 0.4 * up);
      set(P, 'leftHand', 0, 0, -0.08 - 0.1 * up);
      set(P, 'rightHand', 0, 0, 0.08 + 0.1 * up);
      // lean back slightly, look up
      set(P, 'spine', -0.12 * up, 0, 0);
      set(P, 'chest', -0.05 * up, 0, 0);
      set(P, 'head', 0.14 * up, 0, 0);
      S.posY = up * 0.015; // a tiny lift on the tiptoe stretch
    },
  },
  shake_head: {
    dur: 1.4,
    fn(u, t, P, S) {
      // mirror of `nod`: 2.5 quick left-right cycles on the Y axis (face
      // turn). Y reads visually weaker than nod's X dip, so the amplitude
      // is larger. Envelope eases in/out like nod.
      const n = Math.sin(u * Math.PI * 5);
      const env = Math.sin(u * Math.PI);
      set(P, 'head', 0.03, n * 0.26 * env, 0);
      set(P, 'neck', 0.01, n * 0.09 * env, 0);
    },
  },
  greet: {
    dur: 3.0,
    fn(u, t, P, S) {
      // Greeting combo: cheerful palm-forward wave + two light bounces,
      // left hand settles on the hip for a cheeky hello.
      const ws = Math.sin(u * Math.PI);      // wave envelope
      const osc = Math.sin(u * TAU * 2.5);   // hand wiggle
      const hop = Math.abs(Math.sin(u * Math.PI * 2)) * ws;
      S.posY = hop * 0.09;
      // right arm: raised beside the head, palm toward viewer (wave's
      // geometry-checked path), blended from the resting pose
      set(P, 'rightUpperArm', -0.35 * ws, -0.18 * ws, 0.35 * ws + 1.32 * (1 - ws));
      set(P, 'rightLowerArm', -0.95 * ws - 0.06 * (1 - ws), 0.12 * ws, 0.12 * ws + osc * 0.12 * ws + 0.12 * (1 - ws));
      set(P, 'rightHand', -1.5 * ws, 0, 0.1);
      // left arm: resting -> light akimbo (arm values borrowed from `angry`)
      set(P, 'leftUpperArm', 0.08 * (1 - ws) + 0.15 * ws, 0.35 * ws, -1.32 * (1 - ws) - 0.4 * ws);
      set(P, 'leftLowerArm', -0.06 * (1 - ws) - 0.5 * ws, 0.18 * (1 - ws) - 0.3 * ws, -0.12 * (1 - ws) - 0.5 * ws);
      // head tilts a touch toward the waving side
      set(P, 'head', 0, -0.1 * ws, -0.03 * ws);
      set(P, 'neck', 0, -0.04 * ws, 0);
    },
  },
  spin: {
    dur: 1.6,
    fn(u, t, P, S) {
      // playful 360° twirl (same spinY mechanism as change_costume) with
      // arms out, a small lift and a carefree head tilt
      set(P, 'leftUpperArm', 0.05, 0, -0.5);
      set(P, 'rightUpperArm', 0.05, 0, 0.5);
      set(P, 'leftLowerArm', -0.2, 0, -0.3);
      set(P, 'rightLowerArm', -0.2, 0, 0.3);
      set(P, 'leftHand', 0, 0, -0.2);
      set(P, 'rightHand', 0, 0, 0.2);
      set(P, 'head', 0.03, Math.sin(u * Math.PI) * 0.08, -0.05);
      set(P, 'hips', 0, Math.sin(u * Math.PI * 2) * 0.04, 0);
      S.posY = Math.sin(u * Math.PI) * 0.06;
      S.spinY = easeInOut(u) * TAU; // full twirl, ends facing camera
      if (u >= 1) S.spinY = 0;
    },
  },
};

export class AnimationController {
  constructor(avatar) {
    this.avatar = avatar;
    this.state = 'idle';
    this.u = 0;
    this.t = 0;
    this.damp = 9;         // pose damping speed
    this.posDamp = 6;
    this.onDone = null;
    this.onMid = null;
    this._midFired = false;

    // internal current values (damped)
    this._q = new Map();     // bone name -> THREE.Quaternion
    this._posX = 0;
    this._posY = 0;
    this._rotY = 0;
    this._spinY = 0;
    this._firstFrame = true;
    // talking overlay state (speech gesturing, alpha-blended over idle)
    this._talking = false;
    this._talkA = 0;
  }

  get isBusy() { return this.state !== 'idle'; }

  // speech gesturing: while she talks (TTS playing) her idle pose gets a
  // light gesturing overlay. Ignored while a named action is playing.
  setTalking(on) {
    const v = !!on;
    if (this._talking !== v) this._talking = v;
  }

  play(name, opts = {}) {
    if (!ACTIONS[name]) name = 'idle';
    this.state = name;
    this.u = 0;
    this.onDone = opts.onDone || null;
    this.onMid = opts.onMid || null;
    this._midFired = false;
    if (name === 'idle') { this.onDone = null; this.onMid = null; }
  }

  interrupt() {
    // cancel current action, return to idle smoothly
    const cb = this.onDone;
    this.state = 'idle';
    this.u = 0;
    this.onDone = null;
    this.onMid = null;
    // don't call cb - it was cancelled
  }

  update(dt, gaze = null) {
    this.t += dt;
    const act = ACTIONS[this.state];
    const P = {};
    const S = { posX: 0, posY: 0, rotY: 0, opacity: 1, spinY: this._spinY };

    idlePose(this.t, P, S);

    // talking overlay blends over idle only (named actions take precedence)
    const talkTarget = (this._talking && this.state === 'idle') ? 1 : 0;
    this._talkA = lerp(this._talkA, talkTarget, 1 - Math.exp(-4 * dt));
    if (this._talkA > 0.02) talkPose(this.t, P, S, this._talkA);

    if (act) {
      this.u += dt / act.dur;
      if (!this._midFired && this.u >= 0.5 && this.onMid) {
        this._midFired = true;
        try { this.onMid(); } catch (e) { console.error(e); }
      }
      act.fn(clamp(this.u, 0, 1), this.t, P, S);
      if (this.u >= 1) {
        const cb = this.onDone;
        this.state = 'idle';
        this.u = 0;
        this.onDone = null;
        this.onMid = null;
        if (this.state === 'idle' && ACTIONS.change_costume) { /* noop */ }
        if (cb) { try { cb(); } catch (e) { console.error(e); } }
      }
    }

    this._applyPose(P, S, dt, gaze);
  }

  _applyPose(P, S, dt, gaze) {
    const bones = this.avatar.bones;
    const k = 1 - Math.exp(-this.damp * dt);

    const tmpQ = new THREE.Quaternion();
    const tmpE = new THREE.Euler();

    for (const [name, rot] of Object.entries(P)) {
      const bone = bones[name];
      if (!bone) continue;
      tmpE.set(rot.x, rot.y, rot.z, 'XYZ');
      tmpQ.setFromEuler(tmpE);
      let cur = this._q.get(name);
      if (!cur) { cur = new THREE.Quaternion(); this._q.set(name, cur); }
      if (this._firstFrame) cur.copy(tmpQ);
      cur.slerp(tmpQ, k);
      bone.quaternion.copy(cur);

      // gaze layering on head/neck
      if (gaze && (name === 'head' || name === 'neck')) {
        const gq = name === 'head' ? gaze.head : gaze.neck;
        if (gq) bone.quaternion.multiply(gq);
      }
    }

    // scene-level position / rotation / opacity
    const kp = 1 - Math.exp(-this.posDamp * dt);
    this._posX = this._firstFrame ? S.posX : lerp(this._posX, S.posX, kp);
    this._posY = this._firstFrame ? S.posY : lerp(this._posY, S.posY, kp);
    this._rotY = this._firstFrame ? S.rotY : lerp(this._rotY, S.rotY, kp);
    this._spinY = this._firstFrame ? S.spinY : lerp(this._spinY, S.spinY, kp * 1.2);

    if (this.avatar.vrm) {
      const sc = this.avatar.vrm.scene;
      // Add base position offset from AvatarController (lower-right placement)
      const baseX = this.avatar._basePosX || 0;
      const baseY = this.avatar._basePosY || 0;
      sc.position.x = baseX + this._posX;
      sc.position.y = baseY + this._posY;
      sc.rotation.y = this._rotY + this._spinY;
    }
    this.avatar.setOpacity(S.opacity);

    this._firstFrame = false;
  }
}

export const ACTION_DURATIONS = Object.fromEntries(
  Object.entries(ACTIONS).map(([k, v]) => [k, v.dur])
);
