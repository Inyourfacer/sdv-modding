using System;
using System.Linq;
using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using Observatory.Framework;
using StardewValley;
using StardewValley.BellsAndWhistles;
using StardewValley.Menus;

namespace Observatory.Menus;

/// <summary>The star journal: every constellation, what's known about it, and the perk once charted.</summary>
internal sealed class StarJournalMenu : IClickableMenu
{
    private const int RowsPerPage = 6;
    private const int RowHeight = 104;

    private readonly ClickableTextureComponent PrevPage, NextPage;
    private int Page;

    public StarJournalMenu()
        : base(0, 0, 0, 0, showUpperRightCloseButton: true)
    {
        width = 900;
        height = RowsPerPage * RowHeight + 160;
        var topLeft = Utility.getTopLeftPositionForCenteringOnScreen(width, height);
        xPositionOnScreen = (int)topLeft.X;
        yPositionOnScreen = (int)topLeft.Y + 24;
        initializeUpperRightCloseButton();

        PrevPage = new ClickableTextureComponent(new Rectangle(xPositionOnScreen + 32, yPositionOnScreen + height - 76, 48, 44),
            Game1.mouseCursors, new Rectangle(352, 495, 12, 11), 4f);
        NextPage = new ClickableTextureComponent(new Rectangle(xPositionOnScreen + width - 80, yPositionOnScreen + height - 76, 48, 44),
            Game1.mouseCursors, new Rectangle(365, 495, 12, 11), 4f);
    }

    private int PageCount => Math.Max(1, (Progress.Constellations.Count + RowsPerPage - 1) / RowsPerPage);

    public override void receiveLeftClick(int x, int y, bool playSound = true)
    {
        base.receiveLeftClick(x, y, playSound);
        if (Page > 0 && PrevPage.containsPoint(x, y)) { Page--; Game1.playSound("shwip"); }
        else if (Page < PageCount - 1 && NextPage.containsPoint(x, y)) { Page++; Game1.playSound("shwip"); }
    }

    public override void draw(SpriteBatch b)
    {
        b.Draw(Game1.fadeToBlackRect, Game1.graphics.GraphicsDevice.Viewport.Bounds, Color.Black * 0.6f);
        drawTextureBox(b, xPositionOnScreen, yPositionOnScreen, width, height, Color.White);
        SpriteText.drawStringWithScrollCenteredAt(b, Text.Get("journal.title"), xPositionOnScreen + width / 2, yPositionOnScreen - 56);

        var who = Game1.player;
        string? hover = null;
        var rows = Progress.Ordered.Skip(Page * RowsPerPage).Take(RowsPerPage).ToList();
        int y = yPositionOnScreen + 40;
        int textX = xPositionOnScreen + 120;
        int textWidth = width - 160;
        foreach (var (id, data) in rows)
        {
            bool done = Progress.IsDone(who, id);
            bool coords = Progress.KnowsCoords(who, id);
            bool riddle = Progress.KnowsRiddle(who, id);

            var color = done ? Ui.Gold : coords ? Ui.Known : Ui.Unknown;
            Ui.Star(b, new Vector2(xPositionOnScreen + 70, y + 32), color, 4f, glow: done);

            string name = done || coords ? Text.Get(data.DisplayName) : Text.Get("journal.unknown");
            b.DrawString(Game1.dialogueFont, name, new Vector2(textX, y), Game1.textColor);

            string detail;
            if (done)
                detail = Text.Get(data.PerkText);
            else if (coords)
                detail = Text.Get("journal.coords", new { coords = Progress.FormatCoords(data.RightAscension, data.Declination) });
            else if (riddle && !string.IsNullOrEmpty(data.Riddle))
                detail = "\"" + Text.Get(data.Riddle) + "\"";
            else
                detail = Text.Get(data.SourceHint);

            string wrapped = Game1.parseText(detail, Game1.smallFont, textWidth);
            b.DrawString(Game1.smallFont, wrapped, new Vector2(textX, y + 46), Game1.textColor * 0.85f);

            if (done && !string.IsNullOrEmpty(data.Description))
            {
                var bounds = new Rectangle(xPositionOnScreen + 32, y, width - 64, RowHeight - 8);
                if (bounds.Contains(Game1.getMouseX(), Game1.getMouseY()))
                    hover = Game1.parseText(Text.Get(data.Description), Game1.smallFont, 480);
            }
            y += RowHeight;
        }

        string footer = Text.Get("journal.footer", new { done = Progress.DoneCount(who), total = Progress.Constellations.Count });
        Ui.TextCentered(b, footer, Ui.Small, xPositionOnScreen + width / 2, yPositionOnScreen + height - 64, Game1.textColor);
        if (Page > 0) PrevPage.draw(b);
        if (Page < PageCount - 1) NextPage.draw(b);

        base.draw(b);
        if (hover != null)
            drawHoverText(b, hover, Game1.smallFont);
        drawMouse(b);
    }
}
