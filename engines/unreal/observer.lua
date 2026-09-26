-- Experimental UMG bridge. The desktop process owns the Argos runtime.
-- Paths are substituted only when this mod is installed by SFTranslator.
if os.getenv("SFTRANSLATOR_MANAGED_RUNTIME") ~= "1" then return end
local log_path = OBSERVER_LOG_PATH
local bridge_path = OBSERVER_BRIDGE_PATH
local translate_enabled = OBSERVER_TRANSLATE_ENABLED
local profile = OBSERVER_PROFILE
local pending = {}
local last_sent = {}
local cache = {}
local rendered = {}
local intercept_logged = {}
local in_flight = {}
local responses = {}
local deferred = {}
local deferred_count = 0
local serial = 0
local applying = false
local queued = 0
local later = ExecuteInGameThreadWithDelay or ExecuteWithDelay

local function emit(kind, widget, value)
    local file = io.open(log_path, "a")
    if not file then return end
    value = tostring(value or ""):gsub("[\r\n\t]", " ")
    widget = tostring(widget or ""):gsub("[\r\n\t]", " ")
    file:write(kind, "\t", widget, "\t", value, "\n")
    file:close()
end

local function classify(widget, value, kind)
    if kind ~= "TEXT" and not (profile == "woman" and kind == "RICH") then return nil end
    -- The bridge accepts 8192 UTF-8 bytes. Never cut a multibyte character
    -- in the middle: over-limit text is observed but not sent for translation.
    if #value > 8192 or value:match("^%s*$") then return nil end
    if widget:find("_Dummy", 1, true) or widget:find("TalkerName", 1, true)
        or widget:find("GameVer", 1, true) then return nil end
    if value:find("<", 1, true) or value:find("\\", 1, true)
        or (not value:match("%a") and not value:find("[\128-\255]")) then return nil end
    if profile == "woman" then
        if not widget:find("BP_GameInstance_C_", 1, true) then return nil end
        local leaf = widget:match("%.([^.]+)$") or ""
        if leaf == "TB_Version" or leaf == "T_FPS" or leaf == "PaperCounter"
            or leaf == "PaperDayNumber" or leaf == "TB_DayNumber"
            or leaf == "T_Price" or leaf == "TB_Balance" or leaf == "T_Money"
            or leaf == "T_MoneyCount" or leaf == "T_SUM" or leaf == "TextBlock_79"
            or leaf == "T_DlgName" or widget:find("FallbackKeyLabel", 1, true)
            or value:match("^%a$") or value:match("^%d+[%d: /$%%%.]*$")
            or value:match("%.[A-Za-z0-9]+$") then return nil end
        if widget:find("WB_MainMenu2_C_", 1, true)
            and widget:match("%.B_[^.]+%.WidgetTree_%d+%.TextBlock$") then return "menu" end
        if widget:find("WB_EscapeMenu_C_", 1, true)
            and widget:match("%.B_[^.]+%.WidgetTree_%d+%.TextBlock$") then return "menu" end
        if widget:find("WB_Hotbar_C_", 1, true) and leaf == "TB_InteracteName" then return "interaction" end
        if widget:find("WB_QuestsPaper_C_", 1, true) and leaf == "TextBlock" then return "quest" end
        if widget:find("Messenger", 1, true) and (leaf == "T_MsgText" or leaf == "T_LastMsg") then return "chat" end
        if widget:find("DialogueResponseWidget_C_", 1, true) then return "choice" end
        if widget:find("DialogueWidget_C_", 1, true)
            and (leaf:find("DlgText", 1, true) or leaf == "T_MsgText" or leaf == "TextBlock") then return "dialogue" end
        -- A game-specific UMG fallback covers labels and planner panels whose
        -- Text property is initialized or bound without a SetText call.
        if leaf:find("Text", 1, true) or leaf:match("^TB_") or leaf:match("^T_")
            or leaf == "LabelText" or leaf == "NameLabel"
            or leaf == "TitleText" or leaf == "DescriptionText" then return "interface" end
        return nil
    end
    if widget:find("CommonTextBlock_CurrentSerif", 1, true) then return "dialogue" end
    if widget:find(".QuestName", 1, true) or widget:find(".QuestDescription", 1, true) then return "quest" end
    if widget:find(".TextBlock_ButtonText", 1, true) or widget:find(".TextBlock_GuideText", 1, true)
        or widget:find(".TextBlock_Title", 1, true) or widget:find(".TextBlock_Main", 1, true) then return "menu" end
    return nil
end

