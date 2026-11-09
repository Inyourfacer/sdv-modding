namespace Observatory;

/// <summary>Every ID shared between the C# mod and the [CP] pack. The CP pack uses the same prefix through its <c>Obs</c> dynamic token.</summary>
internal static class Ids
{
    public const string Prefix = "Inyourfacer.Observatory";

    // locations
    public const string ObservatoryLocation = Prefix + "_Observatory";
    public const string RoofLocation = Prefix + "_ObservatoryRoof";

    // tile actions (Buildings layer: Action <key>)
    public const string TelescopeAction = Prefix + "_Telescope";
    public const string StarChartAction = Prefix + "_StarCharts";
    public const string JournalAction = Prefix + "_Journal";

    // custom data assets (editable by other packs with EditData)
    public const string ConstellationsAsset = "Mods/" + Prefix + "/Constellations";
    public const string StarChartsAsset = "Mods/" + Prefix + "/StarCharts";
    public const string UiTextureAsset = "Mods/" + Prefix + "/UI";

    // unlock / construction (mail flags on the host)
    public const string MaruLetter = Prefix + "_MaruLetter";          // Maru's 6-heart letter (CP mail)
    public const string TownProjectDone = Prefix + "_TownProjectDone"; // special order reward (CP)
    public const string ConstructionStarted = Prefix + "_ConstructionStarted";
    public const string Built = Prefix + "_Built";
    public const string FinaleSeen = Prefix + "_Finale";

    // per-player flags, built from a constellation ID
    public static string RiddleFlag(string id) => $"{Prefix}_Riddle_{id}";
    public static string CoordsFlag(string id) => $"{Prefix}_Coords_{id}";
    public static string DoneFlag(string id) => $"{Prefix}_Done_{id}";

    // modData keys
    public const string ConstructionStartDayKey = Prefix + "/ConstructionStartDay";
    public static string BundleKey(string bundleId) => $"{Prefix}/Bundle/{bundleId}";
}
