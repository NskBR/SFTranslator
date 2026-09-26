const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const vm = require("node:vm");

const plugin = fs.readFileSync(require("node:path").join(__dirname, "..", "js", "SFTranslator.js"), "utf8");

function makeGame({ gameId = "test-game", source = "en", target = "pb", flowMode = "direct", port = 5002, fetchImpl, storage, clock } = {}) {
    const values = storage || new Map();
    class Game_Message {
        constructor() { this.clear(); }
        clear() { this._texts = []; this._choices = []; }
        add(text) { this._texts.push(text); }
        allText() { return this._texts.join("\n"); }
        hasText() { return this._texts.length > 0; }
        scrollMode() { return false; }
        choices() { return this._choices; }
        isChoice() { return this._choices.length > 0; }
        setChoices(choices) { this._choices = choices; }
    }
    class Window_Base { update() {} }
    class Window_Message extends Window_Base {
        update() { if (context.$gameMessage.hasText()) this.rendered = context.$gameMessage.allText(); }
        startInput() { this.startedChoices = [...context.$gameMessage.choices()]; return true; }
    }
    class Game_Map {
        displayName() { return this.name || ""; }
    }
    const context = {
        Game_Message, Game_Map, Window_Base, Window_Message,
        DataManager: { onLoad() {} },
        SceneManager: { _scene: { _windowLayer: { children: [] } } },
        PluginManager: { parameters: () => ({ gameId, source, target, flowMode, port: String(port) }) },
        localStorage: {
            getItem: key => values.get(key) || null,
            setItem: (key, value) => values.set(key, value),
        },
        fetch: fetchImpl,
        console: { info() {}, warn() {} },
        setTimeout, clearTimeout, AbortController, Buffer,
        Date: clock ? class extends Date { static now() { return clock.now; } } : Date,
        window: null,
    };
    context.window = context;
    context.$gameMessage = new Game_Message();
    context.$gameMap = new Game_Map();
    context.$gameSystem = { _mapNameData: { name: "" } };
    vm.runInNewContext(plugin, context, { filename: "SFTranslator.js" });
    return { context, message: context.$gameMessage, window: new Window_Message(), storage: values };
}

const tick = () => new Promise(resolve => setImmediate(resolve));
async function waitFor(predicate) {
    for (let attempt = 0; attempt < 30; attempt++) {
        if (predicate()) return;
        await tick();
    }
    assert.fail("Translation did not complete");
}
const response = translatedText => ({ ok: true, json: async () => ({ translatedText }) });

test("MZ translates dialogue before displaying it and protects control codes", async () => {
    const requests = [];
    const game = makeGame({ fetchImpl: async (_url, options) => {
        requests.push(JSON.parse(options.body).q);
        return response("Olá");
    } });
    game.message.add("\\C[2]Hello");
    game.window.update();
    assert.equal(game.window.rendered, undefined);
    await waitFor(() => !game.window._sfMessagePending);
    game.window.update();
    assert.equal(game.window.rendered, "\\C[2]Olá");
    assert.deepEqual(requests, ["Hello"]);
});

test("MZ translates choices without changing their indexes", async () => {
    const game = makeGame({ fetchImpl: async (_url, options) => response(`${JSON.parse(options.body).q}-PB`) });
    game.message.setChoices(["Yes", "No"]);
    game.window.startInput();
    assert.equal(game.window.startedChoices, undefined);
    await waitFor(() => !game.window._sfChoicesPending);
    assert.deepEqual([...game.window.startedChoices], ["Yes-PB", "No-PB"]);
});

test("MZ preserves page breaks between translated passages", async () => {
    const game = makeGame({ fetchImpl: async (_url, options) => response(`${JSON.parse(options.body).q}-PB`) });
    assert.equal(await game.context.SFTranslatorMZ.translateText("First\fSecond"), "First-PB\fSecond-PB");
});

test("MV/MZ preserves message plugin tags without sending them to Argos", async () => {
    const requests = [];
    const game = makeGame({ fetchImpl: async (_url, options) => {
        const original = JSON.parse(options.body).q;
        requests.push(original);
        return response(`PB:${original}`);
    } });
    const original = "<WordWrap>\\c[1]New Go to School Quest has been added <br>\n<WordWrap>Open Quest Logs";
    const translated = await game.context.SFTranslatorRPGMaker.translateText(original);
    assert.equal(translated, "<WordWrap>\\c[1]PB:New Go to School Quest has been added <br>\n<WordWrap>PB:Open Quest Logs");
    assert.deepEqual(requests, ["New Go to School Quest has been added ", "Open Quest Logs"]);
});

