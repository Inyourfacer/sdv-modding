using System;
using Microsoft.Xna.Framework;
using StardewModdingAPI;
using StardewValley;
using StardewValley.Buildings;
using StardewValley.Menus;
using StardewValley.Objects;
using StardewValley.TerrainFeatures;

namespace Observatory.Framework;

/// <summary>Construction timer, riddle sources, reveal spots, and the perks that don't need Harmony.</summary>
internal sealed class WorldHooks
{
    private const int BaseJunimoRadius = 8;

    private readonly IModHelper Helper;
    private readonly IMonitor Monitor;
    private readonly ModConfig Config;

    public WorldHooks(IModHelper helper, IMonitor monitor, ModConfig config)
    {
        Helper = helper;
        Monitor = monitor;
        Config = config;
    }

    // ------------------------------------------------------------------ unlock & construction (host)
    /// <summary>Unlock = Maru's letter read (any player) or the town project special order done. Robin then builds for N days.</summary>
    public void UpdateConstruction()
    {
        if (!Context.IsMainPlayer)
            return;
        var host = Game1.MasterPlayer;
        if (host.mailReceived.Contains(Ids.Built))
            return;

        bool unlocked = host.mailReceived.Contains(Ids.TownProjectDone);
        foreach (var f in Game1.getAllFarmers())
            unlocked |= f.mailReceived.Contains(Ids.MaruLetter);
        if (!unlocked)
            return;

        int today = Game1.Date.TotalDays;
        if (!host.modData.TryGetValue(Ids.ConstructionStartDayKey, out var raw) || !int.TryParse(raw, out int start))
        {
            host.modData[Ids.ConstructionStartDayKey] = today.ToString();
            host.mailReceived.Add(Ids.ConstructionStarted);
            Game1.addHUDMessage(new HUDMessage(Text.Get("construction.started", new { days = Config.ConstructionDays }), HUDMessage.newQuest_type));
            Monitor.Log($"Observatory construction started on day {today}.", LogLevel.Debug);
            return;
        }

        if (today - start >= Config.ConstructionDays)
            FinishConstruction();
    }

    public void FinishConstruction()
    {
        Game1.MasterPlayer.mailReceived.Add(Ids.ConstructionStarted);
        Game1.MasterPlayer.mailReceived.Add(Ids.Built);
        // the [CP] pack's Backwoods edit is conditioned on this flag; refresh so it shows without a day change
        Helper.GameContent.InvalidateCache("Maps/Backwoods");
        Game1.addHUDMessage(new HUDMessage(Text.Get("construction.finished"), HUDMessage.newQuest_type));
        Monitor.Log("Observatory construction finished.", LogLevel.Debug);
    }

    // ------------------------------------------------------------------ riddles
    /// <summary>Riddles of type "Warp": found the first time the player enters a location (e.g. mines floor 40).</summary>
    public void OnWarped(GameLocation newLocation)
    {
        if (!Progress.IsBuilt)
            return;
        string name = newLocation.NameOrUniqueName;
        foreach (var (id, data) in Progress.Ordered)
        {
            var src = data.RiddleSource;
            if (src is null || src.Type != "Warp" || !string.Equals(src.Location, name, StringComparison.OrdinalIgnoreCase))
                continue;
            if (Progress.KnowsRiddle(Game1.player, id) || Progress.KnowsCoords(Game1.player, id))
                continue;
            if (!string.IsNullOrEmpty(src.Condition) && !GameStateQuery.CheckConditions(src.Condition, newLocation, Game1.player))
                continue;
            // delay one tick so the warp fade doesn't eat the letter
            DelayedAction.functionAfterDelay(() => Progress.LearnRiddle(Game1.player, id, data, showLetter: true), 600);
        }
    }

    /// <summary>Stand where a known riddle points and the coordinates are revealed.</summary>
    public void CheckRevealSpots()
    {
        if (!Progress.IsBuilt || Game1.eventUp || Game1.activeClickableMenu != null)
            return;
        var who = Game1.player;
        var loc = who.currentLocation;
        if (loc is null)
            return;

        foreach (var (id, data) in Progress.Constellations)
        {
            var spot = data.RevealSpot;
            if (spot is null || Progress.KnowsCoords(who, id))
                continue;
            if (!string.IsNullOrEmpty(data.Riddle) && !Progress.KnowsRiddle(who, id))
                continue;
            if (!string.Equals(spot.Location, loc.NameOrUniqueName, StringComparison.OrdinalIgnoreCase))
                continue;
            if (spot.Tile is Point tile)
            {
                if (tile.X < 0)
                    tile = GrandpaShrineTile(loc);
                var p = who.TilePoint;
                if (Math.Abs(p.X - tile.X) > spot.Radius || Math.Abs(p.Y - tile.Y) > spot.Radius)
                    continue;
            }
            if (!string.IsNullOrEmpty(spot.Condition) && !GameStateQuery.CheckConditions(spot.Condition, loc, who))
                continue;

            Progress.RevealCoords(who, id, data);
        }
    }

