# NPCs, dialogue, schedules, events, mail

Wiki pages of record: Modding:NPC data, Modding:Dialogue, Modding:Schedule data, Modding:Event data, Modding:Mail data, Modding:Trigger actions, Modding:Game state queries. Patch-export vanilla assets (`patch export Data/Characters`) to copy exact shapes.

## New NPC (1.6) — minimum set
Internal name: `{{ModId}}_Name` (avoids collisions). Display name via i18n.

```json
{ "Action": "Load", "Target": "Characters/{{ModId}}_Mira", "FromFile": "assets/sprites/Mira.png" },
{ "Action": "Load", "Target": "Portraits/{{ModId}}_Mira",  "FromFile": "assets/portraits/Mira.png" },
{ "Action": "Load", "Target": "Characters/Dialogue/{{ModId}}_Mira", "FromFile": "assets/dialogue/Mira.json" },
{ "Action": "Load", "Target": "Characters/schedules/{{ModId}}_Mira", "FromFile": "assets/schedules/Mira.json" },
{
  "Action": "EditData", "Target": "Data/Characters",
  "Entries": {
    "{{ModId}}_Mira": {
      "DisplayName": "{{i18n:mira.name}}",
      "BirthSeason": "Fall", "BirthDay": 12,
      "HomeRegion": "Town",
      "Gender": "Female", "Age": "Adult",
      "Manner": "Polite", "SocialAnxiety": "Neutral", "Optimism": "Positive",
      "CanBeRomanced": false,
      "Home": [ { "Id": "Default", "Location": "Town", "Tile": { "X": 52, "Y": 70 }, "Direction": "down" } ]
    }
  }
},
{ "Action": "EditData", "Target": "Data/NPCGiftTastes", "Entries": {
    "{{ModId}}_Mira": "{{i18n:mira.gift.love}}/(O)72 (O)395/{{i18n:mira.gift.like}}/-6/{{i18n:mira.gift.dislike}}/(O)330/{{i18n:mira.gift.hate}}/(O)168/{{i18n:mira.gift.neutral}}/"
} }
```
Other `Data/Characters` fields as needed: `Appearance` (list of outfit/sprite/portrait choices with `Season`, `Indoors`/`Outdoors`, `Condition`, `Portrait`, `Sprite`, `Precedence`), `Size` (sprite frame size), `Breather`, `Shadow`, `CanSocialize`, `CanReceiveGifts`, `Calendar`, `SocialTab`, `IntroductionsQuest`, `FriendsAndFamily`, `SpouseRoom`, `SpousePatio`, `SpouseAdopts`, `UnlockConditions`, `SpawnIfMissing`, `TextureName`. Verify field names against the exported vanilla data before using an unfamiliar one.

Romanceable: `"CanBeRomanced": true` + marriage dialogue (`Characters/Dialogue/MarriageDialogue{{ModId}}_Mira`), engagement/marriage strings, spouse room map, 10/14-heart events. Patch-export an existing spouse (e.g. `Characters/Dialogue/MarriageDialogueAbigail`) as the key template.

## Dialogue (`Characters/Dialogue/<Name>`)
Keys (most specific wins): `Introduction`, `<season>_<day>` (`spring_12`), `<DayOfWeek>` (`Mon`), `<season>_<DayOfWeek>`, `<DayOfWeek><hearts>` (`Mon6`), `<location>`/`<location>_<x>_<y>`, `Rain`, `AcceptGift_(O)<id>`, `AcceptBirthdayGift_Positive`/`_Negative`, `danceRejection`, `divorced`, `breakUp`, `GreenRain`, `Resort*`… Verify less common keys against vanilla files.

Inline commands:
- `#$b#` page break; `#$e#` end and continue on next talk
- portrait: `$h $s $u $l $a` or `$N`
- `@` player name; `^` splits male^female text; `%adj%`, `%noun%`, `%place%`… random words
- question: `$q <responseIds> <fallbackKey>#Question text#$r <id> <friendship> <replyKey>#Answer text`
- `$y 'question_answer1_reply1_answer2_reply2'` quick question
- `$p <id>#if-yes|if-no` prior answer branch; `$d <condition>#a|b` world-state branch
- `$query <GSQ>#if true|if false`
- `$action <trigger action>` run a trigger action
- `[(O)72 (O)395]` give the player a random item from the list
Keep every line in i18n: `"Mon": "{{i18n:mira.mon}}"`.

## Schedules (`Characters/schedules/<Name>`)
```json
{
  "spring": "900 Town 47 87 2/1200 Saloon 10 18 2 \"Strings\\schedules\\{{ModId}}_Mira:lunch\"/1800 Town 52 70 2",
  "Mon": "GOTO spring",
  "rain": "800 Town 52 70 2/2000 bed",
  "default": "GOTO spring"
}
```
Entry = `time location x y facing [animation] [\"dialogue key\"]`; facing 0 up, 1 right, 2 down, 3 left. Keys checked in order: specific date, `<season>_<day>`, marriage keys, `rain`, `<season>_<DayOfWeek>`, `<DayOfWeek>`, `<season>`, `spring`, `default`. Dialogue strings referenced go into `Strings/schedules/<Name>` via EditData. Custom animations: `Data/animationDescriptions`.

## Events (`Data/Events/<LocationName>`)
Key = `<eventId>/<preconditions>`, value = script.
```json
{
  "Action": "EditData", "Target": "Data/Events/Town",
  "Entries": {
    "{{ModId}}_MiraIntro/f {{ModId}}_Mira 500/t 900 1600/w sunny": "continue/64 15/farmer 64 16 2 {{ModId}}_Mira 64 18 0/skippable/pause 500/speak {{ModId}}_Mira \"{{i18n:event.intro.1}}\"/emote farmer 8/pause 500/end"
  }
}
```
Script: `<music>/<viewport x y>/<actor x y facing …>/commands…/end`. Common commands: `move <actor> dx dy facing`, `speak`, `emote`, `faceDirection`, `pause`, `fade`, `viewport`, `warp`, `animate`, `playSound`, `addItem`, `friendship`, `mail`, `quickQuestion`, `fork`, `switchEvent`, `end dialogue`, `end warpOut`. 1.6 preconditions also accept `G <game state query>`. Test with `debug ebi <eventId>`.

## Mail
```json
{ "Action": "EditData", "Target": "Data/mail", "Entries": {
  "{{ModId}}_Welcome": "{{i18n:mail.welcome}}%item object 72 1 %%[#]{{i18n:mail.welcome.title}}"
} },
{ "Action": "EditData", "Target": "Data/TriggerActions", "Entries": {
  "{{ModId}}_SendWelcome": { "Id": "{{ModId}}_SendWelcome", "Trigger": "DayStarted",
    "Condition": "PLAYER_HEARTS Current {{ModId}}_Mira 2", "Actions": [ "AddMail Current {{ModId}}_Welcome" ] }
} }
```
Mail text: `^` newline, `%item …%%` attachments, `[#]Title` letter title, `[letterbg N]` background, `[textcolor x]`. Mail Framework Mod is an alternative when the user wants its features (custom letter backgrounds from files, repeating mail with conditions); require it as a dependency.

## Augmenting existing NPCs
- Add dialogue: `EditData` on `Characters/Dialogue/<Name>` with new keys; extend existing lines with `TextOperations` Append.
- Change sprite/portrait: Load replaces; EditImage patches regions; or add an `Appearance` entry via `TargetField: ["<Name>", "Appearance"]`.
- Mod NPCs: use their internal name; depend on their mod.
