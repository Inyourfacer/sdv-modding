# Items, crops, recipes, shops, machines (1.6)

Wiki of record: Modding:Items, Modding:Crop data, Modding:Fruit trees, Modding:Recipe data, Modding:Shops, Modding:Machines. When a field below is unfamiliar, `patch export Data/<X>` and copy the vanilla shape.

Always: custom IDs `{{ModId}}_Thing`; textures loaded as `Mods/{{ModId}}/<Sheet>`; text via i18n. Sheet sprite index counts left→right, top→bottom on the frame grid.

## Objects — `Data/Objects`
```json
"{{ModId}}_Jam": {
  "Name": "{{ModId}}_Jam", "DisplayName": "{{i18n:jam.name}}", "Description": "{{i18n:jam.desc}}",
  "Type": "Basic", "Category": -26, "Price": 220,
  "Edibility": 30, "IsDrink": false,
  "Buffs": [ { "Id": "Food", "Duration": 600, "CustomAttributes": { "Speed": 1 } } ],
  "Texture": "Mods/{{ModId}}/Objects", "SpriteIndex": 0,
  "ContextTags": [ "color_red", "food_sweet" ]
}
```
Edibility −300 = inedible. Categories: −2 gem, −4 fish, −5 egg, −6 milk, −7 cooking, −8 crafting, −12 mineral, −15 metal, −16 building resource, −26 artisan goods, −27 syrup, −74 seeds, −75 vegetable, −79 fruit, −80 flower, −81 forage.

## Big craftables — `Data/BigCraftables`
```json
"{{ModId}}_Press": { "Name": "{{ModId}}_Press", "DisplayName": "{{i18n:press.name}}", "Description": "{{i18n:press.desc}}",
  "Price": 0, "Fragility": 0, "CanBePlacedOutdoors": true, "CanBePlacedIndoors": true, "IsLamp": false,
  "Texture": "Mods/{{ModId}}/BigCraftables", "SpriteIndex": 0 }
```
16×32 frames.

## Machines — `Data/Machines` (key = qualified ID)
```json
"(BC){{ModId}}_Press": {
  "OutputRules": [ { "Id": "Default",
    "Triggers": [ { "Id": "ItemPlacedInMachine", "Trigger": "ItemPlacedInMachine", "RequiredItemId": "(O)613", "RequiredCount": 1 } ],
    "OutputItem": [ { "Id": "Out", "ItemId": "(O){{ModId}}_Jam" } ],
    "MinutesUntilReady": 600 } ],
  "LoadEffects": [ { "Id": "Sound", "Sounds": [ { "Id": "Ship" } ] } ],
  "WorkingEffects": [ { "Id": "Frames", "Frames": [ 1, 2 ], "Interval": 200 } ]
}
```

## Crops — `Data/Crops` (key = seed object ID)
```json
"{{ModId}}_BerrySeeds": {
  "Seasons": [ "Summer" ], "DaysInPhase": [ 1, 2, 2, 3 ], "RegrowDays": 3,
  "HarvestItemId": "(O){{ModId}}_Berry", "HarvestMinStack": 1, "HarvestMaxStack": 3,
  "Texture": "Mods/{{ModId}}/Crops", "SpriteIndex": 0
}
```
Also add the seed and produce to `Data/Objects` (seed Category −74, Type "Seeds"). Crop sheet: one 128×32 row per crop (spec `crop`). Giant crops: `Data/GiantCrops`.

## Fruit trees — `Data/FruitTrees` (key = sapling ID)
```json
"{{ModId}}_PlumSapling": { "DisplayName": "{{i18n:plum.tree}}", "Seasons": [ "Spring" ],
  "Fruit": [ { "Id": "Plum", "ItemId": "(O){{ModId}}_Plum" } ],
  "Texture": "Mods/{{ModId}}/FruitTrees", "TextureSpriteRow": 0 }
```

## Furniture — `Data/Furniture` (slash string)
`"{{ModId}}_Table": "{{ModId}}_Table/table/2 2/2 1/1/500/-1/{{i18n:table.name}}/0/Mods\\{{ModId}}\\Furniture"`
Fields (checked against the unpacked game: `Oak Chair/chair/-1/-1/4/350/-1/[LocalizedText Strings\\Furniture:OakChair]`): name / type / sprite size in tiles (-1 = default) / bounding box in tiles (-1 = default) / rotations / price / placement restriction (-1 = any) / display name, then optionally sprite index / texture / off-limits-for-random-sale / context tags. The tail fields are not used by vanilla entries; copy one from a mod that uses them.

## Clothing & hats & weapons
- `Data/Shirts`, `Data/Pants`: models with `Texture`, `SpriteIndex`, `CanBeDyed`, `DefaultColor`, `IsPrismatic`.
- `Data/hats`: slash string `name/description/showRealHair/skipHairstyleOffset/tags/displayName` (checked: `Cowboy Hat/<description>/false/true//Cowboy Hat`), with `spriteIndex/texture` appended for custom sheets (not used by vanilla entries).
- `Data/Weapons`: model with `Name`, `DisplayName`, `Description`, `MinDamage`, `MaxDamage`, `Knockback`, `Speed`, `Precision`, `Defense`, `Type` (0 stab, 1 dagger, 2 club, 3 sword), `AreaOfEffect`, `CritChance`, `CritMultiplier`, `Texture`, `SpriteIndex`.
For full outfit/hair/accessory freedom use Fashion Sense (`fashion-sense-alt-textures.md`).

## Recipes
`Data/CookingRecipes`, `Data/CraftingRecipes` (slash strings):
`"{{ModId}}_Jam": "613 3 245 1/10 10/{{ModId}}_Jam/default/{{i18n:jam.name}}"` → ingredients `<id> <count>…` / unused / output id [count] / unlock condition (`default`, `f <NPC> <hearts>`, `s <skill> <level>`, `none`) / display name. Crafting recipes are `ingredients/Home/yield/isBigCraftable/unlock/displayName` (checked: `Chest` = `388 50/Home/130/true/default/`; `Wood Fence` = `388 2/Field/322/false/default/`, where the second field is the crafting location, `Home` or `Field`); for a big craftable the yield is the big-craftable ID. Teach via mail `%item cookingRecipe <key> %%` or trigger action `MarkCookingRecipeKnown`/`MarkCraftingRecipeKnown`.

## Shops — `Data/Shops`
Add with `TargetField: ["<ShopId>", "Items"]` (vanilla IDs: `SeedShop`, `Carpenter`, `Blacksmith`, `Saloon`, `FishShop`, `AnimalShop`, `Hospital`, `Sandy`, `DesertTrade`, `IslandTrade`, `Joja`, `AdventureShop`, `Dwarf`, `Krobus`, `HatMouse`, `Traveler`…). New shop: new key + `Owners` + open it with a map tile `Action OpenShop {{ModId}}_Shop`.

## Gift tastes, context tags, quests
- Universal tastes: `Data/NPCGiftTastes` keys `Universal_Love` etc. (space-separated IDs).
- Context tags for categorizing custom items (`color_*`, `food_*`, `forage_item`, …).
- Special orders: `Data/SpecialOrders`; quests: `Data/Quests`.
