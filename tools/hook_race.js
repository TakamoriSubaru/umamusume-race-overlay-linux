'use strict';
/*
 * tools/hook_race.js - Frida script (Frida 16 and 17, no frida-il2cpp-bridge needed).
 *
 * Talks to GameAssembly.dll through the IL2CPP C API (il2cpp_* exports), so every class, method and field is
 * found BY NAME at run time. No offsets are hard coded.
 *
 * Messages sent to Python (send()):
 *   {type:"status", level:"info|warn|error", text, ...}      progress / problems (see also rpc status())
 *   {type:"race",  replay, compressed, runners[], courseId, courseInfo, courseShape, courseData, rmap}
 *   {type:"clock", active, time, aiStates}                    same schema as the Race Overlay server
 *   {type:"horses", time, horses:[{i, frameOrder, distance, lane, speed, hp, state}]}   extra, for debugging
 *
 * RPC (python: script.exports_sync.<name>(...)):
 *   status()                         what resolved and what did not
 *   discover(clsRegex, methodRegex, withFields)   list classes / methods / fields  (find the real names)
 *   trace(clsRegex, seconds)         count calls of every matching method (find the per-frame method and the
 *                                    method that receives the big scenario string / byte[])
 *   configure(patch)                 change CFG at run time (deep merge) and re-hook, no restart needed
 *
 * PYTHON SIDE (MemoryHookThread.on_message), what the overlay needs from each message:
 *   race : if not m["compressed"]: m["replay"] = base64.b64encode(gzip.compress(base64.b64decode(m["replay"]))).decode()
 *          rmap = {int(k): v for k, v in m.pop("rmap").items()}     # JSON turns the int keys into strings
 *          self.race.emit(m, rmap)
 *   clock: self.clock.emit(m)          status: log it          horses: optional, not used by the overlay
 *
 * IMPORTANT: the class / method / field NAMES in CFG below are best guesses (candidate lists). Run
 * discover() / trace() once on your game build and put the real names into CFG (or call configure()).
 */

const CFG = {
  module: 'GameAssembly.dll',
  pollMs: 500,          // how often to look for the module / a ready IL2CPP runtime
  clockHz: 30,          // max "clock" messages per second
  horsesHz: 5,          // max "horses" messages per second (0 = never)
  stallMs: 1200,        // no tick for this long = race is over  ->  clock active:false

  // Method that runs every frame while a race is on screen. `this` (args[0]) is the race object.
  tick: {
    classes: ['Gallop.RaceManager', 'Gallop.RaceViewBase'],
    method: 'Update',
    argc: 0,
    time:   ['_currentTime', 'CurrentTime', '<CurrentTime>k__BackingField', '_raceTime', '_time', '_elapsedTime'],
    horses: ['_horseInfos', '_horseRaceInfos', '_horseArray', '_horses', '<HorseInfos>k__BackingField'],
    courseDistance: ['_courseDistance', 'CourseDistance', '<CourseDistance>k__BackingField'],
    raceId: ['<RaceId>k__BackingField', '_raceId', 'RaceId'],
  },

  // Fields of one horse (element type of the horses array / List). First name that exists wins.
  horse: {
    frameOrder: ['_frameOrder', 'FrameOrder', '<FrameOrder>k__BackingField', '_horseIndex'],
    distance:   ['_distance', 'Distance', '<Distance>k__BackingField', '_currentDistance'],
    lane:       ['_lanePosition', 'LanePosition', '<LanePosition>k__BackingField', '_lane'],
    speed:      ['_speed', 'Speed', '<Speed>k__BackingField', '_currentSpeed'],
    hp:         ['_hp', 'Hp', 'HP', '<Hp>k__BackingField'],
    state:      ['_aiState', 'AiState', '_state', 'TemptationMode'],
    name:       ['_charaName', 'CharaName', '_name'],
    trainer:    ['_trainerName', 'TrainerName', '<TrainerName>k__BackingField'],
    charaId:    ['_charaId', 'CharaId', '<CharaId>k__BackingField'],
    dressId:    ['_raceDressId', '_dressId', 'DressId'],
    style:      ['_runningStyle', 'RunningStyle', '_style'],
    gate:       ['_postNumber', 'PostNumber', '_gateNo', '_gate'],
  },

  // Method that receives the race scenario (the replay). Disabled until you know it, example:
  //   scenario: { classes: ['Gallop.SomeClass'], method: 'SomeMethod', argc: 2, arg: 0, kind: 'string' }
  //   arg  = index of the parameter (0 = first declared parameter, `this` is not counted)
  //   kind = 'string' (base64 text of the gzip data, what the server sends) or 'bytes' (byte[])
  scenario: null,
};

