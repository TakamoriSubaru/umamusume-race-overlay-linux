'use strict';
/*
 * Exact-name Frida hook based on the original Race Overlay's resources/race.js.
 * It reads the known RaceManager singleton clock and intercepts RaceInfo setup
 * for replay/runners. It does not change or patch game state.
 */

const MODULE_NAME = 'GameAssembly.dll';
const POLL_MS = 100;
const ACTIVE_STATES = [3, 4, 5];
const NULLP = ptr(0);
const HDR = 0x10;
const warned = new Set();
let ga = null;
let api = null;
let domain = NULLP;
let images = [];
let setupHook = null;
let bootTimer = null;
let managerClass = null;
let replayBaseClass = null;
let raceInfoClass = null;
let fields = {};
let lastActive = null;
let lastTime = null;
let lastReplay = null;
let fsmKeyOffset = null;
let bootAttempts = 0;

function say(level, text, extra) {
  send(Object.assign({ type: 'status', level: level, text: text }, extra || {}));
}
function warnOnce(key, text) {
  if (warned.has(key)) return;
  warned.add(key);
  say('warn', text);
}
function safe(fn, fallback) {
  try { return fn(); } catch (e) { return fallback === undefined ? null : fallback; }
}
function cstr(s) { return Memory.allocUtf8String(s); }
function valid(p) {
  try {
    if (p === null || p === undefined || p.isNull()) return false;
    return Process.findRangeByAddress(p) !== null;
  } catch (e) { return false; }
}

const API_SIGS = {
  domain_get: ['pointer', []],
  thread_attach: ['pointer', ['pointer']],
  domain_get_assemblies: ['pointer', ['pointer', 'pointer']],
  assembly_get_image: ['pointer', ['pointer']],
  class_from_name: ['pointer', ['pointer', 'pointer', 'pointer']],
  class_get_parent: ['pointer', ['pointer']],
  class_get_method_from_name: ['pointer', ['pointer', 'pointer', 'int']],
  class_get_field_from_name: ['pointer', ['pointer', 'pointer']],
  field_get_offset: ['uint32', ['pointer']],
  field_static_get_value: ['void', ['pointer', 'pointer']],
};

function bindApi(module) {
  const result = {};
  const missing = [];
  for (const key of Object.keys(API_SIGS)) {
    const exp = module.findExportByName('il2cpp_' + key);
    if (!exp || exp.isNull()) {
      // thread_attach is helpful but not essential for all builds.
      if (key !== 'thread_attach') missing.push('il2cpp_' + key);
      continue;
    }
    result[key] = new NativeFunction(exp, API_SIGS[key][0], API_SIGS[key][1]);
  }
  if (missing.length) throw new Error('Missing IL2CPP exports: ' + missing.join(', '));
  return result;
}

