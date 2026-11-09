# SMAPI C# mods (SDV 1.6, SMAPI 4.x, .NET 6)

Prefer Content Patcher for anything expressible as data. Use C# for logic: new mechanics, UI/menus, Harmony patches, custom CP tokens, APIs for other mods.

## Project
```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <AssemblyName>MyMod</AssemblyName>
    <RootNamespace>MyMod</RootNamespace>
    <Version>1.0.0</Version>
    <TargetFramework>net6.0</TargetFramework>
    <Nullable>enable</Nullable>
    <EnableHarmony>true</EnableHarmony>          <!-- only if patching -->
    <!-- <GamePath>D:\Games\Stardew Valley</GamePath>  only if auto-detect fails -->
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Pathoschild.Stardew.ModBuildConfig" Version="4.4.0" />
  </ItemGroup>
</Project>
```
ModBuildConfig (4.4.0 latest known; check NuGet for newer) auto-detects the game, adds references, copies `manifest.json`, `i18n/`, `assets/` and deploys to `Mods/<AssemblyName>` on build, and zips a release in `bin/Release`. Override the deploy folder name with `<ModFolderName>`. A paired CP pack stays a separate folder; deploy it with `scripts/deploy.py`.

## manifest.json
```json
{
  "Name": "My Mod",
  "Author": "Me",
  "Version": "1.0.0",
  "Description": "…",
  "UniqueID": "Me.MyMod",
  "EntryDll": "MyMod.dll",
  "MinimumApiVersion": "4.0.0",
  "UpdateKeys": [],
  "Dependencies": [
    { "UniqueID": "spacechase0.GenericModConfigMenu", "IsRequired": false }
  ]
}
```

## Entry
```csharp
using StardewModdingAPI;
using StardewModdingAPI.Events;
using StardewValley;

namespace MyMod;

internal sealed class ModEntry : Mod
{
    private ModConfig Config = null!;

    public override void Entry(IModHelper helper)
    {
        Config = helper.ReadConfig<ModConfig>();

        helper.Events.GameLoop.GameLaunched += OnGameLaunched;
        helper.Events.GameLoop.SaveLoaded   += (_, _) => { };
        helper.Events.GameLoop.DayStarted   += (_, _) => { };
        helper.Events.Input.ButtonPressed   += OnButtonPressed;
        helper.Events.Content.AssetRequested += OnAssetRequested;
    }
}
```
Common events: `GameLoop.{GameLaunched,SaveLoaded,DayStarted,DayEnding,TimeChanged,UpdateTicked,Saving,ReturnedToTitle}`, `Input.{ButtonPressed,ButtonsChanged,CursorMoved}`, `Display.{MenuChanged,RenderedHud,RenderedWorld,RenderedActiveMenu}`, `Player.{Warped,InventoryChanged,LevelChanged}`, `World.{ObjectListChanged,NpcListChanged,LocationListChanged}`, `Content.{AssetRequested,AssetsInvalidated,AssetReady}`, `Multiplayer.{ModMessageReceived,PeerConnected}`.

Guard world logic with `Context.IsWorldReady`; host-only logic with `Context.IsMainPlayer`.

## Content API (load/edit assets from C#)
```csharp
private void OnAssetRequested(object? sender, AssetRequestedEventArgs e)
{
    if (e.NameWithoutLocale.IsEquivalentTo($"Mods/{ModManifest.UniqueID}/Objects"))
        e.LoadFromModFile<Texture2D>("assets/objects.png", AssetLoadPriority.Medium);

    if (e.NameWithoutLocale.IsEquivalentTo("Data/Objects"))
        e.Edit(asset =>
        {
            var data = asset.AsDictionary<string, StardewValley.GameData.Objects.ObjectData>().Data;
            data[$"{ModManifest.UniqueID}_Gem"] = new() {
                Name = $"{ModManifest.UniqueID}_Gem",
                DisplayName = Helper.Translation.Get("gem.name"),
                Description = Helper.Translation.Get("gem.description"), Type = "Basic", Category = 0, Price = 250,
                Texture = $"Mods/{ModManifest.UniqueID}/Objects", SpriteIndex = 0
            };
        });

    if (e.NameWithoutLocale.IsEquivalentTo("Portraits/Abigail"))
        e.Edit(asset => asset.AsImage().PatchImage(
            Helper.ModContent.Load<Texture2D>("assets/abigail.png"),
            targetArea: new Rectangle(0, 0, 128, 64), patchMode: PatchMode.Replace));
}
```
- `Helper.ModContent.Load<T>("assets/…")` = files in your mod. `Helper.GameContent.Load<T>("Data/…")` = game assets (after all edits).
- `Helper.GameContent.InvalidateCache("Data/Objects")` to force reload after config changes.
- Data models live in `StardewValley.GameData.*` (Objects, BigCraftables, Crops, FruitTrees, Characters, Locations, Buildings, Shops, Machines, …).