test("failure displays the original and direct/chain caches stay separate", async () => {
    const storage = new Map();
    const failed = makeGame({ fetchImpl: async () => { throw new Error("offline"); }, storage });
    failed.message.add("Hello");
    failed.window.update();
    await waitFor(() => !failed.window._sfMessagePending);
    failed.window.update();
    assert.equal(failed.window.rendered, "Hello");

    let requests = 0;
    const direct = makeGame({ fetchImpl: async () => { requests++; return response("Olá"); }, storage });
    assert.equal(await direct.context.SFTranslatorMZ.translateText("Hello"), "Olá");
    assert.equal(await direct.context.SFTranslatorMZ.translateText("Hello"), "Olá");
    const chain = makeGame({ fetchImpl: async () => { requests++; return response("Olá"); }, storage, flowMode: "chain" });
    assert.equal(await chain.context.SFTranslatorMZ.translateText("Hello"), "Olá");
    assert.equal(requests, 2);
    assert.notEqual(direct.context.SFTranslatorMZ.cacheKey, chain.context.SFTranslatorMZ.cacheKey);
});

test("translation caches do not leak between RPG Maker games", async () => {
    const storage = new Map();
    let requests = 0;
    const fetchImpl = async () => { requests++; return response(`Tradução ${requests}`); };
    const first = makeGame({ gameId: "first", storage, fetchImpl });
    const second = makeGame({ gameId: "second", storage, fetchImpl });
    assert.equal(await first.context.SFTranslatorRPGMaker.translateText("Menu"), "Tradução 1");
    assert.equal(await second.context.SFTranslatorRPGMaker.translateText("Menu"), "Tradução 2");
    assert.notEqual(first.context.SFTranslatorRPGMaker.cacheKey, second.context.SFTranslatorRPGMaker.cacheKey);
});

test("unchanged server fallback is retried instead of cached", async () => {
    let requests = 0;
    const game = makeGame({ fetchImpl: async () => { requests++; return response("Hello"); } });
    assert.equal(await game.context.SFTranslatorMZ.translateText("Hello"), "Hello");
    assert.equal(await game.context.SFTranslatorMZ.translateText("Hello"), "Hello");
    assert.equal(requests, 2);
});

test("MZ uses local Node HTTP from an NW.js game", async () => {
    const server = http.createServer((request, responseObject) => {
        let body = "";
        request.on("data", chunk => { body += chunk; });
        request.on("end", () => {
            assert.equal(JSON.parse(body).q, "Hello");
            responseObject.writeHead(200, { "Content-Type": "application/json" });
            responseObject.end(JSON.stringify({ translatedText: "Olá" }));
        });
    });
    await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    try {
        const game = makeGame({ port: server.address().port });
        game.context.require = require;
        assert.equal(await game.context.SFTranslatorMZ.translateText("Hello"), "Olá");
    } finally {
        await new Promise(resolve => server.close(resolve));
    }
});

test("MZ translates map labels and refreshes the current map HUD", async () => {
    const requests = [];
    const game = makeGame({ fetchImpl: async (_url, options) => {
        requests.push(JSON.parse(options.body).q);
        return response("Sala de Estar");
    } });
    game.context.$gameMap.name = "Living Room";
    let refreshed = 0;
    game.context.SceneManager._scene._mapNameHud = { refreshName() { refreshed++; } };
    assert.equal(game.context.$gameMap.displayName(), "Living Room");
    assert.equal(game.context.$gameMap.displayName(), "Living Room");
    await waitFor(() => refreshed === 1);
    assert.equal(game.context.$gameMap.displayName(), "Sala de Estar");
    assert.equal(game.context.$gameSystem._mapNameData.name, "Sala de Estar");
    assert.deepEqual(requests, ["Living Room"]);
});

test("map name retries after a temporary translation failure", async () => {
    const clock = { now: 1000 };
    let requests = 0;
    const game = makeGame({ clock, fetchImpl: async () => {
        requests++;
        return response(requests === 1 ? "Living Room" : "Sala de Estar");
    } });
    game.context.$gameMap.name = "Living Room";
    assert.equal(game.context.$gameMap.displayName(), "Living Room");
    await tick();
    await tick();
    game.context.$gameMap.displayName();
    assert.equal(requests, 1);
    clock.now += 5000;
    game.context.$gameMap.displayName();
    await waitFor(() => game.context.$gameMap.displayName() === "Sala de Estar");
    assert.equal(requests, 2);
});

test("MZ translates database menu terms in memory and refreshes visible windows", async () => {
    const game = makeGame({ fetchImpl: async (_url, options) =>
        response(`${JSON.parse(options.body).q}-PB`) });
    const terms = { commands: ["New Game", "Save", null], basic: ["Level"], params: ["Luck"] };
    game.context.$dataSystem = { terms };
    let refreshed = 0;
    game.context.SceneManager._scene._windowLayer.children.push({ refresh() { refreshed++; } });
    game.context.DataManager.onLoad(game.context.$dataSystem);
    await waitFor(() => terms.commands[1] === "Save-PB" && terms.params[0] === "Luck-PB");
    assert.equal(terms.commands[0], "New Game-PB");
    assert.equal(terms.basic[0], "Level-PB");
    assert.ok(refreshed > 0);
});
