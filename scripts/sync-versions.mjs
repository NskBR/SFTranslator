import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectDir = path.resolve(scriptDir, "..");
const checkOnly = process.argv.includes("--check");
let changed = false;
let failed = false;

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(projectDir, relativePath), "utf8"));
}

function writeJson(relativePath, value) {
  fs.writeFileSync(path.join(projectDir, relativePath), `${JSON.stringify(value, null, 2)}\n`);
}

function synchronizeJsonVersion(relativePath, version, selector = (value) => value.version) {
  const value = readJson(relativePath);
  if (selector(value) === version) return;
  if (checkOnly) {
    console.error(`${relativePath} está em ${selector(value)}, esperado ${version}.`);
    failed = true;
    return;
  }
  value.version = version;
  writeJson(relativePath, value);
  changed = true;
}

function synchronizeText(relativePath, pattern, replacement, description) {
  const filePath = path.join(projectDir, relativePath);
  const current = fs.readFileSync(filePath, "utf8");
  const next = current.replace(pattern, replacement);
  if (next === current) {
    if (!pattern.test(current)) {
      console.error(`${relativePath}: marcador de ${description} não encontrado.`);
      failed = true;
    }
    return;
  }
  if (checkOnly) {
    console.error(`${relativePath} não está sincronizado (${description}).`);
    failed = true;
    return;
  }
  fs.writeFileSync(filePath, next);
  changed = true;
}

const packageJson = readJson("package.json");
const appVersion = packageJson.version;

if (!/^\d+\.\d+\.\d+$/.test(appVersion)) {
  console.error("A versão do aplicativo deve usar SemVer estável (X.Y.Z).");
  process.exit(1);
}

synchronizeJsonVersion("src-tauri/tauri.conf.json", appVersion);
synchronizeJsonVersion("package-lock.json", appVersion);

const lock = readJson("package-lock.json");
if (lock.packages?.[""]?.version !== appVersion) {
  if (checkOnly) {
    console.error("package-lock.json: packages[\"\"].version não acompanha package.json.");
    failed = true;
  } else {
    lock.packages[""].version = appVersion;
    writeJson("package-lock.json", lock);
    changed = true;
  }
}

synchronizeText("src-tauri/Cargo.toml", /^version = "\d+\.\d+\.\d+"$/m, `version = "${appVersion}"`, "versão Rust");
synchronizeText("src-tauri/Cargo.lock", /(\[\[package\]\]\r?\nname = "uat-desktop"\r?\nversion = ")\d+\.\d+\.\d+("\r?\n)/, `$1${appVersion}$2`, "versão Rust no lockfile");

if (failed) process.exit(1);
console.log(checkOnly ? "Versões sincronizadas." : changed ? "Versões sincronizadas e arquivos atualizados." : "Versões já estavam sincronizadas.");