// ------------------------------------------------------------------------------------------------------------
// small helpers
// ------------------------------------------------------------------------------------------------------------
const NULLP = ptr(0);
const HDR = 0x10;                       // Il2CppObject header: klass + monitor
const warned = new Set();
const REPORT = { module: null, ready: false, resolved: {}, missing: [], errors: 0 };

function say(level, text, extra) {
  const m = Object.assign({ type: 'status', level: level, text: text }, extra || {});
  send(m);
}
function warnOnce(key, text, extra) {
  if (warned.has(key)) return;
  warned.add(key);
  say('warn', text, extra);
}
function clone(o) { return JSON.parse(JSON.stringify(o)); }
function deepMerge(dst, src) {
  for (const k of Object.keys(src)) {
    const v = src[k];
    if (v && typeof v === 'object' && !Array.isArray(v) && dst[k] && typeof dst[k] === 'object' && !Array.isArray(dst[k])) deepMerge(dst[k], v);
    else dst[k] = v;
  }
  return dst;
}

const cstrCache = new Map();            // keeps the allocations alive while native code may still use them
function cstr(s) {
  let p = cstrCache.get(s);
  if (!p) { p = Memory.allocUtf8String(s); cstrCache.set(s, p); }
  return p;
}

// a pointer we are willing to dereference: not null, in user space and inside a mapped range
const LOW = ptr('0x10000'), HIGH = ptr('0x7fffffffffff');
function okPtr(p) {
  try {
    if (p === null || p === undefined || p.isNull()) return false;
    if (p.compare(LOW) < 0 || p.compare(HIGH) > 0) return false;
    return Process.findRangeByAddress(p) !== null;
  } catch (e) { return false; }
}

// ------------------------------------------------------------------------------------------------------------
// IL2CPP C API
// ------------------------------------------------------------------------------------------------------------
const SIG = {   // name -> [return type, [argument types], required]
  domain_get:                 ['pointer', [], true],
  thread_attach:              ['pointer', ['pointer'], false],
  domain_get_assemblies:      ['pointer', ['pointer', 'pointer'], true],
  assembly_get_image:         ['pointer', ['pointer'], true],
  image_get_name:             ['pointer', ['pointer'], false],
  image_get_class_count:      ['uint32', ['pointer'], false],
  image_get_class:            ['pointer', ['pointer', 'uint32'], false],
  class_from_name:            ['pointer', ['pointer', 'pointer', 'pointer'], true],
  class_get_name:             ['pointer', ['pointer'], true],
  class_get_namespace:        ['pointer', ['pointer'], false],
  class_get_parent:           ['pointer', ['pointer'], false],
  class_get_methods:          ['pointer', ['pointer', 'pointer'], true],
  class_get_method_from_name: ['pointer', ['pointer', 'pointer', 'int'], true],
  class_get_fields:           ['pointer', ['pointer', 'pointer'], false],
  class_get_field_from_name:  ['pointer', ['pointer', 'pointer'], true],
  class_from_type:            ['pointer', ['pointer'], false],
  class_is_valuetype:         ['bool', ['pointer'], true],
  class_is_enum:              ['bool', ['pointer'], false],
  class_enum_basetype:        ['pointer', ['pointer'], false],
  class_get_element_class:    ['pointer', ['pointer'], true],
  class_array_element_size:   ['int', ['pointer'], true],
  method_get_name:            ['pointer', ['pointer'], true],
  method_get_param_count:     ['uint32', ['pointer'], true],
  method_get_param:           ['pointer', ['pointer', 'uint32'], false],
  method_get_param_name:      ['pointer', ['pointer', 'uint32'], false],
  method_get_return_type:     ['pointer', ['pointer'], false],
  method_get_flags:           ['uint32', ['pointer', 'pointer'], true],
  field_get_name:             ['pointer', ['pointer'], true],
  field_get_offset:           ['int', ['pointer'], true],
  field_get_type:             ['pointer', ['pointer'], true],
  type_get_type:              ['int', ['pointer'], true],
  type_get_name:              ['pointer', ['pointer'], false],
};
let api = null;
let gaModule = null;
let domain = NULLP;
let imageList = null;

