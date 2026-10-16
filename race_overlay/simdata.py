"""Decoder for the race replay data (gzip + base64 binary)."""

import base64
import gzip
import struct



def parse_sim(b64):
    buf = gzip.decompress(base64.b64decode(b64))
    n = len(buf)

    def i32(o):
        return struct.unpack_from("<i", buf, o)[0]

    def f32(o):
        return struct.unpack_from("<f", buf, o)[0]

    def u16(o):
        return struct.unpack_from("<H", buf, o)[0]

    max_len = i32(0)
    if max_len < 4 or max_len > 2000:
        raise ValueError("Bad header %d" % max_len)
    o = 4 + max_len
    if o + 16 > n:
        raise ValueError("Truncated")
    horse_num = i32(o + 4)
    horse_frame_size = i32(o + 8)
    horse_res_size = i32(o + 12)
    o += 16
    if horse_num < 1 or horse_num > 24:
        raise ValueError("Bad horseNum")

    pad1 = i32(o)
    if pad1 < 0 or pad1 > 65536:
        raise ValueError("Bad pad1")
    o += 4 + pad1

    frame_count = i32(o)
    frame_size = i32(o + 4)
    o += 8

    times = []
    frames = []  # frames[k] = list of (dist, lane) per horse
    for _ in range(frame_count):
        if o + frame_size > n:
            break
        times.append(f32(o))
        hs = []
        h = o + 4
        for _j in range(horse_num):
            if h + 12 > n:
                break
            hs.append((f32(h), u16(h + 4)))
            h += horse_frame_size
        frames.append(hs)
        o += frame_size

    results = []
    try:
        pad2 = i32(o)
        if 0 <= pad2 < 65536:
            o += 4 + pad2
            r_size = horse_res_size if horse_res_size > 0 else 31
            for _i in range(horse_num):
                if o + 27 + 4 > n:
                    break
                results.append({
                    "finishOrder": i32(o),
                    "finishTime": f32(o + 4),
                    "finishDiffTime": f32(o + 8),
                    "finishTimeRaw": f32(o + 27),
                })
                o += r_size
    except Exception:
        pass

    return {"times": times, "frames": frames, "results": results, "horseNum": horse_num}