    private Point GrandpaShrineTile(GameLocation loc)
    {
        if (loc is Farm farm)
        {
            var method = Helper.Reflection.GetMethod(farm, "GetGrandpaShrinePosition", required: false);
            if (method != null)
                return method.Invoke<Point>();
        }
        return new Point(8, 7); // standard farm layout
    }

    // ------------------------------------------------------------------ perks without Harmony
    /// <summary>The Sprout: before the overnight update, each watered crop may advance one extra day. Host only.</summary>
    public void ApplyCropGrowth()
    {
        if (!Context.IsMainPlayer)
            return;
        float chance = Perks.WorldValue(PerkIds.CropGrowth);
        if (chance <= 0)
            return;

        int boosted = 0;
        Utility.ForEachLocation(loc =>
        {
            foreach (var feature in loc.terrainFeatures.Values)
                if (feature is HoeDirt dirt && TryBoost(dirt, chance))
                    boosted++;
            foreach (var obj in loc.objects.Values)
                if (obj is IndoorPot pot && pot.hoeDirt.Value is HoeDirt potDirt && TryBoost(potDirt, chance))
                    boosted++;
            return true;
        });
        Monitor.Log($"The Sprout: {boosted} crops grew an extra day.", LogLevel.Trace);
    }

    /// <summary>Mirrors the growth step in <c>Crop.newDay</c> for a watered, still-growing crop.</summary>
    private static bool TryBoost(HoeDirt dirt, float chance)
    {
        var crop = dirt.crop;
        if (crop is null || crop.dead.Value || crop.fullyGrown.Value || dirt.state.Value != HoeDirt.watered)
            return false;
        var phases = crop.phaseDays;
        if (phases.Count == 0 || crop.currentPhase.Value >= phases.Count - 1)
            return false;
        if (Game1.random.NextDouble() >= chance)
            return false;

        crop.dayOfCurrentPhase.Value = Math.Min(crop.dayOfCurrentPhase.Value + 1, phases[crop.currentPhase.Value]);
        if (crop.dayOfCurrentPhase.Value >= phases[crop.currentPhase.Value])
        {
            crop.currentPhase.Value++;
            crop.dayOfCurrentPhase.Value = 0;
        }
        while (crop.currentPhase.Value < phases.Count - 1 && phases[crop.currentPhase.Value] <= 0)
            crop.currentPhase.Value++;
        return true;
    }

    /// <summary>The Junimo: widen every Junimo hut's harvest radius. Host only; reapplied each morning.</summary>
    public void ApplyJunimoRadius()
    {
        if (!Context.IsMainPlayer)
            return;
        int radius = BaseJunimoRadius + (int)Perks.WorldValue(PerkIds.JunimoRadius);
        Utility.ForEachBuilding(building =>
        {
            if (building is JunimoHut hut)
            {
                var field = Helper.Reflection.GetField<int>(hut, "cropHarvestRadius", required: false);
                field?.SetValue(radius);
            }
            return true;
        });
    }

    /// <summary>The Angler: enlarge the fishing bar when the minigame opens.</summary>
    public void OnMenuChanged(IClickableMenu? newMenu)
    {
        if (newMenu is not BobberBar bar)
            return;
        float bonus = Perks.Value(Game1.player, PerkIds.FishingBar);
        if (bonus <= 0)
            return;

        var height = Helper.Reflection.GetField<int>(bar, "bobberBarHeight");
        var pos = Helper.Reflection.GetField<float>(bar, "bobberBarPos");
        int oldHeight = height.GetValue();
        int newHeight = (int)Math.Round(oldHeight * (1f + bonus));
        height.SetValue(newHeight);
        // keep the bar resting on the bottom of the track
        pos.SetValue(Math.Max(0f, pos.GetValue() - (newHeight - oldHeight)));
    }
}
