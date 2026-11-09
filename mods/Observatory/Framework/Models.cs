using System.Collections.Generic;
using Microsoft.Xna.Framework;

namespace Observatory.Framework;

/// <summary>How the faint outline behaves in the star puzzle.</summary>
public enum OutlineMode
{
    /// <summary>Outline stays visible (early constellations).</summary>
    Visible,
    /// <summary>Outline visible for <see cref="ConstellationData.OutlineFadeSeconds"/>, then gone (mid-game).</summary>
    Fades,
    /// <summary>No outline; the player works from <see cref="ConstellationData.ShapeRiddle"/> (late game).</summary>
    None
}

/// <summary>One entry in <c>Mods/Inyourfacer.Observatory/Constellations</c>. Text fields are i18n keys or literal text.</summary>
public sealed class ConstellationData
{
    public string DisplayName { get; set; } = "";
    public string Description { get; set; } = "";
    public int SortOrder { get; set; }

    /// <summary>Telescope coordinates. Right ascension in hours (0-23), declination in degrees (multiple of 10, -80..80).</summary>
    public int RightAscension { get; set; }
    public int Declination { get; set; }

    /// <summary>Riddle text (shown in the journal once the riddle is known). Null for bundle/event sources.</summary>
    public string? Riddle { get; set; }

    /// <summary>Short journal hint shown before anything is known ("Ask Maru", "Star-chart board").</summary>
    public string SourceHint { get; set; } = "";

    /// <summary>Where the player learns the riddle. Null when the riddle comes from mail/events/dialogue (they set the riddle flag themselves).</summary>
    public RiddleSourceData? RiddleSource { get; set; }

    /// <summary>The place the riddle points to. Standing there reveals the coordinates. Null when coordinates come from a bundle or event.</summary>
    public RevealSpotData? RevealSpot { get; set; }

    // ---- puzzle
    /// <summary>Star positions, normalized 0..1 inside the puzzle square.</summary>
    public List<Vector2> Stars { get; set; } = new();
    /// <summary>Lines the player must draw, as pairs of indices into <see cref="Stars"/>.</summary>
    public List<int[]> Lines { get; set; } = new();
    public int Decoys { get; set; }
    public OutlineMode Outline { get; set; } = OutlineMode.Visible;
    public float OutlineFadeSeconds { get; set; } = 5f;
    /// <summary>Text describing the shape, shown when <see cref="Outline"/> is None.</summary>
    public string? ShapeRiddle { get; set; }

    // ---- reward
    /// <summary>One of the IDs in <see cref="PerkIds"/>.</summary>
    public string Perk { get; set; } = "";
    public float PerkValue { get; set; }
    public string PerkText { get; set; } = "";
}

public sealed class RiddleSourceData
{
    /// <summary>"Warp": learned the first time the player enters <see cref="Location"/>.</summary>
    public string Type { get; set; } = "Warp";
    public string Location { get; set; } = "";
    /// <summary>Optional game state query that must pass.</summary>
    public string? Condition { get; set; }
}

public sealed class RevealSpotData
{
    public string Location { get; set; } = "";
    /// <summary>Tile to stand near, or null for anywhere in the location. Use X = -1 for Grandpa's shrine on the farm.</summary>
    public Point? Tile { get; set; }
    public int Radius { get; set; } = 2;
    /// <summary>Optional game state query that must pass (e.g. a time window).</summary>
    public string? Condition { get; set; }
}

/// <summary>One bundle on the star-chart board (<c>Mods/Inyourfacer.Observatory/StarCharts</c>).</summary>
public sealed class StarChartData
{
    public string DisplayName { get; set; } = "";
    public string Description { get; set; } = "";
    /// <summary>Constellation whose coordinates this bundle reveals.</summary>
    public string Constellation { get; set; } = "";
    /// <summary>Qualified item IDs that can be donated (one each).</summary>
    public List<string> Items { get; set; } = new();
    /// <summary>How many distinct items from <see cref="Items"/> complete the bundle.</summary>
    public int Required { get; set; }
}

public static class PerkIds
{
    public const string CropGrowth = "CropGrowth";       // chance a watered crop grows an extra day
    public const string FishingBar = "FishingBar";       // fishing bar height multiplier bonus
    public const string ExtraOre = "ExtraOre";           // chance an ore node drops one extra ore
    public const string CookedEnergy = "CookedEnergy";   // cooked food energy bonus
    public const string JunimoRadius = "JunimoRadius";   // extra tiles of Junimo hut radius
    public const string MaxEnergy = "MaxEnergy";         // flat max energy, granted once
    public const string SkillXp = "SkillXp";             // skill XP bonus
}