## Items in 1.6
- IDs are strings. Qualified IDs: `(O)` object, `(BC)` big craftable, `(F)` furniture, `(H)` hat, `(S)` shirt, `(P)` pants, `(B)` boots, `(W)` weapon, `(T)` tool, `(TR)` trinket, `(WP)` wallpaper, `(FL)` flooring.
- Create: `ItemRegistry.Create("(O)Me.MyMod_Gem", amount: 1)`. Check: `item.QualifiedItemId == "(O)…"`.
- Give: `Game1.player.addItemByMenuIfNecessary(item)`.
- Conditions: `GameStateQuery.CheckConditions("PLAYER_HAS_SEEN_EVENT Current 123")`.
- Trigger actions run from data (`Data/TriggerActions`) or `TriggerActionManager.TryRunAction("AddMail Current Me.MyMod_Letter", out _, out _)`.

## Config, data, translation
```csharp
public sealed class ModConfig { public bool Enabled { get; set; } = true; public SButton Hotkey { get; set; } = SButton.F5; }
Helper.WriteConfig(Config);
Helper.Data.WriteSaveData("state", myObj);            // per-save, host only
Helper.Data.ReadSaveData<MyState>("state");
Game1.player.modData[$"{ModManifest.UniqueID}/flag"] = "1"; // synced per-object data
Helper.Translation.Get("greeting", new { name = Game1.player.Name });
```

## Generic Mod Config Menu
Copy the API interface (only the members you use) from GMCM's `IGenericModConfigMenuApi.cs`:
```csharp
var gmcm = Helper.ModRegistry.GetApi<IGenericModConfigMenuApi>("spacechase0.GenericModConfigMenu");
if (gmcm is null) return;
gmcm.Register(ModManifest, reset: () => Config = new(), save: () => Helper.WriteConfig(Config));
gmcm.AddBoolOption(ModManifest, name: () => "Enabled", getValue: () => Config.Enabled, setValue: v => Config.Enabled = v);
gmcm.AddKeybind(ModManifest, name: () => "Hotkey", getValue: () => Config.Hotkey, setValue: v => Config.Hotkey = v);
```

## Custom Content Patcher tokens
```csharp
var cp = Helper.ModRegistry.GetApi<IContentPatcherAPI>("Pathoschild.ContentPatcher");
cp?.RegisterToken(ModManifest, "Affection", () => Context.IsWorldReady ? new[] { myValue.ToString() } : null);
```
Packs use it as `{{Me.MyMod/Affection}}` and need `Me.MyMod` in their manifest `Dependencies`.

## Harmony
```csharp
var harmony = new HarmonyLib.Harmony(ModManifest.UniqueID);
harmony.Patch(
    original: AccessTools.Method(typeof(StardewValley.Object), nameof(StardewValley.Object.performObjectDropInAction)),
    prefix: new HarmonyMethod(typeof(ObjectPatches), nameof(ObjectPatches.DropIn_Prefix)));
```
Patch methods are `static`; wrap bodies in try/catch and log via a static `IMonitor`. Prefer postfixes; use prefix-returning-false only when replacing behavior. Decompile game code with ILSpy on `Stardew Valley.dll` to find targets.

## Exposing an API to other mods
Override `public override object GetApi() => new MyApi();` and publish the interface.

## Console commands, logging, multiplayer
```csharp
Helper.ConsoleCommands.Add("mymod_give", "Gives the gem.", (cmd, args) => Game1.player.addItemToInventory(ItemRegistry.Create("(O)Me.MyMod_Gem")));
Monitor.Log("message", LogLevel.Debug);      // Trace, Debug, Info, Warn, Error, Alert
Helper.Multiplayer.SendMessage(payload, "MsgType", modIDs: new[] { ModManifest.UniqueID });
```
Net fields (`NetInt`, `NetString`…): read `.Value`; compare values, not net objects.

## Debugging
- Log: `%AppData%\StardewValley\ErrorLogs\SMAPI-latest.txt`; upload via smapi.io/log.
- `debug` console commands (`debug warp Town 10 10`, `debug time 1200`, `debug friendship Abigail 2500`, `debug ebi <eventId>`, `debug item (O)…`).
- Build errors about game path: set `<GamePath>` in csproj or `stardewvalley.targets` in your user folder.