function bindApi(mod) {
  const a = {}, missing = [];
  for (const name of Object.keys(SIG)) {
    const addr = mod.findExportByName('il2cpp_' + name);
    if (addr === null || addr.isNull()) { if (SIG[name][2]) missing.push('il2cpp_' + name); continue; }
    a[name] = new NativeFunction(addr, SIG[name][0], SIG[name][1]);
  }
  return { a: a, missing: missing };
}

function images() {
  if (imageList) return imageList;
  const sizeBuf = Memory.alloc(8);
  sizeBuf.writeU64(0);
  const asms = api.domain_get_assemblies(domain, sizeBuf);
  const n = sizeBuf.readU32();
  const out = [];
  for (let i = 0; i < n; i++) {
    const img = api.assembly_get_image(asms.add(i * Process.pointerSize).readPointer());
    if (!img.isNull()) out.push(img);
  }
  imageList = out;
  return out;
}

function classFullName(k) {
  const nm = api.class_get_name(k).readUtf8String();
  const ns = api.class_get_namespace ? api.class_get_namespace(k).readUtf8String() : '';
  return ns ? ns + '.' + nm : nm;
}

function findClass(full) {
  const i = full.lastIndexOf('.');
  const ns = i < 0 ? '' : full.slice(0, i), nm = i < 0 ? full : full.slice(i + 1);
  for (const img of images()) {
    const k = api.class_from_name(img, cstr(ns), cstr(nm));
    if (!k.isNull()) return k;
  }
  return null;
}

function typeName(t) {
  try { return (api.type_get_name && !t.isNull()) ? api.type_get_name(t).readUtf8String() : '?'; } catch (e) { return '?'; }
}

function methodSig(m) {
  const argc = api.method_get_param_count(m);
  const ps = [];
  for (let i = 0; i < argc; i++) {
    const t = api.method_get_param ? typeName(api.method_get_param(m, i)) : '?';
    const n = api.method_get_param_name ? api.method_get_param_name(m, i).readUtf8String() : 'a' + i;
    ps.push(t + ' ' + n);
  }
  const ret = api.method_get_return_type ? typeName(api.method_get_return_type(m)) : '?';
  const stat = (api.method_get_flags(m, NULLP) & 0x10) !== 0;
  return (stat ? 'static ' : '') + ret + ' ' + api.method_get_name(m).readUtf8String() + '(' + ps.join(', ') + ')';
}

function eachMethod(k, cb) {
  const it = Memory.alloc(Process.pointerSize);
  it.writePointer(NULLP);
  for (let guard = 0; guard < 4096; guard++) {
    const m = api.class_get_methods(k, it);
    if (m.isNull()) break;
    cb(m);
  }
}
function eachField(k, cb) {
  if (!api.class_get_fields) return;
  const it = Memory.alloc(Process.pointerSize);
  it.writePointer(NULLP);
  for (let guard = 0; guard < 4096; guard++) {
    const f = api.class_get_fields(k, it);
    if (f.isNull()) break;
    cb(f);
  }
}

// ------------------------------------------------------------------------------------------------------------
// reading managed memory
// ------------------------------------------------------------------------------------------------------------
function fieldInfo(f) {
  const t = api.field_get_type(f);
  return { name: api.field_get_name(f).readUtf8String(), offset: api.field_get_offset(f), te: api.type_get_type(t), type: t };
}

function findField(klass, names) {
  for (const n of names) {
    for (let k = klass, d = 0; k && !k.isNull() && d < 16; d++) {
      const f = api.class_get_field_from_name(k, cstr(n));
      if (!f.isNull()) return fieldInfo(f);
      if (!api.class_get_parent) break;
      k = api.class_get_parent(k);
    }
  }
  return null;
}

function readStr(p, max) {
  if (!okPtr(p)) return null;
  const len = p.add(HDR).readS32();
  if (len < 0 || len > (max || 4096)) return null;
  return len === 0 ? '' : p.add(HDR + 4).readUtf16String(len);
}