function enumerateImages() {
  const countBuf = Memory.alloc(Process.pointerSize);
  countBuf.writePointer(NULLP);
  const asms = api.domain_get_assemblies(domain, countBuf);
  const count = countBuf.readU32();
  if (!valid(asms) || count < 1 || count > 4096) return [];
  const found = [];
  for (let i = 0; i < count; i++) {
    const asm = safe(() => asms.add(i * Process.pointerSize).readPointer());
    const img = asm && valid(asm) ? safe(() => api.assembly_get_image(asm)) : null;
    if (img && valid(img)) found.push(img);
  }
  return found;
}
function findClass(ns, name) {
  for (const img of images) {
    const k = safe(() => api.class_from_name(img, cstr(ns), cstr(name)));
    if (k && valid(k)) return k;
  }
  return null;
}
function findField(klass, names) {
  for (const name of names) {
    let k = klass;
    for (let depth = 0; k && valid(k) && depth < 16; depth++) {
      const f = safe(() => api.class_get_field_from_name(k, cstr(name)));
      if (f && valid(f)) return { info: f, offset: api.field_get_offset(f), name: name };
      if (!api.class_get_parent) break;
      const parent = safe(() => api.class_get_parent(k));
      if (!parent || parent.isNull()) break;
      k = parent;
    }
  }
  return null;
}
function findMethod(klass, name, argc) {
  if (!klass) return null;
  const m = safe(() => api.class_get_method_from_name(klass, cstr(name), argc));
  if (!m || !valid(m)) return null;
  const fn = safe(() => m.readPointer());
  if (!fn || !valid(fn)) return null;
  return fn;
}
function readStr(p) {
  if (!valid(p)) return '';
  return safe(() => {
    const len = p.add(HDR).readS32();
    if (len < 0 || len > 0x100000) return '';
    return len === 0 ? '' : p.add(HDR + 4).readUtf16String(len);
  }, '');
}
function readI32(obj, fld, fallback) {
  if (!valid(obj) || !fld) return fallback === undefined ? 0 : fallback;
  return safe(() => obj.add(fld.offset).readS32(), fallback === undefined ? 0 : fallback);
}
function readPtrField(obj, fld) {
  if (!valid(obj) || !fld) return null;
  return safe(() => obj.add(fld.offset).readPointer());
}
function runtimeClass(obj) {
  return valid(obj) ? safe(() => obj.readPointer()) : null;
}
function fieldOnObj(obj, names) {
  const k = runtimeClass(obj);
  return k && valid(k) ? findField(k, names) : null;
}
function readStaticPointer(field) {
  if (!field) return null;
  const out = Memory.alloc(Process.pointerSize);
  out.writePointer(NULLP);
  api.field_static_get_value(field.info, out);
  return safe(() => out.readPointer());
}

function extractCourseId(ri) {
  const cs = readPtrField(ri, fields.riCourseSet);
  if (!valid(cs)) return null;
  const idField = fieldOnObj(cs, ['<Id>k__BackingField', 'Id', '_id']);
  return idField ? readI32(cs, idField, null) : null;
}
function extractCourseInfo(ri) {
  const k = runtimeClass(ri);
  if (!valid(k)) return {};
  const readOptional = names => {
    const f = findField(k, names);
    return f ? safe(() => ri.add(f.offset).readS32()) : null;
  };
  return {
    weather: readOptional(['<Weather>k__BackingField', 'weather']),
    groundCondition: readOptional(['<GroundCondition>k__BackingField', 'groundCondition', 'ground_condition']),
    season: readOptional(['<Season>k__BackingField', 'season']),
  };
}
function extractHorses(ri) {
  const arr = readPtrField(ri, fields.riHorses);
  if (!valid(arr)) return [];
  const count = safe(() => arr.add(24).readS32(), 0);
  if (count < 0 || count > 24) return [];
  const runners = [];
  const rmap = {};
  for (let i = 0; i < count; i++) {
    const horse = safe(() => arr.add(32 + i * Process.pointerSize).readPointer());
    if (!valid(horse)) continue;
    const hk = runtimeClass(horse);
    if (!valid(hk)) continue;

    const nameF = findField(hk, ['<charaName>k__BackingField']);
    const name = nameF ? readStr(readPtrField(horse, nameF)) : '';
    const gateF = findField(hk, ['postNumber']);
    const gate = gateF ? readI32(horse, gateF, i + 1) : i + 1;
    const charaF = findField(hk, ['<CharaId>k__BackingField', 'chara_id', '_charaId']);
    let charaId = charaF ? readI32(horse, charaF, 0) : 0;
    const directDressF = findField(hk, ['<DressId>k__BackingField', 'race_dress_id', 'dressId', '_dressId']);
    let dressId = directDressF ? readI32(horse, directDressF, 0) : 0;
    let style = 2;
    let frameOrder = i + 1;
    let trainer = '';

    const responseF = findField(hk, ['_responseHorseData']);
    const rd = responseF ? readPtrField(horse, responseF) : null;
    if (valid(rd)) {
      const rk = runtimeClass(rd);
      if (valid(rk)) {
        const styleF = findField(rk, ['running_style']);
        const frameF = findField(rk, ['frame_order']);
        if (styleF) style = readI32(rd, styleF, 2);
        if (frameF) frameOrder = readI32(rd, frameF, i + 1);
        for (const candidate of ['owner_trainer_name', 'trainer_name', 'player_name', 'name']) {
          const tf = findField(rk, [candidate]);
          const tp = tf ? readPtrField(rd, tf) : null;
          const tv = readStr(tp);
          if (tv) { trainer = tv; break; }
        }
        if (!dressId) {
          const df = findField(rk, ['race_dress_id', 'card_id']);
          if (df) dressId = readI32(rd, df, 0);
        }
      }
    }
    if (!charaId && dressId) charaId = Math.floor(dressId / 100);
    const fo = frameOrder > 0 ? frameOrder : (gate > 0 ? gate : i + 1);
    runners.push({ name: name || ('Horse ' + (i + 1)), trainer: trainer, style: style,
      gate: gate, frameOrder: fo, charaId: charaId, dressId: dressId });
    rmap[String(fo)] = { fo: fo, chara_id: charaId,
      card_id: charaId ? charaId * 100 + 1 : 0, finishOrder: 0, finishTimeRaw: 0 };
  }
  return { runners: runners, rmap: rmap };
}

