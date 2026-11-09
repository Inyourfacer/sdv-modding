using System;
using System.Collections.Generic;
using System.Linq;
using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using Observatory.Framework;
using StardewValley;
using StardewValley.BellsAndWhistles;
using StardewValley.Menus;

namespace Observatory.Menus;

/// <summary>Connect-the-stars puzzle. Click a star, then another, to toggle a line between them. Right-click undoes.</summary>
internal sealed class StarPuzzleMenu : IClickableMenu
{
    private const float HitRadius = 26f;
    private const float SolvedHoldSeconds = 2.5f;
    private const float OutlineAlpha = 0.28f;

    private readonly string Id;
    private readonly ConstellationData Data;
    private readonly List<Vector2> Points = new();     // normalized; real stars first, then decoys
    private readonly HashSet<(int, int)> Target = new();
    private readonly List<(int, int)> Drawn = new();   // ordered, for undo
    private readonly List<Vector2> Background = new(); // faint field stars (not clickable)
    private readonly ClickableTextureComponent ResetButton;

    private Rectangle Sky;
    private int? Selected;
    private float Elapsed;
    private float SolvedFor = -1f;

    public StarPuzzleMenu(string id, ConstellationData data)
        : base(0, 0, 0, 0, showUpperRightCloseButton: true)
    {
        Id = id;
        Data = data;

        var view = Game1.uiViewport;
        int size = Math.Min(720, Math.Min(view.Width - 160, view.Height - 300));
        width = size + 64;
        height = size + 220;
        var topLeft = Utility.getTopLeftPositionForCenteringOnScreen(width, height);
        xPositionOnScreen = (int)topLeft.X;
        yPositionOnScreen = (int)topLeft.Y + 24;
        Sky = new Rectangle(xPositionOnScreen + 32, yPositionOnScreen + 96, size, size);
        initializeUpperRightCloseButton();

        ResetButton = new ClickableTextureComponent(
            new Rectangle(xPositionOnScreen + width - 96, yPositionOnScreen + height - 92, 64, 64),
            Ui.Sheet, Ui.ResetSource, 4f);

        Points.AddRange(data.Stars);
        foreach (var pair in data.Lines)
            if (pair.Length == 2)
                Target.Add(Key(pair[0], pair[1]));

        var rng = new Random(Hash(id));
        AddDecoys(rng, data.Decoys);
        for (int i = 0; i < 90; i++)
            Background.Add(new Vector2((float)rng.NextDouble(), (float)rng.NextDouble()));
    }

    private static int Hash(string s)
    {
        unchecked
        {
            int h = 17;
            foreach (char c in s) h = h * 31 + c;
            return h;
        }
    }

    /// <summary>Scatter decoys that never sit on top of a real star or on one of the target lines.</summary>
    private void AddDecoys(Random rng, int count)
    {
        for (int n = 0, tries = 0; n < count && tries < 500; tries++)
        {
            var p = new Vector2(0.08f + (float)rng.NextDouble() * 0.84f, 0.08f + (float)rng.NextDouble() * 0.84f);
            if (Points.Any(q => Vector2.Distance(p, q) < 0.1f))
                continue;
            if (Target.Any(t => DistanceToSegment(p, Points[t.Item1], Points[t.Item2]) < 0.05f))
                continue;
            Points.Add(p);
            n++;
        }
    }

    private static float DistanceToSegment(Vector2 p, Vector2 a, Vector2 b)
    {
        var ab = b - a;
        float t = ab.LengthSquared() < 1e-6f ? 0f : MathHelper.Clamp(Vector2.Dot(p - a, ab) / ab.LengthSquared(), 0f, 1f);
        return Vector2.Distance(p, a + ab * t);
    }

    private static (int, int) Key(int a, int b) => a < b ? (a, b) : (b, a);
    private Vector2 Screen(Vector2 n) => new(Sky.X + n.X * Sky.Width, Sky.Y + n.Y * Sky.Height);
    private bool Solved => SolvedFor >= 0f;

    private int? StarAt(int x, int y)
    {
        int? best = null;
        float bestDist = HitRadius;
        for (int i = 0; i < Points.Count; i++)
        {
            float d = Vector2.Distance(Screen(Points[i]), new Vector2(x, y));
            if (d <= bestDist)
            {
                best = i;
                bestDist = d;
            }
        }
        return best;
    }

    public override void receiveLeftClick(int x, int y, bool playSound = true)
    {
        if (Solved)
            return;
        base.receiveLeftClick(x, y, playSound);
        if (ResetButton.containsPoint(x, y))
        {
            Drawn.Clear();
            Selected = null;
            Game1.playSound("shwip");
            return;
        }

        int? star = StarAt(x, y);
        if (star is null)
        {
            Selected = null;
            return;
        }
        if (Selected is null || Selected == star)
        {
            Selected = Selected == star ? null : star;
            Game1.playSound("smallSelect");
            return;
        }

        var key = Key(Selected.Value, star.Value);
        if (Drawn.Remove(key))
            Game1.playSound("cancel");
        else
        {
            Drawn.Add(key);
            Game1.playSound("crystal");
        }
        Selected = star; // keep chaining from the last star
        CheckSolved();
    }

