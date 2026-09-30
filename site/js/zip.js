/* Writing a zip file in the browser, so the download needs no server.

   The 1989 format — a local header per entry, a central directory and an end
   record — with no zip64 and no data descriptors, which a few dozen
   kilobytes of scripts cannot need. Deflated with the platform's
   CompressionStream where there is one, stored otherwise. */

const ZIP_VERSION = 20;         // 2.0: the floor for deflate
const UTF8_NAMES = 0x0800;      // filenames below are ASCII, but say so anyway
const STORED = 0;
const DEFLATED = 8;

/* ── A zip file, by hand ───────────────────────────────────────────────
   Small enough to be worth it: the alternative is a dependency, and this
   repository's Python has none by policy. The format is the 1989 one — local
   header per entry, central directory, end record — with no zip64 and no data
   descriptors, neither of which a few dozen kilobytes of R can need. */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/* MS-DOS packed date and time — two's the resolution, so seconds are halved.
   Zip has carried these since before the study's first sweep was archived. */
function dosStamp(d) {
  const time = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
  const date = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
  return { time: time & 0xffff, date: date & 0xffff };
}

/* Raw deflate via the platform, when it has it. Returns null rather than
   throwing, so an older browser gets a stored (uncompressed) archive that is
   larger and equally valid. */
async function deflate(bytes) {
  if (typeof CompressionStream !== "function") return null;
  try {
    const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate-raw"));
    const out = new Uint8Array(await new Response(stream).arrayBuffer());
    // Incompressible input can come back longer; store it instead.
    return out.length < bytes.length ? out : null;
  } catch {
    return null;
  }
}

function block(size) {
  const bytes = new Uint8Array(size);
  return { bytes, view: new DataView(bytes.buffer) };
}

export async function zip(entries, when = new Date()) {
  const encoder = new TextEncoder();
  const { time, date } = dosStamp(when);
  const chunks = [];
  const central = [];
  let offset = 0;

  for (const [path, text] of entries) {
    const name = encoder.encode(path);
    const data = encoder.encode(text);
    const packed = await deflate(data);
    const body = packed || data;
    const method = packed ? DEFLATED : STORED;
    const sum = crc32(data);

    const local = block(30);
    local.view.setUint32(0, 0x04034b50, true);
    local.view.setUint16(4, ZIP_VERSION, true);
    local.view.setUint16(6, UTF8_NAMES, true);
    local.view.setUint16(8, method, true);
    local.view.setUint16(10, time, true);
    local.view.setUint16(12, date, true);
    local.view.setUint32(14, sum, true);
    local.view.setUint32(18, body.length, true);
    local.view.setUint32(22, data.length, true);
    local.view.setUint16(26, name.length, true);
    chunks.push(local.bytes, name, body);

    const entry = block(46);
    entry.view.setUint32(0, 0x02014b50, true);
    entry.view.setUint16(4, ZIP_VERSION, true);
    entry.view.setUint16(6, ZIP_VERSION, true);
    entry.view.setUint16(8, UTF8_NAMES, true);
    entry.view.setUint16(10, method, true);
    entry.view.setUint16(12, time, true);
    entry.view.setUint16(14, date, true);
    entry.view.setUint32(16, sum, true);
    entry.view.setUint32(20, body.length, true);
    entry.view.setUint32(24, data.length, true);
    entry.view.setUint16(28, name.length, true);
    // Regular file, 0644. Left at zero, some unzips produce unreadable modes.
    entry.view.setUint32(38, ((0o100644 << 16) >>> 0), true);
    entry.view.setUint32(42, offset, true);
    central.push(entry.bytes, name);

    offset += local.bytes.length + name.length + body.length;
  }

  const size = central.reduce((n, c) => n + c.length, 0);
  const end = block(22);
  end.view.setUint32(0, 0x06054b50, true);
  end.view.setUint16(8, entries.length, true);
  end.view.setUint16(10, entries.length, true);
  end.view.setUint32(12, size, true);
  end.view.setUint32(16, offset, true);

  return new Blob([...chunks, ...central, end.bytes], { type: "application/zip" });
}
