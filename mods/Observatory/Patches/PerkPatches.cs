using System;
using System.Collections.Generic;
using HarmonyLib;
using Microsoft.Xna.Framework;
using Observatory.Framework;
using StardewModdingAPI;
using StardewValley;
using SObject = StardewValley.Object;

namespace Observatory.Patches;

/// <summary>Harmony patches for perks that hook game code. Every patch fails soft: if a target method is missing, that perk is disabled and logged.</summary>
internal static class PerkPatches
{
    private static IMonitor Monitor = null!;

    /// <summary>Ore node (stone) ID → ore item.</summary>
    private static readonly Dictionary<string, string> OreByNode = new()
    {
        ["751"] = "(O)378", ["849"] = "(O)378", // copper
        ["290"] = "(O)380", ["850"] = "(O)380", // iron
        ["764"] = "(O)384",                     // gold
        ["765"] = "(O)386",                     // iridium
        ["95"] = "(O)909",                      // radioactive
    };

    /// <summary>Fractional XP carried between gains, so +5% works on small XP amounts too.</summary>
    private static readonly Dictionary<(long, int), float> XpRemainder = new();

    public static void Apply(Harmony harmony, IMonitor monitor)
    {
        Monitor = monitor;
        Patch(harmony, "The Pickaxe (extra ore)",
            AccessTools.Method(typeof(GameLocation), "OnStoneDestroyed"),
            postfix: nameof(OnStoneDestroyed_Postfix));
        Patch(harmony, "The Hearth (cooked energy)",
            AccessTools.Method(typeof(SObject), nameof(SObject.staminaRecoveredAmount)),
            postfix: nameof(StaminaRecovered_Postfix));
        Patch(harmony, "The Old Farmer (skill XP)",
            AccessTools.Method(typeof(Farmer), nameof(Farmer.gainExperience)),
            prefix: nameof(GainExperience_Prefix));
    }

    private static void Patch(Harmony harmony, string label, System.Reflection.MethodBase? target, string? prefix = null, string? postfix = null)
    {
        if (target is null)
        {
            Monitor.Log($"Couldn't find the game method for {label}; that perk is disabled.", LogLevel.Warn);
            return;
        }
        harmony.Patch(target,
            prefix: prefix is null ? null : new HarmonyMethod(typeof(PerkPatches), prefix),
            postfix: postfix is null ? null : new HarmonyMethod(typeof(PerkPatches), postfix));
    }

    // The Pickaxe
    private static void OnStoneDestroyed_Postfix(GameLocation __instance, string stoneId, int x, int y, Farmer who)
    {
        try
        {
            if (who is null || stoneId is null || !OreByNode.TryGetValue(stoneId, out var ore))
                return;
            float chance = Perks.Value(who, PerkIds.ExtraOre);
            if (chance <= 0 || Game1.random.NextDouble() >= chance)
                return;
            Game1.createItemDebris(ItemRegistry.Create(ore), new Vector2(x * 64 + 32, y * 64 + 32), Game1.random.Next(4), __instance);
        }
        catch (Exception ex)
        {
            Monitor.Log($"Extra ore patch failed:\n{ex}", LogLevel.Error);
        }
    }

    // The Hearth
    private static void StaminaRecovered_Postfix(SObject __instance, ref int __result)
    {
        try
        {
            if (__result <= 0 || __instance.Category != SObject.CookingCategory)
                return;
            float bonus = Perks.Value(Game1.player, PerkIds.CookedEnergy);
            if (bonus > 0)
                __result = (int)Math.Round(__result * (1f + bonus));
        }
        catch (Exception ex)
        {
            Monitor.Log($"Cooked energy patch failed:\n{ex}", LogLevel.Error);
        }
    }

    // The Old Farmer
    private static void GainExperience_Prefix(Farmer __instance, int which, ref int howMuch)
    {
        try
        {
            if (howMuch <= 0)
                return;
            float bonus = Perks.Value(__instance, PerkIds.SkillXp);
            if (bonus <= 0)
                return;
            var key = (__instance.UniqueMultiplayerID, which);
            XpRemainder.TryGetValue(key, out float carry);
            float extra = howMuch * bonus + carry;
            int whole = (int)extra;
            XpRemainder[key] = extra - whole;
            howMuch += whole;
        }
        catch (Exception ex)
        {
            Monitor.Log($"Skill XP patch failed:\n{ex}", LogLevel.Error);
        }
    }
}
