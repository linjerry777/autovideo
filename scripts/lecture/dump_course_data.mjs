// Dump ai_lesson's course-data.ts to JSON.
// Usage: node --import tsx scripts/lecture/dump_course_data.mjs <path-to-course-data.ts> <out-json>
// We stub out the '@/app/dashboard/StepGuide' Step type import by writing a temp shim.

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { pathToFileURL } from 'node:url';

const [, , inPath, outPath] = process.argv;
if (!inPath || !outPath) {
  console.error('Usage: node --import tsx dump_course_data.mjs <course-data.ts> <out.json>');
  process.exit(1);
}

const absIn = path.resolve(inPath);
const src = fs.readFileSync(absIn, 'utf-8');

// Strip the import that references '@/app/dashboard/StepGuide'.
// course-data.ts only uses `Step` as a type — safe to remove the import line.
const stripped = src.replace(
  /^\s*import\s+type\s*\{\s*Step\s*\}\s*from\s+['"]@\/app\/dashboard\/StepGuide['"];?\s*$/m,
  '// (stub) Step type import removed for tsx eval'
);

// Write to a temp .ts file then import it.
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lecture-dump-'));
const tmpFile = path.join(tmpDir, 'course-data.ts');
fs.writeFileSync(tmpFile, stripped, 'utf-8');

const mod = await import(pathToFileURL(tmpFile).href);

const out = {
  course_title: mod.COURSE_TITLE ?? null,
  course_subtitle: mod.COURSE_SUBTITLE ?? null,
  lessons: mod.lessons ?? [],
};

fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(out, null, 2), 'utf-8');
console.log(`Wrote ${out.lessons.length} lessons → ${outPath}`);

// cleanup
try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch {}
