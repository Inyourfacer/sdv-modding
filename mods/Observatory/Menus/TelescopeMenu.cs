using System.Linq;
using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using Observatory.Framework;
using StardewValley;
using StardewValley.BellsAndWhistles;
using StardewValley.Menus;

namespace Observatory.Menus;

/// <summary>Dial menu: set right ascension and declination, then observe.</summary>
internal sealed class TelescopeMenu : IClickableMenu
{
    // dial positions persist between uses, like a real telescope
    private static int RightAscension;
    private static int Declination;
    private const int DecMin = -80, DecMax = 80, DecStep = 10;

    private readonly ModConfig Config;
    private readonly ClickableTextureComponent RaUp, RaDown, DecUp, DecDown, ObserveButton;
    private string Status;
    private Color StatusColor = Game1.textColor;

    public TelescopeMenu(ModConfig config)
        : base(0, 0, 0, 0, showUpperRightCloseButton: true)
    {
        Config = config;
        width = 760;
        height = 500;
        var topLeft = Utility.getTopLeftPositionForCenteringOnScreen(width, height);
        xPositionOnScreen = (int)topLeft.X;
        yPositionOnScreen = (int)topLeft.Y;
        initializeUpperRightCloseButton();

        int raX = xPositionOnScreen + width / 4;
        int decX = xPositionOnScreen + width * 3 / 4;
        int upY = yPositionOnScreen + 120;
        int downY = yPositionOnScreen + 280;
        RaUp = Arrow(raX, upY, up: true);
        RaDown = Arrow(raX, downY, up: false);
        DecUp = Arrow(decX, upY, up: true);
        DecDown = Arrow(decX, downY, up: false);
        ObserveButton = new ClickableTextureComponent(
            new Rectangle(xPositionOnScreen + width / 2 - 32, yPositionOnScreen + height - 112, 64, 64),
            Game1.mouseCursors, Game1.getSourceRectForStandardTileSheet(Game1.mouseCursors, 46), 1f);

        Status = SkyStatus(out bool ok);
        StatusColor = ok ? Game1.textColor : Color.DarkRed;
    }

    private static ClickableTextureComponent Arrow(int centerX, int y, bool up) =>
        new(new Rectangle(centerX - 22, y, 44, 48), Game1.mouseCursors,
            up ? new Rectangle(421, 459, 11, 12) : new Rectangle(421, 472, 11, 12), 4f);

    public static bool IsObservingTime(ModConfig config) =>
        Game1.timeOfDay >= config.ObserveStartTime && Game1.timeOfDay <= config.ObserveEndTime;

    public static bool IsClearSky(ModConfig config)
    {
        if (!config.RequireClearSky)
            return true;
        var sky = Game1.getLocationFromName("Backwoods") ?? Game1.player.currentLocation;
        return !Game1.IsRainingHere(sky) && !Game1.IsSnowingHere(sky) && !Game1.IsGreenRainingHere(sky);
    }

    private string SkyStatus(out bool ok)
    {
        ok = false;
        if (!IsObservingTime(Config))
            return Text.Get("telescope.too_early", new { start = Game1.getTimeOfDayString(Config.ObserveStartTime) });
        if (!IsClearSky(Config))
            return Text.Get("telescope.cloudy");
        ok = true;
        return Text.Get("telescope.clear");
    }

    public override void receiveLeftClick(int x, int y, bool playSound = true)
    {
        base.receiveLeftClick(x, y, playSound);
        if (RaUp.containsPoint(x, y)) TurnRa(1);
        else if (RaDown.containsPoint(x, y)) TurnRa(-1);
        else if (DecUp.containsPoint(x, y)) TurnDec(1);
        else if (DecDown.containsPoint(x, y)) TurnDec(-1);
        else if (ObserveButton.containsPoint(x, y)) Observe();
    }

    private void TurnRa(int dir)
    {
        RightAscension = (RightAscension + dir + 24) % 24;
        Game1.playSound("smallSelect");
    }

    private void TurnDec(int dir)
    {
        Declination = MathHelper.Clamp(Declination + dir * DecStep, DecMin, DecMax);
        Game1.playSound("smallSelect");
    }

    public override void receiveScrollWheelAction(int direction)
    {
        int dir = direction > 0 ? 1 : -1;
        int mouseX = Game1.getMouseX();
        if (mouseX < xPositionOnScreen + width / 2) TurnRa(dir);
        else TurnDec(dir);
    }

    private void Observe()
    {
        Status = SkyStatus(out bool ok);
        StatusColor = ok ? Game1.textColor : Color.DarkRed;
        if (!ok)
        {
            Game1.playSound("cancel");
            return;
        }

        var match = Progress.Constellations.FirstOrDefault(p => p.Value.RightAscension == RightAscension && p.Value.Declination == Declination);
        if (match.Key is null || !Progress.KnowsCoords(Game1.player, match.Key))
        {
            Status = Text.Get("telescope.nothing");
            StatusColor = Game1.textColor;
            Game1.playSound("shwip");
            return;
        }
        if (Progress.IsDone(Game1.player, match.Key))
        {
            Status = Text.Get("telescope.already", new { name = Text.Get(match.Value.DisplayName) });
            StatusColor = Game1.textColor;
            Game1.playSound("shwip");
            return;
        }

        Game1.playSound("bigSelect");
        Game1.activeClickableMenu = new StarPuzzleMenu(match.Key, match.Value);
    }

    public override void draw(SpriteBatch b)
    {
        b.Draw(Game1.fadeToBlackRect, Game1.graphics.GraphicsDevice.Viewport.Bounds, Color.Black * 0.6f);
        drawTextureBox(b, xPositionOnScreen, yPositionOnScreen, width, height, Color.White);
        SpriteText.drawStringWithScrollCenteredAt(b, Text.Get("telescope.title"), xPositionOnScreen + width / 2, yPositionOnScreen - 64);

        DrawDial(b, xPositionOnScreen + width / 4, Text.Get("telescope.ra"), RightAscension.ToString("00") + "h", RaUp, RaDown);
        DrawDial(b, xPositionOnScreen + width * 3 / 4, Text.Get("telescope.dec"), (Declination >= 0 ? "+" : "") + Declination + "°", DecUp, DecDown);

        var lines = Game1.parseText(Status, Game1.smallFont, width - 96);
        Ui.TextCentered(b, lines, Ui.Small, xPositionOnScreen + width / 2, yPositionOnScreen + 348, StatusColor);

        ObserveButton.draw(b);
        if (ObserveButton.containsPoint(Game1.getMouseX(), Game1.getMouseY()))
            drawHoverText(b, Text.Get("telescope.observe"), Game1.smallFont);

        base.draw(b);
        drawMouse(b);
    }

    private void DrawDial(SpriteBatch b, int centerX, string label, string value, ClickableTextureComponent up, ClickableTextureComponent down)
    {
        Ui.TextCentered(b, label, Ui.Small, centerX, yPositionOnScreen + 72, Game1.textColor);
        var box = new Rectangle(centerX - 90, yPositionOnScreen + 180, 180, 90);
        drawTextureBox(b, Game1.menuTexture, new Rectangle(0, 256, 60, 60), box.X, box.Y, box.Width, box.Height, Color.White, drawShadow: false);
        Ui.TextCentered(b, value, Ui.Dialogue, centerX, box.Y + 22, Game1.textColor);
        up.draw(b);
        down.draw(b);
    }
}
