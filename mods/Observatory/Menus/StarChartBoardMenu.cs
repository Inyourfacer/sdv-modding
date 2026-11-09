using System.Collections.Generic;
using System.Linq;
using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using Observatory.Framework;
using StardewValley;
using StardewValley.BellsAndWhistles;
using StardewValley.Menus;

namespace Observatory.Menus;

/// <summary>The star-chart bundle board. Each bundle reveals one constellation's coordinates.</summary>
internal sealed class StarChartBoardMenu : IClickableMenu
{
    private const int RowHeight = 200;

    private readonly List<(string Id, StarChartData Data, ClickableTextureComponent Button)> Rows = new();
    private string? HoverText;

    public StarChartBoardMenu()
        : base(0, 0, 0, 0, showUpperRightCloseButton: true)
    {
        var bundles = Progress.StarCharts.OrderBy(p => p.Key).ToList();
        width = 960;
        height = System.Math.Max(1, bundles.Count) * RowHeight + 80;
        var topLeft = Utility.getTopLeftPositionForCenteringOnScreen(width, height);
        xPositionOnScreen = (int)topLeft.X;
        yPositionOnScreen = (int)topLeft.Y + 24;
        initializeUpperRightCloseButton();

        int y = yPositionOnScreen + 40;
        foreach (var (id, data) in bundles)
        {
            var button = new ClickableTextureComponent(new Rectangle(xPositionOnScreen + width - 112, y + 96, 64, 64),
                Game1.mouseCursors, Game1.getSourceRectForStandardTileSheet(Game1.mouseCursors, 46), 1f);
            Rows.Add((id, data, button));
            y += RowHeight;
        }
    }

    public override void receiveLeftClick(int x, int y, bool playSound = true)
    {
        base.receiveLeftClick(x, y, playSound);
        foreach (var (id, data, button) in Rows)
            if (button.containsPoint(x, y))
                Donate(id, data);
    }

    /// <summary>Take one of each still-needed item from the inventory (any quality).</summary>
    private static void Donate(string id, StarChartData data)
    {
        var who = Game1.player;
        if (Progress.BundleComplete(who, id, data))
            return;

        var donated = Progress.Donated(who, id);
        int added = 0;
        foreach (string itemId in data.Items)
        {
            if (donated.Count >= data.Required)
                break;
            if (donated.Contains(itemId) || !TakeOne(who, itemId))
                continue;
            donated.Add(itemId);
            added++;
        }

        if (added == 0)
        {
            Game1.playSound("cancel");
            return;
        }
        Progress.SetDonated(who, id, donated);
        Game1.playSound("newArtifact");

        if (donated.Count >= data.Required && Progress.Constellations.TryGetValue(data.Constellation, out var constellation))
            Progress.RevealCoords(who, data.Constellation, constellation);
    }

    private static bool TakeOne(Farmer who, string qualifiedId)
    {
        for (int i = 0; i < who.Items.Count; i++)
        {
            var item = who.Items[i];
            if (item?.QualifiedItemId != qualifiedId)
                continue;
            item.Stack--;
            if (item.Stack <= 0)
                who.Items[i] = null;
            return true;
        }
        return false;
    }

    public override void draw(SpriteBatch b)
    {
        HoverText = null;
        b.Draw(Game1.fadeToBlackRect, Game1.graphics.GraphicsDevice.Viewport.Bounds, Color.Black * 0.6f);
        drawTextureBox(b, xPositionOnScreen, yPositionOnScreen, width, height, Color.White);
        SpriteText.drawStringWithScrollCenteredAt(b, Text.Get("board.title"), xPositionOnScreen + width / 2, yPositionOnScreen - 56);

        var who = Game1.player;
        int mx = Game1.getMouseX(), my = Game1.getMouseY();
        int y = yPositionOnScreen + 40;
        foreach (var (id, data, button) in Rows)
        {
            var donated = Progress.Donated(who, id);
            bool complete = donated.Count >= data.Required;

            b.DrawString(Game1.dialogueFont, Text.Get(data.DisplayName), new Vector2(xPositionOnScreen + 48, y), Game1.textColor);
            string sub = complete
                ? Text.Get("board.complete")
                : Text.Get("board.progress", new { done = donated.Count, required = data.Required, desc = Text.Get(data.Description) });
            b.DrawString(Game1.smallFont, Game1.parseText(sub, Game1.smallFont, width - 220), new Vector2(xPositionOnScreen + 48, y + 46), Game1.textColor * 0.85f);

            int ix = xPositionOnScreen + 48;
            foreach (string itemId in data.Items)
            {
                var parsed = ItemRegistry.GetDataOrErrorItem(itemId);
                var dest = new Rectangle(ix, y + 100, 64, 64);
                bool have = donated.Contains(itemId);
                b.Draw(Game1.menuTexture, dest, Game1.getSourceRectForStandardTileSheet(Game1.menuTexture, 10), Color.White);
                b.Draw(parsed.GetTexture(), dest, parsed.GetSourceRect(), have ? Color.White : Color.Black * 0.35f);
                if (dest.Contains(mx, my))
                    HoverText = parsed.DisplayName;
                ix += 72;
            }

            if (!complete)
            {
                button.draw(b);
                if (button.containsPoint(mx, my))
                    HoverText = Text.Get("board.donate");
            }
            y += RowHeight;
        }

        base.draw(b);
        if (HoverText != null)
            drawHoverText(b, HoverText, Game1.smallFont);
        drawMouse(b);
    }
}