// read the value of one field at `addr` (the address of the field itself)
function readAt(addr, te, type) {
  switch (te) {
    case 0x02: return addr.readU8() !== 0;
    case 0x03: return addr.readU16();
    case 0x04: return addr.readS8();
    case 0x05: return addr.readU8();
    case 0x06: return addr.readS16();
    case 0x07: return addr.readU16();
    case 0x08: return addr.readS32();
    case 0x09: return addr.readU32();
    case 0x0a: return Number(addr.readS64());
    case 0x0b: return Number(addr.readU64());
    case 0x0c: return addr.readFloat();
    case 0x0d: return addr.readDouble();
    case 0x0e: return readStr(addr.readPointer());
    case 0x11: {                                   // value type: only enums are supported (read as their base type)
      if (!api.class_from_type || !api.class_is_enum || !api.class_enum_basetype) return null;
      const kl = api.class_from_type(type);
      if (!api.class_is_enum(kl)) return null;
      const bt = api.class_enum_basetype(kl);
      return readAt(addr, api.type_get_type(bt), bt);
    }
    default: return addr.readPointer();           // class, szarray, generic instance, ...
  }
}

function readField(obj, fi) {                      // obj = managed object pointer
  return readAt(obj.add(fi.offset), fi.te, fi.type);
}

// An array or List<T> field. Everything about its layout comes from the METADATA, once, when the hooks are set
// up (buildSeqInfo). While the game runs, readSeq() only compares class pointers and reads memory: it never calls
// into il2cpp with a pointer that came out of game memory, because a stale pointer would crash the game and a
// JavaScript try/catch cannot stop that.
function buildSeqInfo(fi) {
  if (!api.class_from_type || !api.class_get_element_class) return null;
  const k = api.class_from_type(fi.type);
  if (k.isNull()) return null;
  const si = { klass: k, list: false, itemsOff: 0, sizeOff: 0, arrKlass: k, name: classFullName(k) };
  if (api.class_get_name(k).readUtf8String().indexOf('List`1') === 0) {
    const items = findField(k, ['_items']), size = findField(k, ['_size']);
    if (!items || !size) return null;
    si.list = true; si.itemsOff = items.offset; si.sizeOff = size.offset;
    si.arrKlass = api.class_from_type(items.type);
  } else if (fi.te !== 0x1d) {
    return null;                                          // neither an array nor a List
  }
  const ec = api.class_get_element_class(si.arrKlass);
  if (ec.isNull()) return null;
  si.isVal = api.class_is_valuetype(ec);
  si.stride = si.isVal ? api.class_array_element_size(si.arrKlass) : Process.pointerSize;
  si.hf = horseFields(ec);
  si.elemName = classFullName(ec);
  return si;
}

function readSeq(p, si) {                                  // -> {n, data} or null. Memory reads only.
  if (!okPtr(p)) return null;
  const k = p.readPointer();
  if (!k.equals(si.klass)) { warnOnce('seqklass', 'horses object is not a ' + si.name + ' (class ' + k + ' != ' + si.klass + '): not initialised yet?'); return null; }
  let arr = p, n;
  if (si.list) {
    n = p.add(si.sizeOff).readS32();
    arr = p.add(si.itemsOff).readPointer();
    if (!okPtr(arr) || !arr.readPointer().equals(si.arrKlass)) return null;
  } else {
    n = Number(p.add(0x18).readU64());                    // Il2CppArray::max_length
  }
  if (n < 0 || n > 64) return null;
  return { n: n, data: arr.add(0x20) };
}

// address the field offsets of element i are relative to (null if the element is not readable)
function elementBase(sq, si, i) {
  if (si.isVal) return sq.data.add(i * si.stride).sub(HDR);      // inline struct: offsets include the object header
  const o = sq.data.add(i * si.stride).readPointer();
  return okPtr(o) ? o : null;
}

const horseFieldCache = new Map();
function horseFields(ec) {   // metadata only: ec comes from a field type
  const key = ec.toString();
  let hf = horseFieldCache.get(key);
  if (hf) return hf;
  hf = {};
  const miss = [];
  for (const logical of Object.keys(CFG.horse)) {
    hf[logical] = findField(ec, CFG.horse[logical]);
    if (!hf[logical]) miss.push(logical);
  }
  horseFieldCache.set(key, hf);
  say('info', 'horse class ' + classFullName(ec) + ': fields resolved = ' +
      Object.keys(hf).filter(function (x) { return hf[x]; }).map(function (x) { return x + '=' + hf[x].name; }).join(', '),
      { missing: miss });
  return hf;
}

function num(v) { return (typeof v === 'number' && isFinite(v)) ? v : null; }

