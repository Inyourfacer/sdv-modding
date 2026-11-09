using StardewModdingAPI;

namespace Observatory.Framework;

internal static class Text
{
    public static ITranslationHelper Translation = null!;

    /// <summary>Resolve a data text field: an i18n key if one exists, otherwise the literal text (so other packs can write plain strings).</summary>
    public static string Get(string? keyOrText, object? tokens = null)
    {
        if (string.IsNullOrEmpty(keyOrText))
            return "";
        var t = tokens is null ? Translation.Get(keyOrText) : Translation.Get(keyOrText, tokens);
        return t.HasValue() ? t.ToString() : keyOrText;
    }
}
