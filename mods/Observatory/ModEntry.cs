using System;
using System.Collections.Generic;
using System.Linq;
using HarmonyLib;
using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using Observatory.Framework;
using Observatory.Menus;
using Observatory.Patches;
using StardewModdingAPI;
using StardewModdingAPI.Events;
using StardewValley;

namespace Observatory;

internal sealed class ModEntry : Mod
{
    private ModConfig Config = null!;
    private WorldHooks World = null!;

    public override void Entry(IModHelper helper)
    {
        Config = helper.ReadConfig<ModConfig>();
        Text.Translation = helper.Translation;
        Progress.Helper = helper;
        Perks.Config = Config;
        Ui.Helper = helper;
        World = new WorldHooks(helper, Monitor, Config);

        helper.Events.Content.AssetRequested += OnAssetRequested;
        helper.Events.GameLoop.GameLaunched += OnGameLaunched;
        helper.Events.GameLoop.DayStarted += OnDayStarted;
        helper.Events.GameLoop.DayEnding += OnDayEnding;
        helper.Events.GameLoop.OneSecondUpdateTicked += OnOneSecondUpdateTicked;
        helper.Events.Player.Warped += OnWarped;
        helper.Events.Display.MenuChanged += (_, e) => World.OnMenuChanged(e.NewMenu);

        PerkPatches.Apply(new Harmony(ModManifest.UniqueID), Monitor);
        RegisterCommands();
    }

    // ------------------------------------------------------------------ assets
    private void OnAssetRequested(object? sender, AssetRequestedEventArgs e)
    {
        if (e.NameWithoutLocale.IsEquivalentTo(Ids.ConstellationsAsset))
            e.LoadFromModFile<Dictionary<string, ConstellationData>>("assets/constellations.json", AssetLoadPriority.Exclusive);
        else if (e.NameWithoutLocale.IsEquivalentTo(Ids.StarChartsAsset))
            e.LoadFromModFile<Dictionary<string, StarChartData>>("assets/starcharts.json", AssetLoadPriority.Exclusive);
        else if (e.NameWithoutLocale.IsEquivalentTo(Ids.UiTextureAsset))
            e.LoadFromModFile<Texture2D>("assets/ui.png", AssetLoadPriority.Exclusive);
    }

    // ------------------------------------------------------------------ lifecycle
    private void OnGameLaunched(object? sender, GameLaunchedEventArgs e)
    {
        // tile actions placed on the observatory map by the [CP] pack: "Action Inyourfacer.Observatory_Telescope"
        GameLocation.RegisterTileAction(Ids.TelescopeAction, (_, _, who, _) => OpenIfLocal(who, () => new TelescopeMenu(Config)));
        GameLocation.RegisterTileAction(Ids.StarChartAction, (_, _, who, _) => OpenIfLocal(who, () => new StarChartBoardMenu()));
        GameLocation.RegisterTileAction(Ids.JournalAction, (_, _, who, _) => OpenIfLocal(who, () => new StarJournalMenu()));

        if (!Helper.ModRegistry.IsLoaded(Ids.Prefix + ".CP"))
            Monitor.Log("The [CP] Observatory content pack isn't installed; the observatory building, mail and events won't exist.", LogLevel.Warn);
    }

    private static bool OpenIfLocal(Farmer who, Func<StardewValley.Menus.IClickableMenu> menu)
    {
        if (!who.IsLocalPlayer)
            return false;
        Game1.activeClickableMenu = menu();
        return true;
    }

    private void OnDayStarted(object? sender, DayStartedEventArgs e)
    {
        World.UpdateConstruction();
        World.ApplyJunimoRadius();
    }

    private void OnDayEnding(object? sender, DayEndingEventArgs e) => World.ApplyCropGrowth();

    private void OnOneSecondUpdateTicked(object? sender, OneSecondUpdateTickedEventArgs e)
    {
        if (Context.IsPlayerFree)
            World.CheckRevealSpots();
    }

    private void OnWarped(object? sender, WarpedEventArgs e)
    {
        if (e.IsLocalPlayer)
            World.OnWarped(e.NewLocation);
    }

    // ------------------------------------------------------------------ console commands (testing)
    private void RegisterCommands()
    {
        var c = Helper.ConsoleCommands;
        c.Add("obs_status", "Show observatory progress for the current player.", (_, _) => Status());
        c.Add("obs_build", "Finish construction now (host).", (_, _) =>
        {
            if (!Ready(host: true)) return;
            World.FinishConstruction();
        });
        c.Add("obs_riddle", "obs_riddle <id|all>: learn a constellation's riddle.", (_, a) => ForEach(a, (id, d) => Progress.LearnRiddle(Game1.player, id, d, showLetter: false)));
        c.Add("obs_reveal", "obs_reveal <id|all>: reveal a constellation's coordinates.", (_, a) => ForEach(a, (id, d) => Progress.RevealCoords(Game1.player, id, d)));
        c.Add("obs_complete", "obs_complete <id|all>: chart a constellation and grant its perk.", (_, a) => ForEach(a, (id, d) => Progress.Complete(Game1.player, id, d)));
        c.Add("obs_puzzle", "obs_puzzle <id>: open the star puzzle for a constellation.", (_, a) =>
        {
            if (!Ready() || a.Length == 0 || !Progress.Constellations.TryGetValue(a[0], out var d)) { Monitor.Log("Usage: obs_puzzle <id>", LogLevel.Info); return; }
            Game1.activeClickableMenu = new StarPuzzleMenu(a[0], d);
        });
        c.Add("obs_reset", "obs_reset <id|all>: forget a constellation (riddle, coordinates, perk).", (_, a) => ForEach(a, (id, d) => Progress.Reset(Game1.player, id, d)));
    }

    private bool Ready(bool host = false)
    {
        if (!Context.IsWorldReady) { Monitor.Log("Load a save first.", LogLevel.Info); return false; }
        if (host && !Context.IsMainPlayer) { Monitor.Log("Only the host can do that.", LogLevel.Info); return false; }
        return true;
    }

    private void ForEach(string[] args, Action<string, ConstellationData> action)
    {
        if (!Ready()) return;
        var all = Progress.Constellations;
        if (args.Length == 0) { Monitor.Log($"Specify an ID or 'all'. IDs: {string.Join(", ", all.Keys)}", LogLevel.Info); return; }
        var ids = args[0] == "all" ? all.Keys.ToList() : args.Where(all.ContainsKey).ToList();
        if (ids.Count == 0) { Monitor.Log($"Unknown ID. IDs: {string.Join(", ", all.Keys)}", LogLevel.Info); return; }
        foreach (var id in ids) action(id, all[id]);
        Monitor.Log($"Done: {string.Join(", ", ids)}", LogLevel.Info);
    }

    private void Status()
    {
        if (!Ready()) return;
        var host = Game1.MasterPlayer;
        string build = host.mailReceived.Contains(Ids.Built) ? "built"
            : host.modData.TryGetValue(Ids.ConstructionStartDayKey, out var start) ? $"under construction since day {start}"
            : "locked";
        Monitor.Log($"Observatory: {build}", LogLevel.Info);
        foreach (var (id, d) in Progress.Ordered)
        {
            var p = Game1.player;
            Monitor.Log($"  {id,-10} riddle={Progress.KnowsRiddle(p, id),-5} coords={Progress.KnowsCoords(p, id),-5} done={Progress.IsDone(p, id),-5} " +
                        $"@ {d.RightAscension:00}h {d.Declination:+0;-0}°  perk={d.Perk} {d.PerkValue}", LogLevel.Info);
        }
    }
}
