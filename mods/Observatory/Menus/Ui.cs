using System;
using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using StardewModdingAPI;
using StardewValley;

namespace Observatory.Menus;

/// <summary>Shared drawing helpers and the mod's UI sheet (assets/ui.png).</summary>
internal static class Ui
{
    public static IModHelper Helper = null!;

    /// <summary>9×9 star sprite on the UI sheet.</summary>
    public static readonly Rectangle StarSource = new(0, 0, 9, 9);
    /// <summary>15×15 soft glow on the UI sheet.</summary>
    public static readonly Rectangle GlowSource = new(16, 0, 15, 15);
    /// <summary>16×16 reset (circular arrow) icon on the UI sheet.</summary>
    public static readonly Rectangle ResetSource = new(32, 0, 16, 16);

    public static readonly Color NightSky = new(10, 14, 38);
    public static readonly Color StarWhite = new(235, 240, 255);
    public static readonly Color Gold = new(255, 214, 102);
    public static readonly Color Known = new(140, 190, 255);
    public static readonly Color Unknown = new(110, 110, 130);

    public static Texture2D Sheet => Helper.GameContent.Load<Texture2D>(Ids.UiTextureAsset);

    public static void Line(SpriteBatch b, Vector2 from, Vector2 to, Color color, float thickness = 3f)
    {
        var delta = to - from;
        float length = delta.Length();
        if (length < 1f)
            return;
        float angle = (float)Math.Atan2(delta.Y, delta.X);
        b.Draw(Game1.staminaRect, from, null, color, angle, new Vector2(0f, 0.5f), new Vector2(length, thickness), SpriteEffects.None, 0.9f);
    }

    public static void Rect(SpriteBatch b, Rectangle area, Color color) =>
        b.Draw(Game1.staminaRect, area, color);

    public static void Star(SpriteBatch b, Vector2 center, Color color, float scale, bool glow)
    {
        if (glow)
            b.Draw(Sheet, center, GlowSource, color * 0.55f, 0f, new Vector2(7.5f), scale * 1.6f, SpriteEffects.None, 0.91f);
        b.Draw(Sheet, center, StarSource, color, 0f, new Vector2(4.5f), scale, SpriteEffects.None, 0.92f);
    }

    public static void TextCentered(SpriteBatch b, string text, SpriteFontRef font, int centerX, int y, Color color)
    {
        var f = font.Font;
        var size = f.MeasureString(text);
        b.DrawString(f, text, new Vector2(centerX - size.X / 2f, y), color);
    }

    /// <summary>Tiny wrapper so call sites read nicely (Ui.Small / Ui.Dialogue).</summary>
    public readonly record struct SpriteFontRef(SpriteFont Font);
    public static SpriteFontRef Small => new(Game1.smallFont);
    public static SpriteFontRef Dialogue => new(Game1.dialogueFont);
}