function sendRace(ri) {
  if (!valid(ri) || !fields.riReplay) return;
  const replay = readStr(readPtrField(ri, fields.riReplay));
  if (!replay || replay.length < 64) return;
  if (replay === lastReplay) return;
  lastReplay = replay;
  const horses = safe(() => extractHorses(ri), { runners: [], rmap: {} });
  const courseId = safe(() => extractCourseId(ri));
  const courseInfo = safe(() => extractCourseInfo(ri), {});
  say('info', 'Captured race replay (' + replay.length + ' base64 characters); runners=' + horses.runners.length);
  send({ type: 'race', replay: replay, compressed: replay.indexOf('H4sI') === 0,
    runners: horses.runners, rmap: horses.rmap, courseId: courseId,
    courseInfo: courseInfo, courseShape: {}, courseData: {} });
}

function readFsmState(instance) {
  const fsm = readPtrField(instance, fields.fsm);
  if (!valid(fsm)) return null;
  const klass = runtimeClass(fsm);
  if (!valid(klass)) return null;
  if (fsmKeyOffset === null) {
    const key = findField(klass, ['_currentStateKey']);
    fsmKeyOffset = key ? key.offset : -1;
    if (fsmKeyOffset < 0) warnOnce('fsm-key', 'Could not resolve FSM field _currentStateKey.');
  }
  if (fsmKeyOffset < 0) return null;
  const value = safe(() => fsm.add(fsmKeyOffset).readS32());
  return Number.isInteger(value) && value >= 0 && value <= 15 ? value : null;
}
function emitClock() {
  if (!fields.rmInstance || !fields.rmTime) return;
  const instance = readStaticPointer(fields.rmInstance);
  if (!valid(instance)) {
    if (lastActive !== false) send({ type: 'clock', active: false, time: 0, aiStates: {} });
    lastActive = false;
    lastTime = null;
    return;
  }
  const rawTime = safe(() => instance.add(fields.rmTime.offset).readFloat());
  const state = readFsmState(instance);
  const active = state !== null && ACTIVE_STATES.indexOf(state) >= 0;
  const time = (typeof rawTime === 'number' && Number.isFinite(rawTime) && rawTime >= 0 && rawTime <= 3600) ? rawTime : 0;
  if (!active) {
    if (lastActive !== false) send({ type: 'clock', active: false, time: 0, aiStates: {} });
    lastActive = false;
    lastTime = null;
    return;
  }
  // Send at the original hook's 10 Hz polling rate. The overlay contract remains unchanged.
  send({ type: 'clock', active: true, time: time, aiStates: {} });
  lastActive = true;
  lastTime = time;
}