    public override void receiveRightClick(int x, int y, bool playSound = true)
    {
        if (Solved)
            return;
        if (Selected != null)
            Selected = null;
        else if (Drawn.Count > 0)
        {
            Drawn.RemoveAt(Drawn.Count - 1);
            Game1.playSound("cancel");
        }
    }

    private void CheckSolved()
    {
        if (Drawn.Count == Target.Count && Target.SetEquals(Drawn))
        {
            SolvedFor = 0f;
            Selected = null;
            Game1.playSound("newArtifact");
        }
    }

    public override void update(GameTime time)
    {
        base.update(time);
        float dt = (float)time.ElapsedGameTime.TotalSeconds;
        Elapsed += dt;
        if (Solved)
        {
            SolvedFor += dt;
            if (SolvedFor >= SolvedHoldSeconds)
            {
                Progress.Complete(Game1.player, Id, Data);
                exitThisMenu(playSound: false);
            }
        }
    }

    public override bool readyToClose() => !Solved;

    private float CurrentOutlineAlpha()
    {
        switch (Data.Outline)
        {
            case OutlineMode.Visible:
                return OutlineAlpha;
            case OutlineMode.Fades:
                float fadeStart = Math.Max(0f, Data.OutlineFadeSeconds - 1f);
                if (Elapsed <= fadeStart) return OutlineAlpha;
                return OutlineAlpha * MathHelper.Clamp(1f - (Elapsed - fadeStart), 0f, 1f);
            default:
                return 0f;
        }
    }

    public override void draw(SpriteBatch b)
    {
        b.Draw(Game1.fadeToBlackRect, Game1.graphics.GraphicsDevice.Viewport.Bounds, Color.Black * 0.75f);
        drawTextureBox(b, xPositionOnScreen, yPositionOnScreen, width, height, Color.White);
        SpriteText.drawStringWithScrollCenteredAt(b, Text.Get(Data.DisplayName), xPositionOnScreen + width / 2, yPositionOnScreen - 56);

        string hint = Data.Outline switch
        {
            OutlineMode.Visible => Text.Get("puzzle.hint.visible"),
            OutlineMode.Fades => Text.Get("puzzle.hint.fades", new { seconds = (int)Data.OutlineFadeSeconds }),
            _ => Text.Get(Data.ShapeRiddle ?? "puzzle.hint.none"),
        };
        if (Solved)
            hint = Text.Get("puzzle.solved");
        Ui.TextCentered(b, Game1.parseText(hint, Game1.smallFont, Sky.Width), Ui.Small, xPositionOnScreen + width / 2, yPositionOnScreen + 32, Game1.textColor);

        // sky
        Ui.Rect(b, Sky, Ui.NightSky);
        foreach (var bg in Background)
            Ui.Rect(b, new Rectangle((int)Screen(bg).X, (int)Screen(bg).Y, 2, 2), Color.White * 0.25f);

        // faint outline
        float outline = CurrentOutlineAlpha();
        if (outline > 0f && !Solved)
            foreach (var (a, c) in Target)
                Ui.Line(b, Screen(Points[a]), Screen(Points[c]), Ui.Known * outline, 6f);

        // player lines
        var lineColor = Solved ? Ui.Gold : Ui.StarWhite * 0.85f;
        foreach (var (a, c) in Drawn)
            Ui.Line(b, Screen(Points[a]), Screen(Points[c]), lineColor, Solved ? 4f : 3f);

        // rubber-band line from the selected star
        if (Selected is int sel)
            Ui.Line(b, Screen(Points[sel]), new Vector2(Game1.getMouseX(), Game1.getMouseY()), Ui.StarWhite * 0.4f, 2f);

        // stars (real and decoy drawn identically)
        int hover = StarAt(Game1.getMouseX(), Game1.getMouseY()) ?? -1;
        for (int i = 0; i < Points.Count; i++)
        {
            float twinkle = 0.85f + 0.15f * (float)Math.Sin(Elapsed * 2.2f + i * 1.7f);
            bool lit = i == Selected || i == hover;
            var color = Solved && i < Data.Stars.Count ? Ui.Gold : Ui.StarWhite;
            Ui.Star(b, Screen(Points[i]), color * twinkle, lit ? 4.5f : 3.5f, glow: lit || Solved);
        }

        string progress = Text.Get("puzzle.lines", new { drawn = Drawn.Count });
        b.DrawString(Game1.smallFont, progress, new Vector2(Sky.X, Sky.Bottom + 24), Game1.textColor);
        b.DrawString(Game1.smallFont, Text.Get("puzzle.controls"), new Vector2(Sky.X, Sky.Bottom + 56), Game1.textColor * 0.75f);

        if (!Solved)
        {
            ResetButton.draw(b);
            if (ResetButton.containsPoint(Game1.getMouseX(), Game1.getMouseY()))
                drawHoverText(b, Text.Get("puzzle.reset"), Game1.smallFont);
        }

        base.draw(b);
        drawMouse(b);
    }
}
