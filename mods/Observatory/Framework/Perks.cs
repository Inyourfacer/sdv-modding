using System.Linq;
using StardewValley;

namespace Observatory.Framework;

/// <summary>Sums perk values from a farmer's completed constellations. Perks stack with professions.</summary>
internal static class Perks
{
    public static ModConfig Config = null!;

    public static float Value(Farmer? who, string perk)
    {
        if (who is null || !Config.EnablePerks)
            return 0f;
        float total = 0f;
        foreach (var (id, data) in Progress.Constellations)
            if (data.Perk == perk && Progress.IsDone(who, id))
                total += data.PerkValue;
        return total;
    }

    /// <summary>For shared-world perks (crops, Junimo huts): the best value among all farmers.</summary>
    public static float WorldValue(string perk) =>
        Game1.getAllFarmers().Select(f => Value(f, perk)).DefaultIfEmpty(0f).Max();
}
