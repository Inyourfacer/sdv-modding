using System.Collections.Generic;
using System.Linq;
using StardewModdingAPI;
using StardewValley;

namespace Observatory.Framework;

/// <summary>Reads data assets and the player's progress. Progress is stored as mail flags on each farmer, so it's per-player,
/// synced in multiplayer, saved with the game, and readable from Content Patcher (<c>HasFlag</c>) and game state queries.</summary>
internal static class Progress
{
    public static IModHelper Helper = null!;

    public static Dictionary<string, ConstellationData> Constellations =>
        Helper.GameContent.Load<Dictionary<string, ConstellationData>>(Ids.ConstellationsAsset);

    public static Dictionary<string, StarChartData> StarCharts =>
        Helper.GameContent.Load<Dictionary<string, StarChartData>>(Ids.StarChartsAsset);

    public static IEnumerable<KeyValuePair<string, ConstellationData>> Ordered =>
        Constellations.OrderBy(p => p.Value.SortOrder).ThenBy(p => p.Key);

    public static bool IsBuilt => Game1.MasterPlayer?.mailReceived.Contains(Ids.Built) == true;

    public static bool KnowsRiddle(Farmer who, string id) => who.mailReceived.Contains(Ids.RiddleFlag(id));
    public static bool KnowsCoords(Farmer who, string id) => who.mailReceived.Contains(Ids.CoordsFlag(id));
    public static bool IsDone(Farmer who, string id) => who.mailReceived.Contains(Ids.DoneFlag(id));

    /// <summary>Add a mail flag; true if it wasn't already set.</summary>
    public static bool AddFlag(Farmer who, string flag)
    {
        if (who.mailReceived.Contains(flag))
            return false;
        who.mailReceived.Add(flag);
        return true;
    }

    public static int DoneCount(Farmer who) => Constellations.Keys.Count(id => IsDone(who, id));
    public static bool AllDone(Farmer who) => Constellations.Count > 0 && Constellations.Keys.All(id => IsDone(who, id));

    public static void LearnRiddle(Farmer who, string id, ConstellationData data, bool showLetter)
    {
        if (!AddFlag(who, Ids.RiddleFlag(id)))
            return;
        if (showLetter && who.IsLocalPlayer && !string.IsNullOrEmpty(data.Riddle))
            Game1.activeClickableMenu = new StardewValley.Menus.LetterViewerMenu(
                Text.Get("riddle.found", new { riddle = Text.Get(data.Riddle) }));
    }

    public static void RevealCoords(Farmer who, string id, ConstellationData data, bool announce = true)
    {
        if (!AddFlag(who, Ids.CoordsFlag(id)))
            return;
        if (announce && who.IsLocalPlayer)
        {
            Game1.playSound("newArtifact");
            Game1.addHUDMessage(new HUDMessage(Text.Get("coords.revealed", new
            {
                name = Text.Get(data.DisplayName),
                coords = FormatCoords(data.RightAscension, data.Declination)
            }), HUDMessage.newQuest_type));
        }
    }

    /// <summary>Record a solved constellation and apply one-time perk effects.</summary>
    public static void Complete(Farmer who, string id, ConstellationData data)
    {
        who.mailReceived.Add(Ids.CoordsFlag(id));
        if (!AddFlag(who, Ids.DoneFlag(id)))
            return;

        if (data.Perk == PerkIds.MaxEnergy)
        {
            who.maxStamina.Value += (int)data.PerkValue;
            who.Stamina = who.MaxStamina;
        }

        if (who.IsLocalPlayer)
        {
            Game1.playSound("achievement");
            Game1.addHUDMessage(new HUDMessage(Text.Get("constellation.complete", new
            {
                name = Text.Get(data.DisplayName),
                perk = Text.Get(data.PerkText)
            }), HUDMessage.achievement_type));
        }
    }

    /// <summary>Undo a constellation (debug command).</summary>
    public static void Reset(Farmer who, string id, ConstellationData data)
    {
        if (IsDone(who, id) && data.Perk == PerkIds.MaxEnergy)
            who.maxStamina.Value -= (int)data.PerkValue;
        who.mailReceived.Remove(Ids.DoneFlag(id));
        who.mailReceived.Remove(Ids.CoordsFlag(id));
        who.mailReceived.Remove(Ids.RiddleFlag(id));
    }

    public static string FormatCoords(int ra, int dec) =>
        Text.Get("coords.format", new { ra = ra.ToString("00"), dec = (dec >= 0 ? "+" : "") + dec });

    // ---- star-chart bundles (per player, modData: comma-separated donated item IDs)
    public static HashSet<string> Donated(Farmer who, string bundleId) =>
        who.modData.TryGetValue(Ids.BundleKey(bundleId), out var raw) && !string.IsNullOrEmpty(raw)
            ? raw.Split(',').ToHashSet()
            : new HashSet<string>();

    public static void SetDonated(Farmer who, string bundleId, HashSet<string> items) =>
        who.modData[Ids.BundleKey(bundleId)] = string.Join(",", items);

    public static bool BundleComplete(Farmer who, string bundleId, StarChartData data) =>
        Donated(who, bundleId).Count >= data.Required;
}