local function apply(widget, name, original, translated)
    if translated == original or translated == "" then return end
    local ok, result = pcall(function()
        if not widget or not widget:IsValid() or widget:GetFullName() ~= name then return "gone" end
        local current = widget:GetText()
        if not current or current:ToString() ~= original then return "changed" end
        applying = true
        widget:SetText(FText(translated))
        applying = false
        local updated = widget:GetText()
        return updated and updated:ToString() == translated and "applied" or "unchanged"
    end)
    applying = false
    if not ok then emit("ERROR", name, tostring(result))
    elseif result == "applied" then
        rendered[name] = translated
        emit("APPLY", name, original .. " => " .. translated)
        later(700, function()
            local stable, current = pcall(function()
                if widget and widget:IsValid() and widget:GetFullName() == name then
                    local text = widget:GetText()
                    return text and text:ToString()
                end
            end)
            if stable and current == original then emit("REVERT", name, original)
            elseif stable and current == translated then emit("STABLE", name, translated) end
        end)
    elseif result == "unchanged" then emit("MISS", name, original .. " => " .. translated) end
end

local function request(widget, name, value, category)
    local known = cache[value]
    if known then apply(widget, name, value, known); return end
    local request_id = in_flight[value]
    if request_id then
        table.insert(responses[request_id].widgets, {widget, name, value})
        return
    end
    local urgent = category == "dialogue" or category == "choice"
        or category == "chat" or category == "interaction"
    if queued >= (urgent and 64 or 24) then
        if not deferred[value] then
            if deferred_count >= 256 then emit("ERROR", name, "Fila de tradução cheia"); return end
            deferred[value] = {category = category, widgets = {}}
            deferred_count = deferred_count + 1
        end
        table.insert(deferred[value].widgets, {widget, name, value})
        return
    end
    serial = serial + 1
    request_id = (urgent and "d_" or "m_")
        .. string.format("%08d", serial)
    local path = bridge_path .. "/requests/" .. request_id
    local file = io.open(path .. ".tmp", "wb")
    if not file then emit("ERROR", name, "Fila de tradução indisponível"); return end
    file:write(value)
    file:close()
    local renamed, error_message = os.rename(path .. ".tmp", path .. ".req")
    if not renamed then
        os.remove(path .. ".tmp")
        emit("ERROR", name, tostring(error_message))
        return
    end
    queued = queued + 1
    in_flight[value] = request_id
    responses[request_id] = {source = value, category = category, widgets = {{widget, name, value}}}
    emit("QUEUE", name, value)
end

local function poll()
    for id, item in pairs(responses) do
        local path = bridge_path .. "/responses/" .. id .. ".res"
        local file = io.open(path, "rb")
        if file then
            local translated = file:read("*a")
            file:close()
            os.remove(path)
            responses[id] = nil
            in_flight[item.source] = nil
            queued = queued - 1
            if translated and translated ~= "" then
                cache[item.source] = translated
                for _, target in ipairs(item.widgets) do
                    apply(target[1], target[2], target[3], translated)
                end
            end
        end
    end
    if queued < 64 then
        for pass = 1, 2 do
            for value, item in pairs(deferred) do
                local urgent = item.category == "dialogue" or item.category == "choice"
                    or item.category == "chat" or item.category == "interaction"
                if urgent == (pass == 1) and queued < (urgent and 64 or 24) then
                    deferred[value] = nil
                    deferred_count = deferred_count - 1
                    for _, target in ipairs(item.widgets) do
                        request(target[1], target[2], target[3], item.category)
                    end
                end
            end
        end
    end
    later(100, poll)
end

local function observe(context, incoming, kind)
    if applying then return end
    local ok, widget, name, value = pcall(function()
        local object = context:get()
        if not object or not object:IsValid() then return nil, nil, nil end
        local text = incoming:get()
        if not text then return nil, nil, nil end
        return object, object:GetFullName(), text:ToString()
    end)
    if not ok then emit("ERROR", kind, tostring(widget)); return end
    if not name or not value or value:match("^%s*$") then return end
    local category = classify(name, value, kind)
    if translate_enabled and category and cache[value] and cache[value] ~= value then
        local replaced = pcall(function() incoming:set(FText(cache[value])) end)
        if replaced then
            rendered[name] = cache[value]
            if intercept_logged[name] ~= value then
                intercept_logged[name] = value
                emit("INTERCEPT", name, value .. " => " .. cache[value])
            end
            return
        end
    end
    serial = serial + 1
    local token = serial
    local key = kind .. "\t" .. name
    pending[key] = {token = token, widget = widget, value = value}
    -- The sample emits complete dialogue into SetText. Debounce also protects
    -- widgets that might call SetText for every character.
    later(category == "dialogue" and 180 or category == "choice" and 100
        or category == "chat" and 180 or category == "interaction" and 100
        or category == "menu" and 150 or 450, function()
        local current = pending[key]
        if not current or current.token ~= token then return end
        pending[key] = nil
        if last_sent[key] == current.value then return end
        last_sent[key] = current.value
        emit(kind, name, current.value)
        if translate_enabled and classify(name, current.value, kind) then
            request(current.widget, name, current.value, category)
        end
    end)
