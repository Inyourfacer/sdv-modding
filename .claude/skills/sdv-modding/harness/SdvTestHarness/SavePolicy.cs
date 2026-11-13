namespace SdvTestHarness;

/// <summary>The only rule that lets the harness touch a save. Pure, so it is unit-tested without the game.</summary>
public static class SavePolicy
{
    public const string DefaultPrefix = "SdvTest";

    /// <summary>
    /// True only when <paramref name="saveFolder"/> (the folder name under Saves, e.g. "SdvTest_123456789") starts with the
    /// prefix, the prefix is at least 4 characters and contains "test", and the name cannot escape the Saves folder.
    /// </summary>
    public static bool IsTestSave(string? saveFolder, string? prefix)
    {
        if (string.IsNullOrWhiteSpace(saveFolder) || string.IsNullOrWhiteSpace(prefix))
            return false;
        prefix = prefix.Trim();
        if (prefix.Length < 4)                                  // "A" would match nearly every save
            return false;
        if (!prefix.Contains("test", System.StringComparison.OrdinalIgnoreCase))   // the prefix itself must say it is a test save
            return false;                                                          // (so a config can never name a real farm such as "Hoes")
        if (saveFolder.IndexOfAny(new[] { '/', '\\', ':' }) >= 0 || saveFolder.Contains(".."))
            return false;
        return saveFolder.StartsWith(prefix, System.StringComparison.OrdinalIgnoreCase);
    }
}