// ------------------------------------------------------------------------------------------------------------
// base64 (Frida has no btoa)
// ------------------------------------------------------------------------------------------------------------
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
function b64(bytes) {
  const out = [];
  const n = bytes.length;
  for (let i = 0; i < n; i += 3) {
    const a = bytes[i], b = i + 1 < n ? bytes[i + 1] : 0, c = i + 2 < n ? bytes[i + 2] : 0;
    out.push(B64[a >> 2], B64[((a & 3) << 4) | (b >> 4)],
             i + 1 < n ? B64[((b & 15) << 2) | (c >> 6)] : '=', i + 2 < n ? B64[c & 63] : '=');
  }
  return out.join('');
}
function hashBytes(u8) {                           // FNV-1a, to not send the same scenario twice
  let h = 0x811c9dc5;
  for (let i = 0; i < u8.length; i++) { h ^= u8[i]; h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16) + ':' + u8.length;
}
function hashStr(s) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16) + ':' + s.length;
}

// ------------------------------------------------------------------------------------------------------------
// race state
// ------------------------------------------------------------------------------------------------------------
let tickInfo = null;            // resolved tick method + fields
let listeners = [];             // Interceptor listeners we own
let active = false;
let lastTime = null;
let lastTickAt = 0;
let lastClockAt = 0;
let lastClockTime = -1;
let lastHorsesAt = 0;
let aiStates = {};
let pendingRace = null;         // scenario seen, waiting for the runners to be readable
let pendingSince = 0;
let sentScenarioKey = null;
let errCount = 0;

function guard(where, fn) {
  try { return fn(); } catch (e) {
    errCount++; REPORT.errors = errCount;
    if (errCount <= 20) say('error', where + ': ' + (e && e.message ? e.message : e));
    return undefined;
  }
}

function readHorses(self) {
  if (!tickInfo || !tickInfo.horsesField || !tickInfo.seq) return null;
  const si = tickInfo.seq;
  const sq = readSeq(self.add(tickInfo.horsesField.offset).readPointer(), si);
  if (!sq || sq.n === 0) return null;
  const hf = si.hf;
  const out = [];
  for (let i = 0; i < sq.n; i++) {
    const base = elementBase(sq, si, i);
    if (base === null) continue;
    const h = { i: i };
    for (const key of Object.keys(hf)) {
      const fi = hf[key];
      if (!fi) continue;
      try { h[key] = readAt(base.add(fi.offset), fi.te, fi.type); } catch (e) { h[key] = null; }
    }
    out.push(h);
  }
  return out;
}

function buildRunners(horses) {
  const runners = [], rmap = {};
  for (const h of horses) {
    const fo = num(h.frameOrder) !== null ? h.frameOrder : (num(h.gate) !== null ? h.gate : h.i + 1);
    runners.push({
      name: h.name || '', trainer: h.trainer || '', style: num(h.style) !== null ? h.style : 2,
      gate: num(h.gate) !== null ? h.gate : fo, frameOrder: fo,
      charaId: num(h.charaId) !== null ? h.charaId : 0, dressId: num(h.dressId) !== null ? h.dressId : 0,
    });
    rmap[fo] = { fo: fo, chara_id: num(h.charaId) !== null ? h.charaId : 0,
                 card_id: (num(h.charaId) ? h.charaId * 100 + 1 : 0), finishOrder: 0, finishTimeRaw: 0 };
  }
  return { runners: runners, rmap: rmap };
}

function flushRace(self) {
  if (!pendingRace) return;
  let horses = null;
  try { horses = readHorses(self); } catch (e) { horses = null; }
  const waited = Date.now() - pendingSince;
  if ((!horses || horses.length === 0) && waited < 4000) return;          // give the game time to fill the horses in
  const built = horses && horses.length ? buildRunners(horses) : { runners: [], rmap: {} };
  if (!built.runners.length) warnOnce('norunners', 'race scenario seen but no runners could be read (horse fields not resolved?): the overlay will show nothing');
  let dist = 0, courseId = 0;
  try {
    if (tickInfo.distField) dist = num(readField(self, tickInfo.distField)) || 0;
    if (tickInfo.raceIdField) courseId = num(readField(self, tickInfo.raceIdField)) || 0;
  } catch (e) { /* optional */ }
  send({
    type: 'race', replay: pendingRace.replay, compressed: pendingRace.compressed,
    runners: built.runners, rmap: built.rmap, courseId: courseId, courseInfo: {},
    courseShape: { distance: dist }, courseData: { distance: dist },
  });
  pendingRace = null;
}

