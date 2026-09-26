"use strict";

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const net = require("node:net");
const http = require("node:http");
const vm = require("node:vm");
const { spawn } = require("node:child_process");

const app = path.resolve(__dirname, "..");
const [models, source = "ja", target = "pb", flowMode = "chain", original = "こんにちは。お元気ですか？"] = process.argv.slice(2);
if (!models) throw new Error("Informe o diretório de modelos universais.");
const runtimes = path.join(app, "src-tauri", "resources", "runtimes");
const executable = path.join(runtimes, "unity", "lt.exe");
const plugin = fs.readFileSync(path.join(app, "engines", "rpgmaker", "js", "SFTranslator.js"), "utf8");

async function freePort() {
    const probe = net.createServer();
    await new Promise(resolve => probe.listen(0, "127.0.0.1", resolve));
    const port = probe.address().port;
    await new Promise(resolve => probe.close(resolve));
    return port;
}

function health(port) {
    return new Promise(resolve => {
        const request = http.get(`http://127.0.0.1:${port}/health`, response => {
            response.resume();
            resolve(response.statusCode === 200);
        });
        request.setTimeout(500, () => request.destroy());
        request.on("error", () => resolve(false));
    });
}

async function main() {
    const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "sftranslator-mz-smoke-"));
    let server;
    let output = "";
    try {
        const port = await freePort();
        const state = path.join(temporary, "state");
        fs.mkdirSync(state);
        fs.writeFileSync(path.join(state, "unity_uat_config.json"), JSON.stringify({
            source_language: source, target_language: target, flow_mode: flowMode,
            intermediate_language: "en", server: { port }
        }));
        server = spawn(executable, ["__server__"], {
            cwd: path.dirname(executable), windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
            env: { ...process.env, UAT_STATE_DIR: state, UAT_GAME_DIR: temporary,
                UAT_MODELS_DIR: path.resolve(models), UAT_SBD_DIR: path.join(runtimes, "minisbd"),
                SFTRANSLATOR_MANAGED_RUNTIME: "1", PYTHONIOENCODING: "utf-8" }
        });
        server.stdout.on("data", chunk => { output += chunk.toString(); });
        server.stderr.on("data", chunk => { output += chunk.toString(); });
        for (let attempt = 0; attempt < 180 && !await health(port); attempt++) {
            if (server.exitCode !== null) throw new Error(`Servidor encerrou: ${server.exitCode}\n${output}`);
            await new Promise(resolve => setTimeout(resolve, 500));
        }
        if (!await health(port)) throw new Error(`Servidor não iniciou.\n${output}`);

        class Game_Message { clear() {} }
        class Window_Base { update() {} }
        class Window_Message { update() {} startInput() { return true; } }
        const storage = new Map();
        const cacheFile = path.join(temporary, "cache", "translations.json");
        const context = {
            Game_Message, Window_Base, Window_Message, Buffer, require,
            PluginManager: { parameters: () => ({ source, target, flowMode, port: String(port), cacheFile }) },
            localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) },
            console, setTimeout, clearTimeout, AbortController, window: null,
        };
        context.window = context;
        vm.runInNewContext(plugin, context);
        const translated = await context.SFTranslatorMZ.translateText(original);
        if (!translated || translated === original) throw new Error(`Sem tradução: ${translated}\n${output}`);
        const saved = JSON.parse(fs.readFileSync(cacheFile, "utf8"));
        if (!saved.some(([key, value]) => key === original && value === translated)) {
            throw new Error("A tradução não foi persistida no cache por arquivo.");
        }
        server.kill();
        await new Promise(resolve => server.once("exit", resolve));
        const replay = { ...context, Game_Message, Window_Base, Window_Message };
        vm.runInNewContext(plugin, replay);
        const fromCache = await replay.SFTranslatorMZ.translateText(original);
        if (fromCache !== translated) throw new Error("O cache não foi reutilizado após reiniciar o plugin.");
        console.log(`PASS RPG Maker ${flowMode} via plugin + Argos: ${original} -> ${translated}`);
    } finally {
        if (server && server.exitCode === null) {
            server.kill();
            await new Promise(resolve => server.once("exit", resolve));
        }
        if (path.dirname(temporary) === os.tmpdir()) fs.rmSync(temporary, { recursive: true, force: true });
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
