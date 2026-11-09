# Content Patcher packs

Docs of record: Pathoschild/StardewMods `ContentPatcher/docs/author-guide.md` (and `author-guide/*.md` per action/token). When unsure of a field, check there or `patch export` the target asset in-game.

## Files
```
[CP] My Mod/
  manifest.json
  content.json
  data/*.json        (Include'd patch files, optional)
  assets/*.png|.tmx|.json
  i18n/default.json  (+ fr.json, de.json…)
```
manifest:
```json
{
  "Name": "My Mod", "Author": "Me", "Version": "1.0.0",
  "Description": "…", "UniqueID": "Me.MyMod",
  "UpdateKeys": [],
  "ContentPackFor": { "UniqueID": "Pathoschild.ContentPatcher" },
  "Dependencies": []
}
```
content.json (`//` comments and trailing commas are allowed):
```json
{
  "Format": "2.7.0",
  "ConfigSchema": {
    "Outfit": { "AllowValues": "Default, Summer", "Default": "Default" },
    "EnableNPC": { "AllowValues": "true, false", "Default": "true" }
  },
  "DynamicTokens": [
    { "Name": "Look", "Value": "base" },
    { "Name": "Look", "Value": "rain", "When": { "Weather": "Rain, Storm" } }
  ],
  "Changes": [
    { "Action": "Include", "FromFile": "data/items.json, data/npc.json" }
  ]
}
```
Use the installed Content Patcher version as `Format`.

## Actions
| Action | Key fields |
|---|---|
| `Load` | `Target`, `FromFile`, `Priority` (`Low`/`Medium`/`High`/`Exclusive`) — creates/replaces a whole asset |
| `EditData` | `Target`, `Entries` {key: value / null to delete}, `Fields` {key: {field: value}}, `TargetField` [path…], `MoveEntries`, `TextOperations` |
| `EditImage` | `Target`, `FromFile`, `FromArea`, `ToArea` {X,Y,Width,Height}, `PatchMode` (`Replace` / `Overlay`) |
| `EditMap` | `Target`, `FromFile`+`ToArea`+`PatchMode` (`Overlay`/`ReplaceByLayer`/`Replace`), `MapProperties`, `MapTiles`, `AddWarps`, `TextOperations` |
| `Include` | `FromFile` (comma-separated list of JSON patch files) |

Common to all: `LogName`, `When` (conditions), `Update` (`OnDayStart` default, `OnLocationChange`, `OnTimeChange`), `Priority` (edits: `Early`/`Default`/`Late` or `+N`), `Enabled`.

## Tokens (most used)
`{{ModId}}`, `{{i18n:key}}`, `{{Season}}`, `{{Day}}`, `{{DayOfWeek}}`, `{{Year}}`, `{{Time}}`, `{{Weather}}`, `{{LocationName}}`, `{{IsOutdoors}}`, `{{Hearts:Name}}`, `{{Relationship:Name}}`, `{{Spouse}}`, `{{HasFlag}}`, `{{HasSeenEvent}}`, `{{HasMod}}`, `{{HasProfession}}`, `{{FarmhouseUpgrade}}`, `{{Random:a, b, c}}`, `{{Query: <expr>}}`, `{{Target}}`, `{{TargetWithoutPath}}`, `{{Lowercase:…}}`, `{{Range:1, 5}}`, `{{Merge:…}}`, config keys `{{Outfit}}`, dynamic tokens `{{Look}}`, other mods' tokens `{{Other.Mod/Token}}`.

Conditions: `"When": { "Season": "Spring, Summer", "Hearts:Abigail": "{{Range:6, 14}}", "HasMod |contains=Other.Mod": "true", "Query: {{Day}} > 14": true }`. Game state queries go in data fields named `Condition` (e.g. `"Condition": "SEASON spring, PLAYER_HEARTS Current Abigail 6"`).

## Patterns

Load a custom texture, add an object:
```json
{ "Action": "Load", "Target": "Mods/{{ModId}}/Objects", "FromFile": "assets/objects.png" },
{
  "Action": "EditData", "Target": "Data/Objects",
  "Entries": {
    "{{ModId}}_Gem": {
      "Name": "{{ModId}}_Gem",
      "DisplayName": "{{i18n:gem.name}}",
      "Description": "{{i18n:gem.description}}",
      "Type": "Basic", "Category": 0, "Price": 250,
      "Texture": "Mods/{{ModId}}/Objects", "SpriteIndex": 0
    }
  }
}
```
Append to a list inside an entry (e.g. a shop):
```json
{
  "Action": "EditData", "Target": "Data/Shops", "TargetField": [ "SeedShop", "Items" ],
  "Entries": { "{{ModId}}_Gem": { "Id": "{{ModId}}_Gem", "ItemId": "(O){{ModId}}_Gem", "Price": 500, "Condition": "SEASON spring" } }
}
```
Seasonal/conditional portrait replacement:
```json
{ "Action": "Load", "Target": "Portraits/Abigail", "FromFile": "assets/abigail_{{Season}}.png" }
```
Partial image edit:
```json
{ "Action": "EditImage", "Target": "Maps/springobjects", "FromFile": "assets/fish.png", "ToArea": { "X": 160, "Y": 80, "Width": 16, "Height": 16 } }
```
Text append:
```json
{ "Action": "EditData", "Target": "Characters/Dialogue/Abigail", "TextOperations": [
  { "Operation": "Append", "Target": [ "Entries", "Mon" ], "Value": "{{i18n:abigail.mon.extra}}", "Delimiter": "#$b#" } ] }
```

## Augmenting other mods
- Target their custom assets by name (`Mods/Other.Mod/Objects`, `Characters/Other.Mod_NPC`) and add `{ "UniqueID": "Other.Mod" }` to your `Dependencies` so you load after them.
- Use `"Priority": "Late"` on edits that must win; `"Priority": "High"` on Loads only when replacing their Load is the goal (two non-Exclusive Loads → higher priority wins).
- Use `HasMod` conditions for optional compatibility patches.

## Debug (SMAPI console)
`patch summary <ModId>`, `patch summary full`, `patch reload <ModId>`, `patch export <Asset> [type]`, `patch parse "{{Season}}"`, `patch invalidate <Asset>`.
