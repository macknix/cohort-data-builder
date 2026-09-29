/* Generates a download exactly as the site does, without a browser.

     node tests/generate_bundle.mjs <dataset> <out_dir> <true|false> <file:variable[:column]>...

   Reads the built site/data/, so run build.py first. Used by
   tests/test_generated_scripts.py. */

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "site");
const [key, outDir, na, ...picks] = process.argv.slice(2);
const read = async (p) => JSON.parse(await readFile(join(root, "data", p), "utf-8"));

const { state } = await import(join(root, "js", "state.js"));
const { build } = await import(join(root, "js", "codegen.js"));

state.manifest = await read(`${key}/manifest.json`);
const bundle = [];
for (const pick of picks) {
  const [file, name, column] = pick.split(":");
  const dict = await read(`${key}/dict/${file}.json`);
  state.dictCache.set(`${key}/${file}`, dict);
  const v = dict.variables.find((x) => x.variable === name);
  if (!v) throw new Error(`${file} has no ${name}`);
  bundle.push({ name, label: v.label || "", file, wave: dict.wave, column: column || name });
}

const templates = await read("templates.json");
const { files } = await build(bundle, state.manifest, templates,
  { languages: ["r", "python"], missingToNa: na === "true" });

for (const [path, text] of files) {
  const target = join(outDir, path.split("/").slice(1).join("/"));
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, text);
}
console.log(files.map(([p]) => p).join("\n"));
