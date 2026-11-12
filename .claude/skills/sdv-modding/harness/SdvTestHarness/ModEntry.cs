using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using StardewModdingAPI;
using StardewModdingAPI.Events;
using StardewValley;
using StardewValley.Logging;
using StardewValley.Menus;

namespace SdvTestHarness;

/// <summary>
/// Scripted in-game checks. Dormant unless harness-commands.json exists next to the DLL.
/// Flow: title screen -> load the named TEST save through the real load menu -> run steps -> write harness-results.json -> wait to be closed.
/// Safety: the save folder must pass SavePolicy.IsTestSave before any menu is touched and again after the load; the harness
/// never triggers a save. Steps that need the outside (window screenshots, SMAPI console commands) are handed to game.py through
/// harness-request.json / harness-ack.json.
/// </summary>
internal sealed class ModEntry : Mod
{
    private enum Phase { Dormant, WaitTitle, WaitSlots, Loading, Running, Finished }

    private sealed class Step
    {
        public string Type { get; set; } = "";
        public string? Location { get; set; }
        public int X { get; set; }
        public int Y { get; set; }
        public int Value { get; set; }
        public string? Command { get; set; }
        public string? Item { get; set; }
        public int Count { get; set; } = 1;
        public int Ticks { get; set; } = 60;
        public string? Name { get; set; }
        public string? Npc { get; set; }
    }

    private sealed class Script
    {
        [JsonPropertyName("save")] public string Save { get; set; } = "";
        [JsonPropertyName("save_prefix")] public string SavePrefix { get; set; } = SavePolicy.DefaultPrefix;
        [JsonPropertyName("timeout_seconds")] public int TimeoutSeconds { get; set; } = 300;
        [JsonPropertyName("exit_when_done")] public bool ExitWhenDone { get; set; }
        [JsonPropertyName("steps")] public List<Step> Steps { get; set; } = new();
    }

    private sealed class StepResult
    {
        public int Index { get; set; }
        public string Type { get; set; } = "";
        public bool Ok { get; set; }
        public string? Error { get; set; }
        public string? Info { get; set; }
    }

