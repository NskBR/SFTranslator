// SFTRANSLATOR_RPGMAKER_JS_V1
/*:
 * @plugindesc Experimental local translation for RPG Maker MV/MZ messages, choices and text menus.
 * @author SFTranslator
 * @help Installed and configured by SFTranslator. Keep this plugin last in the list.
 */
(() => {
    "use strict";

    if (typeof Game_Message === "undefined" || typeof Window_Message === "undefined" ||
        typeof Window_Base === "undefined" || typeof PluginManager === "undefined") {
        console.warn("[SFTranslator] RPG Maker JavaScript APIs unavailable.");
        return;
    }

    const settings = PluginManager.parameters("SFTranslator");
    const gameId = String(settings.gameId || "legacy");
    const source = String(settings.source || "en").toLowerCase();
    const target = String(settings.target || "pb").toLowerCase();
    const flowMode = settings.flowMode === "chain" ? "chain" : "direct";
    const intermediate = flowMode === "chain" ? "en" : "";
    const port = Number(settings.port) || 5002;
    const endpoint = `http://127.0.0.1:${port}/translate`;
    const cachePath = `${source}_${intermediate ? `${intermediate}_` : ""}${target}`;
    const cacheKey = `sftranslator_rpgmaker_cache_v2:${gameId}:${cachePath}:${String(settings.cacheVersion || "0")}`;
    const legacyKey = `sftranslator_rpgmaker_cache_v2:${gameId}:${cachePath}`;
    const cache = new Map();
    const cacheFile = String(settings.cacheFile || "");
    let fileSystem = null;

    if (cacheFile && typeof require === "function") {
        try { fileSystem = require("fs"); }
        catch (error) { console.warn("[SFTranslator] File cache unavailable:", error); }
    }

    if (!fileSystem && typeof localStorage !== "undefined" &&
        typeof localStorage.key === "function" && typeof localStorage.removeItem === "function") {
        for (let index = localStorage.length - 1; index >= 0; index--) {
            const key = localStorage.key(index);
            if (key && (key === legacyKey || key.startsWith(`${legacyKey}:`)) && key !== cacheKey) {
                localStorage.removeItem(key);
            }
        }
    }

    try {
        const diskExists = fileSystem && fileSystem.existsSync(cacheFile);
        const migrating = fileSystem && !diskExists && String(settings.cacheVersion || "0") === "0" &&
            typeof localStorage !== "undefined" && Boolean(localStorage.getItem(legacyKey));
        const saved = JSON.parse(fileSystem
            ? (diskExists ? fileSystem.readFileSync(cacheFile, "utf8") :
                (migrating ? localStorage.getItem(legacyKey) : "[]"))
            : (localStorage.getItem(cacheKey) || "[]"));
        if (Array.isArray(saved)) {
            for (const entry of saved) {
                if (Array.isArray(entry) && typeof entry[0] === "string" && typeof entry[1] === "string") {
                    cache.set(entry[0], entry[1]);
                }
            }
        }
        if (migrating) {
            fileSystem.mkdirSync(require("path").dirname(cacheFile), { recursive: true });
            fileSystem.writeFileSync(cacheFile, JSON.stringify([...cache]), "utf8");
            if (typeof localStorage.removeItem === "function") localStorage.removeItem(legacyKey);
        }
    } catch (error) {
        console.warn("[SFTranslator] Cache unavailable:", error);
    }

    function remember(original, translated) {
        cache.set(original, translated);
        if (cache.size > 1000) cache.delete(cache.keys().next().value);
        try {
            if (fileSystem) {
                fileSystem.mkdirSync(require("path").dirname(cacheFile), { recursive: true });
                fileSystem.writeFileSync(`${cacheFile}.tmp`, JSON.stringify([...cache]), "utf8");
                fileSystem.renameSync(`${cacheFile}.tmp`, cacheFile);
            } else {
                localStorage.setItem(cacheKey, JSON.stringify([...cache]));
            }
        } catch (error) {
            console.warn("[SFTranslator] Could not save cache:", error);
        }
    }

    function requestTranslation(text) {
        const body = JSON.stringify({ q: text, source, target });
        if (typeof require === "function") {
            try {
                const http = require("http");
                return new Promise((resolve, reject) => {
                    const request = http.request({
                        hostname: "127.0.0.1", port, path: "/translate", method: "POST",
                        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) }
                    }, response => {
                        const chunks = [];
                        response.on("data", chunk => chunks.push(chunk));
                        response.on("end", () => {
                            if (response.statusCode < 200 || response.statusCode >= 300) {
                                reject(new Error(`HTTP ${response.statusCode}`));
                                return;
                            }
                            try { resolve(JSON.parse(Buffer.concat(chunks).toString("utf8"))); }
                            catch (error) { reject(error); }
                        });
                    });
                    request.setTimeout(90000, () => request.destroy(new Error("Translation timeout")));
                    request.on("error", reject);
                    request.end(body);
                });
            } catch (error) {
                console.warn("[SFTranslator] Node HTTP unavailable, trying fetch:", error);
            }
        }
        const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
        const timer = controller ? setTimeout(() => controller.abort(), 90000) : null;
        return fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body,
            signal: controller ? controller.signal : undefined
        }).then(response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        }).finally(() => { if (timer) clearTimeout(timer); });
    }

    async function translatePlain(text) {
        if (!text.trim() || source === target) return text;
        if (cache.has(text)) return cache.get(text);
        try {
            const result = await requestTranslation(text);
            if (typeof result.translatedText !== "string" || !result.translatedText) {
                throw new Error("Invalid translation response");
            }
            if (result.translatedText !== text) remember(text, result.translatedText);
            return result.translatedText;
        } catch (error) {
            console.warn("[SFTranslator] Translation failed, keeping original:", error);
            return text;
        }
    }

    // Keep RPG Maker escapes and plugin tags such as <WordWrap> and <br> out of Argos.
    // Translating <WordWrap> into <Wrap> makes YEP_MessageCore print it as dialogue.
    const controlCode = /(\\(?:[A-Za-z]+\[[^\]]*\]|[{}.$|!><^\\])|\x1b(?:[A-Za-z]+\[[^\]]*\]|[{}.$|!><^\\])|\f|<\/?[A-Za-z][A-Za-z0-9]*(?:[\s_-]+[A-Za-z0-9]+)*(?::[^<>]*)?>)/g;
    async function translateText(text) {
        if (!text || source === target) return text;
        const parts = text.split(controlCode);
        if (parts.length === 1) return translatePlain(text);
        const translated = await Promise.all(parts.map((part, index) =>
            index % 2 === 1 ? part : translatePlain(part)));
        return translated.join("");
    }

    // Database terms are text, while labels drawn into PNG assets are not.
    // Keep database changes in memory so the game's files and saves stay intact.
    if (typeof DataManager !== "undefined" && typeof DataManager.onLoad === "function") {
        const originalOnLoad = DataManager.onLoad;
        DataManager.onLoad = function(object) {
            originalOnLoad.call(this, object);
            if (object !== window.$dataSystem || !object || !object.terms || source === target) return;
            const fields = [object.terms.commands, object.terms.basic, object.terms.params];
            const jobs = [];
            for (const field of fields) {
                if (!Array.isArray(field)) continue;
                field.forEach((value, index) => {
                    if (typeof value === "string" && value.trim() && !/%\d/.test(value)) {
                        jobs.push({ field, index, value });
                    }
                });
            }
            let next = 0;
            const worker = async () => {
                while (next < jobs.length) {
                    const { field, index, value } = jobs[next++];
                    const translated = await translatePlain(value);
                    if (field[index] !== value || translated === value) continue;
                    field[index] = translated;
                    const windows = window.SceneManager?._scene?._windowLayer?.children || [];
                    for (const gameWindow of windows) {
                        if (typeof gameWindow.refresh === "function") gameWindow.refresh();
                    }
                }
            };
            Promise.all([worker(), worker()]).catch(error =>
                console.warn("[SFTranslator] Menu translation failed:", error));
        };
    }

    if (typeof Game_Map !== "undefined" && typeof Game_Map.prototype.displayName === "function") {
        const originalDisplayName = Game_Map.prototype.displayName;
        const requestedMapNames = new Map();
        Game_Map.prototype.displayName = function() {
            const original = originalDisplayName.call(this);
            if (!original || source === target) return original;
            if (cache.has(original)) return cache.get(original);
            if ((requestedMapNames.get(original) || 0) <= Date.now()) {
                requestedMapNames.set(original, Infinity);
                translatePlain(original).then(translated => {
                    if (translated === original) {
                        requestedMapNames.set(original, Date.now() + 5000);
                        return;
                    }
                    requestedMapNames.delete(original);
                    if (!window.$gameMap ||
                        originalDisplayName.call(window.$gameMap) !== original) return;
                    const mapData = window.$gameSystem?._mapNameData;
                    if (mapData) mapData.name = translated;
                    const scene = window.SceneManager?._scene;
                    if (scene?._mapNameHud && typeof scene._mapNameHud.refreshName === "function") {
                        scene._mapNameHud.refreshName();
                    }
                    if (scene?._mapNameWindow && typeof scene._mapNameWindow.refresh === "function") {
                        scene._mapNameWindow.refresh();
                    }
                }).catch(error => {
                    requestedMapNames.set(original, Date.now() + 5000);
                    console.warn("[SFTranslator] Map name failed:", error);
                });
            }
            return original;
        };
    }

    const originalClear = Game_Message.prototype.clear;
    Game_Message.prototype.clear = function() {
        originalClear.call(this);
        this._sfGeneration = (this._sfGeneration || 0) + 1;
    };

    const originalUpdate = Window_Message.prototype.update;
    Window_Message.prototype.update = function() {
        if (this._sfMessagePending || this._sfChoicesPending) {
            Window_Base.prototype.update.call(this);
            return;
        }
        const message = window.$gameMessage;
        if (message && !this._textState && message.hasText() && !message.scrollMode()) {
            const generation = message._sfGeneration || 0;
            if (this._sfMessageGeneration !== generation) {
                const original = message.allText();
                this._sfMessagePending = true;
                translateText(original).then(translated => {
                    if (window.$gameMessage === message && (message._sfGeneration || 0) === generation &&
                        message.allText() === original) {
                        if (translated !== original) message._texts = translated.split("\n");
                        this._sfMessageGeneration = generation;
                    }
                }).catch(error => {
                    console.warn("[SFTranslator] Message error:", error);
                    this._sfMessageGeneration = generation;
                }).finally(() => { this._sfMessagePending = false; });
                Window_Base.prototype.update.call(this);
                return;
            }
        }
        originalUpdate.call(this);
    };

    const originalStartInput = Window_Message.prototype.startInput;
    Window_Message.prototype.startInput = function() {
        const message = window.$gameMessage;
        if (!message || !message.isChoice()) return originalStartInput.call(this);
        const generation = message._sfGeneration || 0;
        if (this._sfChoiceGeneration === generation) return originalStartInput.call(this);
        if (this._sfChoicesPending) return true;
        const choices = message.choices().slice();
        this._sfChoicesPending = true;
        Promise.all(choices.map(translateText)).then(translated => {
            if (window.$gameMessage === message && (message._sfGeneration || 0) === generation &&
                choices.every((choice, index) => message.choices()[index] === choice)) {
                message._choices = translated;
                this._sfChoiceGeneration = generation;
                originalStartInput.call(this);
            }
        }).catch(error => {
            console.warn("[SFTranslator] Choice error:", error);
            this._sfChoiceGeneration = generation;
            originalStartInput.call(this);
        }).finally(() => { this._sfChoicesPending = false; });
        return true;
    };

    window.SFTranslatorRPGMaker = { translateText, cacheKey, flowMode };
    window.SFTranslatorMZ = window.SFTranslatorRPGMaker;
    console.info(`[SFTranslator] RPG Maker translation ready: ${cachePath}`);
})();