function resolveHooks() {
  managerClass = findClass('Gallop', 'RaceManager');
  replayBaseClass = findClass('Gallop', 'RaceManagerReplayBase');
  raceInfoClass = findClass('Gallop', 'RaceInfo');

  if (!managerClass) throw new Error('IL2CPP class Gallop.RaceManager was not found.');
  if (!replayBaseClass) throw new Error('IL2CPP class Gallop.RaceManagerReplayBase was not found.');
  if (!raceInfoClass) throw new Error('IL2CPP class Gallop.RaceInfo was not found.');

  fields.rmInstance = findField(managerClass, ['_instance']);
  fields.rmTime = findField(managerClass, ['<AccumulateTimeSinceStart>k__BackingField']);
  fields.fsm = findField(replayBaseClass, ['_fsm']);
  fields.riReplay = findField(raceInfoClass, ['<SimDataBase64>k__BackingField']);
  fields.riHorses = findField(raceInfoClass, ['<RaceHorse>k__BackingField']);
  fields.riCourseSet = findField(raceInfoClass, ['<RaceCourseSet>k__BackingField']);

  const missing = [];
  for (const [key, label] of [
    ['rmInstance', 'RaceManager._instance'],
    ['rmTime', 'RaceManager.AccumulateTimeSinceStart'],
    ['fsm', 'RaceManagerReplayBase._fsm'],
    ['riReplay', 'RaceInfo.SimDataBase64'],
    ['riHorses', 'RaceInfo.RaceHorse'],
  ]) if (!fields[key]) missing.push(label);

  say(missing.length ? 'warn' : 'info',
    'Resolved original hook fields: ' + Object.keys(fields).filter(k => fields[k]).join(', '),
    { missing: missing });

  let setupFn = findMethod(raceInfoClass, 'SetupSimulateData', 1);
  if (!setupFn) setupFn = findMethod(raceInfoClass, 'SetupSimulateData', 0);
  if (setupFn) {
    if (setupHook) { safe(() => setupHook.detach()); setupHook = null; }
    setupHook = Interceptor.attach(setupFn, {
      onEnter: function (args) { this.raceInfo = args[0]; },
      onLeave: function () { safe(() => sendRace(this.raceInfo)); }
    });
    say('info', 'Hooked Gallop.RaceInfo::SetupSimulateData at ' + setupFn);
  } else {
    say('warn', 'Could not find Gallop.RaceInfo::SetupSimulateData overload with 0 or 1 parameters; race replay capture is disabled.');
  }
}

function boot() {
  bootAttempts++;
  if (!ga) {
    ga = Process.findModuleByName(MODULE_NAME);
    if (!ga) {
      if (bootAttempts === 10) warnOnce('module-not-visible', 'Frida has not found GameAssembly.dll in this process yet; this can indicate that Linux Frida cannot enumerate Wine-mapped PE modules.');
      return false;
    }
    say('info', 'Found ' + ga.name + ' at ' + ga.base + ' (size ' + ga.size + ')');
  }
  if (!api) api = bindApi(ga);
  domain = api.domain_get();
  if (!valid(domain)) {
    if (bootAttempts === 10) warnOnce('domain-not-ready', 'GameAssembly.dll is visible, but IL2CPP domain is not initialized yet.');
    return false;
  }
  if (api.thread_attach) safe(() => api.thread_attach(domain));
  images = enumerateImages();
  if (!images.length) {
    if (bootAttempts === 10) warnOnce('images-not-ready', 'IL2CPP domain exists, but no loaded assemblies could be enumerated yet.');
    return false;
  }

  say('info', 'IL2CPP ready; loaded ' + images.length + ' assemblies/images.');
  resolveHooks();
  clearInterval(bootTimer);
  bootTimer = null;
  setInterval(() => safe(emitClock), POLL_MS);
  return true;
}

bootTimer = setInterval(() => {
  try { boot(); }
  catch (e) {
    warnOnce('boot-error-' + String(e), 'Hook initialization error: ' + String(e));
  }
}, 500);
say('info', 'Native race hook loaded; waiting for GameAssembly.dll and IL2CPP.');