    private static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true, ReadCommentHandling = JsonCommentHandling.Skip, AllowTrailingCommas = true };

    private Phase phase = Phase.Dormant;
    private Script script = new();
    private readonly List<StepResult> results = new();
    private readonly List<string> errors = new();
    private DateTime started;
    private int stepIndex = -1;
    private int stepTicks;
    private int waitTicks;
    private int requestSeq;
    private bool stepStarted;
    private bool skippedIntro;
    private LoadGameMenu? loadMenu;
    private string commandsPath = "", resultsPath = "", requestPath = "", ackPath = "", exitPath = "";

    public override void Entry(IModHelper helper)
    {
        commandsPath = Path.Combine(helper.DirectoryPath, "harness-commands.json");
        resultsPath = Path.Combine(helper.DirectoryPath, "harness-results.json");
        requestPath = Path.Combine(helper.DirectoryPath, "harness-request.json");
        ackPath = Path.Combine(helper.DirectoryPath, "harness-ack.json");
        exitPath = Path.Combine(helper.DirectoryPath, "harness-exit");
        helper.Events.GameLoop.GameLaunched += (_, _) => Load();
        helper.Events.GameLoop.UpdateTicked += OnTick;
    }

    // ------------------------------------------------------------------ setup
    private void Load()
    {
        if (!File.Exists(commandsPath))
        {
            Monitor.Log("harness-commands.json not found: harness stays dormant.", LogLevel.Trace);
            return;
        }
        try
        {
            script = JsonSerializer.Deserialize<Script>(File.ReadAllText(commandsPath), Json) ?? new Script();
        }
        catch (Exception ex)
        {
            Fail("could not read harness-commands.json: " + ex.Message);
            return;
        }
        File.Delete(exitPath);
        File.Delete(requestPath);
        File.Delete(ackPath);
        started = DateTime.UtcNow;
        if (!SavePolicy.IsTestSave(script.Save, script.SavePrefix))
        {
            Fail($"refusing: save '{script.Save}' does not start with the test prefix '{script.SavePrefix}' (min. 4 characters). No other save is ever loaded.");
            return;
        }
        Monitor.Log($"[harness] script with {script.Steps.Count} step(s) for test save '{script.Save}'.", LogLevel.Info);
        phase = Phase.WaitTitle;
        WriteResults();
    }

    private void Fail(string message)
    {
        Monitor.Log("[harness] " + message, LogLevel.Error);
        errors.Add(message);
        phase = Phase.Finished;
        WriteResults();
        RenameCommands();
    }

    private void RenameCommands()
    {
        try { if (File.Exists(commandsPath)) File.Move(commandsPath, commandsPath + ".done", true); } catch { /* best effort */ }
    }

    private void WriteResults()
    {
        var payload = new
        {
            state = phase.ToString(),
            save = script.Save,
            started = started == default ? null : started.ToString("o"),
            finished = phase == Phase.Finished,
            ok = phase == Phase.Finished && errors.Count == 0 && results.All(r => r.Ok),
            steps = results,
            errors,
            stepCount = script.Steps.Count,
            currentStep = stepIndex,
        };
        File.WriteAllText(resultsPath, JsonSerializer.Serialize(payload, Json));
    }

    // ------------------------------------------------------------------ state machine
    private void OnTick(object? sender, UpdateTickedEventArgs e)
    {
        if (phase == Phase.Dormant)
            return;
        if (phase == Phase.Finished)
        {
            if (e.IsMultipleOf(60) && (script.ExitWhenDone || File.Exists(exitPath)))
            {
                Monitor.Log("[harness] closing the game.", LogLevel.Info);
                Game1.game1.Exit();
            }
            return;
        }
        if ((DateTime.UtcNow - started).TotalSeconds > script.TimeoutSeconds)
        {
            Fail($"timed out after {script.TimeoutSeconds}s in phase {phase}");
            return;
        }
        try
        {
            switch (phase)
            {
                case Phase.WaitTitle: TickTitle(); break;
                case Phase.WaitSlots: TickSlots(); break;
                case Phase.Loading: TickLoading(); break;
                case Phase.Running: TickSteps(); break;
            }
        }
        catch (Exception ex)
        {
            Fail($"exception in {phase}: {ex}");
        }
    }

    private void TickTitle()
    {
        if (Game1.activeClickableMenu is not TitleMenu title)
            return;
        if (!title.titleInPosition)
        {
            if (!skippedIntro) { title.skipToTitleButtons(); skippedIntro = true; }
            return;
        }
        loadMenu = new LoadGameMenu(null);
        TitleMenu.subMenu = loadMenu;
        stepTicks = 0;
        phase = Phase.WaitSlots;
    }

    private void TickSlots()
    {
        if (loadMenu is null)
        {
            phase = Phase.WaitTitle;
            return;
        }
        if (++stepTicks > 900)
        {
            Fail($"test save '{script.Save}' not found in the load menu. Create a farm whose farmer name starts with '{script.SavePrefix}' once, then re-run.");
            return;
        }
        var slots = loadMenu.MenuSlots;
        if (slots is null || slots.Count == 0)
            return;
        var slot = slots.OfType<LoadGameMenu.SaveFileSlot>().FirstOrDefault(s => s.Farmer?.slotName == script.Save);
        if (slot is null)
            return;
        if (!SavePolicy.IsTestSave(slot.Farmer.slotName, script.SavePrefix))   // second, independent check right before the load
        {
            Fail("refusing to load a non-test save.");
            return;
        }
        Monitor.Log($"[harness] loading '{slot.Farmer.slotName}'.", LogLevel.Info);
        slot.Activate();
        phase = Phase.Loading;
    }

    private void TickLoading()
    {
        if (!Context.IsWorldReady)
            return;
        if (!SavePolicy.IsTestSave(Constants.SaveFolderName, script.SavePrefix))       // last line of defence
        {
            Fail($"loaded save '{Constants.SaveFolderName}' is not a test save; closing without saving.");
            Game1.game1.Exit();
            return;
        }
        Monitor.Log("[harness] world ready; running steps.", LogLevel.Info);
        phase = Phase.Running;
        stepIndex = -1;
        stepStarted = false;
    }

    private void TickSteps()
    {
        if (!stepStarted)
        {
            stepIndex++;
            if (stepIndex >= script.Steps.Count)
            {
                phase = Phase.Finished;
                Monitor.Log("[harness] all steps done.", LogLevel.Info);
                WriteResults();
                RenameCommands();
                return;
            }
            stepStarted = true;
            stepTicks = 0;
            waitTicks = 0;
            requestSeq = 0;
        }
        var step = script.Steps[stepIndex];
        stepTicks++;
        StepResult? done = Run(step);
        if (done is null)
            return;                                         // still running; called again next tick
        done.Index = stepIndex;
        done.Type = step.Type;
        results.Add(done);
        Monitor.Log($"[harness] step {stepIndex} {step.Type}: {(done.Ok ? "ok" : "FAILED " + done.Error)}", done.Ok ? LogLevel.Info : LogLevel.Warn);
        stepStarted = false;
        WriteResults();
    }

    // ------------------------------------------------------------------ steps (null = not finished yet)
    private StepResult? Run(Step s)
    {
        StepResult Ok(string? info = null) => new() { Ok = true, Info = info };
        StepResult Bad(string error) => new() { Ok = false, Error = error };
        if (stepTicks > 3600)
            return Bad("step timed out");

        switch (s.Type.ToLowerInvariant())
        {
            case "warp":
                if (stepTicks == 1)
                {
                    if (string.IsNullOrEmpty(s.Location))
                        return Bad("warp needs location");
                    Game1.warpFarmer(s.Location, s.X, s.Y, 2);
                    return null;
                }
                if (Game1.currentLocation?.NameOrUniqueName == s.Location && !Game1.IsFading())
                    return Ok($"at {s.Location} {Game1.player.TilePoint.X},{Game1.player.TilePoint.Y}");
                return null;

            case "time":
                Game1.timeOfDay = s.Value;
                return Ok();

            case "debug":
                if (string.IsNullOrWhiteSpace(s.Command))
                    return Bad("debug needs command");
                var parts = s.Command.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                return DebugCommands.TryHandle(parts, new MonitorLogger(Monitor)) ? Ok(s.Command) : Bad("game did not recognise debug command: " + s.Command);

            case "give":
                var item = ItemRegistry.Create(s.Item, Math.Max(1, s.Count), 0, true);
                if (item is null)
                    return Bad($"unknown item id '{s.Item}'");
                Game1.player.addItemByMenuIfNecessary(item);
                return Ok(item.QualifiedItemId);

            case "wait":
                return stepTicks >= Math.Max(1, s.Ticks) ? Ok() : null;

            case "dialogue":
                if (stepTicks == 1)
                {
                    var npc = Game1.getCharacterFromName(s.Npc ?? "");
                    if (npc is null)
                        return Bad($"npc '{s.Npc}' not found");
                    if (npc.CurrentDialogue.Count == 0)
                        return Bad($"npc '{s.Npc}' has no current dialogue today");
                    Game1.DrawDialogue(npc.CurrentDialogue.Peek());
                    return null;
                }
                return stepTicks >= 20 ? Ok() : null;

            case "assert_location":
                return Game1.currentLocation?.NameOrUniqueName == s.Location ? Ok() : Bad($"in '{Game1.currentLocation?.NameOrUniqueName}', expected '{s.Location}'");

            case "map_screenshot":
                var path = Game1.game1.takeMapScreenshot(0.25f, s.Name ?? "harness_map", null);
                return Ok(path);

            case "screenshot":     // window screenshots (with menus and dialogue boxes) are taken by game.py on request
            case "console":        // SMAPI console commands (patch summary, ...) are typed into the console by game.py
                return Handshake(s);

            default:
                return Bad("unknown step type '" + s.Type + "'");
        }
    }

    private StepResult? Handshake(Step s)
    {
        if (requestSeq == 0)
        {
            if (stepTicks < 20 && s.Type == "screenshot")
                return null;                                // let the frame settle before asking for a picture
            requestSeq = stepIndex + 1;
            File.Delete(ackPath);
            File.WriteAllText(requestPath, JsonSerializer.Serialize(new { seq = requestSeq, type = s.Type, name = s.Name, command = s.Command }, Json));
            waitTicks = 0;
            return null;
        }
        if (++waitTicks % 10 == 0 && File.Exists(ackPath))
        {
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(ackPath));
                if (doc.RootElement.TryGetProperty("seq", out var seq) && seq.GetInt32() == requestSeq)
                {
                    bool ok = !doc.RootElement.TryGetProperty("ok", out var okEl) || okEl.GetBoolean();
                    string? msg = doc.RootElement.TryGetProperty("message", out var m) ? m.GetString() : null;
                    return new StepResult { Ok = ok, Info = ok ? msg : null, Error = ok ? null : msg ?? "game.py reported failure" };
                }
            }
            catch (IOException) { /* being written */ }
            catch (JsonException) { /* being written */ }
        }
        if (waitTicks > 60 * 25)
            return new StepResult { Ok = false, Error = "no answer from game.py (start the game with game.py test so it can take screenshots / send console commands)" };
        return null;
    }

    private sealed class MonitorLogger : IGameLogger
    {
        private readonly IMonitor monitor;
        public MonitorLogger(IMonitor monitor) => this.monitor = monitor;
        public void Verbose(string message) => monitor.Log(message, LogLevel.Trace);
        public void Debug(string message) => monitor.Log(message, LogLevel.Debug);
        public void Info(string message) => monitor.Log(message, LogLevel.Info);
        public void Warn(string message) => monitor.Log(message, LogLevel.Warn);
        public void Error(string error, Exception? exception = null) => monitor.Log(exception is null ? error : error + ": " + exception.Message, LogLevel.Error);
    }
}