function sendClock(t, isActive) {
  lastClockAt = Date.now();
  lastClockTime = t;
  send({ type: 'clock', active: isActive, time: isActive ? t : 0, aiStates: aiStates });
}

function raceEnded(why) {
  if (!active) return;
  active = false;
  lastTime = null;
  sendClock(0, false);
  say('info', 'race ended (' + why + ')');
}

function onTick(self) {
  const now = Date.now();
  lastTickAt = now;
  if (!tickInfo || !tickInfo.timeField) return;
  if (!okPtr(self)) return;                                   // loading / unloading: `this` is not a live object
  const t = num(readField(self, tickInfo.timeField));
  if (t === null || t < 0 || t > 3600) return;                // uninitialised field
  if (lastTime !== null && t < lastTime - 0.25) raceEnded('time went backwards = next race');
  lastTime = t;

  if (pendingRace) flushRace(self);

  const wantHorses = CFG.horsesHz > 0 && now - lastHorsesAt >= 1000 / CFG.horsesHz;
  if (wantHorses) {
    lastHorsesAt = now;
    const hs = readHorses(self);
    if (hs) {
      const st = {};
      for (const h of hs) if (num(h.state) !== null) st[num(h.frameOrder) !== null ? h.frameOrder : h.i + 1] = h.state;
      aiStates = st;
      send({ type: 'horses', time: t, horses: hs });
    }
  }

  if (!active) { active = true; say('info', 'race clock started at ' + t.toFixed(2) + 's'); sendClock(t, true); return; }
  if (now - lastClockAt >= 1000 / CFG.clockHz && Math.abs(t - lastClockTime) > 1e-4) sendClock(t, true);
}

// ------------------------------------------------------------------------------------------------------------
// scenario (replay) capture
// ------------------------------------------------------------------------------------------------------------
function onScenario(args, sc) {
  const a = args[sc.argIndex];
  if (!okPtr(a)) return;
  let replay = null, compressed = true;
  if (sc.kind === 'string') {
    const s = readStr(a, 64 * 1024 * 1024);
    if (!s || s.length < 64) return;
    const key = hashStr(s);
    if (key === sentScenarioKey) return;
    sentScenarioKey = key;
    replay = s.replace(/\n/g, '');
    compressed = replay.indexOf('H4sI') === 0;                // base64 of a gzip stream
  } else {
    const len = Number(a.add(0x18).readU64());
    if (len < 64 || len > 64 * 1024 * 1024) return;
    const u8 = new Uint8Array(a.add(0x20).readByteArray(len));
    const key = hashBytes(u8);
    if (key === sentScenarioKey) return;
    sentScenarioKey = key;
    compressed = u8[0] === 0x1f && u8[1] === 0x8b;
    replay = b64(u8);
  }
  pendingRace = { replay: replay, compressed: compressed };
  pendingSince = Date.now();
  say('info', 'scenario captured: ' + replay.length + ' base64 chars, gzip=' + compressed);
}

// ------------------------------------------------------------------------------------------------------------
// resolving + hooking
// ------------------------------------------------------------------------------------------------------------
function resolveMethod(classNames, mname, argc) {
  for (const cn of classNames) {
    const k = findClass(cn);
    if (!k) continue;
    const m = api.class_get_method_from_name(k, cstr(mname), argc);
    if (m.isNull()) continue;
    const fn = m.readPointer();                               // MethodInfo::methodPointer is the first field
    if (!okPtr(fn)) continue;
    return { klass: k, method: m, fn: fn, cls: cn, isStatic: (api.method_get_flags(m, NULLP) & 0x10) !== 0 };
  }
  return null;
}

function unhookAll() {
  for (const l of listeners) { try { l.detach(); } catch (e) { /* ignore */ } }
  listeners = [];
}