end

-- Some UMG fields are initialized from serialized FText or a binding and never
-- call SetText. Track only newly constructed TextBlocks from this known game;
-- sample a small batch on the game thread instead of scanning all UObjects.
local tracked = {}
local tracked_index = 1
local urgent_tracked = {}
local retries = {}
local unmapped = {}
local unmapped_count = 0

local function sample_widget(entry)
    local ok, value = pcall(function()
        if not entry.widget:IsValid() or entry.widget:GetFullName() ~= entry.name then return nil end
        local current = entry.widget:GetText()
        return current and current:ToString()
    end)
    if not ok or not value then
        entry.failures = (entry.failures or 0) + 1
        return entry.failures < 3
    end
    entry.failures = 0
    local category = classify(entry.name, value, entry.kind)
    local key = entry.kind .. "\t" .. entry.name
    if category == "dialogue" then
        if entry.candidate ~= value then
            entry.candidate = value
            return true
        end
    end
    if category and last_sent[key] ~= value and rendered[entry.name] ~= value then
        last_sent[key] = value
        emit("SNAP", entry.name, value)
        request(entry.widget, entry.name, value, category)
    elseif category and cache[value] and cache[value] ~= value
        and rendered[entry.name] ~= value and (retries[entry.name] or 0) < 2 then
        retries[entry.name] = (retries[entry.name] or 0) + 1
        emit("RETRY", entry.name, value)
        apply(entry.widget, entry.name, value, cache[value])
    elseif not category and #value >= 3 and value:match("%a")
        and unmapped[entry.name] ~= value and unmapped_count < 80 then
        unmapped[entry.name] = value
        unmapped_count = unmapped_count + 1
        emit("UNMAPPED", entry.name, value)
    end
    return true
end

local function poll_tracked()
    for index = #urgent_tracked, 1, -1 do
        if not sample_widget(urgent_tracked[index]) then table.remove(urgent_tracked, index) end
    end
    for _ = 1, 16 do
        if #tracked == 0 then break end
        if tracked_index > #tracked then tracked_index = 1 end
        if sample_widget(tracked[tracked_index]) then tracked_index = tracked_index + 1
        else table.remove(tracked, tracked_index) end
    end
    later(100, poll_tracked)
end

local function track_new_textblocks()
    local function register(path, kind)
        local ok, error_message = pcall(NotifyOnNewObject, path, function(widget)
            local valid, name = pcall(function() return widget:GetFullName() end)
            if not valid or not name or not name:find("BP_GameInstance_C_", 1, true) then return end
            if name:match("%.TextBlock_79$") or name:find("FallbackKeyLabel", 1, true) then return end
            local urgent = name:find("DialogueWidget_C_", 1, true)
                or name:find("Messenger", 1, true)
                or name:find("WB_Hotbar_C_", 1, true)
            local pool = urgent and urgent_tracked or tracked
            local limit = urgent and 96 or 600
            if #pool >= limit then
                table.remove(pool, 1)
                if not urgent then tracked_index = math.max(1, tracked_index - 1) end
            end
            table.insert(pool, {widget = widget, name = name, kind = kind})
        end)
        if ok then emit("HOOK", "SNAP", "Acompanhamento de " .. path .. " sem SetText")
        else emit("ERROR", "SNAP", tostring(error_message)) end
    end
    register("/Script/UMG.TextBlock", "TEXT")
    register("/Script/UMG.RichTextBlock", "RICH")
    later(100, poll_tracked)
end

local function install(path, kind)
    local ok, pre = pcall(RegisterHook, path, function(context, incoming)
        observe(context, incoming, kind)
    end)
    if ok and pre then emit("HOOK", kind, path)
    else emit("ERROR", kind, "Hook indisponível: " .. path .. " " .. tostring(pre)) end
end

emit("READY", "SFTranslator", translate_enabled and "Captura UMG e tradução Argos local iniciadas" or "Captura UMG somente leitura iniciada")
install("/Script/UMG.TextBlock:SetText", "TEXT")
install("/Script/UMG.RichTextBlock:SetText", "RICH")
if translate_enabled then
    later(100, poll)
    if profile == "woman" then track_new_textblocks() end
end
