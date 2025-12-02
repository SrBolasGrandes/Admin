-- ========================================
-- SISTEMA DE MODERAÇÃO EXTERNA - ROBLOX
-- ========================================

local EXTERNAL_API_BASE = "https://vinous-marcos-waggly.ngrok-free.dev/api/moderacao"
local API_KEY = "K8mP9nQ2rT5wV7yZ1bC3dF6gH4jL0N" -- DEVE SER A MESMA DO SERVIDOR FLASK

local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")

-- DataStore para bans permanentes
local BanDataStore = DataStoreService:GetDataStore("BannedPlayers")

-- ========================================
-- CONFIGURAÇÕES
-- ========================================
local UPDATE_INTERVAL = 10 -- Atualizar a cada 10 segundos
local MAX_RETRIES = 3
local DEBUG_MODE = true

-- ========================================
-- FUNÇÕES AUXILIARES
-- ========================================

local function log(message)
    if DEBUG_MODE then
        print("[MODERAÇÃO] " .. message)
    end
end

local function errorLog(message, err)
    warn("[MODERAÇÃO ERRO] " .. message .. ": " .. tostring(err))
end

-- ========================================
-- VERIFICAÇÃO DE BAN AO ENTRAR
-- ========================================

local function checkBanOnJoin(player)
    local userId = player.UserId
    
    -- Verificar no DataStore local
    local success, isBanned = pcall(function()
        return BanDataStore:GetAsync("Ban_" .. userId)
    end)
    
    if success and isBanned then
        player:Kick("🚫 Você está banido. Motivo: " .. (isBanned.reason or "Violação de regras"))
        log("Jogador banido tentou entrar: " .. player.Name .. " (ID: " .. userId .. ")")
        return
    end
    
    -- Verificar na API externa
    local headers = {
        ["X-API-Key"] = API_KEY
    }
    
    local checkSuccess, response = pcall(function()
        return HttpService:RequestAsync({
            Url = EXTERNAL_API_BASE .. "/checkBan/" .. userId,
            Method = "GET",
            Headers = headers
        })
    end)
    
    if checkSuccess and response.Success then
        local data = HttpService:JSONDecode(response.Body)
        
        if data.banned then
            -- Salvar no DataStore local para futuras verificações
            pcall(function()
                BanDataStore:SetAsync("Ban_" .. userId, {
                    reason = data.reason,
                    banned_by = data.banned_by,
                    timestamp = os.time()
                })
            end)
            
            player:Kick("🚫 Você está banido. Motivo: " .. (data.reason or "Violação de regras"))
            log("Jogador banido detectado pela API: " .. player.Name)
        end
    end
end

Players.PlayerAdded:Connect(checkBanOnJoin)

-- ========================================
-- ENVIAR LISTA DE JOGADORES
-- ========================================

local function sendPlayerList()
    local playerTable = {}
    
    for _, player in ipairs(Players:GetPlayers()) do
        table.insert(playerTable, {
            UserId = player.UserId,
            Name = player.Name
        })
    end
    
    local dataToSend = HttpService:JSONEncode(playerTable)
    local headers = {
        ["Content-Type"] = "application/json",
        ["X-API-Key"] = API_KEY
    }
    
    local attempts = 0
    local success = false
    
    while attempts < MAX_RETRIES and not success do
        attempts = attempts + 1
        
        local requestSuccess, response = pcall(function()
            return HttpService:RequestAsync({
                Url = EXTERNAL_API_BASE .. "/updatePlayers",
                Method = "POST",
                Headers = headers,
                Body = dataToSend
            })
        end)
        
        if requestSuccess then
            if response.Success then
                log("Lista de jogadores atualizada com sucesso (" .. #playerTable .. " jogadores)")
                success = true
            else
                errorLog("Falha na resposta do servidor", response.StatusCode)
            end
        else
            errorLog("Tentativa " .. attempts .. " falhou ao enviar lista de jogadores", response)
        end
        
        if not success and attempts < MAX_RETRIES then
            wait(2) -- Aguardar antes de tentar novamente
        end
    end
    
    return success
end

-- ========================================
-- VERIFICAR COMANDOS PENDENTES
-- ========================================

local function checkCommands()
    local headers = {
        ["X-API-Key"] = API_KEY
    }
    
    local success, response = pcall(function()
        return HttpService:RequestAsync({
            Url = EXTERNAL_API_BASE .. "/pendingCommands",
            Method = "GET",
            Headers = headers
        })
    end)
    
    if not success then
        errorLog("Erro ao buscar comandos", response)
        return
    end
    
    if not response.Success then
        errorLog("Resposta com erro ao buscar comandos", response.StatusCode)
        return
    end
    
    local decodeSuccess, commands = pcall(function()
        return HttpService:JSONDecode(response.Body)
    end)
    
    if not decodeSuccess then
        errorLog("Erro ao decodificar JSON", commands)
        return
    end
    
    if type(commands) ~= "table" then
        return
    end
    
    for _, commandData in ipairs(commands) do
        local action = commandData.Action
        local targetUserId = tonumber(commandData.UserId)
        local reason = commandData.Reason or "Ação de Moderação Externa"
        
        if not targetUserId then
            errorLog("UserID inválido recebido", commandData.UserId)
            continue
        end
        
        local targetPlayer = Players:GetPlayerByUserId(targetUserId)
        
        if targetPlayer then
            if action == "Kick" then
                log("Executando KICK em " .. targetPlayer.Name .. " - Motivo: " .. reason)
                targetPlayer:Kick("⚠️ Você foi removido do servidor.\n\nMotivo: " .. reason)
                
            elseif action == "Ban" then
                log("Executando BAN em " .. targetPlayer.Name .. " - Motivo: " .. reason)
                
                -- Salvar ban no DataStore
                pcall(function()
                    BanDataStore:SetAsync("Ban_" .. targetUserId, {
                        username = targetPlayer.Name,
                        reason = reason,
                        timestamp = os.time()
                    })
                end)
                
                targetPlayer:Kick("🚫 Você foi BANIDO permanentemente.\n\nMotivo: " .. reason)
            else
                errorLog("Ação desconhecida recebida", action)
            end
        else
            log("Jogador UserID " .. targetUserId .. " não está online, ignorando comando " .. action)
        end
    end
end

-- ========================================
-- COMANDO DE UNBAN (OPCIONAL)
-- ========================================

local function unbanPlayer(userId)
    local success, err = pcall(function()
        BanDataStore:RemoveAsync("Ban_" .. userId)
    end)
    
    if success then
        log("Ban removido do UserID " .. userId)
        return true
    else
        errorLog("Erro ao remover ban", err)
        return false
    end
end

-- Expor função para comandos do jogo (opcional)
_G.UnbanPlayer = unbanPlayer

-- ========================================
-- LOOP PRINCIPAL
-- ========================================

log("Sistema de moderação externa iniciado!")
log("Conectando ao servidor: " .. EXTERNAL_API_BASE)

-- Verificação inicial
if not HttpService.HttpEnabled then
    warn("⚠️ HTTP não está habilitado! Ative em Game Settings > Security > Allow HTTP Requests")
end

-- Loop infinito
while true do
    local success = sendPlayerList()
    
    -- Só verificar comandos se conseguiu enviar a lista
    if success then
        wait(1) -- Pequeno delay entre operações
        checkCommands()
    else
        warn("Falha ao enviar lista de jogadores, pulando verificação de comandos")
    end
    
    wait(UPDATE_INTERVAL)
end