function hookAll() {
  unhookAll();
  tickInfo = null;
  REPORT.resolved = {};
  REPORT.missing = [];

  const t = CFG.tick;
  const rm = resolveMethod(t.classes, t.method, t.argc);
  if (!rm) {
    REPORT.missing.push('tick method ' + t.classes.join('|') + '::' + t.method + '/' + t.argc);
  } else {
    const timeF = findField(rm.klass, t.time);
    const horsesF = findField(rm.klass, t.horses);
    tickInfo = {
      rm: rm, timeField: timeF, horsesField: horsesF,
      distField: findField(rm.klass, t.courseDistance), raceIdField: findField(rm.klass, t.raceId),
    };
    REPORT.resolved.tick = rm.cls + '::' + t.method + ' @' + rm.fn;
    REPORT.resolved.time = timeF ? timeF.name : null;
    REPORT.resolved.horses = horsesF ? horsesF.name : null;
    if (!timeF) REPORT.missing.push('time field, tried ' + t.time.join(', '));
    if (!horsesF) REPORT.missing.push('horses field, tried ' + t.horses.join(', '));
    if (horsesF) {
      tickInfo.seq = buildSeqInfo(horsesF);
      if (tickInfo.seq) REPORT.resolved.horseElement = tickInfo.seq.elemName + (tickInfo.seq.isVal ? ' (struct)' : '');
      else REPORT.missing.push('horses field ' + horsesF.name + ' is not an array or List<T>');
    }
    if (rm.isStatic) { REPORT.missing.push('tick method is static: it has no `this` to read the fields from'); }
    else if (timeF) {
      listeners.push(Interceptor.attach(rm.fn, { onEnter: function (args) { guard('tick', function () { onTick(args[0]); }); } }));
    }
  }

  const sc = CFG.scenario;
  if (sc) {
    const sm = resolveMethod(sc.classes, sc.method, sc.argc);
    if (!sm) REPORT.missing.push('scenario method ' + sc.classes.join('|') + '::' + sc.method + '/' + sc.argc);
    else {
      const cfg = { kind: sc.kind, argIndex: (sc.arg || 0) + (sm.isStatic ? 0 : 1) };
      listeners.push(Interceptor.attach(sm.fn, { onEnter: function (args) { guard('scenario', function () { onScenario(args, cfg); }); } }));
      REPORT.resolved.scenario = sm.cls + '::' + sc.method + ' @' + sm.fn;
    }
  } else {
    REPORT.missing.push('scenario: not configured (no `race` message will be sent until you set CFG.scenario)');
  }

  REPORT.ready = true;
  say(REPORT.missing.length ? 'warn' : 'info', 'hooks: ' + JSON.stringify(REPORT.resolved), { missing: REPORT.missing });
}

// ------------------------------------------------------------------------------------------------------------
// waiting for the game
// ------------------------------------------------------------------------------------------------------------
let bootTimer = null;
function tryBoot() {
  if (!gaModule) {
    gaModule = Process.findModuleByName(CFG.module);
    if (!gaModule) return false;
    try { Module.ensureInitialized(CFG.module); } catch (e) { /* not needed on every Frida version */ }
    REPORT.module = gaModule.name + ' @' + gaModule.base + ' size ' + gaModule.size;
    say('info', 'found ' + REPORT.module);
  }
  if (!api) {
    const b = bindApi(gaModule);
    if (b.missing.length) {
      warnOnce('noexports', 'il2cpp exports missing in ' + CFG.module + ': ' + b.missing.join(', ') +
               ' (still loading, or the game hides its exports)');
      return false;
    }
    api = b.a;
  }
  domain = api.domain_get();
  if (domain.isNull()) return false;                          // IL2CPP runtime not initialised yet
  if (api.thread_attach) api.thread_attach(domain);           // this (Frida) thread may now call the il2cpp api
  imageList = null;
  if (images().length === 0) return false;
  return true;
}

function boot() {
  if (bootTimer !== null) clearInterval(bootTimer);
  bootTimer = setInterval(function () {
    let ok = false;
    try { ok = tryBoot(); } catch (e) { ok = false; }
    if (!ok) return;
    clearInterval(bootTimer);
    bootTimer = null;
    say('info', 'il2cpp ready: ' + images().length + ' images');
    guard('hookAll', hookAll);
  }, CFG.pollMs);
}

// no ticks for a while: the race is over (or the game left the race scene)
setInterval(function () {
  if (active && Date.now() - lastTickAt > CFG.stallMs) raceEnded('no more updates');
}, 300);

// ------------------------------------------------------------------------------------------------------------
// RPC
// ------------------------------------------------------------------------------------------------------------
function needApi() { if (!api || !REPORT.ready) throw new Error('il2cpp not ready yet: ' + JSON.stringify(REPORT)); }

