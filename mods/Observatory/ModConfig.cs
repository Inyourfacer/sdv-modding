namespace Observatory;

public sealed class ModConfig
{
    /// <summary>Turn all constellation perks on/off without losing progress.</summary>
    public bool EnablePerks { get; set; } = true;

    /// <summary>Days Robin takes to build the observatory after it's unlocked.</summary>
    public int ConstructionDays { get; set; } = 3;

    /// <summary>Observing window (game time, 2000 = 8pm, 2600 = 2am).</summary>
    public int ObserveStartTime { get; set; } = 2000;
    public int ObserveEndTime { get; set; } = 2600;

    /// <summary>Block the telescope when it's raining, storming or snowing.</summary>
    public bool RequireClearSky { get; set; } = true;
}