function matchClasses(clsRe, cap) {
  const re = new RegExp(clsRe || '.', 'i');
  const out = [];
  for (const img of images()) {
    const cnt = api.image_get_class_count ? api.image_get_class_count(img) : 0;
    for (let i = 0; i < cnt && out.length < cap; i++) {
      const k = api.image_get_class(img, i);
      if (k.isNull()) continue;
      let name;
      try { name = classFullName(k); } catch (e) { continue; }
      if (re.test(name)) out.push({ k: k, name: name });
    }
  }
  return out;
}

rpc.exports = {
  status: function () { return clone(REPORT); },

  configure: function (patch) {
    deepMerge(CFG, patch || {});
    horseFieldCache.clear();
    pendingRace = null;
    sentScenarioKey = null;
    if (api && REPORT.ready) guard('hookAll', hookAll);
    return clone(REPORT);
  },

  discover: function (clsRegex, methodRegex, withFields) {
    needApi();
    const mre = methodRegex ? new RegExp(methodRegex, 'i') : null;
    const out = [];
    for (const c of matchClasses(clsRegex, 150)) {
      const e = { cls: c.name, methods: [], fields: [] };
      eachMethod(c.k, function (m) {
        const s = methodSig(m);
        if (!mre || mre.test(s)) e.methods.push(s);
      });
      if (withFields) eachField(c.k, function (f) {
        const fi = fieldInfo(f);
        e.fields.push(fi.name + ' : ' + typeName(fi.type) + ' @0x' + fi.offset.toString(16));
      });
      if (!mre || e.methods.length) out.push(e);
    }
    return out;
  },

  // Hooks every method of the matching classes for `seconds` and reports how often each was called and the
  // biggest string / byte[] argument it saw. The per-frame method is the one called ~60 times per second while
  // a race runs; the scenario method is the one that saw a string / byte[] of 10 000+ characters.
  trace: function (clsRegex, seconds) {
    needApi();
    const stats = new Map();
    const hooks = [];
    const seenFn = new Set();
    let hooked = 0;
    for (const c of matchClasses(clsRegex, 60)) {
      eachMethod(c.k, function (m) {
        if (hooked >= 400) return;
        const fn = m.readPointer();
        if (!okPtr(fn) || seenFn.has(fn.toString())) return;
        seenFn.add(fn.toString());
        const stat = (api.method_get_flags(m, NULLP) & 0x10) !== 0;
        const argc = api.method_get_param_count(m);
        const kinds = [];
        for (let i = 0; i < argc; i++) {
          const tn = api.method_get_param ? typeName(api.method_get_param(m, i)) : '';
          kinds.push(tn === 'System.String' ? 's' : (tn === 'System.Byte[]' ? 'b' : ''));
        }
        const rec = { sig: c.name + '::' + methodSig(m), calls: 0, maxStr: 0, maxBytes: 0 };
        stats.set(fn.toString(), rec);
        try {
          hooks.push(Interceptor.attach(fn, {
            onEnter: function (args) {
              rec.calls++;
              for (let i = 0; i < kinds.length; i++) {
                if (!kinds[i]) continue;
                try {
                  const a = args[i + (stat ? 0 : 1)];
                  if (!okPtr(a)) continue;
                  if (kinds[i] === 's') rec.maxStr = Math.max(rec.maxStr, a.add(HDR).readS32());
                  else rec.maxBytes = Math.max(rec.maxBytes, Number(a.add(0x18).readU64()));
                } catch (e) { /* ignore */ }
              }
            },
          }));
          hooked++;
        } catch (e) { /* some functions cannot be hooked */ }
      });
    }
    say('info', 'tracing ' + hooked + ' methods for ' + seconds + ' s - play / load a race now');
    return new Promise(function (resolve) {
      setTimeout(function () {
        for (const h of hooks) { try { h.detach(); } catch (e) { /* ignore */ } }
        const rows = Array.from(stats.values()).filter(function (r) { return r.calls > 0; });
        rows.sort(function (a, b) { return b.calls - a.calls; });
        resolve({ hooked: hooked, called: rows.length, top: rows.slice(0, 40), bigArguments: rows.filter(function (r) { return r.maxStr > 10000 || r.maxBytes > 10000; }) });
      }, Math.max(1, seconds) * 1000);
    });
  },
};

boot();
say('info', 'hook_race.js loaded, waiting for ' + CFG.module